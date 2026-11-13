from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import StrEnum
from urllib.parse import urlsplit

from ..domain import (
    DiscoveryType, DiscoveryUnit, EventCandidate, EvidenceKind, PlaceCandidate,
    RawItem, Source,
)
from ..domain.evidence import primary_discovery_units
from ..domain.website import (FIELD_ORIGINS, MAX_SESSION_RECORDS, STRUCTURED_FIELDS, SourceSession,
                              is_source_slice)
from .base import DiscoveryProvider, InvalidExtractionOutputError, ProviderExtractionError
from .models import DiscoveryEvidence, DiscoveryFacts, ExtractionInput, SourceField

_SEGMENT_ORIGINS = {EvidenceKind.WEBSITE_TEXT: 'detail', EvidenceKind.WEBSITE_LISTING: 'listing'}
_MAX_FIELD = {'description_text': 50_000}
from .signals import has_meaningful_content
from .validation import validate_discovery_facts

SKIP_EMPTY_TEXT = "empty_text"
SKIP_INSUFFICIENT_TEXT = "insufficient_text"


class DiscoveryStatus(StrEnum):
    DISCOVERED = "discovered"
    SKIPPED = "skipped"
    PROVIDER_FAILED = "provider_failed"
    INVALID_OUTPUT = "invalid_output"


@dataclass(frozen=True, slots=True)
class DiscoveryOutcome:
    """Result of analyzing one RawItem.

    Operational and explanatory detail stays here, not on the candidate: `evidence`
    records why the provider decided as it did and is never persisted.
    """

    raw_item_id: str
    status: DiscoveryStatus
    provider_name: str
    discovery_type: DiscoveryType | None = None
    event: EventCandidate | None = None
    place: PlaceCandidate | None = None
    evidence: DiscoveryEvidence | None = None
    reason: str | None = None
    discovery_unit_id: str | None = None

    @property
    def candidate(self) -> EventCandidate | PlaceCandidate | None:
        return self.event if self.event is not None else self.place


def build_candidate_id(raw_item: RawItem) -> str:
    """Identity of the candidate discovered in one exact RawItem observation.

    The same raw item id and content hash always yield the same id, an edited
    observation yields a new one, and the provider or model never affects it.
    """
    observation = f"{raw_item.id}\x1f{raw_item.content_hash}".encode("utf-8")
    return f"candidate:{hashlib.sha256(observation).hexdigest()}"


def _segments(raw_item: RawItem, unit: DiscoveryUnit | None) -> tuple[tuple[str, str], ...]:
    if raw_item.source_type.value != 'website':
        if unit is None:
            return (('caption', raw_item.raw_text),)
        return tuple((f.kind.value, f.text) for f in unit.fragments)
    if unit is None:
        return (('detail', raw_item.raw_text),)
    return tuple((_SEGMENT_ORIGINS[f.kind], f.text) for f in unit.fragments if f.kind in _SEGMENT_ORIGINS)


def _source_fields(raw_item: RawItem, segments: tuple[tuple[str, str], ...]) -> tuple[SourceField, ...]:
    """Adapter facts admitted only as exact slices of a fragment in this unit."""
    values = raw_item.raw_metadata.get('source_fields')
    if raw_item.source_type.value != 'website' or not segments or not isinstance(values, list):
        return ()
    texts = {origin: [text for o, text in segments if o == origin] for origin in FIELD_ORIGINS}
    admitted = []
    for entry in values:
        if not isinstance(entry, dict):
            continue
        name, value, origin = entry.get('name'), entry.get('value'), entry.get('origin')
        if (name in STRUCTURED_FIELDS and origin in FIELD_ORIGINS and isinstance(value, str)
                and value.strip() and len(value) <= _MAX_FIELD.get(name, 500)
                and any(is_source_slice(name, value, text) for text in texts[origin])):
            admitted.append(SourceField(name, value, origin))
    return tuple(dict.fromkeys(admitted))


