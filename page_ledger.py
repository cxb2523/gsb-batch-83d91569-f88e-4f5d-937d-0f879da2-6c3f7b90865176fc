#!/usr/bin/env python3
"""page_ledger.py — a per-page record of one listing run.

The merged product rows and the single .meta.json status describe a run as
a whole; they cannot say whether page 2 was refused by the site, addressed a
page that does not exist, was served in a shape the parser cannot read,
failed to load at all, was skipped because an earlier page already failed,
or simply added no new products. PageLedger records that outcome for every
page number a run touched, so a pagination problem can be checked against
the page numbers instead of guessed from the log.

The class is engine-neutral (no site knowledge, no Playwright import); the
Playwright engine owns when each page gets registered. Writes go through
the same same-directory temp-file-then-rename atomic path as
output_writer.write_json, so a crash mid-write cannot leave a truncated
ledger where a complete one was.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from output_writer import _atomic

# Every outcome a page can end a run with. The first four mirror the
# product_parser/output_writer failure vocabulary; "fetch_failed" is the
# "the navigation itself never returned a page" case; "skipped" marks pages
# that were never attempted because an earlier page made them pointless.
RESULT_OK = "ok"
RESULT_BLOCKED = "blocked"
RESULT_NOT_FOUND = "not_found"
RESULT_PARSER_FAILED = "parser_failed"
RESULT_FETCH_FAILED = "fetch_failed"
RESULT_SKIPPED = "skipped"

RESULT_CATEGORIES = (
    RESULT_OK,
    RESULT_BLOCKED,
    RESULT_NOT_FOUND,
    RESULT_PARSER_FAILED,
    RESULT_FETCH_FAILED,
    RESULT_SKIPPED,
)

# A failure reason is a short human-readable summary; keep it bounded so a
# driver's multi-line "Call log" cannot blow the ledger up. The full text
# still goes to the engine log — the ledger only needs enough to tell the
# failure classes apart at a glance.
MAX_REASON_LEN = 300


@dataclass
class PageRecord:
    """One page's outcome. Field order is the on-disk JSON order too."""
    page: int
    result: str
    product_count: int
    new_sku_count: int
    reason: Optional[str] = None


def ledger_path_for(out_path: str) -> str:
    """The ledger sits beside the data output: --out with its extension
    removed, plus .pages.json (e.g. stockx.json -> stockx.pages.json)."""
    from pathlib import Path

    return f"{Path(out_path).with_suffix('')}.pages.json"


def _short_reason(reason: Optional[str]) -> Optional[str]:
    if reason is None:
        return None
    text = " ".join(str(reason).split())
    if len(text) > MAX_REASON_LEN:
        text = text[: MAX_REASON_LEN - 1] + "…"
    return text


class PageLedger:
    """Accumulates PageRecords keyed by page number.

    A page number can only be registered once: a repeat registration keeps
    the FIRST result and add_page() returns False rather than overwriting
    it. Records are always emitted sorted by page number, so concurrent
    workers may finish in any order without that order leaking into the
    file."""

    def __init__(self) -> None:
        self._records: Dict[int, PageRecord] = {}

    def add_page(
        self,
        page: int,
        result: str,
        *,
        product_count: int = 0,
        new_sku_count: int = 0,
        reason: Optional[str] = None,
    ) -> bool:
        """Register one page. Returns False (and changes nothing) when
        `page` was already registered; True when the record was stored."""
        if page in self._records:
            return False
        if result not in RESULT_CATEGORIES:
            raise ValueError(
                f"unknown page result {result!r}; expected one of {RESULT_CATEGORIES}"
            )
        self._records[page] = PageRecord(
            page=int(page),
            result=result,
            product_count=int(product_count),
            new_sku_count=int(new_sku_count),
            reason=_short_reason(reason),
        )
        return True

    @property
    def pages(self) -> List[int]:
        return sorted(self._records)

    def __len__(self) -> int:
        return self._records.__len__()

    def to_dict(self) -> dict:
        """A plain, JSON-serialisable view, pages in ascending page-number
        order regardless of registration order."""
        records = [asdict(self._records[n]) for n in sorted(self._records)]
        counts = {name: 0 for name in RESULT_CATEGORIES}
        for record in records:
            counts[record["result"]] += 1
        return {
            "pages": records,
            "page_count": len(records),
            "result_counts": counts,
        }

    def write_json(self, path: str) -> None:
        """Atomically write the ledger to `path`, using the same
        same-directory temp-file-then-rename mechanism as output_writer:
        a failed or interrupted write leaves any previous ledger intact."""
        with _atomic(path) as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
