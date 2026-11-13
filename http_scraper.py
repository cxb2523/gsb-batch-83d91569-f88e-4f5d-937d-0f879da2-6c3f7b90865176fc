#!/usr/bin/env python3
"""
kose-scraper — plain HTTP edition (no browser)
===============================================
The same scrape as `playwright_scraper.py`, over `requests`. Same parser,
same row schema, same sidecar, same exit codes — so its output IS the
browser engines' output, and `diff_runs.py` compares the two without knowing
which one fetched.

Why this exists, and why it is the RECOMMENDED path on this site
-----------------------------------------------------------------
Maison KOSÉ server-renders its grid into the first response and gates
nothing. Measured 2026-10-13 from a datacentre address, on
`/site/cosmedecorte/c/c15_p2/`:

    a project-named User-Agent      HTTP 200, 97,121 bytes, 24 tiles
    python-requests/2.32            HTTP 200, 97,121 bytes, 24 tiles
    NO User-Agent header at all     HTTP 200, 97,121 bytes, 24 tiles
    a desktop Chrome User-Agent     HTTP 200, 97,121 bytes, 24 tiles

Byte-identical, all four. There is no JavaScript to run, no challenge to
clear and no fingerprint to match, so a browser on this site buys nothing
and costs a Chromium install, a few hundred MB of memory and several seconds
a page.

That makes this the honest default, and it was the main recommendation of a
third-party audit on 2026-10-13 — the half of that report which was right.
The other half, that the browser path was broken, was an artefact of the
audit's own `--retries 0`; see `page_flow.attempts`. Both engines work, and
the canary runs both, because "a browser is unnecessary here" is a claim
about the SITE and can stop being true.

What a browser is still for
----------------------------
* a captcha, if Kosé ever renders one — nothing here can solve one;
* the Scraping Browser API over `--cdp-endpoint`, which is a browser;
* a fingerprinted identity, for the same reason.

So the flags this engine cannot honour are REFUSED as usage errors rather
than accepted and silently ignored: a setting that looks configurable and is
not is worse than one that is absent.

Usage:

    python http_scraper.py \\
        --url "https://maison.kose.co.jp/site/cosmedecorte/c/c15/" --pages 3

    python http_scraper.py --tags "シワ改善,スキンケア" --pages 2

    python http_scraper.py --mode product \\
        --url "https://maison.kose.co.jp/site/onebykose/g/gMUSC/"
"""

import argparse
import logging
import re
import sys
import time
from typing import List, Optional, Set
from urllib.parse import quote

import requests

import env_config
import page_flow
from output_writer import (EXIT_API_ERROR, SOURCE_DEFAULT, dedupe_by_key,
                           finish_run)
from product_parser import (PAGE_SIZE, is_product_url, is_supported_url,
                            page_number_from_url, page_url, parse_listing,
                            parse_product_detail, product_link_count,
                            references_own_assets, route_of, tags_from_url)
from proxy_pool import ROTATE_MODES, ProxyError, mask
from proxy_pool import from_args as proxy_pool_from_args

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("http_scraper")

# An honest identity rather than a disguise. Measured above: this site serves
# a project-named UA exactly as it serves Chrome, so there is nothing to gain
# by claiming to be a browser — and the family's notes record a sibling site that
# refuses precisely the CONTRADICTION between a claimed UA and the TLS
# fingerprint underneath it. Saying what we are costs nothing here and cannot
# backfire that way.
USER_AGENT = ("kose-scraper/0.2 (+https://github.com/2scraper/kose-scraper; "
              "reads public catalogue pages)")

# This site's pages are 90-200 KB. A cap stops a misrouted response — a
# captive portal, a proxy's error page, a tarpit — from being read whole.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

REQUEST_TIMEOUT = (10, 30)   # (connect, read) seconds: every call is bounded.

ITEM_LINK_SELECTOR = page_flow.READY_SELECTOR_LISTING


class PageOutcome:
    """What one page produced. Mirrors the browser engines' PageOutcome."""

    def __init__(self, page_num: int, url: str):
        self.page_num = page_num
        self.url = url
        self.final_url: Optional[str] = None
        self.products: List = []
        self.blocked_by: Optional[str] = None
        self.load_failed = False
        self.state: Optional[str] = None
        self.pages_available: Optional[int] = None
        self.canonical: Optional[str] = None
        self.status: Optional[int] = None

    @property
    def ok(self) -> bool:
        return not self.load_failed and self.blocked_by is None


_CREDENTIALS_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^/\s@]+)@")