def _source_sessions(raw_item: RawItem) -> tuple[tuple[SourceSession, ...], tuple[str, ...]]:
    """Only adapter-identified sessions from this exact public detail item."""
    metadata = raw_item.raw_metadata
    if (raw_item.source_type.value != 'website'
            or metadata.get('adapter') != 'jabama-events/3'
            or metadata.get('source_session_schema') != 'jabama-react-router/1'):
        return (), ()
    path = urlsplit(raw_item.content_url).path.rstrip('/')
    if path != '/events/' + raw_item.external_id:
        return (), ('embedded_session_identity_conflict',)
    allowed = {'embedded_sessions_absent', 'embedded_sessions_empty',
               'embedded_session_schema_drift', 'embedded_sessions_schema_drift',
               'embedded_session_identity_conflict', 'embedded_session_price_unit_unknown',
               'embedded_session_discount_unresolved', 'embedded_session_drift_new_properties',
               'embedded_session_drift_timeslots', 'embedded_session_drift_field',
               'embedded_session_unverified_shape', 'embedded_sessions_drift_payload_count',
               'embedded_sessions_drift_payload_size', 'embedded_sessions_drift_call_shape',
               'embedded_sessions_drift_table', 'embedded_sessions_drift_route',
               'embedded_sessions_drift_event_identity', 'embedded_sessions_drift_sessions',
               'embedded_sessions_drift_session_list', 'embedded_session_drift_sold_out_type',
               'embedded_session_drift_timeslot_new_properties',
               'embedded_session_drift_timeslot_missing_properties', 'embedded_session_drift_timeslot_type',
               'embedded_session_drift_timeslot_ownership', 'embedded_session_drift_timeslot_timestamp',
               'embedded_session_drift_timeslot_order', 'embedded_session_timeslots',
               'embedded_timeslot_outside_parent_window', 'embedded_timeslot_parent_window_unknown',
               'embedded_timeslot_availability_inconsistent', 'embedded_timeslot_duplicate_id',
               'embedded_timeslot_identity_conflict'}
    reported = metadata.get('source_session_diagnostics', [])
    diagnostics = tuple(value for value in reported if isinstance(value, str) and value in allowed) if isinstance(reported, list) else ()
    values = metadata.get('source_sessions', [])
    if not isinstance(values, list) or len(values) > MAX_SESSION_RECORDS:
        return (), (*diagnostics, 'embedded_session_schema_drift')
    admitted = []
    for value in values:
        try:
            session = SourceSession.from_mapping(value)
        except ValueError:
            return (), (*diagnostics, 'embedded_session_schema_drift')
        if session.source_event_id != raw_item.external_id:
            return (), (*diagnostics, 'embedded_session_identity_conflict')
        admitted.append(session)
    # A parent session is either one record or a set of uniquely named timeslots.
    if (len({(s.source_session_id, s.source_timeslot_id) for s in admitted}) != len(admitted)
            or len({s.source_timeslot_id for s in admitted if s.source_timeslot_id})
            != len([s for s in admitted if s.source_timeslot_id])
            or {s.source_session_id for s in admitted if s.source_timeslot_id}
            & {s.source_session_id for s in admitted if not s.source_timeslot_id}):
        return (), (*diagnostics, 'embedded_session_identity_conflict')
    return tuple(admitted), tuple(dict.fromkeys(diagnostics))


def build_extraction_input(raw_item: RawItem, source: Source | None = None,
                           unit: DiscoveryUnit | None = None) -> ExtractionInput:
    if source is not None and source.id != raw_item.source_id:
        raise ValueError(
            f"source {source.id} does not match raw item source {raw_item.source_id}"
        )
    title = raw_item.raw_metadata.get('page_title')
    source_title = (title if raw_item.source_type.value == 'website'
                    and raw_item.raw_metadata.get('title_origin') == 'heading'
                    and isinstance(title,str) and 0 < len(title.strip()) <= 500
                    and title in raw_item.raw_text else None)
    segments = _segments(raw_item, unit)
    sessions, session_diagnostics = _source_sessions(raw_item)
    if sessions and unit is not None and not any(
            fragment.kind is EvidenceKind.WEBSITE_TEXT and fragment.source_url == raw_item.content_url
            for fragment in unit.fragments):
        sessions = ()
        session_diagnostics = (*session_diagnostics, 'embedded_session_identity_conflict')
    return ExtractionInput(
        raw_item_id=raw_item.id,
        source_id=raw_item.source_id,
        source_type=raw_item.source_type.value,
        raw_text=raw_item.raw_text,
        content_url=raw_item.content_url,
        content_type=raw_item.content_type,
        published_at=raw_item.published_at,
        author=raw_item.author,
        locale=source.locale if source is not None else None,
        timezone=source.timezone if source is not None else None,
        city_hint=source.city_hint if source is not None else None,
        source_title=source_title,
        source_fields=_source_fields(raw_item, segments),
        segments=segments,
        source_sessions=sessions,
        source_session_diagnostics=session_diagnostics,
    )


