"""CLI tests for `gatherradar extract`.

The command's whole promise is that it is safe and free to run: it reads what was
already collected and does nothing else. These tests hold it to that.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from gatherradar.cli import build_parser, main

CONFIG = Path(__file__).resolve().parents[1] / "config" / "sources.yaml"
PUBLISHED_AT = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)

EVENT_CAPTION = (
    "کارگاه سفالگری با نگاه معاصر\n"
    "جمعه ۲۱ شهریور از ساعت ۱۶ تا ۲۲\n"
    "ورودی ۳۵۰ هزار تومان\n"
    "آدرس: تهران، نیاوران، سه راه یاسر"
)
PLACE_CAPTION = (
    "گالری نگاه، فضایی برای هنر معاصر\n"
    "ساعات بازدید: هر روز از ۱۱ تا ۲۰\n"
    "آدرس: تهران، خیابان کریمخان"
)
OTHER_CAPTION = "گزارش تصویری از کارگاه سفالگری که هفته گذشته برگزار شد"


def run_main(argv, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        exit_code = main(argv, **kwargs)
    return exit_code, out.getvalue(), err.getvalue()


def parse_quietly(argv):
    with redirect_stderr(io.StringIO()):
        return build_parser().parse_args(argv)


def write_store(data_dir: Path, captions) -> Path:
    path = data_dir / "raw" / "instagram" / "davvvat.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for shortcode, published_at, caption in captions:
            handle.write(
                json.dumps(
                    {
                        "id": f"instagram:davvvat:{shortcode}",
                        "source_id": "davvvat_instagram",
                        "source_type": "instagram",
                        "external_id": shortcode,
                        "content_type": "image",
                        "content_url": f"https://www.instagram.com/p/{shortcode}/",
                        "raw_text": caption,
                        "captured_at": "2026-09-15T09:00:00+00:00",
                        "published_at": published_at.isoformat() if published_at else None,
                        "author": "davvvat",
                        "image_url": None,
                        "content_hash": f"{shortcode.lower():0>64}",
                        "raw_metadata": {"transport": "browser"},
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return path


class ExtractArgumentParsingTests(unittest.TestCase):
    def test_extract_instagram_takes_a_source_id_and_defaults(self) -> None:
        args = build_parser().parse_args(["extract", "instagram", "davvvat_instagram"])

        self.assertEqual(args.command, "extract")
        self.assertEqual(args.source_id, "davvvat_instagram")
        self.assertEqual(args.limit, 5)
        self.assertEqual(args.config, "config/sources.yaml")
        self.assertEqual(args.data_dir, "data")

    def test_config_and_data_dir_can_be_overridden(self) -> None:
        args = build_parser().parse_args(
            ["extract", "instagram", "davvvat_instagram", "--config", "c.yaml", "--data-dir", "d", "--limit", "2"]
        )

        self.assertEqual((args.config, args.data_dir, args.limit), ("c.yaml", "d", 2))

    def test_extract_has_no_transport_option(self) -> None:
        args = build_parser().parse_args(["extract", "instagram", "davvvat_instagram"])
        self.assertFalse(hasattr(args, "transport"))

    def test_extract_requires_a_source_type_and_id(self) -> None:
        for argv in (["extract"], ["extract", "instagram"]):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit):
                    parse_quietly(argv)

    def test_a_non_positive_limit_is_rejected(self) -> None:
        exit_code, _, err = run_main(["extract", "instagram", "davvvat_instagram", "--limit", "0"])

        self.assertEqual(exit_code, 2)
        self.assertIn("--limit", err)


class ExtractRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.data_dir = Path(self.workdir.name)
        self.path = write_store(
            self.data_dir,
            [
                ("AAA1", PUBLISHED_AT, EVENT_CAPTION),
                ("BBB2", PUBLISHED_AT - timedelta(days=1), "and"),
                ("CCC3", PUBLISHED_AT - timedelta(days=2), PLACE_CAPTION),
                ("DDD4", PUBLISHED_AT - timedelta(days=3), OTHER_CAPTION),
                ("EEE5", PUBLISHED_AT - timedelta(days=9), "خیلی قدیمی"),
            ],
        )

    def extract(self, *extra):
        return run_main(
            [
                "extract",
                "instagram",
                "davvvat_instagram",
                "--config",
                str(CONFIG),
                "--data-dir",
                str(self.data_dir),
                *extra,
            ]
        )

    def test_a_run_reports_every_result_kind(self) -> None:
        exit_code, out, _ = self.extract()

        self.assertEqual(exit_code, 0)
        self.assertIn("Result: Event", out)
        self.assertIn("Result: Place", out)
        self.assertIn("Result: Other", out)
        self.assertIn("Result: Skipped (insufficient_text)", out)

    def test_the_summary_counts_every_kind(self) -> None:
        _, out, _ = self.extract()

        for line in ("Observed: 5", "Events: 1", "Places: 1", "Other: 2", "Skipped: 1", "Failed: 0"):
            with self.subTest(line=line):
                self.assertIn(line, out)

    def test_scores_and_matched_signals_are_printed(self) -> None:
        _, out, _ = self.extract()

        self.assertIn("Scores: event", out)
        self.assertIn("Reason:", out)
        self.assertIn("Signals:", out)
        self.assertIn("event_strong:کارگاه", out)
        self.assertIn("Negative: retrospective:گزارش تصویری", out)
        self.assertIn("retrospective:برگزار شد", out)

    def test_extracted_fields_are_printed_in_the_source_wording(self) -> None:
        _, out, _ = self.extract()

        self.assertIn("title: کارگاه سفالگری", out)
        self.assertIn("source_date_text: جمعه ۲۱ شهریور از ساعت ۱۶ تا ۲۲", out)
        self.assertIn("price_text: ورودی ۳۵۰ هزار تومان", out)
        self.assertIn("opening_hours_text: ساعات بازدید: هر روز از ۱۱ تا ۲۰", out)
        self.assertIn("evidence_url: https://www.instagram.com/p/AAA1/", out)

    def test_limit_takes_the_newest_stored_items(self) -> None:
        _, out, _ = self.extract("--limit", "2")

        self.assertIn("Observed: 2", out)
        self.assertIn("instagram:davvvat:AAA1", out)
        self.assertIn("instagram:davvvat:BBB2", out)
        self.assertNotIn("instagram:davvvat:EEE5", out)

    def test_the_run_persists_nothing(self) -> None:
        before = {path: path.stat().st_mtime_ns for path in self.data_dir.rglob("*") if path.is_file()}
        contents = self.path.read_bytes()

        self.extract()

        after = {path: path.stat().st_mtime_ns for path in self.data_dir.rglob("*") if path.is_file()}
        self.assertEqual(set(after), set(before))
        self.assertEqual(self.path.read_bytes(), contents)

    def test_the_run_never_collects_from_instagram(self) -> None:
        with (
            mock.patch("gatherradar.cli.run_instagram_collection", side_effect=AssertionError("collected")),
            mock.patch(
                "gatherradar.collectors.instagram_browser.authenticate_browser_profile",
                side_effect=AssertionError("browser opened"),
            ),
            mock.patch(
                "gatherradar.collectors.instagram.InstagramCollector.collect",
                side_effect=AssertionError("collector used"),
            ),
        ):
            exit_code, _, _ = self.extract()

        self.assertEqual(exit_code, 0)

    def test_the_run_makes_no_network_access(self) -> None:
        with mock.patch("socket.socket.connect", side_effect=AssertionError("network used")):
            exit_code, _, _ = self.extract()

        self.assertEqual(exit_code, 0)

    def test_the_run_needs_no_credentials_or_api_key(self) -> None:
        with (
            mock.patch("gatherradar.cli.getpass.getpass", side_effect=AssertionError("secret prompt")),
            mock.patch("builtins.input", side_effect=AssertionError("prompted")),
            mock.patch.dict("os.environ", {}, clear=True),
        ):
            exit_code, _, _ = self.extract()

        self.assertEqual(exit_code, 0)

    def test_the_provider_is_named_as_deterministic_and_free(self) -> None:
        _, out, _ = self.extract()

        self.assertIn("rule-based/1", out)
        self.assertIn("no AI and no network access", out)
        self.assertIn("Nothing was persisted", out)

    def test_an_unreadable_stored_line_is_reported_without_failing_the_run(self) -> None:
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("{not json}\n")

        exit_code, out, _ = self.extract()

        self.assertEqual(exit_code, 0)
        self.assertIn("Unreadable stored lines:", out)
        self.assertIn("Observed: 5", out)


class ExtractFailureTests(unittest.TestCase):
    def test_an_unknown_source_is_reported_without_a_traceback(self) -> None:
        exit_code, _, err = run_main(
            ["extract", "instagram", "not_a_source", "--config", str(CONFIG)]
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("not_a_source", err)
        self.assertNotIn("Traceback", err)

    def test_a_missing_registry_is_reported(self) -> None:
        exit_code, _, err = run_main(
            ["extract", "instagram", "davvvat_instagram", "--config", "no/such/sources.yaml"]
        )

        self.assertEqual(exit_code, 1)
        self.assertNotIn("Traceback", err)

    def test_an_empty_store_explains_how_to_collect(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            exit_code, out, _ = run_main(
                [
                    "extract",
                    "instagram",
                    "davvvat_instagram",
                    "--config",
                    str(CONFIG),
                    "--data-dir",
                    workdir,
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Observed: 0", out)
        self.assertIn("collect instagram davvvat_instagram", out)


if __name__ == "__main__":
    unittest.main()
