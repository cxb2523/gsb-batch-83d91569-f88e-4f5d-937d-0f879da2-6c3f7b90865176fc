"""
page_manifest.py
----------------
The per-page manifest of a listing run: `<out>.pages.json`.

Why this module exists
======================
kohls.com server-renders 120 products per listing page, and the default
"Featured" ordering DRIFTS while a run is in progress (measured 2026-09-25:
page 1 re-fetched 24 seconds later kept only 115 of its 120 products). So the
product JSON/CSV, which holds one row per unique SKU, cannot answer the
operational questions a multi-page run raises:

    what did each page actually deliver?
    which pages were refused, never obtained, or never even attempted?
    how many rows were duplicates of something an earlier page already had?

The manifest answers them, one entry per page the run PLANNED to fetch plus
any page the server answered with instead. Everything here is built from the
run's own `PageOutcome` objects and the rows they parsed — no browser, no
network — so all three engines, and the offline tests, build exactly the same
document.

Page numbers
============
The requested page (`requested_page`) is the page the run's `WS=` URL asked
for. The served page (`served_page`) is what the page itself states
(`currentPage` in the listing island). When the two disagree the run ends as
`end_of_listing` (see page_flow.served_other_page) and that entry is recorded
under BOTH numbers — never silently re-homed to the requested one — with
status `end_of_listing`, so its rows cannot be mistaken for another page's.

Dedupe accounting
=================
Duplicates are judged on the SKU (Kohl's `webID`) and accumulated across the
whole run in page order. A SKU seen twice on the SAME page counts as a
duplicate too, not as a new unique SKU. Rows without a SKU cannot be checked
against anything and are counted as new, matching output_writer.dedupe_by_key.

Statuses (the `status` field of every entry)
============================================
    success           the page was served and yielded rows
    no_products       the page was served but parsed to zero rows
    blocked           refused or challenged by the bot manager (exit 3's case)
    not_obtained      the page was never obtained / served but unparsed (exit 5)
    end_of_listing    a past-the-end page, an honestly empty listing, or a
                      page whose server-reported number did not match the ask
    unattempted       planned, but never fetched (a worker died, an earlier
                      page stopped the run)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

# Entry statuses. Kept as string constants rather than an enum so the
# manifest is plain JSON a consumer can grep without importing this module.
STATUS_SUCCESS = "success"
STATUS_NO_PRODUCTS = "no_products"
STATUS_BLOCKED = "blocked"
STATUS_NOT_OBTAINED = "not_obtained"
STATUS_END = "end_of_listing"
STATUS_UNATTEMPTED = "unattempted"

# Every status the manifest can emit, in reading order.
STATUSES = (STATUS_SUCCESS, STATUS_NO_PRODUCTS, STATUS_BLOCKED,
            STATUS_NOT_OBTAINED, STATUS_END, STATUS_UNATTEMPTED)

# Stop reasons that mean the run genuinely reached the end of the listing, so
# planned pages left without an outcome lie past that end and are NOT
# unattempted. Mirrors output_writer.COMPLETE_STOP_REASONS but is named here
# for the one question this module asks of it.
_END_STOP_REASONS = ("end_of_listing", "no_new_products")


@dataclass
class PageEntry:
    """One page's account of itself. Field names are the JSON contract."""

    requested_page: int
    served_page: Optional[int] = None
    rows_emitted: int = 0
    new_skus: int = 0
    duplicate_skus: int = 0
    status: str = STATUS_UNATTEMPTED
    # The page_flow state ("content", "blocked", "end", …) when one was
    # classified, and the URL the page was asked for: diagnostics, kept beside
    # the status rather than instead of it.
    page_state: Optional[str] = None
    url: Optional[str] = None
    # A masked error message for a page that failed unexpectedly ("" otherwise).
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "requested_page": self.requested_page,
            "served_page": self.served_page,
            "rows_emitted": self.rows_emitted,
            "new_skus": self.new_skus,
            "duplicate_skus": self.duplicate_skus,
            "status": self.status,
            "page_state": self.page_state,
            "url": self.url,
            "error": self.error,
        }


def _outcome_status(outcome) -> str:
    """Map a fetched page's PageOutcome onto a manifest status.

    `outcome` is duck-typed (browser_bridge.PageOutcome) so this module does
    not import the bridge: the bridge imports the manifest, and a cycle would
    pin the two together.
    """
    if outcome.blocked_by is not None:
        return STATUS_BLOCKED
    if outcome.load_failed or outcome.parsed_nothing or outcome.error:
        return STATUS_NOT_OBTAINED
    if outcome.served_other or outcome.state in ("end", "empty"):
        return STATUS_END
    if outcome.products:
        return STATUS_SUCCESS
    # Served content that yielded no rows without the explicit flag: still a
    # parser-side "nothing obtained", never a silent success.
    return STATUS_NO_PRODUCTS


