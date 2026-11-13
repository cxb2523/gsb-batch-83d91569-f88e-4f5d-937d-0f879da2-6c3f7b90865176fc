import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from gatherradar.cli import main
from gatherradar.config import load_sources
from gatherradar.deduplication import MatchKind
from gatherradar.domain import EvidenceFragment, EvidenceKind, DiscoveryUnit
from gatherradar.orchestration.canonicalization_run import run_canonical_review, identity_slot
from gatherradar.storage import JsonlEvidenceStore, JsonlRawItemStore
from gatherradar.storage.jsonl import raw_item_to_dict
from deduplication_fakes import context

from repo_config import FIXTURE_CONFIG as CONFIG
TEXT = 'کارگاه «سفال مهتاب»\n۲ مهر ۱۴۰۵ ساعت ۱۸\nمکان: گالری آبی\nشهر: تهران\nورودی ۳۰۰ تومان'


def snapshot(directory):
    return {str(p.relative_to(directory)): p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}


class CanonicalCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)

    def store(self, source_id, *, text=TEXT, key='1'):
        source = next(s for s in load_sources(CONFIG) if s.id == source_id)
        path = self.data / 'raw' / source.source_type.value / f'{source.username or source.id}.jsonl'
        raw = replace(context(key).raw_item, id=source.id + ':' + key, source_id=source.id,
                      source_type=source.source_type, raw_text=text)
        JsonlRawItemStore(path).append_new((raw,))
        return raw, path

    def run_cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(['canonicalize', '--config', str(CONFIG), '--data-dir', str(self.data), *arguments])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_multisource_offline_readonly_deterministic(self):
        self.store('davvvat_website')
        self.store('davvvat_instagram')
        before = snapshot(self.data)
        with ExitStack() as stack:
            for target in ('socket.socket.connect', 'subprocess.Popen', 'playwright.sync_api.sync_playwright',
                           'gatherradar.cli.run_instagram_collection', 'gatherradar.cli.run_website_collection',
                           'gatherradar.cli.run_instagram_evidence',
                           'gatherradar.storage.jsonl.JsonlRawItemStore.append_new',
                           'pathlib.Path.write_text', 'pathlib.Path.write_bytes'):
                stack.enter_context(patch(target, side_effect=AssertionError('forbidden side effect')))
            args = ('--source', 'davvvat_website', '--source', 'davvvat_instagram')
            first = self.run_cli(*args)
            second = self.run_cli(*args)
        self.assertEqual(first, second)
        self.assertEqual(first[0], 0, first)
        self.assertIn('auto groups: 1', first[1])
        self.assertIn('Auto-match:', first[1])
        self.assertIn('same_publisher', first[1])
        self.assertIn('caption_only', first[1])
        self.assertEqual(before, snapshot(self.data))

    def test_versioned_cross_publisher_fixture_keeps_next_session_separate(self):
        fixture = Path(__file__).parent / 'fixtures/canonicalization/cross_source_occurrences.json'
        for record in json.loads(fixture.read_text(encoding='utf-8'))['records']:
            self.store(record['source_id'], key=record['key'], text=record['text'])
        review = run_canonical_review(all_enabled=True, data_dir=self.data, config_path=CONFIG)
        self.assertEqual(len(review.result.events), 2)
        self.assertEqual(len(review.result.groups), 1)
        self.assertEqual(len(review.result.groups[0].candidate_ids), 3)
        self.assertEqual(sum(d.kind is MatchKind.DISTINCT for d in review.result.decisions), 3)

    def test_all_enabled_no_data_skipped(self):
        self.store('davvvat_website')
        code, output, _ = self.run_cli('--all-enabled')
        self.assertEqual(code, 0)
        self.assertIn('no_local_data', output)
        self.assertIn('Canonical events: 1', output)

    def test_evidence_requested_without_media_reports_fallback(self):
        self.store('davvvat_instagram')
        code, output, _ = self.run_cli('--source', 'davvvat_instagram', '--instagram-evidence')
        self.assertEqual(code, 0)
        self.assertIn('caption_fallback', output)

    def test_evidence_uses_stored_media_and_preserves_unit_identity(self):
        raw, _ = self.store('davvvat_instagram', text='')
        fragment = EvidenceFragment.create(raw_item_id=raw.id, kind=EvidenceKind.CAROUSEL_SLIDE_OCR,
            source_url=raw.content_url, text=TEXT, slide_index=1)
        JsonlEvidenceStore(self.data / 'evidence/instagram/davvvat.jsonl').append_new((fragment,))
        before = snapshot(self.data)
        review = run_canonical_review(('davvvat_instagram',), data_dir=self.data, config_path=CONFIG,
                                      instagram_evidence=True)
        self.assertEqual(review.sources[0].path_used, 'evidence_with_caption_fallback')
        self.assertEqual(len(review.result.events), 1)
        self.assertEqual(review.result.events[0].identity_anchor_slot, 'carousel_slide_ocr:1')
        self.assertEqual(before, snapshot(self.data))

    def test_media_slot_survives_content_edit_and_uses_position(self):
        for kind, position in ((EvidenceKind.CAROUSEL_SLIDE_OCR, {'slide_index': 3}),
                               (EvidenceKind.REEL_FRAME_OCR, {'frame_timestamp_ms': 2000})):
            a = EvidenceFragment.create(raw_item_id='raw:1', kind=kind, text=TEXT, **position)
            b = EvidenceFragment.create(raw_item_id='raw:1', kind=kind, text=TEXT + '\nتازه', **position)
            first, second = DiscoveryUnit.from_fragment(a), DiscoveryUnit.from_fragment(b)
            self.assertNotEqual(first.unit_id, second.unit_id)
            self.assertEqual(identity_slot(first), identity_slot(second))

    def test_first_seen_survives_raw_edit_from_same_snapshot(self):
        raw, path = self.store('davvvat_website')
        first = run_canonical_review(('davvvat_website',), data_dir=self.data, config_path=CONFIG)
        edited = replace(raw, captured_at=raw.captured_at + timedelta(days=10),
                         raw_text=TEXT + '\nخوش آمدید', content_hash='edited')
        JsonlRawItemStore(path).append_new((edited,))
        stored = JsonlRawItemStore(path).read_latest_items()
        self.assertEqual(dict(stored.first_seen_at)[raw.id], raw.captured_at)
        second = run_canonical_review(('davvvat_website',), data_dir=self.data, config_path=CONFIG)
        self.assertEqual(first.result.events[0].event_id, second.result.events[0].event_id)
        self.assertNotEqual(first.result.events[0].candidate_ids, second.result.events[0].candidate_ids)
        self.assertEqual(second.result.events[0].first_seen_at, raw.captured_at)
        self.assertEqual(second.result.events[0].last_seen_at, edited.captured_at)

    def test_malformed_and_foreign_records_reported_without_payload(self):
        raw, path = self.store('davvvat_website')
        with path.open('a', encoding='utf-8') as stream:
            stream.write('\n{"private-secret": bad}\n')
            stream.write(json.dumps(raw_item_to_dict(replace(raw, id='foreign', source_id='another'))) + '\n')
        code, output, _ = self.run_cli('--source', 'davvvat_website')
        self.assertEqual(code, 0)
        self.assertIn('invalid_record', output)
        self.assertIn('context_mismatch', output)
        self.assertNotIn('private-secret', output)
        self.assertIn('Canonical events: 1', output)

    def test_failure_isolated_per_source(self):
        self.store('davvvat_website')
        self.store('davvvat_instagram')
        original = JsonlRawItemStore.read_latest_items
        def read(store):
            if 'instagram' in str(store.path):
                raise OSError('private-secret')
            return original(store)
        with patch.object(JsonlRawItemStore, 'read_latest_items', read):
            code, output, _ = self.run_cli('--source', 'davvvat_instagram', '--source', 'davvvat_website')
        self.assertEqual(code, 1)
        self.assertIn('Canonical events: 1', output)
        self.assertIn('offline_source_failed', output)
        self.assertNotIn('private-secret', output)

    def test_unknown_source_and_invalid_limits(self):
        for args in (('--source', 'unknown'), ('--all-enabled', '--limit', '31'), ('--all-enabled', '--limit', '0')):
            self.assertNotEqual(self.run_cli(*args)[0], 0)

    def test_requires_explicit_exclusive_selection(self):
        for args in ((), ('--all-enabled', '--source', 'davvvat_website')):
            with self.assertRaises(SystemExit):
                self.run_cli(*args)

    def test_duplicate_source_selection_not_duplicated(self):
        self.store('davvvat_website')
        code, output, _ = self.run_cli('--source', 'davvvat_website', '--source', 'davvvat_website')
        self.assertEqual(code, 0)
        self.assertIn('Canonical events: 1', output)

    def test_normalization_failure_retained_and_review_fails(self):
        self.store('davvvat_website')
        with patch('gatherradar.normalization.NormalizationService.normalize', side_effect=RuntimeError('private-secret')):
            code, output, _ = self.run_cli('--source', 'davvvat_website')
        self.assertEqual(code, 1)
        self.assertIn('rejected contexts: 1', output)
        self.assertNotIn('private-secret', output)

    def test_explicit_disabled_source_is_allowed_offline(self):
        import yaml
        self.store('davvvat_website')
        config = self.data / 'sources.yaml'
        payload = yaml.safe_load(CONFIG.read_text(encoding='utf-8'))
        for source in payload['sources']:
            source['enabled'] = False
        config.write_text(yaml.safe_dump(payload), encoding='utf-8')
        all_result = run_canonical_review(all_enabled=True, config_path=config, data_dir=self.data)
        explicit = run_canonical_review(('davvvat_website',), config_path=config, data_dir=self.data)
        self.assertFalse(all_result.result.events)
        self.assertEqual(len(explicit.result.events), 1)
