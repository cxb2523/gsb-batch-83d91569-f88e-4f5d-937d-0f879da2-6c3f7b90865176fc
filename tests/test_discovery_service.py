import unittest
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from discovery_fakes import (
    ENGLISH_EVENT_FACTS,
    ENGLISH_EVENT_TEXT,
    ENGLISH_OTHER_TEXT,
    OTHER_FACTS,
    PERSIAN_EVENT_FACTS,
    PERSIAN_EVENT_TEXT,
    PERSIAN_OTHER_TEXT,
    PERSIAN_PLACE_FACTS,
    PERSIAN_PLACE_TEXT,
    PUBLISHED_AT,
    FailingProvider,
    FixedProvider,
    InvalidOutputProvider,
    OtherProvider,
    ScriptedProvider,
    make_raw_item,
    make_source,
)
from gatherradar.domain import DiscoveryType, EventCandidate, PlaceCandidate
from gatherradar.extraction import (
    SKIP_EMPTY_TEXT,
    SKIP_INSUFFICIENT_TEXT,
    DiscoveryEvidence,
    DiscoveryFacts,
    DiscoveryService,
    DiscoveryStatus,
    ExtractionInput,
    InvalidExtractionOutputError,
    build_candidate_id,
    build_extraction_input,
    validate_discovery_facts,
)

ROOT = Path(__file__).resolve().parents[1]
EVENT_FIELDS = (
    "title",
    "summary",
    "category",
    "source_date_text",
    "venue_name",
    "address",
    "city",
    "event_format",
    "price_text",
    "registration_url",
    "language",
    "extraction_confidence",
)
PLACE_FIELDS = (
    "title",
    "summary",
    "category",
    "address",
    "city",
    "opening_hours_text",
    "price_text",
    "language",
)


def discover(provider, raw_item=None, source=None):
    raw_item = raw_item if raw_item is not None else make_raw_item(PERSIAN_EVENT_TEXT)
    return DiscoveryService(provider).discover(raw_item, source)


class ExtractionInputTests(unittest.TestCase):
    def test_input_carries_only_deliberate_source_evidence(self) -> None:
        raw_item = make_raw_item(PERSIAN_EVENT_TEXT)

        extraction_input = build_extraction_input(raw_item, make_source())

        self.assertEqual(
            extraction_input,
            ExtractionInput(
                raw_item_id="instagram:davvvat:EVT1",
                source_id="davvvat_instagram",
                source_type="instagram",
                raw_text=PERSIAN_EVENT_TEXT,
                content_url="https://www.instagram.com/p/EVT1/",
                content_type="reel",
                published_at=PUBLISHED_AT,
                author="davvvat",
                locale="fa-IR",
                timezone="Asia/Tehran",
                city_hint="Tehran",
                segments=(("caption", PERSIAN_EVENT_TEXT),),
            ),
        )

    def test_raw_metadata_is_not_passed_to_the_provider(self) -> None:
        names = {field.name for field in fields(ExtractionInput)}
        self.assertNotIn("raw_metadata", names)
        self.assertNotIn("image_url", names)

    def test_input_without_source_context_leaves_context_empty(self) -> None:
        extraction_input = build_extraction_input(make_raw_item(ENGLISH_EVENT_TEXT))

        self.assertIsNone(extraction_input.locale)
        self.assertIsNone(extraction_input.timezone)
        self.assertIsNone(extraction_input.city_hint)

    def test_source_context_must_match_the_raw_item_source(self) -> None:
        other = make_source(
            id="vadoostan_instagram", url="https://www.instagram.com/vadoostan/", username="vadoostan"
        )
        with self.assertRaises(ValueError):
            build_extraction_input(make_raw_item(ENGLISH_EVENT_TEXT), other)


