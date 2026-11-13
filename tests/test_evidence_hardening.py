'''Instagram evidence hardening: Persian date grammar, natural venues, repeated anchors.

Synthetic or sanitized wording only. The Reel fixture models the shape of a reviewed
public failure (a caption Event plus noisy OCR frames repeating its title); it holds
no runtime capture, OCR output or account data.
'''
import json
import unittest
from dataclasses import replace
from datetime import date, time
from pathlib import Path

from persiantools.jdatetime import JalaliDate

from discovery_fakes import make_raw_item, make_source
from test_grouping import fragment
from test_normalization_temporal import temporal
from gatherradar.cli import format_evidence_discovery_summary
from gatherradar.deduplication import CandidateContext, canonicalize
from gatherradar.domain import DiscoveryType, DiscoveryUnit, EvidenceKind, caption_fragment
from gatherradar.domain.temporal import DatePrecision
from gatherradar.extraction import DiscoveryService, ExtractionInput, RuleBasedDiscoveryProvider
from gatherradar.extraction import fields
from gatherradar.extraction.signals import analyze
from gatherradar.extraction.text import title_equivalence_key
from gatherradar.grouping import ConservativeGrouping, select_semantic_evidence
from gatherradar.grouping.conservative import (
    NOTE_INSUFFICIENT_OCR, NOTE_REPEATED_ANCHOR, NOTE_SUPPORT_ATTACHED,
)
from gatherradar.orchestration.canonicalization_run import identity_slot
from gatherradar.orchestration.evidence_discovery_run import run_evidence_discovery
from gatherradar.orchestration.normalization_run import run_normalization

FIXTURE = Path(__file__).parent / 'fixtures' / 'evidence_grouping' / 'persian_reel_repeated_anchor.json'
MONTHS = {'فروردین': 1, 'تیر': 4, 'مهر': 7, 'دی': 10, 'اسفند': 12}
SUFFIXES = ('', 'ماه', ' ماه', '‌ماه')
DIGITS = (('۹', '۱۰', '۸'), ('9', '10', '8'))


def discover(text: str):
    return RuleBasedDiscoveryProvider().discover(ExtractionInput(
        raw_item_id='instagram:example:ABC', source_id='example_instagram', source_type='instagram',
        raw_text=text, content_url='https://www.instagram.com/p/ABC/', content_type='image',
    ))


def event_facts(line: str):
    facts = discover('کارگاه سفالگری\n' + line + '\nثبت نام کنید')
    assert facts.discovery_type is DiscoveryType.EVENT, line
    return facts


def codes(result):
    return {diagnostic.code for diagnostic in result.diagnostics}


