"""
page_flow.py
------------
The retry / solve / blocked decision, as DATA rather than as three copies of
an if-chain.

Maison KOSÉ answers a request four ways, and three of them want a different
response:

    a listing or product page with its content on it   -> parse
    a page it served with no products on it            -> parse, it is an answer
    an address that does not exist (HTTP 404)          -> stop, do not retry
    a refusal or a challenge                           -> rotate, or solve
    something that is not a Maison KOSÉ page at all    -> wait, then retry

Three copies of that triage across three engines would drift, and the drift
would be silent — one engine reporting exit 3 where its twin reports exit 0
on the same response.

The honest headline: nothing here has ever fired
-------------------------------------------------
Measured 2026-09-18 from a datacentre address (netcup, Nuremberg), against
maison.kose.co.jp:

    python-requests/2.31.0   HTTP 200, 90,310 bytes
    curl/8.5.0               HTTP 200, 90,310 bytes  (identical)
    a Chrome UA              HTTP 200, 90,310 bytes  (identical)
    no User-Agent header     HTTP 200, 90,310 bytes  (identical)

    12 consecutive page fetches, no delay between them -> 12 × HTTP 200

    zero captcha markers of any vendor across 13 captures (the count, in
    product_parser.BOT_CHALLENGE_MARKERS)

So on this site the block path is a TRIPWIRE, not a description of anything
observed. It is carried in full anyway, because the alternative to a tripwire
is a run that reports an empty catalogue on the day Kosé turns something on —
and because the most expensive bug in this family was a SENTENCE
claiming a captcha could not be met.

Nothing here claims a captcha is unsolvable on this site. There is no widget
to solve today; if one appears, `captcha_solver.py` is wired and the run pays
for it under the usual `--solve-captcha when-blocked` rule.

Two site shapes this module exists to get right
------------------------------------------------
**A category listing walked past its end returns its LAST PAGE AGAIN.**
`/c/c15_p13/` is the last page; `/c/c15_p14/` and `/c/c15_p15/` each return
the same 71,199 bytes, HTTP 200, with 16 real tiles on them. So "keep
fetching until a page comes back empty" never terminates on this route, and
`pages_to_plan` bounds a run by the site's own `N／Mページ` counter rather
than by walking off the end. A tag listing DOES end with an empty page, so
both routes still need the data-based stop.

**No JavaScript crosses this boundary.** `wait_for_count` takes a callback
each engine implements with its own `querySelectorAll`, never a string for
the browser to evaluate: a site whose CSP omits `unsafe-eval` kills
`wait_for_function` with an `EvalError` and takes the run down with exit 1
. maison.kose.co.jp's CSP does allow `unsafe-eval` — it is in
the header, checked — so this costs nothing here and keeps the habit.
"""

import argparse
import re
import time
from typing import Callable, Optional

import product_parser


# How many tiles mean "the grid has painted". Must be > 1: waiting for one
# match can resolve on something unrelated long before a grid is there.
#
# Two rather than four, and the number is measured rather than inherited. The
# anchor below is a real product TILE, not a link, so it cannot resolve on a
# nav item — and listing pages here are legitimately short: 16 tiles on the
# last page of a category, 11 on a single-page brand, 6 on the last page of a
# tag facet. A minimum of 4 would have spent the full readiness budget on a
# perfectly good three-product category before parsing it correctly anyway.
MIN_CARD_MATCHES = 2

# A listing page's readiness anchor.
#
# Element-qualified on purpose. The bare class `.c-product__item` is reused
# on a PRODUCT page as a `<div>` for staff-review cards — 15 of them on one
# measured page — so a class-only anchor would report a listing as ready on a
# product page. Measured across 14 captures: `li.c-product__item` counts
# 11-24 on every listing and **0 on every product page**, which is the clean
# separation montblanc-scraper's `.product-tile` did not have.
READY_SELECTOR_LISTING = "li.c-product__item"

# A product page's readiness anchor: 1 on every product capture, 0 on every
# listing. `.c-product-content__list` was the obvious alternative and was
# rejected by the same measurement — it is 1 on listings AND 1 on two of four
# product pages, because the detail page carries an `awoo` recommendation
# list built out of the same container.
READY_SELECTOR_PRODUCT = ".p-product-detail__item__price"

# This site server-renders both page kinds: the grid is in the first
# response's bytes, so readiness is a formality rather than a wait. The
# budget is generous anyway because it costs nothing when it is not needed —
# it is a ceiling, not a delay.
CONTENT_TIMEOUT_MS = 30_000
CONTENT_TIMEOUT_MS_PRODUCT = 20_000


