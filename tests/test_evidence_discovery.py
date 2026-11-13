import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from discovery_fakes import FixedProvider, PERSIAN_EVENT_FACTS, make_raw_item, make_source
from test_extract_cli import CONFIG, PUBLISHED_AT, run_main, write_store
from test_grouping import fragment
from gatherradar.cli import build_parser, format_evidence_discovery_summary
from gatherradar.domain import DiscoveryType
from gatherradar.extraction import DiscoveryService, RuleBasedDiscoveryProvider
from gatherradar.grouping import ConservativeGrouping
from gatherradar.orchestration.evidence_discovery_run import (
    run_evidence_discovery, run_instagram_evidence_discovery,
)
from gatherradar.storage import JsonlEvidenceStore


class EvidenceDiscoveryTests(unittest.TestCase):
    def run_items(self, items, history=(), **kwargs):
        return run_evidence_discovery(items, history, DiscoveryService(RuleBasedDiscoveryProvider()), **kwargs)

    def poster_carousel(self):
        path = Path(__file__).parent / 'fixtures' / 'evidence_grouping' / 'persian_workshop_carousel.json'
        fixture = json.loads(path.read_text(encoding='utf-8'))
        item = replace(make_raw_item('', shortcode='SYNTHETIC_CAROUSEL'), content_type='carousel')
        parts = tuple(fragment(item, slide['text'], slide=slide['slide_index'])
                      for slide in fixture['slides'])
        return item, parts

    def test_persian_poster_carousel_groups_and_discovers_with_stable_provenance(self):
        item, parts = self.poster_carousel()
        service = DiscoveryService(RuleBasedDiscoveryProvider())
        # Neither the title panel nor the details panel independently announces
        # enough facts for Event classification. Grouping needs their roles.
        self.assertEqual([service.discover(replace(item, raw_text=part.text)).discovery_type
                          for part in parts], [DiscoveryType.OTHER, DiscoveryType.OTHER])
        first = self.run_items((item,), parts)
        again = self.run_items((item,), parts)
        self.assertEqual((first.observed, first.unit_count, first.events, first.failed), (1, 1, 1, 0))
        unit, = first.items[0].units
        self.assertEqual(unit.fragments, parts)
        self.assertEqual([part.slide_index for part in unit.fragments], [0, 1])
        self.assertEqual(unit.text, '\n'.join(part.text for part in parts))
        self.assertEqual(unit.unit_id, again.items[0].units[0].unit_id)
        self.assertEqual(first.items, again.items)
        candidate, = first.candidates
        self.assertEqual(candidate.candidate_id, again.candidates[0].candidate_id)
        self.assertEqual(first.outcomes[0].discovery_unit_id, unit.unit_id)
        self.assertEqual(candidate.raw_item_id, item.id)
        self.assertEqual(candidate.evidence_url, item.content_url)
        self.assertEqual(candidate.title, 'کارگاه نقش و خاک')
        self.assertEqual(candidate.source_title, 'کارگاه «نقش و خاک»')
        self.assertEqual(candidate.source_date_text, 'جمعه ۲۱ شهریور\nساعت ۱۶ تا ۱۹')
        self.assertEqual(candidate.address, 'تهران، خیابان نمونه، پلاک ۱۲')
        self.assertEqual(candidate.city, 'تهران')
        self.assertEqual(candidate.price_text, '۳۵۰ هزار تومان')
        self.assertEqual(candidate.registration_url, 'https://example.test/r/123')
        for name in ('starts_at', 'ends_at', 'price_amount', 'currency'):
            self.assertIsNone(getattr(candidate, name))
        self.assertIn('slide 0 + slide 1', format_evidence_discovery_summary(first))

    def test_persian_poster_details_do_not_attach_across_competing_anchor_or_gap(self):
        item, parts = self.poster_carousel()
        variants = (
            fragment(item, 'کنسرت «آوای باران»\n' + parts[1].text, slide=1),
            fragment(item, 'داستان تازه‌ای در راه است\n' + parts[1].text, slide=1),
            fragment(item, parts[1].text, slide=2),
        )
        for second in variants:
            with self.subTest(text=second.text, slide=second.slide_index):
                result = self.run_items((item,), (parts[0], second))
                self.assertEqual([unit.fragments for unit in result.items[0].units],
                                 [(parts[0],), (second,)])
                self.assertIsNone(result.outcomes[0].candidate)
                self.assertNotIn(parts[1].text, result.items[0].units[0].text)

    def test_zero_one_and_several_outcomes_per_raw_item(self):
        empty = make_raw_item('', shortcode='EMPTY')
        one = make_raw_item('کارگاه سفالگری\nجمعه', shortcode='ONE')
        many = make_raw_item('', shortcode='MANY')
        parts = (fragment(many, 'کنسرت باران\nجمعه', slide=0),
                 fragment(many, 'کارگاه سفالگری\nشنبه', slide=1))
        result = self.run_items((empty, one, many), parts)
        self.assertEqual([len(item.outcomes) for item in result.items], [0, 1, 2])
        self.assertEqual((result.observed, result.unit_count, result.events), (3, 3, 3))
        self.assertEqual(result.items[0].reason, 'no_meaningful_evidence')

    def test_candidates_have_distinct_stable_provider_independent_identities(self):
        item = make_raw_item('')
        parts = (fragment(item, 'کنسرت باران\nجمعه', slide=0),
                 fragment(item, 'کارگاه سفالگری\nشنبه', slide=1))
        first = self.run_items((item,), parts)
        second = run_evidence_discovery((item,), parts, DiscoveryService(FixedProvider(PERSIAN_EVENT_FACTS)))
        ids = [candidate.candidate_id for candidate in first.candidates]
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(ids, [candidate.candidate_id for candidate in second.candidates])
        self.assertEqual(first.items, self.run_items((item,), parts).items)
        for unit, outcome in zip(first.items[0].units, first.outcomes):
            self.assertEqual(outcome.discovery_unit_id, unit.unit_id)
            self.assertEqual(outcome.candidate.raw_item_id, item.id)
            self.assertEqual(outcome.candidate.evidence_url, item.content_url)

    def test_normalization_owned_fields_remain_null(self):
        item = make_raw_item('کارگاه سفالگری')
        result = self.run_items((item,), (fragment(item, 'جمعه ۲۱ شهریور ساعت ۱۸\nورودی ۳۵۰ هزار تومان'),),
                                sources={item.source_id: make_source()})
        candidate, = result.candidates
        self.assertEqual(candidate.source_date_text, 'جمعه ۲۱ شهریور ساعت ۱۸')
        for name in ('starts_at', 'ends_at', 'price_amount', 'currency', 'city'):
            self.assertIsNone(getattr(candidate, name))

    def test_place_group_produces_place_candidate(self):
        item = make_raw_item('')
        result = self.run_items((item,), (fragment(item, 'گالری نگاه', slide=0),
                                         fragment(item, 'ساعات بازدید: هر روز از ۱۱ تا ۲۰', slide=1)))
        self.assertEqual(result.places, 1)
        self.assertEqual(result.outcomes[0].discovery_type, DiscoveryType.PLACE)

    def test_unexpected_unit_failure_does_not_discard_neighbours_or_leak_payload(self):
        item = make_raw_item('')
        parts = (fragment(item, 'کنسرت باران\nجمعه', slide=0),
                 fragment(item, 'کارگاه سفالگری\nشنبه', slide=1))
        provider = FixedProvider(PERSIAN_EVENT_FACTS)
        with mock.patch.object(provider, 'discover', side_effect=[RuntimeError('private-token'), PERSIAN_EVENT_FACTS]):
            result = run_evidence_discovery((item,), parts, DiscoveryService(provider))
        self.assertEqual((result.failed, result.events), (1, 1))
        self.assertNotIn('private-token', format_evidence_discovery_summary(result))

    def test_grouping_failure_is_isolated_per_item(self):
        items = (make_raw_item('bad', shortcode='BAD'), make_raw_item('concert Friday', shortcode='GOOD'))

        class FailFirst(ConservativeGrouping):
            def group(self, bundle):
                if bundle.raw_item_id == items[0].id:
                    raise ValueError('private-token')
                return super().group(bundle)

        result = self.run_items(items, strategy=FailFirst())
        self.assertEqual((result.observed, result.failed, result.events), (2, 1, 1))
        self.assertNotIn('private-token', format_evidence_discovery_summary(result))


class EvidenceExtractCliTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        self.raw_path = write_store(self.data, [('ONE', PUBLISHED_AT, 'کارگاه سفالگری')])
        self.evidence_path = self.data / 'evidence' / 'instagram' / 'davvvat.jsonl'
        self.item = make_raw_item('کارگاه سفالگری', shortcode='ONE')

    def extract(self, *extra):
        return run_main(['extract', 'instagram', 'davvvat_instagram', '--config', str(CONFIG),
                         '--data-dir', str(self.data), *extra])

    def store(self, parts):
        JsonlEvidenceStore(self.evidence_path).append_new(parts)

    def test_flag_is_explicit_and_default_is_caption_only(self):
        self.assertFalse(build_parser().parse_args(['extract', 'instagram', 'davvvat_instagram']).evidence)
        self.store([fragment(self.item, 'جمعه ساعت ۱۸')])
        with mock.patch('gatherradar.cli.run_instagram_evidence_discovery', side_effect=AssertionError('evidence read')):
            code, caption, _ = self.extract()
        self.assertEqual(code, 0)
        self.assertIn('Result: Other', caption)
        self.assertNotIn('DiscoveryUnits:', caption)
        code, evidence, _ = self.extract('--evidence')
        self.assertEqual(code, 0)
        self.assertIn('Result: Event', evidence)
        self.assertIn('caption + image_ocr', evidence)
        self.assertIn('Unit 1 (unit:', evidence)

    def test_no_network_browser_ocr_or_writes(self):
        self.store([fragment(self.item, 'جمعه ساعت ۱۸')])
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.data.rglob('*') if path.is_file()}
        with (
            mock.patch('socket.socket.connect', side_effect=AssertionError('network')),
            mock.patch('subprocess.Popen', side_effect=AssertionError('external process')),
            mock.patch('gatherradar.cli.run_instagram_collection', side_effect=AssertionError('collect')),
            mock.patch('gatherradar.cli.run_instagram_evidence', side_effect=AssertionError('acquire')),
            mock.patch('gatherradar.ocr.TesseractOcrProvider.validate', side_effect=AssertionError('OCR')),
            mock.patch('gatherradar.collectors.instagram_evidence.InstagramMediaEvidenceAcquirer.acquire',
                       side_effect=AssertionError('browser')),
        ):
            code, output, error = self.extract('--evidence')
        self.assertEqual((code, error), (0, ''))
        self.assertIn('Events: 1', output)
        after = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in self.data.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_malformed_evidence_is_isolated_and_not_rewritten(self):
        self.store([fragment(self.item, 'جمعه ساعت ۱۸')])
        with self.evidence_path.open('a', encoding='utf-8') as handle:
            handle.write('{not-json}\n{"kind": "private-token"}\n')
        before = self.evidence_path.read_bytes()
        code, output, _ = self.extract('--evidence')
        self.assertEqual(code, 0)
        self.assertIn('Unreadable stored lines:', output)
        self.assertIn('evidence: line 2:', output)
        self.assertIn('Events: 1', output)
        self.assertNotIn('private-token', output)
        self.assertEqual(before, self.evidence_path.read_bytes())

    def test_malformed_raw_record_diagnostic_does_not_echo_field_values(self):
        payload = json.loads(self.raw_path.read_text(encoding='utf-8').strip())
        payload['source_type'] = 'private-token'
        with self.raw_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(payload) + '\n')
        code, output, _ = self.extract('--evidence')
        self.assertEqual(code, 0)
        self.assertIn('raw: line 2: invalid record', output)
        self.assertNotIn('private-token', output)
        self.assertIn('Raw items: 1', output)

    def test_stored_reversion_limitation_is_explicit_not_invented_recency(self):
        first = fragment(self.item, 'جمعه ساعت ۱۸')
        second = fragment(self.item, 'شنبه ساعت ۲۰')
        self.store([first, second])
        self.store([first])  # Stage 4 suppresses the already-stored fragment id.
        result = run_instagram_evidence_discovery('davvvat_instagram', config_path=CONFIG, data_dir=self.data)
        self.assertEqual(result.items[0].units[0].fragments[-1], second)

    def test_latest_raw_selection_matches_existing_path_and_uses_current_caption(self):
        write_store(self.data, [('OLD', None, 'old text'), ('ONE', PUBLISHED_AT, 'stale caption'),
                                ('ONE', PUBLISHED_AT, 'کارگاه سفالگری')])
        self.store([fragment(self.item, 'جمعه ساعت ۱۸')])
        result = run_instagram_evidence_discovery('davvvat_instagram', config_path=CONFIG, data_dir=self.data, limit=1)
        self.assertEqual(result.observed, 1)
        self.assertEqual(result.items[0].raw_item_id, self.item.id)
        self.assertEqual(result.items[0].units[0].fragments[0].text, 'کارگاه سفالگری')

    def test_missing_evidence_store_uses_caption_without_creating_store(self):
        code, output, _ = self.extract('--evidence')
        self.assertEqual(code, 0)
        self.assertIn('DiscoveryUnits: 1', output)
        self.assertFalse(self.evidence_path.exists())

    def test_no_units_is_reported_as_skip_not_other_or_missing_raw_items(self):
        write_store(self.data, [('ONE', PUBLISHED_AT, '')])
        self.store([fragment(self.item, '', failure_reason='failed')])
        code, output, _ = self.extract('--evidence')
        self.assertEqual(code, 0)
        self.assertIn('no_meaningful_evidence', output)
        self.assertIn('Other: 0', output)
        self.assertIn('Raw items: 1', output)
        self.assertIn('DiscoveryUnits: 0', output)

    def test_review_labels_show_slides_and_frame_positions_without_paths_or_ocr_dump(self):
        self.store([fragment(self.item, 'opaque nonspecific wording', slide=0, local_asset_path='private/path.png'),
                    fragment(self.item, 'opaque frame wording', frame=1000)])
        _, output, _ = self.extract('--evidence')
        self.assertIn('slide 0', output)
        self.assertIn('frame 1000ms', output)
        self.assertNotIn('private/path', output)
        self.assertNotIn('opaque nonspecific', output)


if __name__ == '__main__':
    unittest.main()
