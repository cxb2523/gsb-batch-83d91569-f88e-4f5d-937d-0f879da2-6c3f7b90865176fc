import io
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from gatherradar.cli import main
from gatherradar.config import load_sources
from gatherradar.storage.jsonl import JsonlRawItemStore
from test_normalization_temporal import RAW

from repo_config import FIXTURE_CONFIG as CONFIG
TEXT = 'کارگاه سفالگری\nپنجشنبه ۲ مهر ۱۴۰۵ ساعت ۲۰:۳۰\nورودی ۳۵۰ هزار تومان'


class NormalizationCliTests(unittest.TestCase):
    def _review(self, kind, source_id, evidence=False):
        source = next(s for s in load_sources(CONFIG) if s.id == source_id)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'raw' / kind / f'{source.username if kind == "instagram" else source.id}.jsonl'
            raw = replace(RAW, source_id=source.id, source_type=source.source_type, raw_text=TEXT)
            JsonlRawItemStore(path).append_new((raw,))
            before = {p.relative_to(directory): p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}
            argv = ['extract', kind, source_id, '--config', str(CONFIG), '--data-dir', directory]
            if evidence:
                argv.append('--evidence')
            with ExitStack() as stack:
                # Failing fakes prove normalized review never acquires or persists data.
                for target in ('socket.socket.connect', 'gatherradar.cli.run_instagram_collection',
                               'gatherradar.cli.run_website_collection', 'gatherradar.cli.run_instagram_evidence',
                               'playwright.sync_api.sync_playwright', 'subprocess.Popen',
                               'gatherradar.storage.jsonl.JsonlRawItemStore.append_new'):
                    stack.enter_context(patch(target, side_effect=AssertionError('forbidden side effect')))
                stack.enter_context(patch('uuid.uuid4', return_value=type('ID', (), {'hex': 'fixed-run-id'})()))
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(main(argv), 0)
                default = out.getvalue()
                self.assertNotIn('Normalization review', default)
                out = io.StringIO()
                with redirect_stdout(out):
                    self.assertEqual(main(argv + ['--normalize']), 0)
                normalized = out.getvalue()
            self.assertTrue(normalized.startswith(default))
            self.assertIn('source_date_text: پنجشنبه ۲ مهر ۱۴۰۵ ساعت ۲۰:۳۰', normalized)
            self.assertIn('starts_at: 2026-09-24T20:30:00+03:30', normalized)
            self.assertIn('price_amount: 350000', normalized)
            self.assertIn('currency: TOMAN', normalized)
            self.assertEqual(before, {p.relative_to(directory): p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()})

    def test_instagram_caption_offline_read_only(self):
        self._review('instagram', 'davvvat_instagram')

    def test_instagram_evidence_offline_read_only(self):
        self._review('instagram', 'davvvat_instagram', evidence=True)

    def test_website_offline_read_only(self):
        self._review('website', 'davvvat_website')
