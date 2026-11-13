#!/usr/bin/env python3
"""
andieswim-scraper — Playwright edition (primary engine)
=======================================================

Scrapes andieswim.com (Andie Swim): collection listings, keyword lookups,
and single products with their full size/colour table.

    --mode listing   (default)  /collections/{handle}   -> one row per PRODUCT
    --mode search               /search?q=...           -> one row per PRODUCT
    --mode product              /products/{handle}      -> one row per VARIANT,
                                                           each with its own
                                                           sku, size, colour,
                                                           price and stock

Three engines ship in this repo and they must agree on exit codes, run
status, and whether a run crashes or spends money; the shared decisions live
in output_writer.finish_run() and page_flow.py so they cannot drift apart.

What is different about Andie Swim
-----------------------------------
* **Nothing here is gated, at all.** Measured 2026-09-18 from a datacenter
  address: every route answered HTTP 200 with a browser User-Agent, with
  `curl/8.5.0`, with `python-urllib`, with a crawler UA, and with **no
  User-Agent header at all**. Twenty rapid requests: twenty 200s. No
  challenge has ever been observed. Say so plainly rather than selling a
  product nobody needs here; the README lists what the paid
  products actually buy on this site, which is a specific MARKET and volume
  from many addresses, not access.

* **The data is JSON, and the HTML is not a fallback — it is empty.** A
  collection page's markup holds no product grid: 793 KB of
  `/collections/one-pieces` contains five `/products/` links, all from
  recommendation widgets, and `?page=2` returns the same five. The grid is
  painted after load by a React component over the Storefront API. A product
  page publishes one JSON-LD block and its `@type` is `BreadcrumbList` —
  there is no `Product` node anywhere. So this engine navigates to the
  store's OWN endpoints, which are ungated and richer than any rendered tile
  (ask what the front end calls before assuming a browser).

* **A JSON document needs no readiness wait, and waiting on one is pure
  loss.** The three causes of missing content — unpainted, lazy-loaded, a
  different page served to this session — are all properties of a rendered
  page. `page_flow.wait_is_meaningful()` says so per URL, and the endpoint
  routes skip the wait rather than burning the whole budget to sample the
  same complete document twice.

* **A misspelt collection handle looks EXACTLY like an empty one.**
  `/collections/does-not-exist/products.json` answers HTTP 200 with
  `{"products": []}`; only the HTML route 404s. So a zero-row run checks the
  handle against the store's own collection index and says
  `unknown_collection` rather than `empty` when it is absent. Reporting a
  typo as a successfully-scraped empty category is the failure this costs
  one request to avoid.

* **`products_count` is not a product count, so nothing is planned from it.**
  The collection index reports 472 for a collection the storefront serves 180
  of, and 3089 for one it serves 322 of — against 772 published products in
  the whole store. It reaches the sidecar as `catalog_count` with that
  warning and is used for nothing. The end of a listing is discovered from
  the data instead, and walking off the end is free: the page after the last
  one answers 200 with an empty array.

* **`--sort` does not exist here, and that is a measurement rather than an
  omission.** The JSON endpoint ignores `sort_by` — verified: the response is
  the same with and without it — so a flag would report an ordering the fetch
  never applied. Unlike the sibling repo where ordering decides WHICH
  rows land in a capped file, nothing is capped here: a listing run fetches
  every published product in the collection, so ordering decides `position`
  and nothing else, and two runs under different orderings hold the same
  rows.

* **The market is a path prefix and the price is SET per market.** The
  store's own sitemap index lists 200 of them, all `en-xx`. The same variant
  on 2026-09-18: 112.00 USD, 195.00 CAD, 110.00 GBP, 175.00 AUD, 130.00 EUR,
  21600 JPY. 110 GBP is about 148 USD against a 112 USD list, so a
  cross-market gap is pricing policy and not arbitrage. `--locale
  en-gb` selects one; every row carries which.

* **Currency is read from the site or left null.** The listing endpoint
  publishes no currency field, so this engine resolves it once per run — from
  a product document's `price_currency`, or from `Shopify.currency.active` in
  the market's own HTML — and writes `null` when it could read neither. It is
  never inferred from the market prefix, which would be a mapping this repo
  invented.

Usage
-----
    python3 playwright_scraper.py \\
        --url "https://andieswim.com/collections/one-pieces" --pages 3

    python3 playwright_scraper.py --mode search --query "bikini top"

    python3 playwright_scraper.py --mode product \\
        --url "https://andieswim.com/products/the-amalfi-flat-black-classic"

    python3 playwright_scraper.py --locale en-gb \\
        --url "https://andieswim.com/en-gb/collections/one-pieces"
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
from urllib.parse import quote, urlparse, urljoin

from playwright.sync_api import (sync_playwright, Error as PWError,
                                 TimeoutError as PWTimeout)

from captcha_solver import (detect_recaptcha_v3, detect_recaptcha_in_page,
                            reconcile_detections, solve_recaptcha,
                            CaptchaUnsolvable, INJECT_TOKEN_JS,
                            RECAPTCHA_DISCOVERY_JS)
import product_parser
from product_parser import (DEFAULT_LOCALE, DEFAULT_MODE, PAGE_SIZE,
                            VERIFIED_MARKETS,
                            collection_from_url, collection_url,
                            collection_endpoint, detect_bot_challenge,
                            is_endpoint_url, is_product_url, is_supported_url,
                            listing_endpoint, locale_from_url,
                            market_is_well_formed, page_url,
                            parse_collection, parse_listing,
                            parse_product_detail, parse_products,
                            payload_currency, product_link_count,
                            product_url, references_own_assets,
                            search_endpoint)
from output_writer import (dedupe_by_key, finish_run, EXIT_API_ERROR,
                           SOURCE_DEFAULT)
import page_flow
from page_flow import MIN_CARD_MATCHES
from proxy_pool import (from_args as proxy_pool_from_args, to_playwright, mask,
                        ROTATE_MODES, ProxyError, ProxyPool)
import env_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("playwright_scraper")


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
    # "captcha", "empty", "unknown"). Carried so the caller can tell an
    # EMPTY page — a discover/hub page, a search that matched nothing, or one
    # `start=` past the end of a listing — from a page that FAILED. Both
    # produce zero rows and they mean opposite things.
    state: Optional[str] = None
    # What the site said the result set was. Both stay None on this store: it publishes no result count anywhere,
    # and the one count it does publish (`products_count` in the collection
    # index) counts something other than products the storefront serves.
    # None means UNKNOWN and is never read as zero — treating a missing count
    # as zero would cap every run after page 1 at no pages at all.
    total_available: Optional[int] = None
    pages_available: Optional[int] = None
    # How many products THIS response's array held, before dedupe. The only
    # signal that separates "the collection ended" (0) from "we were handed
    # something that is not a listing" (None), which is why the run's stop
    # condition reads this rather than the deduped row count.
    products_returned: Optional[int] = None
    # The ordering the rows actually came back in. Constant here — the JSON
    # endpoint takes no `sort_by` and ignores one that is passed — and kept
    # because the family schema has it and a consumer reads it by name.
    sort_applied: Optional[str] = None

    @property
    def ok(self) -> bool:
        return not self.load_failed and self.blocked_by is None


ITEM_LINK_SELECTOR = page_flow.READY_SELECTOR_LISTING

# The share of rows that must carry the columns this store populates on every
# listing row, below which the read has broken rather than the data being
# unusual.
#
# Measured over 665 products on four collections (2026-09-18): `title`,
# `url`, `sku`, `handle`, `image_url` and `product_type` were populated on
# 665 of 665, and `price` on 665 of 665 as well — every published product on
# this store has a price, so unlike the sibling repo `price` IS in the floor
# rather than excluded for a range-priced minority.
#
# Deliberately NOT in this check:
#   `currency`     — resolved once per run from a separate fetch, so it is
#                    null on every row or none of them; a per-row floor would
#                    report the same single failure 180 times.
#   `base_sku`     — 613 of 665 (92%). The 52 misses are bundles whose
#                    variants genuinely share no style code, which is correct
#                    data, and a 99% floor on it would fire on every run.
#   `original_price` — 45% on a full-price collection and 100% on the sale
#                    one. It is the discount, not a defect.
CORE_FIELD_FLOOR = 99
CORE_FIELDS = ("title", "url", "sku", "handle", "price")

# The share of rows that must carry a usable price before the run is worth
# trusting as a PRICE run rather than merely as a catalogue listing.
#
# 100% on every collection measured, so a miss here is a parsing break rather
# than the store's own variety — the endpoint publishes a price for every
# variant of every published product. The floor is set below 100 anyway,
# because a single unpriced product added tomorrow is the store's business
# and not a reason to fail a run.
PRICE_COVERAGE_FLOOR = 95

# A page holding less than this share of the page size is reported as thin.
# The size is the site's own `sz`, echoed back as `data-page-size`, and every
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
    # which before "fixing" it). None of the three applies: every address
    # this engine fetches is a JSON endpoint that arrives COMPLETE with its
    # response, so there is nothing to paint, nothing to lazy-load and
    # nothing to scroll into view. A scroll loop here would be ceremony that
    # looks load-bearing.
    #
    # Note the site DOES lazy-load — its rendered collection grid paints 30
    # cards at a time over the Storefront API — which is precisely why this
    # repo does not read the rendered grid. Scrolling it to the end of a
    # 180-product collection is six round trips and a guess about when to
    # stop; one endpoint request is all of it, exactly, in 0.44 s.
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


def detail_of(page, html: str, status=None) -> str:
    """The classifier's REASON, for a log line that has to explain itself."""
    return page_flow.classify_with_reason(html, status, page.url)[1] or "?"


