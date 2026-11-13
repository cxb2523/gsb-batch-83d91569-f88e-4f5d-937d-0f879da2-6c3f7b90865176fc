"""Field extraction tests: what the engine reads out of a classified observation.

Every expected value is a slice of the caption above it. Nothing here should ever
assert a normalized date, a parsed price, or an inferred city — those belong to the
later normalization step.
"""

import unittest

from gatherradar.domain import DiscoveryType
from gatherradar.extraction import ExtractionInput, RuleBasedDiscoveryProvider
from gatherradar.extraction.signals import analyze


def discover(text: str):
    return RuleBasedDiscoveryProvider().discover(
        ExtractionInput(
            raw_item_id="instagram:example:ABC",
            source_id="example_instagram",
            source_type="instagram",
            raw_text=text,
            content_url="https://www.instagram.com/p/ABC/",
            content_type="image",
        )
    )


class DateTextTests(unittest.TestCase):
    def test_the_source_date_wording_is_kept_unconverted(self) -> None:
        facts = discover("کارگاه سفالگری\nجمعه ۲۱ شهریور از ساعت ۱۶ تا ۲۲\nآدرس: تهران")

        self.assertEqual(facts.source_date_text, "جمعه ۲۱ شهریور از ساعت ۱۶ تا ۲۲")

    def test_a_day_range_before_the_month_is_kept(self) -> None:
        facts = discover("نمایشگاه عکس\n۱۹ و ۲۰ شهریور از ساعت ۱۶ تا ۲۲\nآدرس: تهران")

        self.assertEqual(facts.source_date_text, "۱۹ و ۲۰ شهریور از ساعت ۱۶ تا ۲۲")

    def test_a_labelled_date_wins(self) -> None:
        facts = discover("کنسرت موسیقی\nزمان: پنجشنبه ۲۸ شهریور ساعت ۲۱\nآدرس: تهران")

        self.assertEqual(facts.source_date_text, "پنجشنبه ۲۸ شهریور ساعت ۲۱")

    def test_a_relative_date_is_kept_as_written(self) -> None:
        facts = discover("دورهمی عکاسان آخر هفته\nآدرس: تهران، خیابان کریمخان")

        self.assertEqual(facts.source_date_text, "آخر هفته")

    def test_relative_date_text_does_not_expand_to_conversational_prose(self) -> None:
        cases = {
            "نشست هفتگی\nاین هفته کلی اتفاق جذاب داریم\nآدرس: تهران": "این هفته",
            "دورهمی دوستان\nآخر هفته‌ها چیکار کنیم؟ در امروز\nآدرس: تهران": "آخر هفته",
        }
        for text, expected in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(discover(text).source_date_text, expected)

    def test_adjacent_persian_date_and_time_lines_are_kept_together(self) -> None:
        facts = discover("کارگاه سفالگری\n۲ مهر\nساعت ۲۰:۳۰\nآدرس: تهران")

        self.assertEqual(facts.source_date_text, "۲ مهر\nساعت ۲۰:۳۰")

    def test_adjacent_calendar_and_clock_label_lines_are_kept_together(self) -> None:
        facts = discover("نشست هنری\n🗓 ۱ و ۲ مهر ماه\n⏰ ساعت ۲۰:۳۰\n📍 تهران، خیابان نمونه")

        self.assertEqual(facts.source_date_text, "۱ و ۲ مهر ماه\nساعت ۲۰:۳۰")

    def test_adjacent_visual_date_is_kept_when_clock_line_also_names_weekdays(self) -> None:
        facts = discover("نمایشگاه عکس\n🗓 تا ۷ مهر\n🕰 جمعه‌ها ۱۶ تا ۲۰\n📍 تهران، خیابان نمونه")

        self.assertEqual(facts.source_date_text, "تا ۷ مهر\nجمعه‌ها ۱۶ تا ۲۰")

    def test_no_date_wording_means_none(self) -> None:
        facts = discover("رویداد سرام\nمنتظرتونن\nحتما سر بزنید")

        self.assertIs(facts.discovery_type, DiscoveryType.EVENT)
        self.assertIsNone(facts.source_date_text)

    def test_nothing_is_converted_to_a_timestamp(self) -> None:
        facts = discover("کارگاه سفالگری\nجمعه ۲۱ شهریور ساعت ۱۶\nآدرس: تهران")

        self.assertNotIn("starts_at", facts.__slots__)
        self.assertIn("۲۱", facts.source_date_text)


