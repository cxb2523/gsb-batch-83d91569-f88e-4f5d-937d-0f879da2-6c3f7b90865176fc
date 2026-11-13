import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gatherradar.collectors.base import CollectionResult
from gatherradar.config import load_sources
from gatherradar.domain import RawItem, compute_content_hash, SourceType
from gatherradar.orchestration.canonicalization_run import run_canonical_review
from gatherradar.orchestration.collection_run import run_instagram_collection, instagram_output_path
from gatherradar.orchestration.evidence_run import run_instagram_evidence
from gatherradar.orchestration.refresh import RefreshService
from gatherradar.orchestration.website_run import run_website_collection, website_output_path
from gatherradar.sheets.client import SheetsError
from gatherradar.sheets.schema import EVENT_HEADERS, RUNS
from gatherradar.storage import JsonlRawItemStore
from sheets_fakes import RepositoryCase, OfflineCase, STAMP
from test_evidence_run_cli import FakeAcquirer, FakeOcr

from repo_config import FIXTURE_CONFIG as CONFIG
TEXT = 'کارگاه «سفال مهتاب»\n۵ مهر ۱۴۰۵ ساعت ۱۸\nمکان: گالری آبی\nشهر: تهران\nورودی ۳۰۰ تومان'


def raw(source, key='one', text=TEXT, captured=STAMP):
    link = 'https://example.test/events/' + key
    return RawItem(source.id + ':' + key, source.id, source.source_type, key, 'webpage', link, text, captured,
        content_hash=compute_content_hash(raw_text=text, published_at=None, content_url=link))


class MembershipTests(OfflineCase):
    def check_collection(self, source_id, collect):
        source = next(s for s in load_sources(CONFIG) if s.id == source_id)
        initial = raw(source)
        changed = raw(source, text=TEXT + '\nupdated')
        collector = Mock()
        collector.collect.side_effect = [CollectionResult(source.id, (i,)) for i in (initial, initial, changed)]
        runs = [collect(source.id, config_path=CONFIG, data_dir=self.directory, collector=collector) for _ in range(3)]
        self.assertEqual([r.observed_item_ids for r in runs], [(initial.id,)] * 3)
        self.assertEqual((runs[0].new, runs[1].already_existing, runs[2].changed), (1, 1, 1))
        self.assertEqual(runs[2].observed_items, (changed,))

    def test_website_new_existing_and_changed_membership(self):
        self.check_collection('davvvat_website', run_website_collection)

    def test_instagram_new_existing_and_changed_membership(self):
        self.check_collection('davvvat_instagram', run_instagram_collection)

    def test_current_website_selection_ignores_stale_first_seen_order(self):
        source = next(s for s in load_sources(CONFIG) if s.id == 'davvvat_website')
        stale, current = raw(source, 'stale'), raw(source, 'current')
        path = website_output_path(source, self.directory)
        JsonlRawItemStore(path).append_new((stale, current))
        before = path.read_bytes()
        review = run_canonical_review((source.id,), config_path=CONFIG, data_dir=self.directory,
            limit=1, observed_items={source.id: (current,)})
        self.assertEqual({c.raw_item.id for c in review.result.contexts}, {current.id})
        self.assertEqual(path.read_bytes(), before)

    def test_unchanged_item_uses_current_capture_time_without_appending(self):
        source = next(s for s in load_sources(CONFIG) if s.id == 'davvvat_website')
        old = raw(source, captured=STAMP - timedelta(days=1))
        current = replace(old, captured_at=STAMP)
        path = website_output_path(source, self.directory)
        JsonlRawItemStore(path).append_new((old,))
        JsonlRawItemStore(path).append_new((current,))
        review = run_canonical_review((source.id,), config_path=CONFIG, data_dir=self.directory,
            observed_items={source.id: (current,)})
        self.assertEqual(review.result.events[0].last_seen_at, STAMP)
        self.assertEqual(review.result.events[0].first_seen_at, old.captured_at)

    def test_evidence_only_selected_members_and_ocr_cache(self):
        source = next(s for s in load_sources(CONFIG) if s.id == 'davvvat_instagram')
        stale, current = raw(source, 'stale'), raw(source, 'current')
        JsonlRawItemStore(instagram_output_path(source, self.directory)).append_new((stale, current))
        provider = FakeOcr()
        provider.version = '1'
        for _ in range(2):
            summary = run_instagram_evidence(source.id, config_path=CONFIG, data_dir=self.directory,
                observed_items=(current,), limit=1, acquirer=FakeAcquirer(), ocr_provider=provider)
        self.assertEqual(summary.raw_items, 1)
        self.assertEqual(summary.new_evidence, 0)
        self.assertEqual(len(provider.paths), 1)

    def test_ocr_version_change_invalidates_cache(self):
        source = next(s for s in load_sources(CONFIG) if s.id == 'davvvat_instagram')
        current = raw(source)
        provider = FakeOcr()
        for version in ('1', '2'):
            provider.version = version
            run_instagram_evidence(source.id, config_path=CONFIG, data_dir=self.directory,
                observed_items=(current,), acquirer=FakeAcquirer(), ocr_provider=provider)
        self.assertEqual(len(provider.paths), 2)


