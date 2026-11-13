"""Source-to-field gaps in the latest owner workbook (GR-EXCEL-CLOSURE-20261029).

Run ca3548cb65534d868277f140cdc92855 re-exported at 2026-10-29T13:59:38Z. Positive
inputs are the public captions' and detail pages' own wording (case IDs F01, F02,
F04, F07 in docs/FINAL_EXCEL_CASE_RESULTS.json); every rule has negative cases.
"""
from __future__ import annotations

import unittest

from gatherradar.extraction.fields import city, duration_minutes, narrative_durations, venue_name
from gatherradar.extraction.signals import analyze
from gatherradar.review.readiness import assess_readiness
from test_live_run_fields import CHIZMIZ, SEQUENCE
from test_schedule_conflicts import collect_event

ZIRKHAKI = ('ایونت زیرخاکی🧡\n\nاز ۶ تا ۸ آبان، توی عمارت زیرخاکی منتظر یه تجربه‌ی متفاوت و پر از اتفاق‌های جذاب باشید! ✨\n'
            'از اجرای موسیقی زنده و تماشای فیلم با حضور کارگردان‌ها لذت ببرید.\n\n'
            '📍آدرس: نیاوران، جمال‌آباد، میدان خیبر، بن‌بست پروانه، پلاک ۱۳، درب مشکی')
VIRA = ('رویداد فصل پنجم ویرا🧡\n\nاز ۶ تا ۸ آبان، توی فصل پنجم ایونت ویرا در تیدا سنتر، قراره با یک تم متفاوت و مرموز '
        'روبه‌رو بشید! ✨\nبین لاین‌های مختلف بچرخید و خرید کنید.\n\n'
        '📍آدرس: هروی، تهران، بزرگراه شهید صیاد شیرازی، موسوی، بین افشاری و مکران، مجتمع تجاری تیدا سنتر، طبقه دوم')
POTTERY_DESCRIPTION = ('🎯 هدف تجربه:\nیه فرصت ناب برای اینکه دستتو به گل بزنی و با چرخ سفال آشنا بشی.\n'
                       '📋 توی این تجربه قراره چه اتفاقی بیفته:\nآشنایی با اصول پایه‌ی سفالگری با چرخ\n'
                       'تجربه‌ای سه‌ساعته برای لمس آرامش و خلاقیت\n'
                       '(نکته: به خاطر زمان لازم برای پخت، رنگ‌آمیزی و لعاب در این جلسه انجام نمی‌شه)')


class PresenceVenueTests(unittest.TestCase):
    """F01: "توی عمارت زیرخاکی منتظر …" in the clause that states the dates."""

    def test_dated_clause_with_presence_verb_names_the_venue(self):
        self.assertEqual(venue_name(analyze(ZIRKHAKI)), 'عمارت زیرخاکی')

    def test_undated_generic_or_unnamed_mentions_are_not_venues(self):
        for text in (ZIRKHAKI.replace('از ۶ تا ۸ آبان، ', ''),                       # no dates in the clause
                     ZIRKHAKI.replace('عمارت زیرخاکی منتظر', 'عمارت منتظر'),           # head without a name
                     'از ۶ تا ۸ آبان، در خانه منتظر خبرهای ما باشید!',                  # generic phrase
                     'از ۶ تا ۸ آبان در مرکز شهر منتظر شما هستیم'):                     # city-centre wording
            with self.subTest(text=text[:50]):
                self.assertIsNone(venue_name(analyze(text)))

    def test_recovered_venues_are_preserved_and_not_borrowed(self):
        self.assertEqual(venue_name(analyze(SEQUENCE)), 'عمارت زیرخاکی')       # F03 Sekans
        self.assertEqual(venue_name(analyze(CHIZMIZ)), 'کافه‌کتاب مدیا')         # F03 Chizmiz
        # Zirkhaki's own address is kept; nothing is copied from Sekans' differing one.
        self.assertNotIn('بن‌بست ترانه', ZIRKHAKI)


