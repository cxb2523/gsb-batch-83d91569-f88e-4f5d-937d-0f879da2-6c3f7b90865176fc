"""
mercor-scraper — Selenium edition

Scrapes mercor.com: the marketplace index, one marketplace listing, and
Mercor's own corporate openings.

    --mode listings  work.mercor.com/explore
                     The marketplace index. 390 contract roles in ONE
                     response — rates, domains, eligibility, slot counts.
    --mode job       work.mercor.com/jobs/{id}/{slug}
                     One listing, with the company website, the company
                     description and a currency the index does not publish.
                     Enumerated from the sitemap and the index.
    --mode careers   www.mercor.com/careers
                     Mercor's own salaried roles, via Ashby.

What is different about Mercor
==============================

* **Nothing is gated.** Measured 2026-09-18 from a Hetzner datacentre
  address (AS24940, Helsinki): eighteen candidate bot-challenge markers
  counted across seven captures, every one zero; identical 200s from
  `curl`, from `python-requests` and from an EMPTY User-Agent. No captcha,
  no proxy and no key is needed for any route this engine reads.

* **The rows are not in the DOM, and the obvious structured source is the
  wrong one.** `/explore` carries an `ItemList` JSON-LD of 326 URLs and a
  React Query cache of 390 complete records; the JSON-LD omits every one of
  the 55 `evergreen` listings. `product_parser` reads the cache.

* **Hydration rewrites every job anchor.** The served markup has
  `href="/jobs/list_…"`, the live DOM has `href="/explore?listingId=…"`.
  Anything anchored to the DOM here must be checked in a real browser and
  not in a capture — see `page_flow.READY_SELECTOR_LISTING` for what the
  single-spelling version cost.

* **`/explore` has no second page.** `?page=2`, `?limit=`, `?offset=` and
  `?domain=` each returned a byte-identical payload. In `--mode job` a
  "page" is one job instead, and those addresses are read from the sitemap
  rather than guessed from a convention.

* **No single route enumerates the catalogue.** sitemap 447, explore 390,
  shared 375, union 462 — neither contains the other, and the 72
  sitemap-only listings are live jobs.

Usage
-----
    python3 selenium_scraper.py
    python3 selenium_scraper.py --mode careers
    python3 selenium_scraper.py --mode job --pages 50
    python3 selenium_scraper.py --mode job --url "https://work.mercor.com/jobs/list_AAABoGhhxWgF7ygE2LZOgIy3/b-2-b-sales-expert-3-yoe-us-only"

This site answered every one of those from a bare datacentre IP with no
credentials on 2026-09-18. `--proxy` and `--cdp-endpoint` work and are not
required.

Two Selenium limits worth knowing before you reach for them: chromedriver's
`debuggerAddress` takes a bare host:port with nowhere to put a password, so
this engine cannot use an AUTHENTICATED remote CDP endpoint; and
`--proxy-server` cannot authenticate at all, so credentials are stripped
and warned about rather than silently ignored.
"""

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse, urlsplit

from selenium import webdriver
from selenium.common.exceptions import (TimeoutException, WebDriverException,
                                        JavascriptException)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from captcha_solver import (detect_recaptcha_v3, detect_recaptcha_in_page,
                            reconcile_detections, solve_recaptcha,
                            CaptchaUnsolvable, INJECT_TOKEN_JS,
                            RECAPTCHA_DISCOVERY_JS, detect_turnstile,
                            wait_for_turnstile, TURNSTILE_INTERCEPT_JS,
                            TURNSTILE_INJECT_JS, turnstile_task_for)
from product_parser import (MODES, DEFAULT_MODE, category_from_url,
                            detect_bot_challenge, is_supported_url,
                            mode_for_url, page_url, parse_detail,
                            parse_listing_page, parse_careers_page,
                            references_own_assets, site_turnstile_sitekey,
                            enumerate_job_sources, EnumerationResult,
                            route_of,
                            EXPLORE_URL, CAREERS_URL, SITEMAP_URL)
from output_writer import (dedupe_by_key, finish_run, EXIT_API_ERROR,
                           SOURCE_DEFAULT)
import page_flow
from page_flow import MIN_CARD_MATCHES
from proxy_pool import (from_args as proxy_pool_from_args, mask, ROTATE_MODES,
                        ProxyError, split_credentials)
import env_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("selenium_scraper")

ITEM_LINK_SELECTOR = page_flow.READY_SELECTOR_LISTING

# The share of rows that must carry the columns Mercor fills on every
# record, below which the read has broken rather than the data being
# unusual. 390 of 390 listing records carried all four on 2026-09-18.
#
# Deliberately NOT here, each with the measurement that keeps it out:
# `company_name` (99 of 390 — Mercor runs most of its marketplace for
# unnamed clients), `hours_per_week` (294 of 390), `eligible_locations`
# (134 of 390), `rate_currency` (0 on the index, which publishes none).
CORE_FIELD_FLOOR = 99
CORE_FIELDS = ("title", "url", "sku", "rate_min")