def ready_selector(mode: str) -> str:
    return READY_SELECTOR_PRODUCT if mode == "product" else READY_SELECTOR_LISTING


def min_matches(mode: str) -> int:
    return 1 if mode == "product" else MIN_CARD_MATCHES


def content_timeout_ms(mode: str) -> int:
    return CONTENT_TIMEOUT_MS_PRODUCT if mode == "product" else CONTENT_TIMEOUT_MS


READY_POLL_MS = 500


def wait_for_count(count: Callable[[str], int], selector: str, minimum: int,
                   timeout_ms: int, sleep_ms: Callable[[int], None]) -> int:
    """Poll `count(selector)` until it reaches `minimum` or the budget runs out.

    Returns the last count seen, so a caller can report "13 of 24 painted"
    rather than a bare timeout. The OPERATION is named and the driver's own
    primitive is passed in, so no JavaScript dialect crosses this boundary
: Selenium's `execute_script` wants a function body with an
    explicit `return` while Playwright and pyppeteer want `() => expr`, and a
    shared module that spelled either would quietly acquire one driver's
    accent.
    """
    deadline = time.monotonic() + timeout_ms / 1000.0
    seen = 0
    while True:
        try:
            seen = count(selector)
        except Exception:
            seen = 0
        if seen >= minimum:
            return seen
        if time.monotonic() >= deadline:
            return seen
        sleep_ms(READY_POLL_MS)



# ---------------------------------------------------------------------------
# Flag validation
# ---------------------------------------------------------------------------

RETRIES_HELP = ("Attempts per page load before giving up (default 3, "
                "minimum 1). The pause between attempts doubles each time. A "
                "page that comes back EMPTY is not retried: an empty listing "
                "is a correct answer, not a fault. NOTE this counts ATTEMPTS "
                "here and RETRIES in scraper_api_client.py, where each one is "
                "separately billable — each file's own help says which.")


def attempts(value: str) -> int:
    """argparse type for --retries on an ENGINE: attempts, so at least 1.

    The load loop is `range(1, retries + 1)`. Zero ran it NEVER, so `goto`
    was not called and the engine judged `about:blank` — a 39-byte empty DOM
    reported as a result for a site that was never asked.

    That is not a hypothetical. A third-party audit of this repo on
    2026-10-13 ran exactly `--retries 0`, got the 39-byte document and exit
    4, and concluded in writing that the browser path was broken and that
    the HTTP path should replace it. The same command with `--retries 1`,
    same address and same minute, returned 199,558 bytes and 24 products.
    So this flag did not merely waste a run: it produced a confident, wrong
    verdict about the whole project. the family's notes record the identical
    sequence on a sibling repo, which is why this is a usage error now
    rather than a documented quirk.
    """
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer")
    if n < 1:
        raise argparse.ArgumentTypeError(
            "must be at least 1: it counts attempts per page load, and 0 "
            "would attempt none and then judge a page that was never "
            "fetched")
    return n


def extra_attempts(value: str) -> int:
    """argparse type for --retries on the BILLABLE Scraper API path.

    Zero is meaningful and safe there — it means one attempt, because that
    client computes `max(1, retries + 1)` — so this accepts 0 and refuses
    only a negative, which would otherwise be silently clamped and read as
    "the flag did nothing".
    """
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer")
    if n < 0:
        raise argparse.ArgumentTypeError(
            "cannot be negative: 0 means one attempt and no retry")
    return n


