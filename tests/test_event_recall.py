"""Source-grounded synthetic regressions; no owner files or live services."""
import unittest
from dataclasses import replace
from datetime import datetime, date, time, timezone
from zoneinfo import ZoneInfo

from gatherradar.domain import RawItem, Source, SourceType
from gatherradar.domain.evidence import EvidenceFragment, EvidenceKind
from gatherradar.extraction import DiscoveryService, RuleBasedDiscoveryProvider
from gatherradar.extraction.models import DiscoveryFacts
from gatherradar.normalization import NormalizationService
from gatherradar.orchestration.evidence_discovery_run import run_evidence_discovery
from gatherradar.orchestration.canonicalization_run import identity_slot
from gatherradar.deduplication import CandidateContext, canonicalize
from gatherradar.review.eligibility import eligible
from gatherradar.review.relevance import assess_relevance
from gatherradar.review.records import event_record, event_from_record

ZONE = ZoneInfo('Asia/Tehran')
REFERENCE = datetime.fromisoformat('2026-10-23T00:39:15.332636+03:30')
PUBLISHED = datetime(2026, 10, 22, 10, tzinfo=ZONE)
SOURCE = Source('sample_instagram', 'sample', 'Sample', SourceType.INSTAGRAM,
                'https://www.instagram.com/sample/', username='sample', timezone='Asia/Tehran')


def pipeline(text, media=(), published=PUBLISHED):
    raw = RawItem('instagram:sample:one', SOURCE.id, SOURCE.source_type, 'one', 'post',
                  'https://www.instagram.com/p/one/', text, REFERENCE, published_at=published)
    fragments = tuple(EvidenceFragment.create(raw_item_id=raw.id, kind=kind, text=value,
        source_url=raw.content_url, **({'slide_index': pos} if kind is EvidenceKind.CAROUSEL_SLIDE_OCR
                                    else {'frame_timestamp_ms': pos})) for kind, pos, value in media)
    discovered = run_evidence_discovery((raw,), fragments, DiscoveryService(RuleBasedDiscoveryProvider()),
                                        sources={SOURCE.id: SOURCE})
    units = {u.unit_id: u for item in discovered.items for u in item.units}
    contexts = []
    for outcome in discovered.outcomes:
        if outcome.event:
            unit = units[outcome.discovery_unit_id]
            normalized = NormalizationService().normalize(outcome.event, raw, SOURCE, evidence_text=unit.text)
            contexts.append(CandidateContext(normalized, outcome.event, raw, SOURCE, raw.captured_at, identity_slot(unit)))
    return canonicalize(contexts).events, discovered


