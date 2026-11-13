from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..domain import DiscoveryType
from ..domain.website import SourceSession

EVENT_FORMATS = frozenset({"in_person", "online", "hybrid"})


@dataclass(frozen=True, slots=True)
class SourceField:
    """An adapter-verified structural fact: exact retained text plus where it was seen.

    `origin` is `detail` (the item's page) or `listing` (its own listing card).
    The value is already proven to be a verbatim slice of that fragment's text.
    """

    name: str
    value: str
    origin: str


@dataclass(frozen=True, slots=True)
class ExtractionInput:
    """The deliberate, auditable evidence a provider may see for one RawItem.

    Adapter `raw_metadata` is intentionally excluded except for a validated explicit
    website heading passed as `source_title`; the RawItem remains the system
    record. `locale`, `timezone`, and `city_hint` are source configuration context and
    are only set when that configuration is supplied.
    """

    raw_item_id: str
    source_id: str
    source_type: str
    raw_text: str
    content_url: str
    content_type: str
    published_at: datetime | None = None
    author: str | None = None
    locale: str | None = None
    timezone: str | None = None
    city_hint: str | None = None
    source_title: str | None = None
    # Validated structural website facts plus each unit fragment's own text as
    # (origin, text), so captions, OCR, listing and detail facts stay attributable.
    source_fields: tuple[SourceField, ...] = ()
    segments: tuple[tuple[str, str], ...] = ()
    source_sessions: tuple[SourceSession, ...] = ()
    source_session_diagnostics: tuple[str, ...] = ()



@dataclass(frozen=True, slots=True)
class DiscoveryEvidence:
    """Why a provider decided what it decided, for the run report only.

    This is debugging and review material, not a fact about the world: it never
    reaches EventCandidate or PlaceCandidate and is never persisted. A rule engine
    fills in its scores and matched signals; a provider that cannot explain itself
    may leave it out entirely.
    """

    event_score: float = 0.0
    place_score: float = 0.0
    negative_score: float = 0.0
    matched_signals: tuple[str, ...] = ()
    negative_signals: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryFacts:
    """Provider output for one RawItem: what the content is, plus source-supported
    facts about it, before deterministic validation and normalization.

    `discovery_type` answers one question — does this announce a concrete attendable
    event, describe a place worth visiting, or neither? Event-only fields stay None on
    a place and place-only fields stay None on an event, because a gallery has no
    occurrence and an event has no opening hours.

    Every value must be traceable to the source text or supplied source context.
    Unknown values stay None; an event may legitimately have no title.
    """

    discovery_type: DiscoveryType
    title: str | None = None
    summary: str | None = None
    category: str | None = None
    source_date_text: str | None = None
    venue_name: str | None = None
    address: str | None = None
    city: str | None = None
    event_format: str | None = None
    price_text: str | None = None
    opening_hours_text: str | None = None
    registration_url: str | None = None
    language: str | None = None
    extraction_confidence: float | None = None
    evidence: DiscoveryEvidence | None = None
    # Source-provided context, never generated prose; `summary` stays separate.
    description_text: str | None = None
    area_text: str | None = None
    location_context: str | None = None
    duration_text: str | None = None
    organizer_name: str | None = None
    availability_text: str | None = None
    source_schedule_text: str | None = None
    # Exact source-labelled category wording (e.g. a listing genre chip).
    source_category_text: str | None = None
    # Public http(s) URLs written verbatim in the evidence text (Events only).
    reference_urls: tuple[str, ...] = ()
    # Fields left null because listing/detail evidence explicitly disagreed.
    field_conflicts: tuple[str, ...] = ()
    # The disagreeing source wordings behind `field_conflicts`, as (field, value).
    field_conflict_values: tuple[tuple[str, str], ...] = ()
    extraction_diagnostics: tuple[str, ...] = ()
    source_sessions: tuple[SourceSession, ...] = ()
    source_session_diagnostics: tuple[str, ...] = ()
    source_title: str | None = None
    display_title_origin: str | None = None
    title_evidence_text: str | None = None
    title_review_required: bool = False
    event_detection_reason: str | None = None


__all__ = ["EVENT_FORMATS", "DiscoveryEvidence", "DiscoveryFacts", "ExtractionInput", "SourceField"]
