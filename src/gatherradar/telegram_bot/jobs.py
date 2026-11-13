"""One crawl at a time, in a worker thread, with a persisted status record.

The Telegram event loop never runs collection, OCR, browser capture or export
itself. A second request is refused with the current job's status. Status is
written atomically to `data/telegram/jobs.json` (bounded history), so after a
restart a job that was running is reported as interrupted, never as finished.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from ..review.io import atomic_json

LOGGER = logging.getLogger('gatherradar.telegram')
HISTORY = 30
ACTIVE = ('running', 'cancelling')
# Terminal outcomes. "interrupted": the bot process stopped while it ran.
FINAL = ('success', 'partial', 'failed', 'cancelled', 'error', 'interrupted')


@dataclass(frozen=True)
class JobRecord:
    job_id: str                      # also the GatherRadar run ID
    scope: tuple[str, ...]           # selected source IDs (resolved, enabled only)
    all_enabled: bool
    status: str = 'running'
    created_at: str = ''
    finished_at: str | None = None
    stage: str = 'queued'
    current_source: str | None = None
    done_sources: int = 0
    total_sources: int = 0
    source_status: dict = field(default_factory=dict)
    export_ok: bool | None = None
    message: str | None = None       # safe, path-free explanation
    duration_seconds: float | None = None  # measured with a monotonic clock

    @classmethod
    def from_dict(cls, value: dict) -> JobRecord:
        known = {k: value[k] for k in cls.__dataclass_fields__ if k in value}
        known['scope'] = tuple(known.get('scope', ()))
        return cls(**known)


class JobBusyError(RuntimeError):
    def __init__(self, current: JobRecord) -> None:
        super().__init__('a crawl is already running')
        self.current = current


class JobStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def read(self) -> list[JobRecord]:
        try:
            payload = json.loads(self.path.read_text(encoding='utf-8'))
            return [JobRecord.from_dict(item) for item in payload.get('jobs', ())]
        except (OSError, ValueError, TypeError, AttributeError):
            return []

    def save(self, record: JobRecord) -> None:
        with self._lock:
            jobs = [j for j in self.read() if j.job_id != record.job_id] + [record]
            jobs = sorted(jobs, key=lambda j: j.created_at)[-HISTORY:]
            atomic_json(self.path, {'version': 1, 'jobs': [asdict(j) for j in jobs]})

    def get(self, job_id: str) -> JobRecord | None:
        return next((j for j in self.read() if j.job_id == job_id), None)

    def mark_interrupted(self, now: str) -> int:
        """Called at start-up: nothing can still be running in a new process."""
        stale = [j for j in self.read() if j.status in ACTIVE]
        for job in stale:
            self.save(replace(job, status='interrupted', finished_at=now, stage='interrupted',
                              message='ربات در میانه اجرا متوقف شد؛ نتیجه این اجرا قابل اتکا نیست.'))
        return len(stale)


# A runner executes one job synchronously in the worker thread and returns the
# final record. It receives callbacks to report progress and to ask whether to stop.
Runner = Callable[[JobRecord, Callable[[JobRecord], None], Callable[[], bool]], JobRecord]


class JobManager:
    def __init__(self, store: JobStore, runner: Runner, *, now: Callable[[], datetime] | None = None) -> None:
        self.store, self.runner = store, runner
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._current: JobRecord | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._listeners: list[Callable[[JobRecord], None]] = []
        self.store.mark_interrupted(self.now().isoformat())

    @property
    def current(self) -> JobRecord | None:
        with self._lock:
            return self._current

    def subscribe(self, listener: Callable[[JobRecord], None]) -> None:
        self._listeners.append(listener)

    def start(self, scope: tuple[str, ...], all_enabled: bool) -> JobRecord:
        with self._lock:
            if self._current is not None and self._current.status in ACTIVE:
                raise JobBusyError(self._current)
            record = JobRecord(job_id=uuid4().hex, scope=tuple(scope), all_enabled=all_enabled,
                               created_at=self.now().isoformat(), total_sources=len(scope))
            self._current = record
            self._stop.clear()
        self.store.save(record)
        self._thread = threading.Thread(target=self._work, args=(record,), name='gatherradar-crawl', daemon=False)
        self._thread.start()
        return record

    def cancel(self) -> JobRecord | None:
        """Request a cooperative stop; the job ends at the next safe boundary."""
        with self._lock:
            if self._current is None or self._current.status not in ACTIVE:
                return None
            self._stop.set()
            self._current = replace(self._current, status='cancelling')
            record = self._current
        self.store.save(record)
        self._emit(record)
        return record

    def wait(self, timeout: float | None = None) -> bool:
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def _update(self, record: JobRecord) -> None:
        with self._lock:
            if self._current is not None and self._current.status == 'cancelling' and record.status == 'running':
                record = replace(record, status='cancelling')
            self._current = record
        self.store.save(record)
        self._emit(record)

    def _emit(self, record: JobRecord) -> None:
        for listener in list(self._listeners):
            try:
                listener(record)
            except Exception:
                LOGGER.warning('telegram_job_listener_failed')

    def _work(self, record: JobRecord) -> None:
        try:
            final = self.runner(record, self._update, self._stop.is_set)
        except Exception as error:  # the runner should not raise; never leave a job "running"
            LOGGER.error('telegram_job_failed: %s', type(error).__name__, exc_info=error)
            final = replace(self.current or record, status='error', stage='done',
                            message='اجرا با خطای داخلی متوقف شد؛ جزئیات در گزارش محلی ثبت شد.')
        if final.status not in FINAL:
            final = replace(final, status='error')
        final = replace(final, finished_at=final.finished_at or self.now().isoformat())
        self._update(final)