class PersianDateSignalTests(unittest.TestCase):
    def test_same_month_day_list_keeps_both_days_and_suffix_for_all_months(self):
        for month in MONTHS:
            for suffix in SUFFIXES:
                for first, second, _ in DIGITS:
                    wording = f'{first} و {second} {month}{suffix}'
                    with self.subTest(wording=wording):
                        self.assertEqual(event_facts(wording).source_date_text, wording)
                        # Discrete listed days are never one continuous range.
                        self.assertEqual(temporal(wording + ' ۱۴۰۵').start_date, None)
                        self.assertIn('multiple_dates', codes(temporal(wording + ' ۱۴۰۵')))

    def test_same_month_day_range_is_extracted_and_normalized_for_all_months(self):
        for month, number in MONTHS.items():
            for suffix in SUFFIXES:
                for _, end, start in DIGITS:
                    wording = f'{start} تا {end} {month}{suffix} ۱۴۰۵'
                    with self.subTest(wording=wording):
                        extracted = event_facts(wording).source_date_text
                        self.assertEqual(extracted, wording)
                        result = temporal(extracted)
                        self.assertEqual((result.start_date, result.end_date),
                                         (JalaliDate(1405, number, 8).to_gregorian(),
                                          JalaliDate(1405, number, 10).to_gregorian()))
                        self.assertEqual(result.date_precision, DatePrecision.RANGE)
                        self.assertNotIn('inferred_year', codes(result))

    def test_attached_month_suffix_is_one_date_signal(self):
        for month in MONTHS:
            found = analyze(f'۹ {month}ماه')
            self.assertEqual([signal.text for signal in found.dates], [f'{month}ماه'])
        # "دی" alone is ordinary vocabulary; its suffixed month form is not.
        self.assertEqual(analyze('دی جی').dates, ())
        self.assertEqual([s.text for s in analyze('۱۰ دی ماه').dates], ['دی ماه'])

    def test_comma_day_lists_are_schedule_wording_not_a_range(self):
        for wording in ('۵، ۱۲، ۱۹ و ۲۶ مهر', '5, 12, 19 و 26 مهرماه', '۵،۱۲،۱۹ و ۲۶ تیر ماه'):
            with self.subTest(wording=wording):
                facts = event_facts(wording)
                self.assertEqual(facts.source_date_text, wording)
                self.assertEqual(facts.source_schedule_text, wording)
                result = temporal(facts.source_date_text)
                self.assertIsNone(result.start_date)
                self.assertIsNone(result.end_date)

    def test_weekday_with_date_keeps_the_relationship(self):
        facts = event_facts('پنجشنبه ۱۶ مهر ۱۴۰۵')
        self.assertEqual(facts.source_date_text, 'پنجشنبه ۱۶ مهر ۱۴۰۵')
        self.assertEqual(temporal(facts.source_date_text).start_date, date(2026, 10, 8))
        pair = event_facts('پنجشنبه و جمعه، ۱۶ و ۱۷ مهر')
        self.assertEqual(pair.source_date_text, 'پنجشنبه و جمعه، ۱۶ و ۱۷ مهر')
        self.assertIsNone(temporal(pair.source_date_text).start_date)

    def test_weekday_prose_alone_is_not_a_calendar_date(self):
        for wording in ('شنبه', 'شنبه‌ها ساعت ۲۱', 'آخر هفته'):
            with self.subTest(wording=wording):
                extracted = event_facts(wording).source_date_text
                self.assertIsNotNone(extracted)
                self.assertIsNone(temporal(extracted).start_date)

    def test_detection_ordinals_match_the_normalizer_vocabulary(self):
        from gatherradar.extraction import rules
        from gatherradar.normalization.ordinals import DAY_ORDINALS
        self.assertEqual(set(rules.PERSIAN_DAY_ORDINALS), set(DAY_ORDINALS))

    def test_ordinal_naming_part_of_a_month_is_not_a_day(self):
        for wording in ('هفته اول مهر', 'نیمه دوم مهر', 'دهه سوم مهرماه'):
            with self.subTest(wording=wording):
                extracted = event_facts(wording).source_date_text
                self.assertNotIn(wording.split()[1], extracted)
                self.assertIsNone(temporal(extracted).start_date)
        self.assertEqual(event_facts('پنجشنبه اول مهر').source_date_text, 'پنجشنبه اول مهر')

    def test_ordinal_days_keep_their_full_wording(self):
        for wording in ('یکم تا سوم مهرماه', 'سی و یکم اردیبهشت', 'بیست و یکم دی ماه', 'اول تا سوم مهر'):
            with self.subTest(wording=wording):
                self.assertEqual(event_facts(wording).source_date_text, wording)
        result = temporal(event_facts('یکم تا سوم مهرماه').source_date_text)
        self.assertEqual((result.start_date, result.end_date), (date(2026, 9, 23), date(2026, 9, 25)))

    def test_date_and_clock_stay_separate_components(self):
        for wording, start, end, clock, exact in (
            ('۹ مهر ساعت ۱۸', date(2026, 10, 1), None, time(18), True),
            ('۹ مهر، ساعت ۱۸:۳۰', date(2026, 10, 1), None, time(18, 30), True),
            ('۸ تا ۱۰ مهرماه، ۱۶:۰۰ تا ۲۲:۰۰', date(2026, 9, 30), date(2026, 10, 2), time(16), False),
            ('یکم تا سوم مهرماه از ساعت ۱۰ تا ۲۲', date(2026, 9, 23), date(2026, 9, 25), time(10), False),
            ('۱ تا ۳ مهر، ساعت ۱۶ تا ۲۲', date(2026, 9, 23), date(2026, 9, 25), time(16), False),
            ('۱ تا ۳ مهر، ساعت ۱۶:۰۰ تا ۲۲:۰۰', date(2026, 9, 23), date(2026, 9, 25), time(16), False),
        ):
            with self.subTest(wording=wording):
                extracted = event_facts(wording).source_date_text
                self.assertEqual(extracted, wording)
                result = temporal(extracted)
                self.assertEqual((result.start_date, result.end_date, result.start_time), (start, end, clock))
                self.assertEqual(result.starts_at is not None, exact)
                if end is not None:
                    self.assertIn('multi_day_hours', codes(result))
                    self.assertIsNone(result.ends_at)

    def test_listed_days_with_hours_stay_unresolved(self):
        extracted = event_facts('۹ و ۱۰ مهر از ساعت ۱۰ تا ۲۲').source_date_text
        self.assertEqual(extracted, '۹ و ۱۰ مهر از ساعت ۱۰ تا ۲۲')
        self.assertIsNone(temporal(extracted).starts_at)

    def test_explicit_year_after_the_month_is_kept(self):
        extracted = event_facts('جمعه ۱۷ مهر ۱۴۰۵').source_date_text
        self.assertEqual(extracted, 'جمعه ۱۷ مهر ۱۴۰۵')
        self.assertNotIn('inferred_year', codes(temporal(extracted)))

    def test_isolated_noisy_clock_does_not_outrank_a_calendar_date(self):
        facts = discover('رویداد باریستا تویی\n۹ و ۱۰ مهرماه\nبرای ثبت نام سر بزنید\n3 am')
        self.assertEqual(facts.source_date_text, '۹ و ۱۰ مهرماه')

    def test_relative_words_keep_existing_conservative_handling(self):
        self.assertEqual(event_facts('امروز').source_date_text, 'امروز')
        self.assertEqual(event_facts('فردا ساعت ۱۸').source_date_text, 'فردا ساعت ۱۸')
        self.assertIsNone(temporal(event_facts('این هفته').source_date_text).start_date)