def _mask(text: str) -> str:
    """Credentials out of an exception message — GLOBALLY, not once.

    `requests` puts the FULL URL into the text of `HTTPError` and of every
    connection error, so a proxy URL with a password in it reaches the log
    the moment anything goes wrong. A masker that handles the first
    occurrence prints the password the other times and looks like it is
    working. Host and port are kept: which exit a run used is the point
    of the log and is not the secret.
    """
    return _CREDENTIALS_RE.sub(r"\1***:***@", text or "")


def _session(args) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": args.user_agent,
        # The site honours gzip: 97 KB on disk is 18 KB on the wire, measured.
        "Accept-Encoding": "gzip, deflate",
        "Accept": "text/html,application/xhtml+xml",
        # A Japanese storefront with no other market, so this is what a
        # visitor's browser sends rather than a disguise.
        "Accept-Language": "ja,en;q=0.8",
    })
    return s


def _get(session, args, url, proxies):
    """One bounded GET. Returns (html, status, final_url)."""
    response = session.get(url, timeout=REQUEST_TIMEOUT, proxies=proxies,
                           allow_redirects=True, stream=True)
    raw = response.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=True)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError(f"response exceeded {MAX_RESPONSE_BYTES} bytes, "
                         f"which no page on this site does")
    html = raw.decode(response.encoding or "utf-8", "replace")
    return html, response.status_code, response.url


def _fetch_one_page(session, args, pool, page_num: int, url: str) -> PageOutcome:
    """Fetch and parse one page. Never raises for an EXPECTED failure."""
    outcome = PageOutcome(page_num, url)
    html, status, final_url, state = None, None, url, "unknown"

    has_pool = bool(pool and len(pool) > 1)
    block_retries = 0 if not page_flow.RETRY_ON_BLOCKED else (
        args.proxy_block_retries if has_pool
        else page_flow.BLOCK_RETRIES_WITHOUT_POOL)

    for block_attempt in range(block_retries + 1):
        logger.info("Fetching page %d/%d: %s", page_num, args.pages, url)
        load_failed, exit_failed = False, None
        proxies = None
        if pool is not None and pool.current:
            proxies = {"http": pool.current, "https": pool.current}

        for attempt in range(1, args.retries + 1):
            try:
                html, status, final_url = _get(session, args, url, proxies)
                load_failed = False
                break
            except (requests.RequestException, ValueError) as e:
                # A dead or unauthenticated proxy is NOT a timeout, and the
                # two want opposite responses: a timeout deserves another try
                # at the same exit, a dead proxy a different one.
                kind = page_flow.classify_transport_error(e)
                load_failed = True
                if kind == "proxy":
                    exit_failed = kind
                    logger.error("Proxy failure reaching %s: %s",
                                 url, _mask(str(e))[:200])
                    break
                if attempt < args.retries:
                    pause = args.retry_delay * (2 ** (attempt - 1))
                    logger.warning("Failed to load %s (attempt %d/%d: %s) — "
                                   "retrying in %.1fs.", url, attempt,
                                   args.retries, _mask(str(e))[:140], pause)
                    time.sleep(pause)
                else:
                    logger.error("Gave up loading %s after %d attempt(s): %s",
                                 url, args.retries, _mask(str(e))[:200])

        if exit_failed and has_pool and block_attempt < block_retries:
            logger.warning("Exit %s is unusable (%s) — rotating to another "
                           "one (%d/%d).", mask(pool.current), exit_failed,
                           block_attempt + 1, block_retries)
            pool.advance(f"unusable exit: {exit_failed}")
            continue

        if load_failed:
            outcome.load_failed = True
            return outcome

        # The status is threaded to the classifier. That is this engine's one
        # real advantage over Selenium, which cannot: WebDriver exposes no
        # HTTP status at all, so that engine has to read one out of the
        # site's own error page.
        state = page_flow.classify(html, status, final_url)
        if not page_flow.counts_as_blocked(state):
            break

        if block_attempt < block_retries:
            if has_pool:
                logger.warning("Page %d came back as %s from %s — retrying "
                               "from another exit (%d/%d).", page_num, state,
                               mask(pool.current), block_attempt + 1,
                               block_retries)
                pool.advance(f"{state} on page {page_num}")
            else:
                pause = args.retry_delay * (block_attempt + 1)
                logger.warning("Page %d came back as %s and there is no proxy "
                               "pool to rotate through — re-fetching in "
                               "%.1fs (%d/%d).", page_num, state, pause,
                               block_attempt + 1, block_retries)
                time.sleep(pause)

    outcome.state = state
    outcome.final_url = final_url
    outcome.status = status

    if args.dump_html:
        # On success too, not only on failure: a run can return the right
        # count with a column silently unpopulated, and then the exact bytes
        # are the only way to tell a parsing bug from a bad response.
        path = (args.dump_html if args.pages == 1
                else f"{args.dump_html}.page{page_num}")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html or "")
        logger.info("Saved the snapshot the parser sees to %s (%d bytes).",
                    path, len(html or ""))

    if page_flow.counts_as_blocked(state):
        outcome.blocked_by = state
        logger.error(
            "Maison KOSE did not serve this request — HTTP %s, %d bytes, its "
            "own assets referenced %d time(s). Nothing on this site has ever "
            "produced this state: measured 2026-10-13, a request with NO "
            "User-Agent header at all is served the same bytes as a browser. "
            "So check the network path — a proxy, a captive portal, DNS — "
            "before the site. This is exit 3, distinct from a genuinely "
            "empty result (exit 4).",
            status, len(html or ""), references_own_assets(html or ""))
        return outcome

    if state == "not_found":
        logger.error("%s does not exist — HTTP 404. On this site a bogus "
                     "goods code or category id answers 200 with an empty "
                     "page instead, so a real 404 means the PATH is wrong, "
                     "not the id.", final_url)
        return outcome

    if not page_flow.should_parse(state):
        logger.info("Page %d came back as %s; nothing to parse.",
                    page_num, state)
        return outcome

    if args.mode == "product":
        rows, listing = parse_product_detail(html, final_url,
                                             mode=args.mode), None
    else:
        listing = parse_listing(html, final_url, page=page_num, mode=args.mode)
        rows = listing.rows
    if args.category:
        for row in rows:
            row.category = args.category

    logger.info("Parsed %d row(s) from page %d.", len(rows), page_num)

    if listing is not None:
        outcome.pages_available = listing.pages_available
        outcome.canonical = listing.canonical
        if page_num == 1:
            logger.info("Page 1: %s tile(s), %s product-shaped link(s), the "
                        "site reports %s. Canonical: %s",
                        listing.tiles_on_page, listing.product_links_on_page,
                        ("%s page(s)" % listing.pages_available)
                        if listing.pages_available
                        else "no page counter (a tag listing publishes none)",
                        listing.canonical or "none")

    if not rows and page_flow.looks_like_a_parse_failure(
            state, len(rows), product_link_count(html or "")):
        dump = f"{args.out}_page{page_num}_debug.html"
        with open(dump, "w", encoding="utf-8") as f:
            f.write(html or "")
        logger.error(
            "Page %d links to %d product(s) and parsed to ZERO rows. The site "
            "served this page — this is a failure in THIS parser, not an "
            "empty category and not a block. Saved to %s; check "
            "`li.c-product__item` before you check the URL.",
            page_num, product_link_count(html or ""), dump)
        outcome.state = "parse_failed"

    outcome.products = rows
    return outcome


