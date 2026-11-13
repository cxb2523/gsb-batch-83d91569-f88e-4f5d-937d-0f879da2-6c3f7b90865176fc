"""The owner's one-run acceptance bundle (GR-EXCEL-CLOSURE-20261029, R01).

Builds an isolated run directory from synthetic pipeline output, then checks that
the bundle validates the workbook against the run, maps tracked cases to their
fresh outcomes, indexes stored OCR readings by recorded IDs, and leaves out the
database, absolute local paths and signed media URLs.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from gatherradar.cli import main
from gatherradar.domain import EvidenceFragment, EvidenceKind, MediaKind
from gatherradar.orchestration.acceptance import build_bundle
from gatherradar.orchestration.collection_run import find_source, instagram_output_path
from gatherradar.orchestration.evidence_paths import instagram_evidence_output_path
from gatherradar.review.serialization import review_window
from gatherradar.review.workspace import local_workspace
from gatherradar.storage import JsonlEvidenceStore, JsonlRawItemStore, MediaArtifactStore
from gatherradar.storage.sqlite_repository import SqliteCanonicalRepository
from test_evidence_run_cli import CONFIG, item
from test_jabama_session_pipeline import collected, pipeline
from test_jabama_session_schema import page
from test_jabama_timeslots import ONE
from test_ocr_fallback import GARBLED

STARTED = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
SIGNED = 'https://scontent.cdninstagram.com/v/t51/private.jpg?oh=SIGNATURE&oe=1'


class AcceptanceBundleTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.data = self.root / 'data'
        self.run_dir = self.data / 'qa-final-test'
        self.run_dir.mkdir(parents=True)
        _, result = pipeline(collected(page([ONE])))
        with SqliteCanonicalRepository(self.run_dir / 'state.sqlite3') as repo:
            repo.sync(result, review_window(result.events, STARTED), run_id='run-accept', started_at=STARTED,
                      finished_at=STARTED, days=14, review_timezone='Asia/Tehran', source_count=2)
            local_workspace(repo, self.run_dir / 'GatherRadar.xlsx', self.run_dir / 'exports').export('run-accept')
        # One tracked Instagram item with stored readings: a garbled one and a usable one.
        source = find_source('davvvat_instagram', CONFIG)
        raw = item()
        JsonlRawItemStore(instagram_output_path(source, self.data)).append_new([raw])
        artifact = MediaArtifactStore(self.data, 'instagram', source.username).write(raw, MediaKind.IMAGE, b'png').artifact
        readings = [EvidenceFragment.create(raw_item_id=raw.id, kind=EvidenceKind.IMAGE_OCR, text=text,
                                            source_url=SIGNED, local_asset_path=artifact.local_path,
                                            asset_hash=artifact.asset_hash, extraction_engine=engine,
                                            extraction_version='1', extraction_config='c')
                    for engine, text in (('easyocr', 'کارگاه سفال'), ('tesseract', GARBLED))]
        JsonlEvidenceStore(instagram_evidence_output_path(source, self.data)).append_new(readings)
        (self.data / 'runs').mkdir()
        (self.data / 'runs' / 'run-accept.json').write_text(json.dumps({
            'run_id': 'run-accept',
            'sources': [{'source_id': 'davvvat_instagram', 'status': 'success', 'observed_item_ids': [raw.id,
                         'instagram:davvvat:NOTEVENT']}],
            'source_funnel': [{'source_id': 'davvvat_instagram', 'raw_items_selected': 2, 'investigations': [
                {'raw_item_id': 'instagram:davvvat:NOTEVENT', 'reason': 'non_event: product_promotion'}]}],
        }), encoding='utf-8')
        self.cases = self.root / 'cases.json'
        self.cases.write_text(json.dumps({'cases': [
            {'id': 'PASS', 'locators': ['/events/demo-event'], 'expect': {'occurrences_min': 2}},
            {'id': 'CHECK', 'locators': ['/events/demo-event'], 'expect': {'venue_name': 'جای دیگر'}},
            {'id': 'ABSENT', 'locators': ['/p/MISSING/'], 'expect': {}},
            {'id': 'NOTEVENT', 'locators': ['/p/NOTEVENT/'], 'expect': {}},
            {'id': 'MEDIA', 'locators': ['/p/ABC/', '/p/GONE/'], 'expect': {}, 'media': True},
        ]}), encoding='utf-8')

    def bundle(self, **options):
        return build_bundle(self.run_dir, data_dir=self.data, config_path=CONFIG, cases_path=self.cases, **options)

    def test_workbook_is_validated_against_the_run(self):
        _, report = self.bundle()
        workbook = report['workbook']
        self.assertTrue(workbook['ok'], workbook['checks'])
        self.assertEqual((workbook['main_rows'], workbook['schedule_review_rows']), (1, 0))
        self.assertEqual(workbook['core_field_fill']['جلسه بعدی'], '1/1')

    def test_cases_map_to_fresh_outcomes(self):
        _, report = self.bundle()
        status = {case['id']: [e['status'] for e in case['entries']] for case in report['cases']}
        self.assertEqual(status['PASS'], ['PASS'])
        self.assertEqual(status['CHECK'], ['CHECK'])
        self.assertEqual(status['ABSENT'], ['NOT_IN_RUN'])
        notevent = next(c for c in report['cases'] if c['id'] == 'NOTEVENT')['entries'][0]
        self.assertEqual((notevent['outcome'], notevent['investigations']),
                         ('not_an_event_in_run', ['non_event: product_promotion']))

    def test_evidence_index_uses_recorded_ids_and_quality_policy(self):
        _, report = self.bundle()
        stored, gap = report['evidence_index']
        self.assertEqual(stored['raw_item_id'], 'instagram:davvvat:ABC')
        readings = {r['engine']: r for r in stored['readings']}
        self.assertTrue(readings['easyocr']['selected'])  # the usable reading, though older
        self.assertEqual(readings['tesseract']['quality'], 'noisy_lines')
        self.assertEqual((gap['raw_item_id'], gap['status']), ('GONE', 'EVIDENCE_GAP'))

    def test_bundle_excludes_database_paths_and_signed_urls(self):
        archive, report = self.bundle()
        names = zipfile.ZipFile(archive).namelist()
        self.assertIn('GatherRadar.xlsx', names)
        self.assertIn('acceptance-report.json', names)
        self.assertFalse(any(name.endswith(('.sqlite3', '.jsonl')) or name.startswith('media/') for name in names))
        text = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(str(self.root), text)
        self.assertNotIn('SIGNATURE', text)

    def test_media_copies_only_on_request_and_bounded(self):
        archive, report = self.bundle(include_media=True, max_media=1)
        media = [n for n in zipfile.ZipFile(archive).namelist() if n.startswith('media/')]
        self.assertEqual(len(media), 1)

    def add_untracked_excluded_carousel(self):
        """A title-excluded carousel outside the tracked list, with three slides."""
        from dataclasses import replace
        source = find_source('davvvat_instagram', CONFIG)
        raw = replace(item(), id='instagram:davvvat:UNTRACKED', external_id='UNTRACKED',
                      content_url='https://www.instagram.com/p/UNTRACKED/', raw_text='کپشن عمومی پست')
        JsonlRawItemStore(instagram_output_path(source, self.data)).append_new([raw])
        store = MediaArtifactStore(self.data, 'instagram', source.username)
        readings = []
        for index in range(3):
            artifact = store.write(raw, MediaKind.CAROUSEL_SLIDE, f'slide{index}'.encode(), slide_index=index).artifact
            readings.append(EvidenceFragment.create(
                raw_item_id=raw.id, kind=EvidenceKind.CAROUSEL_SLIDE_OCR, text=f'کارگاه شماره {index}',
                local_asset_path=artifact.local_path, asset_hash=artifact.asset_hash, slide_index=index,
                extraction_engine='easyocr', extraction_version='1', extraction_config='c'))
        JsonlEvidenceStore(instagram_evidence_output_path(source, self.data)).append_new(readings)
        manifest_path = self.data / 'runs' / 'run-accept.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['sources'][0]['observed_item_ids'].append(raw.id)
        manifest['source_funnel'][0]['investigations'].append(
            {'raw_item_id': raw.id, 'reason': 'title_resolution_failed'})
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')

    def test_title_excluded_items_are_indexed_with_their_caption(self):
        self.add_untracked_excluded_carousel()
        _, report = self.bundle()
        entry = next(e for e in report['evidence_index'] if e['raw_item_id'] == 'instagram:davvvat:UNTRACKED')
        self.assertEqual(entry['caption_excerpt'], 'کپشن عمومی پست')
        self.assertEqual(len(entry['readings']), 3)
        # Non-event investigations are not indexed as media cases.
        self.assertFalse(any(e['raw_item_id'].endswith('NOTEVENT') for e in report['evidence_index']))

    def test_media_budget_is_shared_round_robin_across_items(self):
        self.add_untracked_excluded_carousel()
        archive, report = self.bundle(include_media=True, max_media=2)
        bundled = {e['raw_item_id']: sum(1 for r in e.get('readings', ()) if r.get('bundled_media'))
                   for e in report['evidence_index'] if e.get('readings')}
        self.assertEqual(bundled, {'instagram:davvvat:ABC': 1, 'instagram:davvvat:UNTRACKED': 1})
        names = zipfile.ZipFile(archive).namelist()
        self.assertTrue(all('\\' not in name for name in names))  # portable entry names

    def test_extra_log_files_join_the_bundle(self):
        log = self.root / 'refresh-output.txt'
        log.write_text('Collection: success', encoding='utf-8')
        archive, _ = self.bundle(extra_files=(log, self.root / 'missing.txt', self.run_dir / 'state.sqlite3'))
        names = zipfile.ZipFile(archive).namelist()
        self.assertIn('refresh-output.txt', names)
        self.assertNotIn('state.sqlite3', names)

    def test_cli_reports_workbook_status_and_bundle_path(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main(['acceptance', '--run-dir', str(self.run_dir), '--data-dir', str(self.data),
                         '--config', str(CONFIG), '--cases', str(self.cases)])
        self.assertEqual(code, 0)
        self.assertIn('Workbook: valid', stream.getvalue())
        self.assertIn('GatherRadar-review-bundle.zip', stream.getvalue())
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['acceptance', '--run-dir', str(self.root / 'missing')]), 2)


if __name__ == '__main__':
    unittest.main()
