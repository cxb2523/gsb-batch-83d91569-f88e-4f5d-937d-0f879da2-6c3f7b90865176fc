"""
wellfound-scraper — Puppeteer edition

Scrapes wellfound.com: role landing pages, the /jobs discovery feed, and
individual job pages.

    --mode role   /role/{role} · /role/r/{role} · /role/l/{role}/{location}
                  The rich one. Full job descriptions, the company's badges,
                  size and tagline, salary AND equity. Paginates.
    --mode jobs   /jobs — the discovery feed. One page, thinner rows.
    --mode job    /jobs/{id}-{slug} — one job from its schema.org block.

What is different about Wellfound
=================================

* **The data is not in the DOM, and there are TWO structured sources, not
  one.** A landing page carries zero JSON-LD blocks and a normalised Apollo
  cache in `__NEXT_DATA__`; a job page carries no `__NEXT_DATA__` at all and
  exactly one schema.org `JobPosting`. They are different applications.
  Pointing the listing parser at a job page returns zero rows in silence,
  which is why `--mode` selects the reader and `product_parser` pins that
  failure.

* **Gating is per ROUTE, not per site.** From a residential US exit,
  measured three times each on 2026-09-17: `/`, `/jobs`, every `/role/…`
  shape and `/jobs/{id}-{slug}` answered 200; `/company/{slug}` answered
  403 every time, and answered 403 to a real Chromium on that same exit too.
  From a datacenter address EVERYTHING is 403, including `robots.txt`.

* **The site loads Cloudflare Turnstile on its own good pages.** It ships
  `challenges.cloudflare.com/turnstile/v0/api.js`, publishes
  `CLOUDFLARE_TURNSTILE_SITE_KEY` in its page config and renders a widget
  into `#turnstile_widget` when its own fetch wrapper is challenged. So the
  marker this family settled on elsewhere fires on GOOD pages here and is
  absent from the real refusal. Read `product_parser`'s marker comment
  before adding one.

* **Walking off the end of a listing does not fail — it repeats.**
  `?page=48` of a 47-page listing answers HTTP 200 carrying page 1 again.
  The response states which page the server really used, and this engine
  reads it.

Usage
-----
    python3 puppeteer_scraper.py --url "https://wellfound.com/role/r/software-engineer" --pages 3
    python3 puppeteer_scraper.py --role software-engineer --location new-york --pages 2
    python3 puppeteer_scraper.py --mode jobs --url "https://wellfound.com/jobs"
    python3 puppeteer_scraper.py --mode job --url "https://wellfound.com/jobs/4697947-senior-software-engineer"

A datacenter address gets nothing from this site. Use a residential
`--proxy`, or `--cdp-endpoint` for the 2Captcha Scraping Browser.
"""

import argparse
import asyncio
import concurrent.futures
import logging
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse, urljoin, parse_qsl

# At module level, deliberately, and not inside the launch path where it
# started out. The offline suite guards `import puppeteer_scraper` behind
# try/except ImportError and REPORTS the skip, and CI's engine-smoke job fails
# on any reported skip — that whole mechanism only works if importing this
# module actually requires the driver. With the import hidden inside
# _Session.open(), the module imported cleanly with no pyppeteer installed at
# all, the group never skipped, and CI could not have noticed a broken import.
# It also let CI install pyppeteer 0.0.25 (a stub, resolved from an unpinned
# `pip install pyppeteer`) without anything failing, because nothing ever
# imported it.
from pyppeteer import launch, connect

from captcha_solver import (detect_recaptcha_v3, detect_recaptcha_in_page,
                            reconcile_detections, solve_recaptcha,
                            CaptchaUnsolvable, INJECT_TOKEN_JS,
                            RECAPTCHA_DISCOVERY_JS, detect_turnstile,
                            wait_for_turnstile, TURNSTILE_INTERCEPT_JS,
                            TURNSTILE_INJECT_JS, turnstile_task_for)
from product_parser import (MODES, DEFAULT_MODE, FEED_URL, category_from_url,
                            detect_bot_challenge, is_supported_url,
                            mode_for_url, page_url, parse_detail,
                            parse_listing_page, references_own_assets,
                            role_url, site_turnstile_sitekey)
from output_writer import (dedupe_by_key, finish_run, EXIT_API_ERROR,
                           finish_without_fetch,
                           SOURCE_DEFAULT)
import page_flow
from page_flow import MIN_CARD_MATCHES
from proxy_pool import (from_args as proxy_pool_from_args, mask, ROTATE_MODES,
                        ProxyError, split_credentials)
import env_config
import proxy_check
import proxy_meter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("puppeteer_scraper")

ITEM_LINK_SELECTOR = page_flow.READY_SELECTOR_LISTING

# The share of rows that must carry the columns Wellfound fills on every
# record. Kept byte-identical to the other two engines — they must not
# disagree about what a healthy page looks like.
CORE_FIELD_FLOOR = 99
CORE_FIELDS = ("title", "url", "sku", "company_name", "company_id")

# ...and the set for --mode job, which is SHORTER on purpose rather than by
# omission. A job page's schema.org block names the hiring organisation but
# publishes no id for it, so `company_id` is legitimately null on every
# detail row. Checking one source's fields against another source's floor is
# how a correct run gets told it is broken.
CORE_FIELDS_JOB = ("title", "url", "sku", "company_name")


def _core_fields(mode: str):
    return CORE_FIELDS_JOB if mode == "job" else CORE_FIELDS

# A page holding less than this share of the fullest page in the same run is
# reported as thin. A landing page holds twenty COMPANIES and however
# many jobs they have — 32 to 45 across the captures — so this is a soft
# signal rather than a fixed page size.
THIN_PAGE_SHARE = 0.35

# Every await in this file goes through the bridge below with a timeout, so a
# hung remote call ends the operation instead of the run. pyppeteer provides
# no connect timeout of its own and its page methods' `timeout` option does
# not cover a browser that has stopped answering at all.
DEFAULT_OP_TIMEOUT = 120
CONNECT_TIMEOUT = 30


