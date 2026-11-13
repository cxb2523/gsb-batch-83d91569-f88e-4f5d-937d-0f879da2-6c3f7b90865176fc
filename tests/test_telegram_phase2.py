"""Telegram Phase 2: crawl jobs, Excel delivery, event browsing and run history.

Offline only: a fake Telegram HTTP transport, fake crawl runners or a real
RefreshService with fake collectors, and temporary data directories built from
synthetic pipeline output. No live crawl, credential or registry write.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from telegram import Update

from gatherradar.orchestration.refresh import RunCancelled
from gatherradar.review.serialization import review_window
from gatherradar.review.workspace import local_workspace
from gatherradar.storage.sqlite_repository import SqliteCanonicalRepository
from gatherradar.telegram_bot import presentation as ui
from gatherradar.telegram_bot.jobs import JobBusyError, JobManager, JobRecord, JobStore
from gatherradar.telegram_bot.operations import LocalOperations, RunSummary
from gatherradar.telegram_bot.runner import build_application
from gatherradar.telegram_bot.services import SourceCatalog
from gatherradar.telegram_bot.settings import TelegramSettings
from test_jabama_session_pipeline import collected, pipeline
from test_jabama_session_schema import page
from test_jabama_timeslots import ONE
from test_telegram_bot import CONFIG, OWNER, STRANGER, TOKEN, FakeTelegram, callback

STARTED = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
ENABLED = tuple(v.id for v in SourceCatalog(CONFIG).list() if v.enabled)


class Telegram(FakeTelegram):
    """Adds sendDocument and records uploaded files."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.documents = []

    async def do_request(self, url, method, request_data=None, **kwargs):
        if url.endswith('/sendDocument'):
            params = dict(request_data.json_parameters)
            files = request_data.multipart_data or {}
            name, content = next(((v[0], v[1]) for v in files.values()), (None, b''))
            self.calls.append(('sendDocument', params))
            self.documents.append({'filename': name, 'content': content, **params})
            return 200, json.dumps({'ok': True, 'result': {
                'message_id': 9, 'date': 0, 'chat': {'id': OWNER, 'type': 'private'},
                'document': {'file_id': 'f', 'file_unique_id': 'u'}}}).encode()
        return await super().do_request(url, method, request_data, **kwargs)


class FakeRunner:
    """Stands in for RefreshService inside the worker thread."""

    def __init__(self, outcome=('success', ()), block=None, cancellable=False):
        self.calls, self.outcome, self.block, self.cancellable = [], outcome, block, cancellable

    def __call__(self, record, progress, should_stop):
        self.calls.append((record.scope, record.all_enabled))
        for index, source in enumerate(record.scope, 1):
            progress('source_started', {'source_id': source, 'index': index, 'total': len(record.scope)})
            if self.block is not None:
                self.block.wait(5)
            if self.cancellable and should_stop():
                raise RunCancelled(record.job_id)
            progress('source_finished', {'source_id': source, 'index': index, 'total': len(record.scope),
                                         'status': 'partial' if index == 1 else 'success'})
        progress('exporting', {})
        return self.outcome


def persist_run(data: Path, run_id: str, started: datetime = STARTED, export: bool = True) -> None:
    """A real persisted run and workbook from synthetic pipeline output."""
    _, result = pipeline(collected(page([ONE])))
    db = data / 'state' / 'gatherradar.sqlite3'
    db.parent.mkdir(parents=True, exist_ok=True)
    with SqliteCanonicalRepository(db) as repo:
        repo.sync(result, review_window(result.events, started), run_id=run_id, started_at=started,
                  finished_at=started, days=14, review_timezone='Asia/Tehran', source_count=1,
                  run_metadata={'selected_source_ids': ['jabama_events_website'], 'mode': 'refresh',
                                'sources': [{'source_id': 'jabama_events_website', 'status': 'success'}]})
        if export:
            local_workspace(repo, data / 'review' / 'GatherRadar.xlsx', data / 'exports').export(run_id)


