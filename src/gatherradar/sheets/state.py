"""Ignored local settings and a single-writer lock, never source/canonical storage."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .client import SheetsError, validate_id


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            os.chmod(temporary, 0o600)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class RuntimeState:
    def __init__(self, data_dir: str | Path = 'data') -> None:
        self.root = Path(data_dir)
        self.path = self.root / 'google' / 'sheets_state.json'

    def read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(value, dict):
                raise ValueError
            if value.get('spreadsheet_id'):
                validate_id(value['spreadsheet_id'])
            return value
        except (OSError, ValueError, TypeError):
            raise SheetsError('Invalid local workbook state; inspect it locally before continuing.') from None

    def save(self, value: dict) -> None:
        atomic_json(self.path, value)

    @contextmanager
    def lock(self):
        path = self.path.with_suffix('.lock')
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = path.open('x', encoding='utf-8')
        except FileExistsError:
            raise SheetsError('Another Sheets operation holds the local lock. After a crash, verify no run is active before removing data/google/sheets_state.lock.') from None
        try:
            with handle:
                handle.write(str(os.getpid()))
            yield
        finally:
            path.unlink(missing_ok=True)