def scrape(args) -> int:
    _started = time.monotonic()
    try:
        pool = proxy_pool_from_args(args)
    except ProxyError as e:
        logger.error("%s", e)
        return 2

    session = _session(args)
    outcomes: List[PageOutcome] = []
    stop_reason = "completed"
    blocked = False
    seen_keys: Set[str] = set()

    target = args.url
    first = _fetch_one_page(session, args, pool, 1, target)
    outcomes.append(first)

    if not first.ok:
        stop_reason = ("page_load_timeout" if first.load_failed
                       else f"blocked_{first.blocked_by}")
        blocked = first.blocked_by is not None
    elif first.state == "not_found":
        stop_reason = "not_found"
    elif first.state == "parse_failed":
        stop_reason = "parser_found_nothing"
    elif args.mode == "product":
        pass
    else:
        seen_keys.update(p.sku for p in first.products if p.sku is not None)
        start = page_number_from_url(first.final_url or target) or 1
        planned = page_flow.pages_to_plan(args.pages, first.pages_available,
                                          start)
        if planned.stop - 1 < start + args.pages - 1:
            logger.info("The site reports %s page(s) and %d were asked for "
                        "starting at %d. Stopping at %d: past the end a "
                        "category listing serves its LAST PAGE again rather "
                        "than an empty one.", first.pages_available,
                        args.pages, start, planned.stop - 1)
            stop_reason = "page_cap_reached"

        for n in list(planned)[1:]:
            page_num = len(outcomes) + 1
            if args.delay:
                time.sleep(args.delay)
            outcome = _fetch_one_page(session, args, pool, page_num,
                                      page_url(first.final_url or target, n))
            outcomes.append(outcome)
            if not outcome.ok:
                stop_reason = ("page_load_timeout" if outcome.load_failed
                               else f"blocked_{outcome.blocked_by}")
                blocked = blocked or outcome.blocked_by is not None
                break
            fresh = [p for p in outcome.products
                     if p.sku is not None and p.sku not in seen_keys]
            if not fresh:
                # The data-based stop, and on this site it is
                # not optional: past its last page a category listing serves
                # THAT PAGE AGAIN, byte-identical and HTTP 200, so a run that
                # waited for an empty page would never stop.
                stop_reason = "no_new_products"
                logger.info("Page %d added no sku this run had not already "
                            "seen — the listing is over.", page_num)
                break
            seen_keys.update(p.sku for p in fresh)

    # Merged in PAGE order, never arrival order.
    all_rows: List = []
    merged_seen: Set[str] = set()
    for oc in sorted(outcomes, key=lambda o: o.page_num):
        all_rows.extend(dedupe_by_key(oc.products, merged_seen, key="sku"))

    ok_pages = [o for o in outcomes if o.ok]
    failed_pages = [o.page_num for o in outcomes if not o.ok]
    final_url = (max(ok_pages, key=lambda o: o.page_num).final_url
                 if ok_pages else args.url)
    pages_available = next((o.pages_available for o in outcomes
                            if o.pages_available is not None), None)
    canonical_seen = next((o.canonical for o in outcomes if o.canonical), None)

    if args.mode == "product":
        extra = {}
    else:
        extra = {"pages_available": pages_available,
                 "page_size": PAGE_SIZE,
                 "canonical_url": canonical_seen,
                 "route": route_of(final_url or args.url),
                 "tags": tags_from_url(final_url or args.url)}

    # Which engine fetched, what version of its transport, and how long it
    # took. A consumer diffing two runs can otherwise not tell that one used
    # a browser and one did not — and on this site they are expected to
    # agree, which is a claim worth being able to check.
    extra = {**extra, "engine": "http",
             "engine_version": requests.__version__,
             "duration_seconds": round(time.monotonic() - _started, 1)}

    return finish_run(
        all_rows, args.out, args.format, args.allow_empty, blocked=blocked,
        stop_reason=("single_page_mode" if args.mode == "product"
                     else stop_reason),
        pages_requested=args.pages, pages_completed=len(ok_pages),
        pages_failed=failed_pages, start_url=args.url, final_url=final_url,
        mode=args.mode, source=SOURCE_DEFAULT, extra=extra)


