"""Classification tests for the deterministic rule engine.

Every caption here is synthetic and sanitized. Real collected Instagram captions are
never committed as fixtures, so these are written to reproduce the *shape* of the
observed cases — an event announcement, a space introducing itself, a recap — rather
than anyone's actual posts.
"""

import unittest
from pathlib import Path
from unittest import mock

from gatherradar.domain import DiscoveryType
from gatherradar.extraction import ExtractionInput, RuleBasedDiscoveryProvider, analyze, classify
from gatherradar.extraction.rule_based import (
    REASON_EVENT_PATH_A,
    REASON_EVENT_PATH_B,
    REASON_PLACE,
)

ROOT = Path(__file__).resolve().parents[1]

# --- The observed real-world shapes, rewritten as synthetic captions -------------------

EVENT_WITH_DATE_AND_ADDRESS = (
    "کارگاه سفالگری با نگاه معاصر\n"
    "جمعه ۲۱ شهریور از ساعت ۱۶ تا ۲۲\n"
    "ورودی ۳۵۰ هزار تومان\n"
    "آدرس: تهران، نیاوران، سه راه یاسر، بن‌بست بهار"
)
EVENT_WITH_RELATIVE_DATE = "دورهمی عکاسان شهری آخر هفته\nآدرس: خیابان کریمخان، پلاک ۴۲"
EVENT_SPACE_WITHOUT_A_DATE = (
    "اینجا فقط ایونت نیست 🌿\n"
    "یک فضای دنج برای کار و گفتگو\n"
    "حتما بهشون سر بزنید\n"
    "آدرس: تهران، سعادت‌آباد، خیابان سرو"
)
NAMED_EVENT_WITH_ATTENDANCE = (
    "رویداد سرام در برج‌های فرمان\n"
    "با آثار بیش از ۳۰ هنرمند\n"
    "منتظرتونن\n"
    "حتما سر بزنید"
)
GALLERY_INTRODUCTION = (
    "گالری نگاه، فضایی برای هنر معاصر\n"
    "ساعات بازدید: هر روز از ۱۱ تا ۲۰\n"
    "آدرس: تهران، خیابان کریمخان"
)
MUSEUM_INTRODUCTION = (
    "موزه هنرهای معاصر پذیرای شما است\n"
    "ساعات بازدید: همه روزه از ۱۰ تا ۱۸\n"
    "آدرس: تهران، خیابان کارگر شمالی"
)
GALLERY_OPENING_WITH_DATE = (
    "گالری نگاه\n"
    "افتتاحیه نمایشگاه نقاشی\n"
    "پنجشنبه ۲۸ شهریور ساعت ۱۷\n"
    "آدرس: تهران، خیابان کریمخان"
)
RETROSPECTIVE_RECAP = (
    "گزارش تصویری از کارگاه سفالگری که هفته گذشته برگزار شد\n"
    "تصاویر رویداد را ببینید\n"
    "مروری بر یک روز خوب"
)
ENGLISH_EVENT = (
    "Join us Friday at 7 PM for a design meetup at Studio North ✨\n"
    "Register at https://tickets.example.test/design-meetup"
)


def discover(text: str):
    provider = RuleBasedDiscoveryProvider()
    return provider.discover(
        ExtractionInput(
            raw_item_id="instagram:example:ABC",
            source_id="example_instagram",
            source_type="instagram",
            raw_text=text,
            content_url="https://www.instagram.com/p/ABC/",
            content_type="image",
        )
    )


def kind(text: str) -> DiscoveryType:
    return discover(text).discovery_type


