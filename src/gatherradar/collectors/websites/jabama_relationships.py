"""Value-free relationship check of a saved public Jabama detail page.

Answers the questions the structural report cannot: does each timeslot's
``sessionId`` equal its parent ``id``, do its timestamps order and fall inside the
parent window, and do its seat counts agree. Output is booleans and counts only:
no identifier, timestamp, price or text value is returned. ``durationHours`` is
compared with the timeslot length, never assumed equal to it.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from ...domain.website import parse_source_instant
from .html import Node
from .jabama_sessions import (_ENQUEUE, _MAX_PAYLOAD, _MAX_SESSIONS, _SESSION_KEYS, _TIMESLOT_KEYS,
                              _SchemaError, _Table, _json, extract_sessions)

_TYPES = {
    'id': (str,), 'sessionId': (str,), 'startAt': (str,), 'endAt': (str,), 'enabled': (bool,),
    'capacityLimit': (int, type(None)), 'bookedCount': (int, type(None)),
    'remainingSeats': (int, type(None)), 'pricePerPerson': (int, Decimal, type(None)),
    'unitPrice': (int, Decimal, type(None)), 'hostDiscountPct': (int, Decimal, type(None)),
    'platformDiscountPct': (int, Decimal, type(None)),
}


def _flag(value: object) -> str:
    return 'missing' if value is None else ('true' if value else 'false') if type(value) is bool else 'other'


def _instant(value: object) -> datetime | None:
    try:
        return parse_source_instant(value)
    except ValueError:
        return None


def _typed(value: object, kinds: tuple[type, ...]) -> bool:
    # bool is an int subclass; a boolean count is a type mismatch.
    return type(value) in kinds


def relationship_report(root: Node, timezone: str = 'Asia/Tehran') -> dict:
    zone = ZoneInfo(timezone)
    scripts = [''.join(part for part in node.children if isinstance(part, str)).strip()
               for node in root.select('script') if not node.attrs.get('src')]
    payloads = [script for script in scripts if _ENQUEUE in script]
    if len(payloads) != 1 or len(payloads[0]) > _MAX_PAYLOAD:
        return {'envelope': 'absent' if not payloads else 'unsupported', 'payload_count': len(payloads)}
    match = re.fullmatch(re.escape(_ENQUEUE) + r'\(\s*("(?:[^"\\]|\\.)*")\s*\);?', payloads[0], re.S)
    if not match:
        return {'envelope': 'unsupported_call_shape'}
    try:
        table = _Table(_json(_json(match[1])))
        loaders = table.object(table.object(0)['loaderData'])
        if 'routes/events.$id' not in loaders:
            return {'envelope': 'ok', 'route': 'missing'}
        route = table.object(loaders['routes/events.$id'])
        event_id = table.scalar(table.object(route['event']), 'id')
        refs = table.value(route['sessions']) if 'sessions' in route else None
        if not isinstance(refs, list):
            return {'envelope': 'ok', 'route': 'routes/events.$id', 'sessions': 'missing'}
        counts: dict[str, Counter] = {name: Counter() for name in (
            'session_event_id_equals_page_event', 'parent_sold_out', 'parent_enabled', 'timeslots_per_session',
            'session_id_equals_parent_id', 'timestamp_form', 'start_before_end', 'parent_window',
            'starts_at_parent_start', 'ends_at_parent_end', 'timeslot_length_equals_parent_duration_hours',
            'same_local_date_as_parent', 'timeslot_enabled', 'availability', 'remaining_exceeds_capacity',
            'timeslot_price_present', 'parent_price_present', 'type_mismatch', 'timeslot_keys')}
        totals = Counter()
        session_ids, timeslot_ids = Counter(), Counter()
        for reference in refs[:_MAX_SESSIONS]:
            try:
                parent = table.object(reference)
            except _SchemaError:
                totals['sessions_not_objects'] += 1
                continue
            totals['sessions'] += 1
            totals['parent_unknown_keys'] += len(set(parent) - _SESSION_KEYS)
            value = lambda key, obj=parent: table.value(obj[key]) if key in obj else None
            parent_id, sold_out = value('id'), value('soldOut')
            if isinstance(parent_id, str):
                session_ids[parent_id] += 1
            counts['session_event_id_equals_page_event'][
                'missing' if value('eventId') is None else _flag(value('eventId') == event_id)] += 1
            counts['parent_sold_out'][_flag(sold_out)] += 1
            counts['parent_enabled'][_flag(value('enabled'))] += 1
            counts['parent_price_present'][_flag(value('pricePerPerson') is not None
                                                 or value('unitPrice') is not None)] += 1
            if value('remainingSeats') == 0 and sold_out is False:
                totals['parent_sold_out_false_with_zero_remaining'] += 1
            start = _instant(value('startIso'))
            hours = value('durationHours')
            window = None
            if start is not None and type(hours) in (int, Decimal) and hours > 0:
                window = (start, start + timedelta(hours=float(hours)))
            slots = value('timeslots')
            if not isinstance(slots, list):
                counts['timeslots_per_session']['not_a_list'] += 1
                continue
            counts['timeslots_per_session'][str(len(slots)) if len(slots) <= 10 else '>10'] += 1
            spans = []
            for slot_ref in slots:
                try:
                    slot = table.object(slot_ref)
                except _SchemaError:
                    totals['timeslots_not_objects'] += 1
                    continue
                totals['timeslots'] += 1
                counts['timeslot_keys']['documented_missing'] += len(_TIMESLOT_KEYS - set(slot))
                counts['timeslot_keys']['unknown'] += len(set(slot) - _TIMESLOT_KEYS)
                get = lambda key, obj=slot: table.value(obj[key]) if key in obj else None
                for key, kinds in _TYPES.items():
                    if key in slot and not _typed(get(key), kinds):
                        counts['type_mismatch'][key] += 1
                if isinstance(get('id'), str):
                    timeslot_ids[get('id')] += 1
                counts['session_id_equals_parent_id'][
                    'missing' if get('sessionId') is None else _flag(get('sessionId') == parent_id)] += 1
                begin, end = _instant(get('startAt')), _instant(get('endAt'))
                for raw, parsed in ((get('startAt'), begin), (get('endAt'), end)):
                    counts['timestamp_form']['unparseable' if parsed is None else
                                             'utc_z' if raw.endswith('Z') else 'explicit_offset'] += 1
                counts['timeslot_enabled'][_flag(get('enabled'))] += 1
                counts['timeslot_price_present'][_flag(get('pricePerPerson') is not None
                                                       or get('unitPrice') is not None)] += 1
                if begin is None or end is None:
                    for name in ('start_before_end', 'parent_window', 'starts_at_parent_start',
                                 'ends_at_parent_end', 'timeslot_length_equals_parent_duration_hours',
                                 'same_local_date_as_parent'):
                        counts[name]['unknown'] += 1
                else:
                    counts['start_before_end'][_flag(begin < end)] += 1
                    if begin < end:
                        spans.append((begin, end))
                    if window is None:
                        for name in ('parent_window', 'ends_at_parent_end',
                                     'timeslot_length_equals_parent_duration_hours'):
                            counts[name]['unknown'] += 1
                    else:
                        counts['parent_window']['within' if window[0] <= begin and end <= window[1] else
                                                'overlapping' if begin < window[1] and window[0] < end
                                                else 'disjoint'] += 1
                        counts['ends_at_parent_end'][_flag(end == window[1])] += 1
                        counts['timeslot_length_equals_parent_duration_hours'][
                            _flag(end - begin == window[1] - window[0])] += 1
                    if start is None:
                        counts['starts_at_parent_start']['unknown'] += 1
                        counts['same_local_date_as_parent']['unknown'] += 1
                    else:
                        counts['starts_at_parent_start'][_flag(begin == start)] += 1
                        counts['same_local_date_as_parent'][
                            _flag(begin.astimezone(zone).date() == start.astimezone(zone).date())] += 1
                    if begin.astimezone(zone).date() != end.astimezone(zone).date():
                        totals['timeslots_crossing_local_midnight'] += 1
                capacity, booked, remaining = get('capacityLimit'), get('bookedCount'), get('remainingSeats')
                if all(type(v) is int for v in (capacity, booked, remaining)):
                    counts['availability']['consistent' if capacity - booked == remaining else 'inconsistent'] += 1
                    if remaining > capacity:
                        counts['remaining_exceeds_capacity']['true'] += 1
                else:
                    counts['availability']['incomplete'] += 1
                if sold_out is True and type(remaining) is int and remaining > 0:
                    totals['sold_out_true_with_remaining_seats'] += 1
                if sold_out is False and remaining == 0:
                    totals['sold_out_false_with_zero_remaining'] += 1
                if get('enabled') is False and sold_out is False:
                    totals['disabled_timeslot_under_unsold_session'] += 1
            spans.sort()
            totals['overlapping_sibling_timeslots'] += sum(
                1 for (a, b), (c, d) in zip(spans, spans[1:]) if c < b)
        totals['duplicate_session_ids'] = sum(n - 1 for n in session_ids.values() if n > 1)
        totals['duplicate_timeslot_ids'] = sum(n - 1 for n in timeslot_ids.values() if n > 1)
        totals['timeslot_ids_equal_to_a_session_id'] = len(set(session_ids) & set(timeslot_ids))
        # What the conservative parser itself accepts from this page (counts only).
        parsed = extract_sessions(root, f'https://saved.invalid/events/{event_id}') if isinstance(
            event_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', event_id) else None
        report = {'envelope': 'ok', 'route': 'routes/events.$id', 'session_count': len(refs),
                  **{key: totals[key] for key in sorted(totals)},
                  **{name: dict(sorted(counter.items())) for name, counter in counts.items()}}
        if parsed is not None:
            report['parser'] = {
                'records_accepted': len(parsed.sessions),
                'timeslot_records_accepted': sum(1 for s in parsed.sessions if s.source_timeslot_id),
                'timeslot_records_inside_parent_window': sum(1 for s in parsed.sessions
                                                             if s.source_timeslot_id and s.schema_status is None),
                'diagnostics': list(parsed.diagnostics)}
        return report
    except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
        return {'envelope': 'undecodable'}


__all__ = ['relationship_report']