class AddressBuildingVenueTests(unittest.TestCase):
    """F02: "در تیدا سنتر" and an address component "مجتمع تجاری تیدا سنتر"."""

    def test_prose_name_of_an_address_building_is_the_venue(self):
        self.assertEqual(venue_name(analyze(VIRA)), 'تیدا سنتر')
        self.assertEqual(city(analyze(VIRA)), 'تهران')  # stated in the address itself

    def test_sponsor_office_past_or_unaddressed_names_are_not_venues(self):
        for text in (VIRA.replace('مجتمع تجاری تیدا سنتر', 'مجتمع تجاری آریا'),       # address names another building
                     VIRA.replace('توی فصل پنجم ایونت ویرا در تیدا سنتر،', 'با حمایت دفتر ویرا در تیدا سنتر،'),
                     VIRA.replace('از ۶ تا ۸ آبان، توی فصل پنجم ایونت ویرا', 'دفعه قبلی ایونت ویرا'),
                     VIRA.replace('📍آدرس: هروی، تهران، بزرگراه شهید صیاد شیرازی، موسوی، بین افشاری و مکران، '
                                  'مجتمع تجاری تیدا سنتر، طبقه دوم', ''),                   # no address at all
                     VIRA.replace('در تیدا سنتر، قراره', 'در تیدا سنتر بزرگ قراره')):       # name runs on
            with self.subTest(text=text[:60]):
                self.assertIsNone(venue_name(analyze(text)))

    def test_city_tokens_in_the_address_are_never_venues(self):
        text = 'رویداد پاییزی\nاز ۶ تا ۸ آبان در تهران، منتظرتونیم\n📍آدرس: خیابان الف، پلاک ۲، مجتمع تهران'
        self.assertIsNone(venue_name(analyze(text)))


class HashtagCityTests(unittest.TestCase):
    """F07: a promotional hashtag is not an explicitly stated event city."""

    def test_hashtag_or_handle_alone_is_not_a_city(self):
        self.assertIsNone(city(analyze(SEQUENCE + '\n#ایونت_تهران #tehranevents')))
        self.assertIsNone(city(analyze('رویداد الف ۶ آبان\n@tehran_events_page')))

    def test_written_city_still_counts(self):
        self.assertEqual(city(analyze('رویداد الف در تهران برگزار می‌شود #ایونت_تهران')), 'تهران')


class NarrativeDurationTests(unittest.TestCase):
    """F04: header "۲ ساعت" against "تجربه‌ای سه‌ساعته" in the description."""

    def test_length_adjectives_are_read_as_written(self):
        self.assertEqual(narrative_durations(analyze('تجربه‌ای سه‌ساعته برای لمس آرامش')), ('سه‌ساعته',))
        self.assertEqual(narrative_durations(analyze('یک کارگاه ۹۰ دقیقه‌ای')), ('۹۰ دقیقه‌ای',))
        self.assertEqual((duration_minutes('سه‌ساعته'), duration_minutes('۹۰ دقیقه‌ای')), (180, 90))
        for text in ('سه ساعت قبل از شروع ثبت‌نام بسته می‌شود', 'یک تجربه‌ی ناب', 'ساعته'):
            with self.subTest(text=text):
                self.assertEqual(narrative_durations(analyze(text)), ())

    def test_conflicting_lengths_are_both_kept_and_neither_chosen(self):
        for slot in ('۸ آبان ساعت ۱۰:۰۰', '۸ آبان ساعت ۱۳:۰۰'):
            with self.subTest(slot=slot):
                event = collect_event(self, 'سفالگری با چرخ', slot, 'محله‌ی توحید', '۲ ساعت', POTTERY_DESCRIPTION)
                self.assertIsNone(event.duration_text)
                self.assertIn(('source_field_conflict', 'duration_text'), {(d.code, d.field) for d in event.diagnostics})
                self.assertEqual(event.conflicting_values, (('duration_text', '۲ ساعت'), ('duration_text', 'سه‌ساعته')))
                readiness = assess_readiness(event)
                self.assertIn('duration_conflict', readiness.reasons)
                self.assertIn('مدت در منبع: «۲ ساعت» / «سه‌ساعته»', readiness.explanation)
                # The verified date and clock stay; no end time is derived from either length.
                occurrence, = event.occurrences
                self.assertEqual(occurrence.start_time.strftime('%H:%M'), slot[-5:].translate(
                    str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')))
                self.assertIsNone(occurrence.end_time)

    def test_agreeing_lengths_are_not_a_conflict(self):
        description = POTTERY_DESCRIPTION.replace('سه‌ساعته', 'دوساعته')
        event = collect_event(self, 'سفالگری با چرخ', '۸ آبان ساعت ۱۰:۰۰', 'محله‌ی توحید', '۲ ساعت', description)
        self.assertEqual(event.duration_text, '۲ ساعت')
        self.assertEqual(event.conflicting_values, ())


if __name__ == '__main__':
    unittest.main()
