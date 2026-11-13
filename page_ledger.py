"""
page_ledger.py
--------------
The per-page attribution record for one multi-page run, as DATA.

A multi-page run's worst failure mode is silent: the output file looks
complete while a middle page is missing, or one product is counted twice.
The JSON/CSV output only says how many rows survived; it cannot say WHICH
page each row came from, which pages were never tried, or whether a zero-row
page was an honest end-of-listing or a parser that broke. This module builds
the side document that answers those questions — `<out>.pages.json`, one
entry per requested page plus a run-level summary.

It deliberately imports NO browser driver and none of the engine modules:
everything here is plain functions over the engine's `PageOutcome` objects
(read by attribute, so any object carrying the same fields works), which is
what lets the offline suite drive every branch with self-made HTML and no
network. The engine owns fetching and retries; this module owns only the
bookkeeping afterwards, so the two cannot drift.

The six per-page statuses
-------------------------
    success        the page was fetched and parsed trustworthily. A page can
                   be `success` with zero parsed rows (a served, genuinely
                   empty grid) and with zero NEW rows (every sku already seen
                   on an earlier page) — neither is a failure.
    blocked        an edge refusal or an unsolved challenge page.
    load_failed    the navigation never produced a page (timeout, dead exit).
    not_found      the site answered that the address does not exist (404).
    parse_empty    the page was SERVED and links to products, but the parser
                   extracted zero rows — our bug, not an empty category.
    not_attempted  the page was planned but never dispatched. Never a failure:
                   the page was not tried, and saying otherwise would overstate
                   the damage. The reason says why it was skipped.

The merge invariant
-------------------
Dedupe is keyed on `sku` and applied in PAGE NUMBER order, never in the order
pages happened to finish (which is nondeterministic under concurrency). The
ledger's per-page `rows_new` are counted against that same ordered merge, so:

    sum(pages[*].rows_new) == the number of rows in the final output

The builder raises rather than emit a record that violates it — a ledger that
does not reconcile with the output is worse than none.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from output_writer import dedupe_by_key


# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------
# Short stable strings: they are persisted into <out>.pages.json and read by
# pipelines, so renaming one is a contract change, not a refactor.
STATUS_SUCCESS = "success"
STATUS_BLOCKED = "blocked"
STATUS_LOAD_FAILED = "load_failed"
STATUS_NOT_FOUND = "not_found"
STATUS_PARSE_EMPTY = "parse_empty"
STATUS_NOT_ATTEMPTED = "not_attempted"

# Every status that means the page did not yield a trustworthy answer. Kept
# in one place so the summary's failed-page list can never disagree with the
# per-page statuses it is summarising. This set is intentionally the same
# partition the engine's `PageOutcome.ok` draws: a page is a ledger failure
# exactly when the engine would not call it ok.
FAILURE_STATUSES = (STATUS_BLOCKED, STATUS_LOAD_FAILED,
                    STATUS_NOT_FOUND, STATUS_PARSE_EMPTY)


# Why a planned page was never dispatched. Only carried on
# STATUS_NOT_ATTEMPTED records; an attempted page's failure reason lives in
# `failure_reason` instead.
#
# The listing ended early: under concurrency a worker fetched a page with no
# rows and signalled the other workers to stop pulling from the queue, so the
# pages still queued were never sent. The sequential twin of this is the
# "no_new_products" stop.
REASON_LISTING_ENDED = "listing_ended"
# Planned away before fetching: page 1's own result-count says the listing
# does not stretch to the page number the run asked for.
REASON_SITE_RESULT_LIMIT = "site_result_limit"
# The sequential loop stopped after a failed page (or the concurrent run lost
# a worker) before this page's turn came.
REASON_RUN_STOPPED = "run_stopped"
REASON_WORKER_DIED = "worker_died"


def status_of(outcome) -> str:
    """Map one fetched page's `PageOutcome` to a ledger status.

    The branch order mirrors `PageOutcome.ok` and `_failure_reason` in the
    engine, restated as data so a ledger cannot invent a seventh outcome:
    transport first (there may be no document at all), then the site's own
    states, then the parser's.
    """
    if getattr(outcome, "load_failed", False):
        return STATUS_LOAD_FAILED
    state = getattr(outcome, "state", None)
    if state == "not_found":
        return STATUS_NOT_FOUND
    if state == "parse_failed":
        return STATUS_PARSE_EMPTY
    if getattr(outcome, "blocked_by", None) is not None or state in (
            "blocked", "captcha"):
        return STATUS_BLOCKED
    return STATUS_SUCCESS


def failure_reason_of(outcome) -> Optional[str]:
    """The machine-readable reason for a failed page, or None on a success.

    The strings deliberately match the engine's stop-reason vocabulary
    (`parser_found_nothing`, `not_found`, `page_load_timeout`,
    `blocked_<vendor>`) so a reader moving between the run metadata sidecar
    and this ledger does not have to translate two naming schemes.
    """
    status = status_of(outcome)
    if status == STATUS_SUCCESS or status == STATUS_NOT_ATTEMPTED:
        return None
    if status == STATUS_LOAD_FAILED:
        return "page_load_timeout"
    if status == STATUS_NOT_FOUND:
        return "not_found"
    if status == STATUS_PARSE_EMPTY:
        return "parser_found_nothing"
    # blocked
    blocked_by = getattr(outcome, "blocked_by", None)
    return ("blocked_" + str(blocked_by)) if blocked_by else "blocked"


# ---------------------------------------------------------------------------
# The authoritative merge
# ---------------------------------------------------------------------------
def merge_rows_in_page_order(outcomes: Sequence[Any],
                             key: str = "sku"
                             ) -> Tuple[List[Any], Dict[int, int]]:
    """Dedupe every fetched page's rows in PAGE NUMBER order.

    Returns `(rows, new_row_counts)` where `new_row_counts[page_num]` is how
    many of that page's rows survived as new — i.e. were not already claimed
    by an earlier page (or by a duplicate earlier on the same page). Rows
    carrying no key are always kept and counted as new, mirroring
    `output_writer.dedupe_by_key`.

    This is the single merge used by the engine for BOTH its output rows and
    the ledger, which is what makes `sum(new_row_counts.values()) ==
    len(rows)` structural rather than hoped-for. Sorting inside the function
    is the point of it: callers may hand over outcomes in worker-completion
    order and the result is still byte-for-byte the page-ordered one.
    """
    seen: Set[Any] = set()
    rows: List[Any] = []
    new_row_counts: Dict[int, int] = {}
    for outcome in sorted(outcomes, key=lambda o: o.page_num):
        fresh = dedupe_by_key(outcome.products, seen, key=key)
        new_row_counts[outcome.page_num] = len(fresh)
        rows.extend(fresh)
    return rows, new_row_counts


@dataclass
class PageRecord:
    """One page's attribution, before serialisation. The engine and tests
    build these through `build_pages_ledger`; the dataclass documents the
    persisted shape and gives the field list a single home."""
    page: int
    request_url: str
    final_url: Optional[str]
    rows_parsed: int
    rows_new: int
    status: str
    failure_reason: Optional[str] = None
    not_attempted_reason: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "page": self.page,
            "request_url": self.request_url,
            "final_url": self.final_url,
            "rows_parsed": self.rows_parsed,
            "rows_new": self.rows_new,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "not_attempted_reason": self.not_attempted_reason,
        }


def _attempted_record(outcome, new_row_counts: Dict[int, int]) -> PageRecord:
    status = status_of(outcome)
    return PageRecord(
        page=outcome.page_num,
        request_url=outcome.url,
        final_url=getattr(outcome, "final_url", None),
        rows_parsed=len(outcome.products),
        rows_new=new_row_counts.get(outcome.page_num, 0),
        status=status,
        failure_reason=failure_reason_of(outcome),
    )


def build_pages_ledger(*, outcomes: Sequence[Any],
                       new_row_counts: Dict[int, int],
                       requested_urls: Dict[int, str],
                       unattempted: Sequence[Tuple[int, str]],
                       pages_requested: int,
                       truncated_page_nums: Sequence[int],
                       stop_reason: str,
                       output_row_count: int) -> dict:
    """Assemble the full `<out>.pages.json` document.

    Parameters
    ----------
    outcomes:
        Every page that was actually fetched, in ANY order — concurrent runs
        hand them over in worker-completion order and the records are sorted
        by page number here.
    new_row_counts:
        `merge_rows_in_page_order`'s per-page new-row map.
    requested_urls:
        The URL planned for EVERY requested page number, including pages that
        were never dispatched. A missing entry is an engine bookkeeping bug
        and raises rather than being written as a blank.
    unattempted:
        `(page_num, reason)` for planned-but-never-dispatched pages, using the
        REASON_* constants.
    pages_requested:
        The run's own `--pages`. Records are emitted for exactly pages
        1..pages_requested.
    truncated_page_nums:
        Pages planned away because page 1's site-stated result count did not
        cover them. Also listed in `unattempted` with
        REASON_SITE_RESULT_LIMIT; this is the summary's own count of them.
    stop_reason:
        The run's final stop reason, echoed into the summary so the ledger is
        self-contained.
    output_row_count:
        How many rows the output file actually holds. Checked against the
        per-page `rows_new` total — a mismatch raises, because a ledger that
        does not reconcile with the output cannot be used to audit it.
    """
    if pages_requested < 1:
        raise ValueError("pages_requested must be >= 1, got %r"
                         % (pages_requested,))

    attempted = {o.page_num: o for o in outcomes}
    unattempted_map = dict(unattempted)
    truncated_set = set(truncated_page_nums)

    # Every requested page must be claimed by exactly one bucket. A page that
    # is neither fetched nor explicitly accounted-for would otherwise be
    # omitted from the record silently — the exact failure this ledger exists
    # to prevent — so this is loud.
    records: List[PageRecord] = []
    for page_num in range(1, pages_requested + 1):
        if page_num in attempted:
            records.append(_attempted_record(attempted[page_num],
                                             new_row_counts))
            continue
        if page_num not in unattempted_map:
            raise ValueError(
                "page %d was neither fetched nor listed as unattempted; the "
                "run's page bookkeeping has a hole" % page_num)
        if page_num not in requested_urls:
            raise ValueError(
                "no request URL recorded for unattempted page %d" % page_num)
        records.append(PageRecord(
            page=page_num,
            request_url=requested_urls[page_num],
            final_url=None,
            rows_parsed=0,
            rows_new=0,
            status=STATUS_NOT_ATTEMPTED,
            not_attempted_reason=unattempted_map[page_num],
        ))

    # Defensive: a page number outside the requested range means the caller
    # mixed two runs' bookkeeping together. Parentheses matter: set union and
    # subtraction do not bind the way `a | b - c` reads.
    claimed = (set(attempted) | set(unattempted_map) | set(requested_urls))
    stray = sorted(claimed - set(range(1, pages_requested + 1)))
    if stray:
        raise ValueError("page numbers outside 1..%d: %r"
                         % (pages_requested, stray))

    records.sort(key=lambda r: r.page)
    page_dicts = [r.as_dict() for r in records]

    # Computed over the PageRecord objects (page_dicts are plain dicts, whose
    # fields are keyed rather than attributed).
    failed_pages = [r.page for r in records
                    if r.status in FAILURE_STATUSES]
    not_attempted_pages = [r.page for r in records
                           if r.status == STATUS_NOT_ATTEMPTED]
    succeeded_pages = [r.page for r in records
                       if r.status == STATUS_SUCCESS]
    rows_new_total = sum(r.rows_new for r in records)
    rows_parsed_total = sum(r.rows_parsed for r in records)

    # The audit invariant. The output is the same ordered merge these counts
    # came from, so a mismatch means the caller passed a different row set or
    # a stale count — never paper over it.
    if rows_new_total != output_row_count:
        raise ValueError(
            "ledger rows_new total (%d) does not match the output row count "
            "(%d): the per-page attribution does not reconcile with the "
            "output file" % (rows_new_total, output_row_count))

    summary = {
        "pages_requested": pages_requested,
        "pages_succeeded": len(succeeded_pages),
        "pages_failed": failed_pages,
        "pages_not_attempted": not_attempted_pages,
        # The task asks for the truncated PAGE COUNT; the list beside it says
        # WHICH pages, since a count alone cannot be audited.
        "pages_truncated_by_site_count": len(truncated_set),
        "pages_truncated_by_site": sorted(truncated_set),
        "rows_parsed_total": rows_parsed_total,
        "rows_new_total": rows_new_total,
        "stop_reason": stop_reason,
    }
    return {"summary": summary, "pages": page_dicts}
