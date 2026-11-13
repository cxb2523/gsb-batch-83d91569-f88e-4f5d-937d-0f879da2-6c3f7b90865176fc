import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    ScriptedProvider,
    make_raw_item,
    make_source,
)
from gatherradar.domain import DiscoveryType, EventCandidate, PlaceCandidate
from gatherradar.extraction import DiscoveryService, DiscoveryStatus, ProviderExtractionError
from gatherradar.orchestration.discovery_run import run_discovery, select_latest

PUBLISHED = datetime(2026, 9, 10, 15, 30, tzinfo=timezone.utc)


def batch():
    """Items in an order that puts failures before successes."""
    items = [
        make_raw_item("Provider will fail on this one", shortcode="FAIL1"),
        make_raw_item(PERSIAN_EVENT_TEXT, shortcode="EVT1"),
        make_raw_item("", shortcode="EMPTY1"),
        make_raw_item("and", shortcode="THIN1"),
        make_raw_item("Provider returns garbage for this one", shortcode="BAD1"),
        make_raw_item(PERSIAN_PLACE_TEXT, shortcode="PLC1"),
        make_raw_item(PERSIAN_OTHER_TEXT, shortcode="OTH1"),
        make_raw_item(ENGLISH_EVENT_TEXT, shortcode="EVT2"),
        make_raw_item(ENGLISH_OTHER_TEXT, shortcode="OTH2"),
    ]
    responses = {
        "instagram:davvvat:FAIL1": ProviderExtractionError("scripted provider failure"),
        "instagram:davvvat:EVT1": PERSIAN_EVENT_FACTS,
        "instagram:davvvat:BAD1": {"discovery_type": "maybe"},
        "instagram:davvvat:PLC1": PERSIAN_PLACE_FACTS,
        "instagram:davvvat:OTH1": OTHER_FACTS,
        "instagram:davvvat:EVT2": ENGLISH_EVENT_FACTS,
        "instagram:davvvat:OTH2": OTHER_FACTS,
    }
    return items, ScriptedProvider(responses)