class AddressAndCityTests(unittest.TestCase):
    def test_an_address_label_is_read(self) -> None:
        for label in ("آدرس", "نشانی", "Address", "Location"):
            with self.subTest(label=label):
                facts = discover(f"کارگاه سفالگری جمعه ۲۱ شهریور\n{label}: خیابان ولیعصر، پلاک ۱۲")
                self.assertEqual(facts.address, "خیابان ولیعصر، پلاک ۱۲")

    def test_an_address_on_the_line_after_the_label_is_read(self) -> None:
        facts = discover("کارگاه سفالگری جمعه ۲۱ شهریور\nآدرس:\nخیابان ولیعصر، پلاک ۱۲")

        self.assertEqual(facts.address, "خیابان ولیعصر، پلاک ۱۲")

    def test_a_venue_label_is_read_separately(self) -> None:
        facts = discover("کنسرت موسیقی جمعه ۲۱ شهریور\nمحل برگزاری: خانه هنرمندان\nآدرس: خیابان ایرانشهر")

        self.assertEqual(facts.venue_name, "خانه هنرمندان")
        self.assertEqual(facts.address, "خیابان ایرانشهر")

    def test_an_ambiguous_venue_label_with_an_address_becomes_address(self) -> None:
        facts = discover("کنسرت موسیقی جمعه ۲۱ شهریور\nمکان: جردن، خیابان انصاری، پلاک ۲۵")

        self.assertEqual(facts.address, "جردن، خیابان انصاری، پلاک ۲۵")
        self.assertIsNone(facts.venue_name)

    def test_ambiguous_venue_labels_keep_clear_venue_names(self) -> None:
        cases = {
            "مکان: گالری شیرین": "گالری شیرین",
            "محل برگزاری: خانه هنرمندان": "خانه هنرمندان",
        }
        for labelled_value, expected in cases.items():
            with self.subTest(labelled_value=labelled_value):
                facts = discover(f"کنسرت موسیقی جمعه ۲۱ شهریور\n{labelled_value}")
                self.assertEqual(facts.venue_name, expected)
                self.assertIsNone(facts.address)

    def test_a_venue_phrase_with_street_structure_is_kept_as_one_address(self) -> None:
        facts = discover(
            "نمایشگاه عکس جمعه ۲۱ شهریور\n"
            "مکان برگزاری: گالری نمونه، بلوار هنر، کوچه دوم، پلاک ۴"
        )

        self.assertEqual(
            facts.address,
            "گالری نمونه، بلوار هنر، کوچه دوم، پلاک ۴",
        )
        self.assertIsNone(facts.venue_name)

    def test_english_address_vocabulary_disambiguates_a_persian_venue_label(self) -> None:
        facts = discover("Design meetup Friday\nمحل: Studio North, Example Street, No. 14")

        self.assertEqual(facts.address, "Studio North, Example Street, No. 14")
        self.assertIsNone(facts.venue_name)

    def test_an_unlabelled_place_word_is_not_a_venue(self) -> None:
        # A place word in prose, without holding or attendance wording, names nothing.
        facts = discover("کنسرت موسیقی جمعه ۲۱ شهریور با الهام از خانه هنرمندان")

        self.assertIsNone(facts.venue_name)

    def test_natural_holding_construction_names_the_venue(self) -> None:
        facts = discover("کنسرت موسیقی جمعه ۲۱ شهریور در خانه هنرمندان برگزار می‌شود")

        self.assertEqual(facts.venue_name, "خانه هنرمندان")
        self.assertIsNone(facts.address)
        self.assertIsNone(facts.city)

    def test_a_city_is_read_only_when_the_text_says_one(self) -> None:
        facts = discover("کارگاه سفالگری جمعه ۲۱ شهریور\nآدرس: تهران، نیاوران، سه راه یاسر")

        self.assertEqual(facts.city, "تهران")

    def test_a_neighborhood_never_implies_its_city(self) -> None:
        facts = discover("کارگاه سفالگری جمعه ۲۱ شهریور\nآدرس: نیاوران، سه راه یاسر، بن‌بست بهار")

        self.assertEqual(facts.address, "نیاوران، سه راه یاسر، بن‌بست بهار")
        self.assertIsNone(facts.city)

    def test_no_address_label_means_no_address(self) -> None:
        facts = discover("کارگاه سفالگری جمعه ۲۱ شهریور در نیاوران")

        self.assertIsNone(facts.address)

    def test_a_map_pin_is_an_explicit_location_label(self) -> None:
        facts = discover(
            "کارگاه سفالگری با حضور هنرمندان تهران\n"
            "🕒 جمعه ساعت ۱۸\n"
            "📍 کاشان، شهرک صنعتی نمونه، خیابان هنر"
        )

        self.assertEqual(facts.source_date_text, "جمعه ساعت ۱۸")
        self.assertEqual(facts.address, "کاشان، شهرک صنعتی نمونه، خیابان هنر")
        self.assertEqual(facts.city, "کاشان")

    def test_a_map_pin_heading_is_not_mistaken_for_an_address(self) -> None:
        facts = discover("نمایشگاه گروهی جمعه ساعت ۱۸\n📍 رویداد تهران با ما")

        self.assertIsNone(facts.address)