def at_least_one(value: str) -> int:
    """argparse type for a COUNT that must be positive: --pages, --concurrency.

    `--pages 0` or `--pages -1` used to be accepted and fetched nothing, so
    the run reported "no products" for a site it never asked.
    """
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer")
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def non_negative_int(value: str) -> int:
    """argparse type for a count where 0 means "none": --proxy-block-retries."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer")
    if n < 0:
        raise argparse.ArgumentTypeError("cannot be negative")
    return n


def non_negative_seconds(value: str) -> float:
    """argparse type for a pause in seconds: --delay, --retry-delay.

    A negative pause is not a shorter one: `time.sleep` raises ValueError on
    it, mid-run, after the first page has already been fetched.
    """
    try:
        n = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number")
    if not n >= 0:          # also refuses NaN
        raise argparse.ArgumentTypeError("cannot be negative")
    return n


def classify(html: Optional[str], status: Optional[int] = None,
             url: str = "") -> str:
    """The page's state, as one word.

    `status` is positional and second, which matters: this signature is bound
    against every call site by the suite, because a sibling repo shipped two
    engines calling `classify(html, url=…)` against a `classify(html, status,
    url)` and both crashed on their FIRST fetch — invisible to import,
    `--help` and `compileall`.
    """
    return classify_with_reason(html, status, url)[0]


def classify_with_reason(html: Optional[str], status: Optional[int] = None,
                         url: str = ""):
    """`(state, detail)`. The detail is for a log line and may be None."""
    if html is None:
        return ("unknown", "no response body")
    return product_parser.detect_page_state(html, status, url)


# A transport-level failure, which never reaches `classify` because no
# response arrived. Chromium reports a dead proxy as a generic error rather
# than as a timeout, and the two want OPPOSITE responses: a timeout deserves
# another try at the same exit, a dead proxy a different one.
_PROXY_FAILURE_RE = re.compile(
    r"ERR_PROXY_CONNECTION_FAILED|ERR_TUNNEL_CONNECTION_FAILED"
    r"|ERR_PROXY_AUTH_UNSUPPORTED|ERR_UNEXPECTED_PROXY_AUTH"
    r"|ERR_PROXY_CERTIFICATE_INVALID|ProxyError|407\b", re.I)

_TRANSPORT_REFUSAL_RE = re.compile(
    r"ERR_CONNECTION_CLOSED|ERR_CONNECTION_RESET|ERR_EMPTY_RESPONSE"
    r"|ERR_HTTP2_PROTOCOL_ERROR|not closed cleanly|INTERNAL_ERROR", re.I)


def classify_transport_error(exc: BaseException) -> str:
    """`proxy` · `refused` · `timeout` · `other` for an exception with no response.

    Unlike montblanc-scraper, `refused` is NOT this site's normal way of
    declining — maison.kose.co.jp has never been observed refusing anything,
    including to a bare `python-requests` UA. It is kept because a dropped
    connection is a real network event on any site and because calling it a
    timeout would send a run into a retry that cannot work.
    """
    text = f"{type(exc).__name__}: {exc}"
    if _PROXY_FAILURE_RE.search(text):
        return "proxy"
    if "timeout" in text.lower() or "timed out" in text.lower():
        return "timeout"
    if _TRANSPORT_REFUSAL_RE.search(text):
        return "refused"
    return "other"


# Product-shaped links below which "served but parsed to nothing" is not
# worth calling a parser failure.
#
# Two rather than one: a single stray `/g/g…/` link appears in the site's own
# 404 page (measured: exactly 1), so a threshold of one would report the 404
# as a broken parser. A real grid links to 22-55.
PARSE_FAILURE_MIN_LINKS = 2


def looks_like_a_parse_failure(state: str, rows: int, link_count: int) -> bool:
    """True when the page was SERVED, links to products, and parsed to zero.

    That combination is this repo's bug, not the site's, and it deserves to
    say so by name — "0 products" sends the reader to check the URL when the
    thing to check is the parser.

    It CAN fire here, which is worth checking before adding the signal: rows
    come from `li.c-product__item` tiles while the link count comes from
    `/g/g…/` hrefs, and a grid page carries 48-55 of those against 24 tiles.
    A tile-markup change therefore leaves the links untouched and the rows at
    zero — exactly the case this names. It is deliberately NOT a new exit
    code: the catalogue question really was answered, so it stays
    EXIT_NO_PRODUCTS and only the `stop_reason` differs.
    """
    if rows:
        return False
    if state not in ("content", "empty"):
        return False
    return link_count >= PARSE_FAILURE_MIN_LINKS


STATE_POLICY = {
    # Product tiles rendered. The unambiguous positive.
    "content":   {"retry": False, "solve": False, "blocked": False, "parse": True},
    # A page Maison KOSÉ served with no tiles on it: a tag facet walked past
    # its end, a bogus goods code, or the site's own 404. The site answered
    # exactly what was asked, so this is an answer and not a failure.
    # EXIT_NO_PRODUCTS rather than EXIT_BLOCKED — reporting it as blocked
    # sends a user hunting for a proxy problem that is not there.
    "empty":     {"retry": False, "solve": False, "blocked": False, "parse": True},
    # The address does not exist. TERMINAL: a 404 is an answer, and retrying
    # it spends a fetch on something that will never be there. Not blocked
    # either — reporting exit 3 would send the reader looking for a proxy
    # problem when the URL is simply wrong.
    #
    # It is its own state rather than folded into `empty` because the two
    # want different things said: an empty listing is a correct answer ABOUT
    # THE CATALOGUE, while a 404 is an answer about the ADDRESS.
    "not_found": {"retry": False, "solve": False, "blocked": False, "parse": False},
    # A refusal with no challenge on it. There is nothing to solve — an edge
    # that declines is not offering a test — so the only move is a different
    # exit. `solve` is False on a state whose name says blocked, and that is
    # the point: the "detected ≠ blocking ≠ paying".
    "blocked":   {"retry": True,  "solve": False, "blocked": True,  "parse": False},
    # A challenge widget. This one IS a test and is the state that pays for a
    # solver. A fresh browser from a different exit clears some challenges
    # too, which is why `retry` is also True. Never observed on this site.
    "challenge": {"retry": True,  "solve": True,  "blocked": True,  "parse": False},
    # Not recognisably a Maison KOSÉ page: an interstitial, a proxy's error
    # page, or Chromium's own — which carries the site's hostname in its
    # <title> and would fool a title check. A wait, not a spend.
    "unknown":   {"retry": True,  "solve": False, "blocked": False, "parse": False},
}


def should_retry(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY["unknown"])["retry"]


def should_solve(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY["unknown"])["solve"]


def counts_as_blocked(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY["unknown"])["blocked"]


def should_parse(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY["unknown"])["parse"]


# Whether a blocked page is worth re-fetching at all. CONSULTED by the
# engines rather than merely documented — setting it False really does stop
# the retry loop. (A sibling repo carried this constant with a paragraph of
# justification and no reader, which is the same defect as dead code that
# looks load-bearing.)
RETRY_ON_BLOCKED = True

# How many times to re-fetch a blocked page when there is no pool to rotate
# through. One: without a different exit, a re-fetch from the same address is
# the same request, and a second identical request is not evidence.
BLOCK_RETRIES_WITHOUT_POOL = 1

# One solve per page. A second solve on the same page is a second bill for
# the same answer.
SOLVES_PER_PAGE = 1


def pagination_is_addressable(url: str) -> bool:
    """Can page N of this listing be fetched without fetching page N-1?

    Yes on both of this site's listing routes, and it was CHECKED rather than
    assumed: page 1's own `rel=next` agrees with what the
    convention builds, on both. That is what lets `--concurrency` above 1
    mean anything here.

    A product URL is not a listing and has no page 2, so it is False — and
    the engines refuse concurrency on it with that reason rather than
    silently fetching page 1 N times.
    """
    return product_parser.is_listing_url(url)


def pages_to_plan(pages_requested: int, pages_avail: Optional[int],
                  start_page: int = 1) -> range:
    """The ABSOLUTE page numbers a run should fetch, starting at `start_page`.

    One implementation, in the shared module, because three engines each
    doing this arithmetic is how three engines come to disagree about where a
    run ends. Returns a range so a caller cannot get the inclusive bound
    wrong in its own loop.

    `start_page` is honoured rather than normalised away: a run pointed at
    `/c/c15_p10/` with `--pages 3` reads 10, 11 and 12. An earlier version
    reset every run to page 1, so a run aimed at page 10 quietly returned
    page 1's products and reported success.

    Bounded by the site's own counter where it published one, and on this
    site that is not merely thrift: a category listing fetched past its last
    page returns THAT LAST PAGE AGAIN, byte-identical and HTTP 200, so an
    uncapped `--pages 50` on a 13-page category would fetch page 13
    thirty-seven times and hand the deduper 888 rows to throw away.

    `pages_avail` of None means the site published no counter — which a TAG
    listing never does — and means UNKNOWN, never zero. Capping a tag run at
    zero pages would turn a working route into an empty file.
    """
    if pages_requested <= 0:
        return range(start_page, start_page)
    last = start_page + pages_requested - 1
    if pages_avail:
        last = min(last, max(pages_avail, start_page))
    return range(start_page, last + 1)


def concurrency_limit(cdp_endpoint: Optional[str]) -> Optional[int]:
    """1 over a remote CDP profile, else no limit imposed here.

    The Scraping Browser API allows ONE live connection per profile, so
    workers sharing an endpoint collide with `profile_locked`. Several `pid`s
    and one run each is the way to parallelise that path.
    """
    return 1 if cdp_endpoint else None
