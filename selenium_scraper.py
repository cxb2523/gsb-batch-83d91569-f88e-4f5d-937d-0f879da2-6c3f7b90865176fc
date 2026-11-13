#!/usr/bin/env python3
"""
kose-scraper — Selenium edition
================================
The same scrape as `playwright_scraper.py`, driven by Selenium. Kept at
parity in behaviour rather than in priority: all three engines must agree on
exit codes, run status, and whether a run crashes or spends money. Verified on 2026-09-18 by running all three against the same two pages
of `/c/c15/` — **48 of 48 rows identical** on sku, price, brand and stock.

Read `playwright_scraper.py`'s docstring for what this site is and what is
odd about it. Two limits are this engine's own and belong in a README rather
than in a surprise:

* **It cannot use an authenticated remote CDP endpoint.** chromedriver's
  `debuggerAddress` takes a bare `host:port` with nowhere to put a password,
  while Playwright's `connect_over_cdp` and pyppeteer's `browserWSEndpoint`
  both authenticate on the WebSocket upgrade. So `--cdp-endpoint` against the
  Scraping Browser API is a Playwright or pyppeteer job.

* **`--proxy-server` cannot authenticate at all.** Credentials are stripped
  and a warning is printed rather than letting anyone believe a `user:pass`
  URL is doing something.

One measurement worth carrying: on the same listing this engine reports
**107** product-shaped links where Playwright reports 57, because more of the
page's own JavaScript has run by the time the DOM is read. Both parse the
same **24** rows, because rows come from tiles and not from links — which is
the whole argument for tile scoping, visible as a number.
"""

import argparse
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse, urlsplit, quote

from selenium import webdriver
from selenium.common.exceptions import (TimeoutException, WebDriverException,
                                        JavascriptException)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

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
logger = logging.getLogger("selenium_scraper")

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


PAGE_LOAD_TIMEOUT = 60
SCRIPT_TIMEOUT = 30