def _refuse(parser, flag: str, why: str):
    parser.error(
        f"{flag} needs a browser and this engine has none: {why}. Use "
        f"playwright_scraper.py (or puppeteer_scraper.py) for it. Refused "
        f"rather than ignored, because a flag that looks configurable and "
        f"does nothing is worse than one that is absent.")


def parse_args():
    p = argparse.ArgumentParser(
        description="Maison KOSE scraper (plain HTTP, no browser). The "
                    "recommended path on this site: it server-renders its "
                    "grid and gates nothing, so a browser buys nothing here.")
    p.add_argument("--url", default=None,
                   help="A maison.kose.co.jp URL: a category listing "
                        "(/site/{brand}/c/cNN/), a tag listing "
                        "(/site/itemtags/list.aspx?tags=A,B) or one product "
                        "page (/site/{brand}/g/gSKU/) with --mode product. "
                        "Also read from KOSE_URL in the environment or .env.")
    p.add_argument("--tags", default=None, metavar="A,B",
                   help="Kose's own facet tags, comma-separated. Builds a "
                        "/site/itemtags/list.aspx URL — the one listing route "
                        "that crosses brands.")
    p.add_argument("--mode", choices=["listing", "product"], default="listing",
                   help="listing (default) or product: the same two modes the "
                        "browser engines take, reading the same columns.")
    p.add_argument("--category", default=None,
                   help="A category id to build a URL from ('c15', 'c21'), or "
                        "a label to tag output rows with.")
    p.add_argument("--pages", type=page_flow.at_least_one, default=1,
                   help="How many pages to read, starting at the one --url "
                        "names (default 1).")
    p.add_argument("--delay", type=page_flow.non_negative_seconds, default=1.0,
                   help="Seconds between pages (default 1.0). Lower than the "
                        "browser engines' default because a request here is "
                        "one GET rather than a page load; on an ungated site "
                        "politeness is the only reason for it.")
    p.add_argument("--retries", type=page_flow.attempts, default=3,
                   help=page_flow.RETRIES_HELP)
    p.add_argument("--retry-delay", type=page_flow.non_negative_seconds, default=2.0,
                   help="Seconds before the first retry, doubling thereafter.")
    p.add_argument("--format", choices=["json", "csv", "both"], default="both")
    p.add_argument("--out", default="kose_products", help="Output file prefix")
    p.add_argument("--proxy", default=None,
                   help="One proxy URL. Credentials ride in the URL and are "
                        "masked in every log line.")
    p.add_argument("--proxy-file", default=None,
                   help="A file of proxy URLs, one per line.")
    p.add_argument("--proxy-rotate", choices=list(ROTATE_MODES),
                   default="per-run")
    p.add_argument("--proxy-shuffle", action="store_true")
    p.add_argument("--proxy-block-retries", type=page_flow.non_negative_int, default=2)
    p.add_argument("--allow-empty", action="store_true",
                   help="Write an empty result instead of leaving the "
                        "previous good output in place.")
    p.add_argument("--dump-html", default=None, metavar="PATH",
                   help="Save the exact HTML the parser is given, on success "
                        "as well as on failure.")
    p.add_argument("--user-agent", default=USER_AGENT,
                   help="What to identify as. The default NAMES this project "
                        "rather than imitating a browser: measured "
                        "2026-10-13, this site serves a project UA, a "
                        "requests UA, a Chrome UA and no UA at all the same "
                        "bytes, so there is nothing to gain by claiming to be "
                        "something else.")
    # Accepted by the parser only so they can be REFUSED with a reason.
    p.add_argument("--cdp-endpoint", default=None, help=argparse.SUPPRESS)
    p.add_argument("--solve-captcha", default=None, help=argparse.SUPPRESS)
    p.add_argument("--fingerprint", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--concurrency", type=page_flow.at_least_one, default=1, help=argparse.SUPPRESS)
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
    env_config.apply(args)

    if args.cdp_endpoint:
        _refuse(p, "--cdp-endpoint", "it IS a remote browser, over CDP")
    if args.solve_captcha:
        _refuse(p, "--solve-captcha",
                "a challenge has to be rendered before it can be solved")
    if args.fingerprint:
        _refuse(p, "--fingerprint",
                "a fingerprint is a browser identity, and this engine sends "
                "one honest User-Agent instead")
    if args.concurrency > 1:
        p.error("--concurrency above 1 is not implemented here. One GET per "
                "page is already fast — three pages in about three seconds, "
                "measured — and parallel requests from one address are a "
                "faster way to get it scored than to gather data. Use "
                "playwright_scraper.py if you need workers.")

    if typed_url and args.tags:
        p.error("--url already names what to fetch; pass either a URL or "
                "--tags, not both.")
    if not typed_url and args.tags:
        if args.mode == "product":
            p.error("--mode product needs a --url: a product is one page at "
                    "one address, and --tags describes a facet.")
        args.url = ("https://maison.kose.co.jp/site/itemtags/list.aspx?tags="
                    + quote(args.tags, safe=","))
        logger.info("Built the tag listing URL from --tags: %s", args.url)
    elif not typed_url and args.category:
        if not re.fullmatch(r"c\d+", args.category):
            p.error("--category builds a URL from a category id like 'c15' or "
                    "'c21'. %r is not one; pass a full --url if you meant "
                    "something else." % args.category)
        args.url = f"https://maison.kose.co.jp/site/c/{args.category}/"
        logger.info("Built the listing URL from --category: %s", args.url)
    if not args.url:
        p.error("no --url given and no --tags/--category: pass a "
                "maison.kose.co.jp URL, or --category c15, or --tags with a "
                "facet. KOSE_URL in the environment or in .env works too.")

    supported, why = is_supported_url(args.url)
    if not supported:
        p.error(f"{args.url!r} {why}.")
    if args.mode == "product" and not is_product_url(args.url):
        p.error(f"--mode product expects a product URL ending in /g/gSKU/; "
                f"{args.url!r} is not one.")
    if args.mode != "product" and is_product_url(args.url):
        p.error(f"{args.url!r} is a single product page. Use --mode product "
                f"for it, or pass a listing URL.")
    if args.mode == "product" and args.pages != 1:
        logger.warning("--pages %d is ignored in --mode product: there is one "
                       "page to read, and on this site one page is one row.",
                       args.pages)
        args.pages = 1
    return args


def _cli():
    """Console entry point, so `pip install .` gives a command.

    The module stays runnable as a script — `python http_scraper.py …` is
    what every example in the README and the workflows uses — and
    this is the same code path rather than a second one.
    """
    try:
        sys.exit(scrape(parse_args()))
    except KeyboardInterrupt:
        logger.warning("Interrupted.")
        sys.exit(EXIT_API_ERROR)


if __name__ == "__main__":
    _cli()
