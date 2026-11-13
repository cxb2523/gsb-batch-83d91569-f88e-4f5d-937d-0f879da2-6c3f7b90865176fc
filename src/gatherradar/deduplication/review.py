"""Concise deterministic review rendering; no raw text or candidate persistence."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import MatchKind

if TYPE_CHECKING:
    from ..orchestration.canonicalization_run import CanonicalReview


def _short(value: str) -> str:
    return value if len(value) <= 28 else value[:12] + "…" + value[-10:]


def _display(value: object) -> str:
    # One line per value, including when upstream source wording contains lines.
    return " ".join(str(value).split())[:180] if value is not None else "-"


def format_canonical_review(review: CanonicalReview) -> str:
    result = review.result
    names = {s.source.id: s.source.name for s in review.sources}
    lines = ["GatherRadar offline canonical review", ""]
    for source in review.sources:
        lines.append(f"Source: {source.source.name} | {source.path_used} | raw={source.raw_items} "
                     f"events={source.event_candidates} places={source.place_candidates}")
        lines.extend(f"  Diagnostic: {code}" for code in source.diagnostics)
    for event in result.events:
        lines.extend(("", f"Event: {event.event_id}",
                      f"  Anchor: {event.identity_anchor_raw_item_id} / {event.identity_anchor_slot}",
                      f"  Group: {event.duplicate_group_id}",
                      f"  Title: {_display(event.title)}",
                      f"  Date: {event.start_date} to {event.end_date}; time: {event.start_time} to {event.end_time}; "
                      f"{event.timezone}; precision={event.date_precision.value}",
                      f"  Location: {_display(event.venue_name)} | {_display(event.address)} | {_display(event.city)}",
                      f"  Sources: {', '.join(names.get(s, s) for s in event.source_ids)}",
                      f"  Candidates: {', '.join(_short(c) for c in event.candidate_ids)}",
                      f"  Review: {event.review_status.value}"))
        for decision in result.decisions:
            if decision.kind is MatchKind.SAME_EVENT and set(decision.candidate_ids) <= set(event.candidate_ids):
                lines.append(f"  Auto-match: {' / '.join(_short(c) for c in decision.candidate_ids)}: {', '.join(decision.reasons)}")
        lines.extend(f"  Diagnostic: {d.code} [{d.field}] ({', '.join(_short(c) for c in d.candidate_ids)})"
                     for d in event.diagnostics)
    lines.extend(("", "Possible duplicates requiring review"))
    for decision in result.possible_duplicates:
        lines.append(f"  {' / '.join(_short(c) for c in decision.candidate_ids)}: {', '.join(decision.reasons)}")
    if not result.possible_duplicates:
        lines.append("  None")
    lines.extend(f"Diagnostic: {d.code} [{d.field}] ({', '.join(_short(c) for c in d.candidate_ids)})"
                 for d in result.diagnostics)
    lines.extend(("", f"Canonical events: {len(result.events)}; auto groups: {len(result.groups)}; "
                  f"singletons: {len(result.singletons)}; possible pairs: {len(result.possible_duplicates)}; "
                  f"places unchanged: {len(result.places)}; rejected contexts: {len(result.rejected)}",
                  "Offline review only. Nothing was persisted."))
    return "\n".join(lines)