class _AsyncBridge:
    """Runs pyppeteer's coroutines on a private event loop, synchronously.

    Exists so this engine can reuse page_flow.py unchanged. That module holds
    the policy all three engines must share (how long to wait for
    challenge, when to scroll, when only a fresh session helps) and it is
    written against plain synchronous callables — which is the right shape for
    two of the three drivers. Bridging here keeps the policy in one place
    rather than growing an async copy of it that would drift.

    The second benefit is the one the family's rules actually require: every
    call gets an explicit, enforced timeout. `.result(timeout)` returns
    control even when the browser never answers, which is not something
    pyppeteer's own API offers.
    """

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._serve, daemon=True,
                                        name="pyppeteer-loop")
        self._thread.start()

    def _serve(self):
        asyncio.set_event_loop(self.loop)
        # pyppeteer leaves CDP calls in flight when a browser closes, and the
        # loop then logs each one as "Future exception was never retrieved:
        # NetworkError('Protocol error Target.sendMessageToTarget: Target
        # closed.')" — at ERROR level, AFTER a successful run has printed its
        # results. Five of those under a "Saved 48 products" line read as a
        # failed run. Only that shape is swallowed; anything else still gets
        # the default handler, because silencing the loop wholesale would hide
        # real faults.
        self.loop.set_exception_handler(self._on_loop_exception)
        self.loop.run_forever()

    @staticmethod
    def _on_loop_exception(loop, context):
        # BOTH, not one or the other. asyncio puts its own words in
        # `message` ("Future exception was never retrieved") and the library's
        # in `exception` (a NetworkError about a closed CDP session), and an
        # `or` between them looks at the exception and never sees the message
        # — which is why these kept printing after they were "handled".
        message = " | ".join(
            str(context.get(k)) for k in ("exception", "message")
            if context.get(k))
        if any(m in message for m in (
                "Target closed", "Connection closed",
                # asyncio's own words when the loop stops with work in
                # flight. Emitted after a successful run; see close().
                "Task was destroyed but it is pending",
                "Future exception was never retrieved",
                # A CDP message addressed to a session that has gone away.
                # Routine over a remote browser: three of six captures of
                # this site had their target closed mid-scroll and succeeded
                # on the next attempt.
                "No session with given id",
                "Event loop is closed")):
            logger.debug("Ignoring teardown noise from pyppeteer: %s", message)
            return
        loop.default_exception_handler(context)

    def run(self, coro, timeout: Optional[float] = DEFAULT_OP_TIMEOUT):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError(
                f"pyppeteer call did not return within {timeout}s")

    def close(self):
        """Stop the loop, CANCELLING whatever it still has in flight.

        Stopping the loop outright leaves pyppeteer's own background tasks
        pending — its websocket reader and keepalive — and asyncio then prints
        "Task was destroyed but it is pending!" plus a traceback for each of
        them. That happens AFTER the output has been written, so the run is
        fine and the log looks like a crash. Four tracebacks under a
        successful run is how a reader learns to ignore the log.

        Cancelling first is the fix, and it has to happen ON the loop thread —
        `call_soon_threadsafe` is what gets it there.
        """
        def _cancel_and_stop():
            pending = [t for t in asyncio.all_tasks(self.loop)
                       if t is not asyncio.current_task(self.loop)]
            for task in pending:
                task.cancel()
            if pending:
                logger.debug("Cancelled %d pending pyppeteer task(s) on "
                             "teardown.", len(pending))
            self.loop.stop()

        self.loop.call_soon_threadsafe(_cancel_and_stop)
        self._thread.join(timeout=5)


@dataclass
class PageOutcome:
    """What one page produced. Mirrors playwright_scraper.PageOutcome."""
    page_num: int
    url: str
    final_url: Optional[str] = None
    products: List = field(default_factory=list)
    blocked_by: Optional[str] = None
    load_failed: bool = False
    state: Optional[str] = None
    # Wellfound's OWN arithmetic, verbatim: how many jobs the listing holds
    # and how many pages the site will serve. These are what pages are
    # planned from.
    total_available: Optional[int] = None
    total_companies: Optional[int] = None
    pages_available: Optional[int] = None
    # The page number the SERVER answered with, read back out of the Apollo
    # cache key — not an echo of the request. Asking for page 48 of a
    # 47-page listing comes back stating page 1, which is how a run learns it
    # has walked off the end instead of silently re-collecting page 1.
    echoed_page: Optional[int] = None
    # The page number the SERVER answered with, read back out of the
    # Apollo cache key rather than echoed from the request.

    @property
    def ok(self) -> bool:
        """Did this page give us the site's own answer?

        `empty` counts as ok — the site served a listing and it matched
        nothing, which is an answer. `unknown`, `parse_error` and
        `not_found` do NOT: the content was never obtained, and an outcome
        that calls them ok is what turns a failed fetch into a complete run
        holding zero jobs (exit 4 instead of 5). The policy lives in
        page_flow so the three engines cannot disagree about it.
        """
        return (not self.load_failed
                and self.blocked_by is None
                and (self.state is None or page_flow.content_obtained(self.state)))


# Every `scheme://user:pass@` in a string, however many times it occurs.
# Matching globally rather than once is the point: a driver's connection
# error can repeat the endpoint several times (the message plus a call log),
# so a masker that handled only the first occurrence would print the password
# the other times and look like it was working.
_CREDENTIALS_IN_URL_RE = re.compile(r"([a-z][a-z0-9+.\-]*://)[^\s/@]+:[^\s/@]+@",
                                    re.IGNORECASE)


def _mask_credentials(text: str) -> str:
    """`text` with any username:password in an embedded URL replaced.

    Takes arbitrary text, not just a URL, because the strings that most need
    this are exception messages with a URL inside them. The host and port are
    KEPT — which endpoint or exit a run used is the useful half of the line
    and is not the secret.
    """
    return _CREDENTIALS_IN_URL_RE.sub(r"\1***:***@", text or "")


