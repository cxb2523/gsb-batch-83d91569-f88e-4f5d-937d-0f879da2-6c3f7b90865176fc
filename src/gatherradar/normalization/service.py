from __future__ import annotations

from dataclasses import replace
import re

from ..domain import EventCandidate, PlaceCandidate, RawItem, Source
from .models import Diagnostic, NormalizationOutcome, Severity
from .prices import normalize_price
from .schedules import normalize_schedule
from .text import fold


class NormalizationService:
    """Pure interpretation of discovered fields. Identity and wording never change."""

    def normalize(
        self, candidate: EventCandidate | PlaceCandidate, raw_item: RawItem, source: Source,
        *, evidence_text: str | None = None,
    ) -> NormalizationOutcome:
        if candidate.raw_item_id != raw_item.id or source.id != raw_item.source_id or source.source_type != raw_item.source_type:
            return NormalizationOutcome(candidate, diagnostics=(Diagnostic(
                "context_mismatch", "provenance", "Candidate, observation and source must correspond.", Severity.ERROR,
            ),))
        price = normalize_price(candidate.price_text)
        if isinstance(candidate, PlaceCandidate):
            return NormalizationOutcome(candidate, price=price, diagnostics=price.diagnostics)
        # Discovery may select a relative token from ordinary prose or a proper name.
        # A bare token needs a standalone temporal line in the exact discovery unit.
        evidence = raw_item.raw_text if evidence_text is None else evidence_text
        lines = {re.sub(r"^(?:زمان|تاریخ|date|when)\s*[:：]\s*", "", fold(line)).strip(" .،؛📅🗓")
                 for line in evidence.splitlines()}
        excluded = {field: None for field in ("source_date_text", "source_schedule_text")
                    if fold(getattr(candidate, field) or "") in {"امروز", "فردا", "today", "tomorrow"}
                    and fold(getattr(candidate, field)) not in lines}
        temporal = normalize_schedule(replace(candidate, **excluded), raw_item, source)
        if (not temporal.occurrences and 'media_ocr_only' in candidate.extraction_diagnostics
                and candidate.source_date_text and not candidate.source_schedule_text):
            # Retain a uniquely readable calendar date even when surrounding OCR
            # clocks are garbled. Calendar/weekday contradictions still veto it;
            # the original wording stays on the candidate for human inspection.
            from .dates import _SINGLE, _WEEKDAY_TEXT
            wording = fold(candidate.source_date_text)
            matches = list(re.finditer(r'(?:' + _WEEKDAY_TEXT + r'\s+)?' + _SINGLE.pattern, wording))
            if len(matches) == 1 and all(d.code in {'ambiguous_date_context', 'unparsed_temporal', 'missing_date'}
                                         for d in temporal.diagnostics):
                recovered = normalize_schedule(replace(candidate, source_date_text=matches[0][0]), raw_item, source)
                if recovered.occurrences and not any(d.code in {'invalid_date', 'weekday_contradiction'} for d in recovered.diagnostics):
                    temporal = replace(recovered, diagnostics=recovered.diagnostics + (Diagnostic(
                        'ocr_clock_needs_review', 'source_date_text', 'Calendar is readable; corrupted clock wording was not interpreted.'),))
        if excluded:
            temporal = replace(temporal, diagnostics=temporal.diagnostics + tuple(
                Diagnostic("ambiguous_relative_context", field,
                           "Bare relative word is not a standalone or labelled temporal line in the evidence.")
                for field in excluded))
        updated = replace(candidate, **{
            name: getattr(temporal, name) for name in (
                "start_date", "end_date", "start_time", "end_time", "starts_at", "ends_at", "timezone", "date_precision",
                "occurrences", "schedule_kind", "recurrence_rule",
            )
        }, price_amount=price.price_amount, currency=price.currency)
        return NormalizationOutcome(updated, temporal, price, temporal.diagnostics + price.diagnostics)
