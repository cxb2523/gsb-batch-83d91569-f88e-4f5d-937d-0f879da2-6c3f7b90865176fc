"""Review presentation fixes found in the frozen 2026-10-23 workbook (cloud field hardening)."""
import csv
import json
import unittest
from dataclasses import replace

from openpyxl import load_workbook

from gatherradar.deduplication.models import CanonicalizationResult
from gatherradar.review.serialization import occurrence_text, review_window
from gatherradar.review.workspace import local_workspace
from local_review_fakes import LocalCase
from test_event_recall import REFERENCE, pipeline

RANGE = ('نمایشگاه انفرادی «آبی» از هنرمند نمونه\n۲۴ مهر تا ۱۵ آبان ۱۴۰۵\nساعت ۱۳ تا ۲۱ (شنبه‌ها تعطیل)\n'
         '📍 محله نمونه، مجتمع سپید، گالری ابر/باران')


class ExportCase(LocalCase):
    def export(self, text):
        events, _ = pipeline(text)
        self.assertEqual(len(events), 1)
        self.repo.sync(CanonicalizationResult(events=events), review_window(events, REFERENCE),
            run_id='fields', started_at=REFERENCE, finished_at=REFERENCE, days=14,
            review_timezone='Asia/Tehran', source_count=1)
        self.assertFalse(local_workspace(self.repo, self.book, self.root / 'exports').export('fields')[1])
        return events[0], self.repo.load('fields')


class RangeRemainingSessionTests(ExportCase):
    """An ongoing range has no countable sessions: not applicable, never "0"."""

    def test_range_remaining_sessions_is_not_applicable_in_every_format(self):
        _, document = self.export(RANGE)
        row = document['events'][0]
        self.assertIsNone(row['remaining_session_count'])
        book = load_workbook(self.book)
        values = dict(zip(next(book.active.values), list(book.active.values)[1]))
        book.close()
        self.assertIn(values['جلسه‌های باقی‌مانده'], (None, ''))
        with (self.root / 'exports' / 'latest' / 'events.csv').open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual(next(csv.DictReader(stream))['remaining_session_count'], '')
        exported = json.loads(next((self.root / 'exports' / 'latest').glob('*.json')).read_text(encoding='utf-8'))
        events = exported['events'] if isinstance(exported, dict) else exported
        self.assertIsNone(events[0]['remaining_session_count'])

    def test_countable_sessions_still_report_a_number(self):
        _, document = self.export('کارگاه سفال آبی\n۳۰ مهر ساعت ۱۶ الی ۲۰، ۱ آبان ساعت ۱۲ الی ۲۰\nثبت نام')
        self.assertEqual(document['events'][0]['remaining_session_count'], 1)


class SessionListOrderTests(unittest.TestCase):
    def test_session_cell_is_chronological_without_changing_stored_order(self):
        events, _ = pipeline('کارگاه سفال آبی\n۳۰ مهر ساعت ۱۶ الی ۲۰، ۱ آبان ساعت ۱۲ الی ۲۰\nثبت نام')
        event = events[0]
        shuffled = replace(event, occurrences=tuple(reversed(event.occurrences)))
        self.assertEqual(occurrence_text(shuffled), occurrence_text(event))
        self.assertTrue(occurrence_text(shuffled).startswith('۳۰ مهر'))
        self.assertEqual(shuffled.occurrences[0], event.occurrences[-1])  # stored data untouched


if __name__ == '__main__':
    unittest.main()