class NaturalVenueTests(unittest.TestCase):
    def facts(self, line):
        return discover('کارگاه سفالگری جمعه ۱۷ مهر\n' + line)

    def test_branch_construction_keeps_the_exact_branch_wording(self):
        for line in ('توی شعبه‌ی لواسان کافه رئیس منتظرتونیم', 'شعبه‌ی لواسان کافه رئیس',
                     'توی شعبه‌ی لواسان کافه رئیس'):
            with self.subTest(line=line):
                facts = self.facts(line)
                self.assertEqual(facts.venue_name, 'شعبه‌ی لواسان کافه رئیس')
                # A branch locality is neither an area, a city nor an address.
                self.assertIsNone(facts.area_text)
                self.assertIsNone(facts.city)
                self.assertIsNone(facts.address)
        self.assertEqual(self.facts('کافه رئیس شعبه لواسان').venue_name, 'کافه رئیس شعبه لواسان')

    def test_ordinary_event_location_phrasing(self):
        for line, venue in (('در گالری نگاه برگزار می‌شود', 'گالری نگاه'),
                            ('رویداد در خانه هنرمندان برگزار می‌شود', 'خانه هنرمندان'),
                            ('در کافه رئیس منتظر شما هستیم', 'کافه رئیس'),
                            ('میزبان شما کافه رئیس است', 'کافه رئیس'),
                            ('برنامه در مجموعه فرهنگی نیاوران برگزار می‌شود', 'مجموعه فرهنگی نیاوران')):
            with self.subTest(line=line):
                facts = self.facts(line)
                self.assertEqual(facts.venue_name, venue)
                self.assertIsNone(facts.address)
                self.assertIsNone(facts.city)

    def test_labelled_venues_keep_precedence(self):
        self.assertEqual(self.facts('مکان: خانه هنرمندان').venue_name, 'خانه هنرمندان')
        self.assertEqual(self.facts('محل برگزاری: مرکز همایش‌های رایزن').venue_name, 'مرکز همایش‌های رایزن')
        self.assertEqual(self.facts('مکان: گالری آ\nدر کافه رئیس منتظرتونیم').venue_name, 'گالری آ')

    def test_non_venue_phrases_yield_no_location(self):
        for line in ('در این رویداد ثبت نام کنید', 'در صفحه ما ببینید', 'در اینستاگرام منتشر شد',
                     'در سایت اطلاعات بیشتر هست', 'در لینک بیو ثبت نام کنید', 'در توضیحات بخوانید',
                     'در گذشته هم برگزار شد', 'در خانه بمانید و آنلاین شرکت کنید',
                     'در مرکز شهر برگزار می‌شود', 'قبلا در کافه رئیس برگزار شد',
                     'در کافه رئیس خیلی خوش گذشت', 'کافه رئیس برگزار می‌کند', 'کافه رئیس'):
            with self.subTest(line=line):
                facts = self.facts(line)
                self.assertIsNone(facts.venue_name)
                self.assertIsNone(facts.area_text)
                self.assertIsNone(facts.address)

    def test_city_wording_is_a_city_not_a_venue(self):
        facts = self.facts('در تهران برگزار می‌شود')
        self.assertIsNone(facts.venue_name)
        self.assertEqual(facts.city, 'تهران')

    def test_alternative_venues_are_not_chosen_between(self):
        for line in ('در کافه نادری یا گالری نگاه منتظرتونیم', 'در کافه رئیس و گالری نگاه برگزار می‌شود',
                     'در کافه رئیس منتظرتونیم\nدر گالری نگاه منتظرتونیم'):
            with self.subTest(line=line):
                self.assertIsNone(self.facts(line).venue_name)


