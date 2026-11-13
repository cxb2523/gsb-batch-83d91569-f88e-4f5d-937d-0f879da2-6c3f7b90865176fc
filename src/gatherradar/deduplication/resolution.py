"""Source-supported field selection with explicit unresolved conflicts."""
from __future__ import annotations

from dataclasses import replace

from ..domain import Event
from ..domain.event import CanonicalDiagnostic, ChannelProvenance, EventStatus, FieldProvenance
from ..domain.temporal import DatePrecision
from ..domain.occurrence import ScheduleKind, identify_occurrence, occurrence_key
from ..extraction.fields import is_sold_out
from .keys import stable_id, text_key
from .matcher import temporal_reliable
from .models import CandidateContext

TEMPORAL_FIELDS = ("start_date", "end_date", "start_time", "end_time", "timezone",
                   "starts_at", "ends_at", "date_precision")
TEXT_FIELDS = ("title", "summary", "category", "source_date_text", "venue_name", "address",
               "city", "event_format", "price_text", "registration_url", "language",
               "area_text", "location_context", "duration_text", "organizer_name", "availability_text", "source_schedule_text",
               "source_category_text")
FOLDED_FIELDS = frozenset({"title", "venue_name", "address", "city", "category", "language",
                           "area_text", "location_context", "duration_text", "organizer_name", "availability_text",
                           "source_schedule_text", "source_category_text"})
# Narrative source context, not an occurrence fact: never matched on, and
# differing descriptions from several sources are not a factual conflict.
CONTEXT_FIELDS = ("description_text",)


# Strategy of an observation without an explicit acquisition marker: the
# channel's ordinary collection path.
DEFAULT_STRATEGIES = {"website": "website_listing", "instagram": "instagram_profile"}


def channel_provenance(context: CandidateContext) -> ChannelProvenance:
    """The channel that really observed this candidate; never another channel's."""
    channel = context.source.source_type.value
    strategy = context.raw_item.raw_metadata.get("acquisition_strategy")
    return ChannelProvenance(
        candidate_id=context.candidate_id, raw_item_id=context.raw_item.id,
        source_id=context.source.id, publisher_key=context.source.publisher_key, channel=channel,
        strategy=strategy if isinstance(strategy, str) and strategy else DEFAULT_STRATEGIES.get(channel, channel),
        content_url=context.raw_item.content_url, evidence_slot=context.identity_slot)


def anchor_order(context: CandidateContext) -> tuple:
    return (context.first_seen_at, context.raw_item.id, context.identity_slot, context.candidate_id)


