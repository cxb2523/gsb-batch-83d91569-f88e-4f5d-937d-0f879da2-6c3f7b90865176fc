"""Synthetic source evidence for the extraction and repeated OCR regressions."""
import unittest

from discovery_fakes import make_raw_item
from gatherradar.domain import DiscoveryType
from gatherradar.extraction import DiscoveryService, RuleBasedDiscoveryProvider
from gatherradar.extraction.fields import source_schedule_text
from gatherradar.extraction.signals import analyze
from gatherradar.grouping import ConservativeGrouping, select_semantic_evidence
from test_grouping import fragment


class ExtractionDataQualityTests(unittest.TestCase):
    def discover(self, text, media=()):
        raw = make_raw_item(text)
        parts = tuple(fragment(raw, value, **kwargs) for value, kwargs in media)
        units = ConservativeGrouping().group(select_semantic_evidence(raw, parts))
        outcomes = DiscoveryService(RuleBasedDiscoveryProvider()).discover_units(raw, units)
        return units, tuple(o.event for o in outcomes if o.event)

    def test_caption_description_is_verbatim_not_an_ocr_concatenation(self):
        caption = "کارگاه سرامیک\nجمعه ساعت ۱۸\nبا هم ساختن را تجربه می‌کنیم."
        units, events = self.discover(caption, [("هزینه: ۱۰۰ تومان", {"slide": 0})])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].description_text, caption)
        self.assertEqual(events[0].evidence_fragment_ids, tuple(f.fragment_id for f in units[0].fragments))

    def test_caption_is_not_copied_to_independent_media_events(self):
        caption = "برای اطلاعات برنامه‌های این هفته به پوسترها نگاه کنید."
        _, events = self.discover(caption, [
            ("کارگاه سرامیک\n۲ مهر ساعت ۱۸", {"slide": 0}),
            ("کنسرت پاییز\n۳ مهر ساعت ۲۰", {"slide": 1}),
        ])
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e.description_text is None for e in events))

    def test_independently_scheduled_caption_headings_are_separate_candidates(self):
        units, events = self.discover("کارگاه سرامیک\n۲ مهر ساعت ۱۸\nکنسرت پاییز\n۳ مهر ساعت ۲۰")
        self.assertEqual({e.title for e in events}, {'کارگاه سرامیک', 'کنسرت پاییز'})
        self.assertEqual(len(units), 2)
        self.assertTrue(all(u.collapsed for u in units))  # original caption retained
        self.assertNotEqual(events[0].evidence_fragment_ids, events[1].evidence_fragment_ids)

    def test_unknown_title_remains_unknown_with_reason(self):
        _, events = self.discover("اینجا هر هفته رویداد داریم\nجمعه ساعت ۱۸")
        self.assertIsNone(events[0].title)
        self.assertIn("missing_source_title", events[0].extraction_diagnostics)

    def test_failed_heading_is_distinct_from_missing_source_title(self):
        _, events = self.discover("رویداد این هفته\nجمعه ساعت ۱۸")
        self.assertIsNone(events[0].title)
        self.assertIn("title_extraction_failed", events[0].extraction_diagnostics)

    def test_quoted_performance_title_requires_credit_context(self):
        _, events = self.discover("«از کنار هم بودن لذت ببریم»\n🎭 «قصه‌های شهر» کاری از گروه تئاتر نمونه\nهر شب ساعت ۲۱\nخرید بلیت\n#ایونت")
        self.assertEqual(events[0].title, "قصه‌های شهر")
        self.assertIn("هر شب ساعت ۲۱", events[0].source_schedule_text)

    def test_short_project_heading_has_occurrence_and_registration_support(self):
        _, events = self.discover("پروژه پنجم ارکستر نمونه ✨\nکنسرت\nزمان: ۲۴ مهر\nبرای ثبت نام اقدام کنید")
        self.assertEqual(events[0].title, "پروژه پنجم ارکستر نمونه")

    def test_performance_announcement_is_title_but_bare_organizer_is_not(self):
        _, events = self.discover("🎸 گروه آوا این‌بار در شیراز!😍\nرونمایی از قطعه‌های تازه\n۲۸ مهر ساعت ۲۱\nخرید بلیت")
        self.assertEqual(events[0].title, "گروه آوا این‌بار در شیراز")
        _, events = self.discover("گروه آوا\nرونمایی از قطعه‌های تازه\n۲۸ مهر ساعت ۲۱\nخرید بلیت")
        self.assertIsNone(events[0].title)

    def test_meaningful_title_digits_survive(self):
        _, events = self.discover("کارگاه سرامیک ۲\n۲ مهر ساعت ۱۸")
        self.assertEqual(events[0].title, "کارگاه سرامیک ۲")

    def test_day_number_after_title_remains_temporal_not_an_edition(self):
        _, events = self.discover("کارگاه سرامیک ۲ مهر ساعت ۱۸")
        self.assertEqual(events[0].title, "کارگاه سرامیک")
        self.assertEqual(events[0].source_date_text, "۲ مهر ساعت ۱۸")

    def test_natural_explicit_branch_does_not_require_invitation_in_same_clause(self):
        _, events = self.discover("رویداد قهوه‌سازی\n۹ و ۱۰ مهرماه می‌تونید توی شعبه‌ی باغستان کافه نمونه شما پشت بار باشید.\nحضور در این رویداد رایگان است.")
        self.assertEqual(events[0].venue_name, "شعبه‌ی باغستان کافه نمونه")
        self.assertIsNone(events[0].city)
        self.assertIsNone(events[0].address)

    def test_pin_names_physical_venue_separately_from_city_and_address(self):
        for line, expected in [
            ("📍 شیراز، سالن مهین‌بانو نمونه", "سالن مهین‌بانو نمونه"),
            ("📍 آکادمی نمونه، محدوده ولیعصر", "آکادمی نمونه"),
            ("📍 مجموعه تئاتر نمونه", "مجموعه تئاتر نمونه"),
        ]:
            with self.subTest(line=line):
                _, events = self.discover("کارگاه سرامیک\n۲ مهر ساعت ۱۸\n" + line)
                self.assertEqual(events[0].venue_name, expected)
                self.assertIsNone(events[0].address)

    def test_organizer_or_city_pin_never_becomes_venue(self):
        for text in ("برگزارکننده: آکادمی نمونه", "📍 تهران", "📍 جاباما ایونت"):
            with self.subTest(text=text):
                _, events = self.discover("کارگاه سرامیک\n۲ مهر ساعت ۱۸\n" + text)
                self.assertIsNone(events[0].venue_name)

    def test_approximate_pin_area_does_not_become_address_or_city(self):
        _, events = self.discover("کارگاه سرامیک\n۲ مهر ساعت ۱۸\n📍 آکادمی نمونه، محدوده ولیعصر")
        self.assertEqual(events[0].area_text, "ولیعصر")
        self.assertIsNone(events[0].city)
        self.assertIsNone(events[0].address)

    def test_corner_location_remains_address_separate_from_venue(self):
        _, events = self.discover("رویداد پاییزی\nاین رویداد توی عمارت نمونه برگزار میشه.\nزمان: ۲ مهر ساعت ۱۸\nمکان: نوفل‌لوشاتو، نبش خارک، عمارت نمونه")
        self.assertEqual(events[0].venue_name, "عمارت نمونه")
        self.assertEqual(events[0].address, "نوفل‌لوشاتو، نبش خارک، عمارت نمونه")

    def test_discrete_dates_and_malformed_sentence_punctuation_survive_schedule(self):
        self.assertEqual(source_schedule_text(analyze("۹ و ۱۰ مهرماه")), "۹ و ۱۰ مهرماه")
        wording = "چهار جلسه، چهارشنبه‌ها ۲۹ مهر و ۶، ۱۳ و. ۲۰ آبان ساعت ۱۹:۳۰"
        self.assertEqual(source_schedule_text(analyze(wording)), wording)
        self.assertEqual(source_schedule_text(analyze("در دو سانس ۱۷ و ۲۰")), "در دو سانس ۱۷ و ۲۰")


