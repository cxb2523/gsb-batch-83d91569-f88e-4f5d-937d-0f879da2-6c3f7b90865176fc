#!/usr/bin/env python3
"""
kose-scraper — Playwright edition (primary engine)
===================================================
Scrapes Maison KOSÉ (`maison.kose.co.jp`), Kosé's own online store:
category listings, tag listings, and product pages.

    --mode listing   (default)  /site/{brand}/c/cNN/           a category
                                /site/itemtags/list.aspx?tags= a tag facet
    --mode product              /site/{brand}/g/gSKU/          one product

Why this is not `kose.com`
--------------------------
`kose.com` resolves for nobody. Measured 2026-09-18: the .com registry
delegates it to `dns1/dns2.supremecenter.com`, both of which answer REFUSED
for the zone, so 8.8.8.8 and 1.1.1.1 both return SERVFAIL. It is a lame
delegation on a domain paid up to 2029 — not a site behind a bot manager.
Kosé's storefront is `maison.kose.co.jp`, which is where `www.kose.co.jp`
sends a visitor with its own meta refresh.

What is different about this site
---------------------------------
* **You need none of the paid products, and the README says so plainly
.** Measured 2026-09-18 from a datacentre address: `curl`,
  `python-requests` and a request with NO User-Agent header each got the
  same 90,310-byte listing; twelve pages back to back were twelve 200s; and
  thirteen captures carry zero captcha markers of any vendor. The captcha,
  proxy and fingerprint paths are all wired and all verified working — they
  simply buy nothing here today.

* **The brand segment in every URL is decorative.** `/site/xyz/c/c15/`
  returns byte-identical bytes to `/site/cosmedecorte/c/c15/`, and the page's
  own `rel=canonical` rewrites it. Only `cNN` and `gSKU` address anything, so
  `brand` is read from each TILE — a tag listing legitimately mixes eleven
  brands across 72 rows, measured on a live run.

* **A category listing walked past its end returns its LAST PAGE AGAIN.**
  Not a 404 and not an empty grid: `/c/c15_p14/` and `/c/c15_p15/` are both
  byte-identical to `/c/c15_p13/`. So the run plans against the site's own
  `N／Mページ` counter, and still stops on "this page added no new sku".
  A TAG listing ends with a genuinely empty page instead, and publishes no
  counter at all — two routes, two endings, one data-based stop.

* **Wrong pagination parameters fail SILENTLY.** `&pageno=2` and `&page=2`
  on a tag listing both return page 1 with HTTP 200. `page_url()` builds the
  convention the site publishes in its own `rel=next`, which is the check
  is required before trusting a constructed URL.

* **`li.` is load-bearing in the tile selector.** A product page reuses the
  class `c-product__item` on `<div>`s for staff-review cards — 15 on one
  measured page. The element-qualified selector sees zero of them.

* **There is one market.** No `hreflang`, no `/en/` route, every price in
  JPY, so there is no `--locale` to pass and no ordering control on either
  listing route, so there is no `--sort`. Both flags are ABSENT rather than
  inert.

Usage:

    python playwright_scraper.py \\
        --url "https://maison.kose.co.jp/site/cosmedecorte/c/c15/" --pages 3

    python playwright_scraper.py --tags "シワ改善,スキンケア" --pages 2

    python playwright_scraper.py --mode product \\
        --url "https://maison.kose.co.jp/site/onebykose/g/gMUSC/"
"""

import argparse
import logging
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse, urljoin, quote

from playwright.sync_api import (sync_playwright, Error as PWError,
                                 TimeoutError as PWTimeout)

from captcha_solver import (detect_recaptcha_v3, detect_recaptcha_in_page,
                            reconcile_detections, solve_recaptcha,
                            CaptchaUnsolvable, INJECT_TOKEN_JS,
                            RECAPTCHA_DISCOVERY_JS)
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
from proxy_pool import (from_args as proxy_pool_from_args, to_playwright, mask,
                        ROTATE_MODES, ProxyError, ProxyPool)
import env_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("playwright_scraper")

# The browser locale the engines present. A constant rather than a flag:
# maison.kose.co.jp is a single Japanese market — no hreflang set, no /en/
# route, every price in JPY — so a --locale would be a setting that changes
# nothing, which is the failure the loader's warning exists for. Sending ja-JP is also the
# honest value: claiming en-US while reading a Japanese storefront is itself
# a mismatch between what the browser says and what it is doing.
BROWSER_LOCALE = "ja-JP"