class ProviderCallTests(unittest.TestCase):
    def test_provider_is_called_exactly_once_per_eligible_item(self) -> None:
        provider = FixedProvider(PERSIAN_EVENT_FACTS)
        raw_item = make_raw_item(PERSIAN_EVENT_TEXT)

        discover(provider, raw_item, make_source())

        self.assertEqual(provider.calls, [build_extraction_input(raw_item, make_source())])

    def test_empty_raw_text_skips_the_provider(self) -> None:
        provider = FixedProvider()

        outcome = discover(provider, make_raw_item(""))

        self.assertEqual(outcome.status, DiscoveryStatus.SKIPPED)
        self.assertEqual(outcome.reason, SKIP_EMPTY_TEXT)
        self.assertEqual(provider.calls, [])

    def test_whitespace_only_raw_text_is_also_skipped(self) -> None:
        provider = FixedProvider()
        outcome = discover(provider, make_raw_item(" \n\t "))

        self.assertEqual(outcome.status, DiscoveryStatus.SKIPPED)
        self.assertEqual(provider.calls, [])

    def test_meaningless_text_is_skipped_rather_than_classified_as_other(self) -> None:
        provider = FixedProvider()

        outcome = discover(provider, make_raw_item("and"))

        self.assertEqual(outcome.status, DiscoveryStatus.SKIPPED)
        self.assertEqual(outcome.reason, SKIP_INSUFFICIENT_TEXT)
        self.assertIsNone(outcome.discovery_type)
        self.assertEqual(provider.calls, [])

    def test_a_short_legitimate_title_is_still_analyzed(self) -> None:
        for text in ("کنسرت", "Concert", "۱۹ شهریور"):
            with self.subTest(text=text):
                provider = FixedProvider(OTHER_FACTS)
                outcome = discover(provider, make_raw_item(text))

                self.assertEqual(outcome.status, DiscoveryStatus.DISCOVERED)
                self.assertEqual(len(provider.calls), 1)

    def test_skipped_item_produces_no_candidate_of_any_kind(self) -> None:
        outcome = discover(OtherProvider(), make_raw_item(""))

        self.assertIsNone(outcome.event)
        self.assertIsNone(outcome.place)
        self.assertIsNone(outcome.candidate)


