import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace

from gatherradar.ocr import OcrStatus, OcrUnavailableError, TesseractOcrProvider


def completed(stdout='', stderr='', returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


class ScriptedRunner:
    def __init__(self, ocr=completed('متن\r\n')):
        self.ocr = ocr
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if '--version' in command:
            return completed('tesseract 5.4.0\n')
        if '--list-langs' in command:
            return completed('List of available languages:\neng\nfas\n')
        if isinstance(self.ocr, Exception):
            raise self.ocr
        return self.ocr


class TesseractTests(unittest.TestCase):
    def test_command_uses_fas_and_eng_without_shell(self):
        runner = ScriptedRunner()
        provider = TesseractOcrProvider(executable='tesseract.exe', runner=runner)
        provider.recognize(Path('image.png'))
        command, kwargs = runner.calls[-1]
        self.assertEqual(
            command,
            ['tesseract.exe', 'image.png', 'stdout', '-l', 'fas+eng', '--psm', '6'],
        )
        self.assertIs(kwargs['shell'], False)

    def test_missing_binary_has_actionable_diagnostic(self):
        def missing(command, **kwargs):
            raise FileNotFoundError('gone')
        with self.assertRaises(OcrUnavailableError) as raised:
            TesseractOcrProvider(runner=missing).validate()
        self.assertIn('GATHERRADAR_TESSERACT_PATH', str(raised.exception))

    def test_missing_persian_language_is_reported(self):
        def runner(command, **kwargs):
            if '--version' in command:
                return completed('tesseract 5')
            return completed('eng\n')
        with self.assertRaises(OcrUnavailableError) as raised:
            TesseractOcrProvider(runner=runner).validate()
        self.assertIn('fas', str(raised.exception))

    def test_failed_validation_cannot_be_bypassed_by_recognize(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            if '--version' in command:
                return completed('tesseract 5')
            if '--list-langs' in command:
                return completed('eng\n')
            return completed('must not run')

        provider = TesseractOcrProvider(runner=runner)
        for action in (provider.validate, lambda: provider.recognize('image.png')):
            with self.assertRaises(OcrUnavailableError):
                action()
        self.assertTrue(all('--version' in call or '--list-langs' in call for call in calls))

    def test_failed_revalidation_invalidates_previous_success(self):
        runner = ScriptedRunner()
        provider = TesseractOcrProvider(runner=runner)
        provider.validate()

        def missing_language(command, **kwargs):
            return completed('tesseract 5') if '--version' in command else completed('eng\n')

        provider._runner = missing_language
        for action in (provider.validate, lambda: provider.recognize('image.png')):
            with self.assertRaises(OcrUnavailableError):
                action()

    def test_success_preserves_raw_output_and_cleans_line_endings(self):
        result = TesseractOcrProvider(runner=ScriptedRunner()).recognize('image.png')
        self.assertEqual(result.status, OcrStatus.SUCCEEDED)
        self.assertEqual(result.raw_text, 'متن\r\n')
        self.assertEqual(result.text, 'متن')
        self.assertEqual(result.engine, 'tesseract')
        self.assertIn('tesseract 5.4.0', result.engine_version)

    def test_empty_output_is_not_meaningful(self):
        result = TesseractOcrProvider(
            runner=ScriptedRunner(completed(' \n'))
        ).recognize('image.png')
        self.assertEqual(result.status, OcrStatus.EMPTY)
        self.assertFalse(result.meaningful)

    def test_timeout_is_an_isolated_failure_result(self):
        timeout = subprocess.TimeoutExpired(['tesseract'], 1)
        result = TesseractOcrProvider(
            runner=ScriptedRunner(timeout)
        ).recognize('image.png')
        self.assertEqual(result.status, OcrStatus.FAILED)
        self.assertIn('timed out', result.failure_reason)

    def test_nonzero_exit_is_a_failure_result(self):
        result = TesseractOcrProvider(
            runner=ScriptedRunner(completed(stderr='bad image', returncode=1))
        ).recognize('image.png')
        self.assertEqual(result.status, OcrStatus.FAILED)
        self.assertEqual(result.failure_reason, 'bad image')


if __name__ == '__main__':
    unittest.main()
