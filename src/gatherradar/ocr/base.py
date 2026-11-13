from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class OcrStatus(StrEnum):
    SUCCEEDED = 'succeeded'
    EMPTY = 'empty'
    FAILED = 'failed'


class OcrError(Exception):
    '''Base class for local OCR failures.'''


class OcrUnavailableError(OcrError):
    '''The configured local OCR engine or language data is unavailable.'''


@dataclass(frozen=True, slots=True)
class OcrResult:
    status: OcrStatus
    raw_text: str
    text: str
    engine: str
    engine_version: str
    config: str
    failure_reason: str | None = None

    @property
    def meaningful(self) -> bool:
        return self.status is OcrStatus.SUCCEEDED and bool(self.text)


class OcrProvider(Protocol):
    name: str

    def validate(self) -> None: ...

    def recognize(self, image_path: str | Path) -> OcrResult: ...


__all__ = [
    'OcrError', 'OcrProvider', 'OcrResult', 'OcrStatus', 'OcrUnavailableError',
]