class CandidateMappingTests(unittest.TestCase):
    def test_event_output_maps_onto_event_candidate(self) -> None:
        outcome = discover(FixedProvider(PERSIAN_EVENT_FACTS), source=make_source())

        self.assertEqual(outcome.status, DiscoveryStatus.DISCOVERED)
        self.assertEqual(outcome.discovery_type, DiscoveryType.EVENT)
        self.assertIsNone(outcome.reason)
        self.assertEqual(outcome.provider_name, "fixed-test-provider")
        self.assertIsInstance(outcome.event, EventCandidate)
        self.assertIsNone(outcome.place)
        self.assertTrue(outcome.event.is_event)
        for name in EVENT_FIELDS:
            with self.subTest(field=name):
                self.assertEqual(getattr(outcome.event, name), getattr(PERSIAN_EVENT_FACTS, name))

    def test_place_output_maps_onto_place_candidate(self) -> None:
        raw_item = make_raw_item(PERSIAN_PLACE_TEXT, shortcode="PLC1")

        outcome = discover(FixedProvider(PERSIAN_PLACE_FACTS), raw_item)

        self.assertEqual(outcome.discovery_type, DiscoveryType.PLACE)
        self.assertIsInstance(outcome.place, PlaceCandidate)
        self.assertIsNone(outcome.event)
        for name in PLACE_FIELDS:
            with self.subTest(field=name):
                self.assertEqual(getattr(outcome.place, name), getattr(PERSIAN_PLACE_FACTS, name))

    def test_place_content_is_never_forced_into_an_event_candidate(self) -> None:
        outcome = discover(FixedProvider(PERSIAN_PLACE_FACTS), make_raw_item(PERSIAN_PLACE_TEXT))

        self.assertIsNone(outcome.event)
        self.assertNotIsInstance(outcome.candidate, EventCandidate)

    def test_place_candidate_has_no_event_only_fields(self) -> None:
        names = {field.name for field in fields(PlaceCandidate)}
        self.assertTrue(
            names.isdisjoint({"is_event", "starts_at", "ends_at", "source_date_text", "registration_url"})
        )

    def test_other_output_produces_no_candidate(self) -> None:
        outcome = discover(OtherProvider(), make_raw_item(PERSIAN_OTHER_TEXT, shortcode="OTH1"))

        self.assertEqual(outcome.status, DiscoveryStatus.DISCOVERED)
        self.assertEqual(outcome.discovery_type, DiscoveryType.OTHER)
        self.assertIsNone(outcome.candidate)

    def test_unknown_fields_remain_none_and_an_event_needs_no_title(self) -> None:
        candidate = discover(FixedProvider(DiscoveryFacts(discovery_type=DiscoveryType.EVENT))).event

        self.assertTrue(candidate.is_event)
        for name in EVENT_FIELDS:
            with self.subTest(field=name):
                self.assertIsNone(getattr(candidate, name))

    def test_whitespace_only_fields_become_none(self) -> None:
        facts = DiscoveryFacts(
            discovery_type=DiscoveryType.EVENT,
            title="   ",
            summary="\n\t",
            venue_name="",
            address=" ",
            price_text="\n",
        )
        candidate = discover(FixedProvider(facts)).event

        for name in ("title", "summary", "venue_name", "address", "price_text"):
            with self.subTest(field=name):
                self.assertIsNone(getattr(candidate, name))

    def test_non_blank_text_is_kept_exactly(self) -> None:
        facts = DiscoveryFacts(discovery_type=DiscoveryType.EVENT, title="  Design meetup  ")
        self.assertEqual(discover(FixedProvider(facts)).event.title, "  Design meetup  ")

    def test_persian_text_and_emoji_are_preserved_exactly(self) -> None:
        provider = FixedProvider(PERSIAN_EVENT_FACTS)
        candidate = discover(provider).event

        self.assertEqual(provider.calls[0].raw_text, PERSIAN_EVENT_TEXT)
        self.assertEqual(candidate.address, "نیاوران، سه راه یاسر، بن‌بست بهار")
        self.assertEqual(candidate.summary, "دورهمی طراحی در خانه هنرمندان 🎨")
        self.assertIn("🎨", provider.calls[0].raw_text)

    def test_english_text_is_preserved_exactly(self) -> None:
        provider = FixedProvider(ENGLISH_EVENT_FACTS)
        candidate = discover(provider, make_raw_item(ENGLISH_EVENT_TEXT, shortcode="EVT2")).event

        self.assertEqual(provider.calls[0].raw_text, ENGLISH_EVENT_TEXT)
        self.assertEqual(candidate.summary, "A design meetup at Studio North on Friday at 7 PM ✨")
        self.assertEqual(candidate.registration_url, "https://tickets.example.test/design-meetup")

    def test_no_normalization_happens_in_this_layer(self) -> None:
        candidate = discover(FixedProvider(PERSIAN_EVENT_FACTS), source=make_source()).event

        self.assertEqual(candidate.source_date_text, "۱۹ و ۲۰ شهریور از ساعت ۱۶ تا ۲۲")
        self.assertEqual(candidate.price_text, "ورودی ۳۵۰ هزار تومان")
        self.assertEqual(candidate.category, "workshop")
        self.assertIsNone(candidate.starts_at)
        self.assertIsNone(candidate.ends_at)
        self.assertIsNone(candidate.price_amount)
        self.assertIsNone(candidate.currency)

    def test_city_hint_context_is_never_copied_into_city(self) -> None:
        provider = FixedProvider(PERSIAN_EVENT_FACTS)
        candidate = discover(provider, source=make_source(city_hint="Tehran")).event

        self.assertEqual(provider.calls[0].city_hint, "Tehran")
        self.assertIsNone(candidate.city)


