"""
page_flow.py
------------
The retry / solve / blocked decision, as DATA rather than as three copies of
an if-chain.

Wellfound answers a request five ways, and four of them want a different
response:

    a rendered page with job records in it              -> parse
    a rendered landing page that matched nothing        -> parse, it is an answer
    Cloudflare's managed challenge, HTTP 403            -> solve, or rotate
    a page Wellfound served that we could not read      -> parse_error, dump it
    something else entirely                             -> wait, then retry

Three copies of that triage across three engines would drift, and the drift
would be silent — one engine reporting exit 3 where its twin reports exit 0
on the same response.

Nothing here imports a browser, and **no JavaScript crosses this boundary**:
Selenium's `execute_script` takes a function BODY with an explicit `return`
while Playwright and pyppeteer take `() => expr`, so a shared snippet would
quietly acquire one driver's dialect. The callbacks below are named for the
OPERATION instead, and each engine spells it in its own dialect.
"""

import argparse
import logging
from typing import Callable, Optional

from product_parser import (detect_bot_challenge,  # noqa: F401
                            detect_page_state, route_of)

log = logging.getLogger("page_flow")


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

# How many job links mean "this response is a listing".
#
# `> 1` on purpose: waiting for ONE match resolves on
# something unrelated — a nav link, a footer — long before the grid is
# really there. A landing page carried 32 to 45 job rows across the
# captures and the thinnest full page held 32, so four is a floor that a
# real page clears instantly and a half-arrived one does not.
MIN_CARD_MATCHES = 4

# A listing page's readiness anchor for the browser engines.
#
# A job URL is `/jobs/{id}-{slug}` — a contract with search engines, not a
# build-generated class, so it is the anchor rather than a CSS class. Wellfound's own class names are Tailwind-style utility strings and
# would churn on any deploy.
#
# Note this is a readiness signal only. The ROWS come out of `__NEXT_DATA__`,
# not out of these anchors, so a page whose grid has not painted can still
# parse completely — which is why the engines do not gate parsing on it.
READY_SELECTOR_LISTING = 'a[href*="/jobs/"]'

# A job page states its title in an `h1`.
READY_SELECTOR_JOB = 'h1'

CONTENT_TIMEOUT_MS = 45_000
CONTENT_TIMEOUT_MS_JOB = 30_000


def ready_selector(mode: str) -> str:
    return READY_SELECTOR_JOB if mode == "job" else READY_SELECTOR_LISTING


def min_matches(mode: str) -> int:
    return 1 if mode == "job" else MIN_CARD_MATCHES


def content_timeout_ms(mode: str) -> int:
    return CONTENT_TIMEOUT_MS_JOB if mode == "job" else CONTENT_TIMEOUT_MS


# How long to keep polling for an anchor, and how often.
#
# Polled through `count(selector)` — a callback each engine implements with
# its own `querySelectorAll` call — and NEVER by handing the browser a string
# to evaluate. A site whose Content-Security-Policy omits
# `unsafe-eval` kills `wait_for_function` with an `EvalError` and takes the
# run down with exit 1. Wellfound has not been measured for that, and the
# cheap habit costs nothing on a site that would have allowed it.
READY_POLL_MS = 500


def wait_for_count(count: Callable[[str], int], selector: str, minimum: int,
                   timeout_ms: int, sleep_ms: Callable[[int], None]) -> int:
    """Poll `count(selector)` until it reaches `minimum` or the budget runs out.

    Returns the last count seen, so a caller can report "3 of 4 expected"
    rather than only that it timed out.
    """
    waited = 0
    seen = 0
    while waited <= timeout_ms:
        seen = count(selector)
        if seen >= minimum:
            return seen
        sleep_ms(READY_POLL_MS)
        waited += READY_POLL_MS
    return seen


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------