# --mode careers. Different rather than shorter: an Ashby record always
# states a department, but only 106 of 108 state a salary, so `rate_min`
# cannot carry a 99% floor here.
CORE_FIELDS_CAREERS = ("title", "url", "sku", "department")

# --mode job. A detail page publishes no `domain` and names a company on
# only some listings, so the floor is the four fields every one of the 7
# detail captures carried.
CORE_FIELDS_JOB = ("title", "url", "sku", "rate_min")


def _core_fields(mode: str):
    if mode == "job":
        return CORE_FIELDS_JOB
    if mode == "careers":
        return CORE_FIELDS_CAREERS
    return CORE_FIELDS


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
    # The target's 5xx status when the page ended as a server error after
    # its retries (see page_flow.target_server_error). Not ok: no content.
    server_error: Optional[int] = None
    state: Optional[str] = None
    # What this response said about itself. Mercor publishes no catalogue
    # and how many pages the site will serve. Real numbers here, unlike the
    # sibling repos' result headers — they are what pages are planned from.
    total_available: Optional[int] = None
    total_companies: Optional[int] = None
    # How many entries the same response's ItemList JSON-LD indexes. 326
    # against 390 records on 2026-09-18 — the gap is why the parser reads
    # the React Query cache, and recording it per run means nobody inherits
    # the figure from a comment.
    urls_in_itemlist: Optional[int] = None
    pages_available: Optional[int] = None
    # The page number the SERVER answered with. Always 1 here, because
    # `/explore` has exactly one page; kept so the three engines carry the
    # same outcome shape and so a site that starts paginating is detected
    # rather than assumed away.
    echoed_page: Optional[int] = None

    @property
    def ok(self) -> bool:
        return (not self.load_failed and self.blocked_by is None
                and self.server_error is None)


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
        # The ONLY way this engine can learn an HTTP status. `driver.get()`
        # returns None and WebDriver exposes no status anywhere, while on
        # this site the status is very nearly the only thing separating a
        # withdrawn listing from a page with nothing on it. Chrome's
        # performance log carries `Network.responseReceived`, and the
        # document entry whose url matches the request carries `status`.
        #
        # Without this, two engines would be better informed than the third
        # about whether a listing still exists — and a fix that reaches two
        # of three twins is the drift `page_flow` exists to prevent.
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
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
        # does NOT decide which route is read — that is --mode, or --url —
        # so this only affects what the browser
        # claims about itself.
        options.add_argument(f"--lang={self.args.locale}")

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
    # forgotten: Mercor serialises its whole result set into
    # __NEXT_DATA__ in the first response, so
    # there is nothing to scroll into view. Mirrors the Playwright engine.
    return {"count": count, "sleep": sleep, "content": content,
            "current_url": current_url}


def _is_single_job_url(args) -> bool:
    """Whether `--url` names one specific job, rather than a route to walk.

    A `--mode job` run given a job URL fetches exactly that job and nothing
    else — no sitemap, no enumeration, one row.
    """
    return bool(args.url) and route_of(args.url) == "job"


def _plan_page_urls(args, page_one_url, pages_available, job_urls=None):
    """URLs for pages 2..N, decided once before any of them is fetched.

    Mercor needs no hedging between a site's next-link and a URL
    convention, and for the opposite reason to most sites in this family:
    it has nothing to hedge ABOUT.

      * `/explore` and `/careers` have exactly one page each. Measured
        2026-09-18, `?page=2`, `?limit=10`, `?offset=100` and
        `?domain=Finance` on `/explore` each returned a byte-identical
        payload of the same 390 records. `page_url()` returns None by
        design, and this plans nothing.
      * `--mode job` plans from a REAL LIST — the enumeration built from
        `/sitemap.xml` and the `/explore` payload — so every planned page
        is an address the site published, and the plan cannot run off the
        end because it is capped by the length of the list.
    """
    if args.mode == "job":
        if not job_urls:
            return []
        wanted = page_flow.pages_to_plan(args.pages, len(job_urls))
        if wanted < args.pages:
            logger.info("The enumeration holds %d job(s) and %d page(s) were "
                        "asked for; planning %d. There is no more catalogue "
                        "to walk to.", len(job_urls), args.pages, wanted)
        return list(job_urls[1:wanted])

    if not page_flow.pagination_is_addressable(page_one_url):
        if args.pages > 1:
            logger.info(
                "%s is served at ONE address and holds its whole result set "
                "in a single response, so %d page(s) were asked for and 1 "
                "will be fetched. Every pagination parameter tried on it was "
                "ignored, so planning a page 2 would re-collect page 1 and "
                "report a complete multi-page run. Use --mode job if you "
                "want many pages: there a page is one job.",
                page_one_url, args.pages)
        return []

    wanted = page_flow.pages_to_plan(args.pages, pages_available)
    planned = []
    for n in range(2, wanted + 1):
        built = page_url(page_one_url, n)
        if built is None:
            break
        planned.append(built)
    return planned


