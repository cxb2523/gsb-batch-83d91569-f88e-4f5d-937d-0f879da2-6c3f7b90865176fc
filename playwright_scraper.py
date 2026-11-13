"""
wellfound-scraper — Playwright edition (primary engine)

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
    python3 playwright_scraper.py --url "https://wellfound.com/role/r/software-engineer" --pages 3
    python3 playwright_scraper.py --role software-engineer --location new-york --pages 2
    python3 playwright_scraper.py --mode jobs --url "https://wellfound.com/jobs"
    python3 playwright_scraper.py --mode job --url "https://wellfound.com/jobs/4697947-senior-software-engineer"

A datacenter address gets nothing from this site. Use a residential
`--proxy`, or `--cdp-endpoint` for the 2Captcha Scraping Browser.
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
from urllib.parse import urlparse, urljoin

from playwright.sync_api import (sync_playwright, Error as PWError,
                                 TimeoutError as PWTimeout)

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
from proxy_pool import (from_args as proxy_pool_from_args, to_playwright, mask,
                        ROTATE_MODES, ProxyError, ProxyPool)
import env_config
import proxy_check
import proxy_meter

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
    # The page_flow state this page came back as ("content", "empty",
    # "blocked", "parse_error", "not_found", "unknown"). Carried so the
    # caller can tell an EMPTY page — a landing page that matched nothing —
    # from a page that failed. Both produce zero rows and
    # they mean opposite things.
    state: Optional[str] = None
    # What Wellfound itself said the result set was: `totalJobCount`,
    # `totalStartupCount` and `pageCount`, verbatim. These are REAL numbers
    # rather than a header to be distrusted — they are the site's own
    # arithmetic and they are what pages are planned from.
    #
    # `total_available` holds the JOB count, because the rows are jobs.
    # `pages_available` counts pages of COMPANIES, twenty per page, which is
    # not the same denominator — see output_writer's `run_meta` docstring.
    total_available: Optional[int] = None
    total_companies: Optional[int] = None
    pages_available: Optional[int] = None
    # The page number the SERVER answered with, read back out of the Apollo
    # cache key. Not an echo of the request: asking for page 48 of a 47-page
    # listing comes back stating page 1, which is how a run learns it has
    # walked off the end instead of silently re-collecting page 1.
    echoed_page: Optional[int] = None

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


ITEM_LINK_SELECTOR = page_flow.READY_SELECTOR_LISTING

# The share of rows that must carry the columns Wellfound fills on every
# record, below which the read has broken rather than the data being
# unusual.
#
# There is no price on this site, so there is no price coverage. What stands
# in its place is the handful of fields that were populated on 203 of 203
# job records across five landing captures and the /jobs feed on 2026-09-17
# — the title, the job URL, the id, the company name and the company id.
#
# Deliberately NOT in this check, with the measurement that keeps them out:
#   compensation           258 of 312 — a listing may state no pay at all
#   description              0 on every /jobs-feed row — the feed's thinner
#                            type does not carry one
#   years_experience_min   109 of 432
#   remote_kind            201 of 432
# A floor on any of those would fire on healthy data.
CORE_FIELD_FLOOR = 99
CORE_FIELDS = ("title", "url", "sku", "company_name", "company_id")

# ...and the set for --mode job, which is SHORTER on purpose rather than by
# omission. A job page's schema.org block names the hiring organisation but
# publishes no id for it, so `company_id` is legitimately null on every
# detail row — measured on the first live run of this engine, which warned
# "0% of page 1 carries company_id" about a perfectly good parse. Checking
# one source's fields against another source's floor is how a correct run
# gets told it is broken.
CORE_FIELDS_JOB = ("title", "url", "sku", "company_name")


def _core_fields(mode: str):
    return CORE_FIELDS_JOB if mode == "job" else CORE_FIELDS

# A landing page holding less than this share of the rows a full page
# carries is reported as thin.
#
# Set LOW on purpose, and the reason is the site's own arithmetic: a landing
# page paginates over COMPANIES — twenty per page — while the rows are JOBS,
# and how many jobs twenty companies have is not fixed. Measured across the
# captures: 32, 37, 43, 45 and 5 rows per page, the 5 being the last page of
# a 47-page listing. A share computed against `page_size` would call a
# perfectly normal page thin, so this is compared against the ROW count of
# page 1 rather than against the site's page size.
THIN_PAGE_SHARE = 0.35


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
    # than forgotten: Wellfound serialises its whole result set into
    # `__NEXT_DATA__` in the first response. Every job record a landing page
    # holds — 37, 43, 45 and 32 on four captures — is in the document before
    # any scrolling could happen, so a scroll would be ceremony that looks
    # load-bearing.
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


def _classify(page, html: str, status=None, mode: str = "role") -> str:
    """`mode` is threaded through because the two page kinds are read by
    different mechanisms: a job page has no `__NEXT_DATA__` at all, so
    classifying one as a listing would call a perfectly good page a
    parse_error."""
    return page_flow.classify(html, status, page.url, mode)

# Every readiness constant and every state policy lives in page_flow.py, with
# its measurement beside it. Nothing about WHAT to do with a page is
# duplicated here — this file only knows HOW to ask Playwright.


def _fetch_text(session, url: str, timeout_ms: int = 60000) -> str:
    """Navigate and return the document's text. Used for the endpoint.

    `innerText` rather than `content()`: the endpoint answers with JSON, and
    Chromium wraps a JSON document in its own viewer markup. Reading the body
    text gives back exactly what the server sent.
    """
    proxy_meter.check(session.args)
    session.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    return _snapshot(session.page, url) or ""


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


def _plan_page_urls(args, page_one_url: str,
                    pages_available: Optional[int]) -> List[str]:
    """URLs for pages 2..N, decided once from what page 1 reported.

    On most sites in this family this function has to hedge: it compares the
    site's own next-link against what the URL convention would build, and
    falls back to chaining link-to-link when the two disagree, because a
    constructed URL the site does not honour produces a complete-looking run
    holding page 1.

    Wellfound needs no hedging on the landing routes and the reason is
    better than a selector: **every landing response states its own
    `pageCount`**. The end of the listing is a number the site hands over on
    page 1, not something discovered by walking off it.

    Walking off it is the thing to avoid here. `?page=48` of a 47-page
    listing does not error and does not empty — it answers HTTP 200 with
    page 1's rows again. So the plan is CAPPED by the site's own figure, and
    `parse_listing_page` reads back which page the server actually used as a
    second line of defence.

    That the convention works at all was verified rather than assumed:
    `?page=2` on /role/r/software-engineer returned 45 job rows sharing
    exactly one id with page 1's 37.
    """
    if not page_flow.pagination_is_addressable(page_one_url):
        # The /jobs feed. `?page=2` on it returns the identical 46 ids as
        # page 1, so planning any page URL at all would manufacture
        # duplicates and report a complete multi-page run holding one page
        # several times.
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
    # Records the arguments Cloudflare passes to `turnstile.render()`.
    #
    # This has to be installed HERE, on the context, and not on a page after
    # navigation: Cloudflare calls `turnstile.render(container, params)` once
    # and keeps nothing, so `sitekey`, `action`, `cData` and `chlPageData`
    # exist only inside that call. A static read of a challenge page — any
    # static read, however careful — cannot produce a solvable task.
    # It costs nothing on a page that never renders one.
    context.add_init_script(TURNSTILE_INTERCEPT_JS)
    if proxy_check.block_media(args, pool, remote=False):
        proxy_check.install_playwright(context)
    # After the media route, so the budget route runs first (Playwright
    # runs routes in reverse order of registration).
    proxy_meter.install_playwright(context, proxy_meter.of(args))
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
    # What it covers here is Cloudflare's managed challenge, which is what
    # Wellfound answers a scored address with. That challenge publishes no
    # sitekey in its markup — Cloudflare calls `turnstile.render` once and
    # keeps nothing — so the LOCAL path needs the init-script hook that
    # records those arguments (see `handle_captcha_if_present`), while this
    # remote path is handled inside the browser and needs none of it.
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
    it. Wellfound does not geo-redirect — the site is one host in one
    language and the exit country changes nothing about the markup — but
    `www.wellfound.com` redirects to the bare host and a challenge page
    replaces itself when it clears, so a snapshot taken right after goto()
    can land exactly on a swap.

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
    """Whether this address answers with raw JSON rather than a document.

    Always False on Wellfound: unlike the sibling repo this engine was
    ported from, there is no ungated JSON endpoint here — every route is an
    HTML page with its payload serialised inside it. The function is kept
    because `_snapshot` branches on it and a sibling engine's twin must
    branch the same way; removing it would make the three engines' snapshot
    paths differ for no reason.
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