def _chrome_ua(chromium_version: str) -> str:
    """Build a desktop-Chrome UA naming the browser's OWN real version.

    Not a hardcoded version number: that drifts the moment a newer Chromium
    ships, and a UA claiming an older Chrome than what the JS engine, WebGL
    strings and TLS ClientHello all actually report is itself a mismatch a
    fingerprinter can key on.
    """
    return (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{chromium_version} Safari/537.36")


@dataclass
class PageOutcome:
    """What one page produced.

    Collected per page and merged afterwards rather than folded into shared
    state as the loop goes. Two reasons, and the second is the point:
    dedupe that mutates a running set inside the loop makes the OUTPUT depend
    on the order pages happen to arrive in — fine while that order is fixed,
    wrong the moment pages are fetched concurrently, because which page
    "claims" a duplicate sku (and so which `scraped_at` the row carries)
    would vary between runs of the same command. Merging afterwards in page
    order is deterministic regardless of arrival order.
    """
    page_num: int
    url: str
    final_url: Optional[str] = None
    products: List = field(default_factory=list)
    blocked_by: Optional[str] = None
    load_failed: bool = False
    # The page_flow state this page came back as ("content", "blocked",
    # "challenge", "empty", "unknown"). Carried so the caller can tell an
    # EMPTY page — an exhausted tag facet, a bogus goods code, or the site's
    # own 404 — from a page that FAILED. Both produce zero rows and they mean
    # opposite things.
    state: Optional[str] = None
    # The site's own page count, from the `N／Mページ` counter it prints in
    # the title and above the grid. This is the arithmetic pages are planned
    # from, and planning against it is load-bearing here rather than thrifty:
    # past its last page a CATEGORY listing serves that last page again,
    # byte-identical and HTTP 200, so an uncapped run fetches duplicates
    # forever instead of reaching an empty page.
    #
    # None on a TAG listing, which publishes no counter at all, and None
    # means UNKNOWN rather than zero — capping a tag run at zero pages would
    # turn a working route into an empty file.
    pages_available: Optional[int] = None
    # The page's own `rel=canonical`. Recorded because the brand segment in
    # a listing address selects nothing — /site/xyz/c/c15/ is served happily
    # — so the canonical is the only thing that says which listing was
    # really read.
    #
    # NOTE it is recorded for a LISTING and deliberately not used as a
    # product row's URL: 5 of 20 measured product pages canonicalise to a
    # DIFFERENT sku, a sibling size or shade. See product_parser.
    canonical: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not self.load_failed and self.blocked_by is None


ITEM_LINK_SELECTOR = page_flow.READY_SELECTOR_LISTING

# The share of rows that must carry the columns this site populates on every
# listing row, below which the read has broken rather than the data being
# unusual.
#
# Measured over 171 listing rows across 8 captures on three routes
# (2026-09-18): `title`, `url`, `sku`, `brand`, `currency`, `image_url`,
# `price` and `tax_rate` were populated on 171 of 171, and a live 3-page run
# reproduced 72 of 72. This site's tiles are unusually complete, so the floor
# can sit high without firing on healthy data.
#
# Deliberately NOT in this check: `badges`, present on 21% of rows because
# most products carry no merchandising flag, and the four detail-only columns
# (`subcategory`, `volume`, `colour_count`, `release_date`), which are null
# on every listing row by design.
CORE_FIELD_FLOOR = 99
CORE_FIELDS = ("title", "url", "sku", "brand", "currency")

# `image_url` is REPORTED and also floored here, which is the opposite of
# what montblanc-scraper does and is a measurement rather than a copy: every
# tile on this site carries a `/img/goods/` thumbnail, 171 of 171 in the
# captures and 72 of 72 on a live run. The first version of the parser read
# the tile's FIRST `<img>` and got the "NEW" badge on every row that had one
# — 100% coverage of the wrong value, which is exactly the failure a value check exists for
# by "assert VALUES on real fixtures, not coverage".

# The share of rows that must carry a usable price before the run is worth
# trusting as a PRICE run rather than merely as a catalogue listing. Both
# `tile` and `jsonld` count, so this fires on a parsing break, not on the
# site's own variety.
PRICE_COVERAGE_FLOOR = 95

# A page holding less than this share of the page size is reported as thin.
# The size is the site's fixed 24 (`product_parser.PAGE_SIZE`), and every
# captured full page held exactly it — so the only legitimately short page is
# the last one of a listing, which is why this can sit high without false
# alarms.
THIN_PAGE_SHARE = 0.6


# ---------------------------------------------------------------------------
# page_flow, bound to Playwright
# ---------------------------------------------------------------------------
# Every decision about WHAT to do with a page — how long to wait, when to
# scroll, when a fresh session is the only fix — lives in page_flow.py so all
# three engines make it identically. What lives here is only HOW to ask this
# particular driver. See page_flow's docstring for why that split exists.
def _driver(page):
    # Named OPERATIONS rather than JavaScript, and that is the point of the
    # split. Selenium's execute_script takes a function BODY with an explicit
    # `return` while Playwright and pyppeteer take `() => expr`, so a shared
    # module handing JS across this boundary would quietly acquire one
    # driver's dialect.
    #
    # There is no scroll primitive here, and its absence is measured rather
    # than forgotten (missing content is one of three things, so check
    # which before "fixing" it). Maison KOSÉ SERVER-RENDERS its grid: a plain
    # HTTP fetch with no JavaScript at all returns every `li.c-product__item`
    # tile of the page (24 on a full one). Everything the parser
    # wants is in the document before any scrolling could happen, on every
    # capture, so a scroll would be ceremony that looks load-bearing.
    return {
        "count": lambda selector: len(page.query_selector_all(selector)),
        "sleep": page.wait_for_timeout,
        "content": lambda: _content_when_settled(page),
        "current_url": lambda: page.url,
    }


def _ready_selector(args) -> str:
    return page_flow.ready_selector(args.mode)


def _min_matches(args) -> int:
    return page_flow.min_matches(args.mode)


def _classify(page, html: str, status=None) -> str:
    return page_flow.classify(html, status, page.url)

# Every readiness constant and every state policy lives in page_flow.py, with
# its measurement beside it. Nothing about WHAT to do with a page is
# duplicated here — this file only knows HOW to ask Playwright.


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

    Distinguishing this from an ordinary timeout matters because the two want
    opposite responses: a timeout deserves a retry from the same exit, while
    an unusable exit deserves a different exit — retrying it unchanged just
    spends the retry budget on a proxy that is not going to answer.
    """
    text = str(exc)
    for marker in _PROXY_ERROR_MARKERS:
        if marker in text:
            return marker
    return ""


def _launch_local(pw, args, pool):
    """Launch our own Chromium on `pool`'s current exit; return (browser, context, page).

    Factored out of scrape() so a proxy rotation can tear the whole browser
    down and call this again. Swapping the proxy under a live session would
    be cheaper and wrong: cookies a bot manager issued against one exit,
    replayed from another, are a stronger signal than either address alone.
    A rotation therefore means a genuinely fresh browser — new cookie jar,
    new storage — which is what an ordinary user on a different network
    looks like.
    """
    launch_kwargs = {"headless": args.headless}
    proxy = to_playwright(pool.current) if pool else None
    if proxy:
        launch_kwargs["proxy"] = proxy
        logger.info("Using proxy exit %s", mask(pool.current))

    browser = pw.chromium.launch(**launch_kwargs)
    # Only override the UA when we launched our own bundled Chromium.
    # Forcing a UA on a page reached via --cdp-endpoint mismatches the remote
    # browser's real TLS/JS fingerprint on purpose-matched values.
    ctx_kwargs = {"user_agent": _chrome_ua(browser.version), "locale": BROWSER_LOCALE}
    init_script = None
    if args.fingerprint:
        # Only meaningful on this branch. Over --cdp-endpoint the Scraping
        # Browser already has its own fingerprint, and layering a second one
        # on top produces a mismatch rather than better cover.
        from fingerprint_client import (get_fingerprint,
                                        playwright_context_kwargs,
                                        playwright_init_script)
        fp = get_fingerprint(args.twocaptcha_key,
                             tags=args.fp_tags, country=args.fp_country)
        ctx_kwargs.update(playwright_context_kwargs(fp))
        init_script = playwright_init_script(fp)
        logger.info("Using 2captcha fingerprint %s (%s)", fp.get("id"), fp.get("country"))

    context = browser.new_context(**ctx_kwargs)
    if init_script:
        # Must be installed on the context, before any page script runs.
        context.add_init_script(init_script)
    return browser, context, context.new_page()


class _BrowserSession:
    """One browser + context + page, relaunchable onto a different exit.

    Exists because a rotation replaces all three handles at once, and passing
    three mutable locals through every helper is how one of them ends up
    stale. It also gives a worker thread a single object to own: with
    Playwright's sync API, a browser and everything reachable from it belong
    to the thread that created them, so each worker builds its own.
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
        except Exception as e:  # noqa: BLE001 — teardown must not mask the reason we're here
            logger.debug("Ignoring error while closing browser for rotation: %s", e)
        self.open()

    def close(self):
        try:
            if self.remote:
                self.page.close()  # leave the remote browser app running
            else:
                self.browser.close()
        except Exception as e:  # noqa: BLE001
            logger.debug("Ignoring error during browser teardown: %s", e)


def _connect_remote(pw, args):
    """Attach to an already-running browser over CDP; return (browser, context, page)."""
    logger.info("Connecting to existing browser over CDP: %s",
                _mask_credentials(args.cdp_endpoint))
    # Explicit timeout. Playwright defaults to 30s here, but stating it makes
    # the contract visible next to the pyppeteer twin, which has no connect
    # timeout at all. A Scraping Browser session that is still held answers
    # with HTTP 500 rather than stalling, so this mostly guards against the
    # endpoint going quiet.
    try:
        browser = pw.chromium.connect_over_cdp(args.cdp_endpoint, timeout=30000)
    except (PWError, PWTimeout) as e:
        # Playwright puts the endpoint it tried into the exception text, and
        # the endpoint is a URL with the password in it. Unmasked, that
        # password lands in the terminal, in CI output and in any log the run
        # is piped to — which is the one thing this project promises does not
        # happen ("credentials never reach argv or logs"). The message is
        # rewritten with the credentials masked and the host and port kept,
        # because WHICH endpoint failed is the useful half and is not the
        # secret.
        raise PWError(
            f"could not connect to --cdp-endpoint "
            f"{_mask_credentials(args.cdp_endpoint)}: "
            f"{_mask_credentials(str(e))}\n"
            f"A Scraping Browser profile allows ONE live connection at a "
            f"time, so a 500 here usually means another run still holds this "
            f"`pid`. Wait for it to finish, or use a different pid."
        ) from None
    # Reuse the remote browser's existing context so its
    # fingerprint/session/proxy settings stay intact.
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.new_page()

    # The Scraping Browser API exposes a documented CDP domain
    # (`Captcha.setAutoSolve` / `Captcha.solve`) that clears supported
    # challenges inside the browser: https://2captcha.com/scraper/browser-api/api
    # Tried first when --cdp-endpoint is set; this script's own detect+solve
    # logic still runs as a fallback if the endpoint does not support it.
    # Note no refusal of any shape has been seen on this site, which is not a
    # and not even a page: the edge resets the connection, so there is no
    # markup for any solver to look at and no widget to solve. See
    # page_flow.classify_transport_error. This path exists for a challenge
    # the site does not render today — zero reCAPTCHA, Turnstile, DataDome
    # and PerimeterX markers across every capture — because a bot manager
    # can be switched on between deploys.
    try:
        cdp_session = context.new_cdp_session(page)
        cdp_session.send("Captcha.setAutoSolve", {"autoSolve": True, "options": [{"type": "*"}]})
        cdp_session.on("Captcha.detected", lambda *_: logger.info("[Scraping Browser] CAPTCHA detected on page."))
        cdp_session.on("Captcha.waitForSolve", lambda *_: logger.info("[Scraping Browser] CAPTCHA sent to 2captcha for solving."))
        cdp_session.on("Captcha.solveFinished", lambda *_: logger.info("[Scraping Browser] CAPTCHA solved automatically."))
        cdp_session.on("Captcha.solveFailed", lambda *_: logger.warning("[Scraping Browser] CAPTCHA auto-solve failed."))
        logger.info("Scraping Browser API Captcha.setAutoSolve enabled — supported "
                    "challenge types will be solved automatically if this "
                    "--cdp-endpoint is a Scraping Browser API session.")
    except Exception as e:
        logger.info("Captcha.setAutoSolve not available on this --cdp-endpoint (%s) — "
                    "relying on this script's own detect+solve logic instead.", e)
    return browser, context, page


def _resolve_pagination_url(base_url: str, href: str) -> str:
    """Resolve a pagination link's raw href against the page it came from.

    Playwright's get_attribute("href") returns the raw HTML attribute,
    unresolved — unlike the DOM .href property Puppeteer/Selenium read for
    the same purpose in this project, which the browser resolves for you.
    urljoin handles every shape correctly — absolute, protocol-relative,
    absolute-path, and page-relative hrefs alike.
    """
    return urljoin(base_url, href)


# Every `scheme://user:pass@` in a string, however many times it occurs.
# Matching globally rather than once is the point: a Playwright connection
# error repeats the endpoint five times (the message plus a four-line call
# log), so a masker that handled only the first occurrence would print the
# password four times and look like it was working.
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


def _content_when_settled(page, attempts: int = 4, pause_ms: int = 700):
    """page.content() that tolerates a page mid-navigation.

    Playwright raises `Page.content: Unable to retrieve content because the
    page is navigating and changing the content` if the document swaps under
    it. On THIS site that is a smaller risk than on its siblings and the
    difference is measured rather than assumed: maison.kose.co.jp does not
    geo-redirect — a German datacentre address and a Japanese exit are served
    the same Japanese pages at the same URLs — so the document does not swap
    under a run because of where it came from. It can still swap on the
    site's own canonicalisation, which is real here: the brand segment in an
    address is decorative and the page corrects it in `rel=canonical`.

    Retries briefly and returns None if the page won't hold still, so the
    caller can skip a check instead of failing the run.
    """
    for attempt in range(1, attempts + 1):
        try:
            return page.content()
        except PWError as e:
            if "navigating" not in str(e).lower():
                raise
            if attempt == attempts:
                logger.warning("Page kept navigating through %d attempts — "
                               "continuing without a snapshot.", attempts)
                return None
            logger.info("Page is navigating (a URL canonicalisation?) — "
                        "retrying content() in %dms (%d/%d).",
                        pause_ms, attempt, attempts)
            page.wait_for_timeout(pause_ms)
    return None


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


def _snapshot(page, url: str) -> Optional[str]:
    """What the parser is given for this address.

    Two shapes, because the two addresses answer with two things and
    Chromium does not hand them over the same way. A PAGE is read with
    `content()`. The ENDPOINT answers with JSON, which Chromium wraps in its
    own JSON-viewer markup — so `content()` there returns the viewer's HTML
    and the payload would be unreachable. `document.body.innerText` gives
    back exactly what the server sent.

    Getting this wrong is silent: the viewer markup parses as "not a listing
    payload", which reads as an empty result rather than as a bug.
    """
    if _is_endpoint(url):
        try:
            return page.evaluate("() => document.body.innerText") or ""
        except (PWError, PWTimeout) as e:
            logger.warning("Could not read the endpoint response: %s", e)
            return None
    return _content_when_settled(page)


def handle_captcha_if_present(page, args, budget) -> bool:
    """Detect and solve a challenge. True if something was solved.

    Runs after EVERY navigation, for ANY page — not scoped to one URL. The
    static-HTML and runtime reCAPTCHA detectors are run and reconciled
    against each other rather than short-circuited, because they can disagree
    about the variant and the parameters for one are rejected for the other.

    NOTE what this has had nothing to do yet. NO challenge of any kind has
    been observed on this site: zero reCAPTCHA, hCaptcha, Turnstile,
    DataDome, PerimeterX, Incapsula, Kasada and AWS WAF markers across all 13
    captures, no `data-sitekey` anywhere, and no refusal of any shape — a
    request with no User-Agent at all is served the same bytes as a browser.

    That is a statement about what this site renders TODAY, not a claim that
    a captcha here could not be solved. Nothing in this repo makes that
    claim: the family's notes record what it cost the family once, and the only
    sentence anyone is entitled to is which task type would be built.

    That is a statement about what the SITE renders, not about what can be
    solved (never write that a captcha cannot be solved — the only
    sentence anyone is entitled to is "this page carries no widget"). This
    path exists because a bot manager can be switched on between deploys, and
    because the family's rule is that detection stays broad:
    different geos and scenarios surface different challenges.
    """
    html = _content_when_settled(page)
    if html is None:
        # Couldn't get a stable snapshot — skip detection for this navigation
        # rather than taking the whole run down. The next navigation gets
        # another chance, and the parse below reads its own copy of the DOM.
        return False

    # Detected is not the same as blocking. A challenge on a page whose
    # products are already rendered guards nothing, and counting the anchors
    # is instant — no wait_for_function, no 20s — which is why this check
    # sits here rather than after the readiness wait. Doing it the other way
    # round would cost 20 wasted seconds on a page the captcha genuinely
    # gates, where solving FIRST is what makes the content appear.
    already_rendered = len(page.query_selector_all(_ready_selector(args)))
    when_blocked = getattr(args, "solve_captcha", "when-blocked") == "when-blocked"

    html_challenge = detect_recaptcha_v3(html, page.url)
    runtime_challenge = detect_recaptcha_in_page(
        lambda js: page.evaluate(js), page_url=page.url)
    challenge = reconcile_detections(html_challenge, runtime_challenge)
    if not challenge:
        return False

    if when_blocked and already_rendered > MIN_CARD_MATCHES:
        logger.info("%s detected via %s, but %d anchors are already on the "
                    "page — not solving it. Pass --solve-captcha always to "
                    "solve it anyway.", challenge.kind, challenge.source,
                    already_rendered)
        return False

    logger.warning("%s detected via %s (sitekey=%s, action=%s) — attempting to solve.",
                   challenge.kind, challenge.source, challenge.sitekey, challenge.action)
    if not args.twocaptcha_key:
        logger.warning("No 2captcha API key, so this challenge cannot be "
                       "solved — continuing with whatever the page already "
                       "holds.")
        return False
    # The allowance is claimed here, immediately before the only paid
    # request, so a call that detected nothing has cost nothing.
    if not budget.claim():
        return False
    try:
        token = solve_recaptcha(challenge, args.twocaptcha_key,
                               api_version=args.captcha_api,
                               min_score=args.min_score)
    except Exception as e:  # noqa: BLE001 — a solver failure is not a crash
        logger.error("Solving the challenge failed (%s) — continuing with "
                     "whatever the page holds.", e)
        return False

    page.evaluate(INJECT_TOKEN_JS, token)
    logger.info("Token injected. Reloading page to continue.")
    page.wait_for_timeout(1500)
    page.reload(wait_until="domcontentloaded", timeout=60000)
    return True


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
    """Fetch and parse one page. Retries, rotations and debug dumps live here.

    Returns a PageOutcome and never raises for an EXPECTED failure — a
    timeout, a 403 refusal, a captcha page, a dead exit are all recorded on the
    outcome instead. What the run should do about them differs between the
    sequential and concurrent paths, so that decision belongs to the caller
    rather than to a raised exception unwinding through it.

    Always goes through `session.page`, never a captured local: a rotation
    replaces the browser, context and page together, and a stale handle is
    exactly the bug _BrowserSession exists to prevent.
    """
    outcome = PageOutcome(page_num=page_num, url=url)

    # How many times a blocked page may be retried.
    #
    # With a pool, each retry moves to a DIFFERENT exit and the budget is the
    # user's `--proxy-block-retries`. WITHOUT one — the ordinary case here,
    # because `--cdp-endpoint` brings its own exit — the retry re-fetches
    # through the same access path, and that is worth doing on this site
    # rather than giving up: a Scraping Browser profile was measured refusing
    # two requests and serving the third. Zero was the family default and it
    # made the first live run of this engine abandon page 1 on its first
    # block without retrying once.
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
    html, state, load_failed = None, "ok", False
    # The HTTP status the navigation returned, threaded all the way to the
    # classifier. Discarding it is a real defect and not a tidiness one: this
    # site answers a missing address with a bare 1,040-byte page carrying NO
    # site chrome, so without a status it reads as "not recognisably this
    # site" — which RETRIES, and spends the retry budget on an address that
    # will never exist. Selenium cannot do this (WebDriver exposes no status
    # at all), which is why `product_parser.status_from_body` exists beside
    # it and why all three engines end up agreeing anyway.
    http_status = None

    for block_attempt in range(block_retries + 1):
        # Logged before the load loop, which is fine now that --retries
        # cannot be 0: with 0 this line announced a fetch the loop then never
        # made, so the log itself corroborated the wrong conclusion.
        logger.info("Fetching page %d/%d: %s", page_num, args.pages, url)
        # Retry a navigation timeout rather than ending the run on it. One
        # network flap on page 12 of 50 should not break the loop.
        load_failed, exit_failed = False, None
        for attempt in range(1, args.retries + 1):
            try:
                response = session.page.goto(url, wait_until="domcontentloaded",
                                             timeout=60000)
                # None on a same-document navigation, which is not an error —
                # it means "no new response", so the previous status stands.
                if response is not None:
                    http_status = response.status
                load_failed = False
                break
            except (PWTimeout, PWError) as e:
                # A dead or misconfigured proxy raises PWError
                # (net::ERR_PROXY_CONNECTION_FAILED), not PWTimeout —
                # catching only the latter lets it escape as a traceback,
                # which is the likeliest failure the first time anyone points
                # --proxy-file at a real list.
                reason = _proxy_failure(e)
                if reason:
                    exit_failed = reason
                    load_failed = True
                    break  # a different exit is the only thing that helps
                load_failed = True
                if attempt < args.retries:
                    pause = args.retry_delay * (2 ** (attempt - 1))
                    logger.warning("Timeout loading %s (attempt %d/%d) — "
                                   "retrying in %.1fs.", url, attempt,
                                   args.retries, pause)
                    time.sleep(pause)

        if exit_failed and has_pool and block_attempt < block_retries:
            logger.warning("Exit %s is unusable (%s) — rotating to another "
                           "one (%d/%d).", mask(pool.current), exit_failed,
                           block_attempt + 1, block_retries)
            pool.advance(f"unusable exit: {exit_failed}")
            session.relaunch()
            continue
        if load_failed:
            break

        # Routed through the budget like every other purchase. This
        # call used to be unguarded, which is how one page could buy
        # a solve per block-retry against a limit of one.
        if handle_captcha_if_present(session.page, args, budget):
            # A solve navigated the page. Give the destination a moment
            # before judging what came back.
            session.page.wait_for_timeout(1000)

        html = _snapshot(session.page, url) or ""
        state = _classify(session.page, html, http_status)

        # This site server-renders its grid, so a listing is parseable in
        # the FIRST response and there is nothing to wait for on a healthy
        # page. Measured 2026-09-18 with no JavaScript executed at all — a
        # plain HTTP fetch of /site/cosmedecorte/c/c15_p3/ returned the whole
        # 90,310-byte page with its tiles, and a product page carries its one
        # JSON-LD `Product` block in the same way. That is why this
        # engine has no scroll step and no readiness pause on the happy path:
        # either would be ceremony that looks load-bearing.
        #
        # The wait below is therefore only for the state that says the site
        # served SOMETHING that is not a catalogue page. That is the one case
        # where waiting can still help, and it is bounded.
        if state == "unknown":
            wait_timeout = page_flow.content_timeout_ms(args.mode)
            logger.info("Page %d is something the site served (%d bytes, "
                        "its own assets referenced %d time(s)) but carries no "
                        "product data — waiting up to %.0fs rather than "
                        "spending a retry.", page_num, len(html),
                        references_own_assets(html), wait_timeout / 1000)
            found = page_flow.wait_for_count(
                lambda sel: len(session.page.query_selector_all(sel)),
                _ready_selector(args), _min_matches(args), wait_timeout,
                session.page.wait_for_timeout)
            if found < _min_matches(args):
                logger.info("Still nothing after %.0fs (%d match(es) for %s).",
                            wait_timeout / 1000, found, _ready_selector(args))
            html = _snapshot(session.page, url) or html
            state = _classify(session.page, html, http_status)

        # The paid path is reached only for state "captcha" — a rendered
        # widget, which IS a test and can be solved. It is NOT reached for
        # "blocked": an edge refusal offers no widget, no sitekey and no
        # challenge of any kind, so a solve there would be a charge for
        # nothing. That distinction is the whole reason page_flow separates
        # the two states, and it is bounded by SOLVES_PER_PAGE so a rotation
        # loop cannot become a bill.
        if page_flow.should_solve(state):
            if handle_captcha_if_present(session.page, args, budget):
                session.page.wait_for_timeout(1000)
                html = _snapshot(session.page, url) or html
                state = _classify(session.page, html, http_status)
                # The VERIFIED outcome, and the only one worth reporting: a
                # "ready" task result is not evidence the token works. This
                # line is what says whether the money bought anything.
                if state == "content":
                    logger.info("The solve was accepted — page %d is content "
                                "now.", page_num)
                else:
                    logger.warning(
                        "The solve was NOT accepted: page %d is still %s. The "
                        "purchase is spent.", page_num, state)

        if not page_flow.should_retry(state):
            # "content" and "empty" are both final answers. An empty page is
            # a CORRECT one — a bogus category id is served with no tiles, and one page past
            # the end of a listing has no products — so retrying it would
            # spend the user's budget re-confirming the same right answer,
            # and rotating the exit would blame an address for the URL it was
            # given.
            break

        # Blocked or challenged. A different exit is the one thing that
        # plausibly changes the outcome: the ADDRESS is what was scored, not
        # the URL, so retrying it unchanged would only confirm it. (On this
        # site no refusal has been observed from any address, datacentre
        # included; this branch is here for the day that changes.)
        if block_attempt < block_retries:
            if has_pool:
                logger.warning("Page %d came back as %s from %s — retrying "
                               "from another exit (%d/%d).", page_num, state,
                               mask(pool.current), block_attempt + 1,
                               block_retries)
                pool.advance(f"{state} on page {page_num}")
                session.relaunch()
            else:
                # No pool, so nowhere else to go — but a plain re-fetch is
                # what clears this on a Scraping Browser profile. The browser
                # is NOT relaunched: over `--cdp-endpoint` a profile allows
                # one live connection, so tearing the session down and
                # reconnecting risks `profile_locked` and would lose the very
                # cookies the retry is meant to build on.
                pause = args.retry_delay * (block_attempt + 1)
                logger.warning("Page %d came back as %s — re-fetching through "
                               "the same access path in %.1fs (%d/%d). On this "
                               "site that is often what clears it.",
                               page_num, state, pause, block_attempt + 1,
                               block_retries)
                time.sleep(pause)

    if load_failed:
        logger.error("Gave up loading %s after %d attempt(s).", url, args.retries)
        outcome.load_failed = True
        return outcome

    outcome.state = state

    if state == "blocked":
        # What a caller needs here is WHICH refusal this is, because the two
        # want different answers and only one of them is solvable.
        #
        # What a reader needs here is WHICH refusal arrived, because the
        # two have different remedies and only one of them is about the
        # address:
        #
        #   a page that is not this site's        — something between here
        #                                           and the site is
        #                                           intercepting, or the exit
        #                                           is scored. A different
        #                                           exit.
        #   nothing at all (the stream was reset) — the network path. On
        #                                           this site no refusal of
        #                                           any kind has been
        #                                           observed (README).
        #
        # Saying which one arrived is more use than a captcha hint that would
        # cost money for a page carrying no widget.
        debug_html = f"{args.out}_page{page_num}_debug.html"
        with open(debug_html, "w", encoding="utf-8") as f:
            f.write(html or "")
        assets = references_own_assets(html or "")
        logger.error(
            "Maison KOSE did not serve this request — %d bytes, its own asset "
            "host referenced %d time(s), saved to %s. There is no widget on "
            "it, so no key would help. Nothing on this site has ever "
            "produced this state: measured 2026-09-18 from a datacentre "
            "address, a request with NO User-Agent at all is served the same "
            "90,310 bytes as a browser, and 12 pages back to back were "
            "12 x HTTP 200. So the first thing to check is the network path "
            "— a proxy, a captive portal, or DNS — then try a different exit "
            "with --proxy or --cdp-endpoint. This "
            "is exit 3, distinct from a genuinely empty result (exit 4).%s",
            len(html or ""), assets, debug_html,
            (f" Tried {block_retries + 1} exit(s)." if has_pool
             else f" Re-fetched {block_retries + 1} time(s)."))
        outcome.blocked_by = "edge refusal" if html else "no-response"
        outcome.final_url = session.page.url
        return outcome

    # No readiness wait and no scroll on the content path, and their absence
    # is MEASURED rather than forgotten — see the "unknown" branch above.
    # This site server-renders its whole grid in the first response, so there
    # is nothing to wait for and nothing to scroll into view. Porting the
    # sibling repos' scroll loop here would be dead code that looks
    # load-bearing.

    # Dumping on success, not only on failure: a run can return the right
    # NUMBER of rows with a field silently unpopulated, and then the only way
    # to tell a parsing bug from a too-early snapshot is to inspect the exact
    # bytes the parser was given.
    if args.dump_html:
        dump_path = (args.dump_html if args.pages == 1
                     else f"{args.dump_html}.page{page_num}")
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("Saved the snapshot the parser sees to %s (%d bytes).",
                    dump_path, len(html))

    # Only for a state page_flow already counts as BLOCKED, and that
    # narrowing was earned twice.
    #
    # A marker on a page whose products have rendered guards nothing — that
    # is the "detected is not blocking" rule the captcha default follows,
    # applied to the blocking decision instead of the spending one. But
    # `state != "content"` is still too wide: an EMPTY page is a correct
    # answer, and a live run of tokopedia-scraper's /p/<slug> hub reported
    # exit 3 on a 191 KB page that site had plainly served, because its own
    # performance script names `akamaihd.net` and "akamai" was in the marker list. Both
    # halves were wrong; the marker is gone (see
    # product_parser.BOT_CHALLENGE_MARKERS) and this now only refines the
    # REASON for a page the policy had already given up on.
    vendor = (detect_bot_challenge(html, url=session.page.url)
              if page_flow.counts_as_blocked(state) else None)
    if vendor:
        debug_html = f"{args.out}_page{page_num}_debug.html"
        with open(debug_html, "w", encoding="utf-8") as f:
            f.write(html)
        try:
            session.page.screenshot(path=f"{args.out}_page{page_num}_debug.png",
                                    full_page=True)
        except Exception as e:
            logger.warning("Could not capture screenshot: %s", e)
        logger.error("Blocked by %s before parsing (%d bytes) — saved to %s%s. "
                     "This is exit 3, distinct from a genuinely empty result "
                     "(exit 4).", vendor, len(html), debug_html,
                     (f" (tried {block_retries + 1} exit(s))" if has_pool
                      else f" (re-fetched {block_retries + 1} time(s))"))
        outcome.blocked_by = vendor
        return outcome

    if not page_flow.should_parse(state):
        # Reached only for a state the policy says holds no rows — and it
        # says so in ONE place, so an engine cannot quietly decide to parse
        # something its twins would not.
        logger.info("Page %d came back as %s; nothing to parse.", page_num,
                    state)
        outcome.final_url = session.page.url
        return outcome

    products, listing = _parse_for_mode(html, session.page.url, args, page_num)
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
        # Reported every time rather than only when it trips, so a consumer
        # gets the number rather than a threshold someone guessed.
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
                    "rather than the products being unusual — re-run with "
                    "--dump-html.",
                    share, page_num, field_name, CORE_FIELD_FLOOR)

        priced = sum(1 for row in products if row.price is not None)
        price_share = 100.0 * priced / len(products)
        if price_share < PRICE_COVERAGE_FLOOR:
            logger.warning(
                "Only %.0f%% of page %d carries a price, against a measured "
                "floor of %d%%. Every one of 171 tiles across 8 captures had "
                "one, so a shortfall is a parsing break rather than the "
                "site's own variety — re-run with --dump-html.",
                price_share, page_num, PRICE_COVERAGE_FLOOR)

        if args.mode == "product":
            group = {row.variant_of for row in products if row.variant_of}
            logger.info("Product: %d row(s) for %s, %d priced.",
                        len(products), next(iter(group), products[0].sku),
                        sum(1 for r in products if r.price is not None))
        else:
            in_stock = sum(1 for row in products if row.in_stock is True)
            brands = len({row.brand for row in products if row.brand})
            logger.info("Page %d: %d row(s), %d priced, %d in stock, %d "
                        "brand(s). Tiles on the page: %s (a grid also carries "
                        "carousel links, which is why rows come from tiles "
                        "and not from links).",
                        page_num, len(products), priced, in_stock, brands,
                        listing.tiles_on_page if listing else "n/a")

    outcome.products = products
    outcome.final_url = session.page.url
    return outcome


