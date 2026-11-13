#!/usr/bin/env python3
"""
flippa-scraper — Playwright edition (primary engine)
=====================================================

Scrapes flippa.com listing pages: any `/search` URL with any combination of
`filter[...]` parameters, and the category shortcuts (`/websites`, `/apps`,
`/domains`, `/buy/sitetype/saas`, ...). No category is hardcoded — what a run
covers is entirely the URL you give it.

Site-specific knowledge in this file is deliberately tiny: the
card selector and card-count threshold below, the readiness wait, and the
module docstring. Everything about WHAT a listing contains lives in
product_parser.py; everything about WHICH ANSWER a page is lives in
page_flow.py, shared with the other two engines so the three cannot drift.

Three things here are specific to this site and worth knowing:

  * **The data is in the served HTML.** Flippa's search page is
    server-rendered: all 50 listing cards are in the first response, with no
    JavaScript needed to produce them (measured 2026-10-14). The readiness
    wait below is therefore a guard against reading a document mid-swap, not
    a wait for an app to paint.

  * **The readiness wait never evaluates a string.** `page.wait_for_function`
    hands the browser a STRING to eval, which a site whose CSP lacks
    `unsafe-eval` refuses — it took a whole run down on another site in this
    family. flippa.com's CSP currently carries only
    `frame-ancestors`, so the eval form WOULD work here today; polling
    through the protocol costs nothing and cannot break when that changes.

  * **Pagination is verified, not assumed.** Page 2 is CONSTRUCTED
    (`?page=2`, the spelling of the site's own next link) and then CHECKED
    against page 1's ids before pages 3..N are planned. Every multi-page run
    in this repo's history before that check returned exactly one page's
    worth of rows and reported success.

Usage
-----
    python3 playwright_scraper.py \\
        --url "https://flippa.com/search?filter%5Bproperty_type%5D=saas" \\
        --pages 3 --format both --out saas_listings

Requires: pip install -r requirements.txt -r requirements-playwright.txt
          then: playwright install chromium   (not needed with --cdp-endpoint)
"""

import argparse
import logging
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse

from playwright.sync_api import (sync_playwright, Error as PWError,
                                 TimeoutError as PWTimeout)

import cli_types
import env_config
import page_flow
from captcha_solver import (INJECT_TOKEN_FN, detect_in_html, detect_in_page,
                            reconcile_detections, solve)
from fingerprint_client import FingerprintError
from output_writer import (EXIT_API_ERROR, failure_stop_reason, finish_run,
                           merge_pages)
from product_parser import (SELECTORS, category_from_url, locale_from_url,
                            page_url, parse_products)
from proxy_pool import (CDP_CONNECT_ATTEMPTS, CDP_CONNECT_PAUSE_S, CDP_CONNECT_TIMEOUT_S,
                        ROTATE_MODES, cdp_refusal_advice, cdp_retryable, ProxyError, ProxyPool,
                        check_exit_or_raise,
                        from_args as proxy_pool_from_args, mask,
                        redact_secret_patterns, to_playwright)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("playwright_scraper")

# --- the whole of this engine's site knowledge -----------------------------
ITEM_CARD_SELECTOR = SELECTORS["item_card"]
# How many cards mean "the grid has rendered". Must be > 1: waiting for one
# match resolves on the first thing that looks like a card long before the
# grid paints. Flippa serves 50 per page, so 5 is comfortably below a full
# page and safely above an accident.
MIN_CARD_MATCHES = 5
# How long to wait for the grid to paint. Not a precondition for data (see the
# module docstring) — it buys the DOM cross-check.
RENDER_WAIT_MS = 15000
# Not followed: pages are constructed with product_parser.page_url and then
# verified against the data, which is what lets --concurrency address them.
NEXT_PAGE_SELECTOR = None
# ---------------------------------------------------------------------------