class EvidenceTests(unittest.TestCase):
    def test_evidence_is_reported_on_the_outcome(self) -> None:
        evidence = DiscoveryEvidence(
            event_score=5.0, matched_signals=("event_strong:کنسرت",), reason="event: path"
        )
        facts = DiscoveryFacts(discovery_type=DiscoveryType.EVENT, evidence=evidence)

        outcome = discover(FixedProvider(facts))

        self.assertEqual(outcome.evidence, evidence)

    def test_evidence_never_reaches_the_candidate(self) -> None:
        names = {field.name for field in fields(EventCandidate)} | {
            field.name for field in fields(PlaceCandidate)
        }
        self.assertTrue(
            names.isdisjoint({"evidence", "event_score", "place_score", "matched_signals", "reason"})
        )

    def test_evidence_is_optional(self) -> None:
        outcome = discover(FixedProvider(DiscoveryFacts(discovery_type=DiscoveryType.EVENT)))
        self.assertIsNone(outcome.evidence)


class ProvenanceTests(unittest.TestCase):
    def test_raw_item_id_and_evidence_url_come_from_the_raw_item(self) -> None:
        raw_item = make_raw_item(ENGLISH_EVENT_TEXT, shortcode="EVT2")

        candidate = discover(FixedProvider(ENGLISH_EVENT_FACTS), raw_item).event

        self.assertEqual(candidate.raw_item_id, raw_item.id)
        self.assertEqual(candidate.evidence_url, raw_item.content_url)
        self.assertNotEqual(candidate.evidence_url, ENGLISH_EVENT_FACTS.registration_url)

    def test_place_provenance_also_comes_from_the_raw_item(self) -> None:
        raw_item = make_raw_item(PERSIAN_PLACE_TEXT, shortcode="PLC1")

        candidate = discover(FixedProvider(PERSIAN_PLACE_FACTS), raw_item).place

        self.assertEqual(candidate.raw_item_id, raw_item.id)
        self.assertEqual(candidate.evidence_url, raw_item.content_url)

    def test_output_that_tries_to_supply_provenance_is_rejected(self) -> None:
        spoofed = SimpleNamespace(
            discovery_type=DiscoveryType.EVENT,
            raw_item_id="instagram:someone:SPOOF",
            evidence_url="https://evil.example.test/",
        )

        outcome = discover(InvalidOutputProvider(spoofed))

        self.assertEqual(outcome.status, DiscoveryStatus.INVALID_OUTPUT)
        self.assertIsNone(outcome.candidate)

    def test_provider_output_contract_has_no_provenance_fields(self) -> None:
        names = {field.name for field in fields(DiscoveryFacts)}
        self.assertTrue(names.isdisjoint({"candidate_id", "raw_item_id", "evidence_url"}))


class CandidateIdTests(unittest.TestCase):
    def test_candidate_ids_are_deterministic(self) -> None:
        first = build_candidate_id(make_raw_item(PERSIAN_EVENT_TEXT))
        again = build_candidate_id(make_raw_item(PERSIAN_EVENT_TEXT))

        self.assertEqual(first, again)
        self.assertTrue(first.startswith("candidate:"))
        int(first.removeprefix("candidate:"), 16)

    def test_same_observation_discovers_the_same_candidate_id(self) -> None:
        raw_item = make_raw_item(PERSIAN_EVENT_TEXT)

        first = discover(FixedProvider(PERSIAN_EVENT_FACTS), raw_item).event
        second = discover(FixedProvider(PERSIAN_EVENT_FACTS), raw_item).event

        self.assertEqual(first.candidate_id, second.candidate_id)
        self.assertEqual(first.candidate_id, build_candidate_id(raw_item))

    def test_changed_content_hash_gives_a_different_candidate_id(self) -> None:
        original = make_raw_item(PERSIAN_EVENT_TEXT, content_hash="a" * 64)
        edited = make_raw_item(PERSIAN_EVENT_TEXT, content_hash="b" * 64)

        self.assertEqual(original.id, edited.id)
        self.assertNotEqual(build_candidate_id(original), build_candidate_id(edited))

    def test_different_raw_items_give_different_candidate_ids(self) -> None:
        self.assertNotEqual(
            build_candidate_id(make_raw_item(PERSIAN_EVENT_TEXT, shortcode="A1", content_hash="c" * 64)),
            build_candidate_id(make_raw_item(PERSIAN_EVENT_TEXT, shortcode="A2", content_hash="c" * 64)),
        )

    def test_candidate_id_does_not_depend_on_the_provider_or_the_result_kind(self) -> None:
        raw_item = make_raw_item(PERSIAN_EVENT_TEXT)

        as_event = discover(FixedProvider(PERSIAN_EVENT_FACTS), raw_item).event
        as_place = discover(FixedProvider(PERSIAN_PLACE_FACTS), raw_item).place

        self.assertEqual(as_event.candidate_id, as_place.candidate_id)
        self.assertEqual(as_event.candidate_id, build_candidate_id(raw_item))


