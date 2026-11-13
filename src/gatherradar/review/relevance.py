"""Pure run-time schedule decisions. No wall clock, persistence or recurrence expansion."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..domain import Event
from ..normalization.temporal import _local_datetime

DISPOSITIONS = ('actionable', 'expired', 'beyond_horizon', 'needs_schedule_review', 'otherwise_excluded')
TEMPORAL_FIELDS = {'temporal', 'source_date_text', 'source_schedule_text', 'occurrences',
                   'source_sessions', 'start_date', 'end_date', 'start_time', 'end_time', 'timezone'}
UNSAFE = ('conflict', 'unresolved', 'weekday_mismatch', 'invalid', 'unparsed', 'ambiguous',
          'schema_drift', 'unreliable_temporal_ocr', 'unverified_shape')
# Session shapes not yet verified. They hold an upcoming session in review but
# never question its own source date, so a passed session still expires.
# Booking facts (sold-out flags, seats) never decide temporal relevance.
HELD = ('unverified_shape',)


def _held(code: str) -> bool:
    return any(word in code for word in HELD)


@dataclass(frozen=True)
class ScheduleDisposition:
    event_id: str
    disposition: str
    reason: str
    occurrence_ids: tuple[str, ...] = ()
    occurrence_dispositions: tuple[tuple[str, str, str], ...] = ()


def disposition_counts(values: tuple[ScheduleDisposition, ...]) -> dict[str, int]:
    counts = Counter(v.disposition for v in values)
    return {name: counts[name] for name in DISPOSITIONS}


def _unsafe(codes) -> bool:
    return any(word in code for code in codes for word in UNSAFE)


def _dated(value, reference: datetime, horizon: datetime, codes=()) -> tuple[str, str]:
    if value.start_date is None or value.date_precision == 'unknown' or _unsafe(codes):
        return 'needs_schedule_review', 'unresolved_date_or_clock'
    try:
        zone = ZoneInfo(value.timezone)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return 'needs_schedule_review', 'unknown_timezone'
    end_day = value.end_date or value.start_date
    if end_day < value.start_date:
        return 'needs_schedule_review', 'reversed_date_range'
    start = _local_datetime(value.start_date, time.min, zone)
    # End-of-day is a comparison boundary only, never an invented Event end.
    day_after = _local_datetime(end_day + timedelta(days=1), time.min, zone)
    if start is None or day_after is None:
        return 'needs_schedule_review', 'ambiguous_date_boundary'
    end = None
    if value.end_date is None:
        end = value.ends_at
        if end is None and value.end_time is not None:
            if value.start_time is not None and value.end_time <= value.start_time:
                return 'needs_schedule_review', 'unresolved_overnight_clock'
            end = _local_datetime(end_day, value.end_time, zone)
            if end is None:
                return 'needs_schedule_review', 'ambiguous_end_time'
    elif value.end_time is not None:
        # Daily hours are not a continuous start-to-end interval. Only the final
        # day's supported closing time can prove that the whole range has ended.
        if value.start_time is not None and value.end_time <= value.start_time:
            return 'needs_schedule_review', 'unresolved_range_hours'
        end = _local_datetime(end_day, value.end_time, zone)
        if end is None:
            return 'needs_schedule_review', 'ambiguous_end_time'
    if end is not None and end <= reference:
        return 'expired', 'supported_end_reached'
    if end is None and day_after <= reference:
        return 'expired', 'last_date_passed'
    # Horizon is exclusive midnight after the last included Tehran date.
    if (value.starts_at or start) >= horizon:
        return 'beyond_horizon', 'starts_after_horizon'
    return 'actionable', 'ongoing_or_upcoming'


def assess_relevance(event: Event, started_at: datetime, days: int = 14,
                     review_timezone: str = 'Asia/Tehran') -> ScheduleDisposition:
    if type(days) is not int or not 1 <= days <= 90:
        raise ValueError('days must be between 1 and 90')
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError('run start must be timezone-aware')
    # Presentation timezone is accepted for existing callers, but actionable
    # membership always follows the owner's explicit Tehran review contract.
    ZoneInfo(review_timezone)
    reference = started_at.astimezone(ZoneInfo('Asia/Tehran'))
    horizon = datetime.combine(reference.date() + timedelta(days=days + 1), time.min,
                               tzinfo=ZoneInfo('Asia/Tehran'))
    def result(kind, reason, ids=(), occurrences=()):
        return ScheduleDisposition(event.event_id, kind, reason, ids, occurrences)
    if event.status in {'cancelled', 'postponed'}:
        return result('otherwise_excluded', 'explicit_' + event.status.value)
    codes = [d.code for d in event.diagnostics if d.field in TEMPORAL_FIELDS
             or 'unreliable_temporal_ocr' in d.code]
    if event.schedule_kind == 'conflict':
        return result('needs_schedule_review', 'conflicting_schedule')
    if event.occurrences:
        def session(o):
            codes = [c for c in o.diagnostics if not any(w in c for w in ('price', 'discount', 'availability'))]
            kind, reason = _dated(o, reference, horizon, [c for c in codes if not _held(c)])
            # An unverified session shape leaves its booking facts unknown, never its
            # own source date: a session that has ended is expired, otherwise review.
            if kind != 'expired' and any(_held(c) for c in codes):
                return o.occurrence_id, 'needs_schedule_review', (
                    'unverified_timeslot' if any('timeslot' in c for c in codes) else 'unverified_session_shape')
            return o.occurrence_id, kind, reason
        sessions = tuple(session(o) for o in event.occurrences)
        ids = tuple(key for key, kind, _ in sessions if kind == 'actionable')
        if ids:
            return result('actionable', 'supported_occurrences_in_window', ids, sessions)
        kinds = {kind for _, kind, _ in sessions}
        bounded_range = all(o.end_date is not None and not _unsafe(o.diagnostics) for o in event.occurrences)
        # Unverified session shape is judged per session above, by its own date.
        event_codes = [c for c in codes if not _held(c)]
        if 'needs_schedule_review' in kinds or (_unsafe(event_codes) and not bounded_range) or event.schedule_kind == 'recurring':
            return result('needs_schedule_review', 'unresolved_sessions', occurrences=sessions)
        if 'beyond_horizon' in kinds:
            return result('beyond_horizon', 'remaining_sessions_after_horizon', occurrences=sessions)
        return result('expired', 'all_sessions_ended', occurrences=sessions)
    if event.schedule_kind == 'recurring' or event.recurrence_rule:
        return result('needs_schedule_review', 'recurrence_without_verified_instances')
    kind, reason = _dated(event, reference, horizon, codes)
    if event.status == 'expired' and kind == 'actionable':
        # An explicit stale status conflicting with the schedule is reviewable.
        return result('needs_schedule_review', 'expired_status_conflicts_with_schedule')
    return result(kind, reason)


def relevant_document(document: dict, *, include_filtered: bool = False) -> dict:
    """Project persisted facts at their stored run time; keep history untouched.

    Dispositions cover the complete canonical input on the repository path.
    Repeated exporter guards retain that full-run ledger and are idempotent.
    """
    from .eligibility import eligible, eligible_document
    from .records import event_from_record, primitive
    supplied = {r['event_id']: r for r in (*document['events'], *document.get('schedule_review', ()))}
    removed = {key for key, record in supplied.items() if not eligible(record)}
    document = eligible_document(dict(document, events=list(supplied.values())))
    run = dict(document['run'])
    reference = datetime.fromisoformat(run['started_at'])
    records = {r['event_id']: r for r in document['events']}
    ledger = {d['event_id']: dict(d) for d in document.get('event_dispositions', ())
              if d['event_id'] not in removed and (d['event_id'] in records
                 or d['disposition'] not in {'actionable', 'needs_schedule_review'})}
    actionable, review, all_records = [], [], []
    for record in records.values():
        event = event_from_record(record)
        decision = assess_relevance(event, reference, run['days'], run.get('review_timezone', 'Asia/Tehran'))
        # Keep original occurrence-level history when guarding an already
        # projected export. The repository always starts from full snapshots.
        previous = ledger.get(event.event_id)
        if (previous is None or previous['disposition'] != decision.disposition
                or tuple(previous['occurrence_ids']) != decision.occurrence_ids):
            ledger[event.event_id] = primitive(asdict(decision))
        decision_record = ledger[event.event_id]
        projected = dict(record, schedule_disposition=decision_record['disposition'],
                         schedule_reason=decision_record['reason'])
        all_records.append(projected)
        if decision_record['disposition'] == 'actionable':
            ids = set(decision_record['occurrence_ids'])
            projected = dict(projected, occurrences=[o for o in record.get('occurrences', ())
                                                      if o['occurrence_id'] in ids])
            upcoming = sorted((o for o in projected['occurrences'] if not o.get('end_date')
                and (datetime.fromisoformat(o['starts_at']) >= reference if o.get('starts_at')
                     else o['start_date'] >= reference.astimezone(ZoneInfo(o['timezone'])).date().isoformat())),
                key=lambda o: (datetime.fromisoformat(o['starts_at']) if o.get('starts_at') else
                    datetime.combine(date.fromisoformat(o['start_date']), time.min,
                                     tzinfo=ZoneInfo(o['timezone'])), o['occurrence_id']))
            next_session = upcoming[0] if upcoming else {}
            # An ongoing range has no countable instances: "not applicable"
            # (null), never a misleading zero remaining sessions.
            countable = any(not o.get('end_date') for o in projected['occurrences'])
            projected.update(next_session_date=next_session.get('start_date'),
                next_session_start_time=next_session.get('start_time'),
                next_session_end_time=next_session.get('end_time'),
                remaining_session_count=len(upcoming) if countable else None)
            actionable.append(projected)
        elif decision_record['disposition'] == 'needs_schedule_review':
            review.append(projected)
    counts = Counter(d['disposition'] for d in ledger.values())
    run.update(event_count=counts['actionable'],
               canonical_event_count=sum(counts.values()),
               filtered=sum(counts.values()) - counts['actionable'],
               undated=counts['needs_schedule_review'],
               schedule_reference_at=reference.astimezone(ZoneInfo('Asia/Tehran')).isoformat(),
               disposition_counts={key: counts[key] for key in DISPOSITIONS})
    actionable.sort(key=lambda r: (
        (r.get('occurrences') or [{}])[0].get('start_date') or r.get('start_date') or '9999',
        (r.get('occurrences') or [{}])[0].get('start_time') or r.get('start_time') or '99', r['event_id']))
    run['data_readiness_counts'] = dict(Counter(r['data_readiness'] for r in actionable if 'data_readiness' in r))
    return dict(document, run=run, events=all_records if include_filtered else actionable,
                schedule_review=review, event_dispositions=[ledger[key] for key in sorted(ledger)])
