"""Local implementation of the bot's application boundary.

Crawls run through the same `RefreshService` wiring as `gatherradar refresh`
(same database, workbook and exports under the data directory). Reads use the
persisted SQLite review projection and the workbook written by the existing XLSX
exporter; nothing here rediscovers, renormalizes or re-exports events.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from ..review.models import ReviewError
from .jobs import ACTIVE, JobManager, JobRecord, JobStore
from .services import SourceCatalog, SourceView
from .timing import CrawlDurationEstimator, Estimate, TimingStore

LOGGER = logging.getLogger('gatherradar.telegram')
TEHRAN = ZoneInfo('Asia/Tehran')
MAX_WORKBOOK_BYTES = 45 * 1024 * 1024  # Telegram bots may send documents up to 50 MB


class ScopeError(ValueError):
    """A selection that may not run (unknown, disabled or empty)."""


class RegistryBusyError(RuntimeError):
    """Source changes wait until the running crawl finishes (its scope is fixed)."""


@dataclass
class _Live:
    """In-memory timing of the running job (monotonic seconds; never persisted)."""
    started: float
    source_started: float | None = None
    post_started: float | None = None
    kinds: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProgressView:
    elapsed: float
    source_elapsed: float | None
    estimate: Estimate | None
    current_kind: str | None


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    started_at: datetime | None
    mode: str                      # refresh | stored_sync | incomplete
    status: str
    source_ids: tuple[str, ...]
    source_status: dict
    discovered: int | None = None  # Event candidates before title admission
    excluded_missing_title: int | None = None
    canonical: int | None = None   # unique canonical Events
    actionable: int | None = None
    schedule_review: int | None = None
    expired: int | None = None
    persisted: bool = True

    @property
    def token(self) -> str:
        return self.run_id[:12]


@dataclass(frozen=True)
class WorkbookCheck:
    ok: bool
    path: Path | None = None
    filename: str | None = None
    sheet: str | None = None
    reason: str | None = None      # safe Persian explanation


def _summary(meta: dict) -> RunSummary:
    started = meta.get('started_at')
    dispositions = meta.get('disposition_counts') or {}
    return RunSummary(
        run_id=meta['run_id'], started_at=datetime.fromisoformat(started) if started else None,
        mode=meta.get('mode', 'refresh'), status=meta.get('status', 'unknown'),
        source_ids=tuple(meta.get('selected_source_ids') or ()),
        source_status={s.get('source_id'): s.get('status') for s in meta.get('sources') or () if isinstance(s, dict)},
        discovered=meta.get('discovered_event_count'), excluded_missing_title=meta.get('excluded_missing_title'),
        canonical=meta.get('canonical_event_count'), actionable=meta.get('event_count'),
        schedule_review=dispositions.get('needs_schedule_review', meta.get('undated')),
        expired=dispositions.get('expired'))


class LocalOperations:
    def __init__(self, catalog: SourceCatalog, *, data_dir: str | Path = 'data',
                 config_path: str | Path = 'config/sources.yaml', limit: int = 5, days: int = 14,
                 refresh_runner: Callable | None = None, clock: Callable[[], float] = time.monotonic,
                 media: bool = True, robots_check: Callable | None = None, resolver: Callable | None = None) -> None:
        from ..source_registry import SourceRegistry
        self.catalog = catalog
        self.data_dir = Path(data_dir)
        self.config_path = Path(config_path)
        self.registry = SourceRegistry(self.config_path)
        self.limit, self.days, self.media = limit, days, media
        self.database = self.data_dir / 'state' / 'gatherradar.sqlite3'
        self.workbook = self.data_dir / 'review' / 'GatherRadar.xlsx'
        self.exports = self.data_dir / 'exports'
        self.refresh_runner = refresh_runner or self._refresh
        self.clock = clock
        self.robots_check, self.resolver = robots_check, resolver
        self.timings = TimingStore(self.data_dir / 'telegram' / 'timings.json')
        self.estimator = CrawlDurationEstimator(self.timings)
        self._live: dict[str, _Live] = {}
        self._registry_lock = threading.Lock()
        self.jobs = JobManager(JobStore(self.data_dir / 'telegram' / 'jobs.json'), self._run_job)

    # -- sources -----------------------------------------------------------------
    def enabled_sources(self) -> tuple[SourceView, ...]:
        return tuple(v for v in self.catalog.list() if v.enabled)

    def resolve_scope(self, source_ids: tuple[str, ...] | None) -> tuple[str, ...]:
        """None means all enabled. Unknown or disabled IDs are refused, never dropped."""
        enabled = {v.id: v for v in self.enabled_sources()}
        if source_ids is None:
            if not enabled:
                raise ScopeError('no enabled sources')
            return tuple(enabled)
        if not source_ids or any(i not in enabled for i in source_ids):
            raise ScopeError('selection contains an unknown or disabled source')
        return tuple(i for i in enabled if i in set(source_ids))  # registry order

    def crawl_active(self) -> bool:
        current = self.jobs.current
        return current is not None and current.status in ACTIVE

    # -- crawl jobs --------------------------------------------------------------
    def start_crawl(self, source_ids: tuple[str, ...] | None, *, expected: tuple[str, ...] | None = None) -> JobRecord:
        """`expected` is the scope the owner confirmed; if the registry changed since,
        nothing starts. The job always runs that explicit snapshot."""
        with self._registry_lock:
            scope = self.resolve_scope(source_ids)
            if expected is not None and tuple(scope) != tuple(expected):
                raise ScopeError('the confirmed sources changed')
            kinds = {v.id: v.kind for v in self.catalog.list()}
            record = self.jobs.start(scope, all_enabled=source_ids is None)
        self._live.setdefault(record.job_id, _Live(self.clock(), kinds={i: kinds.get(i) for i in scope}))
        return record

    def _run_job(self, record: JobRecord, update: Callable[[JobRecord], None],
                 should_stop: Callable[[], bool]) -> JobRecord:
        from ..orchestration.refresh import RunCancelled
        live = self._live.setdefault(record.job_id, _Live(self.clock()))
        if not live.kinds:
            kinds = {v.id: v.kind for v in self.catalog.all()}
            live.kinds = {i: kinds.get(i) for i in record.scope}
        state = {'record': replace(record, stage='starting')}
        update(state['record'])

        def progress(stage: str, details: dict) -> None:
            current = state['record']
            now = self.clock()
            if stage == 'source_started':
                live.source_started = now
                current = replace(current, stage='collecting', current_source=details.get('source_id'),
                                  done_sources=details.get('index', 1) - 1, total_sources=details.get('total', 0))
            elif stage == 'source_finished':
                source_id = details.get('source_id')
                if live.source_started is not None and isinstance(source_id, str):
                    self._record_source(source_id, live.kinds.get(source_id), now - live.source_started,
                                        details.get('status'))
                live.source_started = None
                statuses = dict(current.source_status, **{source_id: details.get('status')})
                current = replace(current, stage='collecting', source_status=statuses,
                                  done_sources=details.get('index', 0), current_source=None)
            else:
                if stage == 'analyzing' and live.post_started is None:
                    live.post_started = now
                current = replace(current, stage=stage, current_source=None)
            state['record'] = current
            update(current)
        try:
            final = self._outcome(record, progress, should_stop, state, RunCancelled)
        finally:
            ended = self.clock()
        final = replace(final, duration_seconds=round(ended - live.started, 1))
        if live.post_started is not None and final.status in ('success', 'partial'):
            try:
                self.timings.record_post(seconds=ended - live.post_started, status=final.status,
                                         sources=len(record.scope))
            except OSError:
                LOGGER.warning('telegram_timing_write_failed')
        self._live.pop(record.job_id, None)
        return final

    def _record_source(self, source_id: str, kind: str | None, seconds: float, status: object) -> None:
        if kind not in ('instagram', 'website') or status not in ('success', 'partial', 'failed'):
            return
        try:
            self.timings.record_source(source_id, kind=kind, seconds=seconds, status=status,
                                       limit=self.limit, media=self.media and kind == 'instagram')
        except OSError:
            LOGGER.warning('telegram_timing_write_failed')

    def _outcome(self, record, progress, should_stop, state, cancelled_error) -> JobRecord:
        try:
            outcome = self.refresh_runner(record, progress, should_stop)
        except cancelled_error:
            return replace(state['record'], status='cancelled', stage='done', current_source=None,
                           message='اجرا پیش از تحلیل متوقف شد؛ هیچ نتیجه‌ای ثبت نشد. '
                                   'مطالب خامی که تا آن لحظه دریافت شده بود حفظ شده است.')
        except ReviewError as error:
            return replace(state['record'], status='error', stage='done',
                           message=_safe_review_error(str(error)))
        except Exception as error:
            LOGGER.error('telegram_crawl_failed: %s', type(error).__name__, exc_info=error)
            return replace(state['record'], status='error', stage='done',
                           message='اجرا با خطا متوقف شد و نتیجه‌ای ثبت نشد؛ جزئیات در گزارش محلی ثبت شد. '
                                   'می‌توانید دوباره تلاش کنید.')
        status, export_failures = outcome
        xlsx_failed = any(e.startswith(('ExcelReviewExporter', 'XLSX')) for e in export_failures)
        return replace(state['record'], status=status, stage='done', current_source=None,
                       export_ok=not xlsx_failed,
                       message='ساخت فایل Excel ناموفق بود؛ داده‌ها ذخیره شده‌اند.' if xlsx_failed else None)

    def progress_view(self, job: JobRecord) -> ProgressView:
        live = self._live.get(job.job_id)
        if live is None:
            return ProgressView(job.duration_seconds or 0.0, None, None, None)
        now = self.clock()
        current_kind = live.kinds.get(job.current_source) if job.current_source else None
        source_elapsed = now - live.source_started if live.source_started is not None and job.current_source else None
        try:
            estimate = self._estimate(job, live, now, current_kind, source_elapsed)
        except Exception:  # never let an estimate break progress reporting
            LOGGER.warning('telegram_estimate_failed')
            estimate = None
        return ProgressView(now - live.started, source_elapsed, estimate, current_kind)

    def _estimate(self, job, live, now, current_kind, source_elapsed) -> Estimate | None:
        if job.status not in ACTIVE:
            return None
        done = set(job.source_status)
        current = None
        if job.current_source and source_elapsed is not None:
            current = (job.current_source, current_kind or '', source_elapsed)
        pending = [(i, live.kinds.get(i) or '') for i in job.scope if i not in done and i != job.current_source]
        if live.post_started is not None:
            current, pending = None, []
        post_elapsed = now - live.post_started if live.post_started is not None else None
        return self.estimator.estimate(pending=pending, current=current, post_elapsed=post_elapsed,
                                       limit=self.limit, media=self.media)

    def preview_estimate(self, scope: tuple[str, ...]) -> Estimate | None:
        kinds = {v.id: v.kind for v in self.catalog.list()}
        try:
            return self.estimator.estimate(pending=[(i, kinds.get(i, '')) for i in scope], current=None,
                                           post_elapsed=None, limit=self.limit, media=self.media)
        except Exception:
            return None

    def _refresh(self, record: JobRecord, progress, should_stop) -> tuple[str, tuple[str, ...]]:
        """Runs in the worker thread with its own SQLite connection. The job's
        confirmed source snapshot is passed explicitly, so a registry change made
        elsewhere during the run cannot widen or alter its scope."""
        from ..orchestration.refresh import application_refresh_service
        from ..review.workspace import local_workspace
        from ..storage.sqlite_repository import SqliteCanonicalRepository
        with SqliteCanonicalRepository(self.database) as repository:
            workspace = local_workspace(repository, self.workbook, self.exports)
            service = application_refresh_service(repository, workspace)
            result = service.run(record.scope, all_enabled=False,
                                 config_path=self.config_path, data_dir=self.data_dir, limit=self.limit,
                                 days=self.days, run_id=record.job_id, progress=progress, should_stop=should_stop,
                                 skip_instagram_evidence=not self.media)
        return result.snapshot.status, tuple(result.export_failures)

    # -- source management ---------------------------------------------------------
    def management_counts(self) -> dict[str, int]:
        views = self.catalog.all()
        listed = [v for v in views if not v.archived]
        return {'active': sum(v.enabled for v in listed), 'disabled': sum(not v.enabled for v in listed),
                'archived': sum(v.archived for v in views),
                'instagram': sum(v.kind == 'instagram' for v in listed),
                'website': sum(v.kind == 'website' for v in listed)}

    def propose_source(self, kind: str, text: str):
        """Validate untrusted input; returns a `Proposal` or raises `IntakeError`.
        May contact only a known supported host's robots.txt (never a crawl)."""
        from ..source_intake import propose_instagram, propose_website
        entries = self.registry.entries(include_shadowed=True)
        if kind == 'instagram':
            return propose_instagram(text, entries)
        if kind == 'website':
            return propose_website(text, entries, resolver=self.resolver, robots_check=self.robots_check)
        raise ValueError('unknown source kind')

    def _guard_registry(self) -> None:
        if self.crawl_active():
            raise RegistryBusyError('a crawl is running')

    def register_source(self, proposal, *, activate: bool):
        """Commit a validated proposal. Re-validated as a whole registry under the
        registry lock; an unsupported or policy-blocked website is always saved
        inactive. Never starts a crawl."""
        source = proposal.source
        if proposal.runnable:
            source = replace(source, enabled=bool(activate), disabled_reason=None if activate else 'owner')
        with self._registry_lock:
            self._guard_registry()
            return self.registry.add(source)

    def change_source(self, source_id: str, action: str):
        """action: enable | disable | archive | restore. Reversible; never deletes data."""
        from ..source_registry import RegistryError
        with self._registry_lock:
            self._guard_registry()
            entry = self.registry.get(source_id)
            if entry is None:
                raise RegistryError('unknown_source', source_id)
            if (action == 'enable' and entry.origin == 'local' and entry.source.website is not None
                    and not entry.locked and not entry.source.archived):
                if self._robots_disallows(entry.source):
                    raise RegistryError('robots_disallowed', source_id)
            if action in ('enable', 'disable'):
                return self.registry.set_enabled(source_id, action == 'enable')
            if action in ('archive', 'restore'):
                return self.registry.set_archived(source_id, action == 'archive')
            raise ValueError('unknown action')

    def _robots_disallows(self, source) -> bool:
        from ..source_intake import default_robots_check
        try:
            return not (self.robots_check or (lambda s: default_robots_check(s, self.resolver)))(source)
        except Exception:
            return False  # unknown: collection still enforces robots.txt before any page

    # -- persisted runs (read-only) ------------------------------------------------
    def _repository(self):
        from ..storage.sqlite_repository import SqliteCanonicalRepository
        if not self.database.exists():  # never create a database from a read action
            return None
        return SqliteCanonicalRepository(self.database)

    def recent_runs(self, limit: int = 10) -> tuple[RunSummary, ...]:
        runs = []
        repository = self._repository()
        if repository is not None:
            with repository:
                runs = [_summary(meta) for meta in repository.list_runs()]
        known = {r.run_id for r in runs}
        # Bot jobs that never reached the database (cancelled, interrupted, failed).
        for job in self.jobs.store.read():
            if job.job_id not in known and job.status not in ('running', 'cancelling'):
                runs.append(RunSummary(job.job_id, datetime.fromisoformat(job.created_at), 'incomplete',
                                       job.status, job.scope, dict(job.source_status), persisted=False))
        runs.sort(key=lambda r: r.started_at or datetime.min.replace(tzinfo=TEHRAN), reverse=True)
        return tuple(runs[:limit])

    def find_run(self, token: str) -> RunSummary | None:
        matches = [r for r in self.recent_runs(limit=200) if r.run_id.startswith(token)]
        return matches[0] if len(matches) == 1 else None

    def run_document(self, run_id: str) -> dict | None:
        repository = self._repository()
        if repository is None:
            return None
        with repository:
            try:
                return repository.load(run_id)
            except ReviewError:
                return None

    def latest_exported_run(self) -> RunSummary | None:
        for run in self.recent_runs(limit=50):
            if run.persisted and self.workbook_for(run.run_id).ok:
                return run
        return None

    def _workbook_index(self, path: Path) -> tuple[set, list]:
        """Sheet names and run index, re-read only when the file changes."""
        stat = path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        cached = getattr(self, '_index_cache', None)
        if cached is None or cached[0] != key:
            cached = (key, _read_index(path))
            self._index_cache = cached
        return cached[1]

    def workbook_for(self, run_id: str) -> WorkbookCheck:
        """The existing workbook, only if its run index holds this run's snapshot."""
        job = self.jobs.store.get(run_id)
        if job is not None and job.export_ok is False:
            return WorkbookCheck(False, reason='ساخت فایل Excel برای این اجرا ناموفق بود.')
        path = self.workbook
        try:
            if not path.is_file():
                return WorkbookCheck(False, reason='فایل Excel هنوز ساخته نشده است.')
            if path.stat().st_size > MAX_WORKBOOK_BYTES:
                return WorkbookCheck(False, reason='فایل Excel برای ارسال در تلگرام بیش از حد بزرگ است.')
            names, rows = self._workbook_index(path)
        except Exception as error:
            LOGGER.warning('telegram_workbook_unreadable: %s', type(error).__name__)
            return WorkbookCheck(False, reason='فایل Excel خوانا نیست؛ خروجی را دوباره بسازید.')
        row = next((r for r in rows if r and r[0] == run_id), None)
        sheet = row[8] if row is not None and len(row) > 8 else None
        if not sheet or sheet not in names:
            return WorkbookCheck(False, reason='فایل Excel فعلی برگه این اجرا را ندارد.')
        run = self.find_run(run_id[:12])
        stamp = run.started_at.astimezone(TEHRAN).strftime('%Y%m%d-%H%M') if run and run.started_at else 'run'
        return WorkbookCheck(True, path, f'GatherRadar-{stamp}-{run_id[:8]}.xlsx', sheet)


def _read_index(path: Path) -> tuple[set, list]:
    from openpyxl import load_workbook
    from ..exports.excel import RUNS
    book = load_workbook(path, read_only=True)
    try:
        names = set(book.sheetnames)
        rows = list(book[RUNS].iter_rows(min_row=2, values_only=True)) if RUNS in names else []
    finally:
        book.close()
    return names, rows


def _safe_review_error(message: str) -> str:
    if 'lock' in message.lower():
        return 'عملیات دیگری روی پایگاه داده در جریان است (مثلاً اجرای خط فرمان). پس از پایان آن دوباره تلاش کنید.'
    return 'اجرا انجام نشد؛ جزئیات در گزارش محلی ثبت شد.'
