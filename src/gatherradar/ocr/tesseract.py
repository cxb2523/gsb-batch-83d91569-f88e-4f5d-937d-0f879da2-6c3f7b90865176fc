from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .base import OcrResult, OcrStatus, OcrUnavailableError

TESSERACT_PATH_ENV = 'GATHERRADAR_TESSERACT_PATH'
DEFAULT_LANGUAGES = ('fas', 'eng')


def _clean_text(raw: str) -> str:
    return raw.replace('\r\n', '\n').replace('\r', '\n').strip()


class TesseractOcrProvider:
    name = 'tesseract'

    def __init__(
        self, *, executable: str | None = None,
        languages: Sequence[str] = DEFAULT_LANGUAGES, psm: int = 6,
        timeout_seconds: float = 30.0,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.executable = executable or os.environ.get(TESSERACT_PATH_ENV) or 'tesseract'
        self.languages = tuple(languages)
        self.psm = psm
        self.timeout_seconds = timeout_seconds
        self._runner = runner
        self._version: str | None = None

    @property
    def version(self) -> str | None:
        return self._version

    @property
    def config(self) -> str:
        return 'languages=' + '+'.join(self.languages) + f';psm={self.psm}'

    def _run(self, command: list[str]) -> Any:
        try:
            return self._runner(
                command, capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=self.timeout_seconds, check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise OcrUnavailableError(
                f'Tesseract was not found at {self.executable!r}. Install Tesseract or set '
                f'{TESSERACT_PATH_ENV} to its executable path.'
            ) from exc

    def validate(self) -> None:
        # A failed initial check or recheck must never authorize recognize().
        self._version = None
        try:
            version = self._run([self.executable, '--version'])
        except subprocess.TimeoutExpired as exc:
            raise OcrUnavailableError('Tesseract version check timed out') from exc
        if version.returncode != 0:
            raise OcrUnavailableError('Tesseract version check failed: ' + version.stderr.strip())
        first_line = (version.stdout or version.stderr or 'tesseract unknown').splitlines()[0]
        try:
            listed = self._run([self.executable, '--list-langs'])
        except subprocess.TimeoutExpired as exc:
            raise OcrUnavailableError('Tesseract language check timed out') from exc
        if listed.returncode != 0:
            raise OcrUnavailableError('Tesseract language check failed: ' + listed.stderr.strip())
        installed = {line.strip() for line in listed.stdout.splitlines() if line.strip()}
        missing = [language for language in self.languages if language not in installed]
        if missing:
            raise OcrUnavailableError(
                'Tesseract language data is missing: ' + ', '.join(missing) +
                '. Install the required language packs (' + ' + '.join(self.languages) + ').'
            )
        self._version = first_line.strip()

    def recognize(self, image_path: str | Path) -> OcrResult:
        if self._version is None:
            self.validate()
        command = [
            self.executable, str(Path(image_path)), 'stdout', '-l',
            '+'.join(self.languages), '--psm', str(self.psm),
        ]
        try:
            completed = self._run(command)
        except subprocess.TimeoutExpired:
            return self._failed('', 'OCR timed out')
        if completed.returncode != 0:
            reason = (completed.stderr or 'Tesseract OCR failed').strip().splitlines()[0]
            return self._failed(completed.stdout or '', reason)
        raw = completed.stdout or ''
        cleaned = _clean_text(raw)
        status = OcrStatus.SUCCEEDED if cleaned else OcrStatus.EMPTY
        return OcrResult(
            status=status, raw_text=raw, text=cleaned, engine=self.name,
            engine_version=self._version or 'unknown', config=self.config,
        )

    def _failed(self, raw: str, reason: str) -> OcrResult:
        return OcrResult(
            status=OcrStatus.FAILED, raw_text=raw, text=_clean_text(raw),
            engine=self.name, engine_version=self._version or 'unknown',
            config=self.config, failure_reason=reason,
        )


__all__ = ['DEFAULT_LANGUAGES', 'TESSERACT_PATH_ENV', 'TesseractOcrProvider']
