"""
page_flow.py
------------
The retry / solve / blocked decision, as DATA rather than as three copies of
an if-chain.

Mercor answers a request five ways, and four of them want a different
response:

    a page whose __NEXT_DATA__ holds records         -> parse
    a page whose __NEXT_DATA__ holds none            -> parse, it is an answer
    HTTP 404 or 410, or the site's own not-found copy -> stop, it is not a block
    HTTP 403 / HTTP 429                              -> blocked / throttled
    a page we could not find a payload in            -> parse_error, dump it
    something else entirely                          -> wait, then retry

Three copies of that triage across three engines would drift, and the drift
would be silent — one engine reporting exit 3 where its twin reports exit 0
on the same response.

There is no fifth state for a challenge on this site because, measured on
2026-09-18, Mercor rendered none: eighteen candidate vendor markers counted
across seven captures, all zero, and identical 200s from `curl`, from
`python-requests` and from an empty User-Agent. `blocked` is in the policy
table anyway — an ungated site today is not an ungated site forever, and a
run should be able to say "blocked" rather than "empty" on the day that
changes.

Nothing here imports a browser, and **no JavaScript crosses this boundary**:
Selenium's `execute_script` takes a function BODY with an explicit `return`
while Playwright and pyppeteer take `() => expr`, so a shared snippet would
quietly acquire one driver's dialect. The callbacks below are named for the
OPERATION instead, and each engine spells it in its own dialect.
"""

import logging
from typing import Callable, Optional

from output_writer import COMPLETE_STOP_REASONS
from product_parser import (detect_bot_challenge,  # noqa: F401
                            detect_page_state, route_of)

log = logging.getLogger("page_flow")


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

# How many job links mean "this response is the marketplace index".
#
# `> 1` on purpose: waiting for ONE match resolves on
# something unrelated — a nav link, a footer — long before the grid is really
# there.
#
# Four, and the ceiling on this number is lower than it looks. `/explore`
# holds 390 records in its payload and paints only **15** anchors into the
# served markup: the grid is virtualised, so the DOM never shows the whole
# catalogue however long anything waits for it. A readiness threshold
# anywhere near the record count would time out on every single run.
#
# Which is the other half of why this is a readiness signal ONLY. The rows
# come out of `__NEXT_DATA__`, which is complete in the first response, so a
# page whose grid has not painted at all still parses to all 390 rows — and
# the engines therefore do not gate parsing on this.
MIN_CARD_MATCHES = 4

# Anchored on a URL pattern, never a CSS class: Mercor's classes are
# build-generated Tailwind strings that churn on every deploy, while
# `/jobs/list_…` is a contract with search engines.
#
# TWO spellings, and the second one is the whole reason this selector is
# not the obvious one-liner. **Hydration rewrites every job anchor.**
# Mercor server-renders `href="/jobs/list_{id}/{slug}?returnPath=/explore"`
# and React then replaces it with `href="/explore?listingId={id}"`, a
# same-page modal route. So, measured in a live headless Chromium on
# 2026-09-18:
#
#     a[href*="/jobs/list_"]        15 in the served HTML, 0 in the live DOM
#     a[href*="listingId=list_"]     0 in the served HTML, 16 in the live DOM
#     the two together              16 at domcontentloaded and every poll after
#
# The single-spelling version is the kind of mistake that does not look
# like one: the rows still come out right, because they are read from
# `__NEXT_DATA__` and not from the DOM. What it costs is invisible in the
# output and expensive everywhere else — the readiness wait can never be
# satisfied, so every page burns its full timeout, and the captcha gate
# sees "zero content on this page" and decides a detected challenge is
# BLOCKING. On the first live run of this engine that turned mercor's
# background reCAPTCHA v3 into "attempting to solve" on a page holding all
# 390 rows; with an API key set, that is a charge per page for nothing
# (detected is not blocking, and never pay for a challenge that is not
# stopping you).
#
# Anything anchored to the DOM on this site needs checking in a real
# browser and not in a capture. The capture is the pre-hydration document.
READY_SELECTOR_LISTING = ('a[href*="/jobs/list_"], '
                          'a[href*="listingId=list_"]')