def _planned_page_numbers(start_page: int, pages_requested: int,
                          pages_available: Optional[int]) -> List[int]:
    """The page numbers the run planned, 1-based, capped like the run itself.

    Local copy of page_flow.pages_to_fetch's arithmetic expressed as the
    actual numbers, so the manifest needs no import from the flow module and
    stays buildable from a bare list of outcomes.
    """
    count = pages_requested
    if pages_available:
        count = max(1, min(pages_requested, pages_available - start_page + 1))
    return [start_page + k for k in range(count)]


def _zero_rows_reason(stop_reason: str, blocked: bool, entries: Sequence[dict]
                      ) -> str:
    """Why a run ended with zero product rows, in the manifest's own words."""
    if blocked or any(e["status"] == STATUS_BLOCKED for e in entries):
        return "blocked"
    if any(e["status"] == STATUS_NOT_OBTAINED for e in entries):
        return "not_obtained"
    if stop_reason in ("served_but_unparsed",):
        return "served_but_unparsed"
    if stop_reason in _END_STOP_REASONS or any(
            e["status"] == STATUS_END for e in entries):
        return "end_of_listing"
    return stop_reason or "no_products"


def build_page_manifest(outcomes, *, start_page: int, pages_requested: int,
                        pages_available: Optional[int], stop_reason: str,
                        blocked: bool) -> dict:
    """Build the `<out>.pages.json` document from a run's outcomes.

    `outcomes` are browser_bridge.PageOutcome objects in any order; they are
    processed in page order so the cross-page duplicate set is deterministic.
    Planned pages with no outcome become `unattempted` entries unless the run
    stopped for an end-of-listing reason, in which case they lie past the end
    and are omitted.
    """
    by_page: Dict[int, object] = {o.page_num: o for o in outcomes}
    planned = _planned_page_numbers(start_page, pages_requested, pages_available)

    # A page whose served number did not match the ask stays keyed under the
    # REQUESTED number with both numbers on the entry and status
    # end_of_listing: it is never re-homed to the page it claimed to be, and
    # its rows are excluded from the product output by the bridge.
    ordered = sorted(set(planned) | set(by_page))

    seen_skus = set()
    entries: List[dict] = []
    for page_num in ordered:
        outcome = by_page.get(page_num)
        if outcome is None:
            # Planned but no outcome. Past an end the run actually reached
            # there was nothing to get; everything else was never attempted.
            if page_num in planned and stop_reason in _END_STOP_REASONS:
                continue
            entries.append(PageEntry(requested_page=page_num).as_dict())
            continue

        rows = outcome.products or []
        new_count = 0
        duplicate_count = 0
        for product in rows:
            sku = getattr(product, "sku", None)
            if sku is None or sku not in seen_skus:
                new_count += 1
                if sku is not None:
                    seen_skus.add(sku)
            else:
                # A repeat on the SAME page is a duplicate just like one seen
                # on an earlier page: it must not inflate the unique count.
                duplicate_count += 1

        served = outcome.listing.get("served_page") if outcome.listing else None
        # A page whose island carried no currentPage states nothing; leave
        # served_page null rather than guessing from the URL.
        entry = PageEntry(
            requested_page=outcome.page_num,
            served_page=served,
            rows_emitted=len(rows),
            new_skus=new_count,
            duplicate_skus=duplicate_count,
            status=_outcome_status(outcome),
            page_state=outcome.state,
            url=outcome.url,
            error=outcome.error or "",
        )
        entries.append(entry.as_dict())

    status_counts = {status: 0 for status in STATUSES}
    for entry in entries:
        status_counts[entry["status"]] += 1

    rows_total = sum(e["rows_emitted"] for e in entries)
    # Rows kept after dedupe == the new-SKU total plus any SKU-less rows; on
    # this site every parsed row carries a webID, so the two are equal, and
    # both are reported rather than assumed.
    unique_skus = len(seen_skus)
    duplicate_rows = sum(e["duplicate_skus"] for e in entries)
    zero_rows = rows_total == 0

    summary = {
        "pages_requested": pages_requested,
        "pages_planned": len(planned),
        "pages_succeeded": status_counts[STATUS_SUCCESS],
        "pages_no_products": status_counts[STATUS_NO_PRODUCTS],
        "pages_blocked": status_counts[STATUS_BLOCKED],
        "pages_not_obtained": status_counts[STATUS_NOT_OBTAINED],
        "pages_end_of_listing": status_counts[STATUS_END],
        "pages_unattempted": status_counts[STATUS_UNATTEMPTED],
        "rows_emitted": rows_total,
        "unique_skus": unique_skus,
        "duplicate_rows": duplicate_rows,
        "zero_rows": zero_rows,
        "zero_rows_reason": _zero_rows_reason(stop_reason, blocked, entries)
        if zero_rows else None,
        "stop_reason": stop_reason,
    }
    return {"source": "kohls.com", "mode": "listing",
            "summary": summary, "pages": entries}