def _worker_pool(pool, worker_index: int):
    """A private ProxyPool for one worker, starting at a different exit.

    Each worker gets its OWN pool object holding the same exits rotated to a
    different offset. Two things fall out of that, both wanted:

      * Workers start on distinct exits, which is the point of running
        several — N workers all leaving from one address is just a faster way
        to burn that address.
      * No shared mutable state between threads, so rotation needs no lock.
        A worker that gets blocked can still walk the rest of the pool on its
        own.

    Its exit stays put for the worker's lifetime otherwise: a SESSION must
    not change address mid-flight, and a worker is one session.
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
    # Set when a page comes back with no rows at all — the end of the
    # listing. Without it, asking for 50 pages of a 5-page result would fetch
    # 45 empty ones. Workers check it before taking more work, so at most
    # (concurrency - 1) extra pages are in flight when it trips.
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
                        outcome = _fetch_one_page(session, args, session.pool,
                                                  page_num, url)
                        with results_lock:
                            results.append(outcome)
                        if outcome.ok and not outcome.products:
                            logger.info("[%s] page %d returned no rows — "
                                        "treating that as the end of the listing "
                                        "and stopping dispatch.", name, page_num)
                            exhausted.set()
                finally:
                    session.close()
        except Exception:  # noqa: BLE001 — a dead worker must not hang the run
            logger.exception("[%s] died; its pages will be reported as failed.", name)

    threads = [threading.Thread(target=worker, args=(i,), name=f"page-worker-{i + 1}")
               for i in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Anything still queued was never attempted (a worker died, or dispatch
    # stopped at the end of the listing). Not reported as failed pages: they
    # were not tried, and claiming otherwise would overstate the damage.
    unattempted = []
    while True:
        try:
            unattempted.append(work.get_nowait()[0])
        except queue.Empty:
            break
    return results, sorted(unattempted), exhausted.is_set()


def scrape(args) -> int:
    _started = time.monotonic()
    # One entry per page attempted, merged after the loop rather than folded
    # into shared state during it — see PageOutcome for why that ordering
    # matters more than it looks.
    outcomes: List[PageOutcome] = []
    seen_keys = set()
    blocked = False
    # Both modes are one row per product, so `sku` is the key for both.
    dedupe_key = "sku"
    # Why the loop ended. "completed" means every requested page was fetched;
    # "no_new_products" means the listing itself ran out (also a complete
    # result). "single_page_mode" is complete by construction — a detail page
    # has no page 2. Anything else is an early stop, and the run is only a
    # partial view.
    # "page_cap_reached" means the run asked for more pages than the
    # category holds and was clamped to the site's own count. On this site
    # that is a COMPLETE result in the strong sense: this site imposes no cap
    # of its own, so the clamp IS the whole category — on 2026-09-18 /c/c15/
    # stated 13 pages, 12 x 24 + 16 = 304 products.
    #
    # Only --mode product is single-page. Both listing routes paginate —
    # `_pN` on a category, `?p=N` on a tag listing — so neither may be
    # treated as single-page, which is the silent-success failure this family
    # exists to avoid. On this site one product page is also one row: a
    # single `Product` block, never a `ProductGroup`.
    stop_reason = "single_page_mode" if args.mode == "product" else "completed"

    pool = proxy_pool_from_args(args)
    if pool and args.cdp_endpoint:
        logger.warning("Ignoring --proxy/--proxy-file: with --cdp-endpoint the "
                       "remote browser has its own exit, and layering a second "
                       "proxy on top would contradict it.")
        pool = None

    concurrency = max(1, args.concurrency)
    if concurrency > 1:
        if args.mode == "product":
            logger.info("--concurrency is ignored in --mode product: there is "
                        "one page to fetch, and it is one row.")
            concurrency = 1
        elif page_flow.concurrency_limit(args.cdp_endpoint) == 1:
            # The limit is page_flow's to state, not this engine's, so all
            # three refuse in the same place for the same reason.
            logger.warning("--concurrency is ignored with --cdp-endpoint: the "
                           "Scraping Browser API allows one live connection per "
                           "profile, and several workers would collide on it "
                           "(profile_locked). Use several pids instead, one run "
                           "each.")
            concurrency = 1
        elif not pool:
            logger.warning("--concurrency %d with no proxy pool: every worker "
                           "leaves from the SAME address, which is a faster way "
                           "to get that address scored than to gather data. "
                           "This site serves an ordinary datacenter address "
                           "today, which makes an address that works one "
                           "worth not burning. Pass --proxy-file to spread "
                           "the load.", concurrency)
        if pool and pool.rotates_per_page():
            logger.info("--proxy-rotate per-page is redundant under "
                        "--concurrency: each worker already holds its own exit "
                        "for its lifetime, which is the same spread without a "
                        "browser relaunch per page.")
        if concurrency > 8:
            logger.warning("--concurrency %d means %d browsers at once "
                           "(~150-300MB each). Make sure the machine has the "
                           "memory for it.", concurrency, concurrency)

    with sync_playwright() as pw:
        session = _BrowserSession(pw, args, pool,
                                  remote=bool(args.cdp_endpoint)).open()
        try:
            target = _target_url(args)
            if target != args.url:
                # The only normalisation this site needs: a listing URL that
                # already names a page is reset to page 1, because page 1 is
                # what decides how far the rest can be addressed.
                logger.info("Normalised to page 1: %s", target)

            # Page 1 is always fetched on its own: its content is what decides
            # how many pages 2..N there are to address at all.
            first = _fetch_one_page(session, args, pool, 1, target)
            outcomes.append(first)

            if not first.ok:
                stop_reason = ("page_load_timeout" if first.load_failed
                               else f"blocked_{first.blocked_by}")
                blocked = first.blocked_by is not None
            elif first.state == "not_found":
                # The address does not exist. A terminal answer about the URL
                # rather than about the catalogue, so the run stops here
                # instead of planning pages 2..N against something that will
                # 404 too. Its own stop_reason, because "no products" would
                # send the reader to check the parser when the thing to check
                # is what they typed.
                stop_reason = "not_found"
                logger.error("%s does not exist — HTTP 404. Nothing was "
                             "scraped. On this site a bogus goods code or "
                             "category id answers 200 with an empty page "
                             "instead, so a real 404 means the PATH is wrong, "
                             "not the id.", first.url)
            elif first.state == "parse_failed":
                # Served, linked to products, parsed to nothing: OUR bug, and
                # it must not reach the sidecar as a complete run.
                stop_reason = "parser_found_nothing"
            elif args.mode == "product":
                pass  # one page is the whole run — but many rows
            else:
                seen_keys.update(p.sku for p in first.products if p.sku is not None)
                planned = _plan_page_urls(args, first.final_url,
                                          first.pages_available)
                if len(planned) + 1 < args.pages:
                    # Clamped to the site's own result count, which is a
                    # complete answer rather than an early stop — see
                    # COMPLETE_STOP_REASONS.
                    stop_reason = "page_cap_reached"

                if args.pages > 1 and concurrency > 1 and not page_flow.pagination_is_addressable(first.final_url):
                    logger.warning("--concurrency %d requested, but this "
                                   "listing's pages cannot be addressed "
                                   "independently — falling back to one page "
                                   "at a time.", concurrency)
                    concurrency = 1

                if planned and concurrency > 1:
                    # Close the page-1 browser before starting workers: it has
                    # done its job, and holding it open would cost one more
                    # browser than asked for.
                    session.close()
                    specs = [(n, planned[n - 2]) for n in range(2, len(planned) + 2)]
                    logger.info("Fetching pages 2-%d across %d workers%s.",
                                len(planned) + 1, concurrency,
                                f" over {len(pool)} exit(s)" if pool else "")
                    rest, unattempted, exhausted = _fetch_pages_concurrently(
                        args, pool, specs, concurrency)
                    outcomes.extend(rest)

                    failed = [o for o in rest if not o.ok]
                    if failed:
                        worst = min(failed, key=lambda o: o.page_num)
                        stop_reason = ("page_load_timeout" if worst.load_failed
                                       else f"blocked_{worst.blocked_by}")
                        blocked = any(o.blocked_by for o in rest)
                    elif exhausted:
                        stop_reason = "no_new_products"
                    elif unattempted:
                        # Should not happen without a failure or exhaustion,
                        # but say so rather than reporting a complete run.
                        stop_reason = "pages_unattempted"
                    session = None  # already closed
                elif planned:
                    url = planned[0]
                    for page_num in range(2, len(planned) + 2):
                        # A new exit per page is what actually spreads a run's
                        # volume, and it costs a browser relaunch: carrying the
                        # session across exits would defeat the point.
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

                        # Whether this page contributed anything not already
                        # seen. Kept as a running check because the condition is
                        # inherently sequential — "new" only means anything
                        # relative to the pages before it. The authoritative
                        # dedupe happens once, after the loop, in page order.
                        fresh_count = sum(1 for p in outcome.products
                                          if p.sku is None or p.sku not in seen_keys)
                        seen_keys.update(p.sku for p in outcome.products
                                         if p.sku is not None)

                        # A page past the first that contributes nothing new
                        # means the end of the results — or that pagination is
                        # looping back on itself. Either way there is nothing
                        # further to fetch, and this is the honest terminating
                        # condition: a property of the DATA, not of a CSS
                        # selector that may have been renamed.
                        if not fresh_count:
                            logger.info("Page %d added no rows not already seen "
                                        "— treating that as the end of the "
                                        "listing.", page_num)
                            stop_reason = "no_new_products"
                            break

                        if page_num - 1 < len(planned):
                            url = planned[page_num - 1]
                            time.sleep(args.delay)
        finally:
            if session is not None:
                session.close()

    # Merge once, in PAGE order — not in the order pages happened to finish.
    # At one page at a time the two are identical, which is the point: this is
    # what keeps the output byte-for-byte the same while removing the
    # dependency on arrival order that concurrency would otherwise introduce.
    all_rows = []
    merged_seen = set()
    for oc in sorted(outcomes, key=lambda o: o.page_num):
        fresh = dedupe_by_key(oc.products, merged_seen, key=dedupe_key)
        if len(fresh) < len(oc.products):
            # Not necessarily "on an earlier page" — a duplicate can be on
            # this page. Healthy pagination here does NOT repeat: every pair
            # of the 8 captured listing pages was disjoint, and pages 1-3 of
            # a live run shared 0 of 72 skus. So any non-zero count is worth
            # a look.
            #
            # And on this site a count EQUAL to the page size has one very
            # specific meaning: a category listing fetched past its last page
            # returns that last page again, byte-identical, so 24 duplicates
            # in a row is the site saying the listing ended — not a bug in
            # the dedupe. The run plans against the site's own page counter
            # precisely so that this stays a diagnostic rather than a cost.
            logger.info("Page %d: dropped %d duplicate row(s).",
                        oc.page_num, len(oc.products) - len(fresh))
        all_rows.extend(fresh)

    # Completeness, checked over the MERGED result rather than per page — a
    # per-page check cannot see a gap BETWEEN two pages, which is exactly
    # where a short page hides.
    #
    # NOT "pages x rows-per-page" as a hard expectation, even though the
    # page size is the site's fixed 24: the LAST page of a listing is
    # legitimately short — /c/c15/ ended 12 x 24 + 16 on 2026-09-18 — and a threshold that fires on every healthy run teaches the
    # reader to ignore it. What is worth warning about is a page that came
    # back materially THIN against its siblings, which is what a truncated
    # response looks like.
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
                "short page in the middle of a run is a truncated response "
                "rather than a short listing — re-run with --dump-html.",
                ", ".join(str(p) for p, _ in thin), fullest,
                ", ".join("page %d: %d" % (p, n) for p, n in thin))

    ok_pages = [o for o in outcomes if o.ok]
    failed_pages = [o.page_num for o in outcomes if not o.ok]
    final_url = (max(ok_pages, key=lambda o: o.page_num).final_url
                 if ok_pages else args.url)

    # One-per-run context, in the sidecar rather than repeated down a column.
    #
    # For a listing run that is the site's own arithmetic —
    # `total_results`, `pages_available`, the page size it actually applied,
    # and the ordering it says it applied. Together they let a consumer tell
    # a run that covered a whole category from one that read the first two
    # pages of it, and no column can carry them because they describe the
    # LISTING rather than any product.
    #
    # No `locale` here, and its absence is a measurement rather than an
    # omission: maison.kose.co.jp is one market. No `hreflang` set, no /en/
    # route, every price in JPY — so a locale field would carry `ja-jp` on
    # every run forever, which is the "a value that never varies
    # is not a field".
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
        # No `capped_by_site` and no `reachable_max` here, and their ABSENCE
        # is the finding rather than an omission. bbb-scraper needs both
        # because that site refuses to serve past page 15 however many rows
        # matched, so "complete" there can mean a 1.2% sample. This site
        # imposes no such cap: on 2026-09-18 /c/c15/ stated 13 pages and
        # 12 x 24 + 16 = 304 products, the whole of Cosme Decorte, so `pages_available` already says
        # everything those fields would — and a `reachable_max` of
        # pages x page_size would OVERSTATE a short last page: 13 x 24 = 312
        # against the 304 that existed then.

    # Which engine ran, what version of its driver, and how long it took.
    # A sidecar that says only "complete" cannot answer "why is this run
    # slower than yesterday's" or "did the pyppeteer upgrade change
    # anything", and all three are one line each. Raised by a third-party
    # audit on 2026-10-13 and agreed with.
    try:
        from importlib.metadata import version as _pkg_version
        _v = _pkg_version("playwright")
    except Exception:  # noqa: BLE001 — a version is never worth a crash
        _v = None
    _run_facts = {"engine": "playwright", "engine_version": _v,
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
        description="Maison KOSE scraper (Playwright edition)")
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
                        "'\u30b7\u30ef\u6539\u5584,\u30b9\u30ad\u30f3\u30b1\u30a2'. Builds a "
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


def _cli():
    """Console entry point, so `pip install .` gives a command.

    The module stays runnable as a script — `python playwright_scraper.py …` is
    what every example in the README and the workflows uses — and
    this is the same code path rather than a second one.
    """
    args = parse_args()
    if args.fingerprint and not args.twocaptcha_key:
        logger.error("--fingerprint needs --twocaptcha-key (the Fingerprint API "
                     "uses the same key, though it's a separate subscription "
                     "from solving).")
        sys.exit(2)
    if args.fingerprint and args.cdp_endpoint:
        logger.warning("--fingerprint is ignored with --cdp-endpoint: the "
                       "Scraping Browser supplies its own fingerprint, and "
                       "stacking a second one on top creates a mismatch rather "
                       "than better cover.")
    try:
        sys.exit(scrape(args))
    except ProxyError as e:
        # Bad usage, not a crash: a typo in a proxy list would otherwise
        # surface as a connection failure on page 1 with nothing naming it.
        logger.error("%s", e)
        sys.exit(2)
    except PWError as e:
        # A remote browser that will not accept the connection is a REMOTE
        # API failure (exit 5), not a crash in this code (exit 1) and not bad
        # usage (exit 2). The distinction earns its keep on the commonest one:
        # `profile_locked` means another run still holds this `pid`, and a
        # harness that sees exit 1 goes looking for a bug in the scraper
        # instead of waiting or passing a different pid.
        text = _mask_credentials(str(e))
        if "profile_locked" in text or "connect to --cdp-endpoint" in text:
            logger.error("%s", text)
            sys.exit(EXIT_API_ERROR)
        raise


if __name__ == "__main__":
    _cli()