class DiscoveryService:
    """Deterministic application behavior around exactly one provider call per RawItem.

    It guards which observations are worth classifying, validates provider output, and
    maps it onto the candidate type the classification calls for, with provenance and
    identity taken from the RawItem itself. It holds no opinion about Persian or
    English event language — that vocabulary lives in `rules`, and the guard below
    only asks whether there are any content words at all.
    """

    def __init__(self, provider: DiscoveryProvider) -> None:
        self._provider = provider

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def discover(self, raw_item: RawItem, source: Source | None = None) -> DiscoveryOutcome:
        units = primary_discovery_units(raw_item)
        if not units:
            return self._outcome(raw_item, DiscoveryStatus.SKIPPED, reason=SKIP_EMPTY_TEXT)
        caption_item = replace(raw_item, raw_text=units[0].text)
        return self._discover_raw(caption_item, source)

    def discover_units(
        self, raw_item: RawItem, units: tuple[DiscoveryUnit, ...],
        source: Source | None = None,
    ) -> tuple[DiscoveryOutcome, ...]:
        return tuple(self.discover_unit(raw_item, unit, source) for unit in units)

    def discover_unit(
        self, raw_item: RawItem, unit: DiscoveryUnit, source: Source | None = None
    ) -> DiscoveryOutcome:
        if unit.raw_item_id != raw_item.id:
            raise ValueError('discovery unit does not belong to the raw item')
        unit_hash = hashlib.sha256(
            (raw_item.content_hash + '\x1f' + unit.unit_id).encode('utf-8')
        ).hexdigest()
        unit_item = replace(raw_item, raw_text=unit.text, content_hash=unit_hash)
        outcome = self._discover_raw(unit_item, source, unit)
        return replace(outcome, discovery_unit_id=unit.unit_id)

    def _discover_raw(
        self, raw_item: RawItem, source: Source | None = None, unit: DiscoveryUnit | None = None,
    ) -> DiscoveryOutcome:
        extraction_input = build_extraction_input(raw_item, source, unit)
        if not raw_item.raw_text.strip():
            # No text is not evidence of anything, so this is not classified at all.
            return self._outcome(raw_item, DiscoveryStatus.SKIPPED, reason=SKIP_EMPTY_TEXT)
        if not has_meaningful_content(raw_item.raw_text):
            # Meaningless content is not an "other": nothing was actually analyzed.
            return self._outcome(raw_item, DiscoveryStatus.SKIPPED, reason=SKIP_INSUFFICIENT_TEXT)

        try:
            facts = validate_discovery_facts(self._provider.discover(extraction_input))
            if facts.display_title_origin:
                # Recompute the bounded resolver against this unit, not arbitrary
                # provider prose or a neighbouring slide's title.
                from .titles import resolve_title
                supported = resolve_title(extraction_input)
                if ((facts.title, facts.display_title_origin, facts.title_evidence_text)
                        != (supported.title, supported.origin, supported.evidence_text)):
                    raise InvalidExtractionOutputError('title resolution is not supported by this candidate evidence')
        except ProviderExtractionError as exc:
            return self._outcome(raw_item, DiscoveryStatus.PROVIDER_FAILED, reason=str(exc))
        except InvalidExtractionOutputError as exc:
            return self._outcome(raw_item, DiscoveryStatus.INVALID_OUTPUT, reason=str(exc))

        return self._outcome(
            raw_item,
            DiscoveryStatus.DISCOVERED,
            discovery_type=facts.discovery_type,
            event=_event_candidate(raw_item, facts, unit),
            place=_place_candidate(raw_item, facts),
            evidence=facts.evidence,
        )

    def _outcome(
        self,
        raw_item: RawItem,
        status: DiscoveryStatus,
        *,
        discovery_type: DiscoveryType | None = None,
        event: EventCandidate | None = None,
        place: PlaceCandidate | None = None,
        evidence: DiscoveryEvidence | None = None,
        reason: str | None = None,
    ) -> DiscoveryOutcome:
        return DiscoveryOutcome(
            raw_item_id=raw_item.id,
            status=status,
            provider_name=self._provider.name,
            discovery_type=discovery_type,
            event=event,
            place=place,
            evidence=evidence,
            reason=reason,
        )


