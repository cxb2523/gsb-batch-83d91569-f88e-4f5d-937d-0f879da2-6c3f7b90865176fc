"""Deterministic complete-link batches, with failure isolation and retained inputs."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from itertools import combinations
from datetime import date, datetime, time
from decimal import Decimal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ..domain import EventCandidate, PlaceCandidate
from ..domain.event import CanonicalDiagnostic
from ..domain.raw_item import _require_aware
from ..domain.temporal import DatePrecision
from ..domain.occurrence import EventOccurrence, ScheduleKind
from .keys import stable_id
from .matcher import match_pair
from .models import CandidateContext, CanonicalizationResult, DuplicateDecision, DuplicateGroup, MatchKind
from .resolution import resolve_group, CONTEXT_FIELDS, TEMPORAL_FIELDS, TEXT_FIELDS


def validate_context(context: CandidateContext) -> None:
    c = context.candidate
    raw, source = context.raw_item, context.source
    if (not isinstance(c, (EventCandidate, PlaceCandidate)) or type(c) is not type(context.original)
            or c.candidate_id != context.original.candidate_id
            or c.raw_item_id != raw.id or context.original.raw_item_id != raw.id
            or raw.source_id != source.id or raw.source_type != source.source_type):
        raise ValueError("context mismatch")
    _require_aware(context.first_seen_at, "first_seen_at")
    if context.first_seen_at > raw.captured_at or not context.identity_slot.strip():
        raise ValueError("invalid identity metadata")
    if isinstance(c, PlaceCandidate):
        return
    if c.is_event is not True or not isinstance(c.date_precision, DatePrecision):
        raise ValueError("invalid event")
    if (not isinstance(c.schedule_kind, ScheduleKind)
            or not isinstance(c.occurrences, tuple)
            or any(not isinstance(o, EventOccurrence) or c.candidate_id not in o.candidate_ids
                   or raw.id not in o.source_item_ids for o in c.occurrences)):
        raise ValueError("invalid occurrence provenance")
    for value in (c.evidence_url, c.registration_url, raw.content_url):
        if value is None:
            continue
        url = urlsplit(value)
        if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
                or any(char.isspace() for char in value)):
            raise ValueError("invalid evidence URL")
        url.port
    for field in (*TEXT_FIELDS, *CONTEXT_FIELDS):
        value = getattr(c, field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError("invalid text")
    if not isinstance(c.field_conflicts, tuple) or any(f not in TEXT_FIELDS for f in c.field_conflicts):
        raise ValueError("invalid field conflicts")
    for field in ("start_date", "end_date"):
        value = getattr(c, field)
        if value is not None and type(value) is not date:
            raise ValueError("invalid date")
    for field in ("start_time", "end_time"):
        value = getattr(c, field)
        if value is not None and (not isinstance(value, time) or value.tzinfo is not None):
            raise ValueError("invalid local time")
    if c.timezone is not None:
        ZoneInfo(c.timezone)
    if ((c.date_precision is not DatePrecision.UNKNOWN and c.start_date is None)
            or (c.date_precision is DatePrecision.EXACT and c.starts_at is None)
            or (c.date_precision is DatePrecision.RANGE and c.end_date is None)
            or (c.end_date is not None and (c.start_date is None or c.end_date < c.start_date))):
        raise ValueError("inconsistent temporal precision")
    for field in ("starts_at", "ends_at"):
        value = getattr(c, field)
        if value is not None:
            if not isinstance(value, datetime):
                raise ValueError("invalid timestamp")
            _require_aware(value, field)
            clock = c.start_time if field == "starts_at" else c.end_time
            if not c.timezone or not c.start_date or clock is None:
                raise ValueError("missing timestamp components")
            local = value.astimezone(ZoneInfo(c.timezone))
            if local.date() != c.start_date or local.time() != clock or c.end_date is not None:
                raise ValueError("inconsistent timestamp components")
    if c.price_amount is not None and (isinstance(c.price_amount, bool)
            or not isinstance(c.price_amount, (int, Decimal))
            or not Decimal(c.price_amount).is_finite() or c.price_amount < 0):
        raise ValueError("invalid price")
    if c.currency is not None and (not isinstance(c.currency, str) or not c.currency.strip()):
        raise ValueError("invalid currency")
    # Only actual normalization outcomes may supply normalized fields.
    if context.outcome.temporal is None or any(getattr(c, f) != getattr(context.outcome.temporal, f)
                                               for f in (*TEMPORAL_FIELDS, "occurrences", "schedule_kind", "recurrence_rule")):
        raise ValueError("missing or inconsistent normalization")
    if (c.price_amount, c.currency) != (context.outcome.price.price_amount, context.outcome.price.currency):
        raise ValueError("inconsistent price normalization")


def canonicalize(contexts: Iterable[CandidateContext]) -> CanonicalizationResult:
    supplied = tuple(contexts)
    valid, rejected, places, diagnostics = [], [], [], []
    for context in supplied:
        try:
            validate_context(context)
        except Exception:
            rejected.append(context)
            diagnostics.append(CanonicalDiagnostic("invalid_candidate_context", "candidate", (context.candidate_id,)))
            continue
        if isinstance(context.candidate, PlaceCandidate):
            places.append(context.candidate)
        else:
            valid.append(context)
    # Ambiguous repeated inputs are quarantined rather than selecting by order.
    id_counts = Counter(c.candidate_id for c in valid)
    slot_counts = Counter((c.raw_item.id, c.identity_slot) for c in valid)
    accepted = []
    for context in valid:
        if id_counts[context.candidate_id] > 1 or slot_counts[context.raw_item.id, context.identity_slot] > 1:
            rejected.append(context)
            diagnostics.append(CanonicalDiagnostic("ambiguous_identity_input", "candidate", (context.candidate_id,)))
        else:
            accepted.append(context)
    accepted.sort(key=lambda c: c.candidate_id)
    decisions = []
    for a, b in combinations(accepted, 2):
        try:
            decisions.append(match_pair(a, b))
        except Exception:
            decisions.append(DuplicateDecision((a.candidate_id, b.candidate_id), MatchKind.INSUFFICIENT,
                                                ("matching_failed",)))
            diagnostics.append(CanonicalDiagnostic("matching_failed", "pair", (a.candidate_id, b.candidate_id)))
    lookup = {d.candidate_ids: d.kind for d in decisions}
    groups: list[list[CandidateContext]] = []
    for context in accepted:
        for group in groups:
            if all(lookup[tuple(sorted((context.candidate_id, member.candidate_id)))] is MatchKind.SAME_EVENT
                   for member in group):
                group.append(context)
                break
        else:
            groups.append([context])
    events, auto_groups = [], []
    for group in groups:
        ids = tuple(c.candidate_id for c in group)
        group_id = stable_id("duplicate:", ids)
        try:
            event = resolve_group(tuple(group), group_id)
        except Exception:
            rejected.extend(group)
            diagnostics.append(CanonicalDiagnostic("canonicalization_failed", "group", ids))
            continue
        events.append(event)
        if len(group) > 1:
            auto_groups.append(DuplicateGroup(group_id, ids))
    membership = {cid: e.event_id for e in events for cid in e.candidate_ids}
    possible = [d for d in decisions if d.kind is MatchKind.POSSIBLE_DUPLICATE]
    # A SAME edge blocked by complete-link still deserves review, not silence.
    for decision in decisions:
        a, b = decision.candidate_ids
        if decision.kind is MatchKind.SAME_EVENT and membership.get(a) != membership.get(b):
            possible.append(DuplicateDecision(decision.candidate_ids, MatchKind.POSSIBLE_DUPLICATE,
                                             tuple(sorted(decision.reasons + ("all_member_grouping_blocked",)))))
    return CanonicalizationResult(
        events=tuple(sorted(events, key=lambda e: e.event_id)),
        groups=tuple(sorted(auto_groups, key=lambda g: g.candidate_ids)),
        decisions=tuple(decisions), possible_duplicates=tuple(sorted(possible, key=lambda d: d.candidate_ids)),
        places=tuple(sorted(places, key=lambda c: c.candidate_id)),
        contexts=tuple(sorted(supplied, key=lambda c: c.candidate_id)),
        rejected=tuple(sorted(rejected, key=lambda c: c.candidate_id)),
        diagnostics=tuple(sorted(set(diagnostics), key=lambda d: (d.code, d.field, d.candidate_ids))),
    )