class ValidationTests(unittest.TestCase):
    def assert_invalid(self, output: object) -> None:
        outcome = discover(InvalidOutputProvider(output))
        self.assertEqual(outcome.status, DiscoveryStatus.INVALID_OUTPUT)
        self.assertIsNone(outcome.candidate)
        self.assertTrue(outcome.reason)

    def test_invalid_confidence_is_rejected(self) -> None:
        for confidence in (1.2, -0.1, float("nan"), float("inf"), True, "0.8"):
            with self.subTest(confidence=confidence):
                self.assert_invalid(
                    DiscoveryFacts(discovery_type=DiscoveryType.EVENT, extraction_confidence=confidence)
                )

    def test_boundary_confidence_values_are_accepted(self) -> None:
        for confidence in (0, 1, 0.0, 0.5, 1.0):
            with self.subTest(confidence=confidence):
                candidate = discover(
                    FixedProvider(
                        DiscoveryFacts(discovery_type=DiscoveryType.EVENT, extraction_confidence=confidence)
                    )
                ).event
                self.assertEqual(candidate.extraction_confidence, float(confidence))

    def test_invalid_registration_url_is_rejected(self) -> None:
        for url in ("tickets.example.test/meetup", "javascript:alert(1)", "ftp://example.test/meetup", "https://"):
            with self.subTest(url=url):
                self.assert_invalid(DiscoveryFacts(discovery_type=DiscoveryType.EVENT, registration_url=url))

    def test_http_and_https_registration_urls_are_accepted(self) -> None:
        for url in ("http://tickets.example.test/meetup", "https://tickets.example.test/meetup?id=1"):
            with self.subTest(url=url):
                facts = DiscoveryFacts(discovery_type=DiscoveryType.EVENT, registration_url=url)
                self.assertEqual(discover(FixedProvider(facts)).event.registration_url, url)

    def test_discovery_type_must_be_the_typed_enum(self) -> None:
        for value in ("event", 1, None, True):
            with self.subTest(discovery_type=value):
                self.assert_invalid(DiscoveryFacts(discovery_type=value))

    def test_text_fields_must_be_text(self) -> None:
        self.assert_invalid(DiscoveryFacts(discovery_type=DiscoveryType.EVENT, title=123))

    def test_unsupported_event_format_is_rejected(self) -> None:
        for event_format in ("in-person", "unknown", "offline"):
            with self.subTest(event_format=event_format):
                self.assert_invalid(
                    DiscoveryFacts(discovery_type=DiscoveryType.EVENT, event_format=event_format)
                )

    def test_supported_event_formats_are_accepted(self) -> None:
        for event_format in ("in_person", "online", "hybrid"):
            with self.subTest(event_format=event_format):
                facts = DiscoveryFacts(discovery_type=DiscoveryType.EVENT, event_format=event_format)
                self.assertEqual(discover(FixedProvider(facts)).event.event_format, event_format)

    def test_other_may_not_carry_facts(self) -> None:
        self.assert_invalid(DiscoveryFacts(discovery_type=DiscoveryType.OTHER, title="Invented"))

    def test_place_may_not_carry_event_only_facts(self) -> None:
        for name in ("source_date_text", "registration_url", "event_format"):
            with self.subTest(field=name):
                value = "https://example.test/x" if name == "registration_url" else "in_person"
                self.assert_invalid(
                    DiscoveryFacts(discovery_type=DiscoveryType.PLACE, **{name: value})
                )

    def test_event_may_not_carry_place_only_facts(self) -> None:
        self.assert_invalid(
            DiscoveryFacts(discovery_type=DiscoveryType.EVENT, opening_hours_text="هر روز ۱۱ تا ۲۰")
        )

    def test_evidence_of_the_wrong_type_is_rejected(self) -> None:
        self.assert_invalid(DiscoveryFacts(discovery_type=DiscoveryType.EVENT, evidence={"score": 1}))

    def test_output_of_the_wrong_type_is_rejected(self) -> None:
        with self.assertRaises(InvalidExtractionOutputError):
            validate_discovery_facts({"discovery_type": DiscoveryType.EVENT})
        self.assert_invalid({"discovery_type": DiscoveryType.EVENT})