class RepeatedOcrQualityTests(unittest.TestCase):
    discover = ExtractionDataQualityTests.discover
    def test_split_unlabelled_clock_does_not_duplicate_known_anchor(self):
        caption = "رویداد باریستا تویی\n۹ و ۱۰ مهرماه\nدر شعبه‌ی باغستان کافه نمونه حضور داشته باشید."
        noisy = "۰ ۱\n‎i}\n۳\n‎am‏ :\na ۰ ۱\nرویداد باریستا تویی\n| ۰ باغستان، کافه نمونه"
        units, events = self.discover(caption, [(noisy, {"frame": 0})])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "رویداد باریستا تویی")
        self.assertEqual(events[0].source_date_text, "۹ و ۱۰ مهرماه")
        self.assertEqual(len(units[0].collapsed), 1)
        self.assertNotIn(noisy, units[0].text)

    def test_repeated_inline_noisy_title_retains_conflict_diagnostic(self):
        _, events = self.discover("اطلاعات در پوستر", [
            ("خودت درستش کن >\nورکشاپ پیتزاء دوشنبه yao PY ساعت ۷", {"frame": 0}),
            ("خودت درستش کن؟/ ۰\nورکشاپ پیتزاء دوشنبه ingot ساعت ۰", {"frame": 1000}),
        ])
        self.assertEqual(len(events), 1)
        self.assertIn("repeated_anchor_with_unreliable_temporal_ocr", events[0].extraction_diagnostics)
        self.assertEqual(events[0].source_date_text, "دوشنبه")

    def test_clean_distinct_times_remain_separate_occurrences(self):
        _, events = self.discover("اطلاعات در پوستر", [
            ("خودت درستش کن\nورکشاپ پیتزا دوشنبه ساعت ۱۷", {"frame": 0}),
            ("خودت درستش کن\nورکشاپ پیتزا دوشنبه ساعت ۱۹", {"frame": 1000}),
        ])
        self.assertEqual(len(events), 2)

    def test_same_title_without_shared_secondary_anchor_is_not_collapsed(self):
        _, events = self.discover("اطلاعات در پوستر", [
            ("ورکشاپ پیتزا دوشنبه yao ساعت ۷", {"frame": 0}),
            ("ورکشاپ پیتزا دوشنبه ingot ساعت ۰", {"frame": 1000}),
        ])
        self.assertEqual(len(events), 2)

    def test_caption_explicit_venue_is_not_a_second_ocr_event(self):
        caption = ("پروژه پنجم ارکستر نمونه\nاین بار توی کارگاه نوآوری هفت و هشت دور هم جمع می‌شیم.\n"
                   "زمان: ۲۴ مهر\nبلیت اجرا را تهیه کنید.")
        media = "پروژه پنجم\nکارگاه نوآوری هفت‌وهشت\nمهر\n۷/۱۳"
        units, events = self.discover(caption, [(media, {"frame": 0})])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "پروژه پنجم ارکستر نمونه")
        self.assertEqual(events[0].venue_name, "کارگاه نوآوری هفت و هشت")
        self.assertIn("source_venue_reclassified_from_ocr_title", events[0].extraction_diagnostics)
        self.assertEqual(units[0].collapsed[0].text, media)

    def test_same_named_media_with_own_concrete_date_is_not_suppressed_as_venue(self):
        caption = ("پروژه پنجم ارکستر نمونه\nاین بار توی کارگاه نوآوری هفت و هشت دور هم جمع می‌شیم.\n"
                   "زمان: ۲۴ مهر\nبلیت اجرا را تهیه کنید.")
        _, events = self.discover(caption, [
            ("کارگاه نوآوری هفت‌وهشت\n۲۵ مهر ساعت ۱۸", {"frame": 0}),
        ])
        self.assertEqual(len(events), 2)

    def test_independent_matching_date_and_subtitle_link_caption_without_fuzzy_title(self):
        caption = "تو این ورکشاپ آشپزی می‌کنیم.\n📅 دوشنبه ۲۷ مهر | ساعت ۱۷\n📍 آکادمی نمونه"
        _, events = self.discover(caption, [
            ("خودت درستش کن\nپیتزا. دوشنبه ۲۷ مهر", {"frame": 0}),
            ("خودت درستش کن >\nورکشاپ پیتزاء دوشنبه yao PY ساعت ۷", {"frame": 1000}),
            ("خودت درستش کن؟/ ۰\nورکشاپ پیتزاء دوشنبه ingot ساعت ۰", {"frame": 2000}),
        ])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "ورکشاپ پیتزاء")
        self.assertEqual(events[0].source_date_text, "دوشنبه ۲۷ مهر | ساعت ۱۷")
        self.assertEqual(events[0].description_text, caption)
        self.assertEqual(events[0].venue_name, "آکادمی نمونه")
        self.assertIn("repeated_anchor_with_unreliable_temporal_ocr", events[0].extraction_diagnostics)

    def test_date_bridge_requires_exact_calendar_and_single_event(self):
        caption = "تو این ورکشاپ آشپزی می‌کنیم.\n📅 دوشنبه ۲۷ مهر | ساعت ۱۷\n📍 آکادمی نمونه"
        base = [
            ("خودت درستش کن >\nورکشاپ پیتزاء دوشنبه yao PY ساعت ۷", {"frame": 1000}),
            ("خودت درستش کن؟/ ۰\nورکشاپ پیتزاء دوشنبه ingot ساعت ۰", {"frame": 2000}),
        ]
        for bridge, extra, expected in [
            ("خودت درستش کن\nپیتزا. دوشنبه ۲۸ مهر", [], 2),
            ("خودت درستش کن\nپیتزا. دوشنبه ۲۷ مهر ساعت ۱۹", [], 2),
            ("خودت درستش کن\nپیتزا. دوشنبه ۲۷ مهر",
             [("کنسرت پاییز\n۲۸ مهر ساعت ۲۰", {"frame": 3000})], 3),
        ]:
            with self.subTest(bridge=bridge, extra=extra):
                _, events = self.discover(caption, [(bridge, {"frame": 0}), *base, *extra])
                self.assertEqual(len(events), expected)


if __name__ == "__main__":
    unittest.main()
