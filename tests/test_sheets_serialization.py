from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from gatherradar.deduplication import canonicalize
from gatherradar.domain.event import CanonicalDiagnostic
from gatherradar.domain.temporal import DatePrecision
from gatherradar.sheets.schema import EVENT_HEADERS, EVENT_VISIBLE, cells
from gatherradar.sheets.serialization import event_row, jalali, price, quality, review_window, url
from deduplication_fakes import context
from sheets_fakes import OfflineCase, STAMP


class SerializationTests(OfflineCase):
    def event(self, **fields):
        return replace(canonicalize([context()]).events[0], **fields)

    def test_persian_headers_and_technical_alignment(self):
        e = self.event()
        row = event_row(e, 'run')
        self.assertEqual(len(row), len(EVENT_HEADERS))
        self.assertEqual(row[EVENT_HEADERS.index('event_id')], e.event_id)
        self.assertEqual(row[0], 'بررسی نشده')
        self.assertEqual(row[EVENT_HEADERS.index('start_date_iso')], '2026-10-01')
        self.assertNotIn('raw_text', EVENT_HEADERS)

    def test_jalali_and_weekday_use_normalized_date(self):
        row = event_row(self.event(start_date=date(2026, 9, 27), source_date_text='contradictory weekday'), 'run')
        self.assertEqual(row[4:6], ['۵ مهر ۱۴۰۵', 'یکشنبه'])

    def test_nowruz_boundary(self):
        self.assertEqual(jalali(date(2025, 3, 20)), '۳۰ اسفند ۱۴۰۳')
        self.assertEqual(jalali(date(2025, 3, 21)), '۱ فروردین ۱۴۰۴')

    def test_missing_dates_are_blank(self):
        row = event_row(self.event(start_date=None, starts_at=None, start_time=None), 'run')
        self.assertEqual(row[4:9], ['', '', '', '', ''])
        self.assertEqual(row[EVENT_HEADERS.index('کیفیت داده')], 'تاریخ نامشخص')

    def test_range_end_display(self):
        row = event_row(self.event(end_date=date(2026, 10, 2), date_precision=DatePrecision.RANGE), 'run')
        self.assertEqual(row[7], jalali(date(2026, 10, 2)))

    def test_price_preserves_wording(self):
        self.assertEqual(price(self.event(price_text='از ۵۰۰ هزار تومان', price_amount=Decimal('600'))), 'از ۵۰۰ هزار تومان')

    def test_decimal_toman_and_irr_are_not_converted(self):
        self.assertEqual(price(self.event(price_amount=Decimal('123.45'), currency='TOMAN')), '۱۲۳.۴۵ تومان')
        self.assertEqual(price(self.event(price_amount=Decimal('123.45'), currency='IRR')), '۱۲۳.۴۵ ریال')

    def test_free_and_unknown(self):
        self.assertEqual(price(self.event(price_amount=0)), 'رایگان')
        self.assertEqual(price(self.event()), '')

    def test_source_links_are_distinct_and_registration_separate(self):
        e = self.event(evidence_urls=('https://example.test/a', 'https://example.test/b'),
                       registration_url='https://example.test/tickets')
        row = event_row(e, 'run')
        self.assertEqual(row[EVENT_HEADERS.index('ثبت‌نام / خرید')], e.registration_url)
        self.assertEqual(row[EVENT_HEADERS.index('منبع اصلی')], e.canonical_source_url)
        self.assertIn('https://example.test/a', row[EVENT_HEADERS.index('همه منابع')])
        self.assertNotIn(e.registration_url, row[EVENT_HEADERS.index('همه منابع')])

    def test_unsafe_urls_rejected(self):
        for value in ('javascript:alert(1)', 'https://user:pass@example.test/', 'https://example.test/ a', 'https://example.test:bad/'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                url(value)

    def test_source_formula_prefixes_are_literal(self):
        for value in ('=IMPORTXML("https://example.test", "//x")', '+123', '-5', '@SUM(A1)'):
            with self.subTest(value=value):
                row = event_row(self.event(title=value, summary=value), 'run', (value, value))
                values = cells(row)['values']
                self.assertEqual(values[1]['userEnteredValue'], {'stringValue': value})
                self.assertNotIn('formulaValue', str(values))

    def test_multiline_urls_are_explicit_rich_links(self):
        links = ['https://example.test/اول', 'https://example.test/second']
        cell = cells(['\n'.join(links)])['values'][0]
        runs = cell['textFormatRuns']
        self.assertEqual([r['format']['link']['uri'] for r in runs], links)
        self.assertEqual(runs[1]['startIndex'], len(links[0].encode('utf-16-le')) // 2 + 1)

    def test_formula_looking_urls_and_embedded_credentials_are_not_linkified(self):
        for value in ('=https://example.test', 'https://user:secret@example.test/', 'https://example.test\nnot a URL'):
            self.assertNotIn('textFormatRuns', cells([value])['values'][0])

    def test_diagnostics_are_explicit(self):
        self.assertEqual(quality(self.event(diagnostics=(CanonicalDiagnostic('field_conflict', 'city'),))), 'تعارض داده')
        self.assertEqual(quality(self.event(diagnostics=(CanonicalDiagnostic('normalization:missing_price', 'price'),))), 'نیاز به بررسی')


class WindowTests(OfflineCase):
    def event(self, **fields):
        return replace(canonicalize([context()]).events[0], **fields)

    def test_inclusive_horizon_and_expired(self):
        dates = [date(2026, 9, 24), date(2026, 9, 25), date(2026, 10, 9), date(2026, 10, 10)]
        events = tuple(self.event(event_id=str(i), start_date=d, starts_at=None, ends_at=None,
                                 date_precision=DatePrecision.DAY) for i, d in enumerate(dates))
        result = review_window(events, STAMP, 14)
        self.assertEqual([e.event_id for e in result.events], ['1', '2'])
        self.assertEqual(result.filtered, 2)

    def test_overlapping_range_survives(self):
        e = self.event(start_date=date(2026, 9, 1), end_date=date(2026, 9, 26), date_precision=DatePrecision.RANGE)
        self.assertEqual(review_window((e,), STAMP).events, (e,))

    def test_undated_after_dated_and_stable_time_ties(self):
        unknown = self.event(event_id='unknown', start_date=None, date_precision=DatePrecision.UNKNOWN)
        late = self.event(event_id='late', start_time=time(19))
        early = self.event(event_id='early', start_time=time(9))
        result = review_window((unknown, late, early), STAMP)
        self.assertEqual([e.event_id for e in result.events], ['early', 'late'])
        self.assertEqual(result.schedule_review, (unknown,))
        self.assertEqual(result.undated, 1)

    def test_review_timezone_determines_today(self):
        start = datetime(2026, 9, 24, 22, tzinfo=timezone.utc)
        e = self.event(start_date=date(2026, 9, 24), start_time=None, end_time=None,
                       starts_at=None, ends_at=None, timezone='Asia/Tehran', date_precision=DatePrecision.DAY)
        self.assertEqual(review_window((e,), start, review_timezone='Asia/Tehran').filtered, 1)
        self.assertEqual(review_window((e,), start, review_timezone='UTC').filtered, 1)

    def test_invalid_windows_and_naive_clock_rejected(self):
        for days in (0, 91, True, '14'):
            with self.subTest(days=days), self.assertRaises(ValueError):
                review_window((), STAMP, days)
        with self.assertRaises(ValueError):
            review_window((), STAMP.replace(tzinfo=None))