# A detail page and the careers page each state their heading server-side,
# and `h1` was confirmed present on both in a live browser (1 each,
# 2026-09-18).
#
# The careers page gets `h1` rather than an anchor selector because it
# renders no job links at all that a selector could wait on: its 108 Ashby
# URLs live in the payload, and after hydration the live DOM still held
# `a[href*="ashbyhq.com"]` = 0. Waiting on those would wait forever.
READY_SELECTOR_JOB = "h1"
READY_SELECTOR_CAREERS = "h1"

CONTENT_TIMEOUT_MS = 45_000
CONTENT_TIMEOUT_MS_JOB = 30_000


def ready_selector(mode: str) -> str:
    if mode == "job":
        return READY_SELECTOR_JOB
    if mode == "careers":
        return READY_SELECTOR_CAREERS
    return READY_SELECTOR_LISTING


def min_matches(mode: str) -> int:
    return 1 if mode in ("job", "careers") else MIN_CARD_MATCHES


def content_timeout_ms(mode: str) -> int:
    return CONTENT_TIMEOUT_MS_JOB if mode in ("job", "careers") else CONTENT_TIMEOUT_MS


# How long to keep polling for an anchor, and how often.
#
# Polled through `count(selector)` — a callback each engine implements with
# its own `querySelectorAll` call — and NEVER by handing the browser a string
# to evaluate. A site whose Content-Security-Policy omits
# `unsafe-eval` kills `wait_for_function` with an `EvalError` and takes the
# run down with exit 1, on the site's most obvious URL. Mercor has not been
# measured for that, and the cheap habit costs nothing on a site that would
# have allowed it.
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
             url: str = "", mode: str = "listings") -> str:
    """Name what Mercor answered with. See product_parser.detect_page_state.

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
    # A page whose payload holds records.
    "content":     {"retry": False, "solve": False, "blocked": False, "parse": True},
    # A page Mercor served whose payload holds no records. The site answered
    # exactly what was asked and there is nothing in it — a real answer, and
    # EXIT_NO_PRODUCTS rather than EXIT_BLOCKED. Reporting it as blocked
    # sends a user hunting for a proxy problem that is not there.
    "empty":       {"retry": False, "solve": False, "blocked": False, "parse": True},
    # Never yet observed on this site. `solve` is True so that a challenge
    # appearing tomorrow is met with the tools this repo already has rather
    # than with a code change; `retry` is True because on every other site
    # in this family a different exit clears a refusal far more cheaply than
    # a solve does.
    "blocked":     {"retry": True,  "solve": True,  "blocked": True,  "parse": False},
    # HTTP 429. Retried with a growing pause (see `throttle_pause`) within
    # the same bounded block-retry budget, never solved, and if it persists
    # it is a refusal: exit 3, or 6 after earlier rows. Not "empty" and not
    # "never reached" — the site answered, and the answer was "not now".
    "throttled":   {"retry": True,  "solve": False, "blocked": True,  "parse": False},
    # A substantial page with no `__NEXT_DATA__` we could read. NOT "zero
    # jobs": a served page that parses to nothing is OUR bug, and reporting
    # it as an empty index sends the reader to check the URL instead of the
    # parser. Worth one retry in case the document was
    # caught mid-swap, and always worth a dump.
    "parse_error": {"retry": True,  "solve": False, "blocked": False, "parse": False},
    # A 404. Retrying an address that does not exist is pure waste, and it
    # is not a block — saying so stops a user rotating proxies over a
    # delisted job. This state is reachable in ordinary use here: `--mode
    # job` works from an enumeration that can outlive a listing, so a job
    # taken down between the sitemap being fetched and its page being read
    # lands exactly here.
    "not_found":   {"retry": False, "solve": False, "blocked": False, "parse": False},
    # Something that is neither the site nor a recognised refusal — an
    # upstream error page, a proxy's own response, Chromium's network-error
    # page. A wait, not a spend.
    "unknown":     {"retry": True,  "solve": False, "blocked": False, "parse": False},
}


def should_retry(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY["unknown"])["retry"]


def should_solve(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY["unknown"])["solve"]


def counts_as_blocked(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY["unknown"])["blocked"]


def should_parse(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY["unknown"])["parse"]


# Numeric flags and the smallest value each can honestly take. A negative
# delay or page count is not a request anyone means: `--pages 0` plans no
# page at all and `--delay -1` reaches `time.sleep` as a ValueError deep in
# the run. Refused at parse time, naming the flag, in every engine.
# (`--retries` is validated on its own, because it counts ATTEMPTS.)
NUMERIC_FLAG_FLOORS = (
    ("pages", "--pages", 1),
    ("concurrency", "--concurrency", 1),
    ("delay", "--delay", 0),
    ("retry_delay", "--retry-delay", 0),
    ("proxy_block_retries", "--proxy-block-retries", 0),
)


def numeric_flag_error(args):
    """The usage error for the first numeric flag below its floor, or None."""
    for attr, flag, floor in NUMERIC_FLAG_FLOORS:
        value = getattr(args, attr, None)
        if value is not None and value < floor:
            return "%s must be at least %s (got %s)" % (flag, floor, value)
    return None


# Whether a blocked page is worth re-fetching at all.
#
# True, and CONSULTED rather than merely documented — the engines read it,
# so setting it False really does stop the retry loop. (A sibling repo
# carried this constant with a paragraph of justification and no reader,
# which is the same defect as dead code that looks load-bearing.)
#
# True is the cautious setting rather than a measured one here, and the
# honest statement of the evidence is that there is none: Mercor has never
# refused this scraper, so no retry has ever been exercised against a real
# refusal. On every site in this family that DOES refuse, a retry that moves
# the address is the retry worth making.
RETRY_ON_BLOCKED = True

# How many times to re-fetch a blocked page when there is no proxy pool to
# rotate into.
#
# One. Without a pool every retry leaves from the same address, and an
# address-level refusal answers a second identical request identically. WITH
# a pool the engines retry once per remaining exit instead, because there the
# retry changes the one variable the refusal would depend on.
BLOCK_RETRIES_WITHOUT_POOL = 1

# At most one solve per page. A challenge that survives a solved token is not
# a challenge this run can pass, and a second solve is a second charge for
# the same answer.
SOLVES_PER_PAGE = 1


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination_is_addressable(url: str) -> bool:
    """Whether page N of this run can be fetched without walking to it.

    Ask this PER URL rather than per site: on
    Mercor the routes give opposite answers for opposite reasons:

      * `/explore` is NOT addressable, because it has no page 2 at all.
        Measured 2026-09-18: `?page=2`, `?limit=10`, `?offset=100` and
        `?domain=Finance` each returned a byte-identical payload holding
        the same 390 records. The route ships the whole index in one
        response. A `page_url()` used here would fetch that payload again,
        find no new sku, conclude the index was exhausted and report a
        COMPLETE multi-page run holding page one several times.
      * `/careers` is not addressable either, for the same reason: 108
        records in one response and no second page.
      * A JOB URL is addressable, and this is where the word earns its
        keep. In `--mode job` a "page" is one job detail page, and those
        addresses are not guessed from a convention — they are read from
        `/sitemap.xml` and from the `/explore` payload before the run
        starts. Every one is a real, independent URL, which is precisely
        what the concurrency machinery needs and what makes the sidecar's
        "which pages failed by number" mean something.

    So a `listings` or `careers` run plans one page and says why, and a
    `job` run may use every worker it is given.
    """
    return route_of(url or "") == "job"


def a_page_without_rows_ends_the_run(mode: str) -> bool:
    """Whether a served page that adds no new rows means "there is no more".

    "This page added no new sku" is the terminating
    condition for a LISTING, where pages are slices of ONE result and a page
    that adds nothing means the slices have run out (or are looping back).

    It is the WRONG condition for an enumerated queue, and `--mode job` is
    one: every page is an independent address read from the sitemap, so one
    page adding nothing says nothing about the next. Mercor makes that
    routine rather than hypothetical, because the enumeration is built
    before any of its addresses is fetched, so a listing withdrawn in
    between is an ordinary event. Reproduced on the audited commit with
    three queued addresses, the second a 404: ONE row, `status: complete`,
    exit 0, `stop_reason: no_new_products`, the third address never fetched.

    A 404 is the end of ONE URL, not of the list. This returns False for
    `job`, and True for the modes that read slices of one result — which on
    this site never reach a second page, so in practice it is a statement
    of intent that keeps the next paginated mode from inheriting the bug.
    """
    return mode != "job"


ENUMERATION_INCOMPLETE = "enumeration_incomplete"
PARSER_FOUND_NOTHING = "parser_found_nothing"


# A served page (2xx, or no status to read) that ended without job data and
# without the site's own empty answer. `parse_error` is a page we could not
# read; `unknown` is one that never turned into the payload after its
# retries and wait. Neither is "zero jobs": only `empty` — the payload's own
# container, present and holding nothing — is the site saying so.
UNREADABLE_STATES = ("parse_error", "unknown")


def account_for_pages(outcomes):
    """(read, failed page numbers, unreadable page numbers) — one place.

    Three engines each computed `ok` and `failed` inline, and "ok" meant "no
    load failure and no block". That left a hole this closes: a page the
    site SERVED but this parser could not read (`parse_error`) was `ok`,
    counted as completed, and contributed nothing — so a run whose every
    page was unreadable had `pages_completed == pages_requested`, no failed
    pages, and `finish_run` took the zero rows for an empty catalogue
    (exit 4). In `--mode job` the same page simply vanished from a run that
    went on to report `complete`.

    An unreadable page is a FAILED page, by number (which pages, not how many,
    so the sidecar can say what is missing), so `finish_run` sees `not complete` and the
    zero-row case becomes exit 5 — "nothing was gathered, nothing can be
    concluded" — instead of exit 4's claim that the answer was nothing.
    """
    unreadable = sorted(o.page_num for o in outcomes
                        if o.ok and o.state in UNREADABLE_STATES)
    read = [o for o in outcomes if o.ok and o.state not in UNREADABLE_STATES]
    failed = sorted({o.page_num for o in outcomes if not o.ok}
                    | set(unreadable))
    return read, failed, unreadable



# The stop reason for a page the TARGET answered with a server error.
TARGET_SERVER_ERROR = "target_http_5xx"


def target_server_error(state: str, status) -> Optional[int]:
    """The status, when a page ended as a target-site HTTP error.

    Any non-2xx status that no other rule explains counts, not only a 5xx:
    an `empty` payload under HTTP 400 is not the site's empty result.

    `detect_page_state` calls a 5xx with no records `unknown`, and `unknown`
    is retried. When the retries are spent the page is still not the site's
    answer. A 503 says nothing about whether the job or the index holds
    anything, so it is content NOT obtained (exit 5, or 6 after earlier
    rows), never the empty result exit 4 claims. A 404 is not here: that is
    the site saying the address does not exist.
    """
    if (state in _UNANSWERED_STATES and isinstance(status, int)
            and not isinstance(status, bool) and not 200 <= status < 300):
        return status
    return None


# The stop reason for a page the target answered with a non-2xx status that
# no other rule explains (not 404/410, 403, 429 or 5xx): a 400, a 401, a
# 451. Content not obtained, exactly like a 5xx, but not retried — the
# classifier calls such a page `empty` or `parse_error` before it gets here.
TARGET_HTTP_ERROR = "target_http_error"

# States a non-2xx status turns into "content not obtained". `content`,
# `not_found`, `blocked` and `throttled` already explain themselves.
_UNANSWERED_STATES = ("unknown", "empty", "parse_error")


# The state, the `blocked_by` value and the stop reason for a page the
# target kept answering with HTTP 429.
THROTTLED = "throttled"

# The longest single pause before re-fetching a throttled page, in seconds.
MAX_THROTTLE_PAUSE_S = 60.0


def throttle_pause(retry_delay: float, block_attempt: int) -> float:
    """Seconds to wait before re-fetching a throttled page.

    Doubles with each block-retry attempt, starting at twice `--retry-delay`,
    and is capped at MAX_THROTTLE_PAUSE_S. The number of attempts is the
    engines' existing block-retry budget, so the wait is bounded too.
    """
    return min(MAX_THROTTLE_PAUSE_S,
               float(retry_delay) * (2 ** (int(block_attempt) + 1)))


def http_error_stop_reason(status: int) -> str:
    """`target_http_5xx` for a server error, `target_http_error` otherwise."""
    return TARGET_SERVER_ERROR if status >= 500 else TARGET_HTTP_ERROR


def failure_stop_reason(outcome) -> str:
    """Why a failed page ended the run, in the same words for every engine."""
    if outcome.load_failed:
        return "page_load_timeout"
    if getattr(outcome, "server_error", None) is not None:
        return http_error_stop_reason(outcome.server_error)
    if outcome.blocked_by == THROTTLED:
        return THROTTLED
    return f"blocked_{outcome.blocked_by}"


def target_http_errors(outcomes) -> dict:
    """{page number: target status} for every page that ended as a target
    HTTP error (a 5xx, or a non-2xx no other rule explains)."""
    return {str(o.page_num): o.server_error
            for o in sorted(outcomes, key=lambda o: o.page_num)
            if getattr(o, "server_error", None) is not None}

def reconcile_stop_reason(stop_reason: str,
                          enumeration_complete: Optional[bool],
                          unreadable_pages=()) -> str:
    """Do not let a run that knowingly saw only part of the picture say "complete".

    `enumeration_complete` is None outside `--mode job` (nothing was
    enumerated), True when both sources answered, False when one did not.
    `unreadable_pages` are pages the site served and the parser could not
    read (see `account_for_pages`).

    A run can fetch every address it was GIVEN and still be short, because
    the list it was given was a fallback, or because some pages parsed to
    nothing. Every stop reason the loop itself reaches (`completed`,
    `page_cap_reached`, …) describes the loop, and says nothing about either
    — so on its own it reads `complete` over rows from part of the catalogue.
    This overrides only a stop reason that was about to be reported as
    complete: a run that already failed for a worse reason (blocked, load
    failure) keeps that one, because it is the more useful thing to tell the
    caller.

    Unreadable pages win over an incomplete enumeration when both hold,
    because they name a defect in THIS code rather than a condition of the
    site; the sidecar still carries the enumeration failure beside it.

    Neither result is in COMPLETE_STOP_REASONS, so `finish_run` reports
    `partial` (exit 6) with the rows kept — or exit 5 with none — and
    `diff_runs.py`, which refuses a run that is not `complete`, will not
    compare it as a full snapshot.
    """
    if stop_reason in COMPLETE_STOP_REASONS:
        if unreadable_pages:
            return PARSER_FOUND_NOTHING
        if enumeration_complete is False:
            return ENUMERATION_INCOMPLETE
    return stop_reason


def pages_to_plan(pages_requested: int, pages_available: Optional[int]) -> int:
    """How many pages a run may ask for, given what the enumeration holds.

    Mercor states no total and no page count on any route, so unlike a site
    that hands over `totalPages` there is nothing to read off page 1. What
    `pages_available` carries instead depends on the mode, and both are
    facts rather than guesses:

      * `listings` and `careers`: 1, because the route has exactly one page.
      * `job`: the size of the enumeration — the union of `/sitemap.xml`
        and the `/explore` payload, 462 distinct listings on 2026-09-18.

    Capping at it matters in the `job` mode: asking for the 463rd job when
    the enumeration holds 462 is not an empty page, it is an IndexError
    waiting to happen, and there is no more catalogue to walk to.
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