class FailureIsolationTests(unittest.TestCase):
    def test_provider_error_becomes_a_provider_failure_outcome(self) -> None:
        outcome = discover(FailingProvider())

        self.assertEqual(outcome.status, DiscoveryStatus.PROVIDER_FAILED)
        self.assertIsNone(outcome.candidate)
        self.assertEqual(outcome.reason, "test provider is unavailable")
        self.assertEqual(outcome.provider_name, "failing-test-provider")

    def test_provider_reported_invalid_output_is_isolated(self) -> None:
        raw_item = make_raw_item(ENGLISH_OTHER_TEXT, shortcode="OTH2")
        provider = ScriptedProvider({raw_item.id: InvalidExtractionOutputError("response was not valid JSON")})

        outcome = discover(provider, raw_item)

        self.assertEqual(outcome.status, DiscoveryStatus.INVALID_OUTPUT)
        self.assertEqual(outcome.reason, "response was not valid JSON")

    def test_unexpected_provider_bugs_are_not_swallowed(self) -> None:
        raw_item = make_raw_item(ENGLISH_EVENT_TEXT)
        provider = ScriptedProvider({raw_item.id: RuntimeError("adapter bug")})

        with self.assertRaises(RuntimeError):
            discover(provider, raw_item)


class NoNetworkTests(unittest.TestCase):
    def test_discovery_runs_without_any_network_access(self) -> None:
        samples = (
            (make_raw_item(PERSIAN_EVENT_TEXT, shortcode="EVT1"), PERSIAN_EVENT_FACTS),
            (make_raw_item(PERSIAN_PLACE_TEXT, shortcode="PLC1"), PERSIAN_PLACE_FACTS),
            (make_raw_item(PERSIAN_OTHER_TEXT, shortcode="OTH1"), OTHER_FACTS),
            (make_raw_item(ENGLISH_EVENT_TEXT, shortcode="EVT2"), ENGLISH_EVENT_FACTS),
        )
        provider = ScriptedProvider({raw_item.id: facts for raw_item, facts in samples})
        service = DiscoveryService(provider)

        with mock.patch("socket.socket.connect", side_effect=AssertionError("network used")):
            outcomes = [service.discover(raw_item, make_source()) for raw_item, _ in samples]

        self.assertTrue(all(outcome.status is DiscoveryStatus.DISCOVERED for outcome in outcomes))

    def test_extraction_code_has_no_provider_sdk_or_network_imports(self) -> None:
        paths = sorted((ROOT / "src" / "gatherradar" / "extraction").glob("*.py"))
        paths.append(ROOT / "src" / "gatherradar" / "orchestration" / "discovery_run.py")
        forbidden = ("openai", "anthropic", "requests", "httpx", "http.client", "urllib.request", "socket")

        for path in paths:
            source = path.read_text(encoding="utf-8").lower()
            for token in forbidden:
                with self.subTest(path=path.name, token=token):
                    self.assertNotIn(token, source)

    def test_no_ai_provider_dependency_is_declared(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
        for dependency in ("openai", "anthropic", "langchain", "cohere", "google-generativeai"):
            with self.subTest(dependency=dependency):
                self.assertNotIn(dependency, pyproject)

    def test_discovery_needs_no_api_key(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "src" / "gatherradar" / "extraction").glob("*.py"))
        ).lower()
        for token in ("api_key", "apikey", "os.environ", "getenv"):
            with self.subTest(token=token):
                self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
