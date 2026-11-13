import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gatherradar.domain import RawItem, SourceType, compute_content_hash
from gatherradar.storage.jsonl import JsonlRawItemStore, StorageError, raw_item_to_dict


CAPTURED_AT = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)


def make_item(shortcode: str = "ABC123", raw_text: str = "کارگاه طراحی شهری", **overrides) -> RawItem:
    content_type = overrides.pop("content_type", "image")
    content_url = overrides.pop("content_url", f"https://www.instagram.com/p/{shortcode}/")
    published_at = overrides.pop(
        "published_at", datetime(2026, 9, 9, 14, 30, tzinfo=timezone.utc)
    )
    content_hash = overrides.pop(
        "content_hash",
        compute_content_hash(
            raw_text=raw_text,
            published_at=published_at,
            content_url=content_url,
        ),
    )
    values = {
        "id": f"instagram:davvvat:{shortcode}",
        "source_id": "davvvat_instagram",
        "source_type": SourceType.INSTAGRAM,
        "external_id": shortcode,
        "content_type": content_type,
        "content_url": content_url,
        "raw_text": raw_text,
        "captured_at": CAPTURED_AT,
        "published_at": published_at,
        "author": "davvvat",
        "image_url": "https://scontent.example.com/image.jpg",
        "content_hash": content_hash,
        "raw_metadata": {"typename": "GraphImage", "hashtags": []},
    }
    values.update(overrides)
    return RawItem(**values)


class SerializationTests(unittest.TestCase):
    def test_raw_item_serializes_to_contract_shape(self) -> None:
        payload = raw_item_to_dict(make_item())

        self.assertEqual(payload["id"], "instagram:davvvat:ABC123")
        self.assertEqual(payload["source_type"], "instagram")
        self.assertEqual(payload["captured_at"], "2026-09-10T09:00:00+00:00")
        self.assertEqual(payload["published_at"], "2026-09-09T14:30:00+00:00")
        self.assertEqual(payload["raw_metadata"]["typename"], "GraphImage")
        self.assertEqual(len(payload["content_hash"]), 64)

    def test_missing_publish_date_serializes_as_null(self) -> None:
        payload = raw_item_to_dict(make_item(published_at=None))
        self.assertIsNone(payload["published_at"])

    def test_persian_text_is_not_escaped_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonlRawItemStore(Path(tmp) / "davvvat.jsonl")
            store.append_new([make_item()])
            content = store.path.read_text(encoding="utf-8")

        self.assertIn("کارگاه طراحی شهری", content)


class ContentHashHelperTests(unittest.TestCase):
    def test_hash_is_deterministic(self) -> None:
        kwargs = dict(
            raw_text="hello",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            content_url="https://example.com/p/1/",
        )
        self.assertEqual(compute_content_hash(**kwargs), compute_content_hash(**kwargs))

    def test_captured_at_is_not_a_hash_input(self) -> None:
        # compute_content_hash has no captured_at parameter at all: reruns on a
        # different day must not change the fingerprint of unchanged content.
        import inspect

        from gatherradar.domain.raw_item import compute_content_hash as fn

        self.assertNotIn("captured_at", inspect.signature(fn).parameters)

    def test_content_type_is_not_a_hash_input(self) -> None:
        # An internal reclassification (e.g. "video" -> "reel") must not change the
        # fingerprint of otherwise-unchanged source content.
        import inspect

        from gatherradar.domain.raw_item import compute_content_hash as fn

        self.assertNotIn("content_type", inspect.signature(fn).parameters)


class JsonlStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "raw" / "instagram" / "davvvat.jsonl"
        self.store = JsonlRawItemStore(self.path)

    def test_first_write_creates_parent_directories(self) -> None:
        outcome = self.store.append_new([make_item("A1"), make_item("B2")])

        self.assertEqual(outcome.new, 2)
        self.assertEqual(outcome.changed, 0)
        self.assertEqual(outcome.already_existing, 0)
        self.assertTrue(self.path.exists())

    def test_each_line_is_one_complete_record(self) -> None:
        self.store.append_new([make_item("A1"), make_item("B2")])
        lines = self.path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertIn("source_id", json.loads(line))

    def test_rerunning_the_same_items_appends_nothing(self) -> None:
        items = [make_item("A1"), make_item("B2")]
        self.store.append_new(items)

        outcome = self.store.append_new(items)

        self.assertEqual(outcome.new, 0)
        self.assertEqual(outcome.changed, 0)
        self.assertEqual(outcome.already_existing, 2)
        self.assertEqual(len(self.path.read_text(encoding="utf-8").splitlines()), 2)

    def test_only_unseen_items_are_appended(self) -> None:
        self.store.append_new([make_item("A1")])

        outcome = self.store.append_new([make_item("A1"), make_item("B2")])

        self.assertEqual(outcome.new, 1)
        self.assertEqual(outcome.already_existing, 1)
        self.assertEqual(self.store.existing_ids(), {
            "instagram:davvvat:A1",
            "instagram:davvvat:B2",
        })

    def test_duplicates_inside_one_batch_are_written_once(self) -> None:
        outcome = self.store.append_new([make_item("A1"), make_item("A1")])

        self.assertEqual(outcome.new, 1)
        self.assertEqual(outcome.already_existing, 1)

    def test_existing_ids_is_empty_when_no_file_yet(self) -> None:
        self.assertEqual(self.store.existing_ids(), set())

    def test_corrupt_jsonl_is_reported_instead_of_duplicated(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not json}\n", encoding="utf-8")

        with self.assertRaises(StorageError):
            self.store.existing_ids()

    def test_blank_lines_are_tolerated(self) -> None:
        self.store.append_new([make_item("A1")])
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write("\n")

        self.assertEqual(self.store.existing_ids(), {"instagram:davvvat:A1"})


class EditedContentDetectionTests(unittest.TestCase):
    """A changed caption must be detected and preserved as new raw evidence, not
    silently skipped just because the item id (shortcode) is unchanged."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "davvvat.jsonl"
        self.store = JsonlRawItemStore(self.path)

    def test_new_shortcode_is_new(self) -> None:
        outcome = self.store.append_new([make_item("A1", raw_text="Event Friday at 17:00")])
        self.assertEqual((outcome.new, outcome.changed, outcome.already_existing), (1, 0, 0))

    def test_same_shortcode_same_content_is_existing(self) -> None:
        self.store.append_new([make_item("A1", raw_text="Event Friday at 17:00")])

        outcome = self.store.append_new([make_item("A1", raw_text="Event Friday at 17:00")])

        self.assertEqual((outcome.new, outcome.changed, outcome.already_existing), (0, 0, 1))

    def test_same_shortcode_edited_caption_is_changed(self) -> None:
        self.store.append_new([make_item("A1", raw_text="Event Friday at 17:00")])

        outcome = self.store.append_new([make_item("A1", raw_text="Event cancelled")])

        self.assertEqual((outcome.new, outcome.changed, outcome.already_existing), (0, 1, 0))

    def test_edited_content_is_appended_not_overwritten(self) -> None:
        self.store.append_new([make_item("A1", raw_text="Event Friday at 17:00")])
        self.store.append_new([make_item("A1", raw_text="Event cancelled")])

        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        texts = [json.loads(line)["raw_text"] for line in lines]
        self.assertEqual(texts, ["Event Friday at 17:00", "Event cancelled"])

    def test_persian_caption_edit_is_detected_as_changed(self) -> None:
        self.store.append_new([make_item("A1", raw_text="جمعه ساعت ۱۷")])

        outcome = self.store.append_new([make_item("A1", raw_text="جمعه ساعت ۱۸")])

        self.assertEqual(outcome.changed, 1)

    def test_empty_caption_is_a_valid_stable_content_state(self) -> None:
        self.store.append_new([make_item("A1", raw_text="")])

        outcome = self.store.append_new([make_item("A1", raw_text="")])

        self.assertEqual((outcome.new, outcome.changed, outcome.already_existing), (0, 0, 1))

    def test_classification_uses_the_most_recently_stored_hash(self) -> None:
        self.store.append_new([make_item("A1", raw_text="v1")])
        self.store.append_new([make_item("A1", raw_text="v2")])

        # Rerunning v2 again should be "existing" against the latest stored hash,
        # not "changed" against the older v1 hash still present earlier in the file.
        outcome = self.store.append_new([make_item("A1", raw_text="v2")])

        self.assertEqual((outcome.new, outcome.changed, outcome.already_existing), (0, 0, 1))

    def test_malformed_jsonl_is_still_reported_safely(self) -> None:
        self.path.write_text("{not json}\n", encoding="utf-8")

        with self.assertRaises(StorageError):
            self.store.append_new([make_item("A1")])


if __name__ == "__main__":
    unittest.main()