class EventRecallTests(unittest.TestCase):
    def only(self, text, **kwargs):
        events, _ = pipeline(text, **kwargs)
        self.assertEqual(len(events), 1, events)
        self.assertTrue(eligible(events[0]), events[0])
        return events[0]

    def test_formal_caption_title(self):
        value = self.only('کارگاه سفال آبی\n۱ آبان ۱۴۰۵ ساعت ۱۸\nثبت نام')
        self.assertEqual(value.display_title_origin, 'explicit_caption')
        self.assertEqual(value.source_title, value.title)
        self.assertTrue(value.display_title_evidence_ids)

    def test_embedded_named_exhibition_and_daily_exception(self):
        value = self.only('نمایشگاه انفرادی «مانا» از هنرمند نمونه\n۲۴ مهر تا ۱۵ آبان ۱۴۰۵\nساعت ۱۳ تا ۲۱ (شنبه‌ها تعطیل)')
        self.assertEqual(value.title, 'نمایشگاه انفرادی مانا')
        self.assertEqual(value.source_title, 'نمایشگاه انفرادی «مانا»')
        self.assertEqual(value.occurrences[0].end_date, date(2026, 11, 6))
        self.assertIsNone(value.occurrences[0].starts_at)
        self.assertEqual(assess_relevance(value, REFERENCE).disposition, 'actionable')
        self.assertEqual(assess_relevance(value, REFERENCE.replace(month=11, day=7)).disposition, 'expired')

    def test_named_title_across_line_break(self):
        value = self.only('رویداد هنری با نام\n“رقص در دستان خزان”\n۲۹ مهر تا ۱ آبان ۱۴۰۵ ساعت ۱۲ الی ۲۲')
        self.assertEqual(value.title, 'رقص در دستان خزان')
        self.assertEqual(value.end_time, time(22))

    def test_descriptive_title_without_invented_hype(self):
        value = self.only('در این کارگاه شرکت‌کنندگان با ساخت شمع‌های دست‌ساز آشنا می‌شوند.\n۱ آبان ۱۴۰۵ ساعت ۱۸\nثبت نام')
        self.assertEqual(value.title, 'کارگاه ساخت شمع‌های دست‌ساز')
        self.assertIsNone(value.source_title)
        self.assertEqual(value.display_title_origin, 'derived_from_source_description')
        self.assertTrue(value.title_review_required)
        self.assertEqual(event_from_record(event_record(value)), value)
        self.assertFalse(eligible(replace(value, title='فستیوال بزرگ شمع‌سازی تهران')))
        self.assertFalse(eligible(replace(value, display_title_evidence_ids=('foreign',))))

    def test_media_only_titles_and_candidate_specific_evidence(self):
        for kind, pos in ((EvidenceKind.CAROUSEL_SLIDE_OCR, 0), (EvidenceKind.REEL_FRAME_OCR, 1000)):
            value = self.only('', media=((kind, pos, 'کارگاه سفال آبی\n۱ آبان ۱۴۰۵ ساعت ۱۸'),))
            self.assertEqual(value.display_title_origin, 'explicit_media_ocr')
            self.assertEqual(len(value.display_title_evidence_ids), 1)

    def test_multiple_events_in_one_carousel(self):
        events, _ = pipeline('تقویم این هفته؛ کدوم اسلاید؟', media=(
            (EvidenceKind.CAROUSEL_SLIDE_OCR, 1, 'کارگاه سفال آبی\n۱ آبان ۱۴۰۵ ساعت ۱۸'),
            (EvidenceKind.CAROUSEL_SLIDE_OCR, 2, 'کنسرت شب روشن\n۲ آبان ۱۴۰۵ ساعت ۲۰')))
        self.assertEqual(len(events), 2)
        self.assertNotEqual(events[0].display_title_evidence_ids, events[1].display_title_evidence_ids)
        self.assertTrue(all(eligible(e) for e in events))

    def test_complementary_slides_keep_identity(self):
        value = self.only('', media=(
            (EvidenceKind.CAROUSEL_SLIDE_OCR, 0, 'کارگاه سفال آبی'),
            (EvidenceKind.CAROUSEL_SLIDE_OCR, 1, 'تاریخ: ۱ آبان ۱۴۰۵\nساعت ۱۸\nثبت نام: https://example.org/ticket')))
        self.assertEqual(value.start_date, date(2026, 10, 23))
        self.assertEqual(len(value.evidence_fragment_ids), 2)

    def test_repeated_noisy_reel_workshop_uses_caption(self):
        text = 'تو این ورکشاپ فوت‌وفن درست کردن پیتزا رو یاد بگیری!\nدوشنبه ۲۷ مهر ساعت ۱۷\nثبت نام'
        value = self.only(text, media=(
            (EvidenceKind.REEL_FRAME_OCR, 1000, 'ورکشاپ پیتزاه دوشنبه yao ساعت ۱۷'),
            (EvidenceKind.REEL_FRAME_OCR, 2000, 'ورکشاپ پیتزا دوشنبه yao ساعت ۱۷')),
            published=PUBLISHED.replace(day=18))
        self.assertEqual(value.title, 'ورکشاپ ساخت پیتزا')
        self.assertEqual(assess_relevance(value, REFERENCE).disposition, 'expired')

    def test_different_clean_workshop_sessions_are_not_collapsed(self):
        events, _ = pipeline('تو این ورکشاپ درست کردن پیتزا رو یاد بگیری!\n۲۷ مهر ۱۴۰۵ ساعت ۱۷\nثبت نام', media=(
            (EvidenceKind.REEL_FRAME_OCR, 1000, 'ورکشاپ پیتزا\n۲۸ مهر ۱۴۰۵ ساعت ۱۸'),))
        self.assertEqual(len(events), 2)

    def test_cross_source_title_address_variants_are_reviewed_not_merged(self):
        from deduplication_fakes import context, changed
        from gatherradar.deduplication.matcher import match_pair
        from gatherradar.deduplication.models import MatchKind
        a = context('one', publisher='one', title='رقص در دستان خزان', end_time=time(22),
                    address='عمارت نمونه، خیابان آبی، کوچه گل')
        b = context('two', publisher='two', title='رویداد هنری رقص دستان در خزان', end_time=time(22),
                    address='تهران، خیابان آبی، کوچه گل، عمارت نمونه')
        self.assertEqual(match_pair(a, b).kind, MatchKind.POSSIBLE_DUPLICATE)
        self.assertNotEqual(match_pair(a, changed(b, start_date=date(2026, 10, 2))).kind, MatchKind.SAME_EVENT)

    def test_non_event_and_collection_guards(self):
        examples = ('فروش محصول جدید؛ تبلیغات کارگاه سفال، تخفیف ثبت نام محصول',
                    'کافه آرام؛ تهران؛ هر روز ساعت ۹ تا ۲۰',
                    'این هفته رویدادهایی رو گرد هم آوردیم؛ تقویم این هفته',
                    'کارگاه سفال برگزار شد. خاطرات و گزارش تصویری',
                    'تهران ۱ آبان ۱۴۰۵، روز خوبی داشته باشید')
        for text in examples:
            with self.subTest(text=text):
                events, _ = pipeline(text)
                self.assertEqual(events, ())

    def test_ambiguous_series_is_diagnostic_not_canonical(self):
        events, discovery = pipeline('هر آخر هفته کنار هم فیلم میبینیم، کتاب میخونیم و کنار روانشناس گفتگو میکنیم. برای ثبت نام برنامه‌ها پیام بدین')
        self.assertEqual(events, ())
        self.assertTrue(any(o.evidence and 'needs_evidence' in o.evidence.reason for o in discovery.outcomes))

    def test_historical_bilingual_range_is_expired(self):
        value = self.only('فستیوال اکتبر برگزار شد.\nOktober in Istanbul took place from October 2 to 4, 2026.')
        self.assertEqual((value.start_date, value.end_date), (date(2026, 10, 2), date(2026, 10, 4)))
        self.assertEqual(assess_relevance(value, REFERENCE).disposition, 'expired')

    def test_english_date_keeps_clock_and_competing_calendar_evidence(self):
        value = self.only('کارگاه سفال آبی\nOctober 23, 2026\nساعت ۱۸ تا ۲۰')
        self.assertEqual(value.start_time, time(18))
        self.assertEqual(value.end_time, time(20))
        value = self.only('کارگاه سفال آبی\nOctober 23, 2026\n۳ آبان ۱۴۰۵ ساعت ۱۸')
        self.assertEqual(assess_relevance(value, REFERENCE).disposition, 'needs_schedule_review')

    def test_mixed_past_and_future_announcements_in_one_caption(self):
        events, _ = pipeline('کارگاه سفال آبی\n۲۷ مهر ۱۴۰۵ ساعت ۱۸ برگزار شد.\n\nکنسرت نوای روشن\n۱ آبان ۱۴۰۵ ساعت ۲۰\nثبت نام')
        self.assertEqual(len(events), 2)
        self.assertEqual({assess_relevance(e, REFERENCE).disposition for e in events}, {'expired', 'actionable'})
        self.assertNotEqual(events[0].event_id, events[1].event_id)

    def test_separate_date_clock_pairs_keep_future_session(self):
        value = self.only('نمایشگاه برآیند\nزمان: ۳۰ مهرماه: ساعت ۱۶ الی ۲۰، ۱ آبان‌ماه: ساعت۱۲ الی ۲۰')
        self.assertEqual([(o.start_date, o.start_time) for o in sorted(value.occurrences, key=lambda o:o.start_date)],
                         [(date(2026, 10, 22), time(16)), (date(2026, 10, 23), time(12))])
        decision = assess_relevance(value, REFERENCE)
        self.assertEqual(decision.disposition, 'actionable')
        self.assertEqual(len(decision.occurrence_ids), 1)

    def test_source_relative_pair_with_weekday_corroboration(self):
        value = self.only('رویداد فروش جادویی\nامروز و فردا قراره دور هم باشیم\nزمان: پنجشنبه و جمعه از ۱۱ تا ۲۳')
        self.assertEqual({o.start_date for o in value.occurrences}, {date(2026, 10, 22), date(2026, 10, 23)})
        self.assertEqual(assess_relevance(value, REFERENCE.replace(day=30)).disposition, 'expired')

    def test_finite_prose_session_list_keeps_only_supported_clocks(self):
        from gatherradar.normalization.schedules import normalize_schedule
        from gatherradar.domain import EventCandidate
        raw = RawItem('raw:dates', SOURCE.id, SOURCE.source_type, 'dates', 'post',
                      'https://example.org/a', '', REFERENCE, published_at=PUBLISHED)
        candidate = EventCandidate('candidate:dates', raw.id, True, title='کارگاه بازیگری',
            source_date_text='۱ آبان ۱۴۰۵ ساعت ۱۳:۳۰',
            source_schedule_text='این گروه در چهار جلسه جمعه‌ها به تاریخ، 1، 8، 15 و 22 آبان ۱۴۰۵ برگزار خواهد شد')
        result = normalize_schedule(candidate, raw, SOURCE)
        self.assertEqual(len(result.occurrences), 4)
        self.assertEqual([o.start_date for o in result.occurrences],
                         [date(2026, 10, 23), date(2026, 10, 30), date(2026, 11, 6), date(2026, 11, 13)])
        self.assertEqual([o.start_time for o in result.occurrences], [time(13, 30), None, None, None])
        self.assertTrue(all(o.candidate_ids == (candidate.candidate_id,) for o in result.occurrences))
        conflict = normalize_schedule(replace(candidate, source_schedule_text=
            candidate.source_schedule_text.replace('جمعه', 'شنبه')), raw, SOURCE)
        self.assertTrue(any(d.code == 'weekday_contradiction' for d in conflict.diagnostics))

    def test_unknown_publication_never_uses_capture_for_relative_dates(self):
        value = self.only('کارگاه سفال آبی\nفردا ساعت ۱۸\nثبت نام', published=None)
        self.assertFalse(value.occurrences)
        self.assertEqual(assess_relevance(value, REFERENCE).disposition, 'needs_schedule_review')

    def test_recurring_schedule_does_not_invent_future_sessions(self):
        value = self.only('کارگاه سفال آبی\nهر جمعه ساعت ۱۸\nثبت نام')
        self.assertFalse(value.occurrences)
        self.assertEqual(assess_relevance(value, REFERENCE).disposition, 'needs_schedule_review')

    def test_verified_sessions_can_corroborate_a_recurring_schedule(self):
        from gatherradar.normalization.schedules import normalize_schedule
        from gatherradar.domain import EventCandidate
        from gatherradar.domain.website import SourceSession
        raw = RawItem('raw:weekly', SOURCE.id, SOURCE.source_type, 'weekly', 'post',
                      'https://example.org/a', '', REFERENCE, published_at=PUBLISHED)
        candidate = EventCandidate('candidate:weekly', raw.id, True, title='نمایش عروسکی',
            source_date_text='چهارشنبه‌ها ساعت ۱۸', source_sessions=(
                SourceSession('one', 'weekly', '2026-10-28T14:30:00Z', 'react-router:loaderData/routes/events.$id/sessions/0'),
                SourceSession('two', 'weekly', '2026-11-04T14:30:00Z', 'react-router:loaderData/routes/events.$id/sessions/1')))
        result = normalize_schedule(candidate, raw, SOURCE)
        self.assertEqual(len(result.occurrences), 2)
        self.assertEqual(result.schedule_kind.value, 'recurring')
        self.assertEqual(result.recurrence_rule, 'FREQ=WEEKLY;BYDAY=WE')
        self.assertFalse(any(d.code == 'schedule_conflict' for d in result.diagnostics))
        event = self.only('کارگاه سفال آبی\n۱ آبان ۱۴۰۵ ساعت ۱۸')
        event = replace(event, occurrences=result.occurrences, schedule_kind=result.schedule_kind,
                        recurrence_rule=result.recurrence_rule)
        self.assertEqual(assess_relevance(event, REFERENCE).disposition, 'actionable')
        self.assertEqual(assess_relevance(event, REFERENCE.replace(month=12)).disposition, 'needs_schedule_review')
        conflict = normalize_schedule(replace(candidate, source_date_text='شنبه‌ها ساعت ۱۸'), raw, SOURCE)
        self.assertEqual(conflict.schedule_kind.value, 'conflict')

    def test_date_only_and_unknown_end_are_actionable(self):
        for schedule in ('۱ آبان ۱۴۰۵', '۱ آبان ۱۴۰۵ ساعت ۰۰:۱۰'):
            value = self.only('کارگاه سفال آبی\n' + schedule)
            self.assertIsNone(value.ends_at)
            self.assertEqual(assess_relevance(value, REFERENCE).disposition, 'actionable')

    def test_contradictory_dates_stay_reviewable(self):
        value = self.only('کارگاه سفال آبی\nزمان: ۱ آبان ۱۴۰۵ و ۳ آبان ۱۴۰۵ یا شاید ۵ آبان')
        self.assertEqual(assess_relevance(value, REFERENCE).disposition, 'needs_schedule_review')

    def test_source_timezone_conversion_at_jalali_year_boundary(self):
        raw = RawItem('raw:year', SOURCE.id, SOURCE.source_type, 'year', 'post', 'https://example.org/a',
            'امروز', REFERENCE, published_at=datetime(2021,3,20,22,tzinfo=timezone.utc))
        from gatherradar.normalization import normalize_temporal
        result = normalize_temporal('امروز', raw, SOURCE)
        self.assertEqual(result.start_date, date(2021,3,21))

    def test_readable_past_calendar_survives_corrupted_ocr_clock(self):
        value = self.only('', media=((EvidenceKind.CAROUSEL_SLIDE_OCR, 1,
            'ایونت بازی و گفتگو\n21:30 جمعه 17 مهر ساعت 18:30 تا ۹'),), published=PUBLISHED.replace(day=6))
        self.assertEqual(value.start_date, date(2026, 10, 9))
        self.assertIsNone(value.start_time)
        self.assertEqual(assess_relevance(value, REFERENCE).disposition, 'expired')

    def test_provider_cannot_claim_derived_text_from_another_candidate(self):
        from gatherradar.domain import DiscoveryType
        from unittest.mock import Mock
        provider = Mock(name='unsafe')
        provider.discover.return_value = DiscoveryFacts(DiscoveryType.EVENT, title='کارگاه ساخت طلا',
            display_title_origin='derived_from_source_description', title_evidence_text='در این کارگاه ساخت طلا را یاد بگیرید.')
        raw = RawItem('raw:fake', SOURCE.id, SOURCE.source_type, 'fake', 'post', 'https://example.org/a',
                      'کارگاه سفال آبی\n۱ آبان ساعت ۱۸', REFERENCE, published_at=PUBLISHED)
        outcome = DiscoveryService(provider).discover(raw, SOURCE)
        self.assertEqual(outcome.status.value, 'invalid_output')
