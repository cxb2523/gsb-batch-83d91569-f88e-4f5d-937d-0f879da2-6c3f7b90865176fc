"""Optional local OCR fallback chain: Tesseract, EasyOCR and Windows.Media.Ocr.

Engine behaviour is faked except in RealTesseractTests, which runs only when a
local Tesseract with Persian data is installed. No network, cloud OCR or GPU.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gatherradar.domain.evidence import EvidenceKind
from gatherradar.grouping.selection import select_semantic_evidence
from gatherradar.ocr import (EasyOcrProvider, FallbackOcrProvider, OcrResult, OcrStatus, OcrUnavailableError,
                             TesseractOcrProvider, WindowsOcrProvider, build_ocr_provider)
from gatherradar.ocr.easyocr_provider import _reading_order
from gatherradar.ocr.windows import _SCRIPT
from gatherradar.orchestration.evidence_run import run_instagram_evidence
from gatherradar.storage import JsonlEvidenceStore, JsonlRawItemStore
from gatherradar.orchestration.collection_run import find_source, instagram_output_path
from test_evidence_run_cli import CONFIG, FakeAcquirer, item


class Engine:
    def __init__(self, name, results=(), available=True):
        self.name, self.version, self.config = name, '1', 'cfg-' + name
        self.results, self.available, self.calls = list(results), available, 0

    def validate(self):
        if not self.available:
            raise OcrUnavailableError(f'{self.name} missing')

    def recognize(self, path):
        self.calls += 1
        value = self.results.pop(0)
        if isinstance(value, Exception):
            raise value
        status = OcrStatus.SUCCEEDED if value else OcrStatus.EMPTY
        return OcrResult(status, value, value, self.name, self.version, self.config)


class FallbackChainTests(unittest.TestCase):
    def test_unavailable_engines_are_skipped_and_none_available_fails_clearly(self):
        chain = FallbackOcrProvider([Engine('a', available=False), Engine('b', ['متن'])])
        chain.validate()
        self.assertEqual([p.name for p in chain.available], ['b'])
        self.assertEqual(chain.unavailable, {'a': 'a missing'})
        self.assertEqual((chain.engine, chain.config), ('b', 'cfg-b'))
        with self.assertRaisesRegex(OcrUnavailableError, 'a missing'):
            FallbackOcrProvider([Engine('a', available=False)]).validate()

    def test_later_engine_runs_only_after_unusable_output_and_attempts_stay_separate(self):
        first, second = Engine('a', ['', 'کارگاه']), Engine('b', ['نسخه دوم'])
        chain = FallbackOcrProvider([first, second])
        chain.validate()
        attempts = chain.recognize_all('x.png')
        self.assertEqual([(r.engine, r.text) for r in attempts], [('a', ''), ('b', 'نسخه دوم')])
        self.assertEqual([r.text for r in chain.recognize_all('y.png')], ['کارگاه'])  # no fallback
        self.assertEqual(second.calls, 1)

    def test_engine_exception_is_isolated_and_reported_without_detail(self):
        chain = FallbackOcrProvider([Engine('a', [RuntimeError('private-path')]), Engine('b', ['ok'])])
        attempts = chain.recognize_all('x.png')
        self.assertEqual(attempts[0].status, OcrStatus.FAILED)
        self.assertNotIn('private-path', attempts[0].failure_reason)
        self.assertEqual(attempts[-1].text, 'ok')

    def test_engine_selection_from_environment(self):
        with mock.patch.dict(os.environ, {'GATHERRADAR_OCR_ENGINES': 'tesseract'}):
            self.assertIsInstance(build_ocr_provider(), TesseractOcrProvider)
        with mock.patch.dict(os.environ, {'GATHERRADAR_OCR_ENGINES': 'windows, easyocr'}):
            chain = build_ocr_provider()
            self.assertEqual([p.name for p in chain.providers], ['windows-ocr', 'easyocr'])
        for bad in (('cloud',), ('tesseract', 'tesseract')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build_ocr_provider(bad)
        self.assertEqual([p.name for p in build_ocr_provider().providers], ['tesseract', 'easyocr', 'windows-ocr'])


class FallbackEvidenceRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name)
        source = find_source('davvvat_instagram', CONFIG)
        JsonlRawItemStore(instagram_output_path(source, self.data_dir)).append_new([item()])

    def run_chain(self, *engines):
        chain = FallbackOcrProvider(list(engines))
        return run_instagram_evidence('davvvat_instagram', config_path=CONFIG, data_dir=self.data_dir,
                                      acquirer=FakeAcquirer(), ocr_provider=chain)

    def test_missing_tesseract_no_longer_stops_media_ocr(self):
        summary = self.run_chain(Engine('tesseract', available=False), Engine('easyocr', ['کارگاه سفال']))
        self.assertEqual((summary.ocr_succeeded, summary.ocr_engines, summary.ocr_unavailable),
                         (1, ('easyocr',), ('tesseract',)))

    def test_every_attempt_is_stored_and_the_selected_one_is_latest_for_its_slot(self):
        summary = self.run_chain(Engine('tesseract', ['']), Engine('easyocr', ['کارگاه سفال']))
        self.assertEqual((summary.ocr_succeeded, summary.ocr_fallback_used), (1, 1))
        stored = JsonlEvidenceStore(summary.output_path).read().fragments
        media = [f for f in stored if f.kind is EvidenceKind.IMAGE_OCR]
        self.assertEqual([(f.extraction_engine, f.text) for f in media], [('tesseract', ''), ('easyocr', 'کارگاه سفال')])
        bundle = select_semantic_evidence(item(), stored)
        chosen = [f for f in bundle.fragments if f.kind is EvidenceKind.IMAGE_OCR]
        self.assertEqual([f.text for f in chosen], ['کارگاه سفال'])  # never concatenated
        again = self.run_chain(Engine('tesseract', ['']), Engine('easyocr', ['کارگاه سفال']))
        self.assertEqual(again.new_evidence, 0)  # idempotent rerun

    def test_meaningful_primary_result_is_cached_by_its_own_engine(self):
        self.run_chain(Engine('tesseract', ['متن']), Engine('easyocr', ['x']))
        first, second = Engine('tesseract', []), Engine('easyocr', [])
        summary = self.run_chain(first, second)
        self.assertEqual((first.calls, second.calls, summary.new_evidence), (0, 0, 0))


class WindowsOcrTests(unittest.TestCase):
    def provider(self, *results, platform='win32'):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            result = results[len(calls) - 1]
            if isinstance(result, Exception):
                raise result
            code, out = result
            return subprocess.CompletedProcess(command, code, out, '')
        return WindowsOcrProvider(platform=platform, runner=runner, language='fa'), calls

    def test_unavailable_off_windows_or_without_the_language(self):
        provider, calls = self.provider(platform='linux')
        with self.assertRaisesRegex(OcrUnavailableError, 'only on Windows'):
            provider.validate()
        self.assertEqual(calls, [])
        provider, _ = self.provider((3, ''))
        with self.assertRaisesRegex(OcrUnavailableError, "'fa' is not installed"):
            provider.validate()
        provider, _ = self.provider(FileNotFoundError())
        with self.assertRaisesRegex(OcrUnavailableError, 'PowerShell'):
            provider.validate()

    def test_inputs_travel_by_environment_never_by_command_text(self):
        provider, calls = self.provider((0, 'version 10.0.22631\n'), (0, 'کارگاه سفال\r\nجمعه ۸ آبان\r\n'))
        result = provider.recognize('C:/media/slide 1;$(evil).png')
        command, options = calls[1]
        self.assertEqual(result.text, 'کارگاه سفال\nجمعه ۸ آبان')
        self.assertEqual((result.engine, result.engine_version, result.config),
                         ('windows-ocr', 'version 10.0.22631', 'language=fa'))
        self.assertFalse(options['shell'])
        self.assertIn('-EncodedCommand', command)
        self.assertNotIn('evil', ' '.join(command))
        self.assertTrue(options['env']['GR_OCR_IMAGE'].endswith('slide 1;$(evil).png'))
        self.assertEqual(options['env']['GR_OCR_LANG'], 'fa')
        self.assertNotIn('$env:GR_OCR_IMAGE"', _SCRIPT)  # never expanded inside a string

    def test_failure_and_timeout_become_failed_results(self):
        provider, _ = self.provider((0, 'version 10\n'), (1, ''), subprocess.TimeoutExpired('ps', 1))
        self.assertEqual(provider.recognize('a.png').status, OcrStatus.FAILED)
        self.assertEqual(provider.recognize('a.png').failure_reason, 'Windows OCR timed out')


class EasyOcrTests(unittest.TestCase):
    def test_missing_package_is_unavailable_not_an_error(self):
        def missing(languages):
            raise ImportError('no easyocr')
        with self.assertRaisesRegex(OcrUnavailableError, 'optional'):
            EasyOcrProvider(reader_factory=missing).validate()

    def test_reading_order_is_top_down_and_right_to_left(self):
        box = lambda x, y: [(x, y), (x + 50, y), (x + 50, y + 20), (x, y + 20)]
        boxes = [(box(0, 0), 'سفال', .9), (box(100, 2), 'کارگاه', .9), (box(60, 40), 'آبان', .8),
                 (box(120, 41), '۸', .8)]
        self.assertEqual(_reading_order(boxes), ['کارگاه سفال', '۸ آبان'])

    def test_recognition_with_a_fake_reader(self):
        class Reader:
            def readtext(self, path, detail, paragraph):
                return [([(0, 0), (40, 0), (40, 10), (0, 10)], 'نمایشگاه', 0.9)]
        provider = EasyOcrProvider(reader_factory=lambda languages: Reader(), version=lambda: 'easyocr 1.7.2')
        provider.validate()
        result = provider.recognize('a.png')
        self.assertEqual((result.status, result.text, result.engine_version),
                         (OcrStatus.SUCCEEDED, 'نمایشگاه', 'easyocr 1.7.2'))
        self.assertEqual(provider.config, 'languages=fa+en;order=rtl-lines')


@unittest.skipUnless(shutil.which('tesseract'), 'Local Tesseract is not installed.')
class RealTesseractTests(unittest.TestCase):
    """A real local engine on a rendered synthetic image; nothing is mocked."""

    def test_real_tesseract_behind_the_chain_reads_rendered_persian(self):
        try:
            from PIL import Image, ImageDraw, ImageFont, features
        except ImportError:
            self.skipTest('Pillow is not installed.')
        fonts = [p for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',) if Path(p).is_file()]
        if not fonts or not features.check('raqm'):
            self.skipTest('No shaping-capable Persian font rendering available.')
        provider = TesseractOcrProvider()
        try:
            provider.validate()
        except OcrUnavailableError as exc:
            self.skipTest(str(exc))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'slide.png'
            image = Image.new('RGB', (900, 220), 'white')
            draw = ImageDraw.Draw(image)
            font = ImageFont.truetype(fonts[0], 56)
            draw.text((860, 40), 'کارگاه سفال', fill='black', font=font, anchor='ra', direction='rtl')
            draw.text((860, 130), '8 Aban 1405', fill='black', font=font, anchor='ra')
            image.save(path)
            chain = FallbackOcrProvider([provider, WindowsOcrProvider(platform='linux')])
            chain.validate()
            attempts = chain.recognize_all(path)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].engine, 'tesseract')
        self.assertIn('1405', attempts[0].text)
        self.assertIn('سفال', attempts[0].text)


if __name__ == '__main__':
    unittest.main()


GARBLED = ('‎ae‏\n‎pee ae > [‏\n9 . ورکشاپ ساخت جاعودی روح و کدو هالووین 7\n'
           '‎fal‏ با مهافت ‎a‏ مود روج ویر ی\n© جمعه و شنبه ۸ و ‎٩‏ آبان — <\n۹ و کل ۱')


class QualityAwareFallbackTests(unittest.TestCase):
    """O01: nonempty but implausible text no longer stops the fallback chain."""

    def test_quality_decision_is_explainable_and_never_requires_event_facts(self):
        from gatherradar.ocr.quality import assess_text
        self.assertEqual(assess_text(GARBLED).reason, 'noisy_lines')  # shape of the real De98iwhkf3A OCR
        for text, reason in (('| ~ . — : ;', 'mostly_symbols'), ('ا ب ت ث ج ح خ د', 'fragmented'), ('', 'empty')):
            with self.subTest(text=text):
                self.assertEqual(assess_text(text).reason, reason)
        # Plain readable text is usable even without any date, title or price.
        for text in ('یک متن معمولی بدون تاریخ', 'Halloween Party\nCafe Lamiz', 'ورکشاپ چارم‌بگ سالووینی ‎La'):
            with self.subTest(text=text):
                self.assertTrue(assess_text(text).usable)

    def test_garbled_nonempty_output_tries_the_next_engine(self):
        first, second = Engine('a', [GARBLED]), Engine('b', ['ورکشاپ ساخت جاعودی\nجمعه و شنبه ۸ و ۹ آبان'])
        chain = FallbackOcrProvider([first, second])
        attempts = chain.recognize_all('x.png')
        self.assertEqual([r.engine for r in attempts], ['a', 'b'])
        self.assertEqual(attempts[-1].engine, 'b')  # chosen last; never concatenated
        self.assertNotIn('ae', attempts[-1].text)

    def test_when_every_engine_is_implausible_the_best_reading_is_chosen_not_merged(self):
        chain = FallbackOcrProvider([Engine('a', ['| ~ . — : ;']), Engine('b', [GARBLED])])
        attempts = chain.recognize_all('x.png')
        self.assertEqual([r.engine for r in attempts], ['a', 'b'])
        self.assertEqual(attempts[-1].text, GARBLED)
        chain = FallbackOcrProvider([Engine('a', [GARBLED]), Engine('b', [''])])
        self.assertEqual(chain.recognize_all('x.png')[-1].engine, 'a')  # empty never beats text


class QualityAwareCacheTests(FallbackEvidenceRunTests):
    def test_cached_garbled_reading_is_retried_when_another_engine_becomes_available(self):
        self.run_chain(Engine('tesseract', [GARBLED]), Engine('easyocr', available=False))
        first, second = Engine('tesseract', []), Engine('easyocr', ['ورکشاپ ساخت جاعودی'])
        summary = self.run_chain(first, second)
        # The garbled cached reading is not reused while an unread engine exists.
        self.assertEqual(second.calls, 1)
        self.assertEqual(summary.ocr_quality_retries, 1)
        stored = JsonlEvidenceStore(summary.output_path).read().fragments
        chosen = [f for f in select_semantic_evidence(item(), stored).fragments if f.kind is EvidenceKind.IMAGE_OCR]
        self.assertEqual([f.text for f in chosen], ['ورکشاپ ساخت جاعودی'])

    def test_garbled_reading_is_not_rerun_once_every_engine_has_read_it(self):
        self.run_chain(Engine('tesseract', [GARBLED]), Engine('easyocr', ['| ~ . —']))
        first, second = Engine('tesseract', []), Engine('easyocr', [])
        summary = self.run_chain(first, second)
        self.assertEqual((first.calls, second.calls, summary.new_evidence), (0, 0, 0))

    def test_usable_reading_from_the_fallback_engine_is_reused(self):
        self.run_chain(Engine('tesseract', ['']), Engine('easyocr', ['کارگاه سفال']))
        first, second = Engine('tesseract', []), Engine('easyocr', [])
        summary = self.run_chain(first, second)
        self.assertEqual((first.calls, second.calls, summary.new_evidence), (0, 0, 0))