def _enumerate_jobs(fetch_source, args) -> EnumerationResult:
    """Every job address this run could fetch, and whether that list is whole.

    The logic is `product_parser.enumerate_job_sources`, shared by all three
    engines; `fetch_source` is supplied by this engine so both reads leave
    from the same exit as the pages they plan.
    """
    return enumerate_job_sources(fetch_source, scrub=_mask_credentials,
                                 attempts=args.retries, pause=time.sleep)


def _parse_for_mode(html: str, url: str, args, page_num: int = 1):
    """(rows, listing) for this mode. `listing` is None outside --mode listings.

    `page_num` is threaded through rather than defaulted, because `position`
    restarts at 1 on every page: without the page number beside it, a row
    from page 2 claims the same position as one from page 1 and the two are
    indistinguishable in the output.
    """
    if args.mode == "job":
        row = parse_detail(html, url=url)
        return ([row] if row is not None else []), None
    if args.mode == "careers":
        return parse_careers_page(html, url=url), None
    listing = parse_listing_page(html, url=url, page=page_num)
    return listing.rows, listing


def _is_endpoint(url: str) -> bool:
    """Whether this address answers with raw JSON rather than a document.

    Always False on Mercor: unlike the sibling repo this engine was
    ported from, there is no ungated JSON endpoint here — every route is an
    HTML page with its payload serialised inside it. Kept so the three
    engines' snapshot paths branch identically.
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


def _document_status(session, url: str):
    """The HTTP status Chrome recorded for the document at `url`, or None.

    Reads `Network.responseReceived` out of the performance log and takes
    the entry whose own url matches the one requested. Matching matters:
    the log also carries the reCAPTCHA anchor iframe (200) and, on a dead
    job, the `/login` page Mercor bounces to (200). Taking the last
    Document entry instead of the matching one reports 200 for a 404 —
    which is what the first version of this did, measured against a URL
    `curl` had already confirmed as 404.

    Returns None rather than raising if logging is unavailable: an older
    chromedriver, a non-Chrome driver, or a remote endpoint that does not
    grant logs. The caller then falls back to `bounced_to_login`, which
    needs no status.
    """
    try:
        entries = session.driver.get_log("performance")
    except Exception:  # noqa: BLE001 - no logs is not a run-ending problem
        return None
    wanted = (url or "").split("#")[0]
    status = None
    for entry in entries:
        try:
            msg = json.loads(entry.get("message", "{}")).get("message", {})
        except (ValueError, TypeError):
            continue
        if msg.get("method") != "Network.responseReceived":
            continue
        params = msg.get("params") or {}
        if params.get("type") != "Document":
            continue
        response = params.get("response") or {}
        if (response.get("url") or "").split("#")[0] == wanted:
            status = response.get("status")
    return status


def _fetch_page_source(session, url: str, timeout_ms: int = 60000) -> str:
    """Navigate and return the serialised document. Used for enumeration.

    `page_source` rather than a text reading, and that matters for the
    sitemap: Chromium renders `text/xml` through its own XML viewer, and the
    serialised document keeps all 463 `<loc>` elements intact where the
    viewer's rendered text does not.
    """
    session.driver.set_page_load_timeout(max(1, timeout_ms // 1000))
    session.driver.get(url)
    return session.driver.page_source or ""


def handle_captcha_if_present(session, args, on_purchase=None) -> bool:
    """Detect and solve a challenge. True if something was solved.

    Same detectors, same reconciliation and the same "detected is not
    blocking" rule as the Playwright engine — the three must agree about
    when a run spends money.

    NOTE what this has never had to help with: Mercor has rendered no
    challenge to this scraper on any route, from any client, on any of the
    seven captures taken 2026-09-18. See product_parser.detect_page_state.
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
    if on_purchase is not None:
        # Counted HERE, at the one moment money is committed, rather than by
        # the caller before it knows whether anything will be bought: a call
        # that found no challenge must not spend the page's allowance.
        on_purchase()
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
    """The address this run actually fetches.

    Every mode has a correct default, so a bare invocation is a working
    command rather than a usage error: Mercor's index takes no parameters,
    so the only choice a user has is which of three routes to read, and
    `--mode` is that choice.
    """
    if args.url:
        return args.url
    if args.mode == "careers":
        return CAREERS_URL
    return EXPLORE_URL


