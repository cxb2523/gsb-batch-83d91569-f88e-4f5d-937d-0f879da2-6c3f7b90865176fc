"""In-memory batch boundary over the exact observations used by discovery."""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from ..domain import RawItem, Source
from ..extraction import DiscoveryOutcome
from ..normalization import NormalizationOutcome, NormalizationService
from ..normalization.models import Diagnostic, Severity


def run_normalization(
    outcomes: Iterable[DiscoveryOutcome], raw_items: Mapping[str, RawItem],
    sources: Mapping[str, Source], *, service: NormalizationService | None = None,
    unit_texts: Mapping[str, str] | None = None,
) -> tuple[NormalizationOutcome, ...]:
    normalizer = service if service is not None else NormalizationService()
    results = []
    for outcome in outcomes:
        candidate = outcome.candidate
        if candidate is None:
            continue
        try:
            raw_item = raw_items[outcome.raw_item_id]
            evidence_text = None
            if outcome.discovery_unit_id is not None:
                # Missing unit context must not fall back to an unrelated caption.
                evidence_text = (unit_texts or {}).get(outcome.discovery_unit_id, "")
            result = normalizer.normalize(candidate, raw_item, sources[raw_item.source_id], evidence_text=evidence_text)
        except Exception:
            # An unexpected failure is isolated; never echo payloads or exception text.
            result = NormalizationOutcome(candidate, diagnostics=(Diagnostic(
                "normalization_failed", "candidate", "Normalization failed or reference context is missing.", Severity.ERROR,
            ),))
        results.append(result)
    return tuple(results)
