"""Jabama program descriptions and session-schema drift (cloud field hardening).

See docs/CLOUD_FIELD_HARDENING_VALIDATION.md.

Inputs are sanitized synthetic fixtures modelled on the frozen 2026-10-23 audit
entries. They prove deterministic behavior only; they are not a claim that the
live pages, original media or OCR were inspected.
"""
from __future__ import annotations

import unittest

from gatherradar.collectors.websites.adapters import build_adapter
from gatherradar.collectors.websites.transport import Page
from gatherradar.domain.website import WebsiteConfig
from gatherradar.review.records import event_from_record, event_record
from test_source_coverage import J_LIST, Pipeline, html, jabama_pages

PROGRAM_URL = 'https://jabama.example/events/event-11112222'
PROGRAM_LINES = ('چه برنامه‌ای داریم؟', 'معرفی گل رس و ابزارها', 'شکل دادن گوشواره با دست',
                 'رنگ‌آمیزی و لعاب‌کاری', 'پخت نهایی در کوره انجام می‌شود و ارسال آن هماهنگ می‌شود.')
ABOUT_LINES = ('با راهنمایی مربی، یک جفت گوشواره سرامیکی می‌سازیم و با خودمان می‌بریم.',
               'همه ابزار در اختیار شرکت‌کنندگان است.')


class JabamaProgramDescriptionTests(unittest.TestCase):
    """P0: the program section ("چه برنامه‌ای داریم؟") joins the About description."""

    def setUp(self):
        self.adapter = build_adapter(WebsiteConfig('jabama-events', ('/events/',), 'article'))

    def description(self, page: str) -> str | None:
        detail = self.adapter.extract(Page(PROGRAM_URL, page), J_LIST)
        found = dict(detail.fields)
        if 'description_text' in found:
            # Each blank-line-separated part is an exact retained slice, in order.
            position = 0
            for part in found['description_text'].split('\n\n'):
                self.assertIn(part, detail.text[position:])
                position = detail.text.index(part, position) + len(part)
        return found.get('description_text')

    def test_about_and_program_in_page_order_without_unrelated_copy(self):
        value = self.description(html('jabama-program-detail.html'))
        self.assertEqual(tuple(value.splitlines()), ABOUT_LINES + PROGRAM_LINES)
        for foreign in ('بیوگرافی', 'رویدادهای مشابه', 'شمع‌سازی', 'محل برگزاری', 'تومان',
                        'غیرقابل‌استرداد', 'میزبان', 'درباره این تجربه'):
            self.assertNotIn(foreign, value)
        self.assertEqual(len(value.splitlines()), len(set(value.splitlines())))  # no duplicated fragments

    def test_page_without_program_is_unchanged(self):
        self.assertEqual(tuple(self.description(html('jabama-experience-detail.html')).splitlines()), ABOUT_LINES)

    def test_unrecognized_or_empty_or_detached_program_keeps_about_only(self):
        page = html('jabama-program-detail.html')
        venue = page[page.index('<section class="mt-[34px]"><h2 class="text-[18px] font-extrabold">محل برگزاری'):]
        venue = venue[:venue.index('</button></div></div></section>') + len('</button></div></div></section>')]
        program = page[page.index('<section class="mt-[34px]"><h2 class="text-[18px] font-extrabold">چه برنامه'):]
        program = program[:program.index('</section>') + len('</section>')]
        variants = {
            'renamed': page.replace('چه برنامه‌ای داریم؟', 'قوانین لغو'),
            'empty': page.replace(program, '<section><h2>چه برنامه‌ای داریم؟</h2><div></div></section>'),
        }
        for name, variant in variants.items():
            with self.subTest(name):
                self.assertEqual(tuple(self.description(variant).splitlines()), ABOUT_LINES)

    def test_program_separated_by_another_section_joins_as_its_own_slice(self):
        page = html('jabama-program-detail.html')
        venue = page[page.index('<section class="mt-[34px]"><h2 class="text-[18px] font-extrabold">محل برگزاری'):]
        venue = venue[:venue.index('</button></div></div></section>') + len('</button></div></div></section>')]
        program = page[page.index('<section class="mt-[34px]"><h2 class="text-[18px] font-extrabold">چه برنامه'):]
        program = program[:program.index('</section>') + len('</section>')]
        detached = self.description(page.replace(program, '').replace(venue, venue + program))
        about, separate = detached.split('\n\n')
        self.assertEqual(tuple(about.splitlines()), ABOUT_LINES)
        self.assertEqual(tuple(separate.splitlines()), PROGRAM_LINES)
        for foreign in ('محل برگزاری', 'بیوگرافی', 'رویدادهای مشابه', 'تومان'):
            self.assertNotIn(foreign, detached)
        # A repeated program block is kept once.
        repeated = self.description(page.replace(venue, venue + program))
        self.assertEqual(repeated.count(PROGRAM_LINES[1]), 1)

    def test_program_without_rich_text_wrapper_and_question_mark_variant(self):
        page = html('jabama-program-detail.html').replace('چه برنامه‌ای داریم؟', 'چه برنامه ای داریم?')
        page = page.replace('<div class="rich-text-content mt-[11px] text-[14px]"><ul>', '<div><ul>')
        value = self.description(page)
        self.assertIn('شکل دادن گوشواره با دست', value)
        self.assertTrue(value.startswith(ABOUT_LINES[0]))

    def test_missing_about_yields_no_description_rather_than_program_only(self):
        page = html('jabama-program-detail.html').replace('درباره این <!-- -->تجربه', 'معرفی')
        self.assertIsNone(self.description(page))

    def test_program_reaches_event_description_and_record(self):
        events = Pipeline(self).events('jabama_experiences_fixture',
                                       jabama_pages(**{PROGRAM_URL: html('jabama-program-detail.html')}), limit=2)
        event = events['تجربه ساخت گوشواره سرامیکی در تهران']
        self.assertEqual(tuple(event.description_text.splitlines()), ABOUT_LINES + PROGRAM_LINES)
        self.assertEqual(event_from_record(event_record(event)).description_text, event.description_text)
        self.assertIn('description_text', {p.field for p in event.field_provenance})



