"""Portable atomic file replacement and local single-owner workflow locking."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .models import ReviewError


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, value: dict) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                                  allow_nan=False) + '\n').encode('utf-8'))


class LocalState:
    def __init__(self, database: Path) -> None:
        self.path = database.with_suffix(database.suffix + '.lock')

    @contextmanager
    def lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            handle = self.path.open('x', encoding='utf-8')
        except FileExistsError:
            raise ReviewError('Another local operation holds the database workflow lock. After a crash, verify no run is active before removing the adjacent .lock file.') from None
        try:
            with handle:
                handle.write(str(os.getpid()))
            yield
        finally:
            self.path.unlink(missing_ok=True)