class ObservedShapeTests(unittest.TestCase):
    """The outcomes this engine was tuned against, as regressions."""

    def test_event_with_date_time_and_address_is_an_event(self) -> None:
        self.assertIs(kind(EVENT_WITH_DATE_AND_ADDRESS), DiscoveryType.EVENT)

    def test_event_with_a_relative_date_and_address_is_an_event(self) -> None:
        self.assertIs(kind(EVENT_WITH_RELATIVE_DATE), DiscoveryType.EVENT)

    def test_an_invitation_without_any_date_is_still_an_event(self) -> None:
        """The tuning fix: requiring a date made this real shape unreachable."""
        facts = discover(EVENT_SPACE_WITHOUT_A_DATE)

        self.assertIs(facts.discovery_type, DiscoveryType.EVENT)
        self.assertEqual(facts.evidence.reason, REASON_EVENT_PATH_B)

    def test_a_named_event_with_attendance_is_an_event(self) -> None:
        facts = discover(NAMED_EVENT_WITH_ATTENDANCE)

        self.assertIs(facts.discovery_type, DiscoveryType.EVENT)
        self.assertEqual(facts.title, "رویداد سرام")

    def test_gallery_introduction_is_a_place(self) -> None:
        facts = discover(GALLERY_INTRODUCTION)

        self.assertIs(facts.discovery_type, DiscoveryType.PLACE)
        self.assertEqual(facts.evidence.reason, REASON_PLACE)

    def test_museum_introduction_is_a_place(self) -> None:
        self.assertIs(kind(MUSEUM_INTRODUCTION), DiscoveryType.PLACE)

    def test_gallery_with_an_opening_and_a_date_is_an_event(self) -> None:
        facts = discover(GALLERY_OPENING_WITH_DATE)

        self.assertIs(facts.discovery_type, DiscoveryType.EVENT)
        self.assertEqual(facts.evidence.reason, REASON_EVENT_PATH_A)

    def test_place_introductions_need_no_hours_date_or_address(self) -> None:
        cases = (
            "معرفی گالری نگاه؛ فضایی برای هنر معاصر",
            "آشنایی با موزه هنرهای معاصر",
            "Introducing North Gallery, an art space worth visiting",
            "Discover a museum in Shiraz worth visiting",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIs(kind(text), DiscoveryType.PLACE)

    def test_introduction_wording_without_a_place_term_is_other(self) -> None:
        self.assertIs(kind("معرفی محصول جدید ما"), DiscoveryType.OTHER)

    def test_concrete_event_evidence_takes_precedence_over_place(self) -> None:
        facts = discover("افتتاحیه نمایشگاه در گالری نگاه، جمعه ساعت ۱۸")

        self.assertIs(facts.discovery_type, DiscoveryType.EVENT)
        self.assertEqual(facts.evidence.reason, REASON_EVENT_PATH_A)

    def test_a_retrospective_recap_is_other(self) -> None:
        self.assertIs(kind(RETROSPECTIVE_RECAP), DiscoveryType.OTHER)

    def test_an_english_announcement_is_an_event(self) -> None:
        self.assertIs(kind(ENGLISH_EVENT), DiscoveryType.EVENT)


class SingleSignalTests(unittest.TestCase):
    """No single signal may create an event on its own."""

    def test_an_event_word_alone_is_not_an_event(self) -> None:
        for text in (
            "ما یک تیم خلاق هستیم و به رویداد علاقه داریم",
            "اینجا کارگاه ما است",
            "we love a good workshop",
        ):
            with self.subTest(text=text):
                self.assertIsNot(kind(text), DiscoveryType.EVENT)

    def test_a_date_alone_is_not_an_event(self) -> None:
        for text in ("جمعه ۲۱ شهریور از ساعت ۱۶ تا ۲۲", "آخر هفته می‌بینیمتون", "Friday at 7 PM"):
            with self.subTest(text=text):
                self.assertIsNot(kind(text), DiscoveryType.EVENT)

    def test_an_address_alone_is_not_an_event(self) -> None:
        self.assertIsNot(kind("آدرس: تهران، خیابان ولیعصر، پلاک ۱۲"), DiscoveryType.EVENT)

    def test_an_attendance_invitation_alone_is_not_an_event(self) -> None:
        for text in ("حتما سر بزنید و از این فرصت استفاده کنید", "منتظر شما هستیم", "join us, come by"):
            with self.subTest(text=text):
                self.assertIsNot(kind(text), DiscoveryType.EVENT)

    def test_registration_alone_is_not_an_event(self) -> None:
        for text in ("برای ثبت نام پیام دهید", "registration is now open"):
            with self.subTest(text=text):
                self.assertIs(kind(text), DiscoveryType.OTHER)

    def test_a_place_word_alone_is_not_a_place(self) -> None:
        self.assertIsNot(kind("عکس امروز از گالری"), DiscoveryType.PLACE)


class EventPathTests(unittest.TestCase):
    def test_path_a_needs_terminology_and_occurrence_evidence(self) -> None:
        facts = discover("کنسرت موسیقی سنتی\nپنجشنبه ۲۸ شهریور ساعت ۲۱")

        self.assertIs(facts.discovery_type, DiscoveryType.EVENT)
        self.assertEqual(facts.evidence.reason, REASON_EVENT_PATH_A)

    def test_path_b_needs_terminology_attendance_and_context(self) -> None:
        facts = discover("نمایشگاه گروهی عکس\nمنتظر شما هستیم\nآدرس: تهران، خیابان سهروردی")

        self.assertIs(facts.discovery_type, DiscoveryType.EVENT)
        self.assertEqual(facts.evidence.reason, REASON_EVENT_PATH_B)

    def test_attendance_without_event_terminology_takes_neither_path(self) -> None:
        facts = discover("منتظر شما هستیم\nآدرس: تهران، خیابان سهروردی")
        self.assertIs(facts.discovery_type, DiscoveryType.OTHER)

    def test_registration_wording_counts_as_occurrence_evidence(self) -> None:
        facts = discover("ورکشاپ طراحی محصول\nبرای ثبت نام به ما پیام دهید\nحضوری")
        self.assertIs(facts.discovery_type, DiscoveryType.EVENT)

    def test_a_bare_link_is_not_occurrence_evidence(self) -> None:
        facts = discover("رویداد جزو علاقه‌مندی‌های ماست https://example.test/profile")
        self.assertIs(facts.discovery_type, DiscoveryType.OTHER)


class RetrospectiveTests(unittest.TestCase):
    def test_retrospective_wording_is_recorded_as_negative_evidence(self) -> None:
        evidence = discover(RETROSPECTIVE_RECAP).evidence

        self.assertGreater(evidence.negative_score, 0)
        self.assertIn("retrospective:هفته گذشته", evidence.negative_signals)
        self.assertIn("retrospective:برگزار شد", evidence.negative_signals)

    def test_english_retrospective_wording_is_also_negative(self) -> None:
        facts = discover("A recap of the workshop we ran last week. Behind the scenes photos.")

        self.assertIs(facts.discovery_type, DiscoveryType.OTHER)
        self.assertGreater(facts.evidence.negative_score, 0)

    def test_a_penalty_is_not_a_veto(self) -> None:
        """A post that recaps the last occurrence and announces the next is an event."""
        facts = discover(
            "کارگاه سفالگری هفته گذشته برگزار شد و دوره بعدی هم اعلام شد\n"
            "نمایشگاه آثار پنجشنبه ۲۸ شهریور ساعت ۱۷\n"
            "برای ثبت نام پیام دهید\n"
            "آدرس: تهران، خیابان کریمخان"
        )

        self.assertIs(facts.discovery_type, DiscoveryType.EVENT)
        self.assertGreater(facts.evidence.negative_score, 0)

    def test_the_future_reading_of_a_verb_is_not_retrospective(self) -> None:
        found = analyze("این نمایشگاه جمعه برگزار می‌شود")

        self.assertEqual(found.retrospective, ())
        self.assertTrue(found.attendance)


class NamedEventTests(unittest.TestCase):
    """Named-event detection is conservative; a false match must not inflate a score."""

    def named(self, text: str):
        return analyze(text).named_event

    def test_a_real_name_is_recognized(self) -> None:
        self.assertEqual(self.named("رویداد سرام در برج‌های فرمان").text, "رویداد سرام")

    def test_a_name_written_with_a_zero_width_non_joiner_is_recognized(self) -> None:
        self.assertEqual(self.named("رویداد ام‌زون امسال هم برگزار شد").text, "رویداد ام‌زون")

    def test_a_quoted_name_is_recognized(self) -> None:
        self.assertEqual(
            self.named("نمایشگاه «نقش‌های ماندگار» از هفته آینده").text,
            "نمایشگاه «نقش‌های ماندگار»",
        )

    def test_a_multi_word_name_is_recognized(self) -> None:
        self.assertEqual(self.named("کارگاه طراحی محصول برای تازه‌کارها").text, "کارگاه طراحی محصول")

    def test_a_grammatical_continuation_is_not_a_name(self) -> None:
        for text in (
            "رویداد میتونید در صفحه ما ببینید",
            "رویداد می‌توانید در صفحه ما ببینید",
            "رویداد جزو برنامه‌های ما بود",
            "رویداد این هفته نیست",
            "ایونت است که ما دوستش داریم",
        ):
            with self.subTest(text=text):
                self.assertIsNone(self.named(text))

    def test_a_plural_form_is_not_one_named_event(self) -> None:
        self.assertIsNone(self.named("رویدادهای تهران را دنبال کنید"))

    def test_a_term_used_mid_sentence_names_nothing(self) -> None:
        self.assertIsNone(self.named("اینجا فقط ایونت نیست"))
        self.assertIsNone(self.named("ما به رویداد سرام علاقه داریم"))

    def test_a_date_after_the_term_is_not_a_name(self) -> None:
        self.assertIsNone(self.named("رویداد آخر هفته"))
        self.assertIsNone(self.named("کنسرت جمعه"))

    def test_a_false_named_event_does_not_raise_the_event_score(self) -> None:
        with_name = discover("رویداد سرام در برج‌های فرمان").evidence.event_score
        without_name = discover("رویداد جزو برنامه‌های ما بود").evidence.event_score

        self.assertGreater(with_name, without_name)
        self.assertNotIn("named_event", " ".join(discover("رویداد جزو برنامه‌های ما بود").evidence.matched_signals))


class TitleTests(unittest.TestCase):
    """An unknown title is better than an invented one."""

    def test_a_sentence_mentioning_an_event_word_has_no_title(self) -> None:
        self.assertIsNone(discover(EVENT_SPACE_WITHOUT_A_DATE).title)

    def test_a_validated_named_event_becomes_the_title(self) -> None:
        self.assertEqual(discover(NAMED_EVENT_WITH_ATTENDANCE).title, "رویداد سرام")

    def test_a_repeated_quoted_name_supports_a_full_heading_with_a_connector(self) -> None:
        facts = discover(
            "رویداد شهر با تو زیباتره\n"
            "«شهر با تو زیباتره» فرصتی برای دیدار سازندگان محلی است\n"
            "جمعه ساعت ۱۸"
        )

        self.assertEqual(facts.title, "رویداد شهر با تو زیباتره")

    def test_title_expansion_does_not_weaken_false_positive_guards(self) -> None:
        for text in (
            "رویداد میتونید در صفحه ما ببینید",
            "رویداد جزو برنامه‌های ما بود",
            "اینجا فقط ایونت نیست",
        ):
            with self.subTest(text=text):
                self.assertIsNone(analyze(text).named_event)

    def test_a_first_line_is_not_a_title_just_because_it_says_event(self) -> None:
        facts = discover("امروز کلی ایونت داریم\nپنجشنبه ۲۸ شهریور ساعت ۱۷\nآدرس: تهران")
        self.assertIsNone(facts.title)

    def test_other_results_carry_no_title(self) -> None:
        self.assertIsNone(discover(RETROSPECTIVE_RECAP).title)


class InsufficientContentTests(unittest.TestCase):
    def test_a_lone_function_word_carries_no_meaningful_content(self) -> None:
        from gatherradar.extraction import has_meaningful_content

        for text in ("and", "  و  ", "the", "🎉", "...", "-"):
            with self.subTest(text=text):
                self.assertFalse(has_meaningful_content(text))

    def test_a_short_real_title_does_carry_meaningful_content(self) -> None:
        from gatherradar.extraction import has_meaningful_content

        for text in ("کنسرت", "گالری", "concert", "۱۹ شهریور", "2026"):
            with self.subTest(text=text):
                self.assertTrue(has_meaningful_content(text))


class ScriptAndFormattingTests(unittest.TestCase):
    def test_persian_digits_are_recognized_as_numbers(self) -> None:
        facts = discover("کارگاه چاپ دستی\nپنجشنبه ۲۸ شهریور ساعت ۱۷")

        self.assertIs(facts.discovery_type, DiscoveryType.EVENT)
        self.assertEqual(facts.source_date_text, "پنجشنبه ۲۸ شهریور ساعت ۱۷")

    def test_a_zero_width_non_joiner_does_not_hide_a_term(self) -> None:
        spaced = analyze("کافه‌گالری نگاه")
        plain = analyze("کافه گالری نگاه")

        self.assertEqual([signal.term for signal in spaced.place_terms], ["کافه گالری"])
        self.assertEqual(
            [signal.term for signal in spaced.place_terms], [signal.term for signal in plain.place_terms]
        )

    def test_emoji_do_not_break_classification_or_wording(self) -> None:
        facts = discover("🎨 کارگاه سفالگری 🌿\nجمعه ۲۱ شهریور ساعت ۱۶ ✨\nآدرس: تهران، خیابان ولیعصر")

        self.assertIs(facts.discovery_type, DiscoveryType.EVENT)
        self.assertEqual(facts.source_date_text, "جمعه ۲۱ شهریور ساعت ۱۶")

    def test_a_longer_word_containing_a_term_does_not_match_it(self) -> None:
        self.assertEqual(analyze("موسیقی کلاسیک ایرانی").event_weak, ())
        self.assertEqual(analyze("رویدادهای تهران").event_strong, ())

    def test_arabic_letter_spellings_still_match(self) -> None:
        self.assertTrue(analyze("گالري نگاه").place_terms)

    def test_language_is_detected_from_the_dominant_script(self) -> None:
        self.assertEqual(discover(EVENT_WITH_DATE_AND_ADDRESS).language, "fa")
        self.assertEqual(discover(ENGLISH_EVENT).language, "en")
        self.assertIsNone(analyze("2026 🎉 ۱۹").language)


class EvidenceReportingTests(unittest.TestCase):
    def test_evidence_records_scores_signals_and_a_reason(self) -> None:
        evidence = discover(EVENT_WITH_DATE_AND_ADDRESS).evidence

        self.assertGreater(evidence.event_score, 0)
        self.assertEqual(evidence.negative_score, 0)
        self.assertIn("event_strong:کارگاه", evidence.matched_signals)
        self.assertIn("date:شهریور", evidence.matched_signals)
        self.assertTrue(evidence.reason)

    def test_matched_signals_are_stable_between_runs(self) -> None:
        first = discover(EVENT_WITH_DATE_AND_ADDRESS).evidence
        second = discover(EVENT_WITH_DATE_AND_ADDRESS).evidence

        self.assertEqual(first, second)

    def test_other_results_still_explain_themselves(self) -> None:
        evidence = discover(RETROSPECTIVE_RECAP).evidence
        self.assertTrue(evidence.reason)

    def test_classification_is_a_pure_function_of_the_text(self) -> None:
        found = analyze(EVENT_WITH_DATE_AND_ADDRESS)
        self.assertEqual(classify(found), classify(analyze(EVENT_WITH_DATE_AND_ADDRESS)))


class OfflineTests(unittest.TestCase):
    def test_the_rule_engine_makes_no_network_access(self) -> None:
        with mock.patch("socket.socket.connect", side_effect=AssertionError("network used")):
            for text in (
                EVENT_WITH_DATE_AND_ADDRESS,
                GALLERY_INTRODUCTION,
                RETROSPECTIVE_RECAP,
                ENGLISH_EVENT,
            ):
                with self.subTest(text=text.splitlines()[0]):
                    self.assertIsNotNone(discover(text).discovery_type)

    def test_the_default_provider_is_the_rule_engine(self) -> None:
        from gatherradar.orchestration import discovery_run

        source = Path(discovery_run.__file__).read_text(encoding="utf-8")
        self.assertIn("RuleBasedDiscoveryProvider()", source)


if __name__ == "__main__":
    unittest.main()