class Phase2Case(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name) / 'data'
        self.data.mkdir()
        self.runner = FakeRunner()
        self.fake = Telegram()
        self.prepare()  # offline fixtures are built before collectors are blocked
        # Nothing the bot does in these tests may reach a real collector or browser.
        for target in ('gatherradar.orchestration.refresh.RefreshService.run',
                       'gatherradar.collectors.website.WebsiteCollector.collect'):
            patcher = mock.patch(target, side_effect=AssertionError('live crawl'))
            patcher.start()
            self.addCleanup(patcher.stop)

    def prepare(self):
        pass

    def operations(self):
        return LocalOperations(SourceCatalog(CONFIG), data_dir=self.data, config_path=CONFIG,
                               refresh_runner=self.runner)

    def session(self, *payloads, ops=None, settle=None):
        """Process updates in order; `settle` runs between updates (e.g. wait for the job)."""
        ops = ops or self.operations()
        self.ops = ops

        async def go():
            app = build_application(TelegramSettings(TOKEN, OWNER), SourceCatalog(CONFIG),
                                    request=self.fake, operations=ops)
            async with app:
                for payload in payloads:
                    if callable(payload):
                        payload = payload()
                    await app.process_update(Update.de_json(payload, app.bot))
                    if settle is not None:
                        await asyncio.to_thread(settle)
                await asyncio.to_thread(ops.jobs.wait, 5)
                await asyncio.sleep(0.2)  # let scheduled progress edits run
        asyncio.run(go())
        return ops

    def edits(self):
        return [p for name, p in self.fake.calls if name == 'editMessageText']

    def answers(self):
        return [p.get('text') for name, p in self.fake.calls if name == 'answerCallbackQuery']

    def buttons(self, payload):
        return [b for row in json.loads(payload['reply_markup'])['inline_keyboard'] for b in row]

    def nonce(self):
        last = next(p for p in reversed(self.edits()) if 'reply_markup' in p)
        go = next(b['callback_data'] for b in self.buttons(last) if b.get('callback_data', '').startswith(ui.GO))
        return go[len(ui.GO):]