def concurrency_for_mode(mode: str, concurrency: int) -> int:
    """Workers this mode can actually use.

    `listings` and `careers` fetch exactly one page, so any worker past the
    first would have nothing to do. Clamping here rather than letting the
    engine start idle threads keeps the run's own log honest about what it
    did — concurrency without a proxy pool
    is a faster way to get an address scored than to gather data, which is a
    poor trade for threads that fetch nothing.
    """
    if mode in ("listings", "careers"):
        return 1
    return max(1, int(concurrency or 1))


# ---------------------------------------------------------------------------
# User-facing text that three engines must say identically
# ---------------------------------------------------------------------------
# These were three hand-copied strings that had drifted into three different
# claims about the same flag, two of them inherited from other sites. One
# definition here makes that impossible, and `smoke_test.py` fails if an
# engine spells a flag's help any other way.
#
# Every sentence is about Mercor and was measured on 2026-09-18; none is
# carried from the repo this one was copied from.

SOLVE_CAPTCHA_HELP = (
    "when-blocked (default): only pay to solve a captcha if the content is "
    "not already readable. always: solve whenever one is detected. On this "
    "site that difference is real money: work.mercor.com loads an invisible "
    "reCAPTCHA Enterprise on every page and it has never blocked a fetch, so "
    "`always` buys a solve on every marketplace page to clear nothing. "
    "www.mercor.com (--mode careers) loads none. No challenge was served on "
    "any route on 2026-09-18; the solver exists for the day that changes.")

