"""Versioned, structured review records; never serialize raw contexts or OCR."""
from __future__ import annotations

import json
from dataclasses import asdict, fields, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum

from ..domain import Event
from ..domain.event import CanonicalDiagnostic, ChannelProvenance, EventStatus, FieldProvenance, ReviewStatus
from ..domain.temporal import DatePrecision
from ..domain.occurrence import EventOccurrence, ScheduleKind
from .readiness import readiness_record
from .serialization import WEEKDAYS, jalali, quality

# 2: source-supported description/area/duration/organizer/availability/schedule.
# Version-1 payloads load with those fields null.
SCHEMA_VERSION = 3


def primitive(value: object) -> object:
    if is_dataclass(value):
        return primitive(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: primitive(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [primitive(item) for item in value]
    return value


def dumps(value: object) -> str:
    return json.dumps(primitive(value), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def event_record(event: Event) -> dict:
    result = primitive(event)
    result.update(jalali_start_date=jalali(event.start_date),
                  jalali_end_date=jalali(event.end_date),
                  weekday=WEEKDAYS[event.start_date.weekday()] if event.start_date else None,
                  data_quality=quality(event))
    result.update(readiness_record(event))
    return result


def event_from_record(record: dict) -> Event:
    values = {f.name: record[f.name] for f in fields(Event) if f.name in record}
    for name in ('first_seen_at', 'last_seen_at', 'starts_at', 'ends_at'):
        if values.get(name) is not None:
            values[name] = datetime.fromisoformat(values[name])
    for name in ('start_date', 'end_date'):
        if values.get(name) is not None:
            values[name] = date.fromisoformat(values[name])
    for name in ('start_time', 'end_time'):
        if values.get(name) is not None:
            values[name] = time.fromisoformat(values[name])
    for name in ('tags', 'source_item_ids', 'candidate_ids', 'source_ids', 'publisher_keys', 'evidence_urls',
                 'reference_urls', 'channel_gaps', 'display_title_evidence_ids', 'evidence_fragment_ids'):
        values[name] = tuple(values.get(name, ()))
    values['status'] = EventStatus(values['status'])
    values['review_status'] = ReviewStatus(values['review_status'])
    values['date_precision'] = DatePrecision(values['date_precision'])
    if values.get('price_amount') is not None:
        values['price_amount'] = Decimal(str(values['price_amount']))
    values['field_provenance'] = tuple(FieldProvenance(p['field'], tuple(p['candidate_ids'])) for p in values['field_provenance'])
    values['diagnostics'] = tuple(CanonicalDiagnostic(p['code'], p['field'], tuple(p['candidate_ids'])) for p in values['diagnostics'])
    # Absent in records persisted before channel provenance existed.
    values['channel_provenance'] = tuple(ChannelProvenance(**p) for p in values.get('channel_provenance', ()))
    values['schedule_kind'] = ScheduleKind(values.get('schedule_kind', 'unknown'))
    values['occurrences'] = tuple(occurrence_from_record(p) for p in values.get('occurrences', ()))
    # Absent in records persisted before conflicting source wordings were kept.
    values['conflicting_values'] = tuple(tuple(pair) for pair in values.get('conflicting_values', ()))
    return Event(**values)


def occurrence_from_record(record: dict) -> EventOccurrence:
    values = {f.name: record[f.name] for f in fields(EventOccurrence) if f.name in record}
    for name in ('start_date', 'end_date'):
        if values.get(name) is not None:
            values[name] = date.fromisoformat(values[name])
    for name in ('start_time', 'end_time'):
        if values.get(name) is not None:
            values[name] = time.fromisoformat(values[name])
    for name in ('starts_at', 'ends_at'):
        if values.get(name) is not None:
            values[name] = datetime.fromisoformat(values[name])
    for name in ('source_item_ids', 'candidate_ids', 'evidence_urls', 'evidence_fragment_ids', 'diagnostics'):
        values[name] = tuple(values.get(name, ()))
    values['date_precision'] = DatePrecision(values.get('date_precision', 'day'))
    if values.get('price_amount') is not None:
        values['price_amount'] = Decimal(str(values['price_amount']))
    return EventOccurrence(**values)


def upgrade_event_record(record: dict) -> dict:
    """Add schema-3 defaults in memory; never rewrite historical fact payloads."""
    result = dict(record)
    event = event_from_record(record)
    result.setdefault('occurrences', primitive(event.occurrences))
    result.setdefault('schedule_kind', event.schedule_kind.value)
    result.setdefault('recurrence_rule', event.recurrence_rule)
    result.update(readiness_record(event))
    return result
