"""
page_report.py
--------------
The per-page outcome record a run leaves beside its output.

Why this exists
===============
The run-metadata sidecar (`<out>.meta.json`) describes the RUN: how many
pages were requested, how many completed, which page numbers failed. It is
deliberately one document per run, so it cannot answer the questions an
operator has when a few pages went missing:

    did THIS page even get an attempt?
    how many times was it tried?
    which proxy exit did the page actually finish on, after rotation?
    what did the last failure say?

This module is that answer, one record per page, written to
`<out>.page_report.json` next to the sidecar. It is engine-agnostic:
`page_flow.fetch_one_page` collects the facts onto each `PageOutcome`, and
the engine that owns the output prefix asks this module to serialise them.

Outcomes
========
Every page ends in exactly one of these:

    success           served and parsed (a page with zero rows is still a
                      success — an empty listing is an answer, not a fault)
    rejected          the endpoint refused the PARAMETERS (HTTP 400 or a
                      non-success JSON code). The same request would be
                      refused again, so it is never retried. Distinct from
                      `blocked`: nothing about the exit changes this answer.
    blocked           the exit was refused: HTTP 403/451 or an AWS WAF
                      challenge that survived the block-retry budget
    transport_failed  the request never completed: a timeout, a dead proxy,
                      an edge that never answered with the endpoint's JSON
    unattempted       the page was planned but never fetched — its worker
                      died, or another page's empty answer ended dispatch

Credential safety
=================
`proxy_exit` is stored MASKED, through `proxy_pool.mask` (host and port
kept, username/password replaced). The raw proxy URL never reaches this
module: callers hand over the pool value and the masking happens here, so a
future caller cannot leak a credential by forgetting. Failure summaries are
passed through the same masking the engines apply to their own error text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import List, Optional, Sequence

from output_writer import _atomic
from proxy_pool import mask as mask_proxy_url

# The five endings. Kept as module constants so a consumer branches on
# imported names rather than string literals it can typo.
SUCCESS = "success"
REJECTED = "rejected"
BLOCKED = "blocked"
TRANSPORT_FAILED = "transport_failed"
UNATTEMPTED = "unattempted"

ALL_OUTCOMES = (SUCCESS, REJECTED, BLOCKED, TRANSPORT_FAILED, UNATTEMPTED)

# The endings that mean the page's data is in the output. An EMPTY page
# (zero rows, the end of a live listing) is still a success: the site
# served exactly what was asked for.
SUCCESSFUL_OUTCOMES = (SUCCESS,)

# How long a failure summary is kept. A `requests` traceback can run to
# several hundred characters once the chained proxies are named; the point
# of this field is a glanceable reason, not the full log line.
REASON_MAX_LEN = 300


def _short_reason(text: Optional[str]) -> Optional[str]:
    """A bounded, single-line failure summary."""
    if not text:
        return None
    line = " ".join(str(text).split())
    if len(line) > REASON_MAX_LEN:
        line = line[: REASON_MAX_LEN - 1].rstrip() + "…"
    return line


def outcome_for(page_outcome) -> str:
    """Map a page_flow.PageOutcome onto one of the five endings."""
    if getattr(page_outcome, "rejected", None):
        return REJECTED
    if getattr(page_outcome, "blocked_by", None):
        return BLOCKED
    if getattr(page_outcome, "load_failed", False) or getattr(
            page_outcome, "unread", False):
        return TRANSPORT_FAILED
    return SUCCESS


def _reason_for(page_outcome, outcome: str) -> Optional[str]:
    """The human-readable summary of why a page did not succeed."""
    if outcome == REJECTED:
        return _short_reason(getattr(page_outcome, "rejected", None)
                             or getattr(page_outcome, "error", None)
                             or "the endpoint refused the request parameters")
    if outcome == BLOCKED:
        # `error` already names the refusal ("blocked by http-403"); fall
        # back to composing one from blocked_by for outcomes built elsewhere.
        detail = getattr(page_outcome, "error", None)
        if detail:
            return _short_reason(detail)
        return _short_reason("blocked by %s"
                             % (getattr(page_outcome, "blocked_by", None)
                                or "refused"))
    if outcome == TRANSPORT_FAILED:
        detail = getattr(page_outcome, "error", None)
        if getattr(page_outcome, "unread", False):
            prefix = "served but the response could not be parsed"
            return _short_reason(prefix + (f": {detail}" if detail else ""))
        return _short_reason(detail or "the request never completed")
    return None


@dataclass
class PageRecord:
    """One page's ending. This is the on-disk shape of each array element."""
    page: int
    outcome: str
    attempts: int
    proxy_exit: str
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def record_for(page_outcome) -> PageRecord:
    """Build the record for a page that was actually fetched."""
    outcome = outcome_for(page_outcome)
    raw_exit = getattr(page_outcome, "proxy_exit", None)
    return PageRecord(
        page=page_outcome.page_num,
        outcome=outcome,
        attempts=max(1, int(getattr(page_outcome, "attempts", 0) or 0)),
        # mask() never raises and turns None into "(none)"; a value that
        # somehow already carries a credential is masked here as well.
        proxy_exit=mask_proxy_url(raw_exit),
        reason=_reason_for(page_outcome, outcome))