def _event_candidate(raw_item: RawItem, facts: DiscoveryFacts,
                     unit: DiscoveryUnit | None = None) -> EventCandidate | None:
    """An EventCandidate, or None when the observation was not an event.

    `starts_at`, `ends_at`, `price_amount`, and `currency` are owned by the later
    normalization step and stay null here; the source wording that would feed them
    stays in `source_date_text` and `price_text`.
    """
    if facts.discovery_type is not DiscoveryType.EVENT:
        return None
    return EventCandidate(
        candidate_id=build_candidate_id(raw_item),
        raw_item_id=raw_item.id,
        is_event=True,
        title=facts.title,
        summary=facts.summary,
        category=facts.category,
        source_date_text=facts.source_date_text,
        venue_name=facts.venue_name,
        address=facts.address,
        city=facts.city,
        event_format=facts.event_format,
        price_text=facts.price_text,
        registration_url=facts.registration_url,
        language=facts.language,
        extraction_confidence=facts.extraction_confidence,
        evidence_url=raw_item.content_url,
        description_text=facts.description_text,
        area_text=facts.area_text,
        location_context=facts.location_context,
        duration_text=facts.duration_text,
        organizer_name=facts.organizer_name,
        availability_text=facts.availability_text,
        source_schedule_text=facts.source_schedule_text,
        source_category_text=facts.source_category_text,
        reference_urls=facts.reference_urls,
        field_conflicts=facts.field_conflicts,
        field_conflict_values=facts.field_conflict_values,
        extraction_diagnostics=tuple(dict.fromkeys((*facts.extraction_diagnostics,
            *(('media_ocr_only',) if all(f.kind in {EvidenceKind.IMAGE_OCR, EvidenceKind.CAROUSEL_SLIDE_OCR,
                EvidenceKind.REEL_FRAME_OCR} for f in unit.fragments) else ()),
            *(note for _, note in unit.notes
              if note in {'repeated_anchor_with_unreliable_temporal_ocr',
                          'source_venue_reclassified_from_ocr_title'})))) if unit else facts.extraction_diagnostics,
        evidence_fragment_ids=tuple(f.fragment_id for f in unit.fragments) if unit else (),
        source_sessions=facts.source_sessions,
        source_session_diagnostics=facts.source_session_diagnostics,
        source_title=facts.source_title,
        display_title_origin=facts.display_title_origin,
        title_evidence_text=facts.title_evidence_text,
        title_review_required=facts.title_review_required,
        event_detection_reason=facts.event_detection_reason,
        display_title_evidence_ids=tuple(f.fragment_id for f in
            (unit.fragments if unit else primary_discovery_units(raw_item)[0].fragments)
            if facts.title_evidence_text and facts.title_evidence_text in f.text),
    )


def _place_candidate(raw_item: RawItem, facts: DiscoveryFacts) -> PlaceCandidate | None:
    if facts.discovery_type is not DiscoveryType.PLACE:
        return None
    return PlaceCandidate(
        candidate_id=build_candidate_id(raw_item),
        raw_item_id=raw_item.id,
        title=facts.title,
        summary=facts.summary,
        category=facts.category,
        address=facts.address,
        city=facts.city,
        opening_hours_text=facts.opening_hours_text,
        price_text=facts.price_text,
        language=facts.language,
        evidence_url=raw_item.content_url,
    )


__all__ = [
    "SKIP_EMPTY_TEXT",
    "SKIP_INSUFFICIENT_TEXT",
    "DiscoveryOutcome",
    "DiscoveryService",
    "DiscoveryStatus",
    "build_candidate_id",
    "build_extraction_input",
]
