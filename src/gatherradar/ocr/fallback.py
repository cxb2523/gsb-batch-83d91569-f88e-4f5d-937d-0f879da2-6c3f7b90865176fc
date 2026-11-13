from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from .base import OcrProvider, OcrResult, OcrStatus, OcrUnavailableError
from .quality import assess_text

OCR_ENGINES_ENV = 'GATHERRADAR_OCR_ENGINES'
DEFAULT_ENGINES = ('tesseract', 'easyocr', 'windows')


class FallbackOcrProvider:
    """Local engines in order; a later engine runs only when earlier output is unusable.

    Unusable means failed, empty, or text that `assess_text` judges implausible
    (mostly symbols, fragmented, scattered Latin noise in Persian), so garbled
    but nonempty output no longer stops recovery. Unavailable engines are skipped
    at validation. Each attempt stays a separate result; the chosen one is last:
    the first usable attempt, else the best-scoring nonempty one, else the last.
    Hypotheses are never concatenated.
    """

    name = 'fallback'

    def __init__(self, providers: Sequence[OcrProvider]) -> None:
        if not providers:
            raise ValueError('at least one OCR provider is required')
        self.providers = tuple(providers)
        self.available: tuple[OcrProvider, ...] = ()
        self.unavailable: dict[str, str] = {}

    # Cache identity follows the first available engine, as for a single provider.
    @property
    def _primary(self) -> OcrProvider | None:
        return self.available[0] if self.available else None

    @property
    def version(self) -> str | None:
        return getattr(self._primary, 'version', None)

    @property
    def config(self) -> str | None:
        return getattr(self._primary, 'config', None)

    @property
    def engine(self) -> str | None:
        return getattr(self._primary, 'name', None)

    def validate(self) -> None:
        available, unavailable = [], {}
        for provider in self.providers:
            try:
                provider.validate()
            except OcrUnavailableError as exc:
                unavailable[provider.name] = str(exc)
            else:
                available.append(provider)
        self.available, self.unavailable = tuple(available), unavailable
        if not available:
            raise OcrUnavailableError('No local OCR engine is available: ' + '; '.join(
                f'{name}: {reason}' for name, reason in unavailable.items()))

    def recognize_all(self, image_path: str | Path, skip: frozenset = frozenset()) -> tuple[OcrResult, ...]:
        """Attempts in engine order with the chosen one last. Engines whose
        (name, version, config) is in `skip` already read this image and are
        not run again."""
        if not self.available:
            self.validate()
        attempts = []
        for provider in self.available:
            if (provider.name, getattr(provider, 'version', None), getattr(provider, 'config', None)) in skip:
                continue
            try:
                result = provider.recognize(image_path)
            except Exception as exc:  # One engine's failure never stops the next.
                result = OcrResult(OcrStatus.FAILED, '', '', provider.name,
                                   str(getattr(provider, 'version', None) or 'unknown'),
                                   str(getattr(provider, 'config', None) or 'unknown'),
                                   f'OCR failed ({type(exc).__name__})')
            attempts.append(result)
            if result.meaningful and assess_text(result.text).usable:
                break
        return choose(tuple(attempts))

    def recognize(self, image_path: str | Path) -> OcrResult:
        return self.recognize_all(image_path)[-1]


def choose(attempts: tuple[OcrResult, ...]) -> tuple[OcrResult, ...]:
    """Reorder so the chosen attempt is last; the others keep engine order."""
    if not attempts:
        return attempts
    usable = [a for a in attempts if a.meaningful and assess_text(a.text).usable]
    readable = [a for a in attempts if a.meaningful]
    chosen = usable[0] if usable else (max(readable, key=lambda a: assess_text(a.text).score)
                                       if readable else attempts[-1])
    index = attempts.index(chosen)
    return attempts[:index] + attempts[index + 1:] + (chosen,)


def build_ocr_provider(engines: Sequence[str] | None = None) -> OcrProvider:
    """Engines from `engines` or GATHERRADAR_OCR_ENGINES ("tesseract,easyocr,windows")."""
    from .easyocr_provider import EasyOcrProvider
    from .tesseract import TesseractOcrProvider
    from .windows import WindowsOcrProvider
    factories = {'tesseract': TesseractOcrProvider, 'easyocr': EasyOcrProvider, 'windows': WindowsOcrProvider}
    if engines is None:
        configured = os.environ.get(OCR_ENGINES_ENV, '')
        engines = tuple(e.strip().lower() for e in configured.split(',') if e.strip()) or DEFAULT_ENGINES
    unknown = [engine for engine in engines if engine not in factories]
    if unknown or len(set(engines)) != len(engines):
        raise ValueError(f'{OCR_ENGINES_ENV} must list distinct engines from: ' + ', '.join(factories))
    providers = [factories[engine]() for engine in engines]
    return providers[0] if len(providers) == 1 else FallbackOcrProvider(providers)


__all__ = ['DEFAULT_ENGINES', 'FallbackOcrProvider', 'OCR_ENGINES_ENV', 'build_ocr_provider', 'choose']