def _solve_budget(args, spent: int):
    """Whether another solve may be bought for this page.

    `page_flow.SOLVES_PER_PAGE` says at most one purchase per page, and that
    is a MONEY limit rather than a style rule. It was not being enforced:
    `handle_captcha_if_present` is called twice per attempt — once before the
    page is classified and once after — and only the SECOND call was counted.

    INHERITED EVIDENCE, from a SIBLING repo and not from Mercor — labelled
    because a number you inherited is not a number you measured,
    and this one cannot be reproduced here: Mercor has never rendered a
    challenge to this scraper, so no page of this site has ever bought a
    solve at all.

    On that sibling, from a datacenter address that meets a real Cloudflare
    challenge on every fetch (2026-09-17): ONE page bought THREE Turnstile
    solves, and every token was refused. The cap read as enforced and was
    not. Both call sites now go through here.

    The fix is carried here anyway. A budget that is never exercised is
    still the difference between a bill and no bill on the day it is.
    """
    return spent < page_flow.SOLVES_PER_PAGE


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
    solves_bought = 0

    for block_attempt in range(block_retries + 1):
        logger.info("Fetching page %d/%d: %s", page_num, args.pages, url)
        load_failed, exit_failed = False, None
        http_status = None
        for attempt in range(1, args.retries + 1):
            try:
                # Drain anything from a previous navigation first, or the
                # status read afterwards can belong to the last page.
                try:
                    session.driver.get_log("performance")
                except Exception:  # noqa: BLE001
                    pass
                session.driver.get(url)
                http_status = _document_status(session, url)
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


        # Counted, because it can BUY. See _solve_budget.
        if _solve_budget(args, solves_bought):
            bought = []
            solved = handle_captcha_if_present(
                session, args, on_purchase=lambda: bought.append(1))
            solves_bought += len(bought)
            if solved:
                time.sleep(1)

        elif solves_bought:
            logger.info("Not solving again on page %d: %d purchase(s) "
                        "already made for it and SOLVES_PER_PAGE is %d.",
                        page_num, solves_bought, page_flow.SOLVES_PER_PAGE)
        html = _snapshot(session, url) or ""
        state = page_flow.classify(html, http_status, d["current_url"](),
                                   mode=args.mode)

        # Mercor server-renders its payload, so a page is parseable in the
        # FIRST response and there is nothing to wait for on a healthy page.
        # Measured with no pause at all after the load. The wait below is
        # only for the state that says Mercor served SOMETHING that is not the
        # payload. Mirrors playwright_scraper exactly.
        if state == "unknown":
            wait_ms = page_flow.content_timeout_ms(args.mode)
            sel = page_flow.ready_selector(args.mode)
            need = page_flow.min_matches(args.mode)
            logger.info("Page %d is something Mercor served (%d bytes, its own "
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
            state = page_flow.classify(html, http_status, d["current_url"](),
                                       mode=args.mode)

        # The paid path is reached only for state "challenge" — Cloudflare's
        # Managed Challenge, which IS a test. It is NOT reached for
        # "blocked": the hard "You have been blocked" page carries no widget
        # and no sitekey, so a solve there would be a charge for nothing.
        # Bounded by SOLVES_PER_PAGE. Mirrors playwright_scraper.
        if (page_flow.should_solve(state)
                and _solve_budget(args, solves_bought)):
            bought = []
            solved = handle_captcha_if_present(
                session, args, on_purchase=lambda: bought.append(1))
            solves_bought += len(bought)
            if solved:
                time.sleep(1)
                html = d["content"]() or html
                state = page_flow.classify(html, http_status,
                                           d["current_url"](), mode=args.mode)
                if state == "content":
                    logger.info("The solve was accepted — page %d is content "
                                "now.", page_num)
                else:
                    logger.warning("The solve was NOT accepted: page %d is "
                                   "still %s. The purchase is spent.",
                                   page_num, state)

        if not page_flow.should_retry(state):
            # "content" and "empty" are both final answers. An empty page is
            # a CORRECT one — a payload with no records — so retrying it
            # would re-confirm the same right answer, and rotating the exit
            # would blame an address for the URL it was given.
            break

        # Blocked or challenged. The ADDRESS is what was scored, not the URL,
        # so a different exit is the only thing that plausibly changes the
        # outcome.
        if block_attempt < block_retries:
            if state == page_flow.THROTTLED and has_pool:
                # Throttling is about time as well as the address: pause
                # (growing per attempt) before the next exit, too.
                time.sleep(page_flow.throttle_pause(args.retry_delay, block_attempt))
            if has_pool:
                logger.warning("Page %d came back as %s from %s — retrying "
                               "from another exit (%d/%d).", page_num, state,
                               mask(pool.current), block_attempt + 1,
                               block_retries)
                pool.advance(f"{state} on page {page_num}")
                session.relaunch()
                d = _driver(session)
            else:
                # No pool, so nowhere else to go — but a plain re-fetch is
                # what clears this on a Scraping Browser profile. The browser
                # is NOT relaunched: over `--cdp-endpoint` a profile allows
                # one live connection, so tearing the session down and
                # reconnecting risks `profile_locked`. Mirrors the Playwright
                # engine, whose branch this was missing: with no `--proxy`
                # the line above dereferenced `pool.current` on None and the
                # run died with AttributeError — on any retryable page state,
                # which no live run had reached until a page was unreadable.
                pause = (page_flow.throttle_pause(args.retry_delay, block_attempt)
                         if state == page_flow.THROTTLED
                         else args.retry_delay * (block_attempt + 1))
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
    outcome.server_error = page_flow.target_server_error(state, http_status)
    if outcome.server_error is not None:
        logger.error("Page %d: Mercor answered HTTP %d (an error status) on every "
                     "attempt. Nothing was obtained from it, so this page is "
                     "FAILED, not empty.", page_num, outcome.server_error)
        outcome.final_url = d["current_url"]()
        return outcome

    if state == page_flow.THROTTLED:
        # HTTP 429 on every attempt, after growing pauses. A refusal for
        # now, not an answer about the page: exit 3, or 6 after rows.
        logger.error("Page %d: Mercor answered HTTP 429 (too many requests) "
                     "on every attempt (%d). Nothing was obtained from it; "
                     "this is exit 3, or 6 after earlier rows, NOT an empty "
                     "result. Wait, raise --delay, or use another exit.",
                     page_num, block_retries + 1)
        outcome.blocked_by = page_flow.THROTTLED
        outcome.final_url = d["current_url"]()
        return outcome

    if state == "blocked":
        # Mercor has never refused this scraper — see
        # playwright_scraper's twin of this block. This is the HARD refusal:
        # no widget, no sitekey, nothing a key could buy.
        debug_html = f"{args.out}_page{page_num}_debug.html"
        with open(debug_html, "w", encoding="utf-8") as f:
            f.write(html or "")
        logger.error(
            "Mercor did not serve this request — %d bytes, its own asset "
            "paths referenced %d time(s), saved to %s. This is NEW: on "
            "2026-09-18 this site served every route to a bare "
            "datacentre address with no challenge of any kind, so there "
            "is no measured remedy to recommend — the saved HTML is the "
            "evidence for what changed. This is exit 3, distinct from an "
            "empty result (exit 4).",
            len(html or ""), references_own_assets(html or ""), debug_html)
        outcome.blocked_by = "refused" if html else "no-response"
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
    # a correct answer, and a sibling repo once reported exit 3 on a page its
    # site had plainly served because the site's own performance script
    # named its CDN. Mirrors playwright_scraper exactly.
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
        # Recorded on every page so all three engines carry one shape; on
        # recorded every time and page 1's copy is what the run plans against.
        outcome.total_available = listing.total_jobs
        outcome.total_companies = listing.total_companies
        outcome.pages_available = listing.pages_available
        outcome.urls_in_itemlist = listing.urls_in_itemlist
        outcome.echoed_page = listing.echoed_page
        if page_num == 1:
            # Mercor states no catalogue total on any route, so what is
            # reported is this response's own two views of itself. Printing
            # a line of Nones about totals the site does not publish would
            # read like a parse failure on a page that parsed perfectly.
            logger.info("This response held %d listing(s); its own ItemList "
                        "JSON-LD indexes %d.", listing.records_in_payload,
                        listing.urls_in_itemlist)
        if listing.page_repeated:
            # The site clamped an out-of-range page back and answered 200.
            logger.info("Asked for page %s and Mercor answered with page "
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
        paid = sum(1 for row in products if row.rate_min is not None)
        remote = sum(1 for row in products
                     if (row.work_arrangement or "").lower() == "remote")
        described = sum(1 for row in products if row.description)
        named = sum(1 for row in products if row.company_name)
        # All reported, none floored. `company_name` is the one that would
        # tempt a floor and must not have one: 291 of 390 listings withhold
        # the client's name on purpose, and `company_brand_visible` says so
        # per row. A floor there would fire on healthy data every run.
        if args.mode == "job":
            row = products[0]
            pay = ("not stated" if row.rate_min is None else
                   "%g-%g %s %s" % (row.rate_min, row.rate_max or row.rate_min,
                                    row.rate_currency or "(currency not "
                                    "published)", row.rate_period or ""))
            logger.info("Job: %s at %s, pay %s.", row.title,
                        row.company_name or "an unnamed client", pay.strip())
        else:
            logger.info("Page %d: %d/%d state pay, %d/%d remote, %d/%d carry "
                        "a description, %d/%d name a company (the rest are "
                        "withheld clients, not missing data).",
                        page_num, paid, len(products), remote, len(products),
                        described, len(products), named, len(products))

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
    outcomes: List[PageOutcome] = []
    seen_keys = set()
    blocked = False
    # All three modes are one row per listing (or careers opening), so `sku`
    # is the key for all of them.
    dedupe_key = "sku"
    # `/explore` and `/careers` each hold their whole result set in one
    # response — measured, not assumed: every pagination parameter tried on
    # `/explore` returned a byte-identical payload on 2026-09-18. --mode job
    # is the paginated mode, and its pages are enumerated job URLs.
    stop_reason = ("single_page_route" if args.mode in ("listings", "careers")
                   else "completed")

    # How many jobs --mode job found to fetch. Bound here rather than inside
    # the session block, so the reporting path cannot raise UnboundLocalError
    # on a run that had already done all its work.
    total_enumerated = 0
    # How whole the enumeration was, or None when this mode enumerates
    # nothing; bound here so the reporting path cannot raise on it.
    enumeration = None

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

        # In --mode job the enumeration comes FIRST, because it is what
        # decides which address page 1 even is. Everywhere else page 1's own
        # content decides how many pages there are, so the order reverses.
        job_urls = []
        if args.mode == "job" and not _is_single_job_url(args):
            enumeration = _enumerate_jobs(
                lambda u: _fetch_page_source(session, u), args)
            job_urls = enumeration.urls
            if not job_urls:
                return finish_run(
                    [], args.out, args.format, args.allow_empty,
                    blocked=False, stop_reason="enumeration_empty",
                    pages_requested=args.pages, pages_completed=0,
                    mode=args.mode, source=SOURCE_DEFAULT,
                    start_url=args.url or "", final_url="")
            total_enumerated = len(job_urls)
            target = job_urls[0]

        if target != args.url:
            logger.info("Fetching %s", target)

        first = _fetch_one_page(session, args, pool, 1, target)
        outcomes.append(first)

        if not first.ok:
            stop_reason = page_flow.failure_stop_reason(first)
            blocked = first.blocked_by is not None
        elif args.mode == "job" and not job_urls:
            pass  # `--url` named one job; one page is the whole run
        else:
            seen_keys.update(p.sku for p in first.products if p.sku is not None)

            # Planned through the SHARED helper, so all three engines decide
            # this identically: one page for a route that has one, and one
            # page per enumerated job in --mode job.
            page_one = first.final_url or target
            planned = _plan_page_urls(args, page_one, first.pages_available,
                                      job_urls=job_urls)
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
                    stop_reason = page_flow.failure_stop_reason(outcome)
                    blocked = outcome.blocked_by is not None
                    break

                fresh_count = sum(1 for p in outcome.products
                                  if p.sku is None or p.sku not in seen_keys)
                seen_keys.update(p.sku for p in outcome.products
                                 if p.sku is not None)
                if (not fresh_count
                        and page_flow.a_page_without_rows_ends_the_run(args.mode)):
                    logger.info("Page %d added no rows not already seen — "
                                "treating that as the end of the listing.",
                                page_num)
                    stop_reason = "no_new_products"
                    break
                if not fresh_count:
                    # --mode job: every page is an independent address, so
                    # one adding nothing (a withdrawn listing, a duplicate)
                    # says nothing about the next.
                    logger.info("Page %d (%s) added no rows (%s) — continuing "
                                "with the rest of the queue.", page_num,
                                outcome.url, outcome.state or "empty")

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

    if args.domain:
        # A CLIENT-SIDE filter, applied after the merge and never presented
        # as anything else: Mercor's index accepts no query parameters, so
        # this cannot reduce what is downloaded and the log says so.
        wanted = args.domain.strip().lower()
        before = len(all_rows)
        all_rows = [r for r in all_rows
                    if (getattr(r, "domain", None) or "").strip().lower() == wanted]
        logger.info("--domain %r kept %d of %d row(s). This filtered rows "
                    "that were already fetched.", args.domain,
                    len(all_rows), before)

    # Completeness, checked over the MERGED result rather than per page — a
    # per-page check cannot see a gap BETWEEN two pages, which is exactly
    # where a short page hides.
    #
    # NOT "pages x rows-per-page" as a hard expectation, and on this site
    # page size is fixed at 15: the LAST page of a listing is legitimately
    # short. Mirrors playwright_scraper.
    total_available = next((o.total_available for o in outcomes
                            if o.total_available is not None), None)
    pages_available = next((o.pages_available for o in outcomes
                            if o.pages_available is not None), None)
    if args.mode == "listings" and all_rows:
        logger.info(page_flow.LISTINGS_NOT_EXHAUSTIVE_NOTE)

    ok_pages, failed_pages, unreadable_pages = page_flow.account_for_pages(
        outcomes)
    final_url = (max(ok_pages, key=lambda o: o.page_num).final_url
                 if ok_pages else args.url)

    # One-per-run context, in the sidecar rather than repeated down a column,
    # and byte-identical in shape to the other two engines. Mercor states no
    # catalogue total on any route, so what goes here is this run's OWN
    # coverage arithmetic — which is what a bare "complete" hides.
    indexed = next((o.urls_in_itemlist for o in outcomes
                    if o.urls_in_itemlist is not None), None)
    extra = {"route_is_paginated": args.mode == "job", "mode": args.mode}
    if unreadable_pages:
        # Pages the site served and this parser could not read — by number,
        # so the loss is a list a reader can act on rather than a count.
        extra["pages_unreadable"] = unreadable_pages
    http_errors = page_flow.target_http_errors(outcomes)
    if http_errors:
        # Pages the TARGET answered with a server error, and its status:
        # failed pages, recorded with the status so a 503 is not mistaken
        # for a dead proxy or an empty index.
        extra["pages_target_http_error"] = http_errors
    if args.mode == "listings":
        extra["records_in_payload"] = total_available
        extra["urls_in_itemlist"] = indexed
        extra["pages_available"] = pages_available
    elif args.mode == "job":
        extra["jobs_enumerated"] = total_enumerated or None
        if enumeration is not None:
            extra.update(enumeration.as_sidecar())
        extra["jobs_fetched"] = len(ok_pages)
        # Addresses the site answered "gone" for. A withdrawn listing is an
        # ordinary event here (the enumeration is built before any address
        # is fetched), so it does not make the run partial — but it is
        # recorded BY ADDRESS, because "complete" with fewer rows than
        # `jobs_fetched` would otherwise read as rows lost without a trace.
        gone = [o.url for o in sorted(outcomes, key=lambda o: o.page_num)
                if o.ok and o.state == "not_found"]
        extra["jobs_not_found"] = len(gone)
        if gone:
            extra["urls_not_found"] = gone
    if args.domain:
        extra["domain_filter"] = args.domain

    # A run that fetched every address it was GIVEN is still short when the
    # list it was given was a fallback — see page_flow.reconcile_stop_reason.
    stop_reason = page_flow.reconcile_stop_reason(
        stop_reason, None if enumeration is None else enumeration.complete,
        unreadable_pages)
    return finish_run(all_rows, args.out, args.format, args.allow_empty,
                      blocked=blocked, stop_reason=stop_reason,
                      pages_requested=args.pages, pages_completed=len(ok_pages),
                      pages_failed=failed_pages, mode=args.mode,
                      source=SOURCE_DEFAULT,
                      start_url=args.url, final_url=final_url,
                      extra=extra)


def parse_args():
    p = argparse.ArgumentParser(
        description="Mercor job scraper (Selenium edition). "
                    "Cannot authenticate a proxy or a remote CDP endpoint — "
                    "see the module docstring; playwright_scraper.py is the "
                    "primary engine.")
    p.add_argument("--url", default=None,
                   help="A mercor.com URL: the marketplace index "
                        "(https://work.mercor.com/explore), one listing "
                        "(https://work.mercor.com/jobs/list_.../slug) with "
                        "--mode job, or Mercor's own openings "
                        "(https://www.mercor.com/careers) with --mode "
                        "careers. OPTIONAL — every mode has a correct "
                        "default. Also read from MERCOR_URL in the "
                        "environment or .env.")
    p.add_argument("--domain", default=None, metavar="NAME",
                   help="Keep only listings whose `domain` matches, case "
                        "insensitively. Filters rows AFTER they are fetched "
                        "and is honest about it: Mercor's index accepts no "
                        "query parameters, so nothing here reduces what is "
                        "downloaded. --mode listings and --mode job only.")
    p.add_argument("--mode", choices=list(MODES), default=DEFAULT_MODE,
                   help=page_flow.MODE_HELP)
    p.add_argument("--category", default=None,
                   help="Label to tag the run with in the sidecar. Defaults "
                        "to what the run selects. Mercor's routes carry no "
                        "category segment, so this names the RUN, not a site "
                        "concept — the site's own category is the `domain` "
                        "column.")
    p.add_argument("--pages", type=int, default=1,
                   help="Pages to fetch. Only --mode job paginates, and "
                        "there a page is one job, planned from the sitemap "
                        "and index enumeration and capped by its length. "
                        "--mode listings and --mode careers have one page "
                        "each and ignore a larger value with a log line.")
    p.add_argument("--delay", type=float, default=2.0, help="Delay between pages, seconds")
    p.add_argument("--concurrency", type=int, default=1, metavar="N",
                   help="Accepted for flag parity and IGNORED here: parallel "
                        "page fetching lives in playwright_scraper.py.")
    p.add_argument("--retries", type=int, default=3,
                   help="Attempts per page load before giving up (default 3). "
                        "A page that comes back EMPTY is not retried: an index "
                        "or careers payload with no records is a correct "
                        "answer, not a fault.")
    p.add_argument("--retry-delay", type=float, default=2.0,
                   help="Seconds before the first retry, doubling thereafter")
    p.add_argument("--format", choices=["json", "csv", "both"], default="both")
    p.add_argument("--out", default="mercor_jobs", help="Output file prefix")
    p.add_argument("--locale", default="en-US",
                   help=page_flow.LOCALE_HELP + " Passed to Chrome as --lang.")
    p.add_argument("--proxy", default=None,
                   help="Proxy URL. NOTE: Selenium cannot authenticate a "
                        "proxy; credentials are stripped and a warning says "
                        "so. Use the Playwright or pyppeteer engine for an "
                        "authenticated exit.")
    p.add_argument("--proxy-file", default=None,
                   help="File with one proxy URL per line to rotate across. "
                        "Wins over --proxy.")
    p.add_argument("--proxy-rotate", choices=list(ROTATE_MODES), default="per-run")
    p.add_argument("--proxy-shuffle", action="store_true")
    p.add_argument("--proxy-block-retries", type=int, default=2)
    p.add_argument("--twocaptcha-key", default=None, help="2captcha.com API key")
    p.add_argument("--allow-empty", action="store_true",
                   help="Write output files even when 0 rows were found.")
    p.add_argument("--fingerprint", action="store_true",
                   help="Fetch a fingerprint from 2captcha's Fingerprint API "
                        "and apply it over CDP. Needs --twocaptcha-key. "
                        "Ignored with --cdp-endpoint.")
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
                        "your proxy's exit country.")
    p.add_argument("--captcha-api", choices=["v2", "v1"], default="v2")
    p.add_argument("--solve-captcha", choices=["when-blocked", "always"],
                   default="when-blocked",
                   help=page_flow.SOLVE_CAPTCHA_HELP)
    p.add_argument("--min-score", type=float, default=0.7)
    p.add_argument("--cdp-endpoint", default=None,
                   help="Attach to a running browser at host:port. Must NOT "
                        "carry credentials — chromedriver's debuggerAddress "
                        "cannot send them, so a credentialed endpoint is "
                        "refused with exit 2 rather than silently failing.")
    p.add_argument("--dump-html", default=None, metavar="PATH",
                   help="Save the exact HTML the parser is given, on success "
                        "as well as failure.")
    p.add_argument("--headless", action="store_true", default=True)
    p.add_argument("--headful", dest="headless", action="store_false")
    args = p.parse_args()
    # Whether --url was TYPED, captured before the environment fills it: a
    # MERCOR_URL from .env is a default, not a request.
    typed_url = args.url
    env_config.apply(args)
    bad_number = page_flow.numeric_flag_error(args)
    if bad_number:
        p.error(bad_number)

    if args.retries < 1:
        p.error(page_flow.RETRIES_MUST_BE_POSITIVE)

    # Spelled identically to the other two engines.
    #
    # Every mode has a correct default URL, so there is nothing to refuse
    # about a missing one and no pair of flags that could disagree: Mercor's
    # index accepts no parameters, so there is no --role/--location
    # equivalent that could contradict a path.
    if args.url:
        ok, why = is_supported_url(args.url)
        if not ok:
            p.error(why)
        implied = mode_for_url(args.url)
        if implied and implied != args.mode and not typed_url:
            # From the environment and naming another route: --mode wins and
            # that mode's own default address is used.
            print("[i] MERCOR_URL (%s) is read by --mode %s; ignoring it for "
                  "--mode %s and using that mode's default address."
                  % (args.url, implied, args.mode), file=sys.stderr)
            args.url = None
        elif implied and implied != args.mode:
            # Refused rather than silently corrected: reading a careers URL
            # under --mode listings would parse it with the wrong reader and
            # report zero rows for a perfectly good page.
            p.error("--url is a %s URL but --mode is %s. %s is read by "
                    "--mode %s; pass that, or drop --url and let --mode %s "
                    "use its own default."
                    % (implied, args.mode, args.url, implied, args.mode))

    if args.domain and args.mode == "careers":
        p.error("--domain filters the marketplace's `domain` column, which "
                "the careers route does not publish — its roles carry a "
                "`department` instead. Drop --domain, or use --mode "
                "listings.")

    if args.mode in ("listings", "careers") and args.pages != 1:
        # Said out loud rather than silently ignored. Measured, not assumed:
        # every pagination parameter tried on /explore returned a
        # byte-identical payload on 2026-09-18.
        logger.warning(page_flow.PAGES_IGNORED_WARNING, args.pages, args.mode)
        args.pages = 1

    if args.category is None:
        args.category = (category_from_url(args.url) if args.url
                         else args.mode)
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