def classify(html: Optional[str], status: Optional[int] = None,
             url: str = "", mode: str = "role") -> str:
    """Name what Wellfound answered with. See product_parser.detect_page_state.

    The argument ORDER is the contract: every engine calls
    `classify(html, status, url)`, with `mode` keyword-only in practice. A
    sibling repo shipped `classify(html, url=...)` in two of three engines
    against a callee that took `status` second, and both crashed on their
    first fetch — invisible to import, `--help`, `compileall` and 400+ green
    offline assertions, because none of those calls a function the way a live
    run does. `smoke_test.py` binds every engine's call against this
    signature for that reason.
    """
    return detect_page_state(html or "", status, url, mode)


STATE_POLICY = {
    # A rendered page with job records in it.
    "content":     {"retry": False, "solve": False, "blocked": False, "parse": True,
                    "obtained": True},
    # A landing page Wellfound served that matched nothing, carrying its own
    # "no jobs found" copy. The site answered exactly what was asked and it
    # has no jobs in it — a real answer, and EXIT_NO_PRODUCTS rather than
    # EXIT_BLOCKED. Reporting it as blocked sends a user hunting for a proxy
    # problem that is not there.
    "empty":       {"retry": False, "solve": False, "blocked": False, "parse": True,
                    "obtained": True},
    # Cloudflare. On this site the two refusal skins — the branded
    # "Security Check | Wellfound" 403 and the "Just a moment..."
    # interstitial — are ONE state, because they are the same decision by the
    # same vendor. They are NOT identical, though, and the difference was
    # measured on 2026-09-18 rather than assumed: the branded no-JS skin
    # carries NO widget at all — 0 references to
    # `challenges.cloudflare.com/turnstile` and 0 to `cf-turnstile`, against
    # `_cf_chl_opt` 7 times — while the browser's "Just a moment..." skin
    # carries one. So there is literally nothing to solve on the first, and
    # something to solve on the second.
    #
    # They stay ONE state anyway, and that is the point of keeping them
    # together: both answer to a different exit, and the solve path already
    # refuses to build a task when no sitekey was captured, which is exactly
    # what happens on the widget-less skin. Splitting the state would add a
    # branch that changes nothing a caller does.
    #
    # `solve` is True because the challenge really is a test, and the engines
    # can build a task for it once `TURNSTILE_INTERCEPT_JS` has captured the
    # parameters Cloudflare keeps out of the markup. `retry` is True because
    # a different exit clears it outright — measured, and much cheaper.
    "blocked":     {"retry": True,  "solve": True,  "blocked": True,  "parse": False,
                    "obtained": False},
    # A page built out of Wellfound's own assets whose payload we could not
    # read. NOT "zero jobs": a served page that links to jobs and parses to
    # nothing is OUR bug, and reporting it as an empty listing sends the
    # reader to check the URL instead of the parser. Worth
    # one retry in case the document was caught mid-swap, and always worth a
    # dump.
    "parse_error": {"retry": True,  "solve": False, "blocked": False, "parse": False,
                    "obtained": False},
    # A 404. Retrying an address that does not exist is pure waste, and it is
    # not a block — saying so stops a user rotating proxies over a typo.
    # A 404 is OBTAINED: the site answered, definitively, that this address
    # holds nothing. A consumer can conclude something about the catalogue
    # from it — "that job is gone" — which is what separates it from
    # `unknown` and `parse_error`, where nothing can be concluded. So it
    # exits 4 like `empty` rather than 5, and it is still not parsed and not
    # retried, because re-fetching an address that does not exist is waste.
    "not_found":   {"retry": False, "solve": False, "blocked": False, "parse": False,
                    "obtained": True},
    # Something that is neither the site nor a recognised refusal — an
    # upstream error page, a proxy's own response, Chromium's network-error
    # page. A wait, not a spend.
    "unknown":     {"retry": True,  "solve": False, "blocked": False, "parse": False,
                    "obtained": False},
}


