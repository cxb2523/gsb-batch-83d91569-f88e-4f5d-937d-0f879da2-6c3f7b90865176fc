"""Evidence-grounded Jabama child timeslots.

Shapes mirror the owner's value-free v3 report (16 parent keys, 12 timeslot keys,
1-4 timeslots per session, 7 and 81 sessions per page). All values are synthetic:
the report deliberately carried no identifiers, timestamps or prices. Value
relationships are unverified, so timeslots stay in Schedule Review until the gate
in ``normalization.schedules.VERIFIED_SESSION_SEMANTICS`` names them.
"""
from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from gatherradar.cli import main
from gatherradar.collectors.websites.html import parse_html
from gatherradar.collectors.websites.jabama_relationships import relationship_report
from gatherradar.domain import EventStatus
from gatherradar.domain.occurrence import EventOccurrence, identify_occurrence, occurrence_key
from gatherradar.domain.temporal import DatePrecision
from gatherradar.domain.website import SourceSession
from gatherradar.exports.excel import XLSX_CELL_LIMIT, overflow_value
from gatherradar.extraction.service import _source_sessions
from gatherradar.review.readiness import DataReadiness, assess_readiness
from gatherradar.review.records import dumps, event_from_record, event_record, occurrence_from_record, primitive
from gatherradar.review.relevance import assess_relevance
from gatherradar.review.workspace import local_workspace
from local_review_fakes import LocalCase
from test_jabama_session_pipeline import collected, pipeline
from test_jabama_session_schema import page
from test_jabama_sessions import _result

RUN = datetime(2026, 9, 26, tzinfo=timezone.utc)
VERIFIED = 'gatherradar.normalization.schedules.VERIFIED_SESSION_SEMANTICS'


def slot(slot_id: str, session_id: str, start: str, end: str, **extra) -> dict:
    return {'id': slot_id, 'sessionId': session_id, 'startAt': start, 'endAt': end, 'enabled': True,
            'capacityLimit': 8, 'bookedCount': 0, 'remainingSeats': 8, 'pricePerPerson': None,
            'unitPrice': None, 'hostDiscountPct': None, 'platformDiscountPct': None, **extra}


def parent(session_id: str, start: str, slots: list[dict], hours: int = 8, **extra) -> dict:
    """The v3 parent shape: capacity/price/remaining null, soldOut false."""
    return {'id': session_id, 'eventId': 'demo-event', 'startIso': start, 'durationHours': hours,
            'capacityLimit': None, 'bookedCount': 0, 'remainingSeats': None, 'enabled': True,
            'inventoryMode': 'timeslot_capacity', 'layoutId': None, 'timeslots': slots,
            'pricePerPerson': None, 'unitPrice': None, 'hostDiscountPct': None,
            'platformDiscountPct': None, 'soldOut': False, **extra}


def day_sessions(count: int, per_session: int = 1) -> list[dict]:
    """``count`` daily parents from 2026-09-28 06:30Z, each with 2-hour timeslots."""
    values = []
    for index in range(count):
        base = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc) + timedelta(days=index)
        session_id = str(500000 + index)
        slots = [slot(str(900000 + index * 10 + n), session_id,
                      (base + timedelta(hours=2 * n)).strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                      (base + timedelta(hours=2 * n + 2)).strftime('%Y-%m-%dT%H:%M:%S.000Z'))
                 for n in range(per_session)]
        values.append(parent(session_id, base.strftime('%Y-%m-%dT%H:%M:%S.000Z'), slots))
    return values


ONE = parent('111', '2026-09-30T06:30:00.000Z', [
    slot('901', '111', '2026-09-30T06:30:00.000Z', '2026-09-30T08:30:00.000Z'),
    slot('902', '111', '2026-09-30T09:30:00.000Z', '2026-09-30T11:30:00.000Z')])


def event_of(sessions, extra=''):
    _, outcome = pipeline(collected(page(sessions, extra)))
    event, = outcome.events
    return event


