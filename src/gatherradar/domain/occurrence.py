"""Source-supported sessions, independent of collection and persistence."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
import re
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from .raw_item import _require_aware
from .temporal import DatePrecision


class ScheduleKind(StrEnum):
    UNKNOWN = "unknown"
    SINGLE = "single"
    DISCRETE = "discrete"
    RANGE = "range"
    RECURRING = "recurring"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class EventOccurrence:
    occurrence_id: str
    start_date: date
    timezone: str
    end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    date_precision: DatePrecision = DatePrecision.DAY
    source_schedule_text: str | None = None
    source_session_id: str | None = None
    source_locator: str | None = None
    source_session_origin: str | None = None
    source_item_ids: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()
    evidence_urls: tuple[str, ...] = ()
    evidence_fragment_ids: tuple[str, ...] = ()
    price_text: str | None = None
    price_amount: int | Decimal | None = None
    currency: str | None = None
    price_per_person: str | None = None
    unit_price: str | None = None
    host_discount_pct: str | None = None
    platform_discount_pct: str | None = None
    availability_text: str | None = None
    remaining_seats: int | None = None
    enabled: bool | None = None
    diagnostics: tuple[str, ...] = ()
    # A child timeslot of the parent ``source_session_id``; the parent session's
    # public sold-out flag and the timeslot's own capacity stay separate facts.
    source_timeslot_id: str | None = None
    source_sold_out: bool | None = None
    capacity_limit: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.occurrence_id, str) or not self.occurrence_id.strip() or type(self.start_date) is not date:
            raise ValueError("occurrence identity and date are required")
        ZoneInfo(self.timezone)
        if self.end_date is not None and (type(self.end_date) is not date or self.end_date < self.start_date):
            raise ValueError("occurrence end date must be a date on or after start")
        if not isinstance(self.date_precision, DatePrecision):
            raise ValueError("occurrence precision must be typed")
        for field in ("start_time", "end_time"):
            clock = getattr(self, field)
            if clock is not None and (type(clock) is not time or clock.tzinfo is not None):
                raise ValueError("occurrence clock must be a local time")
        for field in ("starts_at", "ends_at"):
            _require_aware(getattr(self, field), field)
        if self.end_date is not None and (self.starts_at is not None or self.ends_at is not None):
            raise ValueError("date bounds do not establish a continuous attendance interval")
        if self.starts_at is not None and (
            self.starts_at.astimezone(ZoneInfo(self.timezone)).date() != self.start_date
            or self.starts_at.astimezone(ZoneInfo(self.timezone)).time() != self.start_time
        ):
            raise ValueError("occurrence timestamp must agree with its local date and clock")
        if self.ends_at is not None and (
            self.starts_at is None or self.ends_at <= self.starts_at
            or self.ends_at.astimezone(ZoneInfo(self.timezone)).time() != self.end_time
        ):
            raise ValueError("occurrence end timestamp must follow its start and match its clock")
        if ((self.date_precision is DatePrecision.EXACT and self.starts_at is None)
                or (self.date_precision is DatePrecision.RANGE and self.end_date is None)):
            raise ValueError("occurrence precision requires matching date/time evidence")
        if self.price_amount is not None and (
            isinstance(self.price_amount, bool) or not isinstance(self.price_amount, (int, Decimal))
            or not Decimal(self.price_amount).is_finite()
            or self.price_amount < 0
        ):
            raise ValueError("occurrence price must be finite and nonnegative")
        for field in ("price_per_person", "unit_price", "host_discount_pct", "platform_discount_pct"):
            value = getattr(self, field)
            if value is not None and (
                not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,15}(?:\.[0-9]{1,6})?", value)
                or (field.endswith("_pct") and Decimal(value) > 100)
            ):
                raise ValueError("occurrence source numeric facts must be bounded decimal strings")
        if self.remaining_seats is not None and (
            type(self.remaining_seats) is not int or self.remaining_seats < 0
        ):
            raise ValueError("remaining seats must be a nonnegative integer or null")
        if self.enabled is not None and type(self.enabled) is not bool:
            raise ValueError("session enabled must be a boolean or null")
        if self.source_sold_out is not None and type(self.source_sold_out) is not bool:
            raise ValueError("session sold-out flag must be a boolean or null")
        if self.capacity_limit is not None and (type(self.capacity_limit) is not int or self.capacity_limit < 0):
            raise ValueError("capacity must be a nonnegative integer or null")
        if self.source_timeslot_id is not None and (not self.source_session_id
                                                    or not isinstance(self.source_timeslot_id, str)):
            raise ValueError("a timeslot requires its parent session")


def occurrence_key(value: EventOccurrence) -> tuple[str, ...]:
    """Session identity excludes mutable price/availability and evidence membership."""
    if value.source_session_id:
        origin = value.source_session_origin or (urlsplit(value.evidence_urls[0]).netloc if value.evidence_urls else "")
        key = ("session", origin, value.source_session_id)
        if value.source_timeslot_id:
            # Absent for whole sessions, so their identities are unchanged.
            key += ("timeslot", value.source_timeslot_id)
        if "occurrence_temporal_conflict" in value.diagnostics:
            key += ("conflict", value.start_date.isoformat(),
                    value.start_time.isoformat() if value.start_time else "",
                    value.ends_at.isoformat() if value.ends_at else "", value.timezone)
        return key
    return ("time", value.start_date.isoformat(),
            value.end_date.isoformat() if value.end_date else "",
            value.start_time.isoformat() if value.start_time else "",
            value.end_time.isoformat() if value.end_time else "", value.timezone)


def identify_occurrence(value: EventOccurrence, owner_id: str) -> EventOccurrence:
    payload = json.dumps((owner_id, *occurrence_key(value)), ensure_ascii=False, separators=(",", ":"))
    return replace(value, occurrence_id="occurrence:" + hashlib.sha256(payload.encode()).hexdigest()[:24])
