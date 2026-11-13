import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from gatherradar.collectors.base import SourceNotFoundError
from gatherradar.collectors.instagram import ORIGIN_POST, InstagramCollector
from gatherradar.orchestration.collection_run import (
    find_source,
    instagram_output_path,
    run_instagram_collection,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "sources.yaml"
CAPTURED_AT = datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc)


def make_post(shortcode: str, caption: str = "کارگاه طراحی شهری"):
    return SimpleNamespace(
        shortcode=shortcode,
        mediaid=17998877665544332,
        typename="GraphImage",
        is_video=False,
        caption=caption,
        caption_hashtags=[],
        caption_mentions=[],
        date_utc=datetime(2026, 9, 9, 14, 30),
        owner_username="davvvat",
        url="https://scontent.example.com/image.jpg",
    )


def collector_for(shortcodes, caption: str = "کارگاه طراحی شهری"):
    posts = [(ORIGIN_POST, make_post(code, caption)) for code in shortcodes]
    return InstagramCollector(
        fetch_posts=lambda username, limit: posts[:limit],
        now=lambda: CAPTURED_AT,
    )


class SourceLookupTests(unittest.TestCase):
    def test_registry_provides_the_davvvat_instagram_source(self) -> None:
        source = find_source("davvvat_instagram", CONFIG)

        self.assertEqual(source.username, "davvvat")
        self.assertEqual(source.url, "https://www.instagram.com/davvvat/")

    def test_unknown_source_id_is_reported(self) -> None:
        with self.assertRaises(SourceNotFoundError):
            find_source("not_a_real_source", CONFIG)

    def test_output_path_is_derived_from_the_username(self) -> None:
        source = find_source("davvvat_instagram", CONFIG)
        path = instagram_output_path(source, "data")

        self.assertEqual(path, Path("data") / "raw" / "instagram" / "davvvat.jsonl")


class CollectionRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)

    def run_once(self, shortcodes, limit=5, caption="کارگاه طراحی شهری"):
        return run_instagram_collection(
            "davvvat_instagram",
            config_path=CONFIG,
            data_dir=self.data_dir,
            limit=limit,
            collector=collector_for(shortcodes, caption),
        )

    def test_first_run_stores_every_observed_item(self) -> None:
        summary = self.run_once(["A1", "B2", "C3"])

        self.assertEqual(summary.observed, 3)
        self.assertEqual(summary.new, 3)
        self.assertEqual(summary.changed, 0)
        self.assertEqual(summary.already_existing, 0)
        self.assertEqual(summary.failed, 0)
        self.assertTrue(summary.output_path.exists())

    def test_second_run_adds_nothing_new(self) -> None:
        self.run_once(["A1", "B2", "C3"])

        summary = self.run_once(["A1", "B2", "C3"])

        self.assertEqual(summary.observed, 3)
        self.assertEqual(summary.new, 0)
        self.assertEqual(summary.changed, 0)
        self.assertEqual(summary.already_existing, 3)
        self.assertEqual(
            len(summary.output_path.read_text(encoding="utf-8").splitlines()), 3
        )

    def test_only_genuinely_new_posts_are_added(self) -> None:
        self.run_once(["A1", "B2"])

        summary = self.run_once(["NEW1", "A1", "B2"])

        self.assertEqual(summary.new, 1)
        self.assertEqual(summary.already_existing, 2)

    def test_edited_caption_is_recorded_as_changed(self) -> None:
        self.run_once(["A1"], caption="Event Friday at 17:00")

        summary = self.run_once(["A1"], caption="Event cancelled")

        self.assertEqual(summary.new, 0)
        self.assertEqual(summary.changed, 1)
        self.assertEqual(summary.already_existing, 0)
        lines = summary.output_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)  # both observations preserved, not overwritten

    def test_limit_bounds_the_run(self) -> None:
        summary = self.run_once(["A1", "B2", "C3", "D4", "E5", "F6"], limit=2)

        self.assertEqual(summary.observed, 2)
        self.assertEqual(summary.new, 2)

    def test_run_writes_under_the_requested_data_directory(self) -> None:
        summary = self.run_once(["A1"])

        self.assertEqual(
            summary.output_path,
            self.data_dir / "raw" / "instagram" / "davvvat.jsonl",
        )

    def test_unknown_source_id_is_reported(self) -> None:
        with self.assertRaises(SourceNotFoundError):
            run_instagram_collection(
                "nope",
                config_path=CONFIG,
                data_dir=self.data_dir,
                collector=collector_for([]),
            )


if __name__ == "__main__":
    unittest.main()