class TimeslotParsingTests(unittest.TestCase):
    def test_single_timeslot_keeps_parent_and_child_identity(self):
        value, = _result(page([parent('111', '2026-09-30T06:30:00.000Z',
                                      [slot('901', '111', '2026-09-30T06:30:00.000Z', '2026-09-30T08:30:00Z')])])).sessions
        self.assertEqual((value.source_session_id, value.source_timeslot_id), ('111', '901'))
        self.assertEqual(value.source_locator, 'react-router:loaderData/routes/events.$id/sessions/0/timeslots/0')
        self.assertEqual((value.start_iso, value.end_iso), ('2026-09-30T06:30:00.000Z', '2026-09-30T08:30:00Z'))
        self.assertIsNone(value.duration_hours)  # the parent duration is not the timeslot's
        self.assertEqual((value.capacity_limit, value.booked_count, value.remaining_seats, value.enabled),
                         (8, 0, 8, True))
        self.assertIs(value.sold_out, False)
        self.assertIsNone(value.schema_status)  # inside the 8-hour parent window
        self.assertEqual(SourceSession.from_mapping(value.to_dict()), value)

    def test_multiple_timeslots_are_independent_records(self):
        result = _result(page([ONE]))
        self.assertEqual([s.source_timeslot_id for s in result.sessions], ['901', '902'])
        self.assertEqual(result.diagnostics, ('embedded_session_timeslots',))

    def test_seven_and_eighty_one_parent_sessions(self):
        for count, per_session in ((7, 1), (7, 4), (81, 1), (81, 4)):
            with self.subTest(count=count, per_session=per_session):
                result = _result(page(day_sessions(count, per_session)))
                self.assertEqual(len(result.sessions), count * per_session)
                self.assertEqual(len({(s.source_session_id, s.source_timeslot_id) for s in result.sessions}),
                                 count * per_session)
                self.assertEqual(result.diagnostics, ('embedded_session_timeslots',))

    def test_wrong_owner_is_refused_and_siblings_survive(self):
        wrong = parent('111', '2026-09-30T06:30:00.000Z', [
            slot('901', '999', '2026-09-30T06:30:00.000Z', '2026-09-30T08:30:00.000Z'),
            slot('902', '111', '2026-09-30T09:30:00.000Z', '2026-09-30T11:30:00.000Z')])
        result = _result(page([wrong]))
        self.assertEqual([s.source_timeslot_id for s in result.sessions], ['902'])
        self.assertIn('embedded_session_drift_timeslot_ownership', result.diagnostics)
        missing = _result(page([parent('111', '2026-09-30T06:30:00.000Z', [
            {k: v for k, v in slot('901', '111', '2026-09-30T06:30:00Z', '2026-09-30T08:30:00Z').items()
             if k != 'sessionId'}])]))
        self.assertEqual(missing.sessions, ())
        self.assertIn('embedded_session_drift_timeslot_missing_properties', missing.diagnostics)

    def test_invalid_types_timestamps_and_order_are_refused(self):
        cases = {
            'timeslot_type': [{'enabled': 'true'}, {'enabled': 1}, {'remainingSeats': True},
                              {'capacityLimit': -1}, {'capacityLimit': '8'}, {'id': 901}, {'pricePerPerson': '5'}],
            'timeslot_timestamp': [{'startAt': '2026-09-30T06:30:00'}, {'endAt': '2026-09-30'},
                                   {'startAt': '2026-02-30T06:30:00Z'}],
            'timeslot_order': [{'endAt': '2026-09-30T06:30:00.000Z'}, {'endAt': '2026-09-30T06:00:00Z'}],
            'timeslot_new_properties': [{'label': 'PRIVATE'}],
        }
        for reason, overrides in cases.items():
            for override in overrides:
                with self.subTest(reason=reason, override=override):
                    item = slot('901', '111', '2026-09-30T06:30:00.000Z', '2026-09-30T08:30:00.000Z', **override)
                    result = _result(page([parent('111', '2026-09-30T06:30:00.000Z', [item])]))
                    self.assertEqual(result.sessions, ())
                    self.assertIn('embedded_session_drift_' + reason, result.diagnostics)
                    self.assertNotIn('PRIVATE', repr(result))

    def test_utc_and_offset_spellings_and_timezone_conversion(self):
        same = parent('111', '2026-09-30T06:30:00Z', [
            slot('901', '111', '2026-09-30T10:00:00+03:30', '2026-09-30T08:30:00Z')])
        value, = _result(page([same])).sessions
        self.assertIsNone(value.schema_status)  # equal instants, different spellings
        event = event_of([same])
        occurrence, = event.occurrences
        self.assertEqual((occurrence.start_date.isoformat(), occurrence.start_time, occurrence.end_time,
                          occurrence.timezone), ('2026-09-30', time(10), time(12), 'Asia/Tehran'))
        self.assertEqual(occurrence.starts_at.utcoffset(), timedelta(hours=3, minutes=30))
        late = event_of([parent('111', '2026-09-30T19:00:00Z', [
            slot('901', '111', '2026-09-30T20:00:00Z', '2026-09-30T21:00:00Z')])])
        self.assertEqual(late.occurrences[0].start_date.isoformat(), '2026-09-30')  # 23:30 Tehran
        early = event_of([parent('111', '2026-09-30T20:00:00Z', [
            slot('901', '111', '2026-09-30T20:30:00Z', '2026-09-30T21:30:00Z')])])
        self.assertEqual(early.occurrences[0].start_date.isoformat(), '2026-10-01')  # 00:00 Tehran

    def test_parent_window_relationship(self):
        outside = _result(page([parent('111', '2026-09-30T06:30:00Z', [
            slot('901', '111', '2026-09-30T13:30:00Z', '2026-09-30T15:30:00Z')], hours=2)]))
        self.assertEqual(outside.sessions[0].schema_status, 'timeslot_outside_parent_window')
        self.assertIn('embedded_timeslot_outside_parent_window', outside.diagnostics)
        unknown = _result(page([parent('111', '2026-09-30T06:30:00Z', [
            slot('901', '111', '2026-09-30T06:30:00Z', '2026-09-30T08:30:00Z')], hours=None)]))
        self.assertEqual(unknown.sessions[0].schema_status, 'timeslot_parent_window_unknown')

    def test_duplicate_timeslot_ids(self):
        repeated = slot('901', '111', '2026-09-30T06:30:00Z', '2026-09-30T08:30:00Z')
        same = _result(page([parent('111', '2026-09-30T06:30:00Z', [repeated, dict(repeated)])]))
        self.assertEqual(len(same.sessions), 1)  # an identical repeat is one record
        self.assertIn('embedded_timeslot_duplicate_id', same.diagnostics)
        differing = _result(page([parent('111', '2026-09-30T06:30:00Z', [
            repeated, {**repeated, 'startAt': '2026-09-30T09:30:00Z', 'endAt': '2026-09-30T11:30:00Z'}])]))
        self.assertEqual(differing.sessions, ())  # neither contradictory record is chosen
        self.assertIn('embedded_timeslot_identity_conflict', differing.diagnostics)
        across = _result(page([ONE, parent('222', '2026-09-30T06:30:00Z', [
            slot('901', '222', '2026-09-30T06:30:00Z', '2026-09-30T08:30:00Z')])]))
        self.assertEqual([s.source_timeslot_id for s in across.sessions], ['902'])

    def test_seat_counts(self):
        inconsistent = _result(page([parent('111', '2026-09-30T06:30:00Z', [
            slot('901', '111', '2026-09-30T06:30:00Z', '2026-09-30T08:30:00Z', bookedCount=3, remainingSeats=8)])]))
        value, = inconsistent.sessions
        self.assertEqual((value.capacity_limit, value.booked_count, value.remaining_seats), (None, None, None))
        self.assertIn('embedded_timeslot_availability_inconsistent', inconsistent.diagnostics)
        missing, = _result(page([parent('111', '2026-09-30T06:30:00Z', [
            slot('901', '111', '2026-09-30T06:30:00Z', '2026-09-30T08:30:00Z', capacityLimit=None)])])).sessions
        self.assertEqual((missing.capacity_limit, missing.remaining_seats), (None, 8))  # nothing derived
        disabled, = _result(page([parent('111', '2026-09-30T06:30:00Z', [
            slot('901', '111', '2026-09-30T06:30:00Z', '2026-09-30T08:30:00Z', enabled=False)])])).sessions
        self.assertIs(disabled.enabled, False)

    def test_unknown_parent_properties_with_timeslots_are_refused(self):
        result = _result(page([{**ONE, 'newFlag': True}]))
        self.assertEqual(result.sessions, ())
        self.assertIn('embedded_session_drift_timeslots', result.diagnostics)