class JabamaSessionDriftTests(unittest.TestCase):
    """P0: unsupported embedded session shapes are diagnosable, never guessed."""

    def test_specific_value_free_drift_codes_and_key_names(self):
        from test_jabama_sessions import SESSION, _page, _result
        timeslots = _result(_page([{**SESSION, 'timeslots': ['09:00']}]))
        self.assertEqual(timeslots.sessions, ())
        self.assertIn('embedded_session_schema_drift', timeslots.diagnostics)  # compatible generic code
        self.assertIn('embedded_session_drift_timeslots', timeslots.diagnostics)
        extra = _result(_page([{**SESSION, 'slotLabel': 'SECRET-VALUE', 'bad key!': 1}]))
        self.assertEqual(extra.sessions, ())
        self.assertIn('embedded_session_drift_new_properties', extra.diagnostics)
        self.assertEqual(extra.drift_keys, ('slotLabel',))  # names only, unsafe names dropped
        self.assertNotIn('SECRET', repr(extra))
        field = _result(_page([{**SESSION, 'startIso': '2026-09-24'}]))
        self.assertIn('embedded_session_drift_field', field.diagnostics)
        # Deterministic, and a valid sibling still survives.
        mixed = _page([SESSION, {**SESSION, 'id': 'b', 'timeslots': ['x']}])
        self.assertEqual(_result(mixed), _result(mixed))
        self.assertEqual(len(_result(mixed).sessions), 1)

    def page(self, **changes):
        from test_jabama_sessions import SESSION, _page
        return _page([{**SESSION, **changes}]).replace(
            'ساخت یک اثر با راهنمایی مربی.', 'ساخت یک اثر با راهنمایی مربی.</div><div>میزبان: استودیو نمونه، تهران')

    def test_unknown_additive_session_keys_give_reviewable_dates_not_actionable_sessions(self):
        from datetime import datetime, timezone
        from test_jabama_session_pipeline import collected, pipeline
        from gatherradar.review.readiness import DataReadiness, assess_readiness
        from gatherradar.review.relevance import assess_relevance
        raw = collected(self.page(newShape=1, pricePerPerson=999))
        self.assertEqual(raw.raw_metadata['source_session_drift_keys'], ['newShape'])
        _, result = pipeline(raw)
        event, = result.events
        occurrence, = event.occurrences  # the source's own session date, not invented
        self.assertEqual(occurrence.source_session_id, 'demo-session-a')
        self.assertIsNone(occurrence.price_amount)
        self.assertIn('embedded_session_unverified_shape', occurrence.diagnostics)
        before = datetime(2026, 9, 20, tzinfo=timezone.utc)
        self.assertEqual(assess_relevance(event, before).disposition, 'needs_schedule_review')
        readiness = assess_readiness(event)
        self.assertEqual(readiness.status, DataReadiness.SCHEDULE)
        self.assertIn('source_sessions_unverified', readiness.reasons)
        again = collected(self.page(newShape=1, pricePerPerson=999))
        self.assertEqual(raw.content_hash, again.content_hash)  # stable rerun

    def test_unverified_sessions_matching_visible_page_dates_stay_actionable(self):
        from datetime import datetime, timezone
        from test_jabama_session_pipeline import collected, pipeline
        from test_jabama_sessions import SESSION, _page
        from gatherradar.review.relevance import assess_relevance
        sessions = [{**SESSION, 'id': 'a', 'startIso': '2026-09-30T11:30:00Z', 'newShape': 1},
                    {**SESSION, 'id': 'b', 'startIso': '2026-10-01T11:30:00Z', 'newShape': 1}]
        page = _page(sessions).replace('<h1>کارگاه نمونه</h1>', '<h1>کارگاه نمونه</h1><p>۸ و ۹ مهر - ساعت ۱۵ الی ۱۷</p>')
        _, result = pipeline(collected(page))
        event, = result.events
        self.assertEqual([(o.source_session_id, o.start_time.isoformat()) for o in event.occurrences],
                         [('a', '15:00:00'), ('b', '15:00:00')])
        self.assertTrue(all('embedded_session_corroborated_by_page_text' in o.diagnostics for o in event.occurrences))
        self.assertTrue(all(o.price_amount is None for o in event.occurrences))
        run = datetime(2026, 9, 26, tzinfo=timezone.utc)
        self.assertEqual(assess_relevance(event, run).disposition, 'actionable')
        # A session at a clock the page does not state stays unverified.
        sessions[1] = {**sessions[1], 'startIso': '2026-10-01T14:30:00Z'}
        page = _page(sessions).replace('<h1>کارگاه نمونه</h1>', '<h1>کارگاه نمونه</h1><p>۸ و ۹ مهر - ساعت ۱۵ الی ۱۷</p>')
        _, result = pipeline(collected(page))
        event, = result.events
        self.assertTrue(any('embedded_session_unverified_shape' in o.diagnostics for o in event.occurrences))

    def test_unreadable_sessions_route_to_schedule_review_with_explicit_reason(self):
        from test_jabama_session_pipeline import collected, pipeline
        from gatherradar.review.readiness import DataReadiness, REASON_LABELS, assess_readiness
        raw = collected(self.page(timeslots=['09:00']))
        self.assertIn('embedded_session_drift_timeslots', raw.raw_metadata['source_session_diagnostics'])
        _, result = pipeline(raw)
        event, = result.events
        self.assertEqual(event.occurrences, ())  # no fabricated sessions
        self.assertIn('normalization:embedded_session_drift_timeslots', {d.code for d in event.diagnostics})
        readiness = assess_readiness(event)
        self.assertEqual(readiness.status, DataReadiness.SCHEDULE)
        self.assertIn('source_sessions_unreadable', readiness.reasons)
        self.assertIn('صفحه منبع', readiness.explanation)
        self.assertIn('source_sessions_unreadable', REASON_LABELS)

if __name__ == '__main__':
    unittest.main()
