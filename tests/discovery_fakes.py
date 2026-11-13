"""Synthetic raw items and scripted providers for the discovery tests.

Test-only: production code has no fake provider. The scripted providers decide the
classification, so these tests exercise architecture rather than rule quality — the
rule engine's own judgement is tested in test_discovery_rules.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

from gatherradar.domain import DiscoveryType, RawItem, Source, SourceType, compute_content_hash
from gatherradar.extraction import (
    DiscoveryFacts,
    ExtractionInput,
    ProviderExtractionError,
)

CAPTURED_AT = datetime(2026, 9, 13, 9, 0, tzinfo=timezone.utc)
PUBLISHED_AT = datetime(2026, 9, 10, 15, 30, tzinfo=timezone.utc)

PERSIAN_EVENT_TEXT = (
    "جمعه ۲۱ شهریور از ساعت ۱۸ دورهمی طراحی در خانه هنرمندان برگزار می‌شود 🎨\n"
    "۱۹ و ۲۰ شهریور از ساعت ۱۶ تا ۲۲\n"
    "ورودی ۳۵۰ هزار تومان\n"
    "نیاوران، سه راه یاسر، بن‌بست بهار"
)
PERSIAN_OTHER_TEXT = "امروز چند عکس از هفته گذشته را با شما به اشتراک گذاشتیم."
PERSIAN_PLACE_TEXT = (
    "گالری نگاه، فضایی برای هنر معاصر\n"
    "ساعات بازدید: هر روز از ۱۱ تا ۲۰\n"
    "آدرس: تهران، خیابان کریمخان"
)
ENGLISH_EVENT_TEXT = (
    "Join us Friday at 7 PM for a design meetup at Studio North ✨ "
    "Register at https://tickets.example.test/design-meetup"
)
ENGLISH_OTHER_TEXT = "Our new autumn collection is now available."

PERSIAN_EVENT_FACTS = DiscoveryFacts(
    discovery_type=DiscoveryType.EVENT,
    title="دورهمی طراحی",
    summary="دورهمی طراحی در خانه هنرمندان 🎨",
    category="workshop",
    source_date_text="۱۹ و ۲۰ شهریور از ساعت ۱۶ تا ۲۲",
    venue_name="خانه هنرمندان",
    address="نیاوران، سه راه یاسر، بن‌بست بهار",
    event_format="in_person",
    price_text="ورودی ۳۵۰ هزار تومان",
    language="fa",
    extraction_confidence=0.82,
)
ENGLISH_EVENT_FACTS = DiscoveryFacts(
    discovery_type=DiscoveryType.EVENT,
    title="Design meetup",
    summary="A design meetup at Studio North on Friday at 7 PM ✨",
    source_date_text="Friday at 7 PM",
    venue_name="Studio North",
    registration_url="https://tickets.example.test/design-meetup",
    language="en",
    extraction_confidence=0.9,
)
PERSIAN_PLACE_FACTS = DiscoveryFacts(
    discovery_type=DiscoveryType.PLACE,
    title="گالری نگاه",
    summary="گالری نگاه، فضایی برای هنر معاصر",
    category="gallery",
    address="تهران، خیابان کریمخان",
    city="تهران",
    opening_hours_text="ساعات بازدید: هر روز از ۱۱ تا ۲۰",
    language="fa",
)
OTHER_FACTS = DiscoveryFacts(discovery_type=DiscoveryType.OTHER)


def make_source(**overrides) -> Source:
    values = {
        "id": "davvvat_instagram",
        "publisher_key": "davvvat",
        "name": "Davvvat Instagram",
        "source_type": SourceType.INSTAGRAM,
        "url": "https://www.instagram.com/davvvat/",
        "username": "davvvat",
        "city_hint": "Tehran",
    }
    values.update(overrides)
    return Source(**values)


def make_raw_item(
    raw_text: str,
    *,
    shortcode: str = "EVT1",
    source_id: str = "davvvat_instagram",
    content_hash: str | None = None,
    published_at: datetime | None = PUBLISHED_AT,
) -> RawItem:
    content_url = f"https://www.instagram.com/p/{shortcode}/"
    return RawItem(
        id=f"instagram:davvvat:{shortcode}",
        source_id=source_id,
        source_type=SourceType.INSTAGRAM,
        external_id=shortcode,
        content_type="reel",
        content_url=content_url,
        raw_text=raw_text,
        captured_at=CAPTURED_AT,
        published_at=published_at,
        author="davvvat",
        image_url="https://cdn.example.test/thumb.jpg",
        content_hash=(
            content_hash
            if content_hash is not None
            else compute_content_hash(raw_text=raw_text, published_at=published_at, content_url=content_url)
        ),
        raw_metadata={"transport": "browser", "caption_source": "main:author-block"},
    )


class RecordingProvider:
    """Records every input it receives; subclasses decide the response."""

    name = "recording-test-provider"

    def __init__(self) -> None:
        self.calls: list[ExtractionInput] = []

    def discover(self, extraction_input: ExtractionInput) -> DiscoveryFacts:
        self.calls.append(extraction_input)
        return self.respond(extraction_input)

    def respond(self, extraction_input: ExtractionInput) -> DiscoveryFacts:
        raise NotImplementedError


class FixedProvider(RecordingProvider):
    name = "fixed-test-provider"

    def __init__(self, facts: DiscoveryFacts | None = None) -> None:
        super().__init__()
        self.facts = facts if facts is not None else DiscoveryFacts(discovery_type=DiscoveryType.EVENT)

    def respond(self, extraction_input: ExtractionInput) -> DiscoveryFacts:
        return self.facts


class OtherProvider(RecordingProvider):
    name = "other-test-provider"

    def respond(self, extraction_input: ExtractionInput) -> DiscoveryFacts:
        return OTHER_FACTS


class FailingProvider(RecordingProvider):
    name = "failing-test-provider"

    def respond(self, extraction_input: ExtractionInput) -> DiscoveryFacts:
        raise ProviderExtractionError("test provider is unavailable")


class InvalidOutputProvider(RecordingProvider):
    name = "invalid-output-test-provider"

    def __init__(self, output: object) -> None:
        super().__init__()
        self.output = output

    def respond(self, extraction_input: ExtractionInput) -> DiscoveryFacts:
        return self.output  # type: ignore[return-value]


class ScriptedProvider(RecordingProvider):
    """Responds per raw_item_id: facts or any object are returned, exceptions are raised."""

    name = "scripted-test-provider"

    def __init__(self, responses: dict[str, object]) -> None:
        super().__init__()
        self.responses = responses

    def respond(self, extraction_input: ExtractionInput) -> DiscoveryFacts:
        if extraction_input.raw_item_id not in self.responses:
            raise AssertionError(f"unexpected provider call for {extraction_input.raw_item_id}")
        response = self.responses[extraction_input.raw_item_id]
        if isinstance(response, BaseException):
            raise response
        return response  # type: ignore[return-value]
