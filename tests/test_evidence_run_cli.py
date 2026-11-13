import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from gatherradar.cli import build_parser, main
from gatherradar.collectors.base import SourceNotFoundError
from gatherradar.collectors.instagram_browser import BrowserSessionNotAuthenticatedError
from gatherradar.collectors.instagram_evidence import MediaCaptureResult
from gatherradar.domain import MediaKind, RawItem, SourceType
from gatherradar.ocr import OcrResult, OcrStatus
from gatherradar.orchestration.evidence_run import EvidenceRunSummary, run_instagram_evidence
from gatherradar.storage import JsonlEvidenceStore, JsonlRawItemStore
from gatherradar.orchestration.collection_run import instagram_output_path, find_source

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config' / 'sources.yaml'


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def item():
    return RawItem(
        id='instagram:davvvat:ABC', source_id='davvvat_instagram',
        source_type=SourceType.INSTAGRAM, external_id='ABC', content_type='image',
        content_url='https://www.instagram.com/p/ABC/', raw_text='caption',
        captured_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        content_hash='a' * 64,
    )


class FakeAcquirer:
    def acquire(self, items, source, store):
        artifact = store.write(items[0], MediaKind.IMAGE, b'image').artifact
        return MediaCaptureResult((artifact,))


class FakeOcr:
    name = 'fake'
    config = 'fas+eng'

    def __init__(self):
        self.validated = 0
        self.paths = []

    def validate(self):
        self.validated += 1

    def recognize(self, path):
        self.paths.append(path)
        return OcrResult(
            OcrStatus.SUCCEEDED, 'کارگاه\n', 'کارگاه', 'fake', '1', self.config
        )


class EvidenceRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name)
        source = find_source('davvvat_instagram', CONFIG)
        JsonlRawItemStore(instagram_output_path(source, self.data_dir)).append_new([item()])

    def run_evidence(self):
        provider = FakeOcr()
        summary = run_instagram_evidence(
            'davvvat_instagram', config_path=CONFIG, data_dir=self.data_dir,
            acquirer=FakeAcquirer(), ocr_provider=provider,
        )
        return summary, provider

    def test_fake_media_evidence_run_is_successful(self):
        summary, provider = self.run_evidence()
        self.assertEqual(summary.raw_items, 1)
        self.assertEqual(summary.image_assets, 1)
        self.assertEqual(summary.ocr_succeeded, 1)
        self.assertEqual(summary.new_evidence, 2)
        self.assertEqual(provider.validated, 1)
        self.assertTrue(summary.output_path.is_file())

    def test_unchanged_rerun_is_idempotent(self):
        first, _ = self.run_evidence()
        second, _ = self.run_evidence()
        self.assertEqual(first.new_evidence, 2)
        self.assertEqual(second.new_evidence, 0)
        self.assertEqual(second.existing_evidence, 2)

    def test_candidates_are_not_persisted(self):
        self.run_evidence()
        paths = [path.as_posix() for path in self.data_dir.rglob('*') if path.is_file()]
        self.assertFalse(any('candidate' in path for path in paths))

    def test_ocr_exception_is_persisted_safely_and_other_evidence_survives(self):
        class TwoArtifacts:
            def acquire(self, items, source, store):
                return MediaCaptureResult(tuple(
                    store.write(items[0], MediaKind.CAROUSEL_SLIDE, content,
                                slide_index=index).artifact
                    for index, content in enumerate((b'one', b'two'))
                ))

        provider = FakeOcr()
        good = OcrResult(OcrStatus.SUCCEEDED, 'text\n', 'text', 'fake', '1', 'fas+eng')
        with mock.patch.object(provider, 'recognize', side_effect=[
            RuntimeError('synthetic-private-detail'), good,
        ]):
            summary = run_instagram_evidence(
                'davvvat_instagram', config_path=CONFIG, data_dir=self.data_dir,
                acquirer=TwoArtifacts(), ocr_provider=provider,
            )
        self.assertEqual((summary.ocr_failed, summary.ocr_succeeded), (1, 1))
        self.assertEqual(summary.new_evidence, 3)
        self.assertNotIn('synthetic-private-detail', str(summary.failures))
        persisted = JsonlEvidenceStore(summary.output_path).read()
        self.assertEqual(len(persisted.fragments), 3)
        self.assertNotIn('synthetic-private-detail', summary.output_path.read_text(encoding='utf-8'))

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(SourceNotFoundError):
            run_instagram_evidence(
                'unknown', config_path=CONFIG, data_dir=self.data_dir,
                acquirer=FakeAcquirer(), ocr_provider=FakeOcr(),
            )


class EvidenceCliTests(unittest.TestCase):
    def test_parser_defaults_and_bounds(self):
        args = build_parser().parse_args(['evidence', 'instagram', 'davvvat_instagram'])
        self.assertEqual(args.limit, 5)
        self.assertEqual(args.max_carousel_slides, 20)
        self.assertEqual(args.max_reel_frames, 6)

    def test_non_positive_limit_is_rejected(self):
        code, _, err = run_main(
            ['evidence', 'instagram', 'davvvat_instagram', '--limit', '0']
        )
        self.assertEqual(code, 2)
        self.assertIn('--limit', err)

    def test_missing_auth_is_reported_without_traceback(self):
        error = BrowserSessionNotAuthenticatedError('run auth instagram')
        with mock.patch('gatherradar.cli.run_instagram_evidence', side_effect=error):
            code, _, err = run_main(['evidence', 'instagram', 'davvvat_instagram'])
        self.assertEqual(code, 1)
        self.assertIn('auth instagram', err)
        self.assertNotIn('Traceback', err)

    def test_successful_summary_is_useful(self):
        source = find_source('davvvat_instagram', CONFIG)
        summary = EvidenceRunSummary(
            'run', source, 1, 1, 0, 0, 1, 0, 0, 2, 0,
            Path('data/evidence/instagram/davvvat.jsonl'),
        )
        with mock.patch('gatherradar.cli.run_instagram_evidence', return_value=summary):
            code, out, _ = run_main(['evidence', 'instagram', 'davvvat_instagram'])
        self.assertEqual(code, 0)
        self.assertIn('GatherRadar media evidence run', out)
        self.assertIn('New evidence: 2', out)
        self.assertIn('No semantic candidates were persisted.', out)


if __name__ == '__main__':
    unittest.main()