# Chromium's own names for "the proxy is the problem, not the site". A dead
# proxy and a slow page want opposite responses — a different exit versus
# another try at the same one — so they are told apart by the error text.
_PROXY_ERROR_MARKERS = (
    "ERR_PROXY_CONNECTION_FAILED", "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_PROXY_AUTH_UNSUPPORTED", "ERR_PROXY_AUTH_REQUESTED",
    "ERR_UNEXPECTED_PROXY_AUTH", "ERR_PROXY_CERTIFICATE_INVALID",
)


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
    # The CATEGORY'S OWN DEFAULT ordering, read off the page — NOT what was
    # than echoed from the request.
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

    `driver.capabilities["browserVersion"]` is the installed Chrome's version,
    so the claim matches what the JS engine and the TLS handshake report. A
    hardcoded number drifts the moment Chrome updates, and claiming an older
    Chrome than everything else reports is itself a signal.
    """
    return (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{version} Safari/537.36")


def _cdp_host_port(endpoint: str) -> str:
    """`host:port` for chromedriver's debuggerAddress, or exit 2 with a reason.

    chromedriver takes a bare address here and cannot send credentials, so an
    endpoint that carries them cannot work through this engine. Refused up
    front: connecting anyway would fail somewhere further in with an error
    that names none of this.
    """
    parts = urlsplit(endpoint if "//" in endpoint else f"//{endpoint}")
    if parts.username or parts.password:
        logger.error(
            "This --cdp-endpoint carries credentials (%s), and Selenium cannot "
            "send them: chromedriver's debuggerAddress is a bare host:port. "
            "Use playwright_scraper.py or puppeteer_scraper.py for a "
            "credentialed endpoint such as the Scraping Browser API — both "
            "authenticate on the WebSocket upgrade.",
            _mask_credentials(endpoint))
        sys.exit(2)
    host = parts.hostname or endpoint
    port = f":{parts.port}" if parts.port else ""
    return f"{host}{port}"


class _Session:
    """One Chrome driver, relaunchable onto a different exit.

    Same contract as the Playwright engine's _BrowserSession, including the
    rule that a rotation means a genuinely FRESH browser — and a
    fresh browser is also the only thing that re-rolls the served page
    fresh cookie jar is what an ordinary user on another network looks like.
    """

    def __init__(self, args, pool):
        self.args, self.pool = args, pool
        self.remote = bool(args.cdp_endpoint)
        self.driver = None

    def open(self):
        options = Options()
        if self.remote:
            options.debugger_address = _cdp_host_port(self.args.cdp_endpoint)
            logger.info("Attaching to an existing browser at %s.",
                        options.debugger_address)
            # No UA, no proxy, no fingerprint on this path: the remote browser
            # brings its own, and stacking a second creates a contradiction
            # rather than better cover.
            self.driver = webdriver.Chrome(options=options)
            self._apply_timeouts()
            return self

        if self.args.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1600,1000")
        # Not a fingerprint measure, a correctness one: without it Chrome
        # advertises "HeadlessChrome", which is a giveaway on any site with
        # a bot manager in front of it.
        options.add_argument("--disable-blink-features=AutomationControlled")
        # Flag parity with the Playwright engine, and really applied rather
        # than accepted and ignored: Chrome takes the locale as --lang. It
        # does NOT decide which market is read — this site is one Japanese
        # market — so this only affects what the browser claims about
        # itself.
        options.add_argument(f"--lang={BROWSER_LOCALE}")

        if self.pool:
            scrubbed, credentials = split_credentials(self.pool.current)
            options.add_argument(f"--proxy-server={scrubbed}")
            logger.info("Using proxy exit %s", mask(self.pool.current))
            if credentials:
                logger.warning(
                    "This proxy has credentials and SELENIUM CANNOT SEND "
                    "THEM: --proxy-server accepts an address only, and there "
                    "is no Selenium equivalent of pyppeteer's "
                    "page.authenticate. They have been stripped, so requests "
                    "will go out unauthenticated and the exit will most "
                    "likely refuse them. Use playwright_scraper.py or "
                    "puppeteer_scraper.py for an authenticated proxy.")

        self.driver = webdriver.Chrome(options=options)
        self._apply_timeouts()

        version = self.driver.capabilities.get("browserVersion", "")
        if version:
            # Set over CDP rather than as a launch switch, so it can use the
            # version the driver actually reports.
            try:
                self.driver.execute_cdp_cmd(
                    "Network.setUserAgentOverride",
                    {"userAgent": _chrome_ua(version)})
            except WebDriverException as e:
                logger.debug("Could not override the user agent: %s", e)

        if self.args.fingerprint:
            self._apply_fingerprint()
        return self

    def _apply_timeouts(self):
        # Explicit, because a driver that stops answering otherwise hangs the
        # run: "every remote call is bounded" applies to this engine too.
        self.driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        self.driver.set_script_timeout(SCRIPT_TIMEOUT)

    def _apply_fingerprint(self):
        from fingerprint_client import get_fingerprint, playwright_init_script
        fp = get_fingerprint(self.args.twocaptcha_key, tags=self.args.fp_tags,
                             country=self.args.fp_country)
        ua = (fp.get("userAgent") or {}).get("value")
        script = playwright_init_script(fp)
        try:
            if ua:
                self.driver.execute_cdp_cmd("Network.setUserAgentOverride",
                                            {"userAgent": ua})
            # The same patch script the Playwright engine installs on its
            # context. Shared deliberately: two engines applying different
            # halves of one fingerprint would be a contradiction of exactly
            # the kind a fingerprint is meant to avoid.
            self.driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument", {"source": script})
            logger.info("Using 2captcha fingerprint %s (%s)", fp.get("id"),
                        fp.get("country"))
        except WebDriverException as e:
            logger.warning("Could not apply the fingerprint over CDP (%s) — "
                           "continuing without it.", e)

    def relaunch(self):
        if self.remote:
            return
        self.close()
        self.open()

    def close(self):
        try:
            if self.driver is not None:
                # quit(), not close(): close() ends one window and leaves the
                # driver process running, which on a per-page rotation would
                # leak a chromedriver per page.
                self.driver.quit()
        except Exception as e:  # noqa: BLE001 — teardown must not mask the reason we're here
            logger.debug("Ignoring error during driver teardown: %s", e)


# ---------------------------------------------------------------------------
# page_flow, bound to Selenium
# ---------------------------------------------------------------------------
# Only "how to ask this driver" lives here. Note the JS dialect: Selenium's
# execute_script runs a function BODY and needs an explicit `return`, unlike
# the `() => expr` both other engines take — which is why page_flow names
# operations instead of passing JavaScript.
def _driver(session):
    driver = session.driver

    def count(selector):
        try:
            return len(driver.find_elements(By.CSS_SELECTOR, selector))
        except WebDriverException as e:
            logger.debug("count(%s) failed: %s", selector, e)
            return 0

    def sleep(ms):
        time.sleep(ms / 1000.0)

    def content():
        try:
            return driver.page_source
        except WebDriverException as e:
            # A URL canonicalisation can navigate, so a snapshot can land on
            # the document swap. None tells the caller to skip a check rather
            # than fail the run.
            logger.debug("page_source unavailable (page navigating?): %s", e)
            return None

    def current_url():
        try:
            return driver.current_url
        except WebDriverException:
            return ""

    # No scroll primitive, and its absence is measured rather than
    # forgotten: this site serves its whole grid in the first response, so
    # there is nothing to scroll into view. Mirrors the Playwright engine.
    return {"count": count, "sleep": sleep, "content": content,
            "current_url": current_url}


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
    """What the parser is given for this address.

    A PAGE is read with `page_source`. The ENDPOINT answers with JSON, which
    Chromium wraps in its own JSON-viewer markup — so `page_source` there
    returns the viewer's HTML and the payload would be unreachable. Reading
    the body text gives back exactly what the server sent.

    Note the JS dialect: a function BODY with an explicit `return`, not the
    arrow expression the other two engines pass. That difference is exactly
    why no JavaScript crosses the page_flow boundary.
    """
    if _is_endpoint(url):
        try:
            return session.driver.execute_script(
                "return document.body.innerText;") or ""
        except WebDriverException as e:
            logger.warning("Could not read the endpoint response: %s", e)
            return None
    return _driver(session)["content"]()


def handle_captcha_if_present(session, args, budget) -> bool:
    """Detect and solve a challenge. True if something was solved.

    Same detectors, same reconciliation and the same "detected is not
    blocking" rule as the Playwright engine — the three must agree about
    when a run spends money.

    NOTE nothing has needed this yet: no refusal of any shape and no
    403 carrying its own error page with no challenge on it, so no solve
    applies there and none is attempted. See product_parser.detect_page_state.
    """
    driver = session.driver
    d = _driver(session)
    html = d["content"]()
    if html is None:
        return False

    selector = page_flow.ready_selector(args.mode)
    already_rendered = d["count"](selector)
    when_blocked = getattr(args, "solve_captcha", "when-blocked") == "when-blocked"

    html_challenge = detect_recaptcha_v3(html, d["current_url"]())
    runtime_challenge = detect_recaptcha_in_page(
        lambda js: driver.execute_script(f"return ({js})();"),
        page_url=d["current_url"]())
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
    try:
        driver.execute_script(f"return ({INJECT_TOKEN_JS})(arguments[0]);", token)
    except WebDriverException as e:
        logger.error("Could not inject the token (%s).", e)
        return False
    logger.info("Token injected. Reloading page to continue.")
    time.sleep(1.5)
    driver.refresh()
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

    Kept structurally parallel to its twins on purpose — "all three engines
    agree" is checked by reading them side by side as well as by the smoke
    suite.
    """
    outcome = PageOutcome(page_num=page_num, url=url)
    d = _driver(session)
    html, state, load_failed = None, "ok", False

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
    # No `http_status` here, and its ABSENCE is the finding rather than an
    # oversight: `driver.get()` returns None and WebDriver exposes no HTTP
    # status at all, so this engine cannot thread one however carefully its
    # twins do. Rather than leave it worse informed than they are — the
    # drift a shared module exists to prevent — the classifier falls
    # back to `product_parser.status_from_body`, which reads the status this
    # site states in its own error page (`<title>404- …`). Measured
    # 2026-09-18: that is what makes all three engines agree on a 404 rather
    # than two of them being better informed than the third.

    for block_attempt in range(block_retries + 1):
        # Logged before the load loop, which is fine now that --retries
        # cannot be 0: with 0 this line announced a fetch the loop then never
        # made, so the log itself corroborated the wrong conclusion.
        logger.info("Fetching page %d/%d: %s", page_num, args.pages, url)
        load_failed, exit_failed = False, None
        for attempt in range(1, args.retries + 1):
            try:
                session.driver.get(url)
                load_failed = False
                break
            except (TimeoutException, WebDriverException) as e:
                text = str(e)
                reason = next((m for m in _PROXY_ERROR_MARKERS if m in text), "")
                load_failed = True
                if reason:
                    exit_failed = reason
                    break  # a different exit is the only thing that helps
                if attempt < args.retries:
                    pause = args.retry_delay * (2 ** (attempt - 1))
                    logger.warning("Failed to load %s (attempt %d/%d: %s) — "
                                   "retrying in %.1fs.", url, attempt,
                                   args.retries, text[:120], pause)
                    time.sleep(pause)

        if exit_failed and has_pool and block_attempt < block_retries:
            logger.warning("Exit %s is unusable (%s) — rotating to another "
                           "one (%d/%d).", mask(pool.current), exit_failed,
                           block_attempt + 1, block_retries)
            pool.advance(f"unusable exit: {exit_failed}")
            session.relaunch()
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
        state = page_flow.classify(html, None, d["current_url"]())

        # This site server-renders its data, so a listing is parseable in the
        # FIRST response and there is nothing to wait for on a healthy page.
        # Measured with no pause at all after the load. The wait below is
        # only for the state that says the site served SOMETHING that is not a
        # payload. Mirrors playwright_scraper exactly.
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
            state = page_flow.classify(html, None, d["current_url"]())

        # The paid path is reached only for state "challenge" — a rendered
        # widget, which IS a test. It is NOT reached for "blocked": a hard
        # refusal carries no widget and no sitekey, so a solve there would be
        # a charge for nothing.
        # Bounded by SOLVES_PER_PAGE. Mirrors playwright_scraper.
        if page_flow.should_solve(state):
            if handle_captcha_if_present(session, args, budget):
                time.sleep(1)
                html = d["content"]() or html
                state = page_flow.classify(html, url=d["current_url"]())
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
                d = _driver(session)

    if load_failed:
        logger.error("Gave up loading %s after %d attempt(s).", url, args.retries)
        outcome.load_failed = True
        return outcome

    outcome.state = state

    if state == "blocked":
        # No refusal of any shape has been observed on this site — see
        # playwright_scraper's twin of this block. This is the HARD refusal:
        # no widget, no sitekey, nothing a key could buy.
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
        outcome.final_url = d["current_url"]()
        return outcome

    # No readiness wait and no scroll on the content path, and their absence
    # is MEASURED rather than forgotten — see the "unknown" branch above.
    # Mirrors playwright_scraper.

    if args.dump_html:
        dump_path = (args.dump_html if args.pages == 1
                     else f"{args.dump_html}.page{page_num}")
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("Saved the snapshot the parser sees to %s (%d bytes).",
                    dump_path, len(html))

    # Only when the page is NOT already content. A challenge marker on a
    # page whose products have rendered guards nothing — and over
    # --cdp-endpoint the Scraping Browser's own auto-solve extension injects
    # such markers into every page it loads.
    # Only for a state page_flow already counts as BLOCKED. An EMPTY page is
    # a correct answer, and a live run of tokopedia-scraper's /p/<slug> hub
    # reported exit 3 on a page that site had plainly served because its own
    # performance script names `akamaihd.net`. Mirrors playwright_scraper
    # exactly.
    vendor = (detect_bot_challenge(html, url=d["current_url"]())
              if page_flow.counts_as_blocked(state) else None)
    if vendor:
        debug_html = f"{args.out}_page{page_num}_debug.html"
        with open(debug_html, "w", encoding="utf-8") as f:
            f.write(html)
        try:
            session.driver.save_screenshot(f"{args.out}_page{page_num}_debug.png")
        except WebDriverException as e:
            logger.warning("Could not capture screenshot: %s", e)
        logger.error("Blocked by %s before parsing (%d bytes) — saved to %s. "
                     "This is exit 3, distinct from a genuinely empty result "
                     "(exit 4).", vendor, len(html), debug_html)
        outcome.blocked_by = vendor
        return outcome

    final_url = d["current_url"]() or url
    if not page_flow.should_parse(state):
        logger.info("Page %d came back as %s; nothing to parse.", page_num,
                    state)
        outcome.final_url = final_url
        return outcome

    products, listing = _parse_for_mode(html, final_url, args, page_num)
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
            session.driver.save_screenshot(f"{args.out}_page{page_num}_debug.png")
        except WebDriverException as e:
            logger.warning("Could not capture screenshot: %s", e)
        logger.warning("0 rows parsed — saved what the browser actually saw to "
                       "%s.", debug_html)

    outcome.products = products
    outcome.final_url = final_url
    return outcome