class TitleEquivalenceTests(unittest.TestCase):
    def test_spelling_noise_folds_but_words_and_numbers_stay(self):
        self.assertEqual(title_equivalence_key('☕️ رویداد باریستا تویی!'), title_equivalence_key('رویداد  باریستا تویی'))
        self.assertEqual(title_equivalence_key('کافه‌گالری نگاه'), title_equivalence_key('كافه گالری نگاه'))
        self.assertEqual(title_equivalence_key('کارگاه سفال ۱'), title_equivalence_key('کارگاه سفال 1'))
        self.assertNotEqual(title_equivalence_key('کارگاه سفال ۱'), title_equivalence_key('کارگاه سفال ۲'))
        self.assertNotEqual(title_equivalence_key('کارگاه سفال'), title_equivalence_key('کارگاه سفالگری'))


class RepeatedAnchorGroupingTests(unittest.TestCase):
    def group(self, caption='', slides=(), frames=()):
        item = make_raw_item(caption)
        parts = tuple(fragment(item, text, slide=i) for i, text in enumerate(slides))
        parts += tuple(fragment(item, text, frame=i * 1000) for i, text in enumerate(frames))
        return item, ConservativeGrouping().group(select_semantic_evidence(item, parts))

    def discover(self, caption='', slides=(), frames=()):
        item, units = self.group(caption, slides, frames)
        service = DiscoveryService(RuleBasedDiscoveryProvider())
        outcomes = service.discover_units(item, units)
        return units, [outcome.event for outcome in outcomes if outcome.event is not None]

    def test_caption_title_repeated_in_frame_is_one_event(self):
        units, events = self.discover('رویداد باریستا تویی\n۹ و ۱۰ مهرماه\nثبت نام کنید',
                                      frames=['رویداد باریستا تویی'])
        unit, = units
        self.assertEqual(unit.text, 'رویداد باریستا تویی\n۹ و ۱۰ مهرماه\nثبت نام کنید')
        self.assertEqual([part.kind for part in unit.collapsed], [EvidenceKind.REEL_FRAME_OCR])
        self.assertEqual([note for _, note in unit.notes], [NOTE_REPEATED_ANCHOR])
        self.assertEqual(len(events), 1)

    def test_repeated_title_with_noisy_clock_is_provenance_not_an_event(self):
        units, events = self.discover('رویداد باریستا تویی\n۹ و ۱۰ مهرماه\nثبت نام کنید',
                                      frames=['رویداد باریستا تویی\n3 am'])
        self.assertEqual(len(units), 1)
        self.assertEqual([note for _, note in units[0].notes], [NOTE_INSUFFICIENT_OCR])
        self.assertNotIn('3 am', units[0].text)
        event, = events
        self.assertEqual(event.source_date_text, '۹ و ۱۰ مهرماه')

    def test_repeated_title_with_compatible_clock_enriches_the_caption_event(self):
        units, events = self.discover('رویداد باریستا تویی\n۹ مهر\nثبت نام کنید',
                                      frames=['رویداد باریستا تویی\nساعت ۱۸'])
        unit, = units
        self.assertEqual([note for _, note in unit.notes], [NOTE_SUPPORT_ATTACHED])
        self.assertIn('ساعت ۱۸', unit.text)
        self.assertEqual(len(events), 1)

    def test_caption_anchor_plus_repeated_slide_and_support_is_one_enriched_event(self):
        units, events = self.discover('کارگاه سفالگری\nثبت نام کنید',
                                      slides=['کارگاه سفالگری', 'جمعه ۱۷ مهر ساعت ۱۸', 'آدرس: تهران، خیابان نمونه'])
        unit, = units
        self.assertEqual([part.slide_index for part in unit.fragments[1:]], [1, 2])
        self.assertEqual([part.slide_index for part in unit.collapsed], [0])
        event, = events
        self.assertEqual(event.source_date_text, 'جمعه ۱۷ مهر ساعت ۱۸')
        self.assertEqual(event.address, 'تهران، خیابان نمونه')

    def test_conflicting_repeated_occurrence_is_not_silently_combined(self):
        for caption, slides in (
            ('کارگاه سفالگری\n۹ مهر', ['کارگاه سفالگری\n۱۰ مهر']),
            ('کارگاه سفالگری\n۹ مهر', ['کارگاه سفالگری', '۱۰ مهر']),
            ('کارگاه سفالگری\n۹ مهر\nآدرس: تهران', ['کارگاه سفالگری\nآدرس: شیراز']),
            ('کارگاه سفالگری\n۹ مهر\nقیمت: ۱۰۰ تومان', ['کارگاه سفالگری\nقیمت: ۲۰۰ تومان']),
            ('کارگاه سفالگری\n۹ مهر\nمکان: گالری آ', ['کارگاه سفالگری\nمکان: گالری ب']),
            ('کارگاه سفالگری\n۹ مهر ساعت ۱۸', ['کارگاه سفالگری\nساعت ۲۰']),
        ):
            with self.subTest(slides=slides):
                units, events = self.discover(caption, slides=slides)
                self.assertEqual(len(units), 2)
                self.assertEqual(units[0].text, caption)
                self.assertEqual(units[0].collapsed, ())
                # The caption Event keeps exactly its own facts; the slide is judged alone.
                alone = discover(caption)
                for name in ('source_date_text', 'address', 'price_text', 'venue_name'):
                    self.assertEqual(getattr(events[0], name), getattr(alone, name))

    def test_same_post_is_not_proof_of_one_occurrence(self):
        units, events = self.discover('کارگاه سفالگری\nجمعه ۱۷ مهر', slides=['کنسرت باران\nشنبه ۱۸ مهر'])
        self.assertEqual(len(units), 2)
        self.assertEqual({event.title for event in events}, {'کارگاه سفالگری', 'کنسرت باران'})

    def test_carousel_scenarios(self):
        for name, slides, expected in (
            ('title-date-venue', ['کارگاه سفالگری', 'جمعه ۱۷ مهر ساعت ۱۸', 'آدرس: تهران، خیابان نمونه'], [[0, 1, 2]]),
            ('two events', ['کارگاه سفالگری\nجمعه ۱۷ مهر', 'کنسرت باران\nشنبه ۱۸ مهر'], [[0], [1]]),
            ('support then new event', ['کارگاه سفالگری', 'جمعه ۱۷ مهر ساعت ۱۸', 'کنسرت باران\nشنبه ساعت ۲۰'], [[0, 1], [2]]),
            ('generic cover', ['پیشنهادهای این هفته', 'کارگاه سفالگری', 'جمعه ۱۷ مهر ساعت ۱۸', 'آدرس: تهران'], [[0], [1, 2, 3]]),
        ):
            with self.subTest(name=name):
                _, units = self.group(slides=slides)
                self.assertEqual([[part.slide_index for part in unit.fragments] for unit in units], expected)

    def test_reel_with_one_event_repeated_across_frames_is_one_event(self):
        units, events = self.discover(frames=[
            'رویداد باریستا تویی\n۹ و ۱۰ مهرماه', 'رویداد باریستا تویی', 'رویداد باریستا تویی\n3 am',
            'A eee', 'رویداد باریستا تویی', 'رویداد باریستا تویی\n1 /'])
        event, = events
        self.assertEqual(event.source_date_text, '۹ و ۱۰ مهرماه')
        self.assertEqual(len(units[0].collapsed), 4)

    def test_reel_with_two_distinct_events_keeps_both(self):
        units, events = self.discover(frames=['کارگاه سفالگری\nجمعه ۱۷ مهر', 'کارگاه سفالگری',
                                              'کنسرت باران\nشنبه ۱۸ مهر', 'کنسرت باران', 'کارگاه سفالگری'])
        self.assertEqual([event.title for event in events], ['کارگاه سفالگری', 'کنسرت باران'])
        self.assertEqual([len(unit.collapsed) for unit in units], [2, 1])

    def test_numbered_titles_are_different_anchors(self):
        _, units = self.group(slides=['کارگاه سفال ۱', 'کارگاه سفال ۲'], caption='کارگاه سفال ۱\nجمعه ۱۷ مهر')
        self.assertEqual(len(units), 2)
        self.assertEqual([part.slide_index for part in units[0].collapsed], [0])
        self.assertEqual([part.slide_index for part in units[1].fragments], [1])

    def test_media_only_events_are_preserved(self):
        units, events = self.discover(slides=['کارگاه سفالگری', 'جمعه ۱۷ مهر ساعت ۱۸'])
        self.assertEqual(len(events), 1)
        units, events = self.discover('Our weekly picks', frames=['رویداد باریستا تویی\n۹ مهر'])
        self.assertEqual(len(events), 1)

    def test_ocr_noise_alone_creates_no_event(self):
        _, events = self.discover(frames=['A eee', '1 /', 'ﮐﺎ ﻓ ﺭ', '3 am', '9/25'])
        self.assertEqual(events, [])

    def test_isolated_clock_frame_beside_an_anchor_is_provenance_only(self):
        units, events = self.discover(frames=['concert Friday at 7 PM', '7 PM'])
        unit, = units
        self.assertEqual([note for _, note in unit.notes], [NOTE_INSUFFICIENT_OCR])
        self.assertEqual(unit.text, 'concert Friday at 7 PM')
        self.assertEqual(len(events), 1)

    def test_english_events_are_not_blacklisted(self):
        _, events = self.discover(frames=['Jazz concert Friday at 8 pm'])
        event, = events
        self.assertEqual(event.source_date_text, 'Friday at 8 pm')

    def test_partial_title_repetition_needs_two_exact_words(self):
        _, units = self.group('رویداد باریستا تویی\n۹ مهر\nثبت نام کنید', frames=['باریستا تویی', 'تویی'])
        self.assertEqual([len(unit.collapsed) for unit in units], [1, 0])

    def test_collapsed_fragments_change_identity_but_not_text(self):
        item = make_raw_item('رویداد باریستا تویی\n۹ مهر')
        caption = caption_fragment(item)
        frame = fragment(item, 'رویداد باریستا تویی', frame=0)
        plain = DiscoveryUnit.from_fragments((caption,), strategy='conservative/2')
        with_repeat = DiscoveryUnit.from_fragments((caption,), strategy='conservative/2', collapsed=(frame,))
        self.assertEqual(plain.text, with_repeat.text)
        self.assertNotEqual(plain.unit_id, with_repeat.unit_id)
        self.assertEqual(identity_slot(with_repeat), 'primary')
        with self.assertRaises(ValueError):
            DiscoveryUnit.from_fragments((caption,), strategy='conservative/2', collapsed=(caption,))

    def test_grouping_is_deterministic(self):
        args = dict(caption='رویداد باریستا تویی\n۹ مهر', frames=['رویداد باریستا تویی\n3 am', 'A eee', 'رویداد باریستا تویی'])
        self.assertEqual(self.group(**args)[1], self.group(**args)[1])


class ObservedReelRegressionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.item = make_raw_item(self.fixture['caption'], shortcode='SYNTHETIC_REEL')
        self.source = make_source(timezone='Asia/Tehran')
        self.history = tuple(fragment(self.item, frame['text'], frame=frame['frame_timestamp_ms'])
                             for frame in self.fixture['frames'])
        self.summary = run_evidence_discovery(
            (self.item,), self.history, DiscoveryService(RuleBasedDiscoveryProvider()),
            sources={self.source.id: self.source})

    def test_one_event_with_source_date_and_location(self):
        expected = self.fixture['expected']
        self.assertEqual(self.summary.events, expected['events'])
        event, = self.summary.candidates
        self.assertEqual(event.title, expected['title'])
        self.assertEqual(event.source_date_text, expected['source_date_text'])
        self.assertEqual(event.venue_name, expected['venue_name'])
        self.assertIsNone(event.area_text)
        self.assertIsNone(event.city)
        self.assertIsNone(event.address)
        self.assertEqual(self.summary.items[0].ignored_fragments, 0)

    def test_every_frame_keeps_provenance(self):
        units = self.summary.items[0].units
        kept = {part.fragment_id for unit in units for part in unit.fragments + unit.collapsed}
        self.assertEqual(kept, {part.fragment_id for part in self.history} | {caption_fragment(self.item).fragment_id})

    def test_normalization_keeps_listed_days_unresolved(self):
        outcome, = run_normalization(self.summary.outcomes, {self.item.id: self.item}, {self.source.id: self.source},
                                     unit_texts={u.unit_id: u.text for i in self.summary.items for u in i.units})
        self.assertEqual(outcome.candidate.source_date_text, '۹ و ۱۰ مهرماه')
        self.assertIsNone(outcome.candidate.start_date)
        self.assertIn('multiple_dates', codes(outcome))

    def test_no_duplicate_reaches_canonicalization(self):
        units = {unit.unit_id: unit for item in self.summary.items for unit in item.units}
        normalized = run_normalization(self.summary.outcomes, {self.item.id: self.item}, {self.source.id: self.source},
                                       unit_texts={key: unit.text for key, unit in units.items()})
        discoveries = [o for o in self.summary.outcomes if o.candidate is not None]
        contexts = [CandidateContext(result, found.candidate, self.item, self.source, self.item.captured_at,
                                     identity_slot(units.get(found.discovery_unit_id)))
                    for result, found in zip(normalized, discoveries)]
        result = canonicalize(contexts)
        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.possible_duplicates, ())

    def test_cli_explains_collapsed_frames(self):
        text = format_evidence_discovery_summary(self.summary)
        self.assertIn('Grouping: conservative/2', text)
        self.assertIn(f'Collapsed frame 0ms: {NOTE_INSUFFICIENT_OCR}', text)
        self.assertIn(f'Collapsed frame 6000ms: {NOTE_REPEATED_ANCHOR}', text)

    def test_caption_only_discovery_also_recovers_date_and_venue(self):
        outcome = DiscoveryService(RuleBasedDiscoveryProvider()).discover(self.item, self.source)
        self.assertEqual(outcome.event.source_date_text, '۹ و ۱۰ مهرماه')
        self.assertEqual(outcome.event.venue_name, 'شعبه‌ی لواسان کافه رئیس')

    def test_previous_strategy_identity_is_not_reused(self):
        unit = self.summary.items[0].units[0]
        old = DiscoveryUnit.from_fragments(unit.fragments, strategy='conservative/1')
        self.assertNotEqual(unit.unit_id, old.unit_id)
        self.assertEqual(replace(unit, unit_id=old.unit_id, collapsed=(), notes=()), old)


if __name__ == '__main__':
    unittest.main()