def handle_captcha_if_present(page, args) -> bool:
    """Detect and solve a challenge. True if something was solved.

    Runs after EVERY navigation, for ANY page — not scoped to one URL. The
    static-HTML and runtime reCAPTCHA detectors are run and reconciled
    against each other rather than short-circuited, because they can disagree
    about the variant and the parameters for one are rejected for the other.

    WHAT THIS SITE ACTUALLY PUTS IN FRONT OF A RUN, measured 2026-09-17,
    because a sentence about what a solver
    can do is the most expensive thing this family can get wrong:

    * Cloudflare's **managed challenge**, which every route answers with
      from a datacenter address. It arrives in two skins — a branded
      "Security Check | Wellfound" 403 for a plain HTTP client, and the
      "Just a moment..." interstitial for a real browser — and NEITHER
      publishes a sitekey, because Cloudflare calls `turnstile.render()`
      once and keeps nothing. 2Captcha solves this with
      `TurnstileTaskProxyless`, but the task needs `sitekey`, `action`,
      `cData` and `chlPageData`, and the only way to get them is to hook
      `turnstile.render` before any page script runs. That hook is
      `TURNSTILE_INTERCEPT_JS`, installed on the context below.

    * The site's **own** Turnstile, which is a different thing and is
      configured on every good page: Wellfound publishes
      `CLOUDFLARE_TURNSTILE_SITE_KEY` in its page config and renders a
      widget into `#turnstile_widget` when one of its own XHRs is
      challenged. That one IS solvable from a static read, because its
      sitekey is published. It has not been observed firing on a listing
      fetch; `site_turnstile_sitekey()` exists so that if it ever does, the
      key is read from the page rather than guessed.

    Neither is "unsolvable" — that word belongs to a PAGE with no widget on
    it, not to a vendor. What is true is narrower and is what the README
    says: on the routes this scraper reads, a residential exit removes the
    challenge entirely, so most runs never reach this code.
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
        # No reCAPTCHA. Turnstile is the other thing 2captcha solves, and on
        # this site it is the LIKELY one — Cloudflare is what stands in front
        # of a scored address here. The RUNTIME reading is the one that
        # matters: a Cloudflare challenge page publishes no sitekey in its
        # markup, so only the interception installed at context creation can
        # produce a solvable challenge. The static read is the fallback for
        # the site's OWN widget, whose sitekey IS published.
        # The RUNTIME reading is unconditional: it only returns something
        # when Cloudflare actually called `turnstile.render`, which happens
        # on a challenge page and nowhere else.
        challenge = wait_for_turnstile(lambda js: page.evaluate(js),
                                       lambda s: page.wait_for_timeout(s * 1000),
                                       page_url=page.url)
        # The STATIC reading is gated on the content not being there, and
        # that gate is not caution — it is required on this site. Wellfound
        # loads `challenges.cloudflare.com/turnstile/v0/api.js` on EVERY page
        # it serves, so `detect_turnstile`'s markers match a perfectly good
        # listing every single time. Measured on the first live run of this
        # engine: "turnstile detected via html" on all three pages of a
        # successful 107-row scrape. Ungated, `--solve-captcha always` would
        # have bought three solves for three pages that were never blocked.
        #
        # A marker must be tested against good pages before it is trusted; this is
        # the same rule applied to the SOLVER's, which is a second marker set
        # in a second file and was not covered by it.
        if challenge is None and already_rendered <= MIN_CARD_MATCHES:
            challenge = detect_turnstile(html, page.url)
        if challenge and not challenge.sitekey:
            published = site_turnstile_sitekey(html)
            if published:
                # The site's own widget, which does publish its key. Better
                # than refusing: this is a solvable challenge that the
                # interception simply did not see render.
                challenge.sitekey = published
                logger.info("No sitekey was intercepted, but the page "
                            "publishes one in its own config — using it.")
            else:
                # Raising a task without a sitekey buys a rejected token and
                # an ERROR_CAPTCHA_UNSOLVABLE bill. Say so
                # instead.
                logger.warning(
                    "A Cloudflare Turnstile is on this page but no sitekey "
                    "was captured, so no task can be built and none will be "
                    "paid for. That means the widget rendered before this "
                    "run's interception script was installed — which should "
                    "not happen on a page this engine navigated to, and does "
                    "happen if the browser was attached to mid-flight.")
                return False
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
    try:
        token = solve_recaptcha(challenge, args.twocaptcha_key,
                               api_version=args.captcha_api,
                               min_score=args.min_score)
    except Exception as e:  # noqa: BLE001 — a solver failure is not a crash
        logger.error("Solving the challenge failed (%s) — continuing with "
                     "whatever the page holds.", e)
        return False

    if getattr(challenge, "is_turnstile", False):
        # Turnstile hands its token back through `cf-turnstile-response` and
        # the page's own callback, not through `g-recaptcha-response` and
        # grecaptcha's client registry.
        called_back = page.evaluate(TURNSTILE_INJECT_JS, token)
        logger.info("Turnstile token injected%s.",
                    " and handed to the page's callback" if called_back
                    else " (no callback was captured — relying on the form "
                         "field)")
        if getattr(challenge, "solved_user_agent", None):
            # Logged so it can be RULED OUT rather than guessed at. Measured
            # on a sibling site, a token minted under a mismatched UA was
            # accepted anyway — so this is evidence, not a known cause.
            logger.info("2captcha solved it against user agent %r. Cloudflare "
                        "checks that on a challenge page, so a mismatch here "
                        "is worth ruling out if a paid token is refused.",
                        challenge.solved_user_agent[:60] + "…")
    else:
        page.evaluate(INJECT_TOKEN_JS, token)
    logger.info("Token injected. Reloading page to continue.")
    page.wait_for_timeout(1500)
    page.reload(wait_until="domcontentloaded", timeout=60000)
    return True


def _parse_for_mode(html: str, url: str, args, page_num: int = 1):
    """(rows, listing) for this mode. `listing` is None in --mode job.

    `parse_detail` returns a single row or None; wrapping it here keeps
    every caller downstream — dedupe, merge, coverage logging, the writers —
    working on one shape instead of branching on the mode again.

    `page_num` is threaded through rather than defaulted, because `position`
    restarts at 1 on every page: without the page number beside it, a row
    from page 2 claims the same position as one from page 1 and the two are
    indistinguishable in the output. `smoke_test.py` asserts page+position
    is unique across a multi-page run for exactly that reason.
    """
    if args.mode == "job":
        row = parse_detail(html, url)
        return ([row] if row is not None else []), None
    listing = parse_listing_page(html, url=url, page=page_num)
    return listing.rows, listing


def _solve_budget(args, spent: int):
    """Whether another solve may be bought for this page, and the reason.

    `page_flow.SOLVES_PER_PAGE` says at most one purchase per page, and that
    is a MONEY limit rather than a style rule. It was not being enforced:
    `handle_captcha_if_present` is called twice per attempt — once before the
    page is classified, so a challenge is cleared before anything is judged,
    and once after, for the state that says the page really is gated — and
    only the SECOND call was counted.

    Measured 2026-09-17 on a run from a datacenter address, which meets a
    real Cloudflare challenge on every fetch: ONE page bought THREE Turnstile
    solves — two from the uncounted call across two block attempts, one from
    the counted one — and every token was refused. The cap read as enforced
    and was not (a policy constant nothing reads is the same
    defect as dead code).

    Both call sites now go through here.
    """
    return spent < page_flow.SOLVES_PER_PAGE


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
    solves_bought = 0
    html, state, load_failed = None, "ok", False

    for block_attempt in range(block_retries + 1):
        logger.info("Fetching page %d/%d: %s", page_num, args.pages, url)
        # Retry a navigation timeout rather than ending the run on it. One
        # network flap on page 12 of 50 should not break the loop.
        load_failed, exit_failed, status = False, None, None
        for attempt in range(1, args.retries + 1):
            proxy_meter.check(args)
            try:
                # The response is KEPT: its status is the classifier's
                # primary signal (a 403 refusal, a 404 for a job that is
                # gone). Discarding it made `not_found` unreachable, so a
                # removed job was waited on, retried and reported as content
                # never obtained.
                response = session.page.goto(url, wait_until="domcontentloaded",
                                             timeout=60000)
                status = getattr(response, "status", None)
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

        # Counted, because it can BUY. See _solve_budget.
        if _solve_budget(args, solves_bought):
            solves_bought += 1
            if handle_captcha_if_present(session.page, args):
                # A solve navigated the page. Give the destination a moment
                # before judging what came back, and judge it by its body:
                # the first navigation's status no longer describes it.
                session.page.wait_for_timeout(1000)
                status = None
        elif solves_bought:
            logger.info("Not solving again on page %d: %d purchase(s) already "
                        "made for it and SOLVES_PER_PAGE is %d. A challenge "
                        "that survives a paid token is not one this run can "
                        "pass.", page_num, solves_bought,
                        page_flow.SOLVES_PER_PAGE)

        html = _snapshot(session.page, url) or ""
        state = _classify(session.page, html, status, mode=args.mode)

        # Wellfound server-renders its payload into `__NEXT_DATA__`, so a
        # listing is parseable in the FIRST response and there is nothing to
        # wait for on a healthy page. Measured 2026-09-17 with no pause at
        # all after `wait_until="domcontentloaded"`: /role/r/software-engineer
        # gave 37 rows and `pageCount: 47`, and a job page parsed in full.
        # That is why this engine has no scroll step and no readiness pause
        # on the happy path — either would be ceremony that looks
        # load-bearing.
        #
        # The wait below is therefore only for the state that says Wellfound
        # served SOMETHING that is not the payload. That is the one case
        # where waiting can still help, and it is bounded.
        if state == "unknown":
            wait_timeout = page_flow.content_timeout_ms(args.mode)
            logger.info("Page %d is something Wellfound served (%d bytes, "
                        "its own assets referenced %d time(s)) but carries no "
                        "listing payload — waiting up to %.0fs rather than "
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
            # No status here: the document may have changed during the wait
            # (a challenge that clears itself navigates), so the navigation's
            # status no longer describes it and the body decides.
            state = _classify(session.page, html, None, mode=args.mode)

        # The paid path is reached only for a state the policy marks solvable
        # ("blocked" here) — Cloudflare's managed challenge IS a test and can
        # be solved once `TURNSTILE_INTERCEPT_JS` has captured its parameters,
        # while the widget-less branded refusal has nothing to solve. It is bounded
        # by SOLVES_PER_PAGE so a rotation loop cannot become a bill, and a
        # sitekey-less detection refuses to build a task at all rather than
        # paying for one the API will reject.
        if (page_flow.should_solve(state)
                and _solve_budget(args, solves_bought)):
            solves_bought += 1
            if handle_captcha_if_present(session.page, args):
                session.page.wait_for_timeout(1000)
                html = _snapshot(session.page, url) or html
                # The solve reloaded the page; the original status is stale.
                state = _classify(session.page, html, None, mode=args.mode)
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
            # a CORRECT one — a landing page that matched nothing, and one page past
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
        # What a caller needs here is WHICH refusal this is, because the two
        # want different answers and only one of them is solvable.
        #
        #   "Security Check | Wellfound"           — a refusal. No widget,
        #       no sitekey, nothing to solve. A different exit is the only
        #       move.
        #   "Just a moment..." with `_cf_chl_opt`  — a test. It is the same
        #       "blocked" state, but it carries a widget, so the solve path
        #       above may have tried it once.
        #
        # Both refusals are HTTP 403 and the branded one wears Wellfound's
        # own name four times, so a reader who only sees "403" cannot tell
        # them apart from a real page. Saying which one arrived, and what is
        # measured to clear it, is more use than a captcha hint.
        debug_html = f"{args.out}_page{page_num}_debug.html"
        with open(debug_html, "w", encoding="utf-8") as f:
            f.write(html or "")
        assets = references_own_assets(html or "")
        logger.error(
            "Wellfound did not serve this request — %d bytes, its own asset "
            "hosts referenced %d time(s), saved to %s. This is Cloudflare, "
            "and what clears it is measured (2026-09-17): an exit Wellfound "
            "does not score as a datacenter. A Hetzner VPS in Helsinki was "
            "refused on EVERY route including robots.txt, by plain HTTP and "
            "by headless and headful Chromium alike; a residential US exit "
            "was served 200 on every route three times out of three. Use a "
            "residential --proxy, or --cdp-endpoint for the Scraping "
            "Browser. NOTE that /company/ pages stay 403 even from a "
            "residential exit — the gating is per route. This is exit 3, "
            "distinct from a genuinely empty result (exit 4).%s",
            len(html or ""), assets, debug_html,
            (f" Tried {block_retries + 1} exit(s)." if has_pool
             else f" Re-fetched {block_retries + 1} time(s)."))
        outcome.blocked_by = "cloudflare (hard block)" if html else "no-response"
        outcome.final_url = session.page.url
        return outcome

    # No readiness wait and no scroll on the content path, and their absence
    # is MEASURED rather than forgotten — see the "unknown" branch above.
    # Wellfound embeds the whole result set in the first response, so there
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
    # answer, and a sibling scraper reported exit 3 on a 191 KB page its
    # site had plainly served, because a performance script named a vendor
    # host that was in the marker list. Both halves were wrong; that marker
    # is gone (see
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
        outcome.final_url = session.page.url
        return outcome

    products, listing = _parse_for_mode(html, session.page.url, args, page_num)
    logger.info("Parsed %d row(s) from page %d.", len(products), page_num)

    if listing is not None:
        # Wellfound states its own arithmetic on EVERY page, not just the
        # first, so it is recorded every time and page 1's copy is what the
        # run plans against.
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
            # The /jobs feed carries no `Results` node at all, so there is no
            # arithmetic to report. Printing a line of Nones would read like
            # a parse failure on a page that parsed perfectly.
            logger.info("This listing publishes no result counts — %d row(s) "
                        "is what it served.", len(listing.rows))
        if listing.page_repeated:
            # The site clamped an out-of-range page back and answered 200.
            # Reported as a fact about the SITE rather than as a failure:
            # the rows are real, they are simply page 1's, and the caller
            # stops the run here instead of collecting them again.
            logger.info("Asked for page %s and Wellfound answered with page "
                        "%s — that is this site's way of saying the listing "
                        "has ended. Stopping rather than re-collecting page "
                        "%s.", listing.requested_page, listing.echoed_page,
                        listing.echoed_page)

    if products:
        # No price on this site, so no price coverage. What stands in its
        # place is the handful of fields Wellfound filled on 203 of 203 job
        # records across the 2026-09-17 captures — reported every time, so a
        # consumer gets the number rather than a threshold someone guessed.
        for field_name in _core_fields(args.mode):
            filled = sum(1 for row in products if getattr(row, field_name, None) not in (None, "", []))
            share = 100.0 * filled / len(products)
            if share < CORE_FIELD_FLOOR:
                logger.warning(
                    "Only %.0f%% of page %d carries `%s`, against a measured "
                    "floor of %d%%. Every record of every capture had one, "
                    "so this is the payload shape moving rather than the "
                    "listings being unusual — re-run with --dump-html.",
                    share, page_num, field_name, CORE_FIELD_FLOOR)
        paid = sum(1 for row in products if row.salary_min is not None)
        remote = sum(1 for row in products if row.remote)
        described = sum(1 for row in products if row.description)
        # All reported, none floored, and that is deliberate: 54 of 312
        # captured listings state no compensation at all, and the /jobs feed
        # publishes no description on any row. A floor on either would fire
        # on perfectly healthy data.
        if args.mode == "job":
            # One job has no page statistics, so the listing sentence would
            # be nonsense about a run of one row.
            logger.info("Job: %s at %s, pay %s.", products[0].title,
                        products[0].company_name or "an unnamed company",
                        products[0].compensation
                        or (f"{products[0].salary_min:.0f}-"
                            f"{products[0].salary_max:.0f} "
                            f"{products[0].salary_currency}"
                            if products[0].salary_min else "not stated"))
        else:
            logger.info("Page %d: %d/%d state pay, %d/%d remote, %d/%d carry "
                        "a description.", page_num, paid, len(products),
                        remote, len(products), described, len(products))

    if not products:
        debug_html = f"{args.out}_page{page_num}_debug.html"
        debug_png = f"{args.out}_page{page_num}_debug.png"
        with open(debug_html, "w", encoding="utf-8") as f:
            f.write(html)
        try:
            session.page.screenshot(path=debug_png, full_page=True)
        except Exception as e:
            logger.warning("Could not capture screenshot: %s", e)
        logger.warning("0 rows parsed — saved what the browser actually saw to "
                       "%s and %s. Open the .png to see it.", debug_html, debug_png)

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
    budget_spent = threading.Event()

    def worker(index: int):
        name = f"worker-{index + 1}"
        try:
            with sync_playwright() as pw:
                session = _BrowserSession(pw, args, _worker_pool(pool, index)).open()
                try:
                    first = True
                    while not (exhausted.is_set() or budget_spent.is_set()):
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
        except proxy_meter.ProxyBudgetExceeded as e:
            # One meter for every worker: the first to hit the cap stops
            # dispatch for all of them, and the rest stop at their next
            # navigation. scrape() names the stop reason.
            logger.error("[%s] stopping: %s.", name, e)
            budget_spent.set()
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
    # All three modes are one row per job posting, so `sku` (the job id) is the
    # key for all of them.
    dedupe_key = "sku"
    # Why the loop ended. "completed" means every requested page was fetched;
    # "no_new_products" means the listing itself ran out (also a complete
    # result). "single_page_mode" is complete by construction — a detail page
    # has no page 2. Anything else is an early stop, and the run is only a
    # partial view.
    # "page_cap_reached" is the one that is specific to this site: every
    # landing response states its own `pageCount`, so a run that fetched all
    # of them fetched everything there is. "page_echo_mismatch" is its
    # safety net — the site answers an out-of-range page with page 1 under
    # HTTP 200, and the response states which page it really used.
    #
    # --mode job is single-page by construction. --mode jobs is single-page
    # by MEASUREMENT: /jobs is served at one address and `?page=2` on it
    # returns the identical 46 job ids, so treating it as paginated would
    # report a complete multi-page run holding one page several times.
    stop_reason = ("single_page_mode" if args.mode == "job"
                   else "single_page_listing" if args.mode == "jobs"
                   else "completed")

    pool = proxy_pool_from_args(args)
    if pool and args.cdp_endpoint:
        logger.warning("Ignoring --proxy/--proxy-file: with --cdp-endpoint the "
                       "remote browser has its own exit, and layering a second "
                       "proxy on top would contradict it.")
        pool = None

    concurrency = max(1, args.concurrency)
    if concurrency > 1:
        if args.mode in ("job", "jobs"):
            logger.info("--concurrency is ignored in --mode %s: there is one "
                        "page to fetch.", args.mode)
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
                           "Wellfound answers a scored address with "
                           "Cloudflare on EVERY route including robots.txt, "
                           "so an address that works is one worth not "
                           "burning. Pass --proxy-file to spread the load.",
                           concurrency)
        if pool and pool.rotates_per_page():
            logger.info("--proxy-rotate per-page is redundant under "
                        "--concurrency: each worker already holds its own exit "
                        "for its lifetime, which is the same spread without a "
                        "browser relaunch per page.")
        if concurrency > 8:
            logger.warning("--concurrency %d means %d browsers at once "
                           "(~150-300MB each). Make sure the machine has the "
                           "memory for it.", concurrency, concurrency)

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

    with sync_playwright() as pw:
        session = _BrowserSession(pw, args, pool,
                                  remote=bool(args.cdp_endpoint)).open()
        try:
            target = _target_url(args)
            if target != args.url:
                logger.info("Fetching %s", target)

            # Page 1 is always fetched on its own: its content is what decides
            # how many pages 2..N there are to address at all.
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
                planned = _plan_page_urls(args, first.final_url,
                                          first.pages_available)
                if len(planned) + 1 < args.pages:
                    # Capped by the site's own `pageCount`, a complete
                    # answer rather than an early stop — see COMPLETE_STOP_REASONS.
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
                        stop_reason = page_flow.stop_reason_for(
                    worst.load_failed, worst.blocked_by, worst.state)
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
                            stop_reason = page_flow.stop_reason_for(
                    outcome.load_failed, outcome.blocked_by, outcome.state)
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
        except proxy_meter.ProxyBudgetExceeded as e:
            logger.error("Stopping: %s. The pages already gathered are kept.", e)
        finally:
            if session is not None:
                session.close()

    # Over budget is the stop reason whatever the loop concluded: the
    # requests after the cap were refused, so nothing after it was read.
    if meter is not None and meter.exceeded:
        stop_reason, blocked = proxy_meter.STOP_BUDGET_EXCEEDED, False

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
            # this page. Wellfound's pagination WAS measured repeating a
            # little — page 1 and page 2 of /role/r/software-engineer shared
            # exactly one job id, because the landing routes paginate over
            # COMPANIES and a company's jobs can straddle the boundary — so a
            # small non-zero count here is expected and a large one is not.
            logger.info("Page %d: dropped %d duplicate row(s).",
                        oc.page_num, len(oc.products) - len(fresh))
        all_rows.extend(fresh)

    # Completeness, checked over the MERGED result rather than per page — a
    # per-page check cannot see a gap BETWEEN two pages, which is exactly
    # where a short page hides.
    #
    # NOT "pages x rows-per-page" as a hard expectation, and on this site
    # that is not even available: a page holds twenty COMPANIES and however
    # many jobs those twenty have, measured at 32, 37, 43 and 45 across the
    # captures. The LAST page is legitimately short too. What is worth
    # warning about is a page that came back materially THIN against its
    # siblings, which is what a truncated response looks like.
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
                "(%d rows): %s. A landing page carries the jobs of twenty "
                "companies, which varies, so this is a soft signal — but a "
                "page under a third of its siblings that is not the last one "
                "is worth a look. Re-run with --dump-html.",
                ", ".join(str(p) for p, _ in thin), fullest,
                ", ".join("page %d: %d" % (p, n) for p, n in thin))
        if total_available:
            # The honest sentence, and the reason `totalJobCount` is worth
            # carrying: it is what the site says the whole listing holds,
            # against what this run actually fetched.
            logger.info("Wellfound reports %d job(s) for this listing; this "
                        "run holds %d (%.1f%%) across %d page(s) of the %s "
                        "the site offers.", total_available, len(all_rows),
                        100.0 * len(all_rows) / total_available,
                        len([o for o in outcomes if o.ok]), pages_available)

    ok_pages = [o for o in outcomes if o.ok]
    failed_pages = [o.page_num for o in outcomes if not o.ok]
    final_url = (max(ok_pages, key=lambda o: o.page_num).final_url
                 if ok_pages else args.url)

    # One-per-run context, in the sidecar rather than repeated down a column.
    #
    # For a listing run that is the site's own arithmetic — `total_jobs`,
    # `total_companies` and `pages_available`. Those describe the LISTING
    # rather than any job, so no column can carry them, and the first two
    # are what stop a reader dividing rows by pages and getting an answer
    # that is wrong for every page: Wellfound paginates over companies and
    # this file holds jobs.
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
        description="Wellfound (AngelList Talent) job scraper "
                    "(Playwright edition)")
    p.add_argument("--url", default=None,
                   help="A wellfound.com URL: a role landing page "
                        "(/role/{role}, /role/r/{role} or "
                        "/role/l/{role}/{location}), the /jobs feed, or a job "
                        "(/jobs/{id}-{slug}) with --mode job. Wellfound "
                        "serves one host in one language, so there is no "
                        "per-country hostname and no locale segment. Optional "
                        "for a landing page: --role and --location build the "
                        "URL instead. Also read from WELLFOUND_URL in the "
                        "environment or in .env.")
    p.add_argument("--role", default=None, metavar="SLUG",
                   help="A role slug as Wellfound spells it in its own URLs: "
                        "software-engineer, data-scientist, product-designer. "
                        "Builds a /role/… URL so a run needs no "
                        "hand-assembled address. Ignored when --url is given.")
    p.add_argument("--location", default=None, metavar="SLUG",
                   help="A location slug, as in /role/l/{role}/{location}: "
                        "san-francisco, new-york, london. Used with --role. "
                        "Ignored when --url is given.")
    p.add_argument("--remote", action="store_true",
                   help="With --role and no --location, build the REMOTE "
                        "landing page (/role/r/{role}) instead of the general "
                        "one (/role/{role}). They are different listings, not "
                        "a filter on one.")
    p.add_argument("--mode", choices=list(MODES), default=DEFAULT_MODE,
                   help="role (default): a /role/… landing page. The rich "
                        "one — full job descriptions, the company's badges, "
                        "size and tagline, and equity as well as salary; it "
                        "paginates. jobs: the /jobs discovery feed, which is "
                        "ONE page (`?page=2` on it returns the identical "
                        "rows) and whose records carry no description, no "
                        "job type and no badges. job: one /jobs/{id}-{slug} "
                        "page, read from its schema.org JobPosting, which "
                        "adds the stated salary PERIOD, the benefits text "
                        "and the industry. --pages applies to --mode role "
                        "only.")
    p.add_argument("--category", default=None,
                   help="Label to tag the run with in the sidecar. Defaults "
                        "to what the URL selects — 'role/software-engineer', "
                        "'role/data-scientist@new-york'. Wellfound has no "
                        "category tree, so this is a name for the QUERY "
                        "rather than a site concept; it exists so two runs of "
                        "different roles are not mistaken for comparable.")
    p.add_argument("--pages", type=page_flow.at_least_one, default=1,
                   help="Number of listing pages to fetch. Applies to --mode "
                        "role only. A run PLANS against the `pageCount` the "
                        "site states on page 1 and never asks past it — "
                        "asking for page 48 of a 47-page listing does not "
                        "error, it answers HTTP 200 with page 1 AGAIN, which "
                        "a run that trusted the request would collect twice. "
                        "A request for more is honoured up to that cap and "
                        "the sidecar records both numbers.")
    p.add_argument("--delay", type=page_flow.seconds, default=2.0, help="Delay between pages, seconds")
    p.add_argument("--concurrency", type=page_flow.at_least_one, default=1, metavar="N",
                   help="Fetch pages through N parallel workers (default 1 — "
                        "unchanged sequential behaviour). Each worker runs its "
                        "own browser and holds its own proxy exit, so N>1 "
                        "without --proxy-file just sends N times the traffic "
                        "from one address. Ignored with --cdp-endpoint.")
    p.add_argument("--retries", type=page_flow.attempts, default=3,
                   help="Attempts per page load before giving up (default 3). "
                        "The pause between attempts doubles each time. A page "
                        "that comes back EMPTY is not retried — see "
                        "page_flow.STATE_POLICY — because an empty "
                        "landing page is a correct answer, not a fault.")
    p.add_argument("--retry-delay", type=page_flow.seconds, default=2.0,
                   help="Seconds before the first page-load retry, doubling "
                        "thereafter (default 2.0)")
    p.add_argument("--format", choices=["json", "csv", "both"], default="both")
    p.add_argument("--out", default="wellfound_jobs", help="Output file prefix")
    p.add_argument("--locale", default="en-US",
                   help="Browser locale (default en-US). It does NOT decide "
                        "which directory is searched — that is find_country "
                        "in the URL, or --country — so this only affects what "
                        "the browser claims about itself.")
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
    p.add_argument("--proxy-block-retries", type=page_flow.non_negative, default=2,
                   help="When a page comes back refused (HTTP 403) or behind "
                        "a captcha, retry it from this many OTHER exits before "
                        "giving up (default 2). Needs a pool of more than one; "
                        "ignored otherwise. This is the flag that matters most "
                        "on this site: the refusal is a property of the "
                        "ADDRESS, and a different exit is what clears it.")
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
                        "always: solve whenever one is detected. Neither "
                        "setting changes what Cloudflare does: a managed "
                        "challenge is what a scored address gets on every "
                        "route here, and a solve only helps once "
                        "TURNSTILE_INTERCEPT_JS has captured its parameters. "
                        "A residential exit removes the challenge entirely, "
                        "which is why most runs never reach this path.")
    p.add_argument("--min-score", type=float, default=0.7,
                   help="reCAPTCHA v3 minimum score to request (0.3, 0.7 or 0.9 "
                        "— the API only accepts these three). Ignored for v2 "
                        "widgets.")
    proxy_check.add_media_flags(p)
    proxy_meter.add_budget_flag(p)
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
                        "a column comes back empty — see \"Traps that look like "
                        "bugs\" in the README.")
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

    # --url and the role flags are two ways to say the same thing, and only
    # one of them may win. Refused rather than merged: a --location that
    # disagreed with the one already in a /role/l/… path would silently
    # scrape a different listing than the address names, which is the hazard
    # a flag that overrides part of a URL always carries.
    if args.url and (args.role or args.location or args.remote):
        conflicting = [name for name, value in
                       (("--role", args.role), ("--location", args.location),
                        ("--remote", args.remote))
                       if value]
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
                "page. WELLFOUND_URL in the environment or in .env works "
                "too.")

    supported, why = is_supported_url(args.url)
    if not supported:
        # Refused rather than attempted. This parser reads Wellfound's own
        # Apollo cache and its JobPosting block; pointing it at another site
        # would not fail loudly, it would return zero rows and look like an
        # empty result. The REASON is given, because a wrong reason
        # about a host that plainly is one sends the reader hunting a typo.
        p.error(f"{args.url!r} {why}.")

    # The URL knows which mode it belongs to, so a disagreement is caught
    # here rather than producing zero rows from the wrong reader.
    # A parser pointed at the wrong page kind fails silently, and silence
    # is the failure this check exists to convert into an error message.
    url_mode = mode_for_url(args.url)
    if url_mode and url_mode != args.mode:
        p.error(f"--mode {args.mode} does not match {args.url!r}, which is a "
                f"--mode {url_mode} address. A /role/… page and a "
                f"/jobs/{{id}}-{{slug}} page publish their data through "
                f"different mechanisms, so the wrong reader returns no rows "
                f"rather than failing.")

    if args.mode in ("job", "jobs") and args.pages != 1:
        # Said out loud rather than silently ignored: a user who passed
        # --pages 5 expects five pages of something.
        logger.warning("--pages %d is ignored in --mode %s: there is one page "
                       "to read. In --mode jobs that is measured, not assumed "
                       "— `?page=2` on /jobs returns the identical rows as "
                       "page 1. The run status will say %s.", args.pages,
                       args.mode,
                       "single_page_mode" if args.mode == "job"
                       else "single_page_listing")
        args.pages = 1

    if args.category is None:
        # Default the run label to what the URL selects, so the sidecar names
        # the query without the flag.
        args.category = category_from_url(args.url)
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