def scrape(args) -> int:
    _started = time.monotonic()
    outcomes: List[PageOutcome] = []
    seen_keys = set()
    blocked = False
    # All three modes are one row per product-at-a-location, so `sku` is the
    # key for all of them.
    dedupe_key = "sku"
    # Only --mode profile is single-page. Both listing modes paginate
    # identically, so neither may be treated as single-page — that is the
    # silent-success failure this family exists to avoid.
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

    session = None
    try:
        session = _Session(args, pool).open()

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
            # site publishes in its own `rel=next`. Mirrors
            # playwright_scraper._plan_page_urls.
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
    # NOT "pages x rows-per-page" as a hard expectation, even though the
    # page size is fixed at 15: the LAST page of a listing is legitimately
    # short. Mirrors playwright_scraper.
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
                "short page that is not the last one is a truncated "
                "response.",
                ", ".join(str(p) for p, _ in thin), fullest,
                ", ".join("page %d: %d" % (p, n) for p, n in thin))

    ok_pages = [o for o in outcomes if o.ok]
    failed_pages = [o.page_num for o in outcomes if not o.ok]
    final_url = (max(ok_pages, key=lambda o: o.page_num).final_url
                 if ok_pages else args.url)

    # One-per-run context, in the sidecar rather than repeated down a column.
    # Byte-identical in shape to the other two engines: the site's own arithmetic,
    # which is what lets a consumer tell a complete-but-capped run from one
    # that covered the whole result set.
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
        _v = _pkg_version("selenium")
    except Exception:  # noqa: BLE001 — a version is never worth a crash
        _v = None
    _run_facts = {"engine": "selenium", "engine_version": _v,
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
        description="Maison KOSE scraper (Selenium edition)")
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
        logger.error("--fingerprint needs --twocaptcha-key.")
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
        if "profile_locked" in text or "connect to --cdp-endpoint" in text:
            logger.error("%s", text)
            sys.exit(EXIT_API_ERROR)
        raise
