"""page_flow.py — the retry / solve / blocked decision, as DATA.

Shared by all three browser engines and the HTTP path so they cannot
quietly disagree about whether a response is worth retrying, worth paying
a solver for, or worth reporting as a block. Three copies of that triage
drift, and the drift is silent: one engine reporting exit 3 where its twin
reports exit 0 on the same account.

Policy and pure algorithms only. No JavaScript crosses this boundary —
Selenium's `execute_script` takes a function BODY with an explicit
`return` while Playwright and pyppeteer take `() => expr`, so a shared
module that carried a snippet would acquire one driver's dialect. What the
engines share here is a NAME for an operation and a decision about it.

TikTok answers a request six ways
---------------------------------
and five of them want a different response, which is why this module
exists on this site at all:

    content            a profile page with an account object on it
    user_unavailable   TikTok returned no account (a real answer)
    empty_success      HTTP 200, content-length 0 — a REFUSAL
    challenge          the slide-puzzle interstitial
    error              an HTTP status the site gave us
    parse_error        a page the site served that we failed to read — OUR bug

`empty_success` is the one a naive engine gets wrong, and it is the
defining shape of this site. Measured 2026-09-22 on the video-feed route
next door, every way it was asked — headless Chromium, headful Chromium, a
Windows user agent, after accepting the EU cookie consent, and through a
residential exit in Peru — TikTok answered:

    HTTP 200   content-type: application/json   content-length: 0

No status to key on, no body to parse, no marker to match. Folded into
"empty" it reads as an account with no data and the run reports exit 0;
named separately it rotates an exit and reports exit 3. This repo's own
route has not produced it, and it is carried anyway, because the cost of
being wrong about it is a silent wrong answer.

`user_unavailable` is the other one. TikTok reports statusCode 10221 and
the message "user banned" for a handle that never existed as well as for
one that was banned, so it is a real answer to the question asked — not a
block. Reporting it as one sends a user rotating proxies over an account
that is not there.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from product_parser import (STATE_CHALLENGE, STATE_CONTENT,
                            STATE_EMPTY_SUCCESS, STATE_ERROR,
                            STATE_PARSE_ERROR, STATE_UNKNOWN,
                            STATE_WAF_CHALLENGE,
                            STATE_USER_UNAVAILABLE, detect_page_state)

# ---------------------------------------------------------------------------
# Readiness — for the browser engines only
# ---------------------------------------------------------------------------
#
# The browser engines do not read the account out of the DOM — it is in
# the page SOURCE, in a script tag, server-rendered. So what they wait for
# is not a rendered grid but a document that has finished arriving. That is
# a much weaker requirement than most repos in this family have, and
# stating it here keeps an engine from growing a tile-counting wait that
# measures the wrong thing.
#
# A run that never sees the selector still works — the payload is parsed
# out of the source either way — so this is a wait, not a gate.
#
# `[data-e2e="user-page"]` is the profile header's own test id, which is a
# build artefact and therefore listed AFTER nothing more durable exists;
# `body` is the floor that always matches, which is why the minimum is 1
# rather than the >1 the family requires of a LISTING. A profile page
# holds exactly one account, so "more than one match" is not a thing that
# can be waited for here.
READY_SELECTOR = '[data-e2e="user-page"], [data-e2e="user-title"], body'
MIN_CARD_MATCHES = 1
CONTENT_TIMEOUT_MS = 30_000
READY_POLL_MS = 500


def ready_selector(mode: str = "profile") -> str:
    return READY_SELECTOR


def min_matches(mode: str = "profile") -> int:
    return MIN_CARD_MATCHES


def content_timeout_ms(mode: str = "profile") -> int:
    return CONTENT_TIMEOUT_MS


def wait_for_count(count: Callable[[str], int], selector: str, minimum: int,
                   timeout_ms: int = CONTENT_TIMEOUT_MS,
                   poll_ms: int = READY_POLL_MS) -> int:
    """Poll `count(selector)` until it reaches `minimum`, or time out.

    The caller passes a counting primitive rather than a snippet, and the
    primitive must be a protocol call — `querySelectorAll` through the
    driver — never an evaluated STRING. A site whose
    Content-Security-Policy lacks `unsafe-eval` kills
    `wait_for_function`-style string evaluation. TikTok's CSP does carry
    `unsafe-eval` today (measured 2026-09-22), so this is insurance rather
    than a workaround — and it is also the only spelling all three drivers
    share, since Selenium takes a function BODY where the other two take
    `() => expr`.
    """
    deadline = time.time() + (timeout_ms / 1000.0)
    seen = 0
    while True:
        try:
            seen = count(selector)
        except Exception:
            seen = 0
        if seen >= minimum or time.time() >= deadline:
            return seen
        time.sleep(poll_ms / 1000.0)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify(html, status: Optional[int] = None, url: str = "",
             mode: str = "profile") -> str:
    """Name what TikTok answered with. See product_parser.detect_page_state.

    The argument ORDER is the contract: every caller writes
    `classify(html, status, url)`. A sibling repo
    had two engines that called `classify(html, url=...)` against a callee
    taking `status` second, and both crashed on their FIRST fetch —
    invisible to import, `--help`, `compileall` and four hundred green
    offline assertions, because none of those calls a function the way a
    live run does. `smoke_test.py` binds every call site against this
    signature for exactly that reason.

    `status` is threaded through rather than dropped. It is the only
    signal a 503 or a 403 gives, and a classifier that never receives it
    has to guess from a body that may not exist — which, on this site, is
    literally the case: the refusal that matters here HAS no body.
    """
    return detect_page_state(html, status, url)


STATE_POLICY = {
    # A profile page with an account on it.
    STATE_CONTENT: {"retry": False, "solve": False, "blocked": False,
                    "parse": True},
    # TikTok returned no account. A real, complete answer to the question
    # asked — EXIT_NO_PRODUCTS, never EXIT_BLOCKED. Retrying it re-asks a
    # question the site has already answered, and rotating exits over it
    # spends a proxy budget on an account that is not there.
    #
    # `parse` is False because there is nothing to parse; the engine reads
    # the state itself to distinguish this from a failure when it counts
    # pages.
    STATE_USER_UNAVAILABLE: {"retry": False, "solve": False, "blocked": False,
                             "parse": False},
    # HTTP 200 with a zero-length body — TikTok's silent refusal.
    #
    # `retry` True and `blocked` True: a different exit is the only thing
    # that has ever been worth trying against it. `solve` is False, and
    # that is the measured part rather than a default — this shape carries
    # no widget, no sitekey and no challenge page, so there is nothing for
    # a solver to solve and paying for one would be buying a request the
    # API will reject (detected != paying).
    STATE_EMPTY_SUCCESS: {"retry": True, "solve": False, "blocked": True,
                          "parse": False},
    # The slide-puzzle interstitial. `solve` is False: this repo implements
    # no solver for ByteDance's puzzle, so a solve on this state would be a
    # promise with nothing behind it. `retry` and `blocked` are True: a
    # different profile is what has actually worked (tiktok-shop-scraper).
    STATE_CHALLENGE: {"retry": True, "solve": False, "blocked": True,
                      "parse": False},
    # TikTok's WAF interstitial: HTTP 200, 1,462 bytes, "Please wait...",
    # carrying a JavaScript challenge.
    #
    # `blocked` True is what makes `--transport auto` do the right thing:
    # the engines switch to a browser for any state that counts as
    # blocked, and a browser is the measured remedy — 3 of 3 cleared on
    # the very exits that refused a plain HTTP client.
    #
    # `solve` False, and that is measured rather than defaulted: the page
    # carries no widget, no sitekey and no captcha of any kind, so paying
    # a solver would buy a request the API cannot fulfil (detected
    # != paying).
    STATE_WAF_CHALLENGE: {"retry": True, "solve": False, "blocked": True,
                          "parse": False},
    # An HTTP error that is not a recognised refusal — a 500, a gateway's
    # own page, a truncated body. A wait, not a spend.
    STATE_ERROR: {"retry": True, "solve": False, "blocked": False,
                  "parse": False},
    # A page the site plainly served, with its own assets all over it, that
    # this parser failed to read. OUR bug, and it gets its own name so it
    # cannot be reported as "no such account" — which would send the
    # reader to check the handle instead of the parser.
    # One retry in case a response was truncated, and always worth a dump.
    STATE_PARSE_ERROR: {"retry": True, "solve": False, "blocked": False,
                        "parse": False},
    # Neither the site nor a recognised refusal — a proxy's own response,
    # Chromium's network-error page (which carries the site's hostname in
    # its title and would fool a title check), an upstream error.
    STATE_UNKNOWN: {"retry": True, "solve": False, "blocked": False,
                    "parse": False},
}


def should_retry(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY[STATE_UNKNOWN])["retry"]


def should_solve(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY[STATE_UNKNOWN])["solve"]


def counts_as_blocked(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY[STATE_UNKNOWN])["blocked"]


def should_parse(state: str) -> bool:
    return STATE_POLICY.get(state, STATE_POLICY[STATE_UNKNOWN])["parse"]


# ---------------------------------------------------------------------------
# One record per account asked for
# ---------------------------------------------------------------------------
#
# A run of N `--url` handles used to end with its per-account story only in
# the log: which account moved to another exit, how many times, and whether
# its fetch ended with data, no account, a refusal, a parse failure or no
# worker at all. The sidecar named only `pages_failed` (by NUMBER) and
# `handles_unavailable` (by name), so "what happened to @zachking" was a
# question you answered by reading a log afterwards.
#
# These records answer it in the sidecar, in `--url` order. The STATUS
# vocabulary is deliberately small and each name is a fact about the account
# rather than about the machinery:
#
#   ok                rows were read from the page
#   user_unavailable  TikTok returned no account (banned or never existed —
#                     one answer, and this repo does not tell them apart)
#   blocked           the page ended refused (challenge, WAF, zero-byte 200)
#   parse_error       TikTok served a page this parser could not read — OUR bug
#   failed            the content was never obtained (transport, 5xx, unknown)
#   not_fetched       NO worker reached it — a crashed worker, not a site answer
#
# `user_unavailable` is the one that must never be folded into a failure: it
# is the site ANSWERING the question asked, and the run's `handles_unavailable`
# list and exit code 4 depend on that distinction.
HANDLE_STATUS_OK = "ok"
HANDLE_STATUS_UNAVAILABLE = STATE_USER_UNAVAILABLE
HANDLE_STATUS_BLOCKED = "blocked"
HANDLE_STATUS_PARSE_ERROR = STATE_PARSE_ERROR
HANDLE_STATUS_FAILED = "failed"
HANDLE_STATUS_NOT_FETCHED = "not_fetched"


def handle_status(outcome) -> str:
    """Name one account's final outcome from its PageOutcome.

    Duck-typed rather than importing an engine's PageOutcome: the three
    engines each define that dataclass, and this module is what keeps their
    TRIAGE from drifting. Reading it here, once, is what stops the three
    sidecars acquiring three vocabularies for the same five facts.
    """
    if outcome is None or not getattr(outcome, "attempted", True):
        # Nothing reached this account. Distinct from "the fetch failed":
        # a worker that never started says nothing about TikTok or the exit.
        return HANDLE_STATUS_NOT_FETCHED
    if getattr(outcome, "rows", None):
        return HANDLE_STATUS_OK
    state = getattr(outcome, "state", STATE_UNKNOWN)
    if state == STATE_USER_UNAVAILABLE:
        return HANDLE_STATUS_UNAVAILABLE
    if state == STATE_PARSE_ERROR:
        return HANDLE_STATUS_PARSE_ERROR
    if getattr(outcome, "blocked", False):
        return HANDLE_STATUS_BLOCKED
    return HANDLE_STATUS_FAILED


def handle_reason(outcome, status: str) -> Optional[str]:
    """Why a non-successful account ended the way it did, or None.

    `user_unavailable` is not a failure — it is the site's answer — so it
    carries no reason. Everything else says what was seen: the state the
    classifier named, the HTTP status where there was one, and the error
    text the engine recorded when there was one.
    """
    if status in (HANDLE_STATUS_OK, HANDLE_STATUS_UNAVAILABLE):
        return None
    if status == HANDLE_STATUS_NOT_FETCHED:
        return str(getattr(outcome, "error", None) or
                   "no worker could fetch it (see the log)")
    error = getattr(outcome, "error", None)
    if error:
        return str(error)
    detail = "state: %s" % getattr(outcome, "state", STATE_UNKNOWN)
    http_status = getattr(outcome, "status", None)
    if http_status is not None:
        detail += ", http %s" % http_status
    return detail


def make_handle_record(handle: str, status: str, rotations: int = 0,
                       reason: Optional[str] = None) -> Dict[str, Any]:
    """Build one record from its facts.

    The single place the record's SHAPE is written. Every engine builds its
    records from a `PageOutcome` (see `handle_record`), and the one
    single-account path (`scraper_api_client.py`) has no outcome to read —
    it knows the facts directly. Going through this constructor is what
    stops that path growing a second, subtly different record shape, which
    is the drift this family treats as a defect rather than a style choice.
    """
    rotations = max(0, int(rotations or 0))
    return {
        "handle": handle,
        "status": status,
        "rotated": rotations > 0,
        "rotations": rotations,
        "reason": reason,
    }


def handle_record(handle: str, outcome) -> Dict[str, Any]:
    """The sidecar record for one account asked for, in `--url` order.

    `rotations` counts EXIT SWITCHES, not attempts: the engines read it from
    their pool's own counter, which only moves when `advance()` actually
    lands on a different exit (a one-exit pool refuses to move). A retry at
    the same exit, an HTTP -> browser switch, and a browser rebuild that
    stays on the same exit are all correctly zero. With no pool at all the
    count is zero by construction.
    """
    status = handle_status(outcome)
    return make_handle_record(
        handle, status,
        rotations=int(getattr(outcome, "rotations", 0) or 0),
        reason=handle_reason(outcome, status))


def handle_records(handles: List[str], outcomes) -> List[Dict[str, Any]]:
    """One record per handle, in the order `--url` named them.

    Indexed rather than zipped for a reason: a missing outcome must still
    produce a record (`not_fetched`), because the whole point is that every
    account asked for is accounted for. `zip` would silently shorten the
    list, which is the defect this feature exists to end.
    """
    out = []
    for i, handle in enumerate(handles):
        outcome = outcomes[i] if i < len(outcomes) else None
        out.append(handle_record(handle, outcome))
    return out


# Whether a blocked page is worth re-fetching at all. CONSULTED by the
# engines rather than merely documented — setting it False really does stop
# the retry loop. (A policy constant nothing reads is the
# same defect as dead code, and this family shipped one for months.)
RETRY_ON_BLOCKED = True

# Retries to spend on a refusal when there is no pool to rotate through.
# Without a pool every retry leaves from the same address that was just
# refused, so more than one is repetition rather than a second attempt.
BLOCK_RETRIES_WITHOUT_POOL = 1

# ---------------------------------------------------------------------------
# The solve budget
# ---------------------------------------------------------------------------
#
# One paid solve per page. This constant has
# read like an enforced limit in every repo in this family and was not one:
# every engine calls the captcha handler TWICE per attempt — once before
# the response is classified, so a challenge is cleared before anything is
# judged, and once after, for the state that says the page really is gated
# — and only the second call was counted. Measured from an address where a
# challenge rendered on every fetch, one page bought THREE solves.
#
# So the budget is not a number engines are trusted to respect. It is a
# function both call sites go through, and `smoke_test.py` asserts that the
# number of call sites equals the number of guards equals the number of
# increments.
SOLVES_PER_PAGE = 1


class SolveBudget:
    """One page's paid-solve allowance, shared by both call sites.

    `spend()` returns True at most SOLVES_PER_PAGE times and counts the
    spend itself, so neither caller can forget to.
    """

    def __init__(self, limit: int = SOLVES_PER_PAGE):
        self.limit = max(0, int(limit))
        self.spent = 0

    def may_spend(self) -> bool:
        return self.spent < self.limit

    def spend(self) -> bool:
        if not self.may_spend():
            return False
        self.spent += 1
        return True

    def __repr__(self) -> str:                # pragma: no cover - debugging
        return f"SolveBudget(spent={self.spent}/{self.limit})"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def pagination_is_addressable(url: str = "", mode: str = "profile") -> bool:
    """Whether page N of this run can be fetched without walking to it.

    Ask this per ROUTE rather than per site. On this
    route the honest answer is that the question does not arise: a TikTok
    profile has exactly ONE page. There is no page 2 to address, walk to,
    or construct.

    True is nonetheless the right return, and the reason is worth stating
    because the opposite reading is tempting. What a "page" means to this
    engine is one ACCOUNT, and every account has a real, independent
    address — `https://www.tiktok.com/@handle`. That is what the
    concurrency machinery needs, and what makes the sidecar's "which pages
    failed by number" mean something a reader can act on.

    Deliberately NOT true of the neighbouring route: a profile's video
    feed is a cursor chain, and it is also refused, which is why it lives
    in tiktok-video-scraper and not behind a flag here.
    """
    return True


def pages_to_plan(pages_requested: int, pages_available: Optional[int]) -> int:
    """How many pages a run may ask for, given what is known to exist.

    Here `pages_available` is the number of handles `--url` named, and
    capping at it matters: asking for the eleventh of ten accounts is not
    an empty page, it is an index error waiting to happen.

    A profile page states no page count of its own, because it has none.
    """
    wanted = max(1, int(pages_requested or 1))
    if pages_available and pages_available > 0:
        return min(wanted, int(pages_available))
    return wanted


def non_negative_int(text: str) -> int:
    """argparse type for a count that may be 0 but never negative.

    `--retries` counts EXTRA attempts, so 0 is legal (one fetch, no retry).
    A negative value used to be accepted and silently read as 0; it is now
    refused up front as a usage error (exit 2) naming the flag.
    """
    import argparse
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {text!r}")
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {value}")
    return value


def positive_int(text: str) -> int:
    """argparse type for a count that must be at least 1 (pages, workers)."""
    import argparse
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {text!r}")
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, got {value}")
    return value


def non_negative_float(text: str) -> float:
    """argparse type for a delay in seconds: 0 or more, and finite.

    A negative delay reached `time.sleep` and crashed the run mid-way
    (exit 1) instead of being refused as a usage error.
    """
    import argparse
    import math
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid float value: {text!r}")
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, got {text}")
    return value


def concurrency_limit(cdp_endpoint: Optional[str]) -> Optional[int]:
    """1 when workers would collide, else None for "no limit imposed here".

    The Scraping Browser API allows ONE live connection per profile, so N
    workers sharing a `pid` collide with `profile_locked`. Several `pid`s,
    one run each, is the way to parallelise that path.
    """
    return 1 if cdp_endpoint else None


def concurrency_for_mode(mode: str, concurrency: int) -> int:
    """Workers this mode can actually use.

    Every mode here — there is one — fetches independently addressed
    accounts, so nothing needs clamping to 1 the way a token chain does.
    The real cap is the number of handles, and the engine applies it,
    because this module does not know how many were asked for.
    """
    return max(1, int(concurrency or 1))


def sample_share(collected: int, total: Optional[int]) -> Optional[float]:
    """What fraction of the accounts asked for a run actually holds.

    "Complete" and "exhaustive" are different words, and a
    sidecar that says only the first is lying by omission. The distinction
    is milder on this route than on a capped search listing — a profile run
    asks for N accounts and either gets them or does not — but the number
    still belongs in the sidecar, because a run of 50 handles that holds 47
    rows and says "complete" is answering a different question from the one
    it was asked.
    """
    if not total or total <= 0 or collected < 0:
        return None
    return round(100.0 * collected / total, 4)
