from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gatherradar.collectors.website import WebsiteCollector
from gatherradar.collectors.websites.adapters import build_adapter
from gatherradar.collectors.websites.html import parse_html
from gatherradar.collectors.websites.jabama_sessions import extract_sessions
from gatherradar.collectors.websites.transport import Page
from gatherradar.domain import Source, SourceType
from gatherradar.domain.website import SourceSession, WebsiteConfig

BASE = 'https://community.example/'
URL = BASE + 'events/demo-event'
FIXTURE = Path(__file__).parent / 'fixtures' / 'websites' / 'jabama-sessions-detail.html'
PREFIX = 'window.__reactRouterContext.streamController.enqueue'
SESSION = {
    'id': 'demo-session-a', 'eventId': 'demo-event',
    'startIso': '2026-09-24T17:00:00.000Z', 'durationHours': 2,
    'capacityLimit': 152, 'bookedCount': 75, 'remainingSeats': 45, 'enabled': True,
    'inventoryMode': 'assigned_seat', 'layoutId': 'demo-layout', 'timeslots': [],
    'pricePerPerson': None, 'unitPrice': None, 'hostDiscountPct': None,
    'platformDiscountPct': None,
}


def _encode(value):
    """Small fixture writer for the observed indexed JSON envelope."""
    table = []

    def append(item):
        if item is None:
            return -5
        index = len(table)
        table.append(None)
        if isinstance(item, dict):
            table[index] = {f'_{append(key)}': append(child) for key, child in item.items()}
        elif isinstance(item, list):
            table[index] = [append(child) for child in item]
        else:
            table[index] = item
        return index

    append(value)
    return table


def _page(sessions=None, *, event_id='demo-event', route_extras=None):
    sessions = [dict(SESSION)] if sessions is None else sessions
    route = {'event': {'id': event_id, 'pricePerPerson': 999999,
                       'reviews': [{'text': 'UNRELATED REVIEW MUST NEVER BE RETAINED'}]},
             'sessions': sessions, 'firstSession': sessions[0] if sessions else None}
    route.update(route_extras or {})
    # Unrelated root state must not be traversed or stored.
    value = {'loaderData': {'root': {'viewerId': None}, 'routes/events.$id': route},
             'actionData': None, 'errors': None}
    argument = json.dumps(json.dumps(_encode(value), ensure_ascii=False, separators=(',', ':')),
                          ensure_ascii=False)
    return ('<main><article><h1>کارگاه نمونه</h1><section><h2>درباره این ایونت</h2>'
            '<div class="rich-text-content">ساخت یک اثر با راهنمایی مربی.</div></section></article>'
            '<aside><p>از ۹۹۹٬۹۹۹ تومان</p><button>خرید بلیت</button></aside></main>'
            f'<script>{PREFIX}({argument});</script>')


def _result(page=None):
    return extract_sessions(parse_html(page or _page()), URL)