class RefreshTests(RepositoryCase):
    def setUp(self):
        super().setUp()
        self.source = next(s for s in load_sources(CONFIG) if s.id == 'davvvat_website')
        self.current = raw(self.source)
        self.collector = Mock()
        self.collector.collect.return_value = CollectionResult(self.source.id, (self.current,))
        self.website = Mock(side_effect=lambda source_id, **kwargs:
            run_website_collection(source_id, collector=self.collector, **kwargs))
        self.instagram = Mock(side_effect=RuntimeError('secret session content'))
        self.evidence = Mock(return_value=SimpleNamespace(failures=(), malformed=()))
        self.service = RefreshService(self.repo, website_collect=self.website,
            instagram_collect=self.instagram, acquire_evidence=self.evidence, now=lambda: STAMP)

    def run_refresh(self, **kwargs):
        ids = kwargs.pop('source_ids', (self.source.id,))
        return self.service.run(ids, config_path=CONFIG, data_dir=self.directory, run_id=kwargs.pop('run_id', 'refresh_one'), **kwargs)

    def test_full_pipeline_real_discovery_normalization_and_fake_sheets(self):
        result = self.run_refresh()
        self.assertEqual(result.snapshot.status, 'success')
        self.assertEqual(result.snapshot.events, 1)
        row = self.client.values(result.snapshot.event_tab)[1]
        self.assertEqual(row[EVENT_HEADERS.index('start_date_iso')], '2026-09-27')
        self.assertEqual(result.sources[0].observed_item_ids, (self.current.id,))
        manifest = json.loads((self.directory / 'runs/refresh_one.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['status'], 'success')
        self.assertNotIn('raw_text', str(manifest))

    def test_one_failed_source_does_not_destroy_success(self):
        result = self.run_refresh(source_ids=(self.source.id, 'davvvat_instagram'))
        self.assertEqual(result.snapshot.status, 'partial')
        self.assertEqual(result.snapshot.events, 1)
        self.assertEqual(sum(r.status == 'failed' for r in result.sources), 1)
        self.assertNotIn('secret session', str(result))

    def test_google_validation_precedes_collection(self):
        with patch.object(self.repo, 'find_run', side_effect=SheetsError('not reachable')):
            with self.assertRaises(SheetsError):
                self.run_refresh()
        self.website.assert_not_called()

    def test_current_run_does_not_include_stale_storage(self):
        stale = raw(self.source, 'stale', TEXT.replace('۵ مهر', '۶ مهر'))
        JsonlRawItemStore(website_output_path(self.source, self.directory)).append_new((stale,))
        result = self.run_refresh(limit=1)
        self.assertEqual(result.snapshot.events, 1)
        raw_ids = json.loads(self.client.values(result.snapshot.event_tab)[1][EVENT_HEADERS.index('source_item_ids')])
        self.assertEqual(raw_ids, [self.current.id])

    def test_offline_sync_cannot_collect_or_modify_raw_evidence(self):
        store = JsonlRawItemStore(website_output_path(self.source, self.directory))
        store.append_new((self.current,))
        before = store.path.read_bytes()
        with patch.object(JsonlRawItemStore, 'append_new', side_effect=AssertionError('unexpected append')):
            result = self.run_refresh(collect=False)
        self.assertEqual(result.snapshot.events, 1)
        self.website.assert_not_called()
        self.instagram.assert_not_called()
        self.evidence.assert_not_called()
        self.assertEqual(store.path.read_bytes(), before)

    def test_completed_retry_does_not_recollect(self):
        self.run_refresh()
        second = self.run_refresh()
        self.assertTrue(second.snapshot.already_synced)
        self.assertEqual(self.website.call_count, 1)

    def test_invalid_options_fail_before_google(self):
        with patch.object(self.repo, 'find_run') as google:
            for kwargs in ({'days': 91}, {'limit': 0}, {'run_id': '../escape'}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    self.run_refresh(**kwargs)
        google.assert_not_called()

    def test_instagram_evidence_receives_exact_current_items(self):
        source = next(s for s in load_sources(CONFIG) if s.id == 'davvvat_instagram')
        item = raw(source)
        collector = Mock()
        collector.collect.return_value = CollectionResult(source.id, (item,))
        self.service.instagram_collect = lambda source_id, **kwargs: run_instagram_collection(source_id, collector=collector, **kwargs)
        result = self.run_refresh(source_ids=(source.id,))
        self.assertEqual(self.evidence.call_args.kwargs['observed_items'], (item,))
        self.assertEqual(result.snapshot.events, 1)

    def test_caption_fallback_on_evidence_failure(self):
        source = next(s for s in load_sources(CONFIG) if s.id == 'davvvat_instagram')
        item = raw(source)
        collector = Mock()
        collector.collect.return_value = CollectionResult(source.id, (item,))
        self.service.instagram_collect = lambda source_id, **kwargs: run_instagram_collection(source_id, collector=collector, **kwargs)
        self.evidence.side_effect = RuntimeError('private media state')
        result = self.run_refresh(source_ids=(source.id,))
        self.assertEqual(result.snapshot.status, 'partial')
        self.assertEqual(result.snapshot.events, 1)
        self.assertNotIn('private media state', str(result))

    def test_media_diagnostics_survive_manifest_and_analysis(self):
        source = next(s for s in load_sources(CONFIG) if s.id == 'davvvat_instagram')
        item = raw(source)
        collector = Mock()
        collector.collect.return_value = CollectionResult(source.id, (item,))
        self.service.instagram_collect = lambda source_id, **kwargs: run_instagram_collection(source_id, collector=collector, **kwargs)
        detail = dict(source_id=source.id, raw_item_id=item.id, slide_index=2,
                      category='visual_not_ready', retry_count=2)
        self.evidence.return_value = SimpleNamespace(failures=('private detail intentionally not logged',),
            malformed=(), capture_diagnostics=(detail,), ocr_failed=0)
        result = self.run_refresh(source_ids=(source.id,))
        self.assertEqual(result.sources[0].media_diagnostics, (detail,))
        manifest = json.loads((Path(self.directory)/'runs/refresh_one.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['sources'][0]['media_diagnostics'], [detail])
        self.assertNotIn('private detail', str(manifest))

    def test_skip_evidence_never_acquires(self):
        self.run_refresh(skip_instagram_evidence=True)
        self.evidence.assert_not_called()

    def test_all_sources_failed_records_failed_run_without_tab(self):
        result = self.run_refresh(source_ids=('davvvat_instagram',))
        self.assertEqual(result.snapshot.status, 'failed')
        self.assertEqual(result.snapshot.event_tab, '')
        self.assertEqual(len(self.client.values(RUNS)), 2)