class CrawlFlowTests(Phase2Case):
    def test_all_enabled_crawl_needs_confirmation_and_runs_enabled_sources_only(self):
        holder = {}

        def confirm_then_go():
            holder['nonce'] = self.nonce()
            return callback(ui.GO + holder['nonce'])
        self.session(callback(ui.CRAWL_ALL), confirm_then_go)
        confirm = self.edits()[0]['text']
        self.assertIn(f'همه منابع فعال ({ui.persian(len(ENABLED))} منبع)', confirm)
        self.assertIn('از هر منبع حداکثر ۵ مورد اخیر بررسی می‌شود', confirm)
        self.assertIn('بازه ۱۴ روز آینده', confirm)
        self.assertIn('آیا می‌خواهید جمع‌آوری شروع شود؟', confirm)
        (scope, all_enabled), = self.runner.calls
        self.assertTrue(all_enabled)
        self.assertEqual(set(scope), set(ENABLED))
        self.assertNotIn('davvvat_website', scope)  # disabled by robots policy, never run

    def test_menu_navigation_never_starts_a_crawl(self):
        self.session(callback(ui.MAIN), callback(ui.CRAWL_ALL), callback(ui.SELECT + '0'),
                     callback(ui.SELECT + 'all:0'), callback(ui.SELECT + 'ok'), callback(ui.RUNS + '0'),
                     callback(ui.OUTPUTS), callback(ui.JOB))
        self.assertEqual(self.runner.calls, [])

    def test_selection_toggles_persist_across_pages_and_run_only_the_choice(self):
        holder = {}

        def go():
            return callback(ui.GO + self.nonce())
        self.session(callback(ui.SELECT + '0'), callback(f'{ui.SELECT}t:jabama_events_website:0'),
                     callback(ui.SELECT + '1'), callback(f'{ui.SELECT}t:vadoostan_website:1'),
                     callback(ui.SELECT + '0'), callback(ui.SELECT + 'ok'), go)
        selection = self.edits()[4]['text']
        self.assertIn('انتخاب‌شده: ۲', selection)
        (scope, all_enabled), = self.runner.calls
        self.assertFalse(all_enabled)
        self.assertEqual(set(scope), {'jabama_events_website', 'vadoostan_website'})

    def test_select_all_and_clear(self):
        self.session(callback(ui.SELECT + 'all:0'), callback(ui.SELECT + 'clr:0'), callback(ui.SELECT + 'ok'))
        self.assertIn(f'انتخاب‌شده: {ui.persian(len(ENABLED))}', self.edits()[0]['text'])
        self.assertIn('انتخاب‌شده: ۰', self.edits()[1]['text'])
        self.assertEqual(self.answers()[-1], 'هیچ منبعی انتخاب نشده است.')
        self.assertEqual(self.runner.calls, [])

    def test_disabled_unknown_and_forged_sources_are_refused(self):
        self.session(callback(f'{ui.SELECT}t:davvvat_website:0'), callback(f'{ui.SELECT}t:not_a_source:0'),
                     callback(ui.GO + 'deadbeef0000'), callback(ui.SELECT + 'ok'))
        self.assertEqual(self.answers()[:3], [ui.INVALID] * 3)
        self.assertEqual(self.runner.calls, [])
        ops = self.operations()
        for scope in (('davvvat_website',), ('nope',), ()):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                ops.resolve_scope(scope)

    def test_replayed_confirmation_cannot_launch_twice(self):
        holder = {}

        def go():
            holder['nonce'] = holder.get('nonce') or self.nonce()
            return callback(ui.GO + holder['nonce'])
        self.session(callback(ui.CRAWL_ALL), go, go, settle=lambda: time.sleep(0.05))
        self.assertEqual(len(self.runner.calls), 1)
        self.assertIn(ui.INVALID, self.answers())

    def test_cancel_button_discards_the_pending_confirmation(self):
        holder = {}

        def cancel():
            holder['nonce'] = self.nonce()
            return callback(ui.NO + holder['nonce'])
        self.session(callback(ui.CRAWL_ALL), cancel, lambda: callback(ui.GO + holder['nonce']))
        self.assertEqual(self.runner.calls, [])
        self.assertIn('جمع‌آوری شروع نشد.', self.answers())

    def test_strangers_cannot_use_any_new_action(self):
        actions = (ui.CRAWL_ALL, ui.SELECT + '0', ui.SELECT + 'ok', ui.GO + 'deadbeef0000', ui.OUTPUTS,
                   ui.RUNS + '0', ui.JOB, ui.JOB_CANCEL, ui.EXCEL + 'abcdef123456',
                   ui.EVENTS + 'abcdef123456:a:0', ui.EVENT + 'abcdef123456:a:0')
        self.session(*(callback(action, STRANGER) for action in actions))
        self.assertEqual(self.answers(), [ui.PRIVATE_ONLY] * len(actions))
        self.assertEqual(self.edits(), [])
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.fake.documents, [])


