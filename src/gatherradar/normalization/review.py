from __future__ import annotations

from collections.abc import Iterable

from .models import NormalizationOutcome


def format_normalization(outcomes: Iterable[NormalizationOutcome]) -> str:
    lines = ["", "Normalization review (offline; nothing persisted)"]
    for result in outcomes:
        candidate = result.candidate
        lines.extend(("", f"candidate_id: {candidate.candidate_id}", f"raw_item_id: {candidate.raw_item_id}",
                      f"normalization_status: {result.status.value}"))
        if result.temporal is not None:
            lines.append(f"source_date_text: {candidate.source_date_text}")
            lines.append(f"temporal_status: {result.temporal.status.value}")
            for name in ("start_date", "end_date", "start_time", "end_time", "timezone", "starts_at", "ends_at",
                         "date_precision", "reference_basis", "reference_at"):
                value = getattr(result.temporal, name)
                lines.append(f"{name}: {value.isoformat() if hasattr(value, 'isoformat') else value}")
        lines.extend((f"price_text: {candidate.price_text}", f"price_status: {result.price.status.value}",
                      f"price_amount: {result.price.price_amount}", f"currency: {result.price.currency}"))
        lines.extend(f"diagnostic: {d.severity.value}/{d.code}: {d.message}" for d in result.diagnostics)
    return "\n".join(lines)
