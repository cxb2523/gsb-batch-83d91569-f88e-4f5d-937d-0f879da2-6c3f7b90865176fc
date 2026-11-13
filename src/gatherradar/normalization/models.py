"""Transient normalization interpretations; diagnostics are not source facts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum

from ..domain import EventCandidate, PlaceCandidate
from ..domain.temporal import DatePrecision
from ..domain.occurrence import EventOccurrence, ScheduleKind


class NormalizationStatus(StrEnum):
    NORMALIZED = "normalized"
    PARTIAL = "partially_normalized"
    UNRESOLVED = "unresolved"
    INVALID = "invalid"


class Severity(StrEnum):
    INFO = "info"
    REVIEW = "review"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    field: str
    message: str
    severity: Severity = Severity.REVIEW


def status_for(has_values: bool, diagnostics: tuple[Diagnostic, ...]) -> NormalizationStatus:
    if any(d.severity is Severity.ERROR for d in diagnostics):
        return NormalizationStatus.INVALID
    if not has_values:
        return NormalizationStatus.UNRESOLVED
    if any(d.severity is Severity.REVIEW for d in diagnostics):
        return NormalizationStatus.PARTIAL
    return NormalizationStatus.NORMALIZED


@dataclass(frozen=True, slots=True)
class TemporalResult:
    start_date: date | None = None
    end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    timezone: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    date_precision: DatePrecision = DatePrecision.UNKNOWN
    reference_at: datetime | None = None
    reference_basis: str | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    occurrences: tuple[EventOccurrence, ...] = ()
    schedule_kind: ScheduleKind = ScheduleKind.UNKNOWN
    recurrence_rule: str | None = None

    @property
    def status(self) -> NormalizationStatus:
        return status_for(bool(self.occurrences) or self.start_date is not None or self.start_time is not None, self.diagnostics)


@dataclass(frozen=True, slots=True)
class PriceResult:
    price_amount: Decimal | None = None
    currency: str | None = None
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def status(self) -> NormalizationStatus:
        return status_for(self.price_amount is not None, self.diagnostics)


@dataclass(frozen=True, slots=True)
class NormalizationOutcome:
    candidate: EventCandidate | PlaceCandidate
    temporal: TemporalResult | None = None
    price: PriceResult = PriceResult()
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def status(self) -> NormalizationStatus:
        has_values = self.price.price_amount is not None or (
            self.temporal is not None and
            (bool(self.temporal.occurrences) or self.temporal.start_date is not None or self.temporal.start_time is not None)
        )
        return status_for(bool(has_values), self.diagnostics)