def resolve_group(members: tuple[CandidateContext, ...], group_id: str) -> Event:
    ordered = sorted(members, key=anchor_order)
    anchor = ordered[0]
    ids = tuple(sorted(c.candidate_id for c in members))
    diagnostics: list[CanonicalDiagnostic] = []
    provenance: list[FieldProvenance] = []
    values: dict = {}
    event_id = stable_id("event:", (anchor.raw_item.id, anchor.identity_slot))

    def resolve(field: str, pool: list[CandidateContext]):
        populated = [(c, getattr(c.candidate, field)) for c in pool
                     if getattr(c.candidate, field) is not None]
        if not populated:
            return None
        def key(value):
            return text_key(value) if field in FOLDED_FIELDS else value
        distinct = {key(value) for _, value in populated}
        if len(distinct) > 1:
            diagnostics.append(CanonicalDiagnostic("field_conflict", field,
                               tuple(sorted(c.candidate_id for c, _ in populated))))
            return None
        value = populated[0][1]
        provenance.append(FieldProvenance(field, tuple(sorted(
            c.candidate_id for c, v in populated if key(v) == key(value)))))
        return value

    for field in TEXT_FIELDS:
        values[field] = resolve(field, ordered)
    title_owner = next((c.candidate for c in ordered
                        if c.candidate.title == values['title'] and c.candidate.display_title_origin), None)
    if title_owner:
        for field in ('source_title', 'display_title_origin', 'title_evidence_text',
                      'display_title_evidence_ids', 'title_review_required', 'event_detection_reason'):
            values[field] = getattr(title_owner, field)
    values['evidence_fragment_ids'] = tuple(sorted({f for c in ordered
        for f in (*c.candidate.evidence_fragment_ids, *c.candidate.display_title_evidence_ids)}))
    values["extraction_confidence"] = resolve("extraction_confidence", ordered)
    for field in CONTEXT_FIELDS:
        # Earliest-anchored source description, exactly as written; other
        # sources' descriptions remain in their own raw evidence.
        populated = [c for c in ordered if getattr(c.candidate, field) is not None]
        values[field] = getattr(populated[0].candidate, field) if populated else None
        if populated:
            provenance.append(FieldProvenance(field, tuple(sorted(
                c.candidate_id for c in populated
                if getattr(c.candidate, field) == values[field]))))
    for context in ordered:
        for field in getattr(context.candidate, "field_conflicts", ()):
            # Listing and detail explicitly disagreed inside one observation.
            diagnostics.append(CanonicalDiagnostic("source_field_conflict", field, (context.candidate_id,)))

    # Monetary amount and stated unit are inseparable: never combine a free
    # amount from one source with a paid currency from another.
    prices = [(c, (c.candidate.price_amount, c.candidate.currency)) for c in ordered
              if c.candidate.price_amount is not None or c.candidate.currency is not None]
    if prices:
        if len({value for _, value in prices}) == 1:
            values["price_amount"], values["currency"] = prices[0][1]
            for field in ("price_amount", "currency"):
                if values[field] is not None:
                    provenance.append(FieldProvenance(field, tuple(sorted(c.candidate_id for c, _ in prices))))
        else:
            diagnostics.append(CanonicalDiagnostic("field_conflict", "price", tuple(sorted(c.candidate_id for c, _ in prices))))

    # Resolve temporal interpretations atomically. This preserves every chosen
    # tuple as supplied by Stage 7, including partial/range/inferred semantics.
    # Unknown components do not conflict; use an existing tuple that covers the
    # other tuples, never synthesize a new datetime/date-range from fragments.
    temporal = [c for c in ordered if any(getattr(c.candidate, f) is not None
                for f in TEMPORAL_FIELDS if f not in {"date_precision", "timezone"})]
    chosen = None
    if temporal:
        strongest = [c for c in temporal if temporal_reliable(c)] or temporal
        def compatible(a, b):
            return all(getattr(a.candidate, f) is None or getattr(b.candidate, f) is None
                       or getattr(a.candidate, f) == getattr(b.candidate, f)
                       for f in TEMPORAL_FIELDS if f != "date_precision")
        if all(compatible(a, b) for a in strongest for b in strongest):
            covering = [a for a in strongest if all(
                getattr(b.candidate, f) is None or getattr(a.candidate, f) == getattr(b.candidate, f)
                for b in strongest for f in TEMPORAL_FIELDS if f != "date_precision")]
            if covering:
                chosen = covering[0]
        if chosen is None:
            diagnostics.append(CanonicalDiagnostic("unresolved_temporal_interpretations", "temporal", ids))
        elif any(not compatible(chosen, c) for c in temporal):
            diagnostics.append(CanonicalDiagnostic("stronger_explicit_temporal_selected", "temporal", ids))
    if chosen is not None:
        for field in TEMPORAL_FIELDS:
            value = getattr(chosen.candidate, field)
            values[field] = value
            if value is not None:
                provenance.append(FieldProvenance(field, tuple(sorted(c.candidate_id for c in ordered
                    if getattr(c.candidate, field) == value))))
        # Complementary weaker values are still visible through membership and
        # this diagnostic; no information is silently interpreted as absent.
        if any(getattr(c.candidate, f) is not None and values[f] is None
               for c in temporal for f in TEMPORAL_FIELDS):
            diagnostics.append(CanonicalDiagnostic("partial_temporal_not_combined", "temporal", ids))
    else:
        values["date_precision"] = DatePrecision.UNKNOWN
        values["timezone"] = resolve("timezone", ordered)

    for context in ordered:
        for code in context.candidate.extraction_diagnostics:
            diagnostics.append(CanonicalDiagnostic("extraction:" + code, "extraction", (context.candidate_id,)))
        for diagnostic in context.outcome.diagnostics:
            diagnostics.append(CanonicalDiagnostic("normalization:" + diagnostic.code, diagnostic.field,
                                                   (context.candidate_id,)))
    # Occurrences carry their own evidence and own commercial facts. Combining
    # a canonical Event never lends an Event price to an individual session.
    occurrences = {}
    conflicting_session_keys = set()
    for context in ordered:
        for supplied in context.candidate.occurrences:
            key = occurrence_key(supplied)
            value = supplied
            if key in conflicting_session_keys:
                value = replace(value, diagnostics=tuple(sorted(set(value.diagnostics) | {"occurrence_temporal_conflict"})))
                key = occurrence_key(value)
            previous = occurrences.get(key)
            if previous is not None and any(
                getattr(previous, field) is not None and getattr(value, field) is not None
                and getattr(previous, field) != getattr(value, field)
                for field in TEMPORAL_FIELDS if field != "date_precision"
            ):
                conflicting_session_keys.add(key)
                del occurrences[key]
                previous = replace(previous, diagnostics=tuple(sorted(set(previous.diagnostics) | {"occurrence_temporal_conflict"})))
                value = replace(value, diagnostics=tuple(sorted(set(value.diagnostics) | {"occurrence_temporal_conflict"})))
                occurrences[occurrence_key(previous)] = identify_occurrence(previous, event_id)
                key = occurrence_key(value)
                diagnostics.append(CanonicalDiagnostic("occurrence_temporal_conflict", "occurrences",
                                                       tuple(sorted(set(previous.candidate_ids) | set(value.candidate_ids)))))
                previous = occurrences.get(key)
            if previous is not None:
                changes = {}
                for field in ("source_item_ids", "candidate_ids", "evidence_urls", "evidence_fragment_ids", "diagnostics"):
                    changes[field] = tuple(sorted(set(getattr(previous, field)) | set(getattr(value, field))))
                for field in ("price_text", "price_amount", "currency", "price_per_person", "unit_price",
                              "host_discount_pct", "platform_discount_pct", "availability_text", "remaining_seats", "enabled",
                              "source_sold_out", "capacity_limit"):
                    a, b = getattr(previous, field), getattr(value, field)
                    changes[field] = a if b is None or a == b else b if a is None else None
                    if a is not None and b is not None and a != b:
                        diagnostics.append(CanonicalDiagnostic("occurrence_field_conflict", field,
                                                               changes["candidate_ids"]))
                for field in TEMPORAL_FIELDS:
                    if getattr(previous, field) is None and getattr(value, field) is not None:
                        changes[field] = getattr(value, field)
                value = replace(previous, **changes)
            occurrences[key] = identify_occurrence(value, event_id)
    # A date-only source can corroborate one precise session. It is not itself
    # another session. If several sessions could fit, keep the ambiguity visible.
    for key, value in tuple(occurrences.items()):
        if value.source_session_id or value.start_time is not None or value.end_date is not None:
            continue
        covering = [(other_key, other) for other_key, other in occurrences.items()
                    if other_key != key and other.start_date == value.start_date
                    and other.end_date is None and other.start_time is not None
                    and other.timezone == value.timezone]
        if len(covering) == 1:
            other_key, other = covering[0]
            occurrences[other_key] = replace(other, **{
                field: tuple(sorted(set(getattr(other, field)) | set(getattr(value, field))))
                for field in ("source_item_ids", "candidate_ids", "evidence_urls", "evidence_fragment_ids", "diagnostics")
            })
            del occurrences[key]
    values["occurrences"] = tuple(occurrences[key] for key in sorted(occurrences))
    kinds = {c.candidate.schedule_kind for c in ordered} - {ScheduleKind.UNKNOWN}
    values["schedule_kind"] = (next(iter(kinds)) if len(kinds) == 1 else ScheduleKind.CONFLICT if kinds
                               else ScheduleKind.UNKNOWN)
    if conflicting_session_keys:
        values["schedule_kind"] = ScheduleKind.CONFLICT
    rules = {c.candidate.recurrence_rule for c in ordered if c.candidate.recurrence_rule}
    values["recurrence_rule"] = next(iter(rules)) if len(rules) == 1 else None
    if len(values["occurrences"]) > 1:
        # A canonical multi-session Event has no arbitrary primary occurrence.
        for field in TEMPORAL_FIELDS:
            if field != "timezone":
                values[field] = DatePrecision.UNKNOWN if field == "date_precision" else None
        provenance = [p for p in provenance if p.field not in TEMPORAL_FIELDS or p.field == "timezone"]
        if values["schedule_kind"] not in {ScheduleKind.CONFLICT, ScheduleKind.RECURRING}:
            values["schedule_kind"] = ScheduleKind.DISCRETE
    for field in ("occurrences", "schedule_kind", "recurrence_rule"):
        if values[field]:
            provenance.append(FieldProvenance(field, tuple(c.candidate_id for c in ordered
                                                          if getattr(c.candidate, field))))
    if values["title"] is None:
        diagnostics.append(CanonicalDiagnostic("missing_canonical_title", "title", ids))
    url = anchor.candidate.evidence_url or anchor.raw_item.content_url
    provenance.append(FieldProvenance("canonical_source_url", (anchor.candidate_id,)))
    # Lifecycle status only from explicit sold-out wording; availability itself
    # never participates in matching or identity.
    status = EventStatus.SOLD_OUT if is_sold_out(values["availability_text"]) else EventStatus.UNKNOWN
    if status is EventStatus.UNKNOWN and values["occurrences"] and all(
            "source_session_sold_out" in o.diagnostics for o in values["occurrences"]):
        # Every public session carries a verified, uncontradicted sold-out flag.
        status = EventStatus.SOLD_OUT
    return Event(
        status=status,
        event_id=event_id,
        canonical_source_url=url,
        first_seen_at=min(c.first_seen_at for c in members),
        last_seen_at=max(c.raw_item.captured_at for c in members),
        identity_anchor_raw_item_id=anchor.raw_item.id, identity_anchor_slot=anchor.identity_slot,
        candidate_ids=ids,
        source_item_ids=tuple(sorted({c.raw_item.id for c in members})),
        source_ids=tuple(sorted({c.source.id for c in members})),
        publisher_keys=tuple(sorted({c.source.publisher_key for c in members})),
        evidence_urls=tuple(sorted({u for c in members for u in
                                  (c.candidate.evidence_url, c.raw_item.content_url) if u})),
        duplicate_group_id=group_id,
        field_provenance=tuple(sorted(provenance, key=lambda p: p.field)),
        diagnostics=tuple(sorted(set(diagnostics), key=lambda d: (d.code, d.field, d.candidate_ids))),
        reference_urls=tuple(dict.fromkeys(u for c in ordered for u in getattr(c.candidate, "reference_urls", ()))),
        channel_provenance=tuple(sorted({channel_provenance(c) for c in members}, key=lambda p: p.candidate_id)),
        conflicting_values=tuple(dict.fromkeys(
            (field, value) for c in ordered for field, value in getattr(c.candidate, "field_conflict_values", ())
            if values.get(field) is None)),
        **values,
    )