def content_obtained(state: str) -> bool:
    """Did this response give us the site's own answer?

    The distinction `should_parse` does NOT make. `empty` holds no rows and
    is still an answer — the site served a listing and it matched nothing —
    while `unknown`, `parse_error`, `not_found` and `blocked` mean the
    content was never obtained, so nothing can be concluded about the
    catalogue from them.

    Collapsing the two is how a run that fetched nothing reports "0 jobs"
    (exit 4) instead of "the content never arrived" (exit 5). A third-party
    audit on 2026-10-13 reported exactly that outcome and read it as the
    site having emptied out; the chain was `unknown` -> an outcome still
    marked ok -> stop_reason "completed" -> zero rows -> exit 4, with
    `finish_run`'s own exit-5 branch never reachable because nothing ever
    told it the run had failed.
    """
    return STATE_POLICY.get(state, STATE_POLICY["unknown"])["obtained"]


def stop_reason_for(load_failed: bool, blocked_by: Optional[str],
                    state: Optional[str]) -> str:
    """The stop reason for a page that did not yield rows.

    One implementation because the engines derive this in seven places
    between them, and three copies of a triage drift silently — which is the
    argument this module exists for. `content_not_obtained_*`
    is deliberately NOT in `COMPLETE_STOP_REASONS`, so a zero-row run
    carrying it exits 5 rather than 4.
    """
    if load_failed:
        return "page_load_timeout"
    if blocked_by:
        return f"blocked_{blocked_by}"
    if state and not content_obtained(state):
        return f"content_not_obtained_{state}"
    return "completed"


def should_retry(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY["unknown"])["retry"]


def should_solve(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY["unknown"])["solve"]


def counts_as_blocked(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY["unknown"])["blocked"]


def should_parse(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY["unknown"])["parse"]


# Whether a blocked page is worth re-fetching at all.
#
# True here, and CONSULTED rather than merely documented — the engines read
# it, so setting it False really does stop the retry loop. (A sibling repo
# carried this constant with a paragraph of justification and no reader,
# which is the same defect as dead code that looks load-bearing.)
#
# True because on Wellfound a re-fetch genuinely can change the answer, and
# the measurement says which kind of re-fetch. From one datacenter address
# every route was refused — plain HTTP, headless Chromium and headful
# Chromium alike — so retrying from the SAME address is near-hopeless; from
# a residential exit every route this scraper reads answered 200 three times
# out of three. What the site scores is the address, and a retry that moves
# the address is the retry worth making.
#
# CONSULTED rather than merely documented — the engines read it, so setting
# it False really does stop the retry loop. (A sibling repo carried this
# constant with a paragraph of justification and no reader, which is the
# same defect as dead code that looks load-bearing.)
RETRY_ON_BLOCKED = True

# How many times to re-fetch a blocked page when there is no proxy pool to
# rotate into.
#
# One, and only one: without a pool every retry leaves from the same address,
# and Wellfound's refusal is an address-level decision — a Hetzner VPS was
# refused on every route including robots.txt, by three different clients. A
# second attempt from the same exit is a second identical refusal. WITH a
# pool, the engines retry once per remaining exit instead, because there the
# retry changes the one variable the refusal depends on.
BLOCK_RETRIES_WITHOUT_POOL = 1

