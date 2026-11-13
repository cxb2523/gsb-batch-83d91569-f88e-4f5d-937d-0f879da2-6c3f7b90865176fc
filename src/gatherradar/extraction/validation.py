from __future__ import annotations

import math
from dataclasses import fields, replace
from urllib.parse import urlparse

from ..domain import DiscoveryType
from ..domain.website import SourceSession
from .base import InvalidExtractionOutputError
from .models import EVENT_FORMATS, DiscoveryEvidence, DiscoveryFacts

_TEXT_FIELDS = tuple(
    field.name
    for field in fields(DiscoveryFacts)
    if field.name not in ("discovery_type", "extraction_confidence", "evidence", "field_conflicts",
                          "field_conflict_values",
                          "reference_urls", "extraction_diagnostics", "source_sessions",
                          "source_session_diagnostics", "title_review_required")
)

# Fields that only make sense for one kind of result. A place has no occurrence and
# no registration; an event has no opening hours. Mixing them would let a provider
# smuggle invented facts into the wrong record.
_EVENT_ONLY_FIELDS = ("source_date_text", "event_format", "registration_url", "description_text",
                      "area_text", "location_context", "duration_text", "organizer_name", "availability_text",
                      "source_schedule_text", "source_category_text")
_PLACE_ONLY_FIELDS = ("opening_hours_text",)


def validate_discovery_facts(facts: object) -> DiscoveryFacts:
    """Check provider output against the contract.

    Blank or whitespace-only text becomes None; non-blank text is kept exactly as
    given. Anything else that is materially invalid raises
    InvalidExtractionOutputError rather than being corrected.
    """
    if not isinstance(facts, DiscoveryFacts):
        raise InvalidExtractionOutputError(
            f"provider returned {type(facts).__name__}, expected DiscoveryFacts"
        )
    if not isinstance(facts.discovery_type, DiscoveryType):
        raise InvalidExtractionOutputError("discovery_type must be a DiscoveryType")
    if type(facts.title_review_required) is not bool:
        raise InvalidExtractionOutputError('title_review_required must be boolean')
    if facts.evidence is not None and not isinstance(facts.evidence, DiscoveryEvidence):
        raise InvalidExtractionOutputError("evidence must be DiscoveryEvidence or null")
    for name in ('extraction_diagnostics', 'source_session_diagnostics'):
        values = getattr(facts, name)
        if not isinstance(values, tuple) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise InvalidExtractionOutputError(f"{name} must be a tuple of diagnostic codes")
        if values and facts.discovery_type is not DiscoveryType.EVENT:
            raise InvalidExtractionOutputError(f"{name} is only reported for events")
    if (not isinstance(facts.source_sessions, tuple)
            or any(not isinstance(s, SourceSession) for s in facts.source_sessions)
            or (facts.source_sessions and facts.discovery_type is not DiscoveryType.EVENT)):
        raise InvalidExtractionOutputError("source_sessions must contain event SourceSession values")

    cleaned: dict[str, object] = {}
    for name in _TEXT_FIELDS:
        value = getattr(facts, name)
        if value is not None and not isinstance(value, str):
            raise InvalidExtractionOutputError(f"{name} must be text or null")
        cleaned[name] = value if value is not None and value.strip() else None

    confidence = facts.extraction_confidence
    if confidence is not None:
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise InvalidExtractionOutputError("extraction_confidence must be a number between 0 and 1")
        cleaned["extraction_confidence"] = float(confidence)

    event_format = cleaned["event_format"]
    if event_format is not None and event_format not in EVENT_FORMATS:
        raise InvalidExtractionOutputError("event_format must be in_person, online, hybrid, or null")

    registration_url = cleaned["registration_url"]
    if registration_url is not None:
        parsed = urlparse(registration_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise InvalidExtractionOutputError("registration_url must be an http or https URL")

    references = facts.reference_urls
    if not isinstance(references, tuple) or len(set(references)) != len(references) or any(
            not isinstance(url, str) or urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc
            for url in references):
        raise InvalidExtractionOutputError("reference_urls must be distinct http or https URLs")
    if references and facts.discovery_type is not DiscoveryType.EVENT:
        raise InvalidExtractionOutputError("reference_urls are only reported for events")

    conflicts = facts.field_conflicts
    if (not isinstance(conflicts, tuple) or any(name not in _TEXT_FIELDS for name in conflicts)
            or len(set(conflicts)) != len(conflicts)
            or any(cleaned[name] is not None for name in conflicts)):
        raise InvalidExtractionOutputError("field_conflicts must name distinct, unset text fields")
    if conflicts and facts.discovery_type is not DiscoveryType.EVENT:
        raise InvalidExtractionOutputError("field_conflicts are only reported for events")
    values = facts.field_conflict_values
    if not isinstance(values, tuple) or any(
            not isinstance(item, tuple) or len(item) != 2 or item[0] not in conflicts
            or not isinstance(item[1], str) or not item[1].strip() or len(item[1]) > 500
            for item in values) or len(set(values)) != len(values):
        raise InvalidExtractionOutputError("field_conflict_values must be distinct source wordings of conflicts")

    _reject_mismatched_fields(facts.discovery_type, cleaned)
    return replace(facts, **cleaned)


def _reject_mismatched_fields(discovery_type: DiscoveryType, cleaned: dict[str, object]) -> None:
    if discovery_type is DiscoveryType.OTHER:
        supplied = [name for name in _TEXT_FIELDS if cleaned[name] is not None]
        if supplied:
            raise InvalidExtractionOutputError(
                f"{discovery_type.value} carries no facts, but {', '.join(sorted(supplied))} was supplied"
            )
        return

    forbidden = _PLACE_ONLY_FIELDS if discovery_type is DiscoveryType.EVENT else _EVENT_ONLY_FIELDS
    supplied = [name for name in forbidden if cleaned[name] is not None]
    if supplied:
        raise InvalidExtractionOutputError(
            f"{', '.join(sorted(supplied))} is not a {discovery_type.value} field"
        )


__all__ = ["validate_discovery_facts"]