class JabamaSessionTests(unittest.TestCase):
    def test_sanitized_observed_envelope_keeps_only_own_session_facts(self):
        result = _result(FIXTURE.read_text(encoding='utf-8'))
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(len(result.sessions), 1)  # firstSession is not a second occurrence
        value, = result.sessions
        self.assertEqual(value.source_session_id, 'demo-session-a')
        self.assertEqual(value.start_iso, '2026-09-24T17:00:00.000Z')
        self.assertEqual(value.duration_hours, '2')
        self.assertEqual(value.remaining_seats, 45)
        self.assertTrue(value.enabled)
        self.assertIsNone(value.price_per_person)  # no event/default price borrowing
        self.assertNotIn('REVIEW', json.dumps(value.to_dict()))
        self.assertEqual(SourceSession.from_mapping(value.to_dict()), value)

    def test_distinct_sessions_keep_dates_prices_and_availability_separate(self):
        second = {**SESSION, 'id': 'demo-session-b', 'startIso': '2026-09-25T10:30:00+03:30',
                  'durationHours': 1.5, 'pricePerPerson': 250000, 'remainingSeats': 0,
                  'enabled': False}
        result = _result(_page([SESSION, second]))
        a, b = result.sessions
        self.assertNotEqual(a.source_session_id, b.source_session_id)
        self.assertIsNone(a.price_per_person)
        self.assertEqual(b.price_per_person, '250000')
        self.assertEqual(b.duration_hours, '1.5')
        self.assertEqual(b.remaining_seats, 0)
        self.assertFalse(b.enabled)
        self.assertIn('embedded_session_price_unit_unknown', result.diagnostics)

    def test_fractional_source_amount_retains_exact_decimal_value(self):
        page = _page([{**SESSION, 'pricePerPerson': 1.25}]).replace('1.25', '100000000000000.01')
        self.assertEqual(_result(page).sessions[0].price_per_person, '100000000000000.01')

    def test_repeated_identical_session_deduplicates_but_conflicting_identity_abstains(self):
        self.assertEqual(len(_result(_page([SESSION, dict(SESSION)])).sessions), 1)
        result = _result(_page([SESSION, {**SESSION, 'startIso': '2026-10-01T17:00:00Z'}]))
        self.assertEqual(result.sessions, ())
        self.assertIn('embedded_session_identity_conflict', result.diagnostics)

    def test_cross_event_sessions_are_rejected_without_poisoning_a_valid_sibling(self):
        result = _result(_page([SESSION, {**SESSION, 'id': 'other', 'eventId': 'unrelated'}]))
        self.assertEqual(len(result.sessions), 1)
        self.assertIn('embedded_session_schema_drift', result.diagnostics)

    def test_embedded_event_must_match_current_detail_identity(self):
        result = _result(_page(event_id='other-event'))
        self.assertEqual(result.sessions, ())
        self.assertEqual(result.diagnostics, ('embedded_sessions_schema_drift', 'embedded_sessions_drift_event_identity'))

    def test_unsupported_timeslots_and_new_session_properties_are_visible(self):
        for changes in ({'timeslots': ['09:00']}, {'newClock': '10:00', 'bad key!': 1}):
            with self.subTest(changes=changes):
                result = _result(_page([{**SESSION, **changes}]))
                self.assertEqual(result.sessions, ())
                self.assertIn('embedded_session_schema_drift', result.diagnostics)

    def test_additive_unknown_properties_keep_only_identity_start_and_duration(self):
        result = _result(_page([{**SESSION, 'pricePerPerson': 250000, 'remainingSeats': 3,
                                 'newClock': '10:00', 'statusCode': 'X'}]))
        value, = result.sessions
        self.assertEqual((value.source_session_id, value.start_iso, value.duration_hours),
                         ('demo-session-a', '2026-09-24T17:00:00.000Z', '2'))
        self.assertEqual(value.schema_status, 'unverified_properties')
        self.assertIsNone(value.price_per_person)  # meaning may be changed by unknown keys
        self.assertIsNone(value.remaining_seats)
        self.assertIsNone(value.enabled)
        self.assertEqual(result.drift_keys, ('newClock', 'statusCode'))
        self.assertIn('embedded_session_drift_new_properties', result.diagnostics)
        self.assertIn('embedded_session_unverified_shape', result.diagnostics)
        self.assertNotIn('10:00', repr(result))
        self.assertEqual(SourceSession.from_mapping(value.to_dict()), value)
        documented = _result(_page()).sessions[0].to_dict()
        self.assertNotIn('schema_status', documented)  # documented sessions hash as before

    def test_bad_timestamps_and_types_cannot_supply_sessions(self):
        for changes in ({'startIso': '2026-09-24'}, {'startIso': '2026-09-24T25:00:00Z'},
                        {'startIso': '2026-09-24T17:00:00'}, {'durationHours': True},
                        {'durationHours': 0}, {'durationHours': -1}, {'remainingSeats': True},
                        {'remainingSeats': -1}, {'enabled': 'yes'}, {'pricePerPerson': -5},
                        {'id': '../other'}, {'startIso': None}):
            with self.subTest(changes=changes):
                self.assertEqual(_result(_page([{**SESSION, **changes}])).sessions, ())

    def test_no_session_fallback_from_first_session_or_json_ld(self):
        result = _result(_page([], route_extras={'firstSession': SESSION}))
        self.assertEqual(result.sessions, ())
        self.assertIn('embedded_sessions_empty', result.diagnostics)
        absent = _result('<script type="application/ld+json">{"startDate":"2026-09-24"}</script>')
        self.assertEqual(absent.sessions, ())
        self.assertIn('embedded_sessions_absent', absent.diagnostics)

    def test_injected_javascript_and_multiple_envelopes_are_never_executed(self):
        for page in (_page().replace(');</script>', ');raiseError();</script>'),
                     _page() + _page(), f'<script>{PREFIX}(doSomething());</script>',
                     f'<script>{PREFIX}("not JSON");</script>'):
            with self.subTest(page=page[:60]):
                result = _result(page)
                self.assertEqual(result.sessions, ())
                self.assertIn('embedded_sessions_schema_drift', result.diagnostics)

    def test_out_of_bounds_and_cyclic_references_fail_closed(self):
        for table in ([{'_1': 99999}, 'loaderData'], [{'_1': 0}, 'loaderData'],
                      [{'_1': -1}, 'loaderData']):
            page = '<script>' + PREFIX + '(' + json.dumps(json.dumps(table)) + ');</script>'
            self.assertEqual(_result(page).diagnostics[0], 'embedded_sessions_schema_drift')

    def test_duplicate_json_keys_nonfinite_values_and_resource_bounds_fail_closed(self):
        for serialized in ('[{"_1":2,"_1":3},"loaderData",{},{}]', '[NaN]'):
            page = '<script>' + PREFIX + '(' + json.dumps(serialized) + ');</script>'
            self.assertEqual(_result(page).diagnostics[0], 'embedded_sessions_schema_drift')
        many = _page([{**SESSION, 'id': f'session-{i}'} for i in range(201)])
        self.assertEqual(_result(many).sessions, ())
        large = '<script>' + PREFIX + '(' + json.dumps('x' * 1_000_001) + ');</script>'
        self.assertEqual(_result(large).diagnostics, ('embedded_sessions_schema_drift', 'embedded_sessions_drift_payload_size'))

    def test_session_discount_is_reported_without_adjusting_source_price(self):
        result = _result(_page([{**SESSION, 'pricePerPerson': 100, 'hostDiscountPct': 10}]))
        self.assertEqual(result.sessions[0].price_per_person, '100')
        self.assertEqual(result.sessions[0].host_discount_pct, '10')
        self.assertIn('embedded_session_discount_unresolved', result.diagnostics)

    def test_source_session_mapping_refuses_extra_fields_and_bad_provenance(self):
        value = _result().sessions[0]
        for changes in ({'secret': 'not allowed'}, {'source_locator': 'other-event'},
                        {'start_iso': '2026-01-01T12:00:00'}, {'unit_price': 'NaN'},
                        {'remaining_seats': 1.5}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                SourceSession.from_mapping({**value.to_dict(), **changes})

    def test_adapter_preserves_visible_text_without_synthetic_schedule_lines(self):
        detail = build_adapter(WebsiteConfig('jabama-events', ('/events/',))).extract(Page(URL, _page()), BASE)
        self.assertEqual(len(detail.sessions), 1)
        self.assertNotIn('2026-', detail.text)
        self.assertNotIn('REVIEW', detail.text)
        self.assertTrue(detail.structured_data_present)

    def test_collector_hash_changes_with_session_facts_but_not_unrelated_script_fields(self):
        source = Source('jabama_test', 'jabama', 'Jabama', SourceType.WEBSITE, BASE,
                        website=WebsiteConfig('jabama-events', ('/events/',)))

        class Transport:
            page = _page()

            def fetch(self, url, *, allowed=None):
                return Page(url, self.page if url == URL else '<a href="/events/demo-event">برنامه</a>')

        transport = Transport()
        collector = WebsiteCollector(transport=transport, now=lambda: datetime(2026, 9, 24, tzinfo=timezone.utc))
        first, = collector.collect(source, limit=1).items
        same, = collector.collect(source, limit=1).items
        self.assertEqual(first.content_hash, same.content_hash)
        self.assertEqual(first.raw_metadata['source_session_schema'], 'jabama-react-router/1')
        self.assertEqual(len(first.raw_metadata['source_sessions']), 1)
        transport.page = _page().replace('UNRELATED REVIEW MUST NEVER BE RETAINED', 'OTHER UNRELATED REVIEW')
        unrelated, = collector.collect(source, limit=1).items
        self.assertEqual(first.content_hash, unrelated.content_hash)
        transport.page = _page([{**SESSION, 'remainingSeats': 0}])
        changed, = collector.collect(source, limit=1).items
        self.assertNotEqual(first.content_hash, changed.content_hash)
        self.assertEqual(first.id, changed.id)
