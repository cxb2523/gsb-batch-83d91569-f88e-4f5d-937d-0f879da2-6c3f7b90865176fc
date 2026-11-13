"""The deterministic, free discovery provider.

This is GatherRadar's default: no model, no API key, no network access, no cost. It
reads the signals found in the source text, scores them with the weights in `rules`,
and decides between an event, a place, and neither — then reports why.

Two ideas keep it honest.

**No single keyword decides anything.** An event needs a recognized path through the
evidence, not one word. Two paths are legitimate, because real captions come in two
shapes:

* **Path A** — event terminology together with date, time, or registration evidence.
  The classic announcement.
* **Path B** — strong event terminology or a validated named event, together with an
  invitation to attend, plus venue or location context when the terminology alone is
  not specific enough. This is the shape of a post that says where to come and when
  they are waiting for you without ever printing a date, and requiring a date was the
  tuning mistake that made the first version of this engine too strict.

An attendance invitation alone never creates an event, and neither does a date alone,
an address alone, or an event word alone.

**Evidence that it already happened counts against it, but never vetoes.** A recap
carries retrospective phrases; a post that is both a recap and an announcement of the
next occurrence can still outweigh them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..domain import DiscoveryType
from . import fields, rules
from .models import DiscoveryEvidence, DiscoveryFacts, ExtractionInput
from .signals import SignalSet, analyze
from .text import normalize
from .titles import caption_description, event_title, resolve_title
from .detection import context_diagnostic

PROVIDER_NAME = "rule-based/1"

REASON_EVENT_PATH_A = "event: terminology with date, time, or registration evidence"
REASON_EVENT_PATH_B = "event: event terminology with attendance and venue context"
REASON_EVENT_STRUCTURED = "event: verified detail date/time slot with attendance or price evidence"
REASON_PLACE ="place: place vocabulary with descriptive or visit context"
REASON_NO_EVENT_PATH = "other: no event or place path was satisfied"
REASON_BELOW_THRESHOLD = "other: evidence did not outweigh the score threshold"


@dataclass(frozen=True, slots=True)
class Scores:
    event: float = 0.0
    place: float = 0.0
    negative: float = 0.0

    @property
    def net_event(self) -> float:
        return self.event - self.negative

    @property
    def net_place(self) -> float:
        return self.place - self.negative


def score(found: SignalSet) -> Scores:
    """Add up the weighted evidence. Distinct terms count, repetitions do not."""
    event = 0.0
    strong = found.distinct_terms(found.event_strong)
    if strong:
        event += rules.WEIGHT_EVENT_TERM_STRONG + min(
            (strong - 1) * rules.WEIGHT_EVENT_TERM_STRONG_EXTRA, rules.MAX_EVENT_TERM_STRONG_EXTRA
        )
    weak = found.distinct_terms(found.event_weak)
    if weak:
        event += min(weak * rules.WEIGHT_EVENT_TERM_WEAK, rules.MAX_EVENT_TERM_WEAK)
    if found.named_event is not None:
        event += rules.WEIGHT_NAMED_EVENT
    if found.dates:
        event += rules.WEIGHT_DATE
    if found.times:
        event += rules.WEIGHT_TIME
    if found.registration:
        event += rules.WEIGHT_REGISTRATION
    if found.attendance:
        event += rules.WEIGHT_ATTENDANCE
    if found.prices:
        event += rules.WEIGHT_PRICE
    if found.locations:
        event += rules.WEIGHT_LOCATION

    place = 0.0
    place_terms = found.distinct_terms(found.place_terms)
    if place_terms:
        place += rules.WEIGHT_PLACE_TERM + min(
            (place_terms - 1) * rules.WEIGHT_PLACE_TERM_EXTRA, rules.MAX_PLACE_TERM_EXTRA
        )
    if found.place_context:
        place += rules.WEIGHT_PLACE_CONTEXT
    if found.locations:
        place += rules.WEIGHT_PLACE_LOCATION

    negative = found.distinct_terms(found.retrospective) * rules.WEIGHT_RETROSPECTIVE
    return Scores(event=event, place=place, negative=negative)


def classify(found: SignalSet) -> tuple[DiscoveryType, Scores, str]:
    """Decide what the observation is, and say why in one sentence."""
    scores = score(found)
    diagnostic = context_diagnostic(found.text)
    if diagnostic:
        return DiscoveryType.OTHER, scores, diagnostic

    has_event_term = bool(found.event_strong or found.event_weak)
    has_strong_term = bool(found.event_strong)
    # A bare link is not occurrence evidence: Instagram captions carry links for
    # every reason. Registration has to be said in words to count.
    # A month name in an OCR logo ("October Festival") is not a schedule.
    month_names = {normalize(m) for m in rules.JALALI_MONTHS + rules.JALALI_MONTH_FORMS + rules.GREGORIAN_MONTHS}
    temporal = fields.source_date_text(found) or ''
    meaningful_dates = any(normalize(s.text).strip() not in month_names for s in found.dates)
    has_occurrence_evidence = bool((found.dates and (meaningful_dates or any(c.isdigit() for c in temporal)))
                                   or found.times or found.registration)
    has_location_context = bool(found.locations or found.place_terms)

    path_a = has_event_term and has_occurrence_evidence
    path_b = bool(found.attendance) and (
        (has_strong_term and found.named_event is not None)
        or (has_strong_term and has_location_context)
    )

    if path_a or path_b:
        if scores.net_event >= rules.EVENT_SCORE_THRESHOLD:
            return DiscoveryType.EVENT, scores, REASON_EVENT_PATH_A if path_a else REASON_EVENT_PATH_B
        return DiscoveryType.OTHER, scores, REASON_BELOW_THRESHOLD

    place_path = bool(found.place_terms) and bool(found.place_context or found.locations)
    if place_path and scores.net_place >= rules.PLACE_SCORE_THRESHOLD:
        return DiscoveryType.PLACE, scores, REASON_PLACE

    return DiscoveryType.OTHER, scores, REASON_NO_EVENT_PATH


def _evidence(found: SignalSet, scores: Scores, reason: str) -> DiscoveryEvidence:
    return DiscoveryEvidence(
        event_score=round(scores.event, 2),
        place_score=round(scores.place, 2),
        negative_score=round(scores.negative, 2),
        matched_signals=found.labels_of(found.positive),
        negative_signals=found.labels_of(found.retrospective),
        reason=reason,
    )


def _event_facts(found: SignalSet, evidence: DiscoveryEvidence) -> DiscoveryFacts:
    return DiscoveryFacts(
        discovery_type=DiscoveryType.EVENT,
        title=fields.title(found, found.named_event),
        category=fields.category(found),
        source_date_text=fields.source_date_text(found),
        venue_name=fields.venue_name(found),
        address=fields.address(found),
        city=fields.city(found),
        event_format=fields.event_format(found),
        price_text=fields.price_text(found),
        registration_url=fields.registration_url(found),
        language=found.language,
        evidence=evidence,
        area_text=fields.area_text(found),
        location_context=fields.location_context(found),
        duration_text=fields.duration_text(found),
        organizer_name=fields.organizer_name(found),
        availability_text=fields.availability_text(found),
        reference_urls=fields.reference_urls(found),
    )


def _place_facts(found: SignalSet, evidence: DiscoveryEvidence) -> DiscoveryFacts:
    return DiscoveryFacts(
        discovery_type=DiscoveryType.PLACE,
        title=fields.title(found, found.named_place),
        summary=fields.place_summary(found),
        category=fields.place_category(found),
        address=fields.address(found),
        city=fields.city(found),
        price_text=fields.price_text(found),
        opening_hours_text=fields.opening_hours_text(found),
        language=found.language,
        evidence=evidence,
    )


# Simple facts read from each evidence fragment separately and compared. Temporal
# wording, titles and categories are read from the whole unit, as before.
MERGED_FIELDS = {
    "location_context": fields.location_context,
    "price_text": fields.price_text, "venue_name": fields.venue_name, "address": fields.address,
    "city": fields.city, "area_text": fields.area_text, "duration_text": fields.duration_text,
    "organizer_name": fields.organizer_name, "availability_text": fields.availability_text,
}
_ORIGIN_ORDER = {"detail": 0, "listing": 1}


def _agreement_key(value: str) -> str:
    # Wording-level comparison only: spacing and digit script never disagree.
    return "".join(normalize(value).split())


def _merge_evidence(facts: DiscoveryFacts, extraction_input: ExtractionInput) -> DiscoveryFacts:
    """Combine a page with its own listing card and adapter-verified structure.

    Precedence contract: an adapter-verified structural value (a dedicated price
    badge, a fixed header slot, a labelled card/section field) outranks a value
    read from free text, which may be a prose mention (e.g. a breakfast cost in
    a description). Values of the same tier from several places must agree:
    identical facts keep one exact wording (detail first); explicitly different
    values are never chosen between — the field stays null and is named in
    `field_conflicts`. A fact only one place states (a list-only price) is kept.
    """
    structural: dict[str, list[tuple[str, str]]] = {}
    for source_field in extraction_input.source_fields:
        structural.setdefault(source_field.name, []).append((source_field.origin, source_field.value))
    textual: dict[str, list[tuple[str, str]]] = {}
    if extraction_input.segments:
        for origin, text in extraction_input.segments:
            found = analyze(text)
            for name, reader in MERGED_FIELDS.items():
                if value := reader(found):
                    textual.setdefault(name, []).append((origin, value))
    else:
        for name in MERGED_FIELDS:
            if value := getattr(facts, name):
                textual.setdefault(name, []).append(("text", value))

    updates: dict[str, str | None] = {name: None for name in MERGED_FIELDS}
    conflicts = []
    conflict_values: list[tuple[str, str]] = []

    def keep(name: str, values) -> None:
        seen = set()
        for value in values:
            if _agreement_key(value) not in seen:
                seen.add(_agreement_key(value))
                conflict_values.append((name, value.strip()[:500]))
    for name in {*structural, *textual}:
        found_values = structural.get(name) or textual[name]
        if len({_agreement_key(value) for _, value in found_values}) > 1:
            updates[name] = None
            conflicts.append(name)
            keep(name, [value for _, value in found_values])
            continue
        updates[name] = min(found_values, key=lambda item: _ORIGIN_ORDER.get(item[0], 2))[1]
    if updates.get("duration_text") and "duration_text" not in conflicts:
        # A header length and an explicit "به مدت …" sentence on the same item
        # that disagree are both source facts; neither is chosen.
        stated = fields.duration_minutes(updates["duration_text"])
        narrative = fields.narrative_durations(analyze(extraction_input.raw_text))
        others = {fields.duration_minutes(v) for v in narrative}
        if stated is not None and others - {None, stated}:
            keep("duration_text", [updates["duration_text"],
                                   *(v for v in narrative if fields.duration_minutes(v) not in (None, stated))])
            updates["duration_text"] = None
            conflicts.append("duration_text")
    if "source_category_text" in structural:
        # An explicit source category label outranks free-text keyword inference:
        # the canonical category is only its supported exact mapping, else null.
        label = updates.get("source_category_text")
        updates["category"] = rules.EVENT_CATEGORIES.get(normalize(label).strip()) if label else None
    return replace(facts, **updates, field_conflicts=tuple(sorted(conflicts)),
                   field_conflict_values=tuple(dict.fromkeys(v for v in conflict_values if v[1])))


def structured_occurrence(found: SignalSet, extraction_input: ExtractionInput) -> bool:
    """Concrete attendable occurrence stated in adapter-verified detail structure.

    Requires the item's own detail page to state a fixed date slot holding both a
    date and a clock time, plus price, registration or attendance evidence, with
    the event evidence outweighing retrospective wording. Listing/source context
    alone, a date without a time, or free-text dates never qualify.
    """
    dates = [f.value for f in extraction_input.source_fields
             if f.name == "source_date_text" and f.origin == "detail"]
    if len(dates) != 1:
        return False
    slot = analyze(dates[0])
    if not (slot.dates and slot.times):
        return False
    attendable = bool(found.prices or found.registration or found.attendance) or any(
        f.name == "price_text" for f in extraction_input.source_fields)
    return attendable and score(found).net_event > 0


class RuleBasedDiscoveryProvider:
    """A DiscoveryProvider that classifies and extracts with deterministic rules only.

    It is source-neutral: it reads `ExtractionInput`, so the same engine will serve
    website observations and any later public source family without change. It never
    reaches the outside world, so it cannot fail for operational reasons and never
    raises ProviderExtractionError.
    """

    name = PROVIDER_NAME

    def discover(self, extraction_input: ExtractionInput) -> DiscoveryFacts:
        found = analyze(extraction_input.raw_text)
        discovery_type, scores, reason = classify(found)
        if ((discovery_type is DiscoveryType.OTHER and structured_occurrence(found, extraction_input))
                or (extraction_input.source_sessions and isinstance(extraction_input.source_title, str)
                    and extraction_input.source_title.strip()
                    and extraction_input.source_title in extraction_input.raw_text)):
            discovery_type, reason = DiscoveryType.EVENT, REASON_EVENT_STRUCTURED
        evidence = _evidence(found, scores, reason)

        if discovery_type is DiscoveryType.EVENT:
            facts = _event_facts(found, evidence)
            resolved = resolve_title(extraction_input)
            diagnostics = () if resolved.title else event_title(found)[1]
            facts = replace(facts, title=resolved.title, extraction_diagnostics=diagnostics,
                            source_title=resolved.source_title, display_title_origin=resolved.origin,
                            title_evidence_text=resolved.evidence_text, title_review_required=resolved.review_required,
                            event_detection_reason=reason)
            # Classification is unchanged. An explicit retained heading can name
            # an already-classified Event; arbitrary first lines cannot.
            title = extraction_input.source_title
            if (isinstance(title,str) and 0 < len(title.strip()) <= 500
                    and title in extraction_input.raw_text):
                facts = replace(facts,title=title)
                facts = replace(facts, extraction_diagnostics=())
            else:
                title = None
            captions = [text for origin, text in extraction_input.segments if origin == 'caption']
            if len(captions) == 1:
                description, caption_diagnostics = caption_description(captions[0])
                facts = replace(facts, description_text=description,
                                extraction_diagnostics=(*facts.extraction_diagnostics, *caption_diagnostics))
            facts = replace(facts, source_schedule_text=fields.source_schedule_text(found, exclude=title),
                            source_sessions=extraction_input.source_sessions,
                            source_session_diagnostics=extraction_input.source_session_diagnostics)
            return _merge_evidence(facts, extraction_input)
        if discovery_type is DiscoveryType.PLACE:
            return _place_facts(found, evidence)
        # "Other" means analyzed and found unrelated, so it carries no facts.
        return DiscoveryFacts(discovery_type=DiscoveryType.OTHER, evidence=evidence)


__all__ = [
    "PROVIDER_NAME",
    "REASON_BELOW_THRESHOLD",
    "REASON_EVENT_PATH_A",
    "REASON_EVENT_PATH_B",
    "REASON_EVENT_STRUCTURED",
    "REASON_NO_EVENT_PATH",
    "REASON_PLACE",
    "RuleBasedDiscoveryProvider",
    "Scores",
    "classify",
    "score",
    "structured_occurrence",
]