class DiscoveryRunTests(unittest.TestCase):
    def run_batch(self, **kwargs):
        items, provider = batch()
        summary = run_discovery(items, DiscoveryService(provider), **kwargs)
        return summary, provider

    def test_summary_counts_events_places_other_skipped_and_failed(self) -> None:
        summary, _ = self.run_batch()

        self.assertEqual(summary.observed, 9)
        self.assertEqual(summary.discovered, 5)
        self.assertEqual(summary.events, 2)
        self.assertEqual(summary.places, 1)
        self.assertEqual(summary.other, 2)
        self.assertEqual(summary.skipped, 2)
        self.assertEqual(summary.failed, 2)

    def test_batch_continues_after_failed_items(self) -> None:
        summary, _ = self.run_batch()

        self.assertEqual(
            [outcome.status for outcome in summary.outcomes],
            [
                DiscoveryStatus.PROVIDER_FAILED,
                DiscoveryStatus.DISCOVERED,
                DiscoveryStatus.SKIPPED,
                DiscoveryStatus.SKIPPED,
                DiscoveryStatus.INVALID_OUTPUT,
                DiscoveryStatus.DISCOVERED,
                DiscoveryStatus.DISCOVERED,
                DiscoveryStatus.DISCOVERED,
                DiscoveryStatus.DISCOVERED,
            ],
        )
        self.assertEqual(
            [candidate.raw_item_id for candidate in summary.candidates],
            ["instagram:davvvat:EVT1", "instagram:davvvat:PLC1", "instagram:davvvat:EVT2"],
        )

    def test_event_and_place_candidates_are_reported_separately(self) -> None:
        summary, _ = self.run_batch()

        self.assertTrue(all(isinstance(item, EventCandidate) for item in summary.event_candidates))
        self.assertTrue(all(isinstance(item, PlaceCandidate) for item in summary.place_candidates))
        self.assertEqual(len(summary.event_candidates), 2)
        self.assertEqual(len(summary.place_candidates), 1)

    def test_provider_is_called_once_per_eligible_item(self) -> None:
        _, provider = self.run_batch()

        called = [call.raw_item_id for call in provider.calls]
        self.assertEqual(len(called), 7)
        self.assertNotIn("instagram:davvvat:EMPTY1", called)
        self.assertNotIn("instagram:davvvat:THIN1", called)

    def test_source_context_is_looked_up_by_source_id(self) -> None:
        _, provider = self.run_batch(sources={"davvvat_instagram": make_source()})

        self.assertTrue(all(call.locale == "fa-IR" for call in provider.calls))
        self.assertTrue(all(call.city_hint == "Tehran" for call in provider.calls))

    def test_items_without_known_source_get_no_context(self) -> None:
        _, provider = self.run_batch(sources={})
        self.assertTrue(all(call.locale is None and call.timezone is None for call in provider.calls))

    def test_candidates_are_returned_in_memory_and_nothing_is_persisted(self) -> None:
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as workdir:
            os.chdir(workdir)
            try:
                summary, _ = self.run_batch()
                written = list(Path(workdir).iterdir())
            finally:
                os.chdir(original_cwd)

        self.assertEqual(written, [])
        self.assertEqual(len(summary.candidates), 3)

    def test_summary_reports_the_provider_name(self) -> None:
        summary, _ = self.run_batch()
        self.assertEqual(summary.provider_name, "scripted-test-provider")

    def test_any_iterable_of_raw_items_is_accepted(self) -> None:
        items, provider = batch()
        summary = run_discovery((item for item in items), DiscoveryService(provider))
        self.assertEqual(summary.observed, 9)

    def test_empty_batch_has_zero_counts(self) -> None:
        summary = run_discovery([], DiscoveryService(ScriptedProvider({})))

        self.assertEqual(
            (summary.observed, summary.discovered, summary.events, summary.places, summary.other,
             summary.skipped, summary.failed),
            (0, 0, 0, 0, 0, 0, 0),
        )

    def test_discovery_types_are_the_typed_enum(self) -> None:
        summary, _ = self.run_batch()
        reported = {outcome.discovery_type for outcome in summary.outcomes if outcome.discovery_type}

        self.assertTrue(reported <= {DiscoveryType.EVENT, DiscoveryType.PLACE, DiscoveryType.OTHER})


class SelectLatestTests(unittest.TestCase):
    def items(self):
        return [
            make_raw_item("سه", shortcode="C", published_at=PUBLISHED - timedelta(days=2)),
            make_raw_item("یک", shortcode="A", published_at=PUBLISHED),
            make_raw_item("بدون تاریخ", shortcode="X", published_at=None),
            make_raw_item("دو", shortcode="B", published_at=PUBLISHED - timedelta(days=1)),
        ]

    def shortcodes(self, selected):
        return [item.external_id for item in selected]

    def test_newest_published_items_come_first(self) -> None:
        self.assertEqual(self.shortcodes(select_latest(self.items(), 3)), ["A", "B", "C"])

    def test_undated_items_sort_after_dated_ones(self) -> None:
        self.assertEqual(self.shortcodes(select_latest(self.items(), 4)), ["A", "B", "C", "X"])

    def test_limit_takes_at_most_that_many_items(self) -> None:
        self.assertEqual(len(select_latest(self.items(), 2)), 2)
        self.assertEqual(len(select_latest(self.items(), 99)), 4)

    def test_selection_is_stable_and_repeatable(self) -> None:
        items = self.items()
        self.assertEqual(select_latest(items, 3), select_latest(items, 3))

    def test_items_published_at_the_same_time_keep_storage_order(self) -> None:
        same = [
            make_raw_item("اول", shortcode="P1", published_at=PUBLISHED),
            make_raw_item("دوم", shortcode="P2", published_at=PUBLISHED),
            make_raw_item("سوم", shortcode="P3", published_at=PUBLISHED),
        ]
        self.assertEqual(self.shortcodes(select_latest(same, 3)), ["P1", "P2", "P3"])

    def test_empty_input_selects_nothing(self) -> None:
        self.assertEqual(select_latest([], 5), ())


if __name__ == "__main__":
    unittest.main()
