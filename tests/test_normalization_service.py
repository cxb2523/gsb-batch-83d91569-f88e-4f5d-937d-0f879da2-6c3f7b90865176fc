import unittest
from dataclasses import fields, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from gatherradar.domain import EventCandidate, PlaceCandidate
from gatherradar.extraction import DiscoveryOutcome, DiscoveryStatus, DiscoveryService, RuleBasedDiscoveryProvider
from gatherradar.normalization import NormalizationService, NormalizationStatus
from gatherradar.orchestration.discovery_run import run_discovery
from gatherradar.orchestration.evidence_discovery_run import run_evidence_discovery
from gatherradar.orchestration.normalization_run import run_normalization
from test_normalization_temporal import RAW, SOURCE

EVENT = EventCandidate('candidate:1', RAW.id, True, title='عنوان', summary='خلاصه', category='workshop',
                       source_date_text='پنجشنبه ۲ مهر ۱۴۰۵ ساعت ۲۰:۳۰', price_text='۳۵۰ هزار تومان',
                       evidence_url=RAW.content_url, extraction_confidence=0.8)


class NormalizationServiceTests(unittest.TestCase):
    def test_source_fields_preserved_exactly(self):
        result = NormalizationService().normalize(EVENT, RAW, SOURCE)
        owned = {'start_date', 'end_date', 'start_time', 'end_time', 'starts_at', 'ends_at',
                 'timezone', 'date_precision', 'price_amount', 'currency',
                 'occurrences', 'schedule_kind', 'recurrence_rule'}
        for field in fields(EVENT):
            if field.name not in owned:
                self.assertEqual(getattr(EVENT, field.name), getattr(result.candidate, field.name))
        self.assertEqual(result.status, NormalizationStatus.NORMALIZED)
        self.assertIsNone(EVENT.starts_at)
        self.assertIsNone(EVENT.price_amount)
        self.assertEqual(result.candidate.price_amount, Decimal(350000))

    def test_place_only_price(self):
        place = PlaceCandidate('place:1', RAW.id, price_text='۱۰۰ هزار تومان', opening_hours_text='هر روز ساعت ۱۶')
        result = NormalizationService().normalize(place, RAW, SOURCE)
        self.assertIs(result.candidate, place)
        self.assertIsNone(result.temporal)
        self.assertEqual(result.price.price_amount, Decimal(100000))

    def test_relative_publisher_name_is_not_an_event_date(self):
        event = replace(EVENT, source_date_text='امروز')
        raw = replace(RAW, raw_text='ایونت گفتگو امروز ایونتز برای گفتگو ایجاد شد')
        result = NormalizationService().normalize(event, raw, SOURCE)
        self.assertIsNone(result.temporal.start_date)
        self.assertIn('ambiguous_relative_context', {d.code for d in result.diagnostics})

    def test_relative_standalone_and_labelled_evidence(self):
        for text in ('امروز', 'زمان: امروز', 'عنوان\nتاریخ: امروز'):
            event = replace(EVENT, source_date_text='امروز')
            result = NormalizationService().normalize(event, replace(RAW, raw_text=text, published_at=RAW.captured_at), SOURCE)
            self.assertEqual(result.temporal.start_date, date(2026, 9, 24))

    def test_relative_uses_ocr_unit_not_unrelated_caption(self):
        event = replace(EVENT, source_date_text='فردا')
        outcome = DiscoveryOutcome(RAW.id, DiscoveryStatus.DISCOVERED, 'test', event=event, discovery_unit_id='unit:1')
        result, = run_normalization((outcome,), {RAW.id: replace(RAW, published_at=RAW.captured_at)}, {SOURCE.id: SOURCE}, unit_texts={'unit:1': 'زمان: فردا'})
        self.assertEqual(result.temporal.start_date, date(2026, 9, 25))
        result, = run_normalization((outcome,), {RAW.id: replace(RAW, raw_text='فردا')}, {SOURCE.id: SOURCE})
        self.assertIsNone(result.temporal.start_date)

    def test_mismatched_source_is_invalid(self):
        result = NormalizationService().normalize(EVENT, RAW, replace(SOURCE, id='other'))
        self.assertEqual(result.status, NormalizationStatus.INVALID)
        self.assertIsNone(result.temporal)

    def test_mismatched_raw_is_invalid(self):
        result = NormalizationService().normalize(replace(EVENT, raw_item_id='other'), RAW, SOURCE)
        self.assertEqual(result.status, NormalizationStatus.INVALID)

    def test_invalid_temporal_does_not_discard_price(self):
        result = NormalizationService().normalize(replace(EVENT, source_date_text='۳۲ مهر ۱۴۰۵'), RAW, SOURCE)
        self.assertEqual(result.status, NormalizationStatus.INVALID)
        self.assertEqual(result.price.price_amount, Decimal(350000))

    def test_unknown_is_not_invalid(self):
        result = NormalizationService().normalize(replace(EVENT, source_date_text=None, price_text=None), RAW, SOURCE)
        self.assertEqual(result.status, NormalizationStatus.UNRESOLVED)

    def test_repeated_normalization_and_updated_copy_equal(self):
        service = NormalizationService()
        for event in (EVENT, replace(EVENT, source_date_text='فردا'), replace(EVENT, source_date_text='۲ مهر')):
            first = service.normalize(event, RAW, SOURCE)
            self.assertEqual(first, service.normalize(event, RAW, SOURCE))
            self.assertEqual(first, service.normalize(first.candidate, RAW, SOURCE))

    def test_stale_normalized_values_are_replaced(self):
        candidate = replace(EVENT, source_date_text=None, price_text=None,
                            starts_at=datetime(2000, 1, 1, tzinfo=timezone.utc), price_amount=999)
        result = NormalizationService().normalize(candidate, RAW, SOURCE)
        self.assertIsNone(result.candidate.starts_at)
        self.assertIsNone(result.candidate.price_amount)

    def test_batch_isolates_failure_and_redacts_error(self):
        discovery = DiscoveryOutcome(RAW.id, DiscoveryStatus.DISCOVERED, 'test', event=EVENT)
        normalizer = Mock(spec=NormalizationService)
        normalizer.normalize.side_effect = [RuntimeError('private-token'), NormalizationService().normalize(EVENT, RAW, SOURCE)]
        results = run_normalization((discovery, discovery), {RAW.id: RAW}, {SOURCE.id: SOURCE}, service=normalizer)
        self.assertEqual(results[0].status, NormalizationStatus.INVALID)
        self.assertNotIn('private-token', repr(results[0]))
        self.assertEqual(results[1].status, NormalizationStatus.NORMALIZED)

    def test_batch_missing_context(self):
        discovery = DiscoveryOutcome(RAW.id, DiscoveryStatus.DISCOVERED, 'test', event=EVENT)
        result, = run_normalization((discovery,), {}, {})
        self.assertEqual(result.status, NormalizationStatus.INVALID)

    def test_batch_no_candidate(self):
        discovery = DiscoveryOutcome(RAW.id, DiscoveryStatus.SKIPPED, 'test')
        self.assertEqual(run_normalization((discovery,), {}, {}), ())

    def test_orchestration_retains_exact_reference_for_both_routes(self):
        raw = replace(RAW, raw_text='کارگاه سفالگری\n۲ مهر ۱۴۰۵ ساعت ۱۸\nورودی ۳۵۰ هزار تومان')
        service = DiscoveryService(RuleBasedDiscoveryProvider())
        for summary in (run_discovery(iter((raw,)), service), run_evidence_discovery(iter((raw,)), (), service)):
            self.assertEqual(summary.raw_items, (raw,))
            self.assertIsNone(summary.event_candidates[0].starts_at)
            results = run_normalization(summary.outcomes, {raw.id: raw}, {SOURCE.id: SOURCE})
            self.assertEqual(results[0].temporal.start_date, date(2026, 9, 24))
