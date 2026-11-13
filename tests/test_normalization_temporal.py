import unittest
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone

from persiantools.jdatetime import JalaliDate

from gatherradar.domain import RawItem, Source, SourceType
from gatherradar.domain.temporal import DatePrecision
from gatherradar.normalization import NormalizationStatus, normalize_temporal
from gatherradar.normalization.text import fold

SOURCE = Source('sample', 'sample', 'Sample', SourceType.WEBSITE, 'https://example.org')
RAW = RawItem('raw:1', SOURCE.id, SOURCE.source_type, '1', 'webpage',
              'https://example.org/1', '', datetime(2026, 9, 24, 12, tzinfo=timezone.utc))


def temporal(text, *, raw=RAW, source=SOURCE):
    return normalize_temporal(text, raw, source)


def codes(result):
    return {d.code for d in result.diagnostics}


class TemporalNormalizationTests(unittest.TestCase):
    def test_script_folding(self):
        self.assertEqual(fold('كي ۱۲٣\u00a0 ۴\u200c۵'), 'کی 123 4 5')

    def test_three_digit_scripts(self):
        for text in ('۲ مهر ۱۴۰۵', '٢ مهر ١٤٠٥', '2 مهر 1405'):
            with self.subTest(text=text):
                self.assertEqual(temporal(text).start_date, date(2026, 9, 24))

    def test_character_variants(self):
        self.assertEqual(temporal('٢٥ شهريور ١٤٠٥').start_date, date(2026, 9, 16))

    def test_date_only_no_midnight(self):
        result = temporal('۲ مهر ۱۴۰۵')
        self.assertEqual(result.date_precision, DatePrecision.DAY)
        self.assertIsNone(result.start_time)
        self.assertIsNone(result.starts_at)
        self.assertIsNone(result.end_date)

    def test_explicit_date_and_clock(self):
        result = temporal('پنجشنبه ۲ مهر ۱۴۰۵ ساعت ۲۰:۳۰')
        self.assertEqual(result.starts_at.isoformat(), '2026-09-24T20:30:00+03:30')
        self.assertEqual(result.date_precision, DatePrecision.EXACT)
        self.assertEqual(result.status, NormalizationStatus.NORMALIZED)

    def test_date_and_hour(self):
        self.assertEqual(temporal('۲ مهر ۱۴۰۵ ساعت ۱۸').start_time, time(18))

    def test_date_and_range(self):
        result = temporal('۲ مهر ۱۴۰۵ از ساعت ۱۶ تا ۲۰')
        self.assertEqual(result.ends_at.isoformat(), '2026-09-24T20:00:00+03:30')
        self.assertEqual(result.starts_at.date(), result.ends_at.date())

    def test_date_and_bare_time_range(self):
        result = temporal('۲ مهر ۱۴۰۵\n۱۰ تا ۱۹')
        self.assertEqual((result.start_time, result.end_time), (time(10), time(19)))

    def test_times_without_date(self):
        for text in ('ساعت ۲۰:۳۰', '۲۰:۳۰', 'ساعت ۱۸', 'از ساعت ۱۶ تا ۲۰', '۱۰ تا ۱۹'):
            with self.subTest(text=text):
                result = temporal(text)
                self.assertIsNotNone(result.start_time)
                self.assertIsNone(result.starts_at)
                self.assertEqual(result.status, NormalizationStatus.PARTIAL)
                self.assertEqual(result.date_precision, DatePrecision.UNKNOWN)

    def test_same_month_range(self):
        result = temporal('۲۵ تا ۲۷ شهریور ۱۴۰۵')
        self.assertEqual((result.start_date, result.end_date), (date(2026, 9, 16), date(2026, 9, 18)))
        self.assertEqual(result.date_precision, DatePrecision.RANGE)
        self.assertIsNone(result.starts_at)

    def test_cross_month_range(self):
        result = temporal('۲۷ شهریور تا ۱۵ آبان ۱۴۰۵')
        self.assertEqual((result.start_date, result.end_date), (date(2026, 9, 18), date(2026, 11, 6)))

    def test_explicit_cross_year_range(self):
        result = temporal('۲۹ اسفند ۱۴۰۴ تا ۲ فروردین ۱۴۰۵')
        self.assertEqual((result.start_date, result.end_date), (date(2026, 3, 20), date(2026, 3, 22)))

    def test_reversed_date_range_invalid(self):
        result = temporal('۱۵ آبان تا ۲۷ شهریور ۱۴۰۵')
        self.assertIn('invalid_date', codes(result))
        self.assertIsNone(result.start_date)

    def test_calendar_reference_values(self):
        # Verified against persiantools 6.2.0, Gregorian datetime and weekday.
        cases = [((1399, 12, 30), date(2021, 3, 20)), ((1400, 1, 1), date(2021, 3, 21)),
                 ((1404, 1, 1), date(2025, 3, 21)), ((1405, 1, 1), date(2026, 3, 21))]
        for jalali, gregorian in cases:
            self.assertEqual(JalaliDate(*jalali).to_gregorian(), gregorian)

    def test_leap_esfand(self):
        self.assertEqual(temporal('۳۰ اسفند ۱۳۹۹').start_date, date(2021, 3, 20))

    def test_invalid_nonleap_esfand(self):
        self.assertIn('invalid_date', codes(temporal('۳۰ اسفند ۱۴۰۰')))

    def test_invalid_day(self):
        for text in ('۳۲ مهر ۱۴۰۵', '۰ مهر ۱۴۰۵', '۳۱ مهر ۱۴۰۵'):
            self.assertEqual(temporal(text).status, NormalizationStatus.INVALID)

    def test_malformed_year_is_not_replaced_with_inferred_year(self):
        for text in ('۲ مهر ۱۴۰۵۰', '۲ مهر ۱۴۰', '۲ مهر ۱۴۰۵ ۱۴۰۶'):
            result = temporal(text)
            self.assertIsNone(result.start_date)
            self.assertEqual(result.status, NormalizationStatus.INVALID)

    def test_all_month_names(self):
        months = 'فروردین اردیبهشت خرداد تیر مرداد شهریور مهر آبان آذر دی بهمن اسفند'.split()
        for number, month in enumerate(months, 1):
            self.assertEqual(temporal(f'۱ {month} ۱۴۰۵').start_date, JalaliDate(1405, number, 1).to_gregorian())

    def test_yearless_near_reference(self):
        result = temporal('۲ مهر ساعت ۱۸')
        self.assertEqual(result.start_date, date(2026, 9, 24))
        self.assertIn('inferred_year', codes(result))
        self.assertEqual(result.date_precision, DatePrecision.INFERRED)
        self.assertEqual(result.status, NormalizationStatus.PARTIAL)

    def test_yearless_far_from_reference(self):
        result = temporal('۱ فروردین')
        self.assertIsNone(result.start_date)
        self.assertIn('missing_year', codes(result))

    def test_year_inference_window_is_inclusive_and_bounded(self):
        for offset in (-46, -45, 45, 46):
            raw = replace(RAW, captured_at=RAW.captured_at + timedelta(days=offset))
            result = temporal('۲ مهر', raw=raw)
            self.assertEqual(result.start_date is not None, abs(offset) <= 45)

    def test_yearless_impossible_day_invalid(self):
        self.assertEqual(temporal('۳۲ مهر').status, NormalizationStatus.INVALID)

    def test_yearless_range_duration_bound(self):
        result = temporal('۲ مهر تا ۱۵ بهمن')
        self.assertIsNone(result.start_date)
        self.assertIn('missing_year', codes(result))

    def test_yearless_before_nowruz(self):
        raw = replace(RAW, captured_at=datetime(2026, 3, 20, tzinfo=timezone.utc))
        self.assertEqual(temporal('۲ فروردین', raw=raw).start_date, date(2026, 3, 22))

    def test_yearless_after_nowruz_does_not_roll_forward(self):
        raw = replace(RAW, captured_at=datetime(2026, 3, 22, tzinfo=timezone.utc))
        self.assertEqual(temporal('۲۹ اسفند', raw=raw).start_date, date(2026, 3, 20))

    def test_yearless_range(self):
        result = temporal('۲۷ شهریور تا ۱۵ آبان')
        self.assertEqual(result.end_date, date(2026, 11, 6))
        self.assertIn('inferred_year', codes(result))

    def test_yearless_cross_nowruz_range_unresolved(self):
        raw = replace(RAW, captured_at=datetime(2026, 3, 20, tzinfo=timezone.utc))
        self.assertIsNone(temporal('۲۹ اسفند تا ۲ فروردین', raw=raw).start_date)

    def test_weekday_agreement(self):
        self.assertEqual(temporal('پنج شنبه ۲ مهر ۱۴۰۵').start_date, date(2026, 9, 24))

    def test_weekday_contradiction(self):
        result = temporal('جمعه ۲ مهر ۱۴۰۵ ساعت ۱۸')
        self.assertIsNone(result.start_date)
        self.assertIsNone(result.starts_at)
        self.assertEqual(result.status, NormalizationStatus.INVALID)
        self.assertIn('weekday_contradiction', codes(result))

    def test_weekday_alone(self):
        self.assertIsNone(temporal('جمعه').start_date)

    def test_today_and_tomorrow(self):
        raw = replace(RAW, published_at=RAW.captured_at)
        self.assertEqual(temporal('امروز', raw=raw).start_date, date(2026, 9, 24))
        self.assertEqual(temporal('فردا ساعت ۱۸', raw=raw).start_date, date(2026, 9, 25))

    def test_published_reference_preferred(self):
        raw = replace(RAW, published_at=datetime(2021, 3, 20, 22, tzinfo=timezone.utc))
        result = temporal('امروز', raw=raw)
        self.assertEqual(result.start_date, date(2021, 3, 21))
        self.assertEqual(result.reference_basis, 'published_at')
        self.assertEqual(result.reference_at, raw.published_at)

    def test_capture_reference_never_resolves_relative_announcement(self):
        self.assertEqual(temporal('امروز').reference_basis, 'captured_at')
        self.assertIsNone(temporal('امروز').start_date)
        self.assertIn('unknown_publication_reference', codes(temporal('امروز')))

    def test_reference_in_source_timezone(self):
        raw = replace(RAW, published_at=datetime(2026, 9, 24, 1, tzinfo=timezone.utc))
        source = replace(SOURCE, timezone='America/New_York')
        self.assertEqual(temporal('امروز', raw=raw, source=source).start_date, date(2026, 9, 23))

    def test_broad_relative(self):
        for text in ('این هفته', 'آخر هفته', 'هفته آینده', 'next week'):
            result = temporal(text)
            self.assertIsNone(result.start_date)
            self.assertIn('broad_relative_date', codes(result))

    def test_discrete_dates(self):
        for text in ('۱ و ۲ مهر', '۱، ۲ مهر ۱۴۰۵', '۱ مهر ۱۴۰۵ و ۲ مهر ۱۴۰۵', '2026-09-24 and 2026-09-25'):
            result = temporal(text)
            self.assertIsNone(result.start_date)
            self.assertIsNone(result.end_date)
            self.assertIn('multiple_dates', codes(result))

    def test_recurring_schedule(self):
        result = temporal('۲۷ شهریور تا ۱۵ آبان ۱۴۰۵ دوشنبه تا جمعه هر هفته ساعت ۱۶ تا ۲۰')
        self.assertEqual(result.start_date, date(2026, 9, 18))
        self.assertIsNone(result.starts_at)
        self.assertIsNone(result.ends_at)
        self.assertIn('recurring_schedule', codes(result))

    def test_multiday_hours(self):
        result = temporal('۲۷ شهریور تا ۱۵ آبان ۱۴۰۵ ساعت ۱۶ تا ۲۰')
        self.assertEqual(result.start_time, time(16))
        self.assertIsNone(result.starts_at)
        self.assertIsNone(result.ends_at)
        self.assertIn('multi_day_hours', codes(result))

    def test_overnight_is_not_assumed(self):
        for text in ('۲ مهر ۱۴۰۵ ساعت ۲۲ تا ۲', '۲ مهر ۱۴۰۵ ساعت ۱۸ تا ۱۸'):
            result = temporal(text)
            self.assertIsNone(result.starts_at)
            self.assertIsNone(result.ends_at)
            self.assertIn('ambiguous_overnight', codes(result))

    def test_invalid_times(self):
        for text in ('۲ مهر ۱۴۰۵ ساعت ۲۴:۰۰', '۲ مهر ۱۴۰۵ ساعت ۱۸:۶۰', 'ساعت ۹۹', 'از ساعت ۱۶ تا ۲۵'):
            self.assertIn('invalid_time', codes(temporal(text)))

    def test_no_clock_correction(self):
        # A day-part word is read only inside fixed bounds (see test_persian_day_parts);
        # "۲ شب" could be 02:00 or 14:00 and is never corrected.
        for text in ('۲۰:۳', '۲۰:۳۰:۴۵', '-۱:۰۰', 'ساعت ۲ شب'):
            result = temporal(text)
            self.assertIsNone(result.start_time)
            self.assertIsNone(result.starts_at)

    def test_other_timezone(self):
        result = temporal('2026-09-24 20:30', source=replace(SOURCE, timezone='Europe/Paris'))
        self.assertEqual(result.starts_at.isoformat(), '2026-09-24T20:30:00+02:00')

    def test_invalid_timezone(self):
        result = temporal('۲ مهر ۱۴۰۵ ساعت ۱۸', source=replace(SOURCE, timezone='Invalid/Zone'))
        self.assertEqual(result.status, NormalizationStatus.INVALID)
        self.assertIsNone(result.timezone)
        self.assertIsNone(result.starts_at)

    def test_dst_gap_and_fold(self):
        for text in ('2026-03-08 02:30', '2026-11-01 01:30'):
            result = temporal(text, source=replace(SOURCE, timezone='America/New_York'))
            self.assertIn('ambiguous_local_time', codes(result))
            self.assertIsNone(result.starts_at)

    def test_iso_date(self):
        self.assertEqual(temporal('2026-09-24').start_date, date(2026, 9, 24))

    def test_invalid_iso(self):
        self.assertIn('invalid_date', codes(temporal('2026-02-30')))

    def test_ambiguous_numeric(self):
        for text in ('03/04/2026', '1405-07-02'):
            self.assertIsNone(temporal(text).start_date)

    def test_missing_and_oversize(self):
        self.assertIn('missing_date', codes(temporal(None)))
        self.assertIn('temporal_too_long', codes(temporal('x' * 4097)))

    def test_determinism(self):
        for text in ('فردا ساعت ۱۸', '۲ مهر', 'آخر هفته', '۲ مهر ۱۴۰۵ ساعت ۲۵'):
            self.assertEqual(temporal(text), temporal(text))

    def test_mehr_is_not_recurrence(self):
        self.assertNotIn('recurring_schedule', codes(temporal('چهارشنبه ۸ مهر ماه - ساعت')))

    def test_weekdays_on_range_endpoints(self):
        result = temporal('چهارشنبه ۱ مهر تا جمعه ۳ مهر ۱۴۰۵ ساعت ۱۰ تا ۲۱')
        self.assertEqual((result.start_date, result.end_date), (date(2026, 9, 23), date(2026, 9, 25)))
        self.assertIsNone(result.starts_at)

    def test_range_weekday_contradiction(self):
        for text in ('جمعه ۱ مهر تا جمعه ۳ مهر ۱۴۰۵', 'چهارشنبه ۱ مهر تا شنبه ۳ مهر ۱۴۰۵'):
            self.assertIn('weekday_contradiction', codes(temporal(text)))

    def test_qualified_dates_are_not_single_start_dates(self):
        for text in ('تا ۲ مهر ۱۴۰۵', 'بعد از ۲ مهر ۱۴۰۵', 'حدود ۲ مهر ۱۴۰۵'):
            self.assertIsNone(temporal(text).start_date)

    def test_incomplete_clock_not_repaired(self):
        self.assertIsNone(temporal('ساعت ۲۰:').start_time)


if __name__ == '__main__':
    unittest.main()
