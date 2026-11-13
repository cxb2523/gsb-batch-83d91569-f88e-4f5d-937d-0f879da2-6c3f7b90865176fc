"""Read-only tests for the append-only raw store.

Analysis reads stored observations; it must never rewrite them, and it must look at
what the source says now rather than what it said the first time it was seen.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gatherradar.domain import RawItem, SourceType, compute_content_hash
from gatherradar.storage.jsonl import JsonlRawItemStore, raw_item_from_dict, raw_item_to_dict

CAPTURED_AT = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)
PUBLISHED_AT = datetime(2026, 9, 10, 15, 30, tzinfo=timezone.utc)


def make_item(shortcode: str = "ABC123", raw_text: str = "کارگاه طراحی شهری", **overrides) -> RawItem:
    content_url = overrides.pop("content_url", f"https://www.instagram.com/p/{shortcode}/")
    published_at = overrides.pop("published_at", PUBLISHED_AT)
    values = {
        "id": f"instagram:davvvat:{shortcode}",
        "source_id": "davvvat_instagram",
        "source_type": SourceType.INSTAGRAM,
        "external_id": shortcode,
        "content_type": "image",
        "content_url": content_url,
        "raw_text": raw_text,
        "captured_at": CAPTURED_AT,
        "published_at": published_at,
        "author": "davvvat",
        "image_url": "https://cdn.example.test/thumb.jpg",
        "content_hash": compute_content_hash(
            raw_text=raw_text, published_at=published_at, content_url=content_url
        ),
        "raw_metadata": {"transport": "browser", "hashtags": ["#هنر"]},
    }
    values.update(overrides)
    return RawItem(**values)


class RoundTripTests(unittest.TestCase):
    def test_a_stored_item_reads_back_identically(self) -> None:
        original = make_item()

        self.assertEqual(raw_item_from_dict(raw_item_to_dict(original)), original)

    def test_persian_text_and_emoji_survive_the_round_trip(self) -> None:
        original = make_item(raw_text="کافه‌گالری نگاه 🎨\nساعت ۱۸")

        self.assertEqual(raw_item_from_dict(raw_item_to_dict(original)).raw_text, original.raw_text)

    def test_a_missing_publish_date_reads_back_as_none(self) -> None:
        self.assertIsNone(raw_item_from_dict(raw_item_to_dict(make_item(published_at=None))).published_at)

    def test_timestamps_come_back_timezone_aware(self) -> None:
        item = raw_item_from_dict(raw_item_to_dict(make_item()))

        self.assertIsNotNone(item.captured_at.tzinfo)
        self.assertEqual(item.published_at, PUBLISHED_AT)

    def test_malformed_payloads_are_rejected(self) -> None:
        for broken in (
            {},
            {"id": "x"},
            dict(raw_item_to_dict(make_item()), source_type="telegram"),
            dict(raw_item_to_dict(make_item()), captured_at="not-a-date"),
            dict(raw_item_to_dict(make_item()), captured_at="2026-09-15T09:00:00"),
            dict(raw_item_to_dict(make_item()), raw_metadata=["not", "an", "object"]),
            dict(raw_item_to_dict(make_item()), id=""),
            dict(raw_item_to_dict(make_item()), raw_text=None),
        ):
            with self.subTest(payload=sorted(broken)[:2]):
                with self.assertRaises((KeyError, TypeError, ValueError)):
                    raw_item_from_dict(broken)


class ReadLatestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.path = Path(self.workdir.name) / "raw" / "instagram" / "davvvat.jsonl"
        self.store = JsonlRawItemStore(self.path)

    def write(self, *items: RawItem) -> None:
        self.store.append_new(items)

    def test_reading_an_absent_file_finds_nothing(self) -> None:
        outcome = self.store.read_latest_items()

        self.assertEqual(outcome.items, ())
        self.assertEqual(outcome.malformed, ())
        self.assertEqual(outcome.path, self.path)

    def test_stored_items_are_read_back(self) -> None:
        self.write(make_item("A1"), make_item("A2"))

        self.assertEqual(
            [item.external_id for item in self.store.read_latest_items().items], ["A1", "A2"]
        )

    def test_only_the_latest_observation_of_an_id_is_analyzed(self) -> None:
        self.write(make_item("A1", raw_text="متن اول"))
        self.write(make_item("A1", raw_text="متن ویرایش‌شده"))

        items = self.store.read_latest_items().items

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].raw_text, "متن ویرایش‌شده")

    def test_earlier_observations_stay_on_disk(self) -> None:
        self.write(make_item("A1", raw_text="متن اول"))
        self.write(make_item("A1", raw_text="متن ویرایش‌شده"))

        lines = self.path.read_text(encoding="utf-8").strip().splitlines()

        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["raw_text"], "متن اول")

    def test_reading_never_rewrites_the_file(self) -> None:
        self.write(make_item("A1"), make_item("A2"))
        before = self.path.read_bytes()

        self.store.read_latest_items()

        self.assertEqual(self.path.read_bytes(), before)

    def test_a_malformed_line_is_isolated_and_reported(self) -> None:
        self.write(make_item("A1"), make_item("A2"))
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("{not json}\n")
            handle.write(json.dumps({"id": "instagram:davvvat:BAD", "source_type": "instagram"}) + "\n")
            handle.write(json.dumps(["not", "an", "object"]) + "\n")

        outcome = self.store.read_latest_items()

        self.assertEqual([item.external_id for item in outcome.items], ["A1", "A2"])
        self.assertEqual(len(outcome.malformed), 3)
        self.assertTrue(all(reason.startswith("line ") for reason in outcome.malformed))

    def test_a_malformed_report_does_not_include_stored_text(self) -> None:
        self.write(make_item("A1", raw_text="متن محرمانه"))
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({"id": "x", "raw_text": "متن محرمانه", "source_type": "instagram"}) + "\n")

        for reason in self.store.read_latest_items().malformed:
            self.assertNotIn("متن محرمانه", reason)

    def test_blank_lines_are_tolerated(self) -> None:
        self.write(make_item("A1"))
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n   \n")

        outcome = self.store.read_latest_items()

        self.assertEqual(len(outcome.items), 1)
        self.assertEqual(outcome.malformed, ())

    def test_undated_and_dated_observations_are_both_read(self) -> None:
        self.write(
            make_item("A1", published_at=PUBLISHED_AT),
            make_item("A2", published_at=None),
            make_item("A3", published_at=PUBLISHED_AT - timedelta(days=1)),
        )

        items = self.store.read_latest_items().items

        self.assertEqual(len(items), 3)
        self.assertIsNone(next(item for item in items if item.external_id == "A2").published_at)


if __name__ == "__main__":
    unittest.main()
