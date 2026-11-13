"""Temporal/field defects confirmed in live run e3ddedf31d5248808f78e5586b58d703 (2026-10-29).

Positive inputs reuse the live caption/page wording from the owner's review.json;
each grammar has negative cases. See docs/LIVE_RUN_QA_2026-10-29.md.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, time, timezone

from gatherradar.extraction import fields
from gatherradar.extraction.signals import analyze
from gatherradar.normalization.text import fold
from gatherradar.normalization.times import parse_times
from gatherradar.review.readiness import assess_readiness
from gatherradar.review.relevance import assess_relevance
from test_event_recall import PUBLISHED, pipeline

RUN = datetime(2026, 10, 29, 12, 54, 35, tzinfo=timezone.utc)  # live run start


def event(text):
    events, _ = pipeline(text, published=PUBLISHED.replace(day=27))
    value, = events
    return value


def codes(value):
    return {d.code for d in value.diagnostics}


class DurationLabelIsNotDateLabelTests(unittest.TestCase):
    """Jabama 08945247: "مدت زمان: ۲ ساعت" became source_date_text "۲ ساعت"."""

    def test_nested_label_belongs_to_the_longer_label(self):
        found = analyze('چه برنامه‌ای داریم؟\nجزئیات ورکشاپ:\nمدت زمان: ۲ ساعت\nمتریال: خمیر هواخشک')
        self.assertIsNone(fields.source_date_text(found))
        self.assertEqual(fields.duration_text(found), '۲ ساعت')

    def test_real_date_label_after_a_duration_label_still_counts(self):
        for text in ('مدت زمان: ۲ ساعت\nزمان: ۸ آبان ساعت ۱۵', 'زمان: ۸ آبان\nمدت زمان: ۲ ساعت',
                     'مدت زمان برگزاری: ۹۰ دقیقه\nزمان برگزاری: ۸ آبان'):
            with self.subTest(text=text):
                found = analyze(text)
                self.assertTrue(fields.source_date_text(found).startswith('۸ آبان'))
                self.assertIsNotNone(fields.duration_text(found))


class MiddleDotSeparatorTests(unittest.TestCase):
    """Jabama 95037796: "۸ آبان · ۱۸:۰۰" lost its clock and went to schedule review."""

    def test_middle_dot_separates_date_and_clock(self):
        value = event('رویداد هالووین\n۸ آبان · ۱۸:۰۰\nثبت نام')
        self.assertEqual((value.start_date, value.start_time), (date(2026, 10, 30), time(18)))
        self.assertNotIn('normalization:unparsed_temporal', codes(value))

    def test_middle_dot_does_not_rescue_unsupported_wording(self):
        value = event('رویداد هالووین\n۸ آبان · بزودی\nثبت نام')
        self.assertIsNone(value.start_time)  # no clock is invented after the separator


class MeridiemTests(unittest.TestCase):
    """Salovini De98iwhkf3A: "جمعه ۸ آبان / ساعت ۵" was published as 05:00."""

    def test_bare_early_hour_keeps_date_and_chooses_no_clock(self):
        value = event('ورکشاپ چارم‌بگ\nجمعه ۸ آبان\nساعت ۵')
        self.assertEqual(value.occurrences[0].start_date, date(2026, 10, 30))
        self.assertIsNone(value.occurrences[0].start_time)
        self.assertIn('normalization:ambiguous_meridiem', codes(value))
        self.assertEqual(assess_relevance(value, RUN).disposition, 'needs_schedule_review')
        self.assertIn('ambiguous_meridiem', assess_readiness(value).reasons)

    def test_day_part_words_are_kept_by_extraction_and_applied(self):
        cases = {'جمعه ۸ آبان ساعت ۵ عصر': (time(17), None), '۸ آبان ساعت ۸ شب': (time(20), None),
                 '۸ آبان ساعت ۱۰ صبح تا ۱ ظهر': (time(10), time(13)), '۸ آبان ساعت ۴ تا ۷ عصر': (time(16), time(19))}
        for wording, clocks in cases.items():
            with self.subTest(wording=wording):
                self.assertEqual(fields.source_date_text(analyze('کارگاه\n' + wording)), wording)
                value = event('کارگاه سفال\n' + wording + '\nثبت نام')
                self.assertEqual((value.start_time, value.end_time), clocks)

    def test_unsure_and_unambiguous_clocks(self):
        for text in ('ساعت ۵', 'ساعت ۵ تا ۸', 'ساعت ۱۲ شب', 'ساعت ۲ شب', 'ساعت ۱۴ صبح'):
            with self.subTest(text=text):
                parsed = parse_times(fold(text))
                self.assertIsNone(parsed.start)
                self.assertIn(parsed.diagnostics[0].code, {'ambiguous_meridiem'})
        for text, value in (('ساعت ۱۸', time(18)), ('ساعت ۷', time(7)), ('ساعت ۶:۰۰', time(6)),
                            ('ساعت ۱۷ عصر', time(17)), ('3 pm', time(15))):
            with self.subTest(text=text):
                self.assertEqual(parse_times(fold(text)).start, value)
        self.assertEqual(parse_times(fold('ساعت ۲۲ تا ۲')).diagnostics[0].code, 'ambiguous_overnight')


class WeekdayListPrefixTests(unittest.TestCase):
    """Salovini De98iwhkf3A: "جمعه و شنبه ۸ و ‎٩‏ آبان" was ambiguous_date_context."""

    def test_one_weekday_per_listed_day_in_order(self):
        value = event('ورکشاپ ساخت جاعودی\nجمعه و شنبه ۸ و ‎٩‏ آبان\nثبت نام')
        self.assertEqual([o.start_date for o in value.occurrences], [date(2026, 10, 30), date(2026, 10, 31)])
        self.assertTrue(all(o.start_time is None for o in value.occurrences))

    def test_wrong_order_or_count_is_a_contradiction(self):
        for wording in ('شنبه و جمعه ۸ و ۹ آبان', 'جمعه و شنبه و یکشنبه ۸ و ۹ آبان'):
            with self.subTest(wording=wording):
                value = event('ورکشاپ ساخت جاعودی\n' + wording + '\nثبت نام')
                self.assertEqual(value.occurrences, ())


if __name__ == '__main__':
    unittest.main()