def _classify(page, html: str, status=None) -> str:
    return page_flow.classify(html, status, page.url)

# Every readiness constant and every state policy lives in page_flow.py, with
# its measurement beside it. Nothing about WHAT to do with a page is
# duplicated here — this file only knows HOW to ask Playwright.


def _target_url(args) -> str:
    """The address this run actually fetches.

    Never the URL the user typed. Every route on this store publishes its
    data at a JSON endpoint beside the human page, and the human page
    publishes none of it (see the module docstring for both counts) — so
    `/collections/one-pieces` becomes
    `/collections/one-pieces/products.json?limit=250&page=1`, carrying
    whichever market prefix the URL had.

    `--query` and `--category` are turned into a URL before this runs, so
    there is exactly one input shape however the run was started.
    """
    if args.mode == "search":
        return search_endpoint(args.query or "", limit=args.limit,
                               market=_market(args))
    if args.mode == "product":
        return product_parser.product_endpoint(args.url)
    return listing_endpoint(args.url, page=1, limit=args.limit)


def _market(args) -> Optional[str]:
    """The market prefix this run reads, or None for the bare US store.

    The URL wins over `--locale` when both name one, because the URL is what
    is actually being fetched — silently preferring the flag would put a
    price from one market under another market's label. The disagreement is
    logged rather than resolved quietly.
    """
    from_url = product_parser.market_from_url(args.url or "")
    wanted = (getattr(args, "locale", "") or "").strip().lower() or None
    if wanted == DEFAULT_LOCALE:
        wanted = None                 # "en-us" is spelled as the bare path
    if from_url and wanted and from_url != wanted:
        logger.warning("The URL names market %s and --locale names %s. Using "
                       "%s, because that is the address being fetched.",
                       from_url, wanted, from_url)
    return from_url or wanted