LOCALE_HELP = (
    "Browser locale (default en-US). It changes what the browser claims "
    "about itself and nothing about which listings are read: no route this "
    "scraper reads carries a locale segment or a per-country host.")

CONCURRENCY_NO_POOL_WARNING = (
    "--concurrency %d with no proxy pool: every worker leaves from the SAME "
    "address, which is N times the traffic from one place. Mercor served "
    "every request measured on 2026-09-18 from a bare datacentre address, so "
    "this is a courtesy to the site rather than a known risk to you. Pass "
    "--proxy-file to spread the load.")

RETRIES_MUST_BE_POSITIVE = (
    "--retries counts ATTEMPTS per page load, not repeats after the first, "
    "so it must be at least 1. With 0 the load loop never runs: nothing is "
    "fetched, the empty document the browser starts with is read, and the "
    "run then waits out its full readiness timeout and reports exit 4 — "
    "'this listing is empty' — for a page it never requested.")

# NO LIVE COUNT in any of the three below, on purpose (a number
# describing a living thing is paired with the command that produces it, or
# left out). They used to say "390 contract roles", "462 jobs" and "the 72
# listings the index does not show" — figures from 2026-09-18 that read as
# current, and by 2026-10-07 were 305, 306 and 1. The run itself measures
# them (sidecar: `records_in_payload`, `enumeration_sources`), and
# `smoke_test.py` fails on a count creeping back into a user-visible string.