def _chrome_ua(version: str) -> str:
    """A desktop-Chrome UA naming the browser's OWN real version.

    Not a hardcoded number: it drifts the moment a newer Chromium ships, and
    claiming an older Chrome than the JS engine and TLS handshake report is
    itself a mismatch a fingerprinter can key on. pyppeteer's
    `browser.version()` returns "HeadlessChrome/115.0.0.0"; the marketing
    part is what a real Chrome would send.
    """
    number = version.split("/")[-1] if "/" in version else version
    return (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{number} Safari/537.36")


class _Session:
    """One pyppeteer browser + page, relaunchable onto a different exit.

    Same contract as the Playwright engine's _BrowserSession, including the
    rule that a rotation means a genuinely FRESH browser: cookies a bot
    manager issued against one exit, replayed from another, are a stronger
    signal than either address alone, so the cookie jar goes with the exit.
    """

    def __init__(self, bridge: _AsyncBridge, args, pool):
        self.bridge, self.args, self.pool = bridge, args, pool
        self.remote = bool(args.cdp_endpoint)
        self.browser = self.page = None

    def open(self):
        if self.remote:
            logger.info("Connecting to an existing browser over CDP: %s",
                        _mask_credentials(self.args.cdp_endpoint))
            # pyppeteer's browserWSEndpoint takes the full ws://user:pass@host
            # form and authenticates on the WebSocket upgrade, so an
            # authenticated Scraping Browser endpoint works here — unlike
            # Selenium's debuggerAddress, which has nowhere to put a password.
            try:
                self.browser = self.bridge.run(
                    connect(browserWSEndpoint=self.args.cdp_endpoint,
                            ignoreHTTPSErrors=True), timeout=CONNECT_TIMEOUT)
            except Exception as e:  # noqa: BLE001 — see below
                # The websockets library raises InvalidStatusCode here, and
                # its message is just "server rejected WebSocket connection:
                # HTTP 500" — which names neither the endpoint nor the
                # reason, and matched none of the patterns __main__ uses to
                # map a remote failure onto exit 5. A live profile run
                # therefore died with a raw traceback and exit 1, telling a
                # harness to go looking for a bug in this code when the real
                # answer is "wait, or use a different pid".
                #
                # Re-raised with the endpoint MASKED and the meaning spelled
                # out. HTTP 500 from cb.2captcha.com is overwhelmingly
                # `profile_locked`: a Scraping Browser profile allows ONE live
                # connection, and the run before this one may still hold it.
                raise RuntimeError(
                    "could not connect to --cdp-endpoint %s: %s\n"
                    "A Scraping Browser profile allows ONE live connection at "
                    "a time, so an HTTP 500 here usually means another run "
                    "still holds this `pid`. Wait for it to finish, or use a "
                    "different pid."
                    % (_mask_credentials(self.args.cdp_endpoint),
                       _mask_credentials(str(e)))) from None
            self.page = self.bridge.run(self.browser.newPage())
            return self

        # --lang really applies the locale rather than accepting the flag
        # and ignoring it. It does NOT decide which listing is
        # searched; that is find_country in the URL.
        launch_args = ["--no-sandbox", "--disable-dev-shm-usage",
                       f"--lang={self.args.locale}"]
        launch_kwargs = {}
        if self.args.chromium_path:
            launch_kwargs["executablePath"] = self.args.chromium_path
            logger.info("Using the Chromium at %s instead of pyppeteer's own.",
                        self.args.chromium_path)
        credentials = None
        if self.pool:
            exit_url = self.pool.current
            # Credentials go through page.authenticate(), never onto the
            # command line: --proxy-server= becomes part of the browser's
            # argv, readable by anything that can run `ps`.
            scrubbed, credentials = split_credentials(exit_url)
            launch_args.append(f"--proxy-server={scrubbed}")
            logger.info("Using proxy exit %s", mask(exit_url))

        # handleSIGINT/TERM/HUP off, and not for tidiness: pyppeteer installs
        # signal handlers inside launch(), and `signal.signal` raises
        # "signal only works in main thread of the main interpreter" because
        # the event loop here lives on a worker thread. Teardown is handled by
        # _Session.close() in scrape()'s finally block instead, so nothing is
        # lost — the browser is still closed on both success and failure.
        self.browser = self.bridge.run(
            launch(headless=self.args.headless, args=launch_args,
                   ignoreHTTPSErrors=True, handleSIGINT=False,
                   handleSIGTERM=False, handleSIGHUP=False, **launch_kwargs),
            timeout=CONNECT_TIMEOUT * 2)
        self.page = self.bridge.run(self.browser.newPage())
        version = self.bridge.run(self.browser.version())
        self.bridge.run(self.page.setUserAgent(_chrome_ua(version)))
        self.bridge.run(self.page.setViewport({"width": 1600, "height": 1000}))
        if self.args.fingerprint:
            self._apply_fingerprint()
        if credentials:
            self.bridge.run(self.page.authenticate(
                {"username": credentials[0], "password": credentials[1]}))
        if proxy_check.block_media(self.args, self.pool, remote=False):
            self.bridge.run(proxy_check.install_pyppeteer(self.page))
        self.bridge.run(proxy_meter.install_pyppeteer(
            self.page, proxy_meter.of(self.args)))
        return self

    def _apply_fingerprint(self):
        """Apply a 2captcha fingerprint to this page.

        The SAME init script the Playwright and Selenium engines install,
        shared deliberately: two engines applying different halves of one
        fingerprint would be a contradiction of exactly the kind a
        fingerprint is meant to avoid.

        Never reached over --cdp-endpoint (the remote browser brings its own
        identity, and stacking a second is worse than none) — that branch
        returns before this is called.
        """
        from fingerprint_client import get_fingerprint, playwright_init_script
        fp = get_fingerprint(self.args.twocaptcha_key, tags=self.args.fp_tags,
                             country=self.args.fp_country)
        ua = (fp.get("userAgent") or {}).get("value")
        try:
            if ua:
                self.bridge.run(self.page.setUserAgent(ua))
            self.bridge.run(
                self.page.evaluateOnNewDocument(playwright_init_script(fp)))
            logger.info("Using 2captcha fingerprint %s (%s)", fp.get("id"),
                        fp.get("country"))
        except Exception as e:  # noqa: BLE001 — a fingerprint is not the run
            logger.warning("Could not apply the fingerprint (%s) — continuing "
                           "without it.", e)

    def relaunch(self):
        if self.remote:
            return
        try:
            self.bridge.run(self.browser.close(), timeout=30)
        except Exception as e:  # noqa: BLE001 — teardown must not mask the reason we're here
            logger.debug("Ignoring error while closing browser: %s", e)
        self.open()

    def close(self):
        """Close the page, and on a REMOTE browser disconnect from it too.

        The disconnect is not tidiness. Closing only the page leaves
        pyppeteer's websocket to the remote browser open, and when the
        bridge's event loop then shuts down, `websockets` unwinds its own
        connection outside a running loop — printing four "Exception ignored
        in: <coroutine …>" tracebacks AFTER the output has already been
        written. A successful run that ends in four tracebacks is how a
        reader learns to ignore the log, which is the same reasoning as
        _AsyncBridge.close()'s.

        The remote BROWSER is deliberately left running: it is not ours, and
        a Scraping Browser profile is reused across runs.
        """
        try:
            if self.remote:
                self.bridge.run(self.page.close(), timeout=30)
                self.bridge.run(self.browser.disconnect(), timeout=30)
            else:
                self.bridge.run(self.browser.close(), timeout=30)
        except Exception as e:  # noqa: BLE001
            logger.debug("Ignoring error during browser teardown: %s", e)


# ---------------------------------------------------------------------------
# page_flow, bound to pyppeteer
# ---------------------------------------------------------------------------
# Only "how to ask this driver" lives here; every decision about what to do
# with the answer is in page_flow.py so all three engines make it the same way.
def _driver(session):
    bridge, page = session.bridge, session.page

    def count(selector):
        return len(bridge.run(page.querySelectorAll(selector)))

    def sleep(ms):
        time.sleep(ms / 1000.0)

    def content():
        try:
            return bridge.run(page.content())
        except Exception as e:  # noqa: BLE001
            # A URL canonicalisation can navigate, so a snapshot can land
            # exactly on the document swap. None tells the caller to skip a
            # check rather than fail the run.
            logger.debug("content() unavailable (page navigating?): %s", e)
            return None

    def current_url():
        return page.url

    # Named OPERATIONS rather than JavaScript crossing the page_flow
    # boundary: pyppeteer takes `() => expr` while Selenium takes a function
    # body with an explicit `return`, so a shared module passing JS would
    # acquire one driver's dialect.
    #
    # No scroll primitive, and its absence is measured rather than forgotten:
    # Wellfound serialises its whole result set into __NEXT_DATA__ in the
    # first response. Mirrors the
    # other two engines.
    return {"count": count, "sleep": sleep, "content": content,
            "current_url": current_url}


def _content(session) -> Optional[str]:
    return _driver(session)["content"]()


def _plan_page_urls(args, page_one_url, pages_available):
    """URLs for pages 2..N, decided once from what page 1 reported.

    Wellfound states its own `pageCount` in every landing response, so the
    end of the listing is a number the site hands over on page 1 rather than
    something discovered by walking off it.

    Walking off it is the thing to avoid here. `?page=48` of a 47-page
    listing does not error and does not empty — it answers HTTP 200 with
    page 1's rows again. So the plan is CAPPED by the site's own figure, and
    `parse_listing_page` reads back which page the server actually used as a
    second line of defence.
    """
    if not page_flow.pagination_is_addressable(page_one_url):
        # The /jobs feed. `?page=2` on it returns the identical 46 ids as
        # page 1, so planning any page URL would manufacture duplicates and
        # report a complete multi-page run holding one page several times.
        if args.pages > 1:
            logger.info("This listing is served at ONE address — %s. "
                        "`?page=2` on it returns the identical rows as page "
                        "1, so %d page(s) were asked for and 1 will be "
                        "fetched.", page_one_url, args.pages)
        return []
    wanted = page_flow.pages_to_plan(args.pages, pages_available)
    if wanted < args.pages:
        logger.info("Wellfound reports %s page(s) for this listing; %d were "
                    "asked for. Planning %d — asking past the site's own last "
                    "page returns page 1 again under HTTP 200, not an empty "
                    "page.", pages_available, args.pages, wanted)
    return [page_url(page_one_url, n) for n in range(2, wanted + 1)]


def _parse_for_mode(html: str, url: str, args, page_num: int = 1):
    """(rows, listing) for this mode. `listing` is None in --mode job.

    `page_num` is threaded through rather than defaulted, because `position`
    restarts at 1 on every page: without the page number beside it, a row
    from page 2 claims the same position as one from page 1 and the two are
    indistinguishable in the output.
    """
    if args.mode == "job":
        row = parse_detail(html, url)
        return ([row] if row is not None else []), None
    listing = parse_listing_page(html, url=url, page=page_num)
    return listing.rows, listing


def _is_endpoint(url: str) -> bool:
    """Whether this address answers with raw JSON rather than a document.

    Always False on Wellfound: unlike the sibling repo this engine was
    ported from, there is no ungated JSON endpoint here — every route is an
    HTML page with its payload serialised inside it. Kept so the three
    engines' snapshot paths branch identically.
    """
    return False


def _snapshot(session, url: str):
    """What the parser is given for this address. Mirrors the other engines.

    A PAGE is read with `content()`. The ENDPOINT answers with JSON, which
    Chromium wraps in its own JSON-viewer markup, so reading the body text is
    the only way to get back what the server actually sent.
    """
    if _is_endpoint(url):
        try:
            return session.bridge.run(session.page.evaluate(
                "() => document.body.innerText")) or ""
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not read the endpoint response: %s", e)
            return None
    return _driver(session)["content"]()


def handle_captcha_if_present(session, args) -> bool:
    """Detect and solve a challenge. True if something was solved.

    Same two families, same order, same "detected is not blocking" rule as
    the Playwright engine — see its docstring for why the anchor count is
    checked here rather than after the readiness wait.
    """
    bridge, page = session.bridge, session.page
    html = _content(session)
    if html is None:
        return False

    selector = page_flow.ready_selector(args.mode)
    already_rendered = len(bridge.run(page.querySelectorAll(selector)))
    when_blocked = getattr(args, "solve_captcha", "when-blocked") == "when-blocked"

    html_challenge = detect_recaptcha_v3(html, page.url)
    runtime_challenge = detect_recaptcha_in_page(
        lambda js: bridge.run(page.evaluate(js)), page_url=page.url)
    challenge = reconcile_detections(html_challenge, runtime_challenge)
    if not challenge:
        return False
    if when_blocked and already_rendered > MIN_CARD_MATCHES:
        logger.info("%s detected via %s, but %d anchors are already on the "
                    "page — not solving it.", challenge.kind, challenge.source,
                    already_rendered)
        return False
    logger.warning("%s detected via %s (sitekey=%s) — attempting to solve.",
                   challenge.kind, challenge.source, challenge.sitekey)
    if not args.twocaptcha_key:
        logger.warning("No 2captcha API key, so this challenge cannot be solved.")
        return False
    try:
        token = solve_recaptcha(challenge, args.twocaptcha_key,
                                api_version=args.captcha_api,
                                min_score=args.min_score)
    except Exception as e:  # noqa: BLE001
        logger.error("Solving the challenge failed (%s).", e)
        return False
    bridge.run(page.evaluate(INJECT_TOKEN_JS, token))
    logger.info("Token injected. Reloading page to continue.")
    time.sleep(1.5)
    bridge.run(page.reload({"waitUntil": "domcontentloaded", "timeout": 60000}))
    return True





def _target_url(args) -> str:
    """The address this run actually fetches.

    Unlike the sibling repo this engine was ported from, there is no
    endpoint to prefer: every route here is an HTML page carrying its own
    structured payload, so what a visitor loads is what this fetches. The
    function stays because `--role`/`--location` build a URL that `--url`
    would otherwise have to be typed for.
    """
    if args.url:
        return args.url
    return role_url(args.role, location=args.location, remote=args.remote)


def _solve_budget(args, spent: int):
    """Whether another solve may be bought for this page.

    `page_flow.SOLVES_PER_PAGE` says at most one purchase per page, and that
    is a MONEY limit rather than a style rule. It was not being enforced:
    `handle_captcha_if_present` is called twice per attempt — once before the
    page is classified and once after — and only the SECOND call was counted.

    Measured 2026-09-17 from a datacenter address, which meets a real
    Cloudflare challenge on every fetch: ONE page bought THREE Turnstile
    solves, and every token was refused. The cap read as enforced and was not.
    Both call sites now go through here.
    """
    return spent < page_flow.SOLVES_PER_PAGE


def _fetch_one_page(session, args, pool, page_num: int, url: str) -> PageOutcome:
    """Fetch and parse one page. Mirrors playwright_scraper._fetch_one_page.

    The retry/rotate/wait policy is page_flow's and finish_run's; what differs
    here is only the driver calls. Kept structurally parallel on purpose —
    the two files are meant to be diffable, because "all three engines agree"
    is checked by reading them side by side as well as by the smoke suite.
    """
    outcome = PageOutcome(page_num=page_num, url=url)
    bridge, page = session.bridge, session.page
    d = _driver(session)

    # See the Playwright engine for the measurement: without a pool there is
    # no exit to rotate to, but a plain re-fetch is what clears a block on a
    # Scraping Browser profile, so the budget is not zero.
    has_pool = bool(pool and len(pool) > 1)
    # `RETRY_ON_BLOCKED` is CONSULTED, not just documented. It was a
    # constant with a paragraph of justification that no engine read — a
    # policy statement nothing enforced, which is the same defect as dead
    # code that looks load-bearing. Setting it False now really does stop
    # the retry loop.
    block_retries = 0 if not page_flow.RETRY_ON_BLOCKED else (
        args.proxy_block_retries if has_pool
        else page_flow.BLOCK_RETRIES_WITHOUT_POOL)
    # Counted across the whole block-retry loop, not per attempt: a page that
    # keeps coming back as a challenge would otherwise buy one solve per
    # rotation, which is how a run quietly turns into a bill.
    solves_bought = 0
    html, state, load_failed = None, "ok", False

    for block_attempt in range(block_retries + 1):
        logger.info("Fetching page %d/%d: %s", page_num, args.pages, url)
        # `exit_failed` holds Chromium's own name for a proxy fault, or None.
        # Named and shaped exactly as in the other two engines: the give-up
        # branch below reports it, and three engines that structure this
        # differently drift.
        load_failed, exit_failed, status = False, None, None
        for attempt in range(1, args.retries + 1):
            proxy_meter.check(args)
            try:
                # The response is kept: its status is the classifier's primary
                # signal (403 refusal, 404 for a job that is gone).
                response = bridge.run(page.goto(
                    url, {"waitUntil": "domcontentloaded", "timeout": 60000}))
                status = getattr(response, "status", None)
                load_failed = False
                break
            except Exception as e:  # noqa: BLE001 — pyppeteer raises many types
                load_failed = True
                # pyppeteer surfaces a dead proxy as a page error whose text
                # carries Chromium's own name for it, exactly as Playwright
                # does; a timeout and an unusable exit want opposite
                # responses, so they are told apart by that text.
                text = str(e)
                marker = next((m for m in _PROXY_ERROR_MARKERS if m in text), None)
                if marker:
                    exit_failed = marker
                    logger.warning("Exit %s is unusable (%s).",
                                   mask(pool.current) if pool else "(none)", text[:120])
                    break
                if attempt < args.retries:
                    pause = args.retry_delay * (2 ** (attempt - 1))
                    logger.warning("Failed to load %s (attempt %d/%d: %s) — "
                                   "retrying in %.1fs.", url, attempt,
                                   args.retries, text[:120], pause)
                    time.sleep(pause)

        # Only a dead EXIT is worth a rotation, and only when there is another
        # exit to rotate to — the same gate as the Playwright engine. This used
        # to rotate on any load failure and called `pool.advance` with no pool
        # at all, raising AttributeError on a plain timeout without --proxy.
        if exit_failed and has_pool and block_attempt < block_retries:
            logger.warning("Exit %s is unusable (%s) — rotating to another "
                           "one (%d/%d).", mask(pool.current), exit_failed,
                           block_attempt + 1, block_retries)
            pool.advance(f"unusable exit: {exit_failed}")
            session.relaunch()
            bridge, page = session.bridge, session.page
            d = _driver(session)
            continue
        if load_failed:
            break


        # Counted, because it can BUY. See _solve_budget.
        if _solve_budget(args, solves_bought):
            solves_bought += 1
            if handle_captcha_if_present(session, args):
                time.sleep(1)
                status = None   # the solve reloaded; that status is stale

        elif solves_bought:
            logger.info("Not solving again on page %d: %d purchase(s) "
                        "already made for it and SOLVES_PER_PAGE is %d.",
                        page_num, solves_bought, page_flow.SOLVES_PER_PAGE)
        html = _snapshot(session, url) or ""
        # `mode` is passed because a job page carries no listing payload:
        # classified as a listing, every one came out `parse_error`.
        state = page_flow.classify(html, status, page.url, mode=args.mode)

        # Wellfound server-renders its payload, so a listing is parseable
        # in the FIRST response. The wait below is only for the state that
        # says Wellfound
        # served SOMETHING that is not the payload. Mirrors the other two
        # engines.
        if state == "unknown":
            wait_ms = page_flow.content_timeout_ms(args.mode)
            sel = page_flow.ready_selector(args.mode)
            need = page_flow.min_matches(args.mode)
            logger.info("Page %d is something Wellfound served (%d bytes, its own "
                        "assets referenced %d time(s)) but carries no listing "
                        "payload — waiting up to %.0fs rather than spending a "
                        "retry.", page_num, len(html),
                        references_own_assets(html), wait_ms / 1000.0)
            found = page_flow.wait_for_count(d["count"], sel, need, wait_ms,
                                             d["sleep"])
            if found < need:
                logger.info("Still nothing after %.0fs (%d match(es) for %s).",
                            wait_ms / 1000.0, found, sel)
            html = _snapshot(session, url) or html
            # No status: the document may have changed during the wait.
            state = page_flow.classify(html, None, page.url, mode=args.mode)

        # The paid path is reached only for a state the policy marks solvable
        # ("blocked" here). Cloudflare's managed challenge IS a test; the
        # branded refusal carries no widget and no sitekey, and the solver
        # refuses to build a task without one, so it costs nothing there.
        # Bounded by SOLVES_PER_PAGE. Mirrors the other two engines.
        if (page_flow.should_solve(state)
                and _solve_budget(args, solves_bought)):
            solves_bought += 1
            if handle_captcha_if_present(session, args):
                time.sleep(1)
                html = _content(session) or html
                state = page_flow.classify(html, None, page.url,
                                           mode=args.mode)
                if state == "content":
                    logger.info("The solve was accepted — page %d is content "
                                "now.", page_num)
                else:
                    logger.warning("The solve was NOT accepted: page %d is "
                                   "still %s. The purchase is spent.",
                                   page_num, state)

        if not page_flow.should_retry(state):
            # "content" and "empty" are both final answers. An empty page is
            # a CORRECT one — a landing page that matched nothing — so retrying it
            # would re-confirm the same right answer, and rotating the exit
            # would blame an address for the URL it was given.
            break

        # Blocked or challenged. The ADDRESS is what was scored, not the URL,
        # so a different exit is the only thing that plausibly changes the
        # outcome.
        if block_attempt < block_retries:
            if has_pool:
                logger.warning("Page %d came back as %s from %s — retrying "
                               "from another exit (%d/%d).", page_num, state,
                               mask(pool.current), block_attempt + 1,
                               block_retries)
                pool.advance(f"{state} on page {page_num}")
                session.relaunch()
                bridge, page = session.bridge, session.page
                d = _driver(session)
            else:
                # No pool, so no other exit: re-fetch through the same access
                # path, as the Playwright engine does. This branch used to
                # touch `pool.current` unconditionally and raised
                # AttributeError on the ordinary no-proxy block.
                pause = args.retry_delay * (block_attempt + 1)
                logger.warning("Page %d came back as %s — re-fetching through "
                               "the same access path in %.1fs (%d/%d).",
                               page_num, state, pause, block_attempt + 1,
                               block_retries)
                time.sleep(pause)

    if load_failed:
        # NAME the proxy when it was the proxy. A dead exit and
        # a timeout want opposite responses — another try at the same exit
        # versus a different exit — so a message that cannot tell them apart
        # leaves the reader guessing which they got.
        #
        # This branch used to drop `exit_failed` on the floor. With a POOL the
        # reason was logged on rotation, but WITHOUT one — a single --proxy,
        # which is the common case — the run said only "gave up loading" for
        # a proxy that had refused the connection outright. Found by running
        # it: `--proxy http://127.0.0.1:9` reported the generic message while
        # `_proxy_failure()` had correctly identified
        # ERR_PROXY_CONNECTION_FAILED one frame earlier.
        if exit_failed:
            logger.error(
                "Gave up loading %s: the PROXY refused the connection (%s), "
                "which is not a timeout and will not fix itself on a retry "
                "from the same exit. Check the exit, or pass --proxy-file so "
                "the run can rotate to another one.", url, exit_failed)
        else:
            logger.error("Gave up loading %s after %d attempt(s).",
                         url, args.retries)
        outcome.load_failed = True
        outcome.blocked_by = None
        return outcome

    outcome.state = state

    if state == "blocked":
        # Wellfound refuses in TWO skins, both Cloudflare — see
        # playwright_scraper's twin of this block. This is the HARD refusal.
        debug_html = f"{args.out}_page{page_num}_debug.html"
        with open(debug_html, "w", encoding="utf-8") as f:
            f.write(html or "")
        logger.error(
            "Wellfound did not serve this request — %d bytes, its own asset hosts "
            "referenced %d time(s), saved to %s. There is no widget on this "
            "page and no key would help. What clears it, measured "
            "2026-09-17: an exit Wellfound does not score as a datacenter. This is "
            "exit 3, distinct from a genuinely empty result (exit 4).",
            len(html or ""), references_own_assets(html or ""), debug_html)
        outcome.blocked_by = "cloudflare (hard block)" if html else "no-response"
        outcome.final_url = page.url
        return outcome

    # No readiness wait and no scroll on the content path, and their absence
    # is MEASURED rather than forgotten — see the "unknown" branch above.

    if args.dump_html:
        dump_path = (args.dump_html if args.pages == 1
                     else f"{args.dump_html}.page{page_num}")
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("Saved the snapshot the parser sees to %s (%d bytes).",
                    dump_path, len(html))

    # Only for a state page_flow already counts as BLOCKED: an EMPTY page
    # is a correct answer and must never become exit 3 because a marker
    # matched it. Mirrors playwright_scraper exactly.
    vendor = (detect_bot_challenge(html, url=page.url)
              if page_flow.counts_as_blocked(state) else None)
    if vendor:
        debug_html = f"{args.out}_page{page_num}_debug.html"
        with open(debug_html, "w", encoding="utf-8") as f:
            f.write(html)
        try:
            bridge.run(page.screenshot({"path": f"{args.out}_page{page_num}_debug.png",
                                        "fullPage": True}))
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not capture screenshot: %s", e)
        logger.error("Blocked by %s before parsing (%d bytes) — saved to %s. "
                     "This is exit 3, distinct from a genuinely empty result "
                     "(exit 4).", vendor, len(html), debug_html)
        outcome.blocked_by = vendor
        return outcome

    if not page_flow.should_parse(state):
        # Dump it. A state that holds no rows is a state somebody will have
        # to diagnose, and the only way to tell a parsing bug from a page
        # that never arrived is the exact bytes. Until the
        # 2026-10-13 audit this path wrote nothing at all: the auditor's run
        # failed and left no artefact, which is half of why the cause was
        # misread. The blocked path has always dumped; this one did not.
        debug_html = f"{args.out}_page{page_num}_debug.html"
        try:
            with open(debug_html, "w", encoding="utf-8") as f:
                f.write(html or "")
        except OSError as e:
            debug_html = f"(could not be written: {e})"
        logger.info("Page %d came back as %s (%d bytes, own assets "
                    "referenced %d time(s)) — nothing to parse, saved to %s.",
                    page_num, state, len(html or ""),
                    references_own_assets(html or ""), debug_html)
        outcome.final_url = page.url
        return outcome

    products, listing = _parse_for_mode(html, page.url, args, page_num)
    logger.info("Parsed %d row(s) from page %d.", len(products), page_num)

    if listing is not None:
        # Wellfound states its own arithmetic on every landing page, so it is
        # recorded every time and page 1's copy is what the run plans against.
        outcome.total_available = listing.total_jobs
        outcome.total_companies = listing.total_companies
        outcome.pages_available = listing.pages_available
        outcome.echoed_page = listing.echoed_page
        if page_num == 1 and listing.pages_available:
            logger.info("Wellfound reports %s job(s) at %s compan(ies) across "
                        "%s page(s) of %s companies each.", listing.total_jobs,
                        listing.total_companies, listing.pages_available,
                        listing.page_size)
        elif page_num == 1:
            # The /jobs feed carries no `Results` node at all. Printing a line
            # of Nones would read like a parse failure on a page that parsed.
            logger.info("This listing publishes no result counts — %d row(s) "
                        "is what it served.", len(listing.rows))
        if listing.page_repeated:
            # The site clamped an out-of-range page back and answered 200.
            logger.info("Asked for page %s and Wellfound answered with page "
                        "%s — that is this site's way of saying the listing "
                        "has ended.", listing.requested_page,
                        listing.echoed_page)

    if products:
        for field_name in _core_fields(args.mode):
            filled = sum(1 for row in products
                         if getattr(row, field_name, None) not in (None, "", []))
            share = 100.0 * filled / len(products)
            if share < CORE_FIELD_FLOOR:
                logger.warning(
                    "Only %.0f%% of page %d carries `%s`, against a measured "
                    "floor of %d%%. Every record of every capture had one, so "
                    "this is the payload shape moving rather than the "
                    "listings being unusual — re-run with --dump-html.",
                    share, page_num, field_name, CORE_FIELD_FLOOR)
        paid = sum(1 for row in products if row.salary_min is not None)
        remote = sum(1 for row in products if row.remote)
        described = sum(1 for row in products if row.description)
        # All reported, none floored: 54 of 312 captured listings state no
        # compensation at all, and the /jobs feed publishes no description on
        # any row. A floor on either would fire on healthy data.
        if args.mode == "job":
            logger.info("Job: %s at %s.", products[0].title,
                        products[0].company_name or "an unnamed company")
        else:
            logger.info("Page %d: %d/%d state pay, %d/%d remote, %d/%d carry "
                        "a description.", page_num, paid, len(products),
                        remote, len(products), described, len(products))

    if not products:
        debug_html = f"{args.out}_page{page_num}_debug.html"
        with open(debug_html, "w", encoding="utf-8") as f:
            f.write(html)
        try:
            bridge.run(page.screenshot({"path": f"{args.out}_page{page_num}_debug.png",
                                        "fullPage": True}))
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not capture screenshot: %s", e)
        logger.warning("0 rows parsed — saved what the browser actually saw to "
                       "%s.", debug_html)

    outcome.products = products
    outcome.final_url = page.url
    return outcome


# Chromium's own names for "the proxy is the problem, not the site".
_PROXY_ERROR_MARKERS = (
    "ERR_PROXY_CONNECTION_FAILED", "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_PROXY_AUTH_UNSUPPORTED", "ERR_PROXY_AUTH_REQUESTED",
    "ERR_UNEXPECTED_PROXY_AUTH", "ERR_PROXY_CERTIFICATE_INVALID",
)


def scrape(args) -> int:
    outcomes: List[PageOutcome] = []
    seen_keys = set()
    blocked = False
    # All three modes are one row per job posting, keyed by its id.
    dedupe_key = "sku"
    # --mode job is one page by construction and --mode jobs is a feed
    # served at one address; only --mode role paginates.
    stop_reason = ("single_page_mode" if args.mode == "job"
                   else "single_page_listing" if args.mode == "jobs"
                   else "completed")

    pool = proxy_pool_from_args(args)
    if pool and args.cdp_endpoint:
        logger.warning("Ignoring --proxy/--proxy-file: with --cdp-endpoint the "
                       "remote browser has its own exit, and layering a second "
                       "proxy on top would contradict it.")
        pool = None
    if args.concurrency > 1:
        logger.warning("--concurrency is ignored in this engine: parallel page "
                       "fetching is implemented in playwright_scraper.py, "
                       "which is the primary engine. Running one page at a "
                       "time.")

    # One request through the proxy before a browser exists: a 407 or 402
    # from the gateway ends the run here, in seconds, instead of surfacing
    # as a navigation timeout after every retry.
    refused = proxy_check.gate(pool, _target_url(args))
    if refused:
        return finish_without_fetch(
            args.out, stop_reason=refused.stop_reason,
            pages_requested=args.pages, start_url=_target_url(args),
            mode=args.mode, source=SOURCE_DEFAULT)
    meter = proxy_meter.start(args, pool, remote=bool(args.cdp_endpoint))

    bridge = _AsyncBridge()
    session = None
    try:
        session = _Session(bridge, args, pool).open()

        target = _target_url(args)
        if target != args.url:
            logger.info("Fetching %s", target)

        first = _fetch_one_page(session, args, pool, 1, target)
        outcomes.append(first)

        if not first.ok:
            stop_reason = page_flow.stop_reason_for(
                    first.load_failed, first.blocked_by, first.state)
            blocked = first.blocked_by is not None
        elif args.mode == "job":
            pass  # one page is the whole run
        else:
            seen_keys.update(p.sku for p in first.products if p.sku is not None)

            # Planned through the SHARED helper, so all three engines decide
            # this identically: it reads the site's own `pageCount` and
            # refuses to build page URLs for a listing that has none.
            page_one = first.final_url or target
            planned = _plan_page_urls(args, page_one, first.pages_available)
            if len(planned) + 1 < args.pages:
                stop_reason = "page_cap_reached"

            for index, url in enumerate(planned):
                page_num = index + 2
                if pool and pool.rotates_per_page():
                    pool.advance(f"per-page rotation, page {page_num}")
                    session.relaunch()

                outcome = _fetch_one_page(session, args, pool, page_num, url)
                outcomes.append(outcome)
                if not outcome.ok:
                    stop_reason = page_flow.stop_reason_for(
                    outcome.load_failed, outcome.blocked_by, outcome.state)
                    blocked = outcome.blocked_by is not None
                    break

                fresh_count = sum(1 for p in outcome.products
                                  if p.sku is None or p.sku not in seen_keys)
                seen_keys.update(p.sku for p in outcome.products
                                 if p.sku is not None)
                if not fresh_count:
                    logger.info("Page %d added no rows not already seen — "
                                "treating that as the end of the listing.",
                                page_num)
                    stop_reason = "no_new_products"
                    break

                if index + 1 < len(planned):
                    time.sleep(args.delay)
    except proxy_meter.ProxyBudgetExceeded as e:
        logger.error("Stopping: %s. The pages already gathered are kept.", e)
    finally:
        if session is not None:
            session.close()
        bridge.close()

    # Over budget is the stop reason whatever the loop concluded: the
    # requests after the cap were refused, so nothing after it was read.
    if meter is not None and meter.exceeded:
        stop_reason, blocked = proxy_meter.STOP_BUDGET_EXCEEDED, False

    all_rows = []
    merged_seen = set()
    for oc in sorted(outcomes, key=lambda o: o.page_num):
        fresh = dedupe_by_key(oc.products, merged_seen, key=dedupe_key)
        if len(fresh) < len(oc.products):
            logger.info("Page %d: dropped %d duplicate row(s).",
                        oc.page_num, len(oc.products) - len(fresh))
        all_rows.extend(fresh)

    # Completeness, checked over the MERGED result rather than per page — a
    # per-page check cannot see a gap BETWEEN two pages, which is exactly
    # where a short page hides.
    #
    # NOT "pages x rows-per-page" as a hard expectation: the LAST page of a
    # listing is legitimately short. Mirrors the other two engines.
    total_available = next((o.total_available for o in outcomes
                            if o.total_available is not None), None)
    pages_available = next((o.pages_available for o in outcomes
                            if o.pages_available is not None), None)
    if args.mode == "role" and all_rows:
        counts = [(o.page_num, len(o.products)) for o in outcomes if o.ok]
        fullest = max((n for _, n in counts), default=0)
        thin = [(p, n) for p, n in counts
                if fullest and n < THIN_PAGE_SHARE * fullest]
        last_page = max((p for p, _ in counts), default=0)
        thin = [(p, n) for p, n in thin if p != last_page]
        if thin:
            logger.warning(
                "Page(s) %s came back much thinner than the fullest page "
                "(%d rows): %s. A landing page carries the jobs of twenty companies, "
                "which varies, so this is a soft signal.",
                ", ".join(str(p) for p, _ in thin), fullest,
                ", ".join("page %d: %d" % (p, n) for p, n in thin))
        if total_available:
            logger.info("Wellfound reports %d job(s) for this listing; this run "
                        "holds %d (%.1f%%).", total_available, len(all_rows),
                        100.0 * len(all_rows) / total_available)

    ok_pages = [o for o in outcomes if o.ok]
    failed_pages = [o.page_num for o in outcomes if not o.ok]
    final_url = (max(ok_pages, key=lambda o: o.page_num).final_url
                 if ok_pages else args.url)

    # One-per-run context, in the sidecar rather than repeated down a column.
    # Byte-identical in shape to the other two engines: the site's own
    # counts, which describe the LISTING rather than any job. `total_jobs`
    # beside `total_companies` is what stops a reader dividing rows by pages
    # — Wellfound paginates over companies and this file holds jobs.
    extra = None
    if args.mode != "job":
        total_companies = next((o.total_companies for o in outcomes
                                if o.total_companies is not None), None)
        extra = {"total_jobs": total_available,
                 "total_companies": total_companies,
                 "pages_available": pages_available,
                 "paginates_by_url": args.mode == "role"}
    extra = proxy_meter.finish(args, extra)

    return finish_run(all_rows, args.out, args.format, args.allow_empty,
                      blocked=blocked, stop_reason=stop_reason,
                      pages_requested=args.pages, pages_completed=len(ok_pages),
                      pages_failed=failed_pages, mode=args.mode,
                      source=SOURCE_DEFAULT,
                      start_url=args.url, final_url=final_url,
                      extra=extra)


def parse_args():
    p = argparse.ArgumentParser(
        description="Wellfound (AngelList Talent) job scraper (pyppeteer "
                    "edition). pyppeteer is effectively unmaintained — "
                    "playwright_scraper.py is the primary engine.")
    p.add_argument("--url", default=None,
                   help="A wellfound.com URL: /role/{role}, /role/r/{role}, "
                        "/role/l/{role}/{location}, /jobs, or "
                        "/jobs/{id}-{slug} with --mode job. Optional for a "
                        "landing page: --role and --location build it. Also "
                        "read from WELLFOUND_URL in the environment or .env.")
    p.add_argument("--role", default=None, metavar="SLUG",
                   help="A role slug as Wellfound spells it in its own URLs: "
                        "software-engineer, data-scientist. Builds a /role/… "
                        "URL. Ignored when --url is given.")
    p.add_argument("--location", default=None, metavar="SLUG",
                   help="A location slug, as in /role/l/{role}/{location}: "
                        "san-francisco, new-york, london. Used with --role.")
    p.add_argument("--remote", action="store_true",
                   help="With --role and no --location, build the REMOTE "
                        "landing page (/role/r/{role}) instead of the general "
                        "one. They are different listings, not a filter.")
    p.add_argument("--mode", choices=list(MODES), default=DEFAULT_MODE,
                   help="role (default): a /role/… landing page — full "
                        "descriptions, company badges, equity. jobs: the "
                        "/jobs feed, which is ONE page. job: one "
                        "/jobs/{id}-{slug} page from its schema.org "
                        "JobPosting. --pages applies to --mode role only.")
    p.add_argument("--category", default=None,
                   help="Label to tag the run with in the sidecar. Defaults "
                        "to what the URL selects. Wellfound has no category "
                        "tree, so this names the QUERY, not a site concept.")
    p.add_argument("--pages", type=page_flow.at_least_one, default=1,
                   help="Listing pages to fetch (--mode role only). A run "
                        "plans against the `pageCount` the site states on "
                        "page 1 and never asks past it: page 48 of a 47-page "
                        "listing answers HTTP 200 with page 1 AGAIN.")
    p.add_argument("--delay", type=page_flow.seconds, default=2.0, help="Delay between pages, seconds")
    p.add_argument("--concurrency", type=page_flow.at_least_one, default=1, metavar="N",
                   help="Accepted for flag parity and IGNORED here: parallel "
                        "page fetching lives in playwright_scraper.py.")
    p.add_argument("--retries", type=page_flow.attempts, default=3,
                   help="Attempts per page load before giving up (default 3). "
                        "A page that comes back EMPTY is not retried: an empty "
                        "landing page is a correct answer, not a fault.")
    p.add_argument("--retry-delay", type=page_flow.seconds, default=2.0,
                   help="Seconds before the first retry, doubling thereafter")
    p.add_argument("--format", choices=["json", "csv", "both"], default="both")
    p.add_argument("--out", default="wellfound_jobs", help="Output file prefix")
    p.add_argument("--proxy", default=None,
                   help="Proxy URL, e.g. http://ACCOUNT:PASSWORD@HOST:9999. "
                        "Credentials are sent over CDP (page.authenticate), "
                        "never on the browser's command line.")
    p.add_argument("--proxy-file", default=None,
                   help="File with one proxy URL per line to rotate across. "
                        "Wins over --proxy.")
    p.add_argument("--proxy-rotate", choices=list(ROTATE_MODES), default="per-run")
    p.add_argument("--proxy-shuffle", action="store_true")
    p.add_argument("--proxy-block-retries", type=page_flow.non_negative, default=2)
    p.add_argument("--twocaptcha-key", default=None, help="2captcha.com API key")
    p.add_argument("--allow-empty", action="store_true",
                   help="Write output files even when 0 rows were found.")
    p.add_argument("--captcha-api", choices=["v2", "v1"], default="v2")
    p.add_argument("--solve-captcha", choices=["when-blocked", "always"],
                   default="when-blocked",
                   help="when-blocked (default): only pay to solve a "
                        "reCAPTCHA if the content is not already readable. "
                        "always: solve whenever one is detected. Note that "
                        "NO challenge has ever been observed on this site — a "
                        "refused request gets no page at all — so neither "
                        "setting has anything to act on today, and neither "
                        "helps with a refusal.")
    p.add_argument("--min-score", type=float, default=0.7)
    proxy_check.add_media_flags(p)
    proxy_meter.add_budget_flag(p)
    p.add_argument("--cdp-endpoint", default=None,
                   help="Connect to a running browser over CDP, e.g. "
                        "ws://user:pass@host:port. pyppeteer authenticates on "
                        "the WebSocket upgrade, so a credentialed Scraping "
                        "Browser endpoint works here.")
    p.add_argument("--dump-html", default=None, metavar="PATH",
                   help="Save the exact HTML the parser is given, on success "
                        "as well as failure.")
    p.add_argument("--locale", default="en-US",
                   help="Browser locale (default en-US), passed to Chromium "
                        "as --lang. It does NOT decide which directory is "
                        "searched; that is find_country in the URL.")
    p.add_argument("--fingerprint", action="store_true",
                   help="Fetch a browser fingerprint from 2captcha's "
                        "Fingerprint API and apply it to the launched "
                        "browser. Needs --twocaptcha-key. Ignored with "
                        "--cdp-endpoint, where the Scraping Browser supplies "
                        "its own.")
    p.add_argument("--fp-tags", default="Windows",
                   help="ONE OS-family tag for the fingerprint filter: "
                        "Windows, Microsoft Windows or Android. NOT a list — "
                        "Chrome, Desktop and Mobile are each rejected by the "
                        "API with 400. (default: Windows)")
    p.add_argument("--fp-country", default=None,
                   help="Fingerprint country, ISO 3166-1 alpha-2. Match it to "
                        "your proxy's exit country — a US fingerprint on a "
                        "German IP is a contradiction.")
    p.add_argument("--chromium-path", default=None, metavar="PATH",
                   help="Browser executable to drive, instead of the Chromium "
                        "pyppeteer downloads for itself. Needed where that "
                        "build will not start: on an Apple Silicon Mac "
                        "pyppeteer fetches an x86_64 Chromium 117, which runs "
                        "under Rosetta far enough to print --version and then "
                        "fails to open its DevTools socket (measured "
                        "2026-09-08; the same failure occurs with no wrapper "
                        "code at all, so it is the build, not this engine). "
                        "Point it at a Chrome or Chromium of your own — "
                        "Playwright's, if you have it installed.")
    p.add_argument("--headless", action="store_true", default=True)
    p.add_argument("--headful", dest="headless", action="store_false")
    args = p.parse_args()
    # What was TYPED, captured before the environment fills anything in.
    typed_url = args.url
    # Fill --twocaptcha-key / --cdp-endpoint / --proxy / --url from the
    # environment or .env when the flag was not given. An explicit flag wins.
    env_config.apply(args)
    # A WELLFOUND_URL from the environment or .env is a default target, not
    # a query the user typed, so it yields to the role flags and to an
    # explicit --mode job/jobs. Without this, a copied .env.example made
    # `--role X` and `--mode jobs` exit 2 as if --url had been typed with them.
    if not typed_url and args.url and (
            args.role or args.location or args.remote
            or (args.mode in ("job", "jobs")
                and mode_for_url(args.url) not in (None, args.mode))):
        logger.info("Not using WELLFOUND_URL from the environment: the "
                    "command line selects the query.")
        args.url = None

    # Spelled identically to the other two engines.
    if args.url and (args.role or args.location or args.remote):
        conflicting = [name for name, value in
                       (("--role", args.role), ("--location", args.location),
                        ("--remote", args.remote)) if value]
        p.error("--url already carries the whole query; %s would have to "
                "agree with it and nothing here checks that they do. Pass "
                "either a URL or the role flags, not both."
                % ", ".join(conflicting))

    if not args.url and args.role:
        if args.mode == "job":
            p.error("--mode job needs a --url: a job is one page at one "
                    "address, and --role/--location describe a listing.")
        if args.mode == "jobs":
            p.error("--mode jobs reads /jobs, which takes no role or "
                    "location. Drop --role, or use --mode role.")
        args.url = role_url(args.role, location=args.location,
                            remote=args.remote)
        logger.info("Built the listing URL from --role/--location: %s", args.url)

    if not args.url and args.mode == "jobs":
        args.url = FEED_URL

    if not args.url:
        p.error("no --url given and no --role: pass a wellfound.com URL, or "
                "--role (with an optional --location) to build a landing "
                "page. WELLFOUND_URL in the environment or in .env works too.")

    supported, why = is_supported_url(args.url)
    if not supported:
        p.error(f"{args.url!r} {why}.")

    # The URL knows which mode it belongs to, so a disagreement is caught
    # here rather than producing zero rows from the wrong reader.
    url_mode = mode_for_url(args.url)
    if url_mode and url_mode != args.mode:
        p.error(f"--mode {args.mode} does not match {args.url!r}, which is a "
                f"--mode {url_mode} address. A /role/… page and a "
                f"/jobs/{{id}}-{{slug}} page publish their data through "
                f"different mechanisms, so the wrong reader returns no rows "
                f"rather than failing.")

    if args.mode in ("job", "jobs") and args.pages != 1:
        logger.warning("--pages %d is ignored in --mode %s: there is one page "
                       "to read. In --mode jobs that is measured, not assumed "
                       "— `?page=2` on /jobs returns the identical rows as "
                       "page 1.", args.pages, args.mode)
        args.pages = 1

    if args.category is None:
        args.category = category_from_url(args.url)
    return args


if __name__ == "__main__":
    args = parse_args()
    try:
        sys.exit(scrape(args))
    except ProxyError as e:
        logger.error("%s", e)
        sys.exit(2)
    except Exception as e:
        # A remote browser that will not accept the connection is a REMOTE
        # API failure (exit 5), not a crash in this code (exit 1) and not bad
        # usage (exit 2). The distinction earns its keep on the commonest
        # one: `profile_locked` means another run still holds this `pid`, and
        # a harness that sees exit 1 goes looking for a bug in the scraper
        # instead of waiting or passing a different pid.
        text = _mask_credentials(str(e))
        if ("profile_locked" in text or "connect to --cdp-endpoint" in text
                or "rejected WebSocket connection" in text):
            logger.error("%s", text)
            sys.exit(EXIT_API_ERROR)
        raise
