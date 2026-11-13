"""Explicit date lists with shared clocks, and conflicting header facts (cloud field hardening).

Detail pages are the Vadoostan multi-session fixture carrying the schedule and
length wording quoted by the frozen 2026-10-23 audit (Simorgh, Rokhdad). See
docs/CLOUD_FIELD_HARDENING_VALIDATION.md.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, time, timezone

from gatherradar.extraction.fields import duration_minutes
from gatherradar.review.readiness import DataReadiness, assess_readiness
from gatherradar.review.relevance import assess_relevance
from test_source_coverage import V_LIST, Pipeline, html, vadoostan_pages

RUN = datetime(2026, 10, 23, 19, 59, 11, tzinfo=timezone.utc)  # frozen run start
SESSION_DATES = (date(2026, 10, 27), date(2026, 11, 3), date(2026, 11, 10), date(2026, 11, 17))
SIMORGH = ('گروه «سیمرغ»: کوهپیمایی و داستان کودک برای بزرگسالان (4 جلسه)', '۵ آبان ساعت ۶:۰۰', 'درکه', '۳ ساعت', '''اگر کوه، ذهن‌آگاهی و معاشرت‌های عمیق با آدما به وجدت میاره، گروه سیمرغ جای توئه.
صبح ساعت ۵ میریم و تا حدود ۸ برمیگردیم.
📅 زمان: سه‌شنبه صبح‌ها
سه‌شنبه 5، 12، 19 و 26 آبان
۵ تا ۸ صبح
📍 مکان: درکه
ثبت‌نام شامل هر چهار جلسه است.''')
ROKHDAD = ('گروه کتاب‌خوانی «رخداد»: کتاب «ملت دوپامین» (۴ جلسه)', '۵ آبان ساعت ۱۹:۰۰', 'ایرانشهر - خیابان سمیه', '۲ ساعت', '''📘📗 کتابی که می‌خونیم در مورد چیه؟
توی این گروه‌ها یک کتاب رو طی چند جلسه می‌خونیم و در جلسه حضوری به کمک تسهیلگر گفتگو می‌کنیم.
🚨 توجه: این تجربه در چهار جلسه و به مدت یک ساعت و نیم به تاریخ ۵ آبان، ۱۲ آبان، ۱۹ آبان و ۲۶ آبان ساعت ۱۹ الی ۲۰:۳۰ برگزار خواهد شد. در صورتی که علاقه به شرکت در یک جلسه از تجربه رو دارید، می‌تونید با هماهنگی با پشتیبانی به صورت تک‌جلسه در تجربه شرکت کنید.''')


def collect_event(case, title, slot, area, length, description):
    """One detail page and its consistent listing card, collected at the frozen run time."""
    old = ('گروه کشف موسیقی: «جز و آزادی» (۴ جلسه)', '۵ مهر ساعت ۱۹:۰۰', 'ایرانشهر - خیابان سمیه')
    detail = html('vadoostan-multisession-detail.html')
    old_description = detail[detail.index('🪷'):detail.index('</div><hr class="q-separator"><div class="font-black mb-2.5">سوالات')]
    detail = (detail.replace(old[0], title).replace(old[1], slot).replace(old[2], area)
              .replace('۲ ساعت ', length + ' ').replace(old_description, description))
    clock = slot.split('ساعت ', 1)[1]
    listing = (html('vadoostan-list-cards.html').replace(old[0], title)
               .replace(' محله: ایرانشهر - خیابان سمیه ', f' محله: {area} ').replace(' ساعت: ۱۹:۰۰', f' ساعت: {clock}')
               .replace(' تکمیل ظرفیت ', '۱٬۲۰۰٬۰۰۰ تومان'))
    pipeline = Pipeline(case)
    pages = vadoostan_pages(**{V_LIST: listing, V_LIST + '/MusicGroupB2': detail})
    result = pipeline.collect('vadoostan_fixture', pages, limit=2, now=RUN)
    events = pipeline.review({'vadoostan_fixture': result.items}).events
    return next(e for e in events if e.title == title)


def codes(event):
    return {(d.code, d.field) for d in event.diagnostics}


class RokhdadSharedClockTests(unittest.TestCase):
    def setUp(self):
        self.event = collect_event(self, *ROKHDAD)

    def test_every_listed_date_keeps_the_explicitly_shared_clock(self):
        sessions = [(o.start_date, o.start_time, o.end_time) for o in self.event.occurrences]
        self.assertEqual(sessions, [(day, time(19), time(20, 30)) for day in SESSION_DATES])
        self.assertTrue(all(o.starts_at is not None for o in self.event.occurrences))
        self.assertIsNone(self.event.start_date)  # no session date is written into the parent

    def test_conflicting_lengths_are_not_chosen_and_are_explained(self):
        self.assertIsNone(self.event.duration_text)
        self.assertIn(('source_field_conflict', 'duration_text'), codes(self.event))
        self.assertIn('یک ساعت و نیم', self.event.source_schedule_text)  # alternative wording visible
        readiness = assess_readiness(self.event)
        self.assertIn('duration_conflict', readiness.reasons)
        self.assertIn('مدت', readiness.explanation)

    def test_actionable_at_frozen_run_with_all_sessions(self):
        value = assess_relevance(self.event, RUN)
        self.assertEqual(value.disposition, 'actionable')
        # 14-day horizon: 5 and 12 Aban are in the window, later sessions are not.
        self.assertEqual(len(value.occurrence_ids), 2)
        self.assertEqual(len(value.occurrence_dispositions), 4)

    def test_rerun_is_stable(self):
        again = collect_event(self, *ROKHDAD)
        self.assertEqual([o.occurrence_id for o in again.occurrences],
                         [o.occurrence_id for o in self.event.occurrences])
        self.assertEqual(again.event_id, self.event.event_id)


class SimorghClockConflictTests(unittest.TestCase):
    def setUp(self):
        self.event = collect_event(self, *SIMORGH)

    def test_dates_retained_date_only_with_explicit_clock_conflict(self):
        self.assertEqual([o.start_date for o in self.event.occurrences], list(SESSION_DATES))
        self.assertTrue(all(o.start_time is None and o.starts_at is None for o in self.event.occurrences))
        self.assertIn(('normalization:schedule_clock_conflict', 'source_schedule_text'), codes(self.event))
        self.assertEqual(self.event.source_date_text, '۵ آبان ساعت ۶:۰۰')  # header wording kept
        self.assertTrue(self.event.source_schedule_text.endswith('۵ تا ۸ صبح'))  # alternative clock visible
        self.assertIsNone(self.event.start_time)

    def test_routes_to_schedule_review_not_definitively_upcoming(self):
        self.assertEqual(assess_relevance(self.event, RUN).disposition, 'needs_schedule_review')
        readiness = assess_readiness(self.event)
        self.assertEqual(readiness.status, DataReadiness.SCHEDULE)
        self.assertIn('schedule_clock_conflict', readiness.reasons)

    def test_without_a_listed_clock_the_header_clock_stays_on_its_own_date(self):
        title, slot, area, length, description = SIMORGH
        description = description.replace('۵ تا ۸ صبح\n', '').replace('صبح ساعت ۵ میریم و تا حدود ۸ برمیگردیم.\n', '')
        event = collect_event(self, title, slot, area, length, description)
        self.assertEqual([(o.start_date, o.start_time) for o in event.occurrences],
                         [(SESSION_DATES[0], time(6)), *((d, None) for d in SESSION_DATES[1:])])
        self.assertNotIn(('normalization:schedule_clock_conflict', 'source_schedule_text'), codes(event))

    def test_weekday_contradiction_and_unordered_lists_are_not_expanded(self):
        title, slot, area, length, description = SIMORGH
        for changed in ('دوشنبه 5، 12، 19 و 26 آبان', 'سه‌شنبه 12، 5 آبان'):
            with self.subTest(changed=changed):
                event = collect_event(self, title, slot, area, length,
                                      description.replace('سه‌شنبه 5، 12، 19 و 26 آبان', changed))
                # Falls back to the previous header-only behaviour: never expanded.
                self.assertLessEqual(len(event.occurrences), 1)
                self.assertTrue({c for c, _ in codes(event)} & {'normalization:weekday_contradiction',
                                                                 'normalization:unresolved_schedule'})


class DurationParsingTests(unittest.TestCase):
    def test_minutes_of_explicit_lengths(self):
        for text, minutes in (('۲ ساعت', 120), ('یک ساعت و نیم', 90), ('۹۰ دقیقه', 90),
                              ('دو ساعت', 120), ('نیم ساعت', 30), ('سه‌روزه', None), ('چند ساعت', None)):
            with self.subTest(text=text):
                self.assertEqual(duration_minutes(text), minutes)


if __name__ == '__main__':
    unittest.main()