def _plan_page_urls(args, page_one_url: str,
                    pages_avail: Optional[int]) -> List[str]:
    """URLs for pages 2..N, decided once from what page 1 reported.

    A constructed page URL may only be trusted once page 1's own
    convention has been checked. Checked here, 2026-09-18, by walking the
    whole store: `/products.json?limit=250&page=1..4` returned 250 + 250 +
    250 + 22 = **772 distinct handles with no repeats**, and page 5 was
    empty. Page N is genuinely a different slice, which is also what makes
    `--concurrency` legal on this site.

    Nothing caps the plan. The one count this store publishes
    (`products_count` in the collection index) is not a count of products it
    will serve — 472 against 180, 3089 against 322 — so planning against it
    would clamp a correct run against a number that was never right. The end
    is discovered from the data instead (a data-based stop, not a selector), and overshooting is
    free: a page past the last one is HTTP 200 with an empty array, not the
    HTTP 500 the same overshoot produces on bbb-scraper's site.
    """
    if not page_flow.pagination_is_addressable(args.url or page_one_url):
        # A product document and a predictive-search lookup are ONE response
        # each and have no page 2. Handing "page 3" of one to a worker would
        # refetch page 1 and report its rows a third time.
        return []
    wanted = page_flow.pages_to_plan(args.pages, pages_avail)
    if wanted < args.pages:
        logger.info("Planning %d page(s) of the %d asked for.",
                    wanted, args.pages)
    return [page_url(args.url or page_one_url, n, args.limit)
            for n in range(2, wanted + 1)]


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
    ctx_kwargs = {"user_agent": _chrome_ua(browser.version), "locale": args.locale}
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
    # This path exists for a challenge the store does not render today. What
    # it DOES ship is Shopify's storefront-forms hCaptcha
    # (`ce_storefront_forms_captcha_hcaptcha…iife.js`, sitekey
    # f06e6c50-85a8-45c8-87d0-21a2b65856fe), bound to FORM SUBMITS — the
    # newsletter, contact and account forms — and never rendered on a
    # listing, a product page or any JSON route this engine reads. Zero
    # reCAPTCHA, Turnstile, DataDome, PerimeterX, Incapsula, Kasada and AWS
    # WAF markers across every capture. Kept wired because a bot manager can
    # be switched on between deploys, and because 2Captcha solves hCaptcha
    # (`HCaptchaTaskProxyless`) if one ever appears on a read path.
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
    it.

    On this store that is a live risk rather than a theoretical one, and the
    shape of it is worth naming because it caught this repo out.

    There is no HTTP redirect anywhere: `curl -L` follows ZERO hops on every
    route, and an HTTP client always gets the bare (US) market. But the theme
    ships a CLIENT-SIDE geolocation app that rewrites the location to the
    visitor's own market after the page loads. Measured 2026-09-18 from a
    Finnish address: `/collections/all` snapshotted at `domcontentloaded` is
    still the bare path and says USD, and the same URL read after a full load
    has become `/en-fi/collections/all` and says EUR.

    So an HTML page on this store is timing-dependent, and three engines that
    wait for different things will disagree about which market they are on.
    That is exactly why nothing this repo depends on is read from an HTML
    page: the JSON endpoints run no JavaScript, cannot be moved that way, and
    gave all three engines the identical answer (verified: byte-identical
    output and the same currency on the same collection).

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

    True for every address a normal run on this store fetches. The decision
    lives in `product_parser` so the three engines cannot disagree about
    which reader to use — and disagreeing would be SILENT: Chromium's JSON
    viewer markup parses as "not a listing payload", which reads as an empty
    result rather than as a bug.
    """
    return is_endpoint_url(url)


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

    NOTE what is actually on this site, because "no captcha" would be too
    strong and "captcha, therefore buy a key" would be too weak.

    The store ships Shopify's storefront-forms **hCaptcha** bundle
    (`ce_storefront_forms_captcha_hcaptcha.v1.5.3.iife.js`, sitekey
    `f06e6c50-85a8-45c8-87d0-21a2b65856fe`) on every page it serves. It is
    bound to FORM SUBMITS — the script hooks `submit` and looks for an
    `h-captcha-response` field — so it guards the newsletter, contact and
    account-creation forms and is never rendered on a listing, on a product
    page, or on any JSON route this engine reads. A scrape never meets it.

    Nothing else is present: zero reCAPTCHA, Turnstile, DataDome, PerimeterX,
    Incapsula, Kasada and AWS WAF markers across every capture, and no
    `data-sitekey` anywhere. (`recaptcha-v3-token` and `g-recaptcha-response`
    DO appear in the page — inside that same Shopify bundle, as two entries
    in a list of field names it checks for. They are not a reCAPTCHA, and both were counted on a page known to be good before
    either was left out of the marker set.)

    And to be explicit: this is a statement about what the PAGE
    carries, not about what can be solved. 2Captcha solves hCaptcha with
    `HCaptchaTaskProxyless`, so if the store ever puts one on a read path
    there is nothing here that says it could not be cleared — only that today
    no read path renders one.

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
    if not budget.spend():
        logger.info("Not buying another solve for this page: %d of %d "
                    "already bought. A challenge that survives a solved "
                    "token is not one this run can pass.",
                    budget.spent, budget.limit)
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

    `parse_product_detail` returns one row PER VARIANT — seven sizes of a
    one-piece are seven rows — so the two modes already agree on shape and
    neither needs wrapping. What differs is that a product document has no
    listing-level arithmetic to report, hence the None.

    The two entry points are separate on purpose and it is not tidiness. The
    two payloads are different documents — `{"products": [...]}` against
    `{"product": {...}}` — and each parser REFUSES the other's on the
    document's own evidence rather than returning something plausible. A
    listing parser handed a product document would otherwise emit one row
    whose `position` is 1 and whose page arithmetic was invented, and the run
    would look complete. `smoke_test.py` pins both directions.

    They also disagree about a UNIT: `/products/{h}.js` prices in integer
    cents and every other route in a decimal string. Which one a payload is
    is detected from the payload rather than from the URL, because a
    `--dump-html` replay arrives without one, and reading either as the other
    is a factor of 100 in every price.

    `page_num` is threaded through rather than defaulted, because `position`
    restarts at 1 on every page: without the page number beside it, a row
    from page 2 claims the same position as one from page 1 and the two are
    indistinguishable in the output. `smoke_test.py` asserts page+position
    is unique across a multi-page run for exactly that reason.
    """
    source_url = args.url or url
    currency = getattr(args, "resolved_currency", None)
    if args.mode == "product":
        rows = parse_product_detail(html, source_url, mode=args.mode,
                                    currency=currency)
        if args.category:
            for row in rows:
                row.category = args.category
        return rows, None
    listing = parse_listing(html, source_url, page=page_num, mode=args.mode,
                            currency=currency,
                            collection=collection_from_url(source_url),
                            catalog_count=getattr(args, "catalog_count", None),
                            page_size=args.limit)
    if args.category:
        for row in listing.rows:
            row.category = args.category
    return listing.rows, listing


def _fetch_text(session, url: str, timeout_ms: int = 30000) -> str:
    """Navigate and return whatever the address answered with.

    The one-shot reader for the two SUPPORTING fetches a run makes — the
    market's currency and the collection index. It goes through `_snapshot`
    rather than reading the page directly, so a JSON address is read as JSON
    (`innerText`) and an HTML one with `content()`, exactly as the paged
    fetches are. A supporting fetch that read the endpoint through Chromium's
    JSON viewer would come back as viewer markup and be silently unusable.
    """
    session.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    return _snapshot(session.page, url) or ""


def _resolve_run_currency(session, args) -> None:
    """Learn the market's currency ONCE, from something the store stated.

    The listing endpoint publishes no currency field at all — 180 products,
    1137 variants, not one `price_currency` among them — so without this
    every listing row would carry `currency: null`. The obvious alternative,
    mapping `en-gb` to GBP in this file, would be a table this repo invented
    rather than a fact the site published (a stated fact against a guess).

    Two JSON requests, and BOTH being JSON is the whole point:

        /{market}/products.json?limit=1   -> any published handle
        /{market}/products/{handle}.json  -> variants[].price_currency

    The first version of this read `Shopify.currency.active` off an HTML page
    instead, and it was WRONG in a way that only running all three engines
    exposed: the three disagreed on the same URL, playwright and pyppeteer
    reporting USD where Selenium reported EUR.

    The cause is worth recording, because it is a property of the store and
    not of the engines. There is no HTTP redirect anywhere — `curl -L` on
    every route follows zero hops — but the theme ships a **client-side**
    geolocation app that rewrites the location to the visitor's own market
    after the page loads. Measured 2026-09-18 from a Finnish address:
    `/collections/all` snapshotted at `domcontentloaded` says
    `Shopify.currency.active = "USD"`, and the same URL under Selenium, which
    waits for the full load, ends at `/en-fi/collections/all` saying `"EUR"`.
    Same address, two answers, decided by how long the engine happened to
    wait.

    A JSON endpoint runs no JavaScript, so it cannot be redirected that way
    and all three engines get the identical answer. It is also the BETTER
    source on the currency ladder — `price_currency` is stated beside the price it
    belongs to, where `Shopify.currency` is a page-level fact one step
    removed.

    Leaves `currency` None if neither request answers, and says so. A run
    with a null currency is honest and still useful; a run with a guessed or
    a wrong-market currency is neither.
    """
    if getattr(args, "resolved_currency", None):
        return
    market = _market(args)
    try:
        handle = None
        if args.mode == "product":
            handle = product_parser.handle_from_url(args.url or "")
        if not handle:
            probe = product_parser.store_products_endpoint(market, limit=1)
            sample = parse_products(_fetch_text(session, probe), probe)
            handle = sample[0].handle if sample else None
        if handle:
            doc = product_parser.product_json_endpoint(handle, market)
            code = payload_currency(product_parser.load_payload(
                _fetch_text(session, doc)))
            if code:
                args.resolved_currency = code
                args.currency_source = "price_currency"
                logger.info("Market %s prices in %s (read from %s).",
                            market or DEFAULT_LOCALE, code, handle)
                return
    except Exception as e:                       # noqa: BLE001
        logger.warning("Could not read the market's currency (%s). Rows will "
                       "carry currency: null rather than a guessed code.",
                       _mask_credentials(str(e)))
    args.resolved_currency = None
    args.currency_source = None