class JobTests(Phase2Case):
    def test_progress_edits_one_status_message_and_completion_offers_outputs(self):
        self.session(callback(ui.CRAWL_ALL), lambda: callback(ui.GO + self.nonce()))
        texts = [p['text'] for p in self.edits()]
        self.assertIn('در حال جمع‌آوری رویدادها', texts[1])
        self.assertIn('⏱ زمان سپری‌شده:', texts[1])
        final = self.edits()[-1]
        self.assertEqual(final['message_id'], '7')  # the same status message is edited
        self.assertIn('این اجرا به ثبت نتیجه نرسید', final['text'])  # the fake runner persists nothing
        self.assertNotIn(str(self.data), json.dumps(self.fake.calls, ensure_ascii=False))

    def test_only_one_job_at_a_time(self):
        gate = threading.Event()
        self.runner = FakeRunner(block=gate)
        ops = self.operations()
        job = ops.start_crawl(('jabama_events_website',))
        with self.assertRaises(JobBusyError) as busy:
            ops.start_crawl(None)
        self.assertEqual(busy.exception.current.job_id, job.job_id)
        self.session(callback(ui.CRAWL_ALL), ops=ops)
        self.assertIn(ui.BUSY, self.answers())
        gate.set()
        self.assertTrue(ops.jobs.wait(5))
        self.assertEqual(len(self.runner.calls), 1)

    def test_cancellation_stops_at_a_safe_boundary(self):
        gate = threading.Event()
        self.runner = FakeRunner(block=gate, cancellable=True)
        ops = self.operations()
        ops.start_crawl(('jabama_events_website', 'vadoostan_website'))
        time.sleep(0.1)
        self.assertEqual(ops.jobs.cancel().status, 'cancelling')
        gate.set()
        ops.jobs.wait(5)
        final = ops.jobs.store.read()[-1]
        self.assertEqual(final.status, 'cancelled')
        self.assertIn('هیچ نتیجه‌ای ثبت نشد', final.message)
        self.assertIsNone(ops.jobs.cancel())  # nothing left to cancel

    def test_partial_sources_and_export_failure_are_reported_separately(self):
        self.runner = FakeRunner(outcome=('partial', ('ExcelReviewExporter: write failed',)))
        ops = self.operations()
        ops.start_crawl(('jabama_events_website', 'vadoostan_website'))
        ops.jobs.wait(5)
        final = ops.jobs.store.read()[-1]
        self.assertEqual((final.status, final.export_ok), ('partial', False))
        self.assertEqual(sorted(final.source_status.values()), ['partial', 'success'])
        self.assertEqual(set(final.source_status), {'jabama_events_website', 'vadoostan_website'})
        self.assertFalse(ops.workbook_for(final.job_id).ok)

    def test_runner_errors_are_safe_and_never_left_running(self):
        def boom(record, progress, should_stop):
            raise OSError(r'C:\Users\owner\secret path')
        ops = LocalOperations(SourceCatalog(CONFIG), data_dir=self.data, config_path=CONFIG, refresh_runner=boom)
        ops.start_crawl(('jabama_events_website',))
        ops.jobs.wait(5)
        final = ops.jobs.store.read()[-1]
        self.assertEqual(final.status, 'error')
        self.assertNotIn('secret', final.message)

    def test_restart_marks_running_jobs_interrupted(self):
        store = JobStore(self.data / 'telegram' / 'jobs.json')
        store.save(JobRecord('a' * 32, ('jabama_events_website',), False, created_at=STARTED.isoformat()))
        JobManager(store, FakeRunner())
        job = store.get('a' * 32)
        self.assertEqual(job.status, 'interrupted')
        run, = self.operations().recent_runs()
        self.assertEqual((run.mode, run.status, run.persisted), ('incomplete', 'interrupted', False))