MODE_HELP = (
    "listings (default): work.mercor.com/explore, the marketplace index, the "
    "whole of it in ONE response, with rates, domains, eligibility and slot "
    "counts; --pages does not apply, the route has no second page. job: one "
    "listing per page, enumerated from the sitemap AND the index, adding the "
    "company website, the company description, the spot counts and a "
    "currency; the only mode that reads listings the index does not show. "
    "--pages says how many (capped at what the enumeration holds) and "
    "--concurrency fetches them in parallel (Playwright only). careers: "
    "www.mercor.com/careers, Mercor's OWN salaried openings via Ashby — a "
    "different population with its own id space, so diff_runs.py will not "
    "compare it against the other two.")

LISTINGS_NOT_EXHAUSTIVE_NOTE = (
    "--mode listings fetches everything /explore serves, and /explore is not "
    "guaranteed to be everything Mercor publishes. How much it omits changes "
    "from day to day — large on 2026-09-18, almost nothing on 2026-10-07 — so "
    "--mode job, which reads the sitemap as well and records the size of the "
    "union in the sidecar (enumeration_sources), is how to find out.")

PAGES_IGNORED_WARNING = (
    "--pages %d is ignored in --mode %s: the route holds its whole result "
    "set in ONE response and honours no pagination parameter. --mode job is "
    "the mode that pages — there a page is one job, and --pages is capped at "
    "what the enumeration holds. The run status will say single_page_route.")
