#!/usr/bin/env python3
"""
kose-scraper — pyppeteer edition
=================================
The same scrape as `playwright_scraper.py`, driven by pyppeteer. Kept at
parity in behaviour rather than in priority: verified on
2026-09-18 by running all three engines against the same two pages of
`/c/c15/` — **48 of 48 rows identical** on sku, price, brand and stock.

Read `playwright_scraper.py`'s docstring for what this site is and what is
odd about it.

pyppeteer is effectively unmaintained and its own README points at
Playwright. It is here because this family keeps three engines and because it
CAN authenticate against a remote CDP endpoint, which the Selenium engine
cannot. Prefer Playwright unless you have a reason not to.

Its driver is imported at MODULE level on purpose. An engine that imports its
driver inside the launch path imports cleanly with the library absent, so the
offline suite never records a skip and the CI job that exists to fail on
unexpected skips cannot catch a broken import. The suite
asserts the module-level import with an `ast` walk, because this drifts back
silently.
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
from urllib.parse import urlparse, urljoin, parse_qsl, quote

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
                            CaptchaUnsolvable, INJECT_TOKEN_JS)
from product_parser import (PAGE_SIZE, canonical_url, category_from_url,
                            page_number_from_url,
                            detect_bot_challenge, is_listing_url,
                            is_product_url, is_supported_url, page_url,
                            parse_listing, parse_product_detail,
                            parse_products, product_link_count,
                            references_own_assets, route_of, tags_from_url,
                            total_pages)
from output_writer import (dedupe_by_key, finish_run, EXIT_API_ERROR,
                           SOURCE_DEFAULT)
import page_flow
from page_flow import MIN_CARD_MATCHES
from proxy_pool import (from_args as proxy_pool_from_args, mask, ROTATE_MODES,
                        ProxyError, split_credentials)
import env_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("puppeteer_scraper")

# The browser locale the engines present. A constant rather than a flag:
# maison.kose.co.jp is a single Japanese market — no hreflang set, no /en/
# route, every price in JPY — so a --locale would be a setting that changes
# nothing, which is the failure the loader's warning exists for. Sending ja-JP is also the
# honest value: claiming en-US while reading a Japanese storefront is itself
# a mismatch between what the browser says and what it is doing.
BROWSER_LOCALE = "ja-JP"

ITEM_LINK_SELECTOR = page_flow.READY_SELECTOR_LISTING

# The share of rows that must carry the columns this site populates on every
# listing row. Measured over 171 listing rows across 8 captures on three
# routes (2026-09-18): title, url, sku, brand, currency, image_url, price and
# tax_rate on 171 of 171, reproduced as 72 of 72 on a live 3-page run.
#
# Deliberately NOT here: `badges`, on 21% of rows because most products carry
# no merchandising flag, and the four detail-only columns, null on every
# listing row by design.
CORE_FIELD_FLOOR = 99
CORE_FIELDS = ("title", "url", "sku", "brand", "currency")

# `image_url` is REPORTED and also floored here, which is the opposite of
# what montblanc-scraper does and is a measurement rather than a copy: every
# tile on this site carries a `/img/goods/` thumbnail, 171 of 171 in the
# captures and 72 of 72 on a live run. The first version of the parser read
# the tile's FIRST `<img>` and got the "NEW" badge on every row that had one
# — 100% coverage of the wrong value, which is exactly the failure a value check exists for
# by "assert VALUES on real fixtures, not coverage".

# The share of rows that must carry a usable price. Both `tile` and
# `jsonld` count, so this fires on a parsing break rather than on the
# site's own variety.
PRICE_COVERAGE_FLOOR = 95

# A page holding less than this share of the page size is reported as thin.
# The size is the site's fixed 24, so the only legitimately short page is the
# last one of a listing.
THIN_PAGE_SHARE = 0.6


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
    # The site's OWN arithmetic: the `N／Mページ` counter it prints on every
    # category page. Pages are planned from it, and that is load-bearing
    # rather than thrifty here — past its last page a category listing serves
    # that last page AGAIN, byte-identical, so an uncapped run collects
    # duplicates instead of reaching an empty page. None on a TAG listing,
    # which publishes no counter, and None means UNKNOWN rather than zero.
    pages_available: Optional[int] = None
    # The CATEGORY'S OWN DEFAULT ordering, not what the site applied (it
    # does not publish that). See product_parser.default_sort_rule.
    canonical: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not self.load_failed and self.blocked_by is None


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
        # and ignoring it. It does NOT decide which market is read: this
        # site is one Japanese market whatever the browser claims.
        launch_args = ["--no-sandbox", "--disable-dev-shm-usage",
                       f"--lang={BROWSER_LOCALE}"]
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
    # This site serves its whole grid in the first response. Mirrors the
    # other two engines.
    return {"count": count, "sleep": sleep, "content": content,
            "current_url": current_url}


def _content(session) -> Optional[str]:
    return _driver(session)["content"]()


def _parse_for_mode(html: str, url: str, args, page_num: int = 1):
    """(rows, listing) for this mode. `listing` is None in --mode product.

    The two entry points are separate on purpose and it is not tidiness. A
    product page carries 15 `div.c-product__item` staff-review cards and an
    `awoo-product-list` recommendation block, so a listing parser turned on
    one is exactly how a parser invents products. This repo's
    tile selector is element-qualified (`li.c-product__item`) and therefore
    sees zero of them, which `smoke_test.py` pins in both directions.

    `page_num` is threaded through rather than defaulted, because `position`
    restarts at 1 on every page: without the page number beside it, a row
    from page 2 claims the same position as one from page 1 and the two are
    indistinguishable in the output.
    """
    if args.mode == "product":
        rows = parse_product_detail(html, url, mode=args.mode)
        if args.category:
            for row in rows:
                row.category = args.category
        return rows, None
    listing = parse_listing(html, url, page=page_num, mode=args.mode)
    if args.category:
        for row in listing.rows:
            row.category = args.category
    return listing.rows, listing

def _is_endpoint(url: str) -> bool:
    """Whether this address answers with JSON rather than a page.

    Always False on Maison KOSÉ, and the function is kept rather than deleted
    because `_snapshot` branches on it and a sibling repo's version of this
    file does have a JSON route. Returning a constant with the reason beside
    it is honest; silently dropping the branch would make the engines diverge
    in shape for no reason.

    the rule is to ask what the front end calls before assuming a
    browser is needed, and that was done here first rather than last: the
    captures were grepped for `/api/`, `/graphql`, `__NEXT_DATA__` and
    `__PRELOADED_STATE__` and every one came back ZERO. This is an ASP.NET
    store that server-renders its grid into the first response, so there is
    no JSON route to prefer — which is also why a plain `curl` gets the whole
    catalogue page and why the browser engines are a convenience here rather
    than a necessity.
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