class PriceTests(unittest.TestCase):
    def test_price_wording_is_preserved(self) -> None:
        facts = discover("کارگاه سفالگری جمعه ۲۱ شهریور\nورودی ۳۵۰ هزار تومان")

        self.assertEqual(facts.price_text, "ورودی ۳۵۰ هزار تومان")

    def test_a_free_event_keeps_its_wording(self) -> None:
        facts = discover("نشست تخصصی پنجشنبه ۲۸ شهریور\nورود برای همه رایگان است")

        self.assertEqual(facts.price_text, "ورود برای همه رایگان است")

    def test_no_numeric_price_is_produced(self) -> None:
        facts = discover("کارگاه سفالگری جمعه ۲۱ شهریور\nهزینه: ۳۵۰۰۰۰ تومان")

        self.assertEqual(facts.price_text, "۳۵۰۰۰۰ تومان")
        self.assertFalse(hasattr(facts, "price_amount"))
        self.assertFalse(hasattr(facts, "currency"))

    def test_no_price_wording_means_none(self) -> None:
        facts = discover("کارگاه سفالگری جمعه ۲۱ شهریور\nآدرس: تهران")

        self.assertIsNone(facts.price_text)

    def test_price_related_prose_without_a_value_is_not_price_text(self) -> None:
        facts = discover(
            "نشست گفتگو این هفته\n"
            "برای اطلاعات تاریخ، آدرس و هزینه به کانال ما مراجعه کنید"
        )

        self.assertIsNone(facts.price_text)

    def test_explicit_price_shapes_are_kept(self) -> None:
        cases = {
            "رایگان": "رایگان",
            "ورودی رایگان": "ورودی رایگان",
            "۳۵۰ هزار تومان": "۳۵۰ هزار تومان",
            "هزینه: ۴۵۰ هزار تومان": "۴۵۰ هزار تومان",
            "قیمت بلیت: ۵۰۰٬۰۰۰ تومان": "۵۰۰٬۰۰۰ تومان",
            "free": "free",
            "price: $20": "$20",
        }
        for price_line, expected in cases.items():
            with self.subTest(price_line=price_line):
                facts = discover(f"کارگاه طراحی\nجمعه ساعت ۱۸\n{price_line}")
                self.assertEqual(facts.price_text, expected)