def _chrome_ua(chromium_version: str) -> str:
    """A desktop-Chrome UA naming the browser's OWN real version.

    Not a hardcoded version: that drifts the moment a newer Chromium ships,
    and a UA claiming an older Chrome than the JS engine and TLS handshake
    report is itself a mismatch a fingerprinter can key on.
    """
    return (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{chromium_version} Safari/537.36")


def _mask_credentials(url: str) -> str:
    """Never print a username:password embedded in a ws:// or http:// URL."""
    return redact_secret_patterns(url)


@dataclass
class PageOutcome:
    """PageOutcome
    """
    page_num: int
    url: str
    final_url: Optional[str] = None
    products: List = field(default_factory=list)
    state: Optional[page_flow.PageState] = None
    load_failed: bool = False
    # The page was classified as carrying listings and the parser still got
    # nothing out of it. page_flow only returns CONTENT when it has counted
    # listing cards in the page, so this is a parser
    # or schema problem — never the end of the listing, which has its own
    # states (EMPTY, EXHAUSTED).
    parse_failed: bool = False
    # The page was taken off the work queue and never came back: its worker
    # died holding it. Recorded as an outcome so the page exists in SOME list
    # rather than in none.
    lost: bool = False

    @property
    def ok(self) -> bool:
        return not self.load_failed and not self.parse_failed and \
            not self.lost and self.state is not None and \
            not self.state.policy.blocked

    @property
    def complete_here(self) -> bool:
        """The listing genuinely ended on this page."""
        return self.state is not None and self.state.policy.complete


# Chromium's own names for "the proxy is the problem, not the site". Matched
# on the error text because Playwright surfaces them as a generic Error.
_PROXY_ERROR_MARKERS = (
    "ERR_PROXY_CONNECTION_FAILED",     # nothing listening / refused
    "ERR_TUNNEL_CONNECTION_FAILED",    # CONNECT rejected by the proxy
    "ERR_PROXY_AUTH_UNSUPPORTED",      # auth scheme we cannot satisfy
    "ERR_PROXY_AUTH_REQUESTED",        # credentials missing or wrong
    "ERR_UNEXPECTED_PROXY_AUTH",
    "ERR_PROXY_CERTIFICATE_INVALID",
)


def _proxy_failure(exc) -> str:
    """The Chromium proxy-error name in `exc`, or "" if it is not one.

    A dead proxy and a timeout want opposite responses — a different exit
    versus another try at the same one — and catching only the timeout type
    let this escape as a traceback the first time anyone pointed --proxy-file
    at a real list.
    """
    text = str(exc)
    return next((m for m in _PROXY_ERROR_MARKERS if m in text), "")


def _launch_local(pw, args, pool):
    """Launch our own Chromium on `pool`'s current exit; return (browser, context, page).

    A rotation tears this down and calls it again rather than swapping the
    proxy under a live session: cookies a bot manager issued against exit A,
    replayed from exit B, are a stronger signal than either address alone.
    """
    launch_kwargs = {"headless": args.headless}
    proxy = to_playwright(pool.current) if pool else None
    if proxy:
        launch_kwargs["proxy"] = proxy
        logger.info("Using proxy exit %s", mask(pool.current))

    browser = pw.chromium.launch(**launch_kwargs)
    ctx_kwargs = {"user_agent": _chrome_ua(browser.version), "locale": "en-US"}
    init_script = None
    if args.fingerprint:
        # Only meaningful on this branch: over --cdp-endpoint the Scraping
        # Browser brings its own fingerprint and stacking a second one on top
        # is a contradiction, not better cover.
        from fingerprint_client import (get_fingerprint, playwright_context_kwargs,
                                        playwright_init_script)
        fp = get_fingerprint(args.twocaptcha_key, tags=args.fp_tags,
                             country=args.fp_country)
        ctx_kwargs.update(playwright_context_kwargs(fp))
        init_script = playwright_init_script(fp)
        logger.info("Using 2captcha fingerprint %s (%s)", fp.get("id"), fp.get("country"))

    context = browser.new_context(**ctx_kwargs)
    if init_script:
        # Must be installed on the context, before any page script runs.
        context.add_init_script(init_script)
    return browser, context, context.new_page()


def _connect_remote(pw, args):
    """Attach to an already-running browser over CDP; return (browser, context, page)."""
    logger.info("Connecting to existing browser over CDP: %s",
                _mask_credentials(args.cdp_endpoint))
    # An explicit timeout, stated rather than inherited: the pyppeteer twin
    # has no connect timeout of its own and had to grow one by hand.
    #
    # And the connect is WRAPPED, because Playwright puts the endpoint — with
    # its password — into the exception message AND into a four-line call log
    # underneath it. Measured 2026-09-19 against a real endpoint that answered
    # 401: the password appeared five times in one traceback. An exception
    # message is a log.
    #
    # Retried per proxy_pool's CDP policy: a profile stays locked for ~2 s
    # after a clean disconnect (measured 2026-09-24), so a run started right
    # after another met HTTP 500. A 401 (expired credentials) is not retried.
    for attempt in range(1, CDP_CONNECT_ATTEMPTS + 1):
        try:
            browser = pw.chromium.connect_over_cdp(args.cdp_endpoint, timeout=30000)
            break
        except Exception as e:  # noqa: BLE001 — re-raised immediately, redacted
            # Whole message, on one line: the endpoint's host:port is what
            # says WHICH exit failed, and it sits past the first line.
            text = " ".join(redact_secret_patterns(str(e)).split())[:600]
            if attempt < CDP_CONNECT_ATTEMPTS and cdp_retryable(text):
                logger.warning("Scraping Browser connect failed (%s); retrying in %.0fs "
                               "[%d/%d].", text, CDP_CONNECT_PAUSE_S, attempt,
                               CDP_CONNECT_ATTEMPTS)
                time.sleep(CDP_CONNECT_PAUSE_S)
                continue
            raise RuntimeError(f"Could not connect to --cdp-endpoint: {text} — "
                               f"{cdp_refusal_advice(text)}") from None
    # Reuse the remote browser's existing context so its fingerprint, session
    # and exit stay intact.
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.new_page()

    # https://2captcha.com/scraper/browser-api/api — a real CDP domain that
    # solves reCAPTCHA, Turnstile and more inside the browser, but only once
    # it is explicitly enabled for the session. Treat Captcha.solveFinished as
    # the success signal and keep this module's own detect+solve as fallback.
    try:
        cdp = context.new_cdp_session(page)
        cdp.send("Captcha.setAutoSolve", {"autoSolve": True, "options": [{"type": "*"}]})
        cdp.on("Captcha.detected", lambda *_: logger.info("[Scraping Browser] captcha detected."))
        cdp.on("Captcha.waitForSolve", lambda *_: logger.info("[Scraping Browser] captcha sent for solving."))
        cdp.on("Captcha.solveFinished", lambda *_: logger.info("[Scraping Browser] captcha solved."))
        cdp.on("Captcha.solveFailed", lambda *_: logger.warning("[Scraping Browser] auto-solve failed."))
        logger.info("Scraping Browser API Captcha.setAutoSolve enabled.")
    except Exception as e:  # noqa: BLE001 — any non-2Captcha CDP endpoint lands here
        logger.info("Captcha.setAutoSolve is not available on this "
                    "--cdp-endpoint (%s) — relying on this project's own "
                    "detect+solve instead.", redact_secret_patterns(str(e)))
    return browser, context, page


class _BrowserSession:
    """_BrowserSession
    """

    def __init__(self, pw, args, pool, remote: bool = False):
        self.pw, self.args, self.pool, self.remote = pw, args, pool, remote
        self.browser = self.context = self.page = None

    def open(self):
        if self.remote:
            self.browser, self.context, self.page = _connect_remote(self.pw, self.args)
        else:
            self.browser, self.context, self.page = _launch_local(
                self.pw, self.args, self.pool)
        return self

    def relaunch(self):
        """Tear the browser down and come back on the pool's current exit.

        On a remote browser this is a no-op — its exit is not ours to change.
        """
        if self.remote:
            return
        try:
            self.browser.close()
        except Exception as e:  # noqa: BLE001 — teardown must not mask the real reason
            logger.debug("Ignoring error while closing browser for rotation: %s", e)
        self.open()

    def close(self):
        try:
            if self.remote:
                self.page.close()   # leave the remote browser running
            else:
                self.browser.close()
        except Exception as e:  # noqa: BLE001
            logger.debug("Ignoring error during browser teardown: %s", e)


def _content_when_settled(page, attempts: int = 4, pause_ms: int = 700):
    """page.content() that tolerates a page mid-navigation.

    Playwright raises "Unable to retrieve content because the page is
    navigating" if the document swaps under it — a client-side redirect or a
    Turbo visit can land exactly on the snapshot taken right after goto(). Returns
    None if the page will not hold still, so the caller can skip this step
    instead of failing the run.
    """
    for attempt in range(1, attempts + 1):
        try:
            return page.content()
        except PWError as e:
            if "navigating" not in str(e).lower():
                raise
            if attempt == attempts:
                logger.warning("Page kept navigating through %d attempts.", attempts)
                return None
            page.wait_for_timeout(pause_ms)
    return None


def _wait_for_cards(page, timeout_ms: int = RENDER_WAIT_MS) -> int:
    """Wait for the rendered grid, WITHOUT evaluating a string.

    `page.locator(...).count()` goes through the protocol, so it works under
    any Content-Security-Policy — `wait_for_function` would hand the browser a
    string to eval and a site without `unsafe-eval` refuses it outright.

    Returns the number of cards seen. Not reaching MIN_CARD_MATCHES is not a
    failure here: Flippa's data is in the served HTML either way.
    """
    deadline = time.monotonic() + timeout_ms / 1000.0
    count = 0
    while time.monotonic() < deadline:
        try:
            count = page.locator(ITEM_CARD_SELECTOR).count()
        except PWError as e:
            logger.debug("Counting cards failed (%s) — retrying.", e)
            count = 0
        if count > MIN_CARD_MATCHES:
            return count
        page.wait_for_timeout(400)
    return count


def handle_captcha_if_present(page, args, budget: page_flow.SolveBudget,
                              status_code: Optional[int] = None) -> bool:
    """Runs after EVERY navigation, for ANY page — not scoped to one URL.

    Every purchase goes through `budget`, the page's one allowance, checked
    before the solver is called. Returns True when the page was reloaded, so
    the caller knows the status it holds belongs to the previous document.

    Both detectors run and are reconciled; neither short-circuits the other.
    A challenge configured in JavaScript never appears in the served markup,
    and a challenge in the markup can be one the live loader contradicts.
    """
    html = _content_when_settled(page)
    if html is None:
        return False
    challenge = reconcile_detections(
        detect_in_html(html, page.url),
        detect_in_page(lambda js: page.evaluate(js), page_url=page.url))
    if not challenge:
        return False

    # Detected is not blocking. Flippa renders Turnstile on its account forms,
    # not on listings, so a detection on a page whose listings are already
    # here guards nothing. Counting what is already on the page is instant —
    # no readiness wait — which is why this check can sit here rather than
    # forcing a 15s wait on a page a captcha genuinely gates.
    state = page_flow.classify(html, status_code=status_code, url=page.url)
    if args.solve_captcha == "when-blocked" and not state.policy.may_solve:
        logger.info("%s detected via %s, but the page is %s — not paying to "
                    "solve it. Pass --solve-captcha always to solve anyway.",
                    challenge.kind, challenge.source, state)
        return False

    logger.warning("%s detected via %s (sitekey=%s) — attempting to solve.",
                   challenge.kind, challenge.source, challenge.sitekey)

    # A captcha this run cannot solve must not take the run down with it: the
    # listings may well be readable anyway, and a traceback in place of them
    # is strictly worse than a warning.
    if not args.twocaptcha_key:
        logger.warning("No 2captcha API key, so this challenge cannot be solved "
                       "— continuing with whatever the page already holds. The "
                       "run reports exit 3 if it really was blocking.")
        return False
    if not budget.spend():
        logger.warning("%s still present, but this page has already used its "
                       "%d paid solve(s) — not buying another.",
                       challenge.kind, budget.limit)
        return False
    try:
        token = solve(challenge, args.twocaptcha_key,
                      api_version=args.captcha_api, min_score=args.min_score)
    except Exception as e:  # noqa: BLE001 — a solver failure is not a crash
        logger.error("Solving the challenge failed (%s) — continuing with "
                     "whatever the page holds.", redact_secret_patterns(str(e)))
        return False

    page.evaluate(INJECT_TOKEN_FN, token)
    if state.policy.blocked:
        # A challenge that was standing between this run and the content: the
        # reload is what makes the site hand over the page, because the token
        # travels in the cookie the challenge sets.
        logger.info("Token injected. Reloading page to continue.")
        page.wait_for_timeout(1500)
        page.reload(wait_until="domcontentloaded", timeout=60000)
        return True
    else:
        # Measured on 2026-09-19 against flippa.com/signup, which carries a
        # real Turnstile: reloading here THROWS THE TOKEN AWAY, because a form
        # page reads it from the field at submit time rather than from a
        # cookie. Solving a form's captcha buys nothing for a scraper that
        # never submits forms — which this one never does — so the token is
        # left in the field instead of being spent and discarded.
        logger.info("Token injected and left in the page's own response field. "
                    "This page was not blocked, so it is NOT reloaded — a "
                    "reload would discard the token, and nothing here submits "
                    "a form.")
        return False


def _fetch_one_page(session, args, pool, page_num: int, url: str) -> PageOutcome:
    """Fetch, classify and parse one page.

    Never raises for an EXPECTED failure — a timeout, a challenge, a dead exit
    are all recorded on the outcome instead, because what the run should do
    about them differs between the sequential and concurrent paths.

    Always goes through `session.page`, never a captured local: a rotation
    replaces browser, context and page together.
    """
    outcome = PageOutcome(page_num=page_num, url=url)

    # How many times a blocked page may be retried from a DIFFERENT exit. Zero
    # without a pool: there is nowhere else to go, and a bare retry from the
    # same address just burns it further.
    block_retries = args.proxy_block_retries if (pool and len(pool) > 1) else 0
    html, state, load_failed = None, None, False
    # One allowance for the whole page: not per attempt, not per exit.
    budget = page_flow.SolveBudget()

    for block_attempt in range(block_retries + 1):
        logger.info("Fetching page %d/%d: %s", page_num, args.pages, url)
        load_failed, exit_failed, status = False, None, None
        for attempt in range(1, args.retries + 1):
            try:
                response = session.page.goto(url, wait_until="domcontentloaded",
                                             timeout=60000)
                # The HTTP status is the one signal a refusal page with no
                # vendor marker gives; page_flow reads it only when the page
                # carries no listings.
                status = response.status if response is not None else None
                load_failed = False
                break
            except (PWTimeout, PWError) as e:
                reason = _proxy_failure(e)
                if reason:
                    exit_failed, load_failed = reason, True
                    break   # a different exit is the only thing that helps
                load_failed = True
                if attempt < args.retries:
                    pause = args.retry_delay * (2 ** (attempt - 1))
                    logger.warning("Timeout loading %s (attempt %d/%d) — retrying "
                                   "in %.1fs.", url, attempt, args.retries, pause)
                    time.sleep(pause)

        if exit_failed and block_attempt < block_retries:
            logger.warning("Exit %s is unusable (%s) — rotating (%d/%d).",
                           mask(pool.current), exit_failed, block_attempt + 1,
                           block_retries)
            pool.advance(f"unusable exit: {exit_failed}")
            session.relaunch()
            continue
        if exit_failed:
            # Say WHICH failure this was. Chromium reports a dead proxy as a
            # generic error, not a timeout, and the two want opposite
            # responses — "gave up loading" alone sends the reader looking at
            # the site when the exit is what is broken.
            logger.error("The proxy exit %s refused the connection (%s), and "
                         "there is no other exit to try. This is the exit, not "
                         "the site: check the entry, or pass --proxy-file with "
                         "more than one.", mask(pool.current) if pool else "(none)",
                         exit_failed)
        if load_failed:
            break

        if handle_captcha_if_present(session.page, args, budget, status):
            status = None   # the reload replaced the document it described
        cards = _wait_for_cards(session.page)
        html = _content_when_settled(session.page) or ""
        state = page_flow.classify(html, status_code=status, url=session.page.url)
        logger.info("Page %d is %s (%d card(s) rendered).", page_num, state, cards)

        if state.state == page_flow.UNPAINTED and state.policy.wait_first:
            # Served but carrying no listing data: waiting is what helps, and
            # a reload would throw the wait away. One more look after the wait
            # before deciding.
            session.page.wait_for_timeout(RENDER_WAIT_MS)
            html = _content_when_settled(session.page) or html
            state = page_flow.classify(html, status_code=status, url=session.page.url)
            logger.info("After waiting, page %d is %s.", page_num, state)

        if not state.policy.rotate_exit:
            break
        if block_attempt < block_retries:
            logger.warning("Blocked on page %d from %s (%s) — retrying from "
                           "another exit (%d/%d).", page_num, mask(pool.current),
                           state.reason, block_attempt + 1, block_retries)
            pool.advance(f"blocked on page {page_num}")
            session.relaunch()

    if load_failed:
        logger.error("Gave up loading %s after %d attempt(s).", url, args.retries)
        outcome.load_failed = True
        return outcome

    outcome.state = state
    outcome.final_url = session.page.url

    # Dumping on success too, not only on failure: a run can return the right
    # COUNT with a column silently unpopulated, and then the exact bytes are
    # the only way to tell a parsing bug from a too-early snapshot.
    if args.dump_html:
        dump_path = (args.dump_html if args.pages == 1
                     else f"{args.dump_html}.page{page_num}")
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("Saved the snapshot the parser sees to %s (%d bytes).",
                    dump_path, len(html))

    if state.policy.blocked:
        _dump_debug(session.page, args, page_num, html)
        logger.error("Blocked before parsing on page %d (%s) — this is exit 3, "
                     "distinct from a query that genuinely matches nothing "
                     "(exit 4).", page_num, state.reason)
        return outcome

    if state.state in (page_flow.EMPTY, page_flow.EXHAUSTED):
        logger.info("Page %d: %s — nothing further to fetch.", page_num, state.reason)
        return outcome

    products = parse_products(html, session.page.url, category=args.category,
                              page=page_num)
    logger.info("Parsed %d listing(s) from page %d.", len(products), page_num)
    short = page_flow.shortfall(state.total_results, page_num, len(products))
    if short:
        logger.warning("%s.", short)
    if not products:
        _dump_debug(session.page, args, page_num, html)
        # Not "the listing ended here". page_flow classifies the end of a
        # listing as EMPTY or EXHAUSTED and both returned above; reaching this
        # line means the page HAD listing data and this code could not read
        # it. Treating it as the end is how a schema change becomes a
        # successful-looking run holding half the catalogue.
        outcome.parse_failed = True
        logger.error("0 listings parsed from a page classified as %s (%s) — "
                     "that is a parse failure, not the end of the listing. "
                     "Saved what the browser actually saw.",
                     state.state, state.reason)
    outcome.products = products
    return outcome


def _dump_debug(page, args, page_num: int, html: Optional[str]) -> None:
    debug_html = f"{args.out}_page{page_num}_debug.html"
    with open(debug_html, "w", encoding="utf-8") as f:
        f.write(html or "")
    try:
        page.screenshot(path=f"{args.out}_page{page_num}_debug.png", full_page=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not capture screenshot: %s", e)
    logger.warning("Wrote %s (and a .png beside it).", debug_html)


def _worker_pool(pool, worker_index: int):
    """A private ProxyPool for one worker, starting at a different exit.

    Each worker gets its OWN pool object holding the same exits rotated to a
    different offset, so workers start on distinct exits and no thread needs a
    lock: the concurrency is safe by construction rather than by discipline.
    """
    if not pool:
        return None
    proxies = pool.proxies
    offset = worker_index % len(proxies)
    return ProxyPool(proxies[offset:] + proxies[:offset], rotate="per-run")


def _fetch_pages_concurrently(args, pool, specs, concurrency: int):
    """Fetch `specs` [(page_num, url), ...] across `concurrency` workers.

    Each worker owns its own Playwright instance, browser and exit: with the
    sync API a browser belongs to the thread that made it, so sharing one
    across threads is not an option even if it were desirable.
    """
    work = queue.Queue()
    for spec in specs:
        work.put(spec)

    results = []
    results_lock = threading.Lock()
    # The page numbers that came back empty. Which one was LOWEST decides
    # whether the pages still in the queue were skipped legitimately.
    empty_pages = []
    # Set when a page comes back past the end of the listing. Without it,
    # asking for 50 pages of a 5-page search would fetch 45 empty ones.
    exhausted = threading.Event()

    def worker(index: int):
        name = f"worker-{index + 1}"
        try:
            with sync_playwright() as pw:
                session = _BrowserSession(pw, args, _worker_pool(pool, index)).open()
                try:
                    first = True
                    while not exhausted.is_set():
                        try:
                            page_num, url = work.get_nowait()
                        except queue.Empty:
                            break
                        if not first:
                            time.sleep(args.delay)
                        first = False
                        try:
                            outcome = _fetch_one_page(session, args, session.pool,
                                                      page_num, url)
                        except Exception:  # noqa: BLE001
                            # get_nowait already removed this page from the
                            # queue. Letting the exception out of the loop, as
                            # this used to, left the page in no list at all:
                            # not in results, not in unattempted, not in
                            # pages_failed — and a run that lost a page
                            # reported itself complete.
                            logger.exception(
                                "[%s] page %d raised — recording it as a failed "
                                "page and retiring this worker.", name, page_num)
                            lost = PageOutcome(page_num=page_num, url=url)
                            lost.lost = True
                            with results_lock:
                                results.append(lost)
                            break
                        with results_lock:
                            results.append(outcome)
                        if outcome.ok and not outcome.products:
                            logger.info("[%s] page %d returned no listings — "
                                        "treating that as the end of the listing "
                                        "and stopping dispatch.", name, page_num)
                            with results_lock:
                                empty_pages.append(page_num)
                            exhausted.set()
                finally:
                    session.close()
        except Exception:  # noqa: BLE001 — a dead worker must not hang the run
            logger.exception("[%s] died; any page it was holding is reconciled "
                             "into the results below, and whatever is still "
                             "queued is reported unattempted.", name)

    threads = [threading.Thread(target=worker, args=(i,), name=f"page-worker-{i + 1}")
               for i in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Anything still queued was never attempted. Not reported as failed: they
    # were not tried, and claiming otherwise would overstate the damage.
    unattempted = []
    while True:
        try:
            unattempted.append(work.get_nowait()[0])
        except queue.Empty:
            break

    # Every page was asked for, so every page must be in exactly one of the
    # three lists. This reconciliation is the backstop for the per-page
    # handler above: a page that is in none of them is manufactured here as a
    # failure rather than quietly rounding the run down to the pages that
    # happened to survive.
    by_page = dict(specs)
    accounted = {o.page_num for o in results} | set(unattempted)
    for page_num in sorted(set(by_page) - accounted):
        logger.error("Page %d left the queue and never came back — recording it "
                     "as a failed page.", page_num)
        lost = PageOutcome(page_num=page_num, url=by_page[page_num])
        lost.lost = True
        results.append(lost)

    return (results, sorted(unattempted), exhausted.is_set(),
            min(empty_pages) if empty_pages else None)


def _addressable(first: PageOutcome, second: PageOutcome) -> bool:
    """Did the constructed page-2 URL actually reach page 2?

    The check the family's most expensive bug calls for, in the
    form that does not trust markup: the comparison is against the DATA. If page
    2 carries nothing page 1 did not already have, the page parameter did not
    work and pages 3..N cannot be addressed either — which is exactly what
    happened here once, when a page parameter the site ignored made every
    "3-page" run return one page of rows and report success.
    """
    if not second.ok or not second.products:
        return False
    first_ids = {p.sku for p in first.products if p.sku}
    fresh = [p for p in second.products if p.sku and p.sku not in first_ids]
    return bool(fresh)


def scrape(args) -> int:
    outcomes: List[PageOutcome] = []
    blocked = False
    stop_reason = "completed"
    total_results = None
    addressable = None

    pool = proxy_pool_from_args(args)
    if pool and args.cdp_endpoint:
        logger.warning("Ignoring --proxy/--proxy-file: with --cdp-endpoint the "
                       "remote browser has its own exit, and layering a second "
                       "proxy on top would contradict it.")
        pool = None
    # One small request through the exit before a browser is launched. A
    # rotated password otherwise surfaces as three 60s navigation timeouts per
    # page with nothing naming the proxy — measured 2026-09-21.
    check_exit_or_raise(pool, args.url)

    concurrency = max(1, args.concurrency)
    if concurrency > 1:
        if args.cdp_endpoint:
            logger.warning("--concurrency is ignored with --cdp-endpoint: the "
                           "Scraping Browser API allows one live connection per "
                           "profile, so workers collide (profile_locked). Use "
                           "several pids, one run each.")
            concurrency = 1
        elif not pool:
            logger.warning("--concurrency %d with no proxy pool: every worker "
                           "leaves from the SAME address, which is a faster way "
                           "to get that address scored than to gather data. Pass "
                           "--proxy-file to spread the load.", concurrency)
        if pool and pool.rotates_per_page():
            logger.info("--proxy-rotate per-page is redundant under "
                        "--concurrency: each worker already holds its own exit.")
        if concurrency > 8:
            logger.warning("--concurrency %d means %d browsers at once "
                           "(~150-300MB each).", concurrency, concurrency)

    session = None
    with sync_playwright() as pw:
        session = _BrowserSession(pw, args, pool,
                                  remote=bool(args.cdp_endpoint)).open()
        try:
            # Page 1 alone: its content decides whether the rest exist at all.
            first = _fetch_one_page(session, args, pool, 1, args.url)
            outcomes.append(first)
            if first.state is not None:
                total_results = first.state.total_results

            if not first.ok:
                stop_reason = failure_stop_reason(first)
                blocked = bool(first.state and first.state.policy.blocked)
            elif first.complete_here:
                stop_reason = ("no_results" if first.state.state == page_flow.EMPTY
                               else "listing_exhausted")
            elif args.pages > 1:
                # Page 2 is fetched sequentially whatever --concurrency says:
                # it is what proves pages can be addressed by URL at all.
                second = _fetch_one_page(session, args, pool, 2, page_url(args.url, 2))
                outcomes.append(second)
                addressable = _addressable(first, second)

                if not second.ok:
                    stop_reason = failure_stop_reason(second)
                    blocked = bool(second.state and second.state.policy.blocked)
                elif second.complete_here or not second.products:
                    stop_reason = "listing_exhausted"
                elif not addressable:
                    # The constructed URL came back with page 1's listings.
                    # Stopping and SAYING so is the whole point: this is the
                    # failure that reports a complete run holding one page.
                    logger.error(
                        "Page 2 (%s) returned nothing that page 1 did not "
                        "already have, so this listing cannot be paged through "
                        "by URL. Stopping at page 1 and reporting a PARTIAL "
                        "run rather than a complete-looking one.",
                        page_url(args.url, 2))
                    stop_reason = "pagination_not_addressable"
                elif args.pages > 2:
                    rest = list(range(3, args.pages + 1))
                    specs = [(n, page_url(args.url, n)) for n in rest]
                    if concurrency > 1:
                        session.close()
                        session = None
                        logger.info("Fetching pages 3-%d across %d workers%s.",
                                    args.pages, concurrency,
                                    f" over {len(pool)} exit(s)" if pool else "")
                        more, unattempted, ran_out, empty_at = (
                            _fetch_pages_concurrently(args, pool, specs,
                                                      concurrency))
                        outcomes.extend(more)
                        failed = [o for o in more if not o.ok]
                        if failed:
                            worst = min(failed, key=lambda o: o.page_num)
                            stop_reason = failure_stop_reason(worst)
                            blocked = any(o.state and o.state.policy.blocked for o in more)
                        elif ran_out:
                            # Dispatch stops the moment ANY worker reaches the
                            # end of the listing, and workers do not finish in
                            # page order. Pages numbered BELOW the empty one
                            # may still have been sitting in the queue, and
                            # those hold rows — skipping them is a gap, not an
                            # exhausted listing.
                            gap = [n for n in unattempted
                                   if empty_at is None or n < empty_at]
                            if gap:
                                logger.error(
                                    "Page %s came back empty and stopped "
                                    "dispatch, but page(s) %s were never "
                                    "fetched and come BEFORE it — this is a "
                                    "gap, not the end of the listing.",
                                    empty_at, ", ".join(str(n) for n in gap))
                                stop_reason = "pages_unattempted"
                            else:
                                stop_reason = "listing_exhausted"
                        elif unattempted:
                            stop_reason = "pages_unattempted"
                    else:
                        seen = {p.sku for o in outcomes for p in o.products if p.sku}
                        for page_num, url in specs:
                            if pool and pool.rotates_per_page():
                                pool.advance(f"per-page rotation, page {page_num}")
                                session.relaunch()
                            time.sleep(args.delay)
                            outcome = _fetch_one_page(session, args, pool, page_num, url)
                            outcomes.append(outcome)
                            if not outcome.ok:
                                stop_reason = failure_stop_reason(outcome)
                                blocked = bool(outcome.state and outcome.state.policy.blocked)
                                break
                            if outcome.complete_here or not outcome.products:
                                stop_reason = "listing_exhausted"
                                break
                            fresh = [p for p in outcome.products
                                     if p.sku is None or p.sku not in seen]
                            seen.update(p.sku for p in outcome.products if p.sku)
                            # A page that contributes nothing new means the end
                            # of the listing — or pagination looping back on
                            # itself. Either way there is nothing further to
                            # fetch, and this is a property of the DATA.
                            if not fresh:
                                logger.info("Page %d added nothing not already "
                                            "seen — treating that as the end of "
                                            "the listing.", page_num)
                                stop_reason = "no_new_listings"
                                break
        finally:
            if session is not None:
                session.close()

    # Merge once, in PAGE order — not in the order pages happened to finish.
    all_products, merge_stats = merge_pages(
        (o.page_num, o.products) for o in outcomes)
    if merge_stats.duplicate_skus_across_pages:
        logger.info("Dropped %d listing(s) already seen on an earlier page "
                    "(page(s) %s). Recorded in the metadata: a repeat means "
                    "the catalogue shifted under the run.",
                    merge_stats.duplicate_skus_across_pages,
                    ", ".join(str(n) for n in merge_stats.duplicate_pages))

    ok_pages = [o for o in outcomes if o.ok]
    failed_pages = [o.page_num for o in outcomes if not o.ok]
    missing_pages = [o.page_num for o in outcomes if o.lost]
    final_url = (max(ok_pages, key=lambda o: o.page_num).final_url
                 if ok_pages else args.url)
    # Flippa's own match count, as of the run's first page and its last. A
    # change between them says the catalogue was edited mid-run — the one
    # signal that also catches a DELETION, which leaves no duplicate behind.
    counted = [o.state.total_results for o in sorted(outcomes, key=lambda o: o.page_num)
               if o.state is not None and o.state.total_results is not None]

    return finish_run(all_products, args.out, args.format, args.allow_empty,
                      blocked=blocked, stop_reason=stop_reason,
                      pages_requested=args.pages, pages_completed=len(ok_pages),
                      pages_failed=failed_pages, total_results=total_results,
                      addressable=addressable, pages_missing=missing_pages,
                      merge_stats=merge_stats,
                      total_results_first=counted[0] if counted else None,
                      total_results_last=counted[-1] if counted else None,
                      start_url=args.url, final_url=final_url)


def parse_args():
    p = argparse.ArgumentParser(description="Flippa scraper (Playwright edition)")
    p.add_argument("--url", default=None,
                   help="A flippa.com listing URL: /search with any filter[...] "
                        "parameters, or a category shortcut such as /websites. "
                        "Required unless FLIPPA_URL is set in the environment "
                        "or in .env.")
    p.add_argument("--category", default=None,
                   help="Label to tag output rows with. Defaults to what the URL "
                        "itself says, so the column is never empty just because "
                        "the flag was omitted.")
    p.add_argument("--pages", type=cli_types.positive_int, default=1, help="Number of pages to fetch")
    p.add_argument("--delay", type=cli_types.non_negative_float, default=2.0, help="Delay between pages, seconds")
    p.add_argument("--concurrency", type=cli_types.positive_int, default=1, metavar="N",
                   help="Fetch pages 3..N through N parallel workers (default 1). "
                        "Each worker runs its own browser and holds its own proxy "
                        "exit. Pages 1 and 2 are always fetched alone — page 2 is "
                        "what proves the listing can be paged through by URL. "
                        "Ignored with --cdp-endpoint.")
    p.add_argument("--retries", type=cli_types.positive_int, default=3,
                   help="Attempts per page load before giving up (default 3); the "
                        "pause between attempts doubles each time.")
    p.add_argument("--retry-delay", type=cli_types.non_negative_float, default=2.0,
                   help="Seconds before the first page-load retry (default 2.0)")
    p.add_argument("--format", choices=["json", "csv", "both"], default="both")
    p.add_argument("--out", default="flippa_listings", help="Output file prefix")
    p.add_argument("--proxy", default=None,
                   help="Proxy URL, e.g. http://ACCOUNT:PASSWORD@HOST:9999 "
                        "(2captcha.com/proxy)")
    p.add_argument("--proxy-file", default=None,
                   help="File with one proxy URL per line to rotate across. Wins "
                        "over --proxy.")
    p.add_argument("--proxy-rotate", choices=list(ROTATE_MODES), default="per-run",
                   help="per-run (default): one exit for the whole run. per-page: "
                        "a new exit per page, relaunching the browser each time so "
                        "the session does not follow the IP around.")
    p.add_argument("--proxy-shuffle", action="store_true",
                   help="Shuffle the pool at startup, so concurrent runs do not all "
                        "begin on the first exit in the file.")
    p.add_argument("--proxy-block-retries", type=cli_types.non_negative_int, default=2,
                   help="When a page comes back blocked, retry it from this many "
                        "OTHER exits before giving up (default 2).")
    p.add_argument("--twocaptcha-key", default=None, help="2captcha.com API key")
    p.add_argument("--captcha-api", choices=["v2", "v1"], default="v2",
                   help="Which 2captcha solver API to use. v2 is the current JSON "
                        "API (api.2captcha.com/createTask); v1 is the legacy "
                        "in.php/res.php pair.")
    p.add_argument("--solve-captcha", choices=["when-blocked", "always"],
                   default="when-blocked",
                   help="when-blocked (default): only pay to solve a challenge if "
                        "the listings are not already readable — Flippa renders "
                        "Turnstile on its account forms, not on listing pages. "
                        "always: solve whenever one is detected.")
    p.add_argument("--min-score", type=float, default=0.7,
                   help="reCAPTCHA v3 minimum score to request (0.3, 0.7 or 0.9). "
                        "Ignored for Turnstile and v2 widgets.")
    p.add_argument("--allow-empty", action="store_true",
                   help="Write output files even when 0 listings were found. Off by "
                        "default so a failed run cannot overwrite a good result "
                        "with an empty one; the exit code is 4 either way.")
    p.add_argument("--fingerprint", action="store_true",
                   help="Fetch a fingerprint from 2captcha's Fingerprint API and "
                        "apply it to the launched browser. Needs --twocaptcha-key. "
                        "Ignored with --cdp-endpoint.")
    p.add_argument("--fp-tags", default="Windows",
                   help="ONE OS-family tag for the Fingerprint API (default: "
                        "Windows). A list is rejected with HTTP 400.")
    p.add_argument("--fp-country", default=None,
                   help="Fingerprint country, ISO 3166-1 alpha-2. Match it to your "
                        "proxy's exit country — a US fingerprint on a German IP is "
                        "a contradiction.")
    p.add_argument("--cdp-endpoint", default=None,
                   help="Connect to an already-running browser over CDP instead of "
                        "launching Playwright's Chromium, e.g. the Scraping Browser "
                        "API endpoint. --proxy, --fingerprint and "
                        "--headless/--headful are ignored when this is set.")
    p.add_argument("--dump-html", default=None, metavar="PATH",
                   help="Save the exact HTML the parser is given, on success as "
                        "well as failure.")
    p.add_argument("--headless", action="store_true", default=True)
    p.add_argument("--headful", dest="headless", action="store_false")
    args = p.parse_args()
    # Fill --twocaptcha-key / --cdp-endpoint / --proxy / --url from the
    # environment or .env when the flag was not given. An explicit flag wins.
    env_config.apply(args)
    if not args.url:
        p.error("no --url given, and FLIPPA_URL is not set in the environment "
                "or in .env.")
    # Checked after env_config, because --url may have come from .env and an
    # unusable value there fails in exactly the same way.
    for problem in cli_types.check_listing_url(args.url):
        p.error(problem)
    if not cli_types.host_is_expected(args.url):
        logger.warning("--url points at %s, not %s: the parser reads Flippa's "
                       "own page shape and will most likely find nothing there.",
                       urlparse(args.url).hostname, cli_types.EXPECTED_HOST_SUFFIX)
    if args.category is None:
        args.category = category_from_url(args.url)
    locale = locale_from_url(args.url)
    if locale:
        # Said once, up front: a localised path does not merely translate
        # labels, it converts the prices. The same listing was USD 436,829 on
        # /search and EUR 380,546 on /fr/search on 2026-09-19. The currency
        # column follows the page, and two locales do not belong in one
        # dataset.
        logger.info("This URL is Flippa's %s localisation: labels are "
                    "translated and prices are CONVERTED into that locale's "
                    "currency.", locale.upper())
    return args


if __name__ == "__main__":
    args = parse_args()
    if args.fingerprint and not args.twocaptcha_key:
        logger.error("--fingerprint needs --twocaptcha-key (the Fingerprint API "
                     "uses the same key, though it is a separate subscription).")
        sys.exit(2)
    if args.fingerprint and args.cdp_endpoint:
        logger.error("--fingerprint cannot be used with --cdp-endpoint: the "
                     "Scraping Browser supplies its own device identity, and "
                     "stacking a second one contradicts it rather than "
                     "covering it.")
        sys.exit(2)
    try:
        sys.exit(scrape(args))
    except ProxyError as e:
        # Bad usage, not a crash: a typo in a proxy list would otherwise
        # surface as a connection failure on page 1 with nothing naming it.
        logger.error("%s", e)
        sys.exit(2)
    except FingerprintError as e:
        # The run asked for a fingerprint and cannot have one — measured
        # 2026-09-28: a key with a working solver balance gets 403 here when
        # the separate Fingerprint subscription is off. Exit 5 like any other
        # remote API error, with the reason and no traceback.
        logger.error("%s No page was fetched. Drop --fingerprint to run "
                     "without one.", e)
        sys.exit(EXIT_API_ERROR)
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception:  # noqa: BLE001 — a traceback is a log, and it is printed
        # A crash still reports exit 1 and still says where it happened; what
        # it must never do is print a credential on the way out. Both the
        # endpoint and the proxy URL travel through library exception text.
        import traceback
        logger.error("Crashed:\n%s", redact_secret_patterns(traceback.format_exc()))
        sys.exit(1)
