from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum

from .raw_item import _require_aware
from .temporal import DatePrecision
from .occurrence import EventOccurrence, ScheduleKind


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    field: str
    candidate_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChannelProvenance:
    """Which publisher channel and acquisition strategy supplied one candidate."""
    candidate_id: str
    raw_item_id: str
    source_id: str
    publisher_key: str
    channel: str
    strategy: str
    content_url: str
    evidence_slot: str = "primary"


@dataclass(frozen=True, slots=True)
class CanonicalDiagnostic:
    code: str
    field: str
    candidate_ids: tuple[str, ...] = ()


class EventStatus(StrEnum):
    UPCOMING = "upcoming"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    POSTPONED = "postponed"
    SOLD_OUT = "sold_out"
    UNKNOWN = "unknown"


class ReviewStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    title: str | None
    canonical_source_url: str
    first_seen_at: datetime
    last_seen_at: datetime
    status: EventStatus = EventStatus.UNKNOWN
    review_status: ReviewStatus = ReviewStatus.NEEDS_REVIEW
    summary: str | None = None
    category: str | None = None
    tags: tuple[str, ...] = ()
    source_date_text: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    timezone: str | None = None
    venue_name: str | None = None
    address: str | None = None
    city: str | None = None
    event_format: str | None = None
    price_text: str | None = None
    price_amount: int | Decimal | None = None
    currency: str | None = None
    registration_url: str | None = None
    language: str | None = None
    extraction_confidence: float | None = None
    source_item_ids: tuple[str, ...] = ()
    duplicate_group_id: str | None = None
    reviewer_notes: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    date_precision: DatePrecision = DatePrecision.UNKNOWN
    identity_anchor_raw_item_id: str = ""
    identity_anchor_slot: str = "primary"
    candidate_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    publisher_keys: tuple[str, ...] = ()
    evidence_urls: tuple[str, ...] = ()
    field_provenance: tuple[FieldProvenance, ...] = ()
    diagnostics: tuple[CanonicalDiagnostic, ...] = ()
    # Source-supported review context (appended for stable portable columns).
    # `summary` remains reserved for a future dedicated summary contract.
    description_text: str | None = None
    area_text: str | None = None
    location_context: str | None = None
    duration_text: str | None = None
    organizer_name: str | None = None
    availability_text: str | None = None
    source_schedule_text: str | None = None
    # Exact source-labelled category; `category` is only its supported mapping.
    source_category_text: str | None = None
    # Public URLs stated verbatim in source evidence (e.g. an Event page named in a
    # caption). References for the owner only; their unseen content is not extracted.
    reference_urls: tuple[str, ...] = ()
    channel_provenance: tuple[ChannelProvenance, ...] = ()
    # Null fields a currently unavailable publisher channel usually supplies:
    # "missing because the channel was unavailable", not "the source omitted it".
    channel_gaps: tuple[str, ...] = ()
    occurrences: tuple[EventOccurrence, ...] = ()
    schedule_kind: ScheduleKind = ScheduleKind.UNKNOWN
    recurrence_rule: str | None = None
    # `title` remains the compatible display-title field. The source quotation
    # and deterministic derivation evidence are deliberately separate.
    source_title: str | None = None
    display_title_origin: str | None = None
    title_evidence_text: str | None = None
    display_title_evidence_ids: tuple[str, ...] = ()
    evidence_fragment_ids: tuple[str, ...] = ()
    title_review_required: bool = False
    event_detection_reason: str | None = None
    # Disagreeing source wordings (field, value) behind a `source_field_conflict`
    # whose field stayed null: both assertions are kept, neither is chosen.
    conflicting_values: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.event_id.strip() or not self.canonical_source_url.strip():
            raise ValueError("event_id and canonical_source_url must not be empty")
        if self.title is not None and not self.title.strip():
            raise ValueError("title must be populated or null")
        for name in ("first_seen_at", "last_seen_at", "starts_at", "ends_at"):
            _require_aware(getattr(self, name), name)
        if self.last_seen_at < self.first_seen_at:
            raise ValueError("last_seen_at precedes first_seen_at")
        if self.extraction_confidence is not None and not 0 <= self.extraction_confidence <= 1:
            raise ValueError("extraction_confidence must be between 0 and 1")
