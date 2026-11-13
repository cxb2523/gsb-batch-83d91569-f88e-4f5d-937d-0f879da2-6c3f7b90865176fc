"""Read the observed public Jabama React Router session envelope as data only.

This is deliberately not a JavaScript interpreter or a general Turbo Stream
decoder. Only indexed objects/lists and scalar fields on routes/events.$id are
read. Unrelated loader state, profiles, reviews, tokens and recommendations never
become observations. New envelopes or session shapes produce diagnostics.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlsplit

from ...domain.website import (SESSION_UNVERIFIED_PROPERTIES, TIMESLOT_OUTSIDE_PARENT_WINDOW,
                               TIMESLOT_PARENT_WINDOW_UNKNOWN, MAX_SESSION_RECORDS, SourceSession,
                               parse_source_instant)
from .html import Node

_ENQUEUE = 'window.__reactRouterContext.streamController.enqueue'
_MAX_PAYLOAD = 1_000_000
_MAX_TABLE = 20_000
_MAX_SESSIONS = 200
_NULL = -5  # The null sentinel observed in the saved public envelope.
_FIELDS = (
    'id', 'eventId', 'startIso', 'durationHours', 'pricePerPerson', 'unitPrice',
    'remainingSeats', 'enabled',
)
_SESSION_KEYS = frozenset((*_FIELDS, 'capacityLimit', 'bookedCount', 'inventoryMode',
                           'layoutId', 'timeslots', 'hostDiscountPct', 'platformDiscountPct',
                           'soldOut'))
# The child timeslot shape confirmed by the owner's value-free v3 report: exactly
# these twelve keys. Any other key refuses the timeslot rather than guessing.
_TIMESLOT_KEYS = frozenset(('id', 'sessionId', 'startAt', 'endAt', 'enabled', 'capacityLimit',
                            'bookedCount', 'remainingSeats', 'pricePerPerson', 'unitPrice',
                            'hostDiscountPct', 'platformDiscountPct'))
_MAX_TIMESLOTS = 50


_DRIFT_KEY = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,39}')
_MAX_DRIFT_KEYS = 20


_MAX_SHAPES = 3
_SHAPE_DEPTH = 4
_SHAPE_KEYS = 30


def _string_form(value: str) -> str:
    """The kind of a string, never the string itself."""
    for form, pattern in (('iso_datetime', r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?'),
                          ('iso_date', r'\d{4}-\d{2}-\d{2}'), ('clock', r'\d{1,2}:\d{2}(?::\d{2})?'),
                          ('digits', r'\d+'), ('number_text', r'-?\d+(?:[.,]\d+)?'), ('url', r'https?://\S+'),
                          ('identifier', r'[A-Za-z0-9_-]{1,64}')):
        if re.fullmatch(pattern, value):
            return form
    return 'text'


def _length_bucket(length: int) -> str:
    return next(label for limit, label in ((0, '0'), (10, '1-10'), (40, '11-40'), (200, '41-200'))
                if length <= limit) if length <= 200 else '>200'


def value_shape(table: '_Table', reference: object, depth: int = 0) -> dict:
    """A value-free structural description of one embedded value.

    Strings report only their form and a length bucket; numbers their kind and
    sign; booleans their value (public flags such as a sellout marker); objects
    their sanitized key names; arrays their length and the shapes of up to five
    items. Depth and key counts are bounded.
    """
    try:
        value = table.value(reference)
    except (_SchemaError, TypeError):
        return {'type': 'unsupported_reference'}
    if value is None:
        return {'type': 'null'}
    if isinstance(value, bool):
        return {'type': 'bool', 'value': value}
    if isinstance(value, (int, Decimal)):
        return {'type': 'integer' if type(value) is int else 'decimal',
                'sign': 'zero' if value == 0 else 'positive' if value > 0 else 'negative'}
    if isinstance(value, str):
        return {'type': 'string', 'form': _string_form(value), 'length': _length_bucket(len(value))}
    if isinstance(value, list):
        shape: dict = {'type': 'array', 'length': len(value)}
        if depth < _SHAPE_DEPTH:
            items = []
            for item in value[:5]:
                described = value_shape(table, item, depth + 1)
                if described not in items:
                    items.append(described)
            shape['items'] = items
        return shape
    try:
        obj = table.object(reference)
    except _SchemaError:
        return {'type': 'unsupported_object'}
    shape = {'type': 'object', 'key_count': len(obj)}
    if depth < _SHAPE_DEPTH:
        shape['keys'] = {(key if _DRIFT_KEY.fullmatch(key) else '<unsafe-key>'): value_shape(table, ref, depth + 1)
                         for key, ref in sorted(obj.items())[:_SHAPE_KEYS]}
    return shape


@dataclass(frozen=True, slots=True)
class SessionResult:
    sessions: tuple[SourceSession, ...] = ()
    diagnostics: tuple[str, ...] = ()
    present: bool = False
    # Names only (never values) of unexpected session properties, so the owner
    # can report a new public shape without sharing page data.
    drift_keys: tuple[str, ...] = ()
    # Value-free shapes of up to three sessions that did not match the documented
    # schema; the structural evidence needed before supporting a new variant.
    drift_shapes: tuple[dict, ...] = ()


class _SchemaError(ValueError):
    def __init__(self, message: str, reason: str = 'field', keys: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.reason = reason
        self.keys = keys


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _SchemaError('duplicate JSON key')
        result[key] = value
    return result


def _json(text: str) -> object:
    return json.loads(text, object_pairs_hook=_object_pairs, parse_float=Decimal,
                      parse_constant=lambda _: (_ for _ in ()).throw(_SchemaError('non-finite JSON')))


class _Table:
    """Resolve references only along explicitly requested field paths."""

    def __init__(self, values: object) -> None:
        if not isinstance(values, list) or not 1 <= len(values) <= _MAX_TABLE:
            raise _SchemaError('invalid reference table')
        self.values = values

    def value(self, reference: object) -> object:
        if type(reference) is not int:
            raise _SchemaError('invalid reference')
        if reference == _NULL:
            return None
        if not 0 <= reference < len(self.values):
            raise _SchemaError('unsupported reference')
        return self.values[reference]

    def object(self, reference: object) -> dict[str, object]:
        raw = self.value(reference)
        if not isinstance(raw, dict) or len(raw) > 200:
            raise _SchemaError('expected indexed object')
        result: dict[str, object] = {}
        for encoded_key, value_ref in raw.items():
            if not re.fullmatch(r'_[0-9]+', encoded_key):
                raise _SchemaError('unsupported object encoding')
            key = self.value(int(encoded_key[1:]))
            if not isinstance(key, str) or len(key) > 200 or key in result:
                raise _SchemaError('invalid indexed object key')
            result[key] = value_ref
        return result

    def scalar(self, obj: dict[str, object], key: str, *, required: bool = False) -> object:
        if key not in obj:
            if required:
                raise _SchemaError('missing required field')
            return None
        value = self.value(obj[key])
        if isinstance(value, (dict, list)):
            raise _SchemaError('expected scalar')
        if isinstance(value, str) and len(value) > 200:
            raise _SchemaError('oversized scalar')
        return value


def _decimal(value: object) -> str | None:
    if value is None:
        return None
    if type(value) not in (int, Decimal) or not Decimal(value).is_finite() or value < 0:
        raise _SchemaError('invalid numeric session field')
    # Fixed notation preserves exact JSON numeric meaning without exponent text.
    return format(Decimal(str(value)), 'f')


def _count(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 1_000_000:
        raise _SchemaError('invalid timeslot count', 'timeslot_type')
    return value


def _discounts(table: _Table, obj: dict[str, object], reason: str = 'field') -> tuple[str | None, str | None]:
    # A discount changes the meaning of a base price: validated, never applied.
    values = []
    for key in ('hostDiscountPct', 'platformDiscountPct'):
        discount = table.scalar(obj, key)
        if discount is not None and (type(discount) not in (int, Decimal)
                                     or not Decimal(discount).is_finite() or not 0 <= discount <= 100):
            raise _SchemaError('invalid discount', reason)
        values.append(_decimal(discount))
    return values[0], values[1]


def _timeslot(table: _Table, reference: object, parent: dict, locator: str) -> SourceSession:
    """One strictly typed child timeslot. Ownership and order are proven here;
    whether a timeslot is an attendable occurrence is decided after review."""
    try:
        obj = table.object(reference)
    except _SchemaError as error:
        raise _SchemaError('timeslot is not an object', 'timeslots') from error
    extra = set(obj) - _TIMESLOT_KEYS
    if extra:
        raise _SchemaError('new timeslot properties', 'timeslot_new_properties',
                           tuple(sorted(k for k in extra if _DRIFT_KEY.fullmatch(k)))[:_MAX_DRIFT_KEYS])
    if _TIMESLOT_KEYS - set(obj):
        raise _SchemaError('missing timeslot properties', 'timeslot_missing_properties')
    values = {key: table.scalar(obj, key) for key in _TIMESLOT_KEYS}
    for key in ('id', 'sessionId', 'startAt', 'endAt'):
        if not isinstance(values[key], str):
            raise _SchemaError('invalid timeslot text field', 'timeslot_type')
    if values['sessionId'] != parent['id']:
        raise _SchemaError('timeslot belongs to a different session', 'timeslot_ownership')
    if type(values['enabled']) is not bool:
        raise _SchemaError('invalid timeslot enabled flag', 'timeslot_type')
    try:
        start, end = parse_source_instant(values['startAt']), parse_source_instant(values['endAt'])
    except ValueError as error:
        raise _SchemaError('invalid timeslot timestamp', 'timeslot_timestamp') from error
    if end <= start:
        raise _SchemaError('timeslot end does not follow its start', 'timeslot_order')
    for key in ('pricePerPerson', 'unitPrice'):
        if values[key] is not None and (type(values[key]) not in (int, Decimal) or values[key] < 0):
            raise _SchemaError('invalid timeslot price', 'timeslot_type')
    host, platform = _discounts(table, obj, 'timeslot_type')
    capacity, booked, remaining = (_count(values[k]) for k in ('capacityLimit', 'bookedCount', 'remainingSeats'))
    status = TIMESLOT_PARENT_WINDOW_UNKNOWN
    if parent['duration_hours'] is not None:
        # The parent window is its start plus its stated duration. A timeslot
        # duration is its own start/end; it is never assumed equal to the parent's.
        window_start = parse_source_instant(parent['start_iso'])
        window_end = window_start + timedelta(hours=float(parent['duration_hours']))
        status = None if window_start <= start and end <= window_end else TIMESLOT_OUTSIDE_PARENT_WINDOW
    return SourceSession(
        source_session_id=parent['id'], source_event_id=parent['event_id'], start_iso=values['startAt'],
        source_locator=locator, price_per_person=_decimal(values['pricePerPerson']),
        unit_price=_decimal(values['unitPrice']), host_discount_pct=host, platform_discount_pct=platform,
        remaining_seats=remaining, enabled=values['enabled'], schema_status=status,
        source_timeslot_id=values['id'], end_iso=values['endAt'], capacity_limit=capacity,
        booked_count=booked, sold_out=parent['sold_out'])


def _session(table: _Table, reference: object, event_id: str, index: int,
             tolerate: bool = False) -> tuple[tuple[SourceSession, ...], tuple[Exception, ...]]:
    """The documented session itself, or one record per validated child timeslot,
    plus the errors of refused timeslots."""
    obj = table.object(reference)
    # Extra session properties can change booking semantics, unlike unrelated
    # event fields. Strictly they are refused; tolerantly only the session's own
    # identity, start and duration are kept, with the shape marked unverified.
    extra = set(obj) - _SESSION_KEYS
    if extra and (not tolerate or any(not _DRIFT_KEY.fullmatch(key) for key in extra)
                  or len(extra) > _MAX_DRIFT_KEYS):
        keys = tuple(sorted(key for key in extra if _DRIFT_KEY.fullmatch(key)))[:_MAX_DRIFT_KEYS]
        raise _SchemaError('new session properties', 'new_properties', keys)
    values = {key: table.scalar(obj, key, required=key in ('id', 'eventId', 'startIso'))
              for key in _FIELDS}
    if values['eventId'] != event_id:
        raise _SchemaError('session belongs to a different event')
    sold_out = table.value(obj['soldOut']) if 'soldOut' in obj else None
    if sold_out is not None and type(sold_out) is not bool:
        # A non-boolean flag is not interpreted, neither as true nor as false.
        raise _SchemaError('invalid soldOut flag', 'sold_out_type')
    if 'timeslots' not in obj:
        raise _SchemaError('missing session timeslots', 'timeslots')
    slots = table.value(obj['timeslots'])
    if not isinstance(slots, list) or len(slots) > _MAX_TIMESLOTS or (slots and extra):
        raise _SchemaError('unsupported session timeslots', 'timeslots')
    host, platform = _discounts(table, obj)
    locator = f'react-router:loaderData/routes/events.$id/sessions/{index}'
    if not isinstance(values['id'], str) or not isinstance(values['startIso'], str):
        raise _SchemaError('invalid session identity')
    if slots:
        parent = {'id': values['id'], 'event_id': values['eventId'], 'start_iso': values['startIso'],
                  'duration_hours': _decimal(values['durationHours']), 'sold_out': sold_out}
        parse_source_instant(values['startIso'])
        kept, refused = [], []
        for position, ref in enumerate(slots):
            # Independent children: one unreadable timeslot never hides another.
            try:
                kept.append(_timeslot(table, ref, parent, f'{locator}/timeslots/{position}'))
            except (ValueError, KeyError, TypeError, OverflowError) as error:
                refused.append(error)
        return tuple(kept), tuple(refused)
    if extra:
        return (SourceSession(
            source_session_id=values['id'], source_event_id=values['eventId'], start_iso=values['startIso'],
            source_locator=locator, duration_hours=_decimal(values['durationHours']),
            schema_status=SESSION_UNVERIFIED_PROPERTIES),), ()
    return (SourceSession(
        source_session_id=values['id'], source_event_id=values['eventId'],
        start_iso=values['startIso'], source_locator=locator,
        duration_hours=_decimal(values['durationHours']),
        price_per_person=_decimal(values['pricePerPerson']), unit_price=_decimal(values['unitPrice']),
        host_discount_pct=host, platform_discount_pct=platform,
        remaining_seats=values['remainingSeats'], enabled=values['enabled'], sold_out=sold_out,
    ),), ()


def extract_sessions(root: Node, page_url: str) -> SessionResult:
    """Return supported detail sessions, never a firstSession fallback."""
    parts = urlsplit(page_url)
    path = re.fullmatch(r'/events/([A-Za-z0-9_-]{1,100})/?', parts.path)
    if not path:
        return SessionResult(diagnostics=('embedded_sessions_unsupported_path',))
    scripts = [''.join(part for part in node.children if isinstance(part, str)).strip()
               for node in root.select('script') if not node.attrs.get('src')]
    payloads = [script for script in scripts if _ENQUEUE in script]
    if not payloads:
        return SessionResult(diagnostics=('embedded_sessions_absent',))
    def drift(stage: str) -> SessionResult:
        # The generic code stays; the stage names the expectation that failed.
        return SessionResult(diagnostics=('embedded_sessions_schema_drift', 'embedded_sessions_drift_' + stage),
                             present=True)
    if len(payloads) != 1 or len(payloads[0]) > _MAX_PAYLOAD:
        return drift('payload_count' if len(payloads) != 1 else 'payload_size')
    # JSON string argument only. No eval, execution, fetching imports, or attempt
    # to repair malformed JavaScript. Trailing program text is rejected.
    match = re.fullmatch(re.escape(_ENQUEUE) + r'\(\s*("(?:[^"\\]|\\.)*")\s*\);?', payloads[0], re.S)
    if not match:
        return drift('call_shape')
    stage = 'table'
    try:
        serialized = _json(match[1])
        if not isinstance(serialized, str) or len(serialized) > _MAX_PAYLOAD:
            raise _SchemaError('invalid serialized table')
        table = _Table(_json(serialized))
        stage = 'route'
        envelope = table.object(0)
        loaders = table.object(envelope['loaderData'])
        route = table.object(loaders['routes/events.$id'])
        stage = 'event_identity'
        event = table.object(route['event'])
        event_id = table.scalar(event, 'id', required=True)
        if event_id != path[1]:
            raise _SchemaError('page event identity mismatch')
        stage = 'sessions'
        if 'sessions' not in route:
            raise _SchemaError('missing sessions')
        refs = table.value(route['sessions'])
        if not isinstance(refs, list) or len(refs) > _MAX_SESSIONS:
            raise _SchemaError('invalid sessions')
        stage = 'session_list'
        if not refs:
            return SessionResult(diagnostics=('embedded_sessions_empty',), present=True)
        sessions: dict[tuple[str, str | None], SourceSession] = {}
        conflicts: set[tuple[str, str | None]] = set()
        diagnostics: list[str] = []
        drift_keys: set[str] = set()
        shapes: list[dict] = []

        def keep_shape(reference: object) -> None:
            if len(shapes) < _MAX_SHAPES:
                shapes.append(value_shape(table, reference))
        def refuse(error: Exception, reference: object = None) -> None:
            # The generic code stays for compatibility; a specific, value-free
            # code says which documented expectation the public shape broke.
            reason = getattr(error, 'reason', 'field')
            diagnostics.append('embedded_session_schema_drift')
            diagnostics.append('embedded_session_drift_' + reason)
            drift_keys.update(getattr(error, 'keys', ()))
            if reference is not None and reason in ('new_properties', 'timeslots', 'sold_out_type'):
                keep_shape(reference)
        for index, reference in enumerate(refs):
            try:
                try:
                    found, refused = _session(table, reference, event_id, index)
                except _SchemaError as error:
                    if error.reason != 'new_properties':
                        raise
                    # Additive unknown properties: keep the session's own date
                    # for review, report the drift, never its price/availability.
                    drift_keys.update(error.keys)
                    diagnostics.append('embedded_session_drift_new_properties')
                    keep_shape(reference)
                    found, refused = _session(table, reference, event_id, index, tolerate=True)
                    diagnostics.append('embedded_session_unverified_shape')
                for error in refused:
                    refuse(error)
                if refused:
                    keep_shape(reference)
                for session in found:
                    if session.source_timeslot_id is not None:
                        diagnostics.append('embedded_session_timeslots')
                        if session.schema_status is not None:
                            diagnostics.append('embedded_' + session.schema_status)
                        if (None not in (session.capacity_limit, session.booked_count, session.remaining_seats)
                                and session.capacity_limit - session.booked_count != session.remaining_seats):
                            # Contradictory seat counts: none of them is kept.
                            diagnostics.append('embedded_timeslot_availability_inconsistent')
                            session = replace(session, capacity_limit=None, booked_count=None, remaining_seats=None)
                    key = (session.source_session_id, session.source_timeslot_id)
                    if session.source_timeslot_id is not None:
                        owners = [k for k in sessions if k[1] == session.source_timeslot_id]
                        if owners:
                            before, after = sessions[owners[0]].to_dict(), session.to_dict()
                            before.pop('source_locator')
                            after.pop('source_locator')
                            diagnostics.append('embedded_timeslot_duplicate_id')
                            if before != after:
                                conflicts.update(owners)
                                conflicts.add(key)
                                diagnostics.append('embedded_timeslot_identity_conflict')
                            continue
                    elif any(k[0] == session.source_session_id for k in sessions):
                        previous = next(v for k, v in sessions.items() if k[0] == session.source_session_id)
                        before, after = previous.to_dict(), session.to_dict()
                        before.pop('source_locator')
                        after.pop('source_locator')
                        if before != after:
                            conflicts.update(k for k in sessions if k[0] == session.source_session_id)
                            diagnostics.append('embedded_session_identity_conflict')
                        continue
                    if (session.source_timeslot_id is not None
                            and any(k[0] == session.source_session_id and k[1] is None for k in sessions)):
                        conflicts.add(key)
                        diagnostics.append('embedded_session_identity_conflict')
                        continue
                    sessions[key] = session
                    if session.price_per_person is not None or session.unit_price is not None:
                        diagnostics.append('embedded_session_price_unit_unknown')
                    if session.schema_status != SESSION_UNVERIFIED_PROPERTIES and any(
                            value is not None and Decimal(value) != 0
                            for value in (session.host_discount_pct, session.platform_discount_pct)):
                        diagnostics.append('embedded_session_discount_unresolved')
            except (ValueError, KeyError, TypeError, OverflowError) as error:
                refuse(error, reference)
        if len(sessions) > MAX_SESSION_RECORDS:
            raise _SchemaError('too many session records')
        return SessionResult(tuple(value for key, value in sessions.items() if key not in conflicts),
                             tuple(dict.fromkeys(diagnostics)), True,
                             tuple(sorted(drift_keys))[:_MAX_DRIFT_KEYS], tuple(shapes))
    except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
        return drift(stage)


def describe_embedded_sessions(root: Node) -> dict:
    """Value-free structural report of a saved public detail page's sessions.

    For owner diagnostics only: never used for extraction, no URL is required,
    and no string, price or identifier value is returned.
    """
    scripts = [''.join(part for part in node.children if isinstance(part, str)).strip()
               for node in root.select('script') if not node.attrs.get('src')]
    payloads = [script for script in scripts if _ENQUEUE in script]
    if len(payloads) != 1:
        return {'envelope': 'absent' if not payloads else 'multiple_payloads', 'payload_count': len(payloads)}
    match = re.fullmatch(re.escape(_ENQUEUE) + r'\(\s*("(?:[^"\\]|\\.)*")\s*\);?', payloads[0], re.S)
    if not match or len(payloads[0]) > _MAX_PAYLOAD:
        return {'envelope': 'unsupported_call_shape'}
    try:
        table = _Table(_json(_json(match[1])))
        loaders = table.object(table.object(0)['loaderData'])
        if 'routes/events.$id' not in loaders:
            return {'envelope': 'ok', 'route': 'missing',
                    'loader_routes': sorted(k if _DRIFT_KEY.fullmatch(k.replace('/', '_').replace('.', '_').replace('$', ''))
                                            else '<unsafe-key>' for k in loaders)[:_SHAPE_KEYS]}
        route = table.object(loaders['routes/events.$id'])
        report: dict = {'envelope': 'ok', 'route': 'routes/events.$id',
                        'route_keys': sorted(k if _DRIFT_KEY.fullmatch(k) else '<unsafe-key>' for k in route)[:_SHAPE_KEYS]}
        refs = table.value(route['sessions']) if 'sessions' in route else None
        if not isinstance(refs, list):
            return {**report, 'sessions': 'missing' if refs is None else 'not_a_list'}
        shapes = [value_shape(table, ref) for ref in refs[:_MAX_SESSIONS]]
        summary: dict = {}
        for shape in shapes:
            for key, described in (shape.get('keys') or {}).items():
                entry = summary.setdefault(key, {'types': {}, 'true': 0, 'false': 0, 'present_in': 0})
                entry['present_in'] += 1
                entry['types'][described['type']] = entry['types'].get(described['type'], 0) + 1
                if described['type'] == 'bool':
                    entry['true' if described['value'] else 'false'] += 1
        unknown = sorted(set(summary) - _SESSION_KEYS)
        return {**report, 'session_count': len(refs), 'documented_keys_missing': sorted(_SESSION_KEYS - set(summary)) if shapes else [],
                'unknown_keys': unknown, 'key_summary': summary, 'session_shapes': shapes[:20]}
    except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
        return {'envelope': 'undecodable'}