class RegistrationTests(unittest.TestCase):
    def test_a_registration_url_is_read(self) -> None:
        facts = discover("ورکشاپ طراحی جمعه ۲۱ شهریور\nثبت نام: https://example.test/register")

        self.assertEqual(facts.registration_url, "https://example.test/register")

    def test_trailing_punctuation_is_not_part_of_the_url(self) -> None:
        facts = discover("ورکشاپ طراحی جمعه ۲۱ شهریور\nثبت نام در https://example.test/register.")

        self.assertEqual(facts.registration_url, "https://example.test/register")

    def test_no_link_means_none(self) -> None:
        facts = discover("ورکشاپ طراحی جمعه ۲۱ شهریور\nبرای ثبت نام پیام دهید")

        self.assertIsNone(facts.registration_url)

    def test_an_unrelated_url_is_not_registration(self) -> None:
        for text in (
            "ورکشاپ طراحی جمعه ۲۱ شهریور\nسایت ما: https://example.test/register",
            "ورکشاپ طراحی جمعه ۲۱ شهریور\nاینستاگرام ما https://instagram.com/example",
        ):
            with self.subTest(text=text):
                self.assertIsNone(discover(text).registration_url)

    def test_the_url_associated_with_registration_is_preferred(self) -> None:
        facts = discover(
            "ورکشاپ طراحی جمعه ۲۱ شهریور\n"
            "سایت ما: https://example.test\n"
            "ثبت‌نام: https://example.test/register"
        )

        self.assertEqual(facts.registration_url, "https://example.test/register")

    def test_ticket_wording_associates_its_url(self) -> None:
        facts = discover(
            "کنسرت موسیقی جمعه ۲۱ شهریور\n"
            "برای تهیه بلیت به https://example.test/tickets مراجعه کنید"
        )

        self.assertEqual(facts.registration_url, "https://example.test/tickets")


class EventFormatTests(unittest.TestCase):
    def test_explicit_online_wording(self) -> None:
        facts = discover("وبینار طراحی محصول پنجشنبه ۲۸ شهریور\nبه صورت آنلاین برگزار می‌شود")

        self.assertEqual(facts.event_format, "online")

    def test_explicit_in_person_wording(self) -> None:
        facts = discover("کارگاه سفالگری جمعه ۲۱ شهریور\nبه صورت حضوری")

        self.assertEqual(facts.event_format, "in_person")

    def test_both_wordings_make_it_hybrid(self) -> None:
        facts = discover("همایش سالانه پنجشنبه ۲۸ شهریور\nحضوری و آنلاین")

        self.assertEqual(facts.event_format, "hybrid")

    def test_an_address_alone_does_not_imply_in_person(self) -> None:
        facts = discover("کارگاه سفالگری جمعه ۲۱ شهریور\nآدرس: تهران، خیابان ولیعصر")

        self.assertIsNone(facts.event_format)


class CategoryTests(unittest.TestCase):
    def test_a_category_comes_from_unambiguous_terminology(self) -> None:
        cases = {
            "کارگاه سفالگری جمعه ۲۱ شهریور\nآدرس: تهران": "workshop",
            "کنسرت موسیقی سنتی جمعه ۲۱ شهریور\nآدرس: تهران": "concert",
            "نمایشگاه عکس جمعه ۲۱ شهریور\nآدرس: تهران": "exhibition",
            "جشنواره تئاتر جمعه ۲۱ شهریور\nآدرس: تهران": "festival",
        }
        for text, expected in cases.items():
            with self.subTest(expected=expected):
                self.assertEqual(discover(text).category, expected)