class RefreshHookTests(unittest.TestCase):
    """The real RefreshService reports progress and stops only between sources."""

    def test_progress_and_cancellation_before_the_second_source(self):
        from sheets_fakes import STAMP
        from test_acquisition import FIXTURE, FIXTURE_CONFIG
        from test_refresh import raw
        from gatherradar.collectors.base import CollectionResult
        from gatherradar.orchestration.collection_run import run_instagram_collection
        from gatherradar.orchestration.refresh import RefreshService
        from gatherradar.orchestration.website_run import run_website_collection
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            calls, stages = [], []

            def collector(source, key):
                collect = mock.Mock()
                collect.collect.side_effect = lambda *a, **k: calls.append(source.id) or CollectionResult(
                    source.id, (raw(source, key),))
                return collect
            website = lambda source_id, **kw: run_website_collection(
                source_id, collector=collector(FIXTURE['davvvat_website'], 'w'), **kw)
            instagram = lambda source_id, **kw: run_instagram_collection(
                source_id, collector=collector(FIXTURE['davvvat_instagram'], 'i'), **kw)
            with SqliteCanonicalRepository(data / 'db.sqlite3') as repo:
                service = RefreshService(repo, website_collect=website, instagram_collect=instagram,
                                         acquire_evidence=mock.Mock(), now=lambda: STAMP)
                stop = {'value': False}

                def progress(stage, details):
                    stages.append(stage)
                    if stage == 'source_finished':
                        stop['value'] = True
                with self.assertRaises(RunCancelled):
                    service.run(('davvvat_website', 'davvvat_instagram'), config_path=FIXTURE_CONFIG,
                                data_dir=data, run_id='cancel-me', skip_instagram_evidence=True,
                                progress=progress, should_stop=lambda: stop['value'])
                self.assertEqual(len(calls), 1)  # the second source never started
                self.assertEqual(stages, ['source_started', 'source_finished'])
                self.assertIsNone(repo.find_run('cancel-me'))  # nothing persisted
            manifest = json.loads((data / 'runs' / 'cancel-me.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['status'], 'cancelled')


class OutputTests(Phase2Case):
    def prepare(self):
        persist_run(self.data, 'run-old-0001', STARTED - timedelta(days=1))
        persist_run(self.data, 'run-new-0002', STARTED)
        persist_run(self.data, 'run-noexport-3', STARTED - timedelta(days=2), export=False)

    def test_latest_workbook_is_sent_with_run_identity(self):
        self.session(callback(ui.OUTPUTS), callback(ui.EXCEL + 'run-new-0002'))
        document, = self.fake.documents
        self.assertTrue(document['filename'].startswith('GatherRadar-'))
        self.assertTrue(document['filename'].endswith('-run-new-.xlsx'))
        self.assertEqual(document['content'], (self.data / 'review' / 'GatherRadar.xlsx').read_bytes())
        self.assertIn('برگه این اجرا', document['caption'])
        self.assertNotIn(str(self.data), document['caption'])

    def test_historical_run_selection_and_its_workbook_sheet(self):
        self.session(callback(ui.RUNS + '0'), callback(ui.RUN + 'run-old-0001'), callback(ui.EXCEL + 'run-old-0001'))
        runs = [b['text'] for b in self.buttons(self.edits()[0]) if b.get('callback_data', '').startswith(ui.RUN)]
        self.assertEqual(len(runs), 3)
        self.assertIn('کرال زنده', runs[0])
        old_sheet = self.ops.workbook_for('run-old-0001').sheet
        new_sheet = self.ops.workbook_for('run-new-0002').sheet
        self.assertNotEqual(old_sheet, new_sheet)
        self.assertIn(old_sheet, self.fake.documents[0]['caption'])

    def test_missing_or_mismatched_workbook_is_never_sent(self):
        ops = self.operations()
        self.assertFalse(ops.workbook_for('run-noexport-3').ok)
        (self.data / 'review' / 'GatherRadar.xlsx').unlink()
        self.session(callback(ui.EXCEL + 'run-new-0002'), callback(ui.EXCEL + 'run-noexport'), ops=ops)
        self.assertEqual(self.fake.documents, [])
        self.assertEqual(self.answers(), ['فایل Excel هنوز ساخته نشده است.'] * 2)

    def test_event_list_detail_close_and_stale_callbacks(self):
        self.session(callback(ui.EVENTS + 'run-new-0002:a:0'), callback(ui.EVENT + 'run-new-0002:a:0'),
                     callback(ui.EVENTS + 'run-new-0002:a:0'), callback(ui.EVENT + 'run-new-0002:a:99'),
                     callback(ui.EVENTS + 'zzzzzzzz:a:0'), callback(ui.EVENTS + 'run-new-0002:r:0'))
        listing, detail, closed, review = [p['text'] for p in self.edits()]
        self.assertIn('رویدادهای پیش‌رو', listing)
        self.assertIn('کارگاه نمونه', listing)
        self.assertIn('مورد ۱ از ۱', detail)
        self.assertEqual(listing, closed)  # collapse returns to the same page
        self.assertIn('نیازمند بررسی زمان‌بندی', review)
        self.assertEqual(self.answers()[-3:-1], [ui.INVALID, ui.INVALID])
        source = [b for b in self.buttons(self.edits()[1]) if 'url' in b]
        self.assertEqual(source[0]['text'], '🔗 مشاهده منبع')

    def test_read_actions_change_no_data(self):
        db = self.data / 'state' / 'gatherradar.sqlite3'
        book = self.data / 'review' / 'GatherRadar.xlsx'
        before = (db.read_bytes(), book.read_bytes())
        self.session(callback(ui.OUTPUTS), callback(ui.RUNS + '0'), callback(ui.RUN + 'run-new-0002'),
                     callback(ui.EVENTS + 'run-new-0002:a:0'), callback(ui.EVENT + 'run-new-0002:a:0'),
                     callback(ui.EXCEL + 'run-new-0002'))
        self.assertEqual((db.read_bytes(), book.read_bytes()), before)
        self.assertEqual(self.runner.calls, [])


class EmptyStateTests(Phase2Case):
    def test_no_database_is_never_created_by_browsing(self):
        self.session(callback(ui.OUTPUTS), callback(ui.RUNS + '0'), callback(ui.JOB))
        outputs, runs, job = [p['text'] for p in self.edits()]
        self.assertIn('هنوز خروجی Excel معتبری', outputs)
        self.assertIn('هنوز اجرایی ثبت نشده', runs)
        self.assertIn('هنوز اجرایی از طریق ربات', job)
        self.assertFalse((self.data / 'state').exists())


class PresentationTests(unittest.TestCase):
    def record(self, index, **fields):
        return dict({'title': f'رویداد <b>{index}</b>', 'start_date': f'2026-10-{10 + index // 3:02d}',
                     'start_time': '18:00:00', 'venue_name': 'گالری & کافه', 'city': 'تهران',
                     'description_text': 'متن منبع ' * 200, 'canonical_source_url': 'https://example.test/e'}, **fields)

    def summary(self):
        return RunSummary('r' * 32, STARTED, 'refresh', 'success', ('a',), {'a': 'success'})

    def test_event_pages_escape_group_by_date_and_fit_limits(self):
        records = [self.record(i) for i in range(12)]
        text = ui.events_text(records, 'a', 1, self.summary())
        self.assertIn('صفحه ۲ از ۳', text)
        self.assertIn('<b>۶. رویداد &lt;b&gt;5&lt;/b&gt;</b>', text)
        self.assertIn('گالری &amp; کافه', text)
        self.assertEqual(text.count('— '), len({r['start_date'] for r in records[5:10]}))
        self.assertLessEqual(len(ui.event_text(self.record(1), 'a', 0, 1)), ui.MESSAGE_LIMIT + 2)
        markup = ui.events_keyboard(records, 'a', 1, 'r' * 12).to_dict()['inline_keyboard']
        labels = [b['text'] for row in markup for b in row]
        self.assertIn('◀️ قبلی', labels)
        self.assertIn('بعدی ▶️', labels)
        self.assertIn('مشاهده جزئیات ۶', labels)
        for row in markup:
            for button in row:
                if 'callback_data' in button:
                    self.assertLessEqual(len(button['callback_data'].encode()), 64)

    def test_missing_facts_stay_honest(self):
        bare = {'title': 'رویداد بدون جزئیات', 'canonical_source_url': 'https://example.test/x'}
        detail = ui.event_text(bare, 'a', 0, 1)
        for invented in ('تاریخ:', 'مکان:', 'هزینه:', 'نوع:'):
            self.assertNotIn(invented, detail)
        listing = ui.events_text([bare], 'a', 0, self.summary())
        self.assertIn('— تاریخ نامشخص —', listing)

    def test_summary_separates_candidates_from_canonical_events(self):
        run = RunSummary('r' * 32, STARTED, 'refresh', 'partial', ('a', 'b'), {'a': 'success', 'b': 'failed'},
                         discovered=36, excluded_missing_title=10, canonical=26, actionable=16,
                         schedule_review=4, expired=6)
        text = ui.run_summary_text(run, {'a': 'منبع الف', 'b': 'منبع ب'}, False)
        for expected in ('نیمه‌موفق', '✅ تکمیل‌شده (۱): منبع الف', '❌ ناموفق (۱): منبع ب',
                         'نامزدهای رویداد کشف‌شده: ۳۶', 'رویدادهای یکتا پس از ادغام تکراری‌ها: ۲۶',
                         'پیش‌رو / در جریان: ۱۶', 'بررسی زمان‌بندی: ۴', 'گذشته: ۶',
                         'بدون عنوان قابل‌اتکا (کنار گذاشته شد): ۱۰', 'خروجی Excel: ساخته نشد'):
            self.assertIn(expected, text)

    def test_progress_text_has_no_invented_percentages(self):
        job = JobRecord('j' * 32, ('a', 'b'), False, stage='collecting', current_source='b',
                        done_sources=1, total_sources=2, source_status={'a': 'partial'})
        text = ui.job_text(job, {'a': 'الف', 'b': 'ب'})
        self.assertIn('منابع تکمیل‌شده: ۱ از ۲', text)
        self.assertIn('منبع فعلی: ب', text)
        self.assertNotIn('%', text)
        self.assertNotIn('٪', text)


if __name__ == '__main__':
    unittest.main()