def handle_captcha_if_present(session, args, budget) -> bool:
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
    # The allowance is claimed here, immediately before the only paid
    # request, so a call that detected nothing has cost nothing.
    if not budget.claim():
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
    """The address this run actually fetches FIRST.

    Maison KOSE server-renders its catalogue and has no JSON endpoint to
    prefer over the rendered page, which was CHECKED rather than assumed
    (ask what the front end calls before assuming a browser).
    Grepped across the captures for `/api/`, `/graphql`, `__NEXT_DATA__` and
    `__PRELOADED_STATE__`: zero hits on every listing and product page.

    So it is the URL the user gave, VERBATIM — including its page number if
    it names one. An earlier version normalised `/c/c15_p10/` back to
    `/c/c15/`, which meant a run pointed at page 10 quietly returned page 1's
    products and reported success. That is this codebase's most common bug
    class, and the fix is simply to fetch what was asked for: the "page
    1 is fetched alone" is about the run's FIRST page deciding how far the
    rest can be addressed, not about the listing's first page.
    """
    return args.url


def _plan_page_urls(args, page_one_url: str,
                    pages_avail=None):
    """URLs for the pages after the first, decided once from what it reported.

    Counts from the page the run STARTED on rather than from 1: a run
    pointed at `/c/c15_p10/` with `--pages 3` reads 10, 11 and 12. The cap is
    the site's own `N／Mページ` counter where the route publishes one, applied
    to the absolute page number so the run stops at the real last page rather
    than after a fixed count.

    The convention is not guessed from the shape of page 1's URL: it is the
    one the site itself publishes in `<link rel="next">`, and `page_url`
    reproduces it byte for byte on both routes. That is the check required
    before trusting a constructed URL, and it matters here because getting it
    wrong is SILENT — `&pageno=2` and `&page=2` on a tag listing both return
    page 1 with HTTP 200.

    Capping is load-bearing rather than thrifty on this site: a category
    listing fetched past its last page returns THAT LAST PAGE AGAIN,
    byte-identical and HTTP 200, so an uncapped run collects duplicates
    instead of reaching an empty page. A tag listing publishes no counter and
    ends with a genuinely empty page, which is why the data-based stop stays
    in place for both.
    """
    planned = page_flow.pages_to_plan(args.pages, pages_avail,
                                      page_url_start(page_one_url))
    if planned.stop - 1 < page_url_start(page_one_url) + args.pages - 1:
        logger.info("The site reports %s page(s) for this listing and the run "
                    "asked for %d starting at %d. Stopping at %d: past the "
                    "end a category listing serves its LAST PAGE again rather "
                    "than an empty one, so the extra fetches would return "
                    "duplicates.", pages_avail, args.pages,
                    page_url_start(page_one_url), planned.stop - 1)
    # Page one is already fetched; this is 2..N of the run.
    return [page_url(page_one_url, n) for n in planned[1:]]


def page_url_start(url: str) -> int:
    """Which page the run was pointed at. 1 when the URL names none."""
    return page_number_from_url(url) or 1