class PlaceFieldTests(unittest.TestCase):
    CAPTION = (
        "گالری نگاه، فضایی برای هنر معاصر\n"
        "ساعات بازدید: هر روز از ۱۱ تا ۲۰\n"
        "بازدید رایگان است\n"
        "آدرس: تهران، خیابان کریمخان، پلاک ۸"
    )

    def setUp(self) -> None:
        self.facts = discover(self.CAPTION)

    def test_the_result_is_a_place(self) -> None:
        self.assertIs(self.facts.discovery_type, DiscoveryType.PLACE)

    def test_a_place_name_is_read(self) -> None:
        self.assertEqual(self.facts.title, "گالری نگاه")

    def test_a_place_name_is_read_after_introduction_wording(self) -> None:
        cases = {
            "معرفی گالری نگاه": "گالری نگاه",
            "آشنایی با موزه هنرهای معاصر": "موزه هنرهای معاصر",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(discover(text).title, expected)

    def test_a_place_summary_quotes_the_source_line(self) -> None:
        self.assertEqual(self.facts.summary, "گالری نگاه، فضایی برای هنر معاصر")

    def test_opening_hours_keep_their_wording(self) -> None:
        self.assertEqual(self.facts.opening_hours_text, "ساعات بازدید: هر روز از ۱۱ تا ۲۰")

    def test_generic_daily_prose_is_not_place_or_opening_hours_context(self) -> None:
        found = analyze("آدم‌ها و برندهایی که هر روز چیزی تازه یاد می‌گیرند")

        self.assertEqual(found.place_context, ())

    def test_daily_wording_with_schedule_evidence_is_opening_hours_context(self) -> None:
        found = analyze("ساعات بازدید هر روز از ۱۱ تا ۲۰")

        self.assertIn("هر روز", {signal.term for signal in found.place_context})

    def test_place_address_and_city_are_read(self) -> None:
        self.assertEqual(self.facts.address, "تهران، خیابان کریمخان، پلاک ۸")
        self.assertEqual(self.facts.city, "تهران")

    def test_a_place_carries_no_event_only_fields(self) -> None:
        for name in ("source_date_text", "event_format", "registration_url"):
            with self.subTest(field=name):
                self.assertIsNone(getattr(self.facts, name))

    def test_a_place_category_is_read(self) -> None:
        self.assertEqual(self.facts.category, "gallery")
        self.assertEqual(discover("موزه هنر\nساعات بازدید: هر روز\nآدرس: تهران").category, "museum")


class OtherResultTests(unittest.TestCase):
    def test_other_carries_no_extracted_fields(self) -> None:
        facts = discover("گزارش تصویری از کارگاه سفالگری که هفته گذشته برگزار شد")

        self.assertIs(facts.discovery_type, DiscoveryType.OTHER)
        for name in ("title", "summary", "category", "address", "city", "price_text", "language"):
            with self.subTest(field=name):
                self.assertIsNone(getattr(facts, name))


class EnglishFieldTests(unittest.TestCase):
    CAPTION = (
        "Design meetup at Studio North\n"
        "Friday at 7 PM\n"
        "Venue: Studio North\n"
        "Address: 14 Example Street\n"
        "Price: free\n"
        "Register at https://tickets.example.test/design-meetup"
    )

    def test_english_fields_are_read_from_their_labels(self) -> None:
        facts = discover(self.CAPTION)

        self.assertIs(facts.discovery_type, DiscoveryType.EVENT)
        self.assertEqual(facts.venue_name, "Studio North")
        self.assertEqual(facts.address, "14 Example Street")
        self.assertEqual(facts.price_text, "free")
        self.assertEqual(facts.registration_url, "https://tickets.example.test/design-meetup")
        self.assertEqual(facts.language, "en")


if __name__ == "__main__":
    unittest.main()