class TimeslotScheduleTests(unittest.TestCase):
    """The owner's relationship report (88 parents / 295 timeslots) verified the
    Jabama timeslot relationships, so validated timeslots are dated occurrences."""

    def test_validated_timeslots_are_dated_occurrences(self):
        event = event_of([ONE])
        self.assertEqual([(o.source_session_id, o.source_timeslot_id) for o in event.occurrences],
                         [('111', '901'), ('111', '902')])
        self.assertEqual(len({o.occurrence_id for o in event.occurrences}), 2)
        self.assertTrue(all(o.diagnostics == () for o in event.occurrences))
        # Each child keeps its own interval; the 8-hour parent duration is not used.
        self.assertEqual([(o.start_time, o.end_time) for o in event.occurrences],
                         [(time(10), time(12)), (time(13), time(15))])
        decision = assess_relevance(event, RUN)
        self.assertEqual((decision.disposition, len(decision.occurrence_ids)), ('actionable', 2))
        self.assertEqual(assess_readiness(event).status, DataReadiness.READY)
        # A passed timeslot expires by its own source date.
        self.assertEqual(assess_relevance(event, RUN + timedelta(days=10)).disposition, 'expired')

    def test_horizon_applies_per_timeslot(self):
        event = event_of(day_sessions(81, 4))
        self.assertEqual(len(event.occurrences), 324)
        decision = assess_relevance(event, RUN)  # 2026-09-26; first parent day 2026-09-28
        kinds = {kind for _, kind, _ in decision.occurrence_dispositions}
        self.assertEqual(kinds, {'actionable', 'beyond_horizon'})
        # 28 Sep .. 10 Oct (Tehran) inclusive: 13 days of four timeslots each.
        self.assertEqual(len(decision.occurrence_ids), 13 * 4)
        later = assess_relevance(event, RUN + timedelta(days=30))
        self.assertIn('expired', {kind for _, kind, _ in later.occurrence_dispositions})
        self.assertEqual(later.disposition, 'actionable')  # later sessions still count

    def test_closed_gate_still_holds_timeslots_for_review(self):
        with patch(VERIFIED, frozenset()):
            event = event_of([ONE])
        self.assertTrue(all(o.diagnostics == ('embedded_timeslot_unverified_shape',) for o in event.occurrences))
        decision = assess_relevance(event, RUN)
        self.assertEqual(decision.disposition, 'needs_schedule_review')
        self.assertEqual({reason for *_, reason in decision.occurrence_dispositions}, {'unverified_timeslot'})
        self.assertIn('source_timeslots_unverified', assess_readiness(event).reasons)

    def test_outside_or_unmeasurable_parent_window_stays_in_review(self):
        outside = event_of([parent('111', '2026-09-30T06:30:00Z', [
            slot('901', '111', '2026-09-30T13:30:00Z', '2026-09-30T15:30:00Z')], hours=2)])
        self.assertEqual(outside.occurrences[0].diagnostics, ('embedded_timeslot_parent_window_conflict',))
        self.assertEqual(assess_relevance(outside, RUN).disposition, 'needs_schedule_review')
        self.assertIn('source_timeslots_unverified', assess_readiness(outside).reasons)
        unknown = event_of([parent('111', '2026-09-30T06:30:00Z', [
            slot('901', '111', '2026-09-30T06:30:00Z', '2026-09-30T08:30:00Z')], hours=None)])
        self.assertEqual(unknown.occurrences[0].diagnostics, ('embedded_timeslot_unverified_shape',))
        self.assertEqual(assess_relevance(unknown, RUN).disposition, 'needs_schedule_review')

    def test_visible_parent_window_is_not_a_second_session(self):
        # "۸ مهر ساعت ۱۰ تا ۱۶" on the page contains both timeslots (10-12, 13-15).
        event = event_of([ONE], '</div><div>۸ مهر ساعت ۱۰ تا ۱۶')
        self.assertEqual([o.source_timeslot_id for o in event.occurrences], ['901', '902'])
        self.assertNotEqual(event.schedule_kind, 'conflict')
        # A visible clock that contradicts the timeslots stays a visible conflict.
        clash = event_of([ONE], '</div><div>۸ مهر ساعت ۹ تا ۱۱')
        self.assertEqual(clash.schedule_kind, 'conflict')

    def test_shorter_timeslot_inside_parent_is_not_a_conflict(self):
        # The wheel page: every timeslot shorter than its parent duration, all inside.
        event = event_of([parent('111', '2026-09-30T06:30:00Z', [
            slot('901', '111', '2026-09-30T07:30:00Z', '2026-09-30T09:00:00Z')], hours=8)])
        self.assertEqual(event.occurrences[0].diagnostics, ())
        self.assertEqual(assess_relevance(event, RUN).disposition, 'actionable')

    def test_sold_out_vs_upcoming_vs_actionable(self):
        sold = [{**ONE, 'soldOut': True, 'timeslots': [{**t, 'remainingSeats': 0, 'bookedCount': 8}
                                                       for t in ONE['timeslots']]}]
        unverified = event_of(sold)
        # The flag is shown, never a status; the sessions stay current by date.
        self.assertNotEqual(unverified.status, EventStatus.SOLD_OUT)
        self.assertTrue(all(o.source_sold_out is True and 'embedded_session_sold_out_unverified' in o.diagnostics
                            for o in unverified.occurrences))
        self.assertEqual(assess_relevance(unverified, RUN).disposition, 'actionable')
        self.assertIn('source_sold_out_flag', assess_readiness(unverified).reasons)
        self.assertEqual(assess_relevance(unverified, RUN + timedelta(days=10)).disposition, 'expired')
        with patch(VERIFIED, frozenset({'timeslots', 'sold_out'})):
            verified = event_of(sold)
        self.assertEqual(verified.status, EventStatus.SOLD_OUT)
        # Upcoming and sold out: still a dated, current Event, never expired.
        self.assertEqual(assess_relevance(verified, RUN).disposition, 'actionable')
        contradicted = event_of([{**ONE, 'soldOut': True}])  # 8 seats remain on each timeslot
        self.assertNotEqual(contradicted.status, EventStatus.SOLD_OUT)
        self.assertTrue(all('embedded_session_sold_out_availability_conflict' in o.diagnostics
                            and o.remaining_seats is None for o in contradicted.occurrences))
        self.assertEqual(assess_relevance(contradicted, RUN).disposition, 'actionable')
        readiness = assess_readiness(contradicted)
        self.assertEqual(readiness.status, DataReadiness.ENRICHMENT)
        self.assertIn('source_availability_conflict', readiness.reasons)