class _SolveBudget:
    """The per-page allowance for paid solves. One counter, claimed
    IMMEDIATELY BEFORE the paid request is sent, and nowhere else.

    `handle_captcha_if_present` runs twice per attempt — once before the page
    is classified, so a challenge is cleared before anything is judged, and
    once after, for the state that says the page really is gated. Both calls
    take this object, and both claim from it only at the point where a task
    would really be submitted.

    Two earlier versions were each wrong in one direction. The first counted
    only the second call site, so the first repeated on every block-retry and
    one page could buy a solve per retry against a limit of one. The second
    counted every CALL, purchase or not: the pre-classification call, which
    on a normal page detects nothing and buys nothing, used up the whole
    allowance, so a challenge first seen after classification (a widget
    rendered late, or a page that only turns into a challenge after the
    readiness wait) was never offered to the solver and the page was
    reported as blocked.

    A claim that is then refused or fails at the solver still counts: it was
    a request sent, and possibly billed, and not counting it would reopen
    the overspend. Detecting nothing, finding the content already rendered
    or having no API key claims nothing.

    The allowance deliberately does NOT reset on retry or rotation: a fresh
    exit is a reason to re-fetch, not a fresh allowance to spend.
    """

    def __init__(self, limit: int):
        self.limit = limit
        self.spent = 0

    def claim(self) -> bool:
        """Count one purchase if the allowance permits it. False if not."""
        if self.spent >= self.limit:
            logger.info("Not attempting another solve on this page: %d of %d "
                        "already bought. A challenge that survives a solved "
                        "token is not one this run can pass, and a second "
                        "solve is a second charge for the same answer.",
                        self.spent, self.limit)
            return False
        self.spent += 1
        return True


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
    budget = _SolveBudget(page_flow.SOLVES_PER_PAGE)
    # The HTTP status the navigation returned. Threaded to the classifier:
    # this site answers a missing address with a bare page carrying no site
    # chrome, which without a status reads as "unknown" and RETRIES.
    http_status = None
    html, state, load_failed = None, "ok", False

    for block_attempt in range(block_retries + 1):
        # Logged before the load loop, which is fine now that --retries
        # cannot be 0: with 0 this line announced a fetch the loop then never
        # made, so the log itself corroborated the wrong conclusion.
        logger.info("Fetching page %d/%d: %s", page_num, args.pages, url)
        load_failed, exit_failed = False, None
        for attempt in range(1, args.retries + 1):
            try:
                response = bridge.run(page.goto(url, {"waitUntil": "domcontentloaded",
                                                      "timeout": 60000}))
                # None on a same-document navigation: no new response, so the
                # previous status stands. See the Playwright engine for why
                # discarding this is a defect rather than a tidiness matter.
                if response is not None:
                    http_status = response.status
                load_failed = False
                break
            except Exception as e:  # noqa: BLE001 — pyppeteer raises many types
                load_failed = True
                # pyppeteer surfaces a dead proxy as a page error whose text
                # carries Chromium's own name for it, exactly as Playwright
                # does; a timeout and an unusable exit want opposite
                # responses, so they are told apart by that text.
                text = str(e)
                if any(marker in text for marker in _PROXY_ERROR_MARKERS):
                    logger.warning("Exit %s is unusable (%s).",
                                   mask(pool.current) if pool else "(none)", text[:120])
                    exit_failed = text[:120]
                    break
                if attempt < args.retries:
                    pause = args.retry_delay * (2 ** (attempt - 1))
                    logger.warning("Failed to load %s (attempt %d/%d: %s) — "
                                   "retrying in %.1fs.", url, attempt,
                                   args.retries, text[:120], pause)
                    time.sleep(pause)

        # Rotate only for an unusable EXIT, and only when there is another
        # exit to rotate to — the same rule as the Playwright and Selenium
        # engines. With no --proxy, `pool` is None, and this branch used to
        # call `pool.advance` on it after any page that failed to load
        # `--retries` times: AttributeError, exit 1, instead of a load
        # failure. A repeated timeout is not a reason to change exits.
        if exit_failed and has_pool and block_attempt < block_retries:
            pool.advance(f"unusable exit: {exit_failed}")
            session.relaunch()
            bridge, page = session.bridge, session.page
            d = _driver(session)
            continue
        if load_failed:
            break


        # Routed through the budget like every other purchase. This
        # call used to be unguarded, which is how one page could buy
        # a solve per block-retry against a limit of one.
        if handle_captcha_if_present(session, args, budget):
            time.sleep(1)

        html = _snapshot(session, url) or ""
        state = page_flow.classify(html, http_status, page.url)

        # This site server-renders its data, so a listing is parseable in the
        # FIRST response. The wait below is only for the state that says the
        # served SOMETHING that is not the payload. Mirrors the other two
        # engines.
        if state == "unknown":
            wait_ms = page_flow.content_timeout_ms(args.mode)
            sel = page_flow.ready_selector(args.mode)
            need = page_flow.min_matches(args.mode)
            logger.info("Page %d is something the site served (%d bytes, its own "
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
            state = page_flow.classify(html, http_status, page.url)

        # Not reached for "blocked": a hard refusal carries no widget, so a
        # solve there would be a charge for nothing. Mirrors the other two
        # engines.
        #
        # The paid path is reached only for state "challenge", which no
        # capture of this site has ever produced. Wired up because a bot
        # manager can be switched on between deploys, and bounded by
        # SOLVES_PER_PAGE so a speculative path cannot become a bill.
        if page_flow.should_solve(state):
            if handle_captcha_if_present(session, args, budget):
                time.sleep(1)
                html = _content(session) or html
                state = page_flow.classify(html, http_status, page.url)
                if state == "content":
                    logger.info("The solve was accepted — page %d is content "
                                "now.", page_num)
                else:
                    logger.warning("The solve was NOT accepted: page %d is "
                                   "still %s. The purchase is spent.",
                                   page_num, state)

        if not page_flow.should_retry(state):
            # "content" and "empty" are both final answers. An empty page is
            # a CORRECT one — a bogus category id is served with no tiles — so retrying it
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
            else:
                # No pool, so nowhere else to go. The primary engine has had
                # this branch since the repo was written and its twins did
                # not: `mask(pool.current)` on a None pool raised
                # AttributeError and the run exited 1 — a CRASH reported for
                # a page that was merely blocked, which destroys the
                # blocked/empty/partial distinction the exit codes exist for.
                # Reproduced by forcing the blocked state with no --proxy.
                pause = args.retry_delay * (block_attempt + 1)
                logger.warning("Page %d came back as %s and there is no proxy "
                               "pool to rotate through — re-fetching through "
                               "the same access path in %.1fs (%d/%d).",
                               page_num, state, pause, block_attempt + 1,
                               block_retries)
                time.sleep(pause)
                bridge, page = session.bridge, session.page
            d = _driver(session)

    if load_failed:
        logger.error("Gave up loading %s after %d attempt(s).", url, args.retries)
        outcome.load_failed = True
        return outcome

    outcome.state = state

    if state == "blocked":
        # No refusal of any shape has been observed on this site — see
        # playwright_scraper's twin of this block. This is the HARD refusal.
        debug_html = f"{args.out}_page{page_num}_debug.html"
        with open(debug_html, "w", encoding="utf-8") as f:
            f.write(html or "")
        logger.error(
            "Maison KOSE did not serve this request — %d bytes, its own asset "
            "hosts referenced %d time(s), saved to %s. Nothing on this site "
            "has ever produced this state: measured 2026-09-18 from a "
            "datacentre address, a request with NO User-Agent at all is "
            "served the same 90,310 bytes as a browser, and 12 pages back to "
            "back were 12 x HTTP 200. So the first thing to check is the "
            "network path — a proxy, a captive portal, or DNS — not the "
            "site. Note this engine cannot use an authenticated remote CDP "
            "endpoint or an authenticated proxy; see the README's engine "
            "limits. This is exit 3, distinct from a genuinely empty result "
            "(exit 4).",
            len(html or ""), references_own_assets(html or ""), debug_html)
        outcome.blocked_by = "edge refusal" if html else "no-response"
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

    # Only for a state page_flow already counts as BLOCKED. An EMPTY
    # page is a correct answer, and a live run of tokopedia-scraper's
    # /p/<slug> hub reported exit 3 on a page that site had plainly served
    # because its own performance script names `akamaihd.net`. Mirrors
    # playwright_scraper exactly.
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
        logger.info("Page %d came back as %s; nothing to parse.", page_num,
                    state)
        outcome.final_url = page.url
        return outcome

    products, listing = _parse_for_mode(html, page.url, args, page_num)
    logger.info("Parsed %d row(s) from page %d.", len(products), page_num)

    if listing is not None:
        outcome.pages_available = listing.pages_available
        outcome.canonical = listing.canonical
        if page_num == 1:
            # Said once per run rather than per page. `pages_available` is
            # None on a TAG listing, which publishes no counter at all, and
            # None means UNKNOWN: the run then walks until a page adds no new
            # sku instead of planning.
            logger.info("Page 1: %s tile(s), %s product-shaped link(s), the "
                        "site reports %s. Canonical: %s",
                        listing.tiles_on_page, listing.product_links_on_page,
                        ("%s page(s)" % listing.pages_available)
                        if listing.pages_available
                        else "no page counter (a tag listing publishes none)",
                        listing.canonical or "none")

    # Tell a BROKEN PARSER apart from an EMPTY CATEGORY before anything
    # downstream reports "0 products" and sends the reader to check the URL.
    if not products and page_flow.looks_like_a_parse_failure(
            state, len(products), product_link_count(html or "")):
        links = product_link_count(html or "")
        dump = f"{args.out}_page{page_num}_debug.html"
        with open(dump, "w", encoding="utf-8") as f:
            f.write(html or "")
        logger.error(
            "Page %d links to %d product(s) and parsed to ZERO rows. "
            "The site served this page — this is a failure in THIS parser, "
            "not an empty category and not a block. Saved to %s; the first "
            "thing to check is the tile markup (li.c-product__item and its "
            "/g/g{SKU}/ link) — a listing carries no JSON-LD. Reported as stop_reason "
            "'parser_found_nothing' so it cannot be read as a complete run.",
            page_num, links, dump)
        outcome.state = "parse_failed"

    if products:
        images = sum(1 for row in products if row.image_url)
        if images < len(products):
            logger.info("Page %d: %d/%d rows carry an image. This site's "
                        "tiles carry a /img/goods/ thumbnail on every "
                        "measured page (171 of 171 in the captures), so a "
                        "gap here points at the tile markup.",
                        page_num, images, len(products))

        for field_name in CORE_FIELDS:
            filled = sum(1 for row in products
                         if getattr(row, field_name, None) not in (None, "", []))
            share = 100.0 * filled / len(products)
            if share < CORE_FIELD_FLOOR:
                logger.warning(
                    "Only %.0f%% of page %d carries `%s`, against a measured "
                    "floor of %d%%. All 171 listing rows across eight "
                    "captured pages had one, so this is the page shape moving "
                    "rather than the products being unusual.",
                    share, page_num, field_name, CORE_FIELD_FLOOR)

        priced = sum(1 for row in products if row.price is not None)
        price_share = 100.0 * priced / len(products)
        if price_share < PRICE_COVERAGE_FLOOR:
            logger.warning(
                "Only %.0f%% of page %d carries a price, against a measured "
                "floor of %d%%. Both the JSON-LD price and the DOM range "
                "count toward that, so a shortfall is a parsing break rather "
                "than the site's own variety.", price_share, page_num,
                PRICE_COVERAGE_FLOOR)

        if args.mode == "product":
            group = {row.variant_of for row in products if row.variant_of}
            logger.info("Product: %d row(s) for %s, %d priced.",
                        len(products), next(iter(group), products[0].sku),
                        priced)
        else:
            in_stock = sum(1 for row in products if row.in_stock is True)
            brands = len({row.brand for row in products if row.brand})
            logger.info("Page %d: %d row(s), %d priced, %d in stock, %d "
                        "brand(s). Tiles on the page: %s (a grid also carries "
                        "carousel links, which is why rows come from tiles "
                        "and not from links).",
                        page_num, len(products), priced, in_stock, brands,
                        listing.tiles_on_page if listing else "n/a")

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
    _started = time.monotonic()
    outcomes: List[PageOutcome] = []
    seen_keys = set()
    blocked = False
    # All three modes are one row per product-at-a-location.
    dedupe_key = "sku"
    # Only --mode product is single-page. A SHOP FRONT paginates exactly like
    # a category listing — ?page=N, the same tiles — and treating it as
    # single-page made `--mode shop --pages 2` fetch one page and report
    # "complete", which is the silent-success failure this family exists to
    # avoid. Found on the first live shop run.
    stop_reason = "single_page_mode" if args.mode == "product" else "completed"

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

    bridge = _AsyncBridge()
    session = None
    try:
        session = _Session(bridge, args, pool).open()

        target = _target_url(args)
        if target != args.url:
            # The only normalisation this site needs: a listing URL that
            # already names a page is reset to page 1, because page 1 is what
            # decides how far the rest can be addressed.
            logger.info("Normalised to page 1: %s", target)

        first = _fetch_one_page(session, args, pool, 1, target)
        outcomes.append(first)

        if not first.ok:
            stop_reason = ("page_load_timeout" if first.load_failed
                           else f"blocked_{first.blocked_by}")
            blocked = first.blocked_by is not None
        elif first.state == "not_found":
            # The address does not exist. A terminal answer about the URL
            # rather than about the catalogue, so the run stops here instead
            # of planning pages 2..N against something that will 404 too. Its
            # own stop_reason, because "no products" would send the reader to
            # check the parser when the thing to check is what they typed.
            stop_reason = "not_found"
            logger.error("%s does not exist — HTTP 404. Nothing was scraped. "
                         "On this site a bogus goods code or category id "
                         "answers 200 with an empty page instead, so a real "
                         "404 means the PATH is wrong, not the id.", first.url)
        elif first.state == "parse_failed":
            # Served, linked to products, parsed to nothing: OUR bug, and it
            # must not reach the sidecar as a complete run.
            stop_reason = "parser_found_nothing"
        elif args.mode != "product":
            seen_keys.update(p.sku for p in first.products if p.sku is not None)

            # Planned from the site's OWN page counter rather than chased
            # through next-links: a category listing prints `N／Mページ` on
            # every page, and `page_url` rebuilds exactly the convention the
            # site publishes in its own `rel=next`. Mirrors the other two
            # engines.
            #
            # The cap is load-bearing here rather than thrifty: past its last
            # page a category listing serves that LAST PAGE AGAIN, HTTP 200
            # and byte-identical, so an uncapped run fetches duplicates
            # forever instead of hitting an empty page.
            page_one = first.final_url or target
            planned = _plan_page_urls(args, page_one, first.pages_available)
            if len(planned) < args.pages - 1:
                stop_reason = "page_cap_reached"

            for index, url in enumerate(planned):
                page_num = index + 2
                if pool and pool.rotates_per_page():
                    pool.advance(f"per-page rotation, page {page_num}")
                    session.relaunch()

                outcome = _fetch_one_page(session, args, pool, page_num, url)
                outcomes.append(outcome)
                if not outcome.ok:
                    stop_reason = ("page_load_timeout" if outcome.load_failed
                                   else f"blocked_{outcome.blocked_by}")
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
    finally:
        if session is not None:
            session.close()
        bridge.close()

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
    pages_available = next((o.pages_available for o in outcomes
                            if o.pages_available is not None), None)
    canonical_seen = next((o.canonical for o in outcomes if o.canonical), None)
    if args.mode != "product" and all_rows:
        counts = [(o.page_num, len(o.products)) for o in outcomes if o.ok]
        fullest = max((n for _, n in counts), default=0)
        thin = [(p, n) for p, n in counts
                if fullest and n < THIN_PAGE_SHARE * fullest]
        last_page = max((p for p, _ in counts), default=0)
        thin = [(p, n) for p, n in thin if p != last_page]
        if thin:
            logger.warning(
                "Page(s) %s came back much thinner than the fullest page "
                "(%d rows): %s. This site serves a FIXED 24 per page, so a "
                "thin page that is not the last one did not fully arrive.",
                ", ".join(str(p) for p, _ in thin), fullest,
                ", ".join("page %d: %d" % (p, n) for p, n in thin))

    ok_pages = [o for o in outcomes if o.ok]
    failed_pages = [o.page_num for o in outcomes if not o.ok]
    final_url = (max(ok_pages, key=lambda o: o.page_num).final_url
                 if ok_pages else args.url)

    # One-per-run context, in the sidecar rather than repeated down a column.
    # Byte-identical in shape to the other two engines.
    extra = None
    if args.mode != "product":
        extra = {"pages_available": pages_available,
                 "page_size": PAGE_SIZE,
                 # The page the SITE says was read, which is not always the
                 # one that was asked for: the brand segment in a listing
                 # address selects nothing, so /site/xyz/c/c15/ is served
                 # happily and only the canonical says it was Cosme
                 # Decorte's. Recording it is what lets a reader tell two
                 # runs apart that differ only in a segment the site ignored.
                 "canonical_url": canonical_seen,
                 "route": route_of(final_url or args.url),
                 "tags": tags_from_url(final_url or args.url)}
        # No `capped_by_site` / `reachable_max`: this site imposes no page
        # cap (measured 2026-09-18: /c/c15/ stated 13 pages, 12 x 24 + 16), so
        # `pages_available` already says everything they would, and
        # pages x page_size would OVERSTATE a short last page.

    # Which engine ran, what version of its driver, and how long it took.
    # A sidecar that says only "complete" cannot answer "why is this run
    # slower than yesterday's" or "did the pyppeteer upgrade change
    # anything", and all three are one line each. Raised by a third-party
    # audit on 2026-10-13 and agreed with.
    try:
        from importlib.metadata import version as _pkg_version
        _v = _pkg_version("pyppeteer")
    except Exception:  # noqa: BLE001 — a version is never worth a crash
        _v = None
    _run_facts = {"engine": "puppeteer", "engine_version": _v,
                  "duration_seconds": round(time.monotonic() - _started, 1)}
    extra = {**(extra or {}), **_run_facts}

    return finish_run(all_rows, args.out, args.format, args.allow_empty,
                      blocked=blocked, stop_reason=stop_reason,
                      pages_requested=args.pages, pages_completed=len(ok_pages),
                      pages_failed=failed_pages, mode=args.mode,
                      source=SOURCE_DEFAULT,
                      start_url=args.url, final_url=final_url,
                      extra=extra)


def parse_args():
    p = argparse.ArgumentParser(
        description="Maison KOSE scraper (pyppeteer edition)")
    p.add_argument("--url", default=None,
                   help="A maison.kose.co.jp URL: a category listing "
                        "(/site/{brand}/c/cNN/), a tag listing "
                        "(/site/itemtags/list.aspx?tags=A,B) or one product "
                        "page (/site/{brand}/g/gSKU/) with --mode product. "
                        "NOTE the {brand} segment selects nothing — "
                        "/site/xyz/c/c15/ returns the same bytes as "
                        "/site/cosmedecorte/c/c15/ — so it is the cNN or the "
                        "gSKU that addresses anything. Optional: --category "
                        "or --tags build the URL instead. Also read from "
                        "KOSE_URL in the environment or in .env.")
    p.add_argument("--tags", default=None, metavar="A,B",
                   help="Kose's own facet tags, comma-separated, e.g. "
                        "'\\u30b7\\u30ef\\u6539\\u5584,\\u30b9\\u30ad\\u30f3\\u30b1\\u30a2'. Builds a "
                        "/site/itemtags/list.aspx URL, which is the one "
                        "listing route that crosses brands — a measured page "
                        "held five brands in 24 tiles. Ignored when --url is "
                        "given.")
    p.add_argument("--mode", choices=["listing", "product"],
                   default="listing",
                   help="listing (default): a category or tag listing page, "
                        "24 tiles each. product: one product page, which "
                        "emits ONE ROW and adds the columns a tile does not "
                        "carry — subcategory, volume, colour_count, "
                        "release_date — out of the page's own JSON-LD. "
                        "--pages applies to listing mode; there is one page "
                        "to read in product mode.")
    p.add_argument("--category", default=None,
                   help="Either a category id to build a URL from ('c15', "
                        "'c21'), used when no --url is given, or a label to "
                        "tag output rows with. The id is the ONLY thing that "
                        "selects a category on this site, which is why the "
                        "flag takes one rather than a brand name: "
                        "/site/cosmedecorte/c/c15/ and /site/xyz/c/c15/ are "
                        "the same page. Rows otherwise carry the cNN the URL "
                        "asked for.")
    p.add_argument("--pages", type=page_flow.at_least_one, default=1,
                   help="Number of listing pages to fetch. Applies to --mode "
                        "listing; ignored in --mode product. A category "
                        "page prints the site's own page counter, so a run "
                        "PLANS against the site's arithmetic rather than "
                        "walking off the end — past its last page a category "
                        "serves that last page again. There is no page cap "
                        "on this site, so a request is limited only by what "
                        "the category holds, and the sidecar records both "
                        "numbers.")
    p.add_argument("--delay", type=page_flow.non_negative_seconds, default=2.0, help="Delay between pages, seconds")
    p.add_argument("--concurrency", type=page_flow.at_least_one, default=1, metavar="N",
                   help="Fetch pages through N parallel workers (default 1 — "
                        "unchanged sequential behaviour). Each worker runs its "
                        "own browser and holds its own proxy exit, so N>1 "
                        "without --proxy-file just sends N times the traffic "
                        "from one address. Ignored with --cdp-endpoint.")
    p.add_argument("--retries", type=page_flow.attempts, default=3,
                   help=page_flow.RETRIES_HELP)
    p.add_argument("--retry-delay", type=page_flow.non_negative_seconds, default=2.0,
                   help="Seconds before the first page-load retry, doubling "
                        "thereafter (default 2.0)")
    p.add_argument("--format", choices=["json", "csv", "both"], default="both")
    p.add_argument("--out", default="kose_products", help="Output file prefix")
    p.add_argument("--proxy", default=None,
                   help="Proxy URL, e.g. http://ACCOUNT:PASSWORD@HOST:9999 "
                        "(2captcha.com/proxy)")
    p.add_argument("--proxy-file", default=None,
                   help="File with one proxy URL per line (# comments and blank "
                        "lines skipped) to rotate across. Wins over --proxy.")
    p.add_argument("--proxy-rotate", choices=list(ROTATE_MODES), default="per-run",
                   help="per-run (default): one exit for the whole run. per-page: "
                        "a new exit for every page — this is what spreads volume, "
                        "and it relaunches the browser each time so the session "
                        "does not follow the IP around.")
    p.add_argument("--proxy-shuffle", action="store_true",
                   help="Shuffle the pool at startup, so concurrent runs do not "
                        "all begin on the first exit in the file.")
    p.add_argument("--proxy-block-retries", type=page_flow.non_negative_int, default=2,
                   help="When a page comes back refused or behind a captcha, "
                        "retry it from this many OTHER exits before giving up "
                        "(default 2). Needs a pool of more than one; ignored "
                        "otherwise. No refusal has been observed on this site "
                        "from an ordinary datacenter address, so this is "
                        "insurance rather than a setting most runs need.")
    p.add_argument("--twocaptcha-key", default=None, help="2captcha.com API key")
    p.add_argument("--allow-empty", action="store_true",
                   help="Write output files even when 0 rows were found. Off by "
                        "default so a failed run can't overwrite a good result "
                        "with an empty one; exit code is 4 either way.")
    p.add_argument("--fingerprint", action="store_true",
                   help="Fetch a browser fingerprint from 2captcha's Fingerprint "
                        "API and apply it to the launched browser. Needs "
                        "--twocaptcha-key. Ignored with --cdp-endpoint, where the "
                        "Scraping Browser supplies its own.")
    # ONE OS-family tag, not a list — and the default is what makes
    # --fingerprint work at all. It shipped as "Windows,Chrome,Desktop" in
    # this family, which the API rejects with HTTP 400 ("Request parameters
    # are invalid"), so --fingerprint failed on every invocation. Measured
    # 2026-09-10: `Windows` succeeds, and `Windows,Chrome,Desktop`, `Chrome`
    # and `Desktop` each 400. fingerprint_client.py's own --tags help has
    # said so all along; the engines' default contradicted it.
    p.add_argument("--fp-tags", default="Windows",
                   help="ONE OS-family tag for the fingerprint filter: "
                        "Windows, Microsoft Windows or Android. NOT a list — "
                        "Chrome, Desktop and Mobile are each rejected by the "
                        "API with 400, and no combination is accepted. Use "
                        "--fp-country to narrow further. (default: Windows)")
    p.add_argument("--fp-country", default=None,
                   help="Fingerprint country, ISO 3166-1 alpha-2. Match it to "
                        "your proxy's exit country — a US fingerprint on a "
                        "German IP is a contradiction.")
    p.add_argument("--captcha-api", choices=["v2", "v1"], default="v2",
                   help="Which 2captcha solver API to use. v2 is the current "
                        "JSON API (api.2captcha.com/createTask); v1 is the "
                        "legacy in.php/res.php pair. Applies to both the image "
                        "captcha and reCAPTCHA.")
    p.add_argument("--solve-captcha", choices=["when-blocked", "always"],
                   default="when-blocked",
                   help="when-blocked (default): only pay to solve a "
                        "reCAPTCHA if the content is not already readable. "
                        "always: solve whenever one is detected. NO challenge "
                        "of any kind has been observed on this site — zero "
                        "reCAPTCHA, Turnstile, DataDome or PerimeterX markers "
                        "across every capture — so this path is wired up "
                        "because a bot manager can be switched on between "
                        "deploys, not because one is in the way today. It "
                        "also cannot touch the edge's own refusal, which "
                        "resets the connection rather than serving a page.")
    p.add_argument("--min-score", type=float, default=0.7,
                   help="reCAPTCHA v3 minimum score to request (0.3, 0.7 or 0.9 "
                        "— the API only accepts these three). Ignored for v2 "
                        "widgets.")
    p.add_argument("--cdp-endpoint", default=None,
                   help="Connect to an already-running browser over CDP instead "
                        "of launching Playwright's bundled Chromium, e.g. "
                        "ws://user:pass@host:port — the Scraping Browser API "
                        "endpoint, or any browser that exposes a CDP URL. "
                        "--proxy and --headless/--headful are ignored when this "
                        "is set.")
    p.add_argument("--dump-html", default=None, metavar="PATH",
                   help="Save the exact HTML the parser is given, on success as "
                        "well as failure. Useful when the row count is right but "
                        "a column comes back empty — see the README's 'Traps that look like bugs'.")
    p.add_argument("--chromium-path", default=None, metavar="PATH",
                   help="Use this Chromium/Chrome binary instead of the one "
                        "pyppeteer downloads on first run. Useful on a "
                        "machine that already has one, or where the download "
                        "is blocked.")
    p.add_argument("--headless", action="store_true", default=True)
    p.add_argument("--headful", dest="headless", action="store_false")
    args = p.parse_args()
    # What the USER typed, before the environment fills anything in.
    #
    # `env_config.apply` only fills UNSET values, so after it runs there is
    # no way to tell a --url from the command line apart from a KOSE_URL in
    # .env. The conflict check below used `args.url` and therefore refused
    # --tags and --category outright for anyone who had set that variable —
    # which `.env.example` ships and the README recommends, so the two flags
    # were unusable in exactly the setup this repo tells people to create.
    typed_url = args.url
    # Fill --twocaptcha-key / --cdp-endpoint / --proxy / --url from the
    # environment or .env when the flag was not given. An explicit flag wins.
    env_config.apply(args)

    # --url and the URL-building flags are two ways to say the same thing,
    # and only one of them may win. Refused rather than merged: a --tags that
    # disagreed with a URL already naming a facet would silently read a
    # different set of products than the address names.
    if typed_url and args.tags:
        p.error("--url already names what to fetch; --tags would have to "
                "agree with it. Pass either a URL or --tags, not both.")

    if not typed_url and args.tags:
        if args.mode == "product":
            p.error("--mode product needs a --url: a product is one page at "
                    "one address, and --tags describes a facet.")
        args.url = ("https://maison.kose.co.jp/site/itemtags/list.aspx?tags="
                    + quote(args.tags, safe=","))
        logger.info("Built the tag listing URL from --tags: %s", args.url)
    elif not typed_url and args.category:
        # `--category` is doing double duty — an id to build a URL from when
        # there is no --url, and a label to tag rows with when there is.
        # It takes the `cNN` id rather than a brand name because the id is
        # the only thing that addresses a category here: /site/xyz/c/c15/ and
        # /site/cosmedecorte/c/c15/ are byte-identical responses.
        if not re.fullmatch(r"c\d+", args.category):
            p.error("--category builds a URL from a category id like 'c15' "
                    "or 'c21'. %r is not one; pass a full --url if you meant "
                    "something else, or use --category as a row label "
                    "alongside --url." % args.category)
        args.url = f"https://maison.kose.co.jp/site/c/{args.category}/"
        logger.info("Built the listing URL from --category: %s", args.url)

    if not args.url:
        p.error("no --url given and no --tags/--category: pass a "
                "maison.kose.co.jp URL, or --category c15, or --tags with a "
                "facet. KOSE_URL in the environment or in .env works too.")

    supported, why = is_supported_url(args.url)
    if not supported:
        # Refused rather than attempted. This parser reads Maison KOSE's own
        # tile markup and its /c/cNN/ and /g/gSKU/ URL shapes; pointing it at
        # another site would not fail loudly, it would return zero rows and
        # look like an empty result. The REASON is given, because "is
        # not a Kose site" about kose.co.jp — which plainly is one — sends
        # the reader hunting a typo they did not make.
        p.error(f"{args.url!r} {why}.")

    if args.mode == "product" and not is_product_url(args.url):
        p.error(f"--mode product expects a product URL ending in /g/gSKU/; "
                f"{args.url!r} is not one. A listing is --mode listing.")
    if args.mode != "product" and is_product_url(args.url):
        p.error(f"{args.url!r} is a single product page. Use --mode product "
                f"for it, or pass a /c/cNN/ or /site/itemtags/list.aspx URL.")

    if args.mode == "product" and args.pages != 1:
        # Said out loud rather than silently ignored: a user who passed
        # --pages 5 expects five pages of something.
        logger.warning("--pages %d is ignored in --mode product: there is one "
                       "page to read, and on this site one page is one row — "
                       "Kose publishes a single Product block per page, not a "
                       "ProductGroup. The run status will say "
                       "single_page_mode.", args.pages)
        args.pages = 1
    return args


if __name__ == "__main__":
    args = parse_args()
    if args.fingerprint and not args.twocaptcha_key:
        logger.error("--fingerprint needs --twocaptcha-key (the Fingerprint "
                     "API uses the same key, though it's a separate "
                     "subscription from solving).")
        sys.exit(2)
    if args.fingerprint and args.cdp_endpoint:
        logger.warning("--fingerprint is ignored with --cdp-endpoint: the "
                       "remote browser supplies its own.")
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
