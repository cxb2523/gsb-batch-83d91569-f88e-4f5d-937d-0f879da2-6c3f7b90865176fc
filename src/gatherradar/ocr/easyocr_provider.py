from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .base import OcrResult, OcrStatus, OcrUnavailableError

EASYOCR_LANGUAGES_ENV = 'GATHERRADAR_EASYOCR_LANGUAGES'
DEFAULT_LANGUAGES = ('fa', 'en')


def _default_reader_factory(languages: list[str]) -> Any:
    import easyocr  # Optional: pip install -e ".[ocr-easyocr]"
    # Local models only after their one-time download; no GPU is required.
    return easyocr.Reader(languages, gpu=False, verbose=False)


def _version() -> str:
    try:
        from importlib.metadata import version
        return 'easyocr ' + version('easyocr')
    except Exception:
        return 'easyocr unknown'


def _reading_order(boxes: list[tuple[Any, str, float]]) -> list[str]:
    """Top-to-bottom lines; right-to-left within a line (Persian layout)."""
    items = []
    for box, text, _ in boxes:
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        items.append((min(ys), max(ys), max(xs), text))
    items.sort(key=lambda item: (item[0], -item[2]))
    lines: list[list[tuple[float, float, float, str]]] = []
    for item in items:
        current = lines[-1] if lines else None
        # Same visual line when the vertical extents overlap by half a box.
        if current and item[0] < (current[0][0] + current[0][1]) / 2:
            current.append(item)
        else:
            lines.append([item])
    return [' '.join(text for *_, text in sorted(line, key=lambda i: -i[2])) for line in lines]


class EasyOcrProvider:
    """Optional local EasyOCR engine (Persian + English), never a cloud call."""

    name = 'easyocr'

    def __init__(self, *, languages: Sequence[str] | None = None,
                 reader_factory: Callable[[list[str]], Any] = _default_reader_factory,
                 version: Callable[[], str] = _version) -> None:
        configured = os.environ.get(EASYOCR_LANGUAGES_ENV, '')
        self.languages = tuple(languages or [x.strip() for x in configured.split(',') if x.strip()]
                               or DEFAULT_LANGUAGES)
        self._factory = reader_factory
        self._version_of = version
        self._reader: Any = None
        self._version: str | None = None

    @property
    def version(self) -> str | None:
        return self._version

    @property
    def config(self) -> str:
        return 'languages=' + '+'.join(self.languages) + ';order=rtl-lines'

    def validate(self) -> None:
        self._version = None
        try:
            self._reader = self._factory(list(self.languages))
        except ImportError as exc:
            raise OcrUnavailableError('EasyOCR is not installed; it is optional '
                                      '(pip install -e ".[ocr-easyocr]").') from exc
        except Exception as exc:
            raise OcrUnavailableError(f'EasyOCR could not start ({type(exc).__name__}).') from exc
        self._version = self._version_of()

    def recognize(self, image_path: str | Path) -> OcrResult:
        if self._reader is None:
            self.validate()
        try:
            boxes = self._reader.readtext(str(Path(image_path)), detail=1, paragraph=False)
        except Exception as exc:
            return OcrResult(OcrStatus.FAILED, '', '', self.name, self._version or 'unknown',
                             self.config, f'EasyOCR failed ({type(exc).__name__})')
        raw = '\n'.join(_reading_order([(b[0], str(b[1]), float(b[2])) for b in boxes]))
        text = raw.strip()
        return OcrResult(OcrStatus.SUCCEEDED if text else OcrStatus.EMPTY, raw, text,
                         self.name, self._version or 'unknown', self.config)


__all__ = ['EASYOCR_LANGUAGES_ENV', 'EasyOcrProvider']