class SessionWindowTests(unittest.TestCase):
    """legacy-941: whole sessions 08:00-17:00 while the activity states 2 hours.
    The pottery reports do not validate this page; dates stay, clocks are reviewed."""

    def window_event(self, hours, duration='۲ ساعت'):
        whole = {'id': '7001', 'eventId': 'demo-event', 'startIso': '2026-09-30T04:30:00Z',
                 'durationHours': hours, 'capacityLimit': None, 'bookedCount': 0, 'remainingSeats': None,
                 'enabled': True, 'inventoryMode': 'timeslot_capacity', 'layoutId': None, 'timeslots': [],
                 'pricePerPerson': None, 'unitPrice': None, 'hostDiscountPct': None,
                 'platformDiscountPct': None, 'soldOut': False}
        extra = f'</div><div>مدت زمان: {duration}' if duration else ''
        return event_of([whole, {**whole, 'id': '7002', 'startIso': '2026-10-01T04:30:00Z'}], extra)

    def test_nine_hour_window_against_two_hour_activity_is_reviewed(self):
        event = self.window_event(9)
        self.assertEqual(event.duration_text, '۲ ساعت')
        self.assertTrue(all('session_window_duration_conflict' in o.diagnostics for o in event.occurrences))
        self.assertEqual([o.start_date.isoformat() for o in event.occurrences], ['2026-09-30', '2026-10-01'])
        self.assertEqual(assess_relevance(event, RUN).disposition, 'needs_schedule_review')
        self.assertIn('session_window_conflict', assess_readiness(event).reasons)
        # No synthetic two-hour slots were created.
        self.assertEqual(len(event.occurrences), 2)

    def test_matching_or_close_windows_stay_actionable(self):
        for hours, duration in ((2, '۲ ساعت'), (1.5, '75 دقیقه'), (9, None)):
            with self.subTest(hours=hours, duration=duration):
                event = self.window_event(hours, duration)
                self.assertFalse(any('session_window' in c for o in event.occurrences for c in o.diagnostics))
                self.assertEqual(assess_relevance(event, RUN).disposition, 'actionable')