def _resolve_collection_index(session, args) -> None:
    """Confirm the collection exists, in ONE request, before anything else.

    `/collections/does-not-exist/products.json` answers **HTTP 200 with
    `{"products": []}`** — only the HTML route 404s — so a zero-row run is
    ambiguous on the listing document alone, and without this check every
    mistyped handle reports a successfully-scraped empty collection. That is
    the failure this costs one request to avoid.

    ONE request, and it used to be five. The first version walked
    `/collections.json?limit=250` until a page came back empty, because that
    is the endpoint the store's own front end uses to enumerate collections —
    834 of them, so four full pages plus the empty one, about a megabyte, on
    EVERY run including the ones that were never going to need the answer.
    Measured 2026-10-13: seven preflight requests to fetch one page of five
    products. A third-party audit was right to call that a cost worth
    measuring, and right that it raises the odds of meeting a rate limit.

    `/collections/{handle}.json` answers the same question better:

        /collections/one-pieces.json       HTTP 200, 536 bytes,
                                           products_count 472
        /collections/does-not-exist.json   HTTP 404, ZERO bytes

    Better rather than merely cheaper, because the walk could only ever
    report "the handle was not among the ones I managed to read" — a
    truncated walk and a missing collection looked identical. Here the store
    says outright that the route is not there, and `catalog_count` comes back
    in the same response.

    A failure here is a WARNING and never fatal: this is a nicety for
    reporting, and a run that fetched 180 real products should not be failed
    because a second request did not answer.
    """
    if args.mode != "listing":
        return
    handle = collection_from_url(args.url or "")
    if not handle:
        return
    url = product_parser.collection_endpoint(handle, _market(args))
    try:
        collection = product_parser.parse_collection(_fetch_text(session, url))
    except Exception as e:                       # noqa: BLE001
        logger.warning("Could not check whether %r is a published collection "
                       "(%s). A zero-row run will report `empty` without "
                       "being able to rule out a mistyped handle.",
                       handle, _mask_credentials(str(e)))
        return
    # An empty body IS the answer here: the JSON route spells a missing
    # handle as a 404 with no bytes at all. It is reported as "not
    # published" rather than as "could not tell", because those want
    # different things from the reader.
    args.collection_known = collection is not None
    args.catalog_count = (collection or {}).get("products_count")
    if not isinstance(args.catalog_count, int):
        args.catalog_count = None
    if collection is None:
        logger.warning("The store does not publish a collection called %r "
                       "(/collections/%s.json answers 404). Its products.json "
                       "will still answer HTTP 200 with an empty list, so "
                       "this run would otherwise look like a "
                       "successfully-scraped empty collection.",
                       handle, handle)
    else:
        logger.info("Collection %r is published (%s).",
                    handle, collection.get("title") or "no title")

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
    budget = page_flow.SolveBudget()
    throttle_waits = 0
    html, state, load_failed = None, "ok", False

    for block_attempt in range(block_retries + 1):
        logger.info("Fetching page %d/%d: %s", page_num, args.pages, url)
        # Retry a navigation timeout rather than ending the run on it. One
        # network flap on page 12 of 50 should not break the loop.
        load_failed, exit_failed = False, None
        # The navigation's own Response, kept rather than discarded.
        #
        # `page.goto()` RETURNS it, and throwing it away costs the classifier
        # the only unambiguous signal some answers have. A 429 arrives as 18
        # bytes of plain text that is neither a payload nor a page built out
        # of the store's assets, so without the status it classifies as
        # `unknown` — which waits the full readiness budget and then RETRIES,
        # which is the one response a throttle must not get quickly.
        status, retry_after = None, None
        for attempt in range(1, args.retries + 1):
            try:
                response = session.page.goto(url, wait_until="domcontentloaded",
                                             timeout=60000)
                if response is not None:
                    status = response.status
                    # Header names are case-insensitive and Playwright
                    # lowercases them; ask for the lowercase spelling.
                    retry_after = (response.headers or {}).get("retry-after")
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

        if handle_captcha_if_present(session.page, args, budget):
            # A solve navigated the page. Give the destination a moment
            # before judging what came back.
            session.page.wait_for_timeout(1000)

        html = _snapshot(session.page, url) or ""
        state = _classify(session.page, html, status)

        # A throttle is not a block and not a transient fault: re-asking at
        # once is what caused it. Wait what the edge asked for (or a backoff
        # when it asked for nothing), out of a budget of its own so it does
        # not eat `--retries`.
        if state == "throttled":
            if throttle_waits < page_flow.THROTTLE_WAITS:
                pause = page_flow.throttle_pause(retry_after, throttle_waits + 1)
                throttle_waits += 1
                logger.warning("The edge is throttling (%s). Waiting %.0fs at "
                               "the SAME exit and asking again (%d/%d) — this "
                               "is not a block and a different address would "
                               "not help.", detail_of(session.page, html, status),
                               pause, throttle_waits, page_flow.THROTTLE_WAITS)
                time.sleep(pause)
                continue
            logger.error("Still throttled after %d wait(s). Reporting it as a "
                         "throttle rather than as an empty catalogue: the "
                         "store never answered this page.",
                         page_flow.THROTTLE_WAITS)
            outcome.load_failed = True
            outcome.state = "throttled"
            outcome.final_url = session.page.url
            return outcome

        # A JSON endpoint arrives COMPLETE with its response, so there is
        # nothing to wait for on a healthy fetch and `wait_is_meaningful()`
        # says so per URL. Measured 2026-09-18 with no JavaScript executed at
        # all — a plain HTTP fetch — `/collections/one-pieces/products.json`
        # returned all 180 products in 0.44 s, and `/products/{h}.json`
        # returned its whole variant table.
        #
        # The wait below is therefore only for `unknown`: something arrived
        # that is neither one of the store's payloads nor a page built out of
        # its assets. That is the one case where waiting can still help — a
        # navigation that had not finished — and it is bounded.
        if state == "unknown":
            wait_timeout = page_flow.content_timeout_ms(args.mode)
            logger.info("Page %d is something the store served (%d bytes, "
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
            state = _classify(session.page, html, status)

        # The paid path is reached only for state "captcha" — a rendered
        # widget, which IS a test and can be solved. It is NOT reached for
        # "blocked": an edge refusal offers no widget, no sitekey and no
        # challenge of any kind, so a solve there would be a charge for
        # nothing. That distinction is the whole reason page_flow separates
        # the two states, and it is bounded by SOLVES_PER_PAGE so a rotation
        # loop cannot become a bill.
        if (page_flow.should_solve(state)
                and budget.allows()):
            if handle_captcha_if_present(session.page, args, budget):
                session.page.wait_for_timeout(1000)
                html = _snapshot(session.page, url) or html
                state = _classify(session.page, html, status)
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
            # a CORRECT one — a hub category has no grid, and one page past
            # the end of a listing has no products — so retrying it would
            # spend the user's budget re-confirming the same right answer,
            # and rotating the exit would blame an address for the URL it was
            # given.
            break

        # Blocked or challenged. A different exit is the one thing that
        # plausibly changes the outcome: the ADDRESS is what was scored, not
        # the URL, so retrying it unchanged would only confirm it. Measured
        # 2026-09-09 — the same URL that answers 403 from a datacentre exit
        # answers 200 from a residential one.
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
        #   a document with none of the store's  — something is
        #   assets on it                           intercepting: a captive
        #                                          portal, a proxy error page,
        #                                          or Chromium's own network
        #                                          error page, which carries
        #                                          the site's HOSTNAME in its
        #                                          title and would fool a
        #                                          title check.
        #   nothing at all                        — the connection failed.
        #
        # Saying which one arrived is more use than a captcha hint that would
        # cost money for a page carrying no widget.
        debug_html = f"{args.out}_page{page_num}_debug.html"
        with open(debug_html, "w", encoding="utf-8") as f:
            f.write(html or "")
        assets = references_own_assets(html or "")
        logger.error(
            "The store did not serve this request — %d bytes, its own asset "
            "host referenced %d time(s), saved to %s. There is no widget on "
            "it, so no key would help. Note what this is NOT: an ordinary "
            "datacenter address is served normally by this store (measured "
            "2026-09-18 — every route HTTP 200 with no User-Agent at all, "
            "and 20 rapid requests all 200), so a refusal here is "
            "unusual rather than expected. Check the User-Agent first — the "
            "edge refuses `curl`, `python-requests` and friends outright — "
            "then try a different exit with --proxy or --cdp-endpoint. This "
            "is exit 3, distinct from a genuinely empty result (exit 4).%s",
            len(html or ""), assets, debug_html,
            (f" Tried {block_retries + 1} exit(s)." if has_pool
             else f" Re-fetched {block_retries + 1} time(s)."))
        outcome.blocked_by = "edge refusal" if html else "no-response"
        outcome.final_url = session.page.url
        return outcome

    # No readiness wait and no scroll on the content path, and their absence
    # is MEASURED rather than forgotten — see the "unknown" branch above. A
    # JSON endpoint hands over the whole payload in one response, so there is
    # nothing to wait for and nothing to scroll into view. Porting the
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
    # answer, and a live run of a /p/<slug> hub reported exit 3 on a 191 KB
    # page the site had plainly served, because the hub's own performance
    # script names `akamaihd.net` and "akamai" was in the marker list. Both
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
        # This store states no result count anywhere, so `total_available`
        # and `pages_available` stay None — and None means UNKNOWN, never
        # zero. Treating a missing count as zero would cap every run after
        # page 1 at no pages at all.
        #
        # What IS reported is `products_returned`, the length of THIS
        # response's array before dedupe. It is the only signal separating
        # "the collection ended" (0) from "we were handed something that is
        # not a listing at all" (None).
        outcome.total_available = None
        outcome.pages_available = None
        outcome.sort_applied = listing.site_default_sort
        outcome.products_returned = listing.products_returned
        if page_num == 1:
            logger.info("Page 1 held %s product(s) (limit %s). The store "
                        "publishes no result count, so the run stops when a "
                        "page returns nothing or adds no new id.",
                        listing.products_returned, args.limit)
            if listing.catalog_count is not None:
                logger.info("The collection index reports products_count=%s "
                            "for %r. That is NOT a count of products the "
                            "storefront serves — measured 472 against 180 "
                            "and 3089 against 322 — so nothing is planned "
                            "from it. It is recorded so the gap is visible.",
                            listing.catalog_count, listing.collection)
            if not listing.sort_applied:
                logger.warning("The URL carries sort_by=%r, and the JSON "
                               "endpoint ignores it. These rows are in the "
                               "collection's own order; the `sort` column "
                               "says so rather than repeating the request.",
                               listing.sort)
            if listing.capped_by_site:
                logger.info("Predictive search is capped by Shopify at %d "
                            "results per type. For the catalogue use "
                            "--mode listing on a collection.",
                            product_parser.SEARCH_MAX_RESULTS)

    # Tell a BROKEN PARSER apart from an EMPTY CATEGORY before anything
    # downstream reports "0 products" and sends the reader to check the URL.
    if not products and page_flow.looks_like_a_parse_failure(
            state, len(products), product_link_count(html or "")):
        links = product_link_count(html or "")
        dump = f"{args.out}_page{page_num}_debug.html"
        with open(dump, "w", encoding="utf-8") as f:
            f.write(html or "")
        logger.error(
            "Page %d names %d product handle(s) and parsed to ZERO rows. "
            "The store served this — this is a failure in THIS parser, not "
            "an empty collection and not a block. Saved to %s; the first "
            "thing to check is whether the payload's top-level key is still "
            "`products`, then whether each entry still carries `handle`. "
            "Reported as stop_reason 'parser_found_nothing' so it cannot be "
            "read as a complete run.",
            page_num, links, dump)
        outcome.state = "parse_failed"

    if products:
        # Reported every time rather than only when it trips, so a consumer
        # gets the number rather than a threshold someone guessed.
        images = sum(1 for row in products if row.image_url)
        if images < len(products):
            logger.info("Page %d: %d/%d rows carry an image. 665 of 665 "
                        "products across four captured collections had one, "
                        "so a miss is worth a look — reported rather than "
                        "floored, because a product published without a photo "
                        "is the store's business and not a parsing fault.",
                        page_num, images, len(products))

        for field_name in CORE_FIELDS:
            filled = sum(1 for row in products
                         if getattr(row, field_name, None) not in (None, "", []))
            share = 100.0 * filled / len(products)
            if share < CORE_FIELD_FLOOR:
                logger.warning(
                    "Only %.0f%% of page %d carries `%s`, against a measured "
                    "floor of %d%%. All 665 products across four captured "
                    "collections had one, so this is the payload shape moving "
                    "rather than the products being unusual — re-run with "
                    "--dump-html.",
                    share, page_num, field_name, CORE_FIELD_FLOOR)

        priced = sum(1 for row in products if row.price is not None)
        price_share = 100.0 * priced / len(products)
        if price_share < PRICE_COVERAGE_FLOOR:
            logger.warning(
                "Only %.0f%% of page %d carries a price, against a measured "
                "floor of %d%%. Both the JSON-LD price and the DOM range "
                "count toward that, so a shortfall is a parsing break rather "
                "than the site's own variety — re-run with --dump-html.",
                price_share, page_num, PRICE_COVERAGE_FLOOR)

        if args.mode == "product":
            group = {row.product_id for row in products if row.product_id}
            available = sum(1 for r in products if r.in_stock is True)
            unknown = sum(1 for r in products if r.in_stock is None)
            logger.info("Product %s: %d variant(s), %d priced, %d available.",
                        next(iter(group), products[0].handle), len(products),
                        sum(1 for r in products if r.price is not None),
                        available)
            if unknown:
                # `/products/{h}.json` omits `available` entirely, so a run
                # off that endpoint knows the sizes and not which are in
                # stock. Said out loud rather than left as a column of nulls
                # the reader has to notice: `in_stock: null` is "not stated",
                # never "out of stock".
                logger.info("%d of %d variants state no availability — this "
                            "endpoint does not publish it. Those rows carry "
                            "in_stock: null, which means UNKNOWN and not "
                            "out-of-stock.", unknown, len(products))
        else:
            in_stock = sum(1 for row in products if row.in_stock is True)
            reduced = sum(1 for row in products if row.discount_pct)
            logger.info("Page %d: %d row(s), %d priced, %d in stock, %d "
                        "reduced.", page_num, len(products), priced,
                        in_stock, reduced)

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
    # One entry per page attempted, merged after the loop rather than folded
    # into shared state during it — see PageOutcome for why that ordering
    # matters more than it looks.
    outcomes: List[PageOutcome] = []
    seen_keys = set()
    blocked = False
    # Every mode emits one row per `sku` (a product in listing and search,
    # a variant in product mode), so `sku` is the key for all of them.
    dedupe_key = "sku"
    # Why the loop ended. "completed" means every requested page was fetched;
    # "no_new_products" means the listing itself ran out (also a complete
    # result). "single_page_mode" is complete by construction — a detail page
    # has no page 2. Anything else is an early stop, and the run is only a
    # partial view.
    # "page_cap_reached" means the run asked for more pages than the route
    # has. On this store that is a COMPLETE result in the strong sense: the
    # store imposes no cap at all, so a listing run that walks to the end
    # holds every published product in the collection — verified on the whole
    # catalogue, 250 + 250 + 250 + 22 = 772 distinct handles with page 5
    # empty.
    #
    # `--mode product` AND `--mode search` are single-response. The product
    # document is one document; predictive search is capped by Shopify at 10
    # results and has no page 2 to ask for. A listing is the only paginating
    # route, and it must never be treated as single-page — that is the
    # silent-success failure this family exists to avoid. Note "single page"
    # is a statement about FETCHING: `--mode product` still emits one row per
    # variant, so a one-page run of a seven-size one-piece is seven rows.
    stop_reason = ("single_page_mode" if args.mode in ("product", "search")
                   else "completed")

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
                        "one page to fetch (however many variants it holds).")
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
                           "This store serves an ordinary datacenter address "
                           "today with no rate limiting observed (20 requests "
                           "in 4.9 s, all 200), which makes an address that "
                           "works one worth not burning. Pass --proxy-file "
                           "to spread the load.", concurrency)
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
                # Always, on this store. The address a user types is a page
                # that carries none of the data; the address fetched is the
                # endpoint beside it. Logged rather than substituted quietly,
                # so a reader comparing the log against what they typed can
                # see it and check it.
                logger.info("Fetching the store's own endpoint rather than "
                            "the page (the page carries no grid): %s", target)

            _resolve_run_currency(session, args)
            _resolve_collection_index(session, args)

            # Page 1 is always fetched on its own: its content is what decides
            # how many pages 2..N there are to address at all.
            first = _fetch_one_page(session, args, pool, 1, target)
            outcomes.append(first)

            if not first.ok:
                stop_reason = ("page_load_timeout" if first.load_failed
                               else f"blocked_{first.blocked_by}")
                blocked = first.blocked_by is not None
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
            # this page. This store's pagination was measured NOT repeating:
            # walking the whole catalogue at limit=250 gave 772 rows and 772
            # distinct handles. So any non-zero count here is worth a look,
            # and a count near the page size means a page was re-fetched
            # rather than advanced.
            logger.info("Page %d: dropped %d duplicate row(s).",
                        oc.page_num, len(oc.products) - len(fresh))
        all_rows.extend(fresh)

    # Completeness, checked over the MERGED result rather than per page — a
    # per-page check cannot see a gap BETWEEN two pages, which is exactly
    # where a short page hides.
    #
    # NOT "pages x rows-per-page" as a hard expectation, even though the
    # page size is the run's own `sz`: the LAST page of a listing is
    # legitimately short — /en-fi/writing-instruments ends 240 + 24 + 16 =
    # 280 — and a threshold that fires on every healthy run teaches the
    # reader to ignore it. What is worth warning about is a page that came
    # back materially THIN against its siblings, which is what a truncated
    # response looks like.
    total_available = next((o.total_available for o in outcomes
                            if o.total_available is not None), None)
    pages_available = next((o.pages_available for o in outcomes
                            if o.pages_available is not None), None)
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
                "(%d rows): %s. This store fills every page but the last one "
                "to the requested limit, so a short page in the MIDDLE of a "
                "run is a truncated response rather than a short collection "
                "— re-run with --dump-html.",
                ", ".join(str(p) for p, _ in thin), fullest,
                ", ".join("page %d: %d" % (p, n) for p, n in thin))
        # No "x% of the catalogue" line here, and the absence is the
        # finding. bbb-scraper can print one because that site states a
        # `totalResults`; this store states nothing usable — its
        # `products_count` is not a count of products it serves (472 against
        # 180, 3089 against 322) — so a share computed from it would be a
        # percentage of a number that was never right. A count that rots
        # is worse than no count.
        #
        # What CAN be said honestly is said instead: a listing run that
        # reached the end of the collection holds all of it, because the
        # store imposes no cap. The end is reached when a page returns no
        # products, and `stop_reason` records whether it was.
        if getattr(args, "catalog_count", None) is not None:
            logger.info("This run holds %d row(s) across %d page(s). The "
                        "collection index's products_count for %r is %s — NOT "
                        "a target this run missed; it counts something other "
                        "than products the storefront serves.",
                        len(all_rows), len([o for o in outcomes if o.ok]),
                        collection_from_url(args.url or ""),
                        args.catalog_count)

    ok_pages = [o for o in outcomes if o.ok]
    failed_pages = [o.page_num for o in outcomes if not o.ok]
    final_url = (max(ok_pages, key=lambda o: o.page_num).final_url
                 if ok_pages else args.url)

    # One-per-run context, in the sidecar rather than repeated down a column.
    #
    # `locale` and `currency` are the load-bearing pair, and they are not
    # decoration: this store SETS prices per market rather than converting
    # them, so a file of prices without the market it was read from is a file
    # of numbers without units. Both are on every row as well, because a
    # consumer merging two runs needs them per row.
    #
    # `catalog_count` is here with its warning attached rather than omitted,
    # because the gap is the interesting part: a reader who fetches the
    # collection index themselves will see 472 against this run's 180 and
    # deserves to be told, in the artefact, that the larger number is not a
    # target this run missed.
    extra = None
    if args.mode != "product":
        extra = {"total_results": total_available,
                 "pages_available": pages_available,
                 "page_size": args.limit,
                 "locale": locale_from_url(final_url or args.url),
                 "currency": getattr(args, "resolved_currency", None),
                 "currency_source": getattr(args, "currency_source", None),
                 "collection": collection_from_url(args.url or ""),
                 "catalog_count": getattr(args, "catalog_count", None),
                 "catalog_count_note":
                     ("the collection index's products_count; NOT a count of "
                      "products the storefront serves (measured 472 against "
                      "180 and 3089 against 322) — nothing is planned from it"
                      if getattr(args, "catalog_count", None) is not None
                      else None),
                 "sort_applied": product_parser.SITE_DEFAULT_SORT,
                 "sort_is_configurable": False,
                 "capped_by_site": args.mode == "search"}
        # `capped_by_site` is True only for `--mode search`, where Shopify
        # caps predictive search at 10 results per type. A LISTING is not
        # capped at all — a run that walks a collection to the end holds
        # every published product in it — which is the opposite of
        # bbb-scraper, where that site refuses to serve past page 15 however
        # many rows matched and "complete" can mean a 1.2% sample. There is
        # deliberately no `reachable_max`: pages x page_size would OVERSTATE
        # a short last page (2 x 250 = 500 on a collection holding 322).

    return finish_run(all_rows, args.out, args.format, args.allow_empty,
                      blocked=blocked, stop_reason=stop_reason,
                      pages_requested=args.pages, pages_completed=len(ok_pages),
                      pages_failed=failed_pages, mode=args.mode,
                      source=SOURCE_DEFAULT,
                      start_url=args.url, final_url=final_url,
                      extra=extra)