# At most one solve per page. A challenge that survives a solved token is not
# a challenge this run can pass, and a second solve is a second charge for
# the same answer.
SOLVES_PER_PAGE = 1


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def attempts(value: str) -> int:
    """argparse type for `--retries`: ATTEMPTS per page load, so at least 1.

    The engines' load loop is `range(1, retries + 1)`. Zero therefore ran it
    NEVER: `goto` was not called, nothing was fetched, and the engine then
    classified `about:blank` — a 39-byte empty DOM with no markers and no
    assets, which comes out as `unknown` and, because the outcome was never
    marked failed, as a COMPLETE run holding zero jobs.

    That is not a hypothetical. A third-party audit of this repo on
    2026-10-13 ran `--retries 0`, got exactly that, and concluded the site
    had stopped serving the scraper. The same command with `--retries 1`
    returned the site's real refusal — 11,922 bytes, classified `blocked`,
    exit 3 — and with a residential exit, 115 rows over three pages.

    So the flag is rejected rather than clamped: a run that silently became
    a different run is how the misreading happened, and `0` is much more
    likely to be a misunderstanding of the name than an instruction.
    """
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer")
    if n < 1:
        raise argparse.ArgumentTypeError(
            "must be at least 1: it counts ATTEMPTS per page load, and 0 "
            "would attempt none and then judge a page that was never "
            "fetched")
    return n


def _number(value: str, kind, minimum, what: str):
    try:
        n = kind(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number")
    if n != n or n < minimum:   # n != n: NaN
        raise argparse.ArgumentTypeError(f"must be {what}, got {value}")
    return n


def at_least_one(value: str) -> int:
    """argparse type for a COUNT of pages or workers: 1 or more."""
    return _number(value, int, 1, "at least 1")


def non_negative(value: str) -> int:
    """argparse type for a count of EXTRA tries (0 = none): 0 or more.

    A negative `--proxy-block-retries` made the block loop `range(0)`, so the
    page was never fetched at all — the same silent no-op `--retries 0` was.
    """
    return _number(value, int, 0, "0 or more")


def seconds(value: str) -> float:
    """argparse type for a delay: 0 or more seconds. `time.sleep` raises on a
    negative value, so `--delay -1` used to crash after page 1."""
    return _number(value, float, 0.0, "0 or more seconds")


def pagination_is_addressable(url: str) -> bool:
    """Whether page N of this listing can be fetched without walking to it.

    Whether pages are addressable is asked PER URL rather than per
    site, and on Wellfound the two page kinds give OPPOSITE answers:

      * a `/role/…` landing page takes `?page=N` and honours it. Measured
        2026-09-17: `?page=2` on /role/r/software-engineer returned 45 job
        rows sharing exactly one id with page 1's 37, and the response
        stated `{"page":2}` in its own Apollo cache key.
      * `/jobs` does NOT. `?page=2` on it does not fail and does not empty —
        it returns the identical 46 job ids as page 1. A `page_url()` used
        unconditionally there would fetch that, find no new sku, conclude the
        listing was exhausted, and report a COMPLETE run holding page 1.

    So this returns False for the feed, the engines fall back to one page,
    and `--concurrency > 1` is refused with that reason: a page that has no
    address cannot be handed to a worker.
    """
    return route_of(url or "") in ("role_remote", "role_location", "role_plain")


def pages_to_plan(pages_requested: int, pages_available: Optional[int]) -> int:
    """How many pages a run may ask for, given what page 1 reported.

    Wellfound states `pageCount` in every landing response, so the end of the
    listing is known from page 1 rather than discovered by walking off it —
    which matters here because walking off it does not error. `?page=48` of a
    47-page listing answers HTTP 200 carrying page 1 AGAIN, so a run that
    overshot would re-collect the same rows and report success.

    There is no hard ceiling on top of the site's own figure: unlike the
    sibling repo this was ported from, Wellfound does not cap what it will
    serve — 47 pages really is all 923 companies. A cap here would silently
    truncate a legitimate run.
    """
    wanted = max(1, int(pages_requested or 1))
    if pages_available and pages_available > 0:
        return min(wanted, int(pages_available))
    return wanted


def concurrency_limit(cdp_endpoint: Optional[str]) -> Optional[int]:
    """1 when workers would collide, else None for "no limit imposed here".

    The Scraping Browser API allows ONE live connection per profile, so N
    workers sharing a `pid` collide with `profile_locked`. Several `pid`s,
    one run each, is the way to parallelise that path.
    """
    return 1 if cdp_endpoint else None