class CompatibilityTests(unittest.TestCase):
    def test_whole_session_records_and_identities_are_unchanged(self):
        legacy = {'source_session_id': 'a', 'source_event_id': 'demo-event', 'start_iso': '2026-09-24T17:00:00Z',
                  'source_locator': 'react-router:loaderData/routes/events.$id/sessions/0', 'duration_hours': '2',
                  'price_per_person': None, 'unit_price': None, 'host_discount_pct': None,
                  'platform_discount_pct': None, 'remaining_seats': 3, 'enabled': True}
        self.assertEqual(SourceSession.from_mapping(legacy).to_dict(), legacy)
        occurrence = EventOccurrence('pending', datetime(2026, 9, 24).date(), 'UTC', source_session_id='a',
                                     source_session_origin='x.test')
        self.assertEqual(occurrence_key(occurrence), ('session', 'x.test', 'a'))
        self.assertNotEqual(identify_occurrence(occurrence, 'e').occurrence_id,
                            identify_occurrence(replace(occurrence, source_timeslot_id='t'), 'e').occurrence_id)
        stored = primitive(occurrence)
        for key in ('source_timeslot_id', 'source_sold_out', 'capacity_limit'):
            stored.pop(key)  # a record persisted before these fields existed
        self.assertEqual(occurrence_from_record(stored), occurrence)

    def test_invalid_timeslot_records_are_rejected_at_the_domain_boundary(self):
        base = dict(source_session_id='111', source_event_id='demo-event', start_iso='2026-09-30T06:30:00Z',
                    source_locator='react-router:loaderData/routes/events.$id/sessions/0/timeslots/0',
                    source_timeslot_id='901', end_iso='2026-09-30T08:30:00Z')
        SourceSession(**base)
        for change in ({'end_iso': None}, {'end_iso': '2026-09-30T06:30:00Z'}, {'sold_out': 'false'},
                       {'source_locator': 'react-router:loaderData/routes/events.$id/sessions/0'},
                       {'capacity_limit': True}, {'source_timeslot_id': None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                SourceSession(**{**base, **change})

    def test_stored_records_with_duplicate_timeslots_are_refused(self):
        raw = collected(page([ONE]))
        stored = raw.raw_metadata['source_sessions']
        self.assertEqual(len(_source_sessions(raw)[0]), 2)
        for sessions in ([stored[0], stored[0]], [stored[0], {**stored[1], 'source_timeslot_id': '901'}],
                         [stored[0], {k: v for k, v in stored[1].items()
                                      if k not in ('source_timeslot_id', 'end_iso')} | {
                             'source_locator': 'react-router:loaderData/routes/events.$id/sessions/1'}]):
            with self.subTest():
                changed = replace(raw, raw_metadata={**raw.raw_metadata, 'source_sessions': sessions})
                self.assertEqual(_source_sessions(changed)[0], ())

    def test_event_record_round_trip(self):
        event = event_of([ONE])
        self.assertEqual(event_from_record(json.loads(dumps(event_record(event)))).occurrences, event.occurrences)


class LargeTimeslotExportTests(LocalCase):
    def test_eighty_one_sessions_with_four_timeslots_export_losslessly(self):
        _, self.result = pipeline(collected(page(day_sessions(81, 4))))
        self.persist('slots')
        document = self.repo.load('slots')
        # Validated timeslots inside the horizon make this one current Event row.
        # The current view carries only in-horizon sessions; SQLite keeps all 324.
        record, = document['events']
        self.assertEqual(len(record['occurrences']), 13 * 4)
        self.assertEqual(record['remaining_session_count'], 13 * 4)
        self.assertEqual((record['next_session_date'], record['next_session_start_time']), ('2026-09-28', '10:00:00'))
        stored, = self.repo.load('slots', include_filtered=True)['events']
        self.assertEqual(len(stored['occurrences']), 324)
        paths, warnings = local_workspace(self.repo, self.book, self.root / 'exports').export('slots')
        self.assertEqual(warnings, ())
        workbook = load_workbook(self.book)
        self.addCleanup(workbook.close)
        sheet = next(s for s in workbook if s.title.startswith('رویدادها') and s.max_row > 1)
        self.assertTrue(all(len(v) <= XLSX_CELL_LIMIT for s in workbook for row in s.iter_rows(values_only=True)
                            for v in row if isinstance(v, str)))
        restored = json.loads(overflow_value(workbook, sheet.title, record['event_id'], 'occurrences'))
        latest = self.root / 'exports' / 'latest'
        csv.field_size_limit(1_000_000)  # the reader's default; the written cell is complete
        with (latest / 'events.csv').open(encoding='utf-8-sig', newline='') as stream:
            row = next(r for r in csv.DictReader(stream) if r['event_id'] == record['event_id'])
        exported = json.loads((latest / 'review.json').read_text(encoding='utf-8'))['events'][0]
        keys = lambda values: [(o['source_session_id'], o['source_timeslot_id']) for o in values]
        self.assertEqual(keys(restored), keys(record['occurrences']))
        self.assertEqual(keys(json.loads(row['occurrences'])), keys(record['occurrences']))
        self.assertEqual(keys(exported['occurrences']), keys(record['occurrences']))
        self.assertEqual(len(set(keys(restored))), 13 * 4)


class RelationshipReportTests(unittest.TestCase):
    def test_booleans_and_counts_only(self):
        sessions = [ONE, parent('222', '2026-10-01T06:30:00Z', [
            slot('903', '999', '2026-10-01T07:00:00+03:30', '2026-10-01T03:00:00Z', bookedCount=2),
            slot('903', '222', '2026-10-01T07:30:00Z', '2026-10-01T09:00:00Z')], hours=2, soldOut=True)]
        report = relationship_report(parse_html(page(sessions)))
        self.assertEqual((report['session_count'], report['sessions'], report['timeslots']), (2, 2, 4))
        self.assertEqual(report['timeslots_per_session'], {'2': 2})
        self.assertEqual(report['session_id_equals_parent_id'], {'false': 1, 'true': 3})
        self.assertEqual(report['start_before_end'], {'false': 1, 'true': 3})
        self.assertEqual(report['parent_window'], {'disjoint': 1, 'overlapping': 1, 'within': 2})
        self.assertEqual(report['timestamp_form'], {'explicit_offset': 1, 'utc_z': 7})
        self.assertEqual(report['availability'], {'consistent': 3, 'inconsistent': 1})
        self.assertEqual(report['timeslot_length_equals_parent_duration_hours'], {'false': 4})
        self.assertEqual(report['parent_sold_out'], {'false': 1, 'true': 1})
        self.assertEqual(report['sold_out_true_with_remaining_seats'], 2)
        self.assertEqual(report['duplicate_timeslot_ids'], 1)
        self.assertEqual(report['parser']['timeslot_records_accepted'], 3)  # wrong owner refused
        text = json.dumps(report)
        for private in ('111', '222', '901', '903', '999', 'demo-event', '2026', 'T06', 'کارگاه'):
            self.assertNotIn(private, text)

    def test_cli_writes_only_the_requested_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            saved = root / 'ورکشاپ PRIVATE.html'
            saved.write_text(page(day_sessions(7)), encoding='utf-8')
            output = root / 'relationships.json'
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(['diagnose', 'jabama-timeslots', '--html', str(saved),
                                       '--output', str(output)]), 0)
            self.assertEqual(sorted(p.name for p in root.iterdir()), sorted([saved.name, output.name]))
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['summary']['timeslots'], 7)
            self.assertEqual(report['summary']['session_id_equals_parent_id'], {'true': 7})
            self.assertEqual(report['pages'][0]['page'], 1)
            self.assertNotIn('PRIVATE', output.read_text(encoding='utf-8'))
            self.assertNotIn('ورکشاپ', output.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()


class BookingPresentationTests(unittest.TestCase):
    """X03: booking facts are shown as source facts, separate from temporal relevance."""

    def test_booking_column_describes_source_facts_without_promising_a_seat(self):
        from gatherradar.review.serialization import booking
        self.assertIn('صندلی باقی‌مانده طبق منبع: ۸', booking(event_of([ONE])))
        self.assertIn('امکان رزرو را در منبع بررسی کنید', booking(event_of([ONE])))
        sold = event_of([{**ONE, 'soldOut': True, 'timeslots': [{**t, 'remainingSeats': 0, 'bookedCount': 8}
                                                               for t in ONE['timeslots']]}])
        self.assertEqual(booking(sold), 'منبع همه جلسه‌ها را «تکمیل ظرفیت» علامت زده است')
        self.assertIn('ناسازگار', booking(event_of([{**ONE, 'soldOut': True}])))
        # The page's own wording always wins over derived session facts.
        self.assertEqual(booking(event_of([ONE], '</div><div>تکمیل ظرفیت')), 'تکمیل ظرفیت')