def parse_args():
    p = argparse.ArgumentParser(
        description="Andie Swim scraper (Playwright edition)")
    p.add_argument("--url", default=None,
                   help="An andieswim.com URL: a collection listing "
                        "(/collections/one-pieces), a search "
                        "(/search?q=bikini) or one product "
                        "(/products/{handle}) with --mode product. The store "
                        "serves all 200 markets from ONE host with the market "
                        "in the PATH (/en-gb/collections/…), so there is no "
                        "per-country hostname. Whatever is passed, the fetch "
                        "goes to the store's own JSON endpoint beside it — "
                        "the rendered page carries no product grid. Optional: "
                        "--query or --category build the URL instead. Also "
                        "read from ANDIESWIM_URL in the environment or "
                        "in .env.")
    p.add_argument("--query", default=None, metavar="TEXT",
                   help="What to search for, e.g. 'bikini top'. Builds a "
                        "/search URL together with --locale, so a run needs "
                        "no hand-assembled URL. Ignored when --url is given. "
                        "NOTE Shopify caps predictive search at 10 results "
                        "per type and there is no page 2 — for the catalogue "
                        "use --mode listing on a collection.")
    p.add_argument("--locale", default=None, metavar="LOCALE",
                   help="Which market to read, as the store spells it in its "
                        "own paths: en-gb, en-ca, en-au, en-de, en-jp "
                        "(default %s, which is the BARE path — the US store "
                        "has no prefix). This is NOT cosmetic and it is not "
                        "the browser's locale: it selects the storefront, and "
                        "the store SETS its prices per market rather than "
                        "converting them. One variant, 2026-09-18: 112.00 USD "
                        "/ 195.00 CAD / 110.00 GBP / 175.00 AUD / 130.00 EUR "
                        "/ 21600 JPY. 110 GBP is about 148 USD against a 112 "
                        "USD list, so a cross-market gap is pricing policy, "
                        "not arbitrage. The store's sitemap names 200 "
                        "markets, all en-xx; five are verified by a live "
                        "fetch and the rest are accepted with a note. REFUSED "
                        "together with a --url that already carries a "
                        "different prefix, because reading one market under "
                        "another's label is a silent wrong answer."
                        % DEFAULT_LOCALE)
    # NO `--sort` HERE, DELIBERATELY, and `smoke_test.py` asserts it stays
    # absent (guard a removed flag, or an editor reintroduces it).
    #
    # The JSON endpoint does not take `sort_by` and ignores one that is
    # passed — verified 2026-09-18, the response is the same with and
    # without. A flag would therefore report an ordering the fetch never
    # applied, which is "never present a guess as a fact" with a column
    # attached. The sibling repo NEEDS its `--sort` because that site caps a
    # result set and the ordering decides which rows land inside the cap;
    # here nothing is capped, so ordering decides `position` and nothing
    # else, and two runs under different orderings hold the same rows.
    p.add_argument("--limit", type=int, default=PAGE_SIZE, metavar="N",
                   help="Products per request (default %(default)s). Shopify "
                        "caps this at 250 and ignores anything larger — "
                        "checked: limit=1000 returned 250 — so the default "
                        "is the cap, and one request covers most collections "
                        "outright (one-pieces holds 180). Lower it only to "
                        "look less like one request for a whole catalogue.")
    p.add_argument("--mode", choices=["listing", "search", "product"],
                   default=DEFAULT_MODE,
                   help="listing (default): a collection, read from "
                        "/collections/{handle}/products.json — one row per "
                        "PRODUCT, and the only paginating mode. search: "
                        "/search/suggest.json — one row per product, capped "
                        "by Shopify at 10 results with no page 2, so it is a "
                        "lookup rather than a catalogue walk. product: one "
                        "product, which emits ONE ROW PER VARIANT out of its "
                        "variant table — seven sizes of a one-piece are seven "
                        "rows, each with its own sku, size, colour, price and "
                        "stock. That last is the question a product document "
                        "exists to answer: 116 of 180 one-pieces are "
                        "available in SOME sizes and not others, and a "
                        "listing row cannot say which. --pages applies to "
                        "--mode listing only.")
    p.add_argument("--category", default=None,
                   help="Either a collection HANDLE to build a URL from "
                        "('one-pieces', 'bikinis', 'sale'), used when no "
                        "--url is given, or a label to tag output rows with. "
                        "Rows otherwise carry the store's own `product_type` "
                        "('One Piece', 'Bikini Top'), populated on 665 of 665 "
                        "products measured, so the column is filled without "
                        "the flag.\n"
                        "Unlike the sibling repo's category paths, a handle "
                        "is NOT market-specific: /collections/one-pieces and "
                        "/en-gb/collections/one-pieces are both real. The "
                        "store publishes 830 collections; "
                        "/collections.json?limit=250 lists them.")
    p.add_argument("--pages", type=page_flow.PAGES, default=1,
                   help="Number of listing pages to fetch. Applies to --mode "
                        "category and --mode search; ignored in --mode "
                        "product. Page 1 prints the catalogue's own result "
                        "count, so a run PLANS against the site's arithmetic "
                        "rather than walking off the end. There is no page "
                        "cap on this site — asking past the last page is a "
                        "served, empty grid rather than an error — so a "
                        "request is limited only by what the category holds, "
                        "and the sidecar records both numbers.")
    p.add_argument("--delay", type=page_flow.SECONDS, default=2.0, help="Delay between pages, seconds")
    p.add_argument("--concurrency", type=page_flow.WORKERS, default=1, metavar="N",
                   help="Fetch pages through N parallel workers (default 1 — "
                        "unchanged sequential behaviour). Each worker runs its "
                        "own browser and holds its own proxy exit, so N>1 "
                        "without --proxy-file just sends N times the traffic "
                        "from one address. Ignored with --cdp-endpoint.")
    p.add_argument("--retries", type=page_flow.attempts, default=3,
                   help="Attempts per page load before giving up (default 3). "
                        "The pause between attempts doubles each time. A page "
                        "that comes back EMPTY is not retried — see "
                        "page_flow.STATE_POLICY — because a hub page with no "
                        "products on it is a correct answer, not a fault.")
    p.add_argument("--retry-delay", type=page_flow.SECONDS, default=2.0,
                   help="Seconds before the first page-load retry, doubling "
                        "thereafter (default 2.0)")
    p.add_argument("--format", choices=["json", "csv", "both"], default="both")
    p.add_argument("--out", default="andieswim_products", help="Output file prefix")
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
    p.add_argument("--proxy-block-retries", type=page_flow.EXTRA_ATTEMPTS, default=2,
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
                        "a column comes back empty — see TROUBLESHOOTING.md.")
    p.add_argument("--headless", action="store_true", default=True)
    p.add_argument("--headful", dest="headless", action="store_false")
    args = p.parse_args()
    # Recorded BEFORE the environment is applied: afterwards a typed --url
    # and one from ANDIESWIM_URL are indistinguishable, and only the typed
    # one may conflict with --query/--category/--locale.
    typed_url = args.url
    # Fill --twocaptcha-key / --cdp-endpoint / --proxy / --url from the
    # environment or .env when the flag was not given. An explicit flag wins.
    env_config.apply(args)

    # --url and the query flags are two ways to say the same thing. A typed
    # --url that disagrees with --locale or --query is refused: a --locale
    # disagreeing with the market in the URL would silently read a different
    # MARKET, which on this site is a different price, not just a different
    # language. There is one host for every market, so the flag cannot
    # contradict a HOSTNAME, only a path segment, and this is where that is
    # caught. A URL from the environment is a default and gives way.
    conflict = page_flow.reconcile_url_flags(args, typed_url)
    if conflict:
        p.error(conflict)

    locale = (args.locale or DEFAULT_LOCALE).strip().lower()
    if locale != DEFAULT_LOCALE and not market_is_well_formed(locale):
        p.error("%r is not a market prefix this store publishes. They are all "
                "spelled `en-xx` with a two-letter country — %s are verified "
                "— and the bare path (%s) is the US store."
                % (locale, ", ".join(VERIFIED_MARKETS), DEFAULT_LOCALE))
    if locale != DEFAULT_LOCALE and locale not in VERIFIED_MARKETS:
        # A WARNING, not an error, and the shape of the list is the reason.
        # The store's sitemap index names 200 markets; five of them were
        # fetched and confirmed to return their own currency. Hardcoding 200
        # two-letter pairs would be a table that rots, and refusing an
        # unverified-but-well-formed one would refuse 195 real markets. If
        # the market does not exist the store answers 404 and the run reports
        # that rather than guessing.
        logger.info("%r is well-formed but is not one of the markets verified "
                    "by a live fetch (%s). The store publishes 200 of them, "
                    "so this is very likely real — continuing.",
                    locale, ", ".join(VERIFIED_MARKETS))

    if not args.url and args.query:
        if args.mode == "product":
            p.error("--mode product needs a --url: a product is one page at "
                    "one address, and --query describes a search.")
        args.mode = "search"
        market = None if locale == DEFAULT_LOCALE else locale
        args.url = "https://%s%s/search?q=%s" % (
            product_parser.CANONICAL_HOST,
            ("/" + market) if market else "",
            quote(args.query))
        logger.info("Built the search URL from --query: %s", args.url)
    elif not args.url and args.category:
        # `--category` is doing double duty — a path to build a URL from when
        # there is no --url, and a label to tag rows with when there is. That
        # is the family's flag and this is the reading that makes it useful
        # on a site whose category paths ARE the addresses.
        args.url = collection_url(args.category.strip("/").lower(),
                                  None if locale == DEFAULT_LOCALE else locale)
        logger.info("Built the listing URL from --category: %s", args.url)

    if not args.url:
        p.error("no --url given and no --query/--category: pass an "
                "andieswim.com URL, or --query 'bikini top', or --category "
                "'one-pieces'. ANDIESWIM_URL in the environment or in .env "
                "works too.")

    supported, why = is_supported_url(args.url)
    if not supported:
        # Refused rather than attempted. This parser reads this store's own
        # Shopify JSON and its `/collections/…` and `/products/…` URL shapes;
        # pointing it at another site would not fail loudly, it would return
        # zero rows and look like an empty result. The REASON is given,
        # because "is not an andieswim.com site" about a host that plainly is
        # one sends the reader hunting a typo they did not make.
        p.error(f"{args.url!r} {why}.")

    if args.mode == "product" and not is_product_url(args.url):
        p.error(f"--mode product expects a /products/{{handle}} URL; "
                f"{args.url!r} is not one. A collection listing is "
                f"--mode listing.")
    if args.mode != "product" and is_product_url(args.url):
        p.error(f"{args.url!r} is a single product page. Use --mode product "
                f"for it — which reads its whole variant table — or pass a "
                f"category or /search URL.")

    if args.mode == "product" and args.pages != 1:
        # Said out loud rather than silently ignored: a user who passed
        # --pages 5 expects five pages of something.
        logger.warning("--pages %d is ignored in --mode product: there is one "
                       "page to read. It still emits one row per variant, so "
                       "the output is not one row. The run status will say "
                       "single_page_mode.", args.pages)
        args.pages = 1
    if args.limit < 1:
        p.error("--limit must be at least 1")
    if args.limit > product_parser.MAX_PAGE_SIZE:
        logger.warning("--limit %d exceeds the %d Shopify will serve; it "
                       "ignores the excess rather than erroring, so this run "
                       "will get %d per request.",
                       args.limit, product_parser.MAX_PAGE_SIZE,
                       product_parser.MAX_PAGE_SIZE)
        args.limit = product_parser.MAX_PAGE_SIZE
    return args


if __name__ == "__main__":
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