def unattempted_record(page_num: int) -> PageRecord:
    """The record for a page that was planned but never fetched."""
    return PageRecord(page=page_num, outcome=UNATTEMPTED, attempts=0,
                      proxy_exit=mask_proxy_url(None), reason=None)


class PageRunReport:
    """Accumulates the per-page records of one run and writes them to disk.

    The record is built from `page_flow.PageOutcome` objects after the page
    loop, rather than mutated from inside worker threads: the outcomes are
    themselves collected under a lock and merged in page order, so record
    construction inherits that guarantee and can never attribute one page's
    exit to another.
    """

    def __init__(self, out_prefix: str):
        self.out_prefix = out_prefix
        self._records: List[PageRecord] = []

    @property
    def path(self) -> str:
        return f"{self.out_prefix}.page_report.json"

    def add_outcomes(self, page_outcomes: Sequence) -> None:
        """Record every fetched page, sorted by page number."""
        for oc in sorted(page_outcomes, key=lambda o: o.page_num):
            self._records.append(record_for(oc))

    def add_unattempted(self, page_nums: Sequence[int]) -> None:
        """Record planned pages the loop never fetched."""
        for n in sorted(page_nums):
            self._records.append(unattempted_record(n))
        self._records.sort(key=lambda r: r.page)

    @property
    def records(self) -> List[PageRecord]:
        return list(self._records)

    def count(self, outcome: str) -> int:
        return sum(1 for r in self._records if r.outcome == outcome)

    @property
    def total_pages(self) -> int:
        return len(self._records)

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self._records if r.outcome in SUCCESSFUL_OUTCOMES)

    def summary_line(self) -> str:
        """The one-line end-of-run summary: success count over the total."""
        line = f"Page report: {self.succeeded}/{self.total_pages} page(s) succeeded"
        bad = {}
        for r in self._records:
            if r.outcome not in SUCCESSFUL_OUTCOMES:
                bad[r.outcome] = bad.get(r.outcome, 0) + 1
        if bad:
            line += " (" + ", ".join(f"{n} {name}"
                                     for name, n in sorted(bad.items())) + ")"
        line += f" -> {self.path}"
        return line

    def to_json(self) -> str:
        return json.dumps([r.to_dict() for r in self._records],
                          ensure_ascii=False, indent=2)

    def write(self) -> str:
        """Atomically write the record next to the .meta.json sidecar.

        Always written, including when every page succeeded: an all-success
        run is exactly when an operator wants a file that proves it, and a
        later "why is a page missing?" question cannot be answered by a file
        the healthy run did not create.
        """
        path = self.path
        with _atomic(path) as f:
            f.write(self.to_json())
        return path
