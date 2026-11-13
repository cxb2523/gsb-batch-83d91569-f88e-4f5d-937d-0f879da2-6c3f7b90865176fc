"""Telegram Phase 2 UX polish and Phase 3 source management.

Offline only: fake Telegram transport, fake crawl runners, a fake DNS resolver
and a fake robots check. The tracked registry is copied to a temporary folder
and the overlay lives there too; nothing touches config/ or a live source.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from telegram import Update

from gatherradar.collectors.base import SourceAccessRestrictedError
from gatherradar.collectors.websites.transport import HttpTransport
from gatherradar.config import load_base_sources, load_sources
from gatherradar.domain.source import Source, SourceType
from gatherradar.source_intake import (IntakeError, check_public_host, parse_instagram, propose_instagram,
                                       propose_website)
from gatherradar.source_registry import OVERLAY_ENV, RegistryError, SourceRegistry
from gatherradar.telegram_bot import presentation as ui
from gatherradar.telegram_bot.handlers import CONVERSATION_TTL
from gatherradar.telegram_bot.jobs import JobRecord
from gatherradar.telegram_bot.operations import LocalOperations, RegistryBusyError, RunSummary
from gatherradar.telegram_bot.runner import build_application
from gatherradar.telegram_bot.services import SourceCatalog
from gatherradar.telegram_bot.settings import TelegramSettings
from gatherradar.telegram_bot.timing import CrawlDurationEstimator, TimingStore
from test_telegram_bot import CONFIG, OWNER, STRANGER, TOKEN, callback, user
from test_telegram_phase2 import STARTED, FakeRunner, Telegram

PUBLIC = ['93.184.216.34']


def text_message(text, uid=OWNER):
    return {'update_id': 3, 'message': {'message_id': 5, 'date': 0, 'from': user(uid), 'text': text,
                                        'chat': {'id': uid, 'type': 'private'}}}


class Clock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now


class RegistryCase(unittest.TestCase):
    """A private copy of the tracked registry plus its overlay."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.config = self.root / 'config' / 'sources.yaml'
        self.config.parent.mkdir()
        shutil.copy(CONFIG, self.config)
        self.overlay = self.root / 'config' / 'sources.local.json'
        env = mock.patch.dict(os.environ, {OVERLAY_ENV: str(self.overlay)})
        env.start()
        self.addCleanup(env.stop)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.robots_calls = []
        self.robots_allowed = True

    def robots(self, source):
        self.robots_calls.append(source.url)
        return self.robots_allowed

    @staticmethod
    def resolver(host):
        return {'internal.example.org': ['10.0.0.8'], 'rebind.example.org': ['93.184.216.34', '127.0.0.1'],
                'missing.example.org': []}.get(host, PUBLIC)

    def registry(self):
        return SourceRegistry(self.config)

    def operations(self, runner=None, clock=None):
        kwargs = {'clock': clock} if clock else {}
        return LocalOperations(SourceCatalog(self.config), data_dir=self.data, config_path=self.config,
                               refresh_runner=runner or FakeRunner(), robots_check=self.robots,
                               resolver=self.resolver, **kwargs)


# -- timing and estimates ------------------------------------------------------------
class DurationFormatTests(unittest.TestCase):
    def test_elapsed_is_real_persian_text(self):
        self.assertEqual(ui.duration(138), '۲ دقیقه و ۱۸ ثانیه')
        self.assertEqual(ui.duration(0), '۰ ثانیه')
        self.assertEqual(ui.duration(59.9), '۵۹ ثانیه')
        self.assertEqual(ui.duration(120), '۲ دقیقه')
        self.assertEqual(ui.duration(3720), '۱ ساعت و ۲ دقیقه')

    def test_eta_is_a_bounded_minute_range(self):
        self.assertEqual(ui.eta_range(190, 350), 'حدود ۳ تا ۶ دقیقه')
        self.assertEqual(ui.eta_range(10, 50), 'کمتر از یک دقیقه')
        self.assertEqual(ui.eta_range(125, 170), 'حدود ۲ تا ۳ دقیقه')
        self.assertEqual(ui.eta_range(180, 180), 'حدود ۳ دقیقه')


class EstimatorTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = TimingStore(Path(folder.name) / 'timings.json')
        self.estimator = CrawlDurationEstimator(self.store)

    def samples(self, source, kind, seconds, status='success', limit=5, media=None):
        for value in seconds:
            self.store.record_source(source, kind=kind, seconds=value, status=status, limit=limit,
                                     media=kind == 'instagram' if media is None else media)

    def post(self, *seconds):
        for value in seconds:
            self.store.record_post(seconds=value, status='success', sources=2)

    def estimate(self, pending, current=None, post_elapsed=None):
        return self.estimator.estimate(pending=pending, current=current, post_elapsed=post_elapsed,
                                       limit=5, media=True)

    def test_no_history_means_no_estimate(self):
        self.assertIsNone(self.estimate([('ig', 'instagram')]))
        self.samples('ig', 'instagram', [100, 120])  # two samples are not enough
        self.post(20, 25, 30)
        self.assertIsNone(self.estimate([('ig', 'instagram')]))

    def test_enough_samples_give_a_range_that_differs_per_source(self):
        self.samples('ig', 'instagram', [200, 240, 300])
        self.samples('web', 'website', [20, 25, 30])
        self.post(30, 40, 50)
        slow = self.estimate([('ig', 'instagram')])
        fast = self.estimate([('web', 'website')])
        self.assertEqual((slow.low, slow.high), (230, 350))
        self.assertEqual((fast.low, fast.high), (50, 80))
        both = self.estimate([('ig', 'instagram'), ('web', 'website')])
        self.assertEqual((both.low, both.high), (250, 380))

    def test_partial_failed_slow_and_other_settings_are_excluded(self):
        self.samples('ig', 'instagram', [200, 210, 220])
        self.samples('ig', 'instagram', [5], status='failed')
        self.samples('ig', 'instagram', [900], status='partial')
        self.samples('ig', 'instagram', [2000])            # unusually slow: tracked, not trusted
        self.samples('ig', 'instagram', [10, 10, 10], limit=1)  # a different item limit
        self.samples('ig', 'instagram', [30, 30, 30], media=False)  # caption-only
        self.post(10, 10, 10)
        result = self.estimate([('ig', 'instagram')])
        self.assertEqual((result.low, result.high), (210, 230))
        stored = self.store.read()['sources']['ig']
        self.assertIn('partial', {s['status'] for s in stored})  # kept for inspection

    def test_unknown_source_uses_its_kind_only_when_that_kind_has_history(self):
        self.post(10, 10, 10)
        self.assertIsNone(self.estimate([('new_ig', 'instagram')]))
        self.samples('ig', 'instagram', [100, 150, 200])
        by_kind = self.estimate([('new_ig', 'instagram')])
        self.assertEqual(by_kind.bases, ('kind', 'stage'))
        self.assertIsNone(self.estimate([('new_web', 'website')]))  # no website history at all

    def test_current_source_shrinks_with_time_and_overrun_is_reported(self):
        self.samples('ig', 'instagram', [100, 150, 200])
        self.post(10, 10, 10)
        early = self.estimate([], current=('ig', 'instagram', 50))
        later = self.estimate([], current=('ig', 'instagram', 120))
        self.assertGreater(early.high, later.high)
        self.assertEqual(later.low, 10)  # never below zero for the current source
        overrun = self.estimate([], current=('ig', 'instagram', 500))
        self.assertTrue(overrun.current_overrun)

    def test_store_is_bounded_and_tolerates_corruption(self):
        self.samples('ig', 'instagram', range(1, 40))
        self.assertEqual(len(self.store.read()['sources']['ig']), 20)
        self.store.path.write_text('{broken', encoding='utf-8')
        self.assertEqual(self.store.read()['sources'], {})
        self.samples('ig', 'instagram', [-5, float('inf')])  # never stored
        self.assertEqual(self.store.read()['sources'], {})


class LiveProgressTests(RegistryCase):
    def test_elapsed_grows_during_one_long_source_and_timings_are_recorded(self):
        clock, gate, seen = Clock(), threading.Event(), []
        ops = None

        def runner(record, progress, should_stop):
            progress('source_started', {'source_id': record.scope[0], 'index': 1, 'total': 1})
            for _ in range(3):  # three refreshes while the same source is still running
                clock.now += 40
                seen.append(ops.progress_view(ops.jobs.current))
            progress('source_finished', {'source_id': record.scope[0], 'index': 1, 'total': 1, 'status': 'success'})
            progress('analyzing', {})
            clock.now += 15
            return 'success', ()
        ops = self.operations(runner=runner, clock=clock)
        job = ops.start_crawl(('vadoostan_instagram',))
        ops.jobs.wait(5)
        self.assertEqual([round(v.elapsed) for v in seen], [40, 80, 120])
        self.assertEqual([round(v.source_elapsed) for v in seen], [40, 80, 120])
        self.assertTrue(all(v.estimate is None for v in seen))  # no history: never an invented ETA
        final = ops.jobs.store.get(job.job_id)
        self.assertEqual(final.duration_seconds, 135)
        stored = ops.timings.read()
        self.assertEqual(stored['sources']['vadoostan_instagram'][0]['seconds'], 120)
        self.assertEqual(stored['post'][0]['seconds'], 15)
        gate.set()

    def test_failed_or_cancelled_runs_do_not_feed_the_post_baseline(self):
        from gatherradar.orchestration.refresh import RunCancelled

        def runner(record, progress, should_stop):
            progress('source_started', {'source_id': record.scope[0], 'index': 1, 'total': 1})
            progress('source_finished', {'source_id': record.scope[0], 'index': 1, 'total': 1, 'status': 'failed'})
            raise RunCancelled(record.job_id)
        ops = self.operations(runner=runner)
        ops.start_crawl(('vadoostan_website',))
        ops.jobs.wait(5)
        stored = ops.timings.read()
        self.assertEqual(stored['post'], [])
        self.assertEqual(stored['sources']['vadoostan_website'][0]['status'], 'failed')
        self.assertIsNone(ops.estimator.source_range('vadoostan_website', 'website', limit=5, media=False))

    def test_restart_has_no_live_state_and_no_estimate(self):
        gate = threading.Event()
        ops = self.operations(runner=FakeRunner(block=gate))
        job = ops.start_crawl(('vadoostan_website',))
        time.sleep(0.1)
        gate.set()
        ops.jobs.wait(5)
        # A record left "running" by a killed process is reported as interrupted.
        ops.jobs.store.save(replace(ops.jobs.store.get(job.job_id), status='running'))
        restarted = self.operations()
        record = restarted.jobs.store.get(job.job_id)
        self.assertEqual(record.status, 'interrupted')
        view = restarted.progress_view(record)
        self.assertIsNone(view.estimate)
        self.assertIsNone(view.source_elapsed)

    def test_progress_text_shows_estimate_or_says_there_is_not_enough_data(self):
        job = JobRecord('j' * 32, ('a', 'b'), True, stage='collecting', current_source='a', total_sources=2)
        from gatherradar.telegram_bot.operations import ProgressView
        from gatherradar.telegram_bot.timing import Estimate
        none = ui.job_text(job, {'a': 'الف'}, ProgressView(138, 30, None, 'instagram'))
        self.assertIn('⏱ زمان سپری‌شده: ۲ دقیقه و ۱۸ ثانیه', none)
        self.assertIn(ui.NO_ESTIMATE, none)
        self.assertIn('منبع فعلی: الف (اینستاگرام)', none)
        self.assertIn('OCR', none)  # Instagram media explains the longer wait
        self.assertIn('⏹ توقف پس از منبع فعلی', none)
        some = ui.job_text(job, {}, ProgressView(138, 30, Estimate(190, 350), 'website'))
        self.assertIn('⌛ زمان باقی‌مانده تقریبی: حدود ۳ تا ۶ دقیقه', some)
        over = ui.job_text(job, {}, ProgressView(900, 600, Estimate(0, 60, True), 'website'))
        self.assertIn('بیشتر از معمول', over)
        for text in (none, some, over):
            self.assertNotIn('%', text)
            self.assertNotIn('٪', text)
        cancelling = ui.job_text(replace(job, status='cancelling'), {}, ProgressView(5, 5, None, 'website'))
        self.assertIn('پس از پایان منبع فعلی', cancelling)
        self.assertNotIn(ui.JOB_CANCEL, json.dumps(ui.job_keyboard(replace(job, status='cancelling')).to_dict()))


class RateLimitedTelegram(Telegram):
    """Answers editMessageText with 429 or "not found" a set number of times."""

    def __init__(self, rate_limited=0, missing=0):
        super().__init__()
        self.rate_limited, self.missing = rate_limited, missing

    async def do_request(self, url, method, request_data=None, **kwargs):
        if url.endswith('/editMessageText') and (self.rate_limited or self.missing):
            params = dict(request_data.json_parameters)
            self.calls.append(('editMessageText', params))
            if self.rate_limited:
                self.rate_limited -= 1
                return 429, json.dumps({'ok': False, 'error_code': 429, 'description': 'Too Many Requests',
                                        'parameters': {'retry_after': 1}}).encode()
            self.missing -= 1
            return 400, json.dumps({'ok': False, 'error_code': 400,
                                    'description': 'Bad Request: message to edit not found'}).encode()
        return await super().do_request(url, method, request_data, **kwargs)


class BotFlowCase(RegistryCase):
    def setUp(self):
        super().setUp()
        self.fake = Telegram()
        for target in ('gatherradar.orchestration.refresh.RefreshService.run',
                       'gatherradar.collectors.website.WebsiteCollector.collect'):
            patcher = mock.patch(target, side_effect=AssertionError('live crawl'))
            patcher.start()
            self.addCleanup(patcher.stop)

    def session(self, *payloads, ops=None, tick=None, during=None):
        ops = ops or self.operations()
        self.ops = ops

        async def go():
            app = build_application(TelegramSettings(TOKEN, OWNER), SourceCatalog(self.config),
                                    request=self.fake, operations=ops)
            handlers = app.bot_data['gatherradar_handlers']
            self.handlers = handlers
            if tick is not None:
                handlers.tick_interval = handlers.min_edit_interval = tick
            async with app:
                for payload in payloads:
                    if callable(payload):
                        payload = payload()
                    await app.process_update(Update.de_json(payload, app.bot))
                if during is not None:
                    await during()
                await asyncio.to_thread(ops.jobs.wait, 5)
                await asyncio.sleep(0.2)
                await handlers.close()
        asyncio.run(go())
        return ops

    def edits(self):
        return [p for name, p in self.fake.calls if name == 'editMessageText']

    def sends(self):
        return [p for name, p in self.fake.calls if name == 'sendMessage']

    def answers(self):
        return [p.get('text') for name, p in self.fake.calls if name == 'answerCallbackQuery']

    @staticmethod
    def buttons(payload):
        return [b for row in json.loads(payload['reply_markup'])['inline_keyboard'] for b in row]

    def button(self, prefix, payload=None):
        payloads = [payload] if payload else [p for p in reversed(self.edits() + self.sends()) if 'reply_markup' in p]
        for item in payloads:
            for b in self.buttons(item):
                if b.get('callback_data', '').startswith(prefix):
                    return b['callback_data']
        raise AssertionError(f'no button {prefix}')


class TickerTests(BotFlowCase):
    def test_status_keeps_moving_during_a_long_source_and_stops_after(self):
        gate = threading.Event()
        ops = self.operations(runner=FakeRunner(block=gate))

        async def wait_then_release():
            await asyncio.sleep(0.45)  # several ticks while the first source is still running
            gate.set()
        self.session(callback(ui.CRAWL_ALL), lambda: callback(self.button(ui.GO)), ops=ops, tick=0.1,
                     during=wait_then_release)
        live = [p['text'] for p in self.edits() if 'در حال جمع‌آوری رویدادها' in p['text']]
        self.assertGreaterEqual(len(live), 2)
        self.assertGreaterEqual(len({t for t in live}), 2)  # spinner/elapsed changed, not a frozen copy
        self.assertTrue(all(ui.NO_ESTIMATE in t for t in live))
        self.assertEqual(self.handlers._tickers, {})  # the loop ended with the job
        final = self.edits()[-1]['text']
        self.assertNotIn('زمان سپری‌شده', final)
        self.assertIn([name for name, _ in self.fake.calls].count('sendChatAction'), (1,))

    def test_rate_limit_and_deleted_status_message_do_not_break_the_run(self):
        self.fake = RateLimitedTelegram()
        gate = threading.Event()
        ops = self.operations(runner=FakeRunner(block=gate))

        async def release():
            self.fake.rate_limited, self.fake.missing = 1, 1  # from the first live refresh on
            await asyncio.sleep(0.4)
            gate.set()
        self.session(callback(ui.CRAWL_ALL), lambda: callback(self.button(ui.GO)), ops=ops, tick=0.1,
                     during=release)
        job = ops.jobs.store.read()[-1]
        self.assertEqual(job.status, 'success')
        # A missing status message continues in a new message; nothing is raised.
        self.assertTrue(any('نتیجه اجرا' in p['text'] or 'زمان سپری‌شده' in p['text'] for p in self.sends()))

    def test_shutdown_cancels_progress_loops(self):
        gate = threading.Event()
        ops = self.operations(runner=FakeRunner(block=gate))

        async def close_while_running():
            await asyncio.sleep(0.15)
            self.assertEqual(len(self.handlers._tickers), 1)
            await self.handlers.close()
            self.assertEqual(self.handlers._tickers, {})
            gate.set()
        self.session(callback(ui.CRAWL_ALL), lambda: callback(self.button(ui.GO)), ops=ops, tick=0.05,
                     during=close_while_running)


# -- UX ---------------------------------------------------------------------------
class JourneyTests(BotFlowCase):
    def test_welcome_settings_help_and_back_are_always_available(self):
        self.session(callback(ui.MAIN), callback(ui.SETTINGS), callback(ui.HELP), callback(ui.MANAGE))
        welcome, settings, help_text, manage = [p['text'] for p in self.edits()]
        self.assertIn('📡 به GatherRadar خوش آمدید', welcome)
        self.assertIn('فقط نمایش', settings)
        self.assertIn('حداکثر ۵ مطلب', settings)
        self.assertIn('برگشت‌پذیر', help_text)
        self.assertIn('منابعی که GatherRadar بررسی می‌کند را از این بخش مدیریت کنید.', manage)
        self.assertIn('🟢 فعال: ۹', manage)
        self.assertIn('🗂 حذف‌شده: ۰', manage)
        for payload in self.edits()[1:]:  # every screen after the menu leads back to it
            labels = [b['text'] for b in self.buttons(payload)]
            self.assertTrue(any('منوی اصلی' in label for label in labels))

    def test_confirmation_shows_history_based_estimate_when_available(self):
        ops = self.operations()
        for source in ('vadoostan_website', 'jabama_events_website'):
            for seconds in (30, 40, 50):
                ops.timings.record_source(source, kind='website', seconds=seconds, status='success', limit=5,
                                          media=False)
        for seconds in (20, 20, 20):
            ops.timings.record_post(seconds=seconds, status='success', sources=2)
        self.session(callback(ui.SELECT + 't:vadoostan_website:0'), callback(ui.SELECT + 't:jabama_events_website:0'),
                     callback(ui.SELECT + 'ok'), ops=ops)
        confirm = self.edits()[-1]['text']
        self.assertIn('۲ منبع انتخاب شده‌اند.', confirm)
        self.assertIn('زمان تقریبی بر اساس اجراهای قبلی: حدود ۱ تا ۲ دقیقه', confirm)
        self.assertNotIn('اینستاگرام', confirm.split('منابع:')[0])

    def test_empty_result_is_not_a_failure_and_offers_next_actions(self):
        run = RunSummary('r' * 32, STARTED, 'refresh', 'success', ('a',), {'a': 'success'}, discovered=0,
                         excluded_missing_title=0, canonical=0, actionable=0, schedule_review=0, expired=0)
        text = ui.run_summary_text(run, {'a': 'الف'}, True, duration_seconds=75)
        self.assertIn('این خطا نیست', text)
        self.assertIn('⏱ مدت کل اجرا: ۱ دقیقه و ۱۵ ثانیه', text)
        labels = [b.text for row in ui.outputs_keyboard('rrrrrrrrrrrr', True, details=True).inline_keyboard for b in row]
        for label in ('📥 دریافت Excel', '📋 مشاهده رویدادها', '🕘 جزئیات اجرا', '↩️ منوی اصلی'):
            self.assertIn(label, labels)

    def test_untrusted_names_are_escaped_and_bounded(self):
        view = SourceCatalog(self.config).list()[0]
        hostile = replace(view, name='<b>x</b>' + 'ن' * 500, public_url='https://e.test/<script>')
        detail = ui.source_text(hostile)
        self.assertNotIn('<script>', detail)
        self.assertIn('&lt;b&gt;x&lt;/b&gt;', detail)
        listing = ui.manage_list_text((hostile,), 'l', 0)
        self.assertLess(len(listing), ui.MESSAGE_LIMIT)
        self.assertNotIn('<b>x</b>', listing)


# -- intake validation ------------------------------------------------------------
class IntakeTests(RegistryCase):
    def test_instagram_forms_normalize_to_one_username(self):
        for raw in ('@Example.Account', 'example.account', 'https://www.instagram.com/example.account/',
                    'instagram.com/example.account', 'https://instagram.com/example.account?igsh=abc'):
            self.assertEqual(parse_instagram(raw), 'example.account')
        for raw, code in (('https://www.instagram.com/p/Cxyz/', 'ig_not_profile'),
                          ('https://www.instagram.com/reel/Cxyz/', 'ig_not_profile'),
                          ('https://evil.example/example', 'ig_url'), ('@bad..name', 'ig_username'),
                          ('@.dot', 'ig_username'), ('@' + 'a' * 31, 'ig_username'), ('', 'empty'),
                          ('two words', 'format'), ('https://user:pw@instagram.com/x', 'credentials')):
            with self.assertRaises(IntakeError) as caught:
                parse_instagram(raw)
            self.assertEqual(caught.exception.code, code, raw)

    def test_instagram_proposal_and_duplicates(self):
        entries = self.registry().entries()
        proposal = propose_instagram('@Example.Account', entries)
        self.assertEqual(proposal.source.id, 'example_account_instagram')
        self.assertEqual(proposal.source.url, 'https://www.instagram.com/example.account/')
        self.assertEqual(proposal.status, 'needs_review')  # access is never claimed
        with self.assertRaises(IntakeError) as caught:
            propose_instagram('https://www.instagram.com/Vadoostan/', entries)
        self.assertEqual((caught.exception.code, caught.exception.source_id), ('duplicate', 'vadoostan_instagram'))
        # A different account whose slug collides keeps a distinct id and publisher.
        other = propose_instagram('@jabama_events', entries)
        self.assertNotEqual(other.source.id, 'jabama_events_instagram')
        self.assertNotEqual(other.source.publisher_key, 'jabama_events')

    def test_ssrf_and_unsafe_urls_are_refused_without_any_request(self):
        entries = self.registry().entries()
        cases = {'http://127.0.0.1/': 'private', 'http://localhost/events': 'private',
                 'http://169.254.169.254/latest/meta-data': 'private', 'http://10.1.2.3/x': 'private',
                 'http://[::1]/': 'private', 'http://192.168.1.10/': 'private', 'https://intranet/': 'private',
                 'https://metadata.google.internal/': 'private', 'https://internal.example.org/e': 'private',
                 'https://rebind.example.org/e': 'private', 'https://missing.example.org/': 'dns',
                 'https://user:secret@example.org/': 'credentials', 'ftp://example.org/': 'scheme',
                 'https://example.org:8443/': 'port', 'file:///etc/passwd': 'scheme',
                 'https://www.instagram.com/x/': 'is_instagram', 'http://0.0.0.0/': 'private',
                 'http://[::ffff:127.0.0.1]/': 'private'}
        for url, code in cases.items():
            with self.assertRaises(IntakeError, msg=url) as caught:
                propose_website(url, entries, resolver=self.resolver, robots_check=self.robots)
            self.assertEqual(caught.exception.code, code, url)
        self.assertEqual(self.robots_calls, [])

    def test_supported_unsupported_policy_blocked_and_duplicate_websites(self):
        entries = self.registry().entries()
        ready = propose_website('https://jabama.events/all?city=isfahan', entries, resolver=self.resolver,
                                robots_check=self.robots)
        self.assertEqual((ready.status, ready.template, ready.robots), ('ready', 'jabama_events_website', 'allowed'))
        self.assertEqual(ready.source.website.adapter, 'jabama-events')
        self.assertIsNone(ready.source.city_hint)  # never copied from another listing
        unsupported = propose_website('example.org/events', entries, resolver=self.resolver, robots_check=self.robots)
        self.assertEqual((unsupported.status, unsupported.source.disabled_reason), ('unsupported', 'unsupported'))
        self.assertFalse(unsupported.runnable)
        self.assertEqual(self.robots_calls, ['https://jabama.events/all?city=isfahan'])  # unknown hosts never contacted
        blocked = propose_website('https://davvvat.ir/events/', entries, resolver=self.resolver, robots_check=self.robots)
        self.assertEqual((blocked.status, blocked.reason), ('policy_blocked', 'robots'))
        self.robots_allowed = False
        refused = propose_website('https://vadoostan.ir/app/experiences?tag=x', entries, resolver=self.resolver,
                                  robots_check=self.robots)
        self.assertEqual((refused.status, refused.source.disabled_reason), ('policy_blocked', 'robots'))
        for duplicate in ('https://www.jabama.events/all?city=tehran', 'https://jabama.events/all/?city=tehran'):
            with self.assertRaises(IntakeError) as caught:
                propose_website(duplicate, entries, resolver=self.resolver, robots_check=self.robots)
            self.assertEqual(caught.exception.source_id, 'jabama_events_website')

    def test_robots_check_failure_is_unknown_never_allowed(self):
        def broken(source):
            raise OSError('timeout')
        proposal = propose_website('https://jabama.events/all?city=shiraz', self.registry().entries(),
                                   resolver=self.resolver, robots_check=broken)
        self.assertEqual((proposal.status, proposal.robots), ('needs_review', 'unknown'))

    def test_robots_fetch_vets_every_redirect_hop(self):
        transport = HttpTransport('https://jabama.events/all')
        responses = iter([(301, {'location': '/elsewhere/robots.txt'}, b''), (200, {'content-type': 'text/plain'}, b'')])
        seen = []
        with mock.patch.object(HttpTransport, '_request', lambda self, url: next(responses)):
            with self.assertRaises(SourceAccessRestrictedError):
                transport.policy(allowed=lambda url: seen.append(url) or url.endswith('/robots.txt') and len(seen) == 1)
        self.assertEqual(len(seen), 2)

    def test_host_check_accepts_public_addresses(self):
        check_public_host('example.org', self.resolver)
        check_public_host('93.184.216.34')


# -- registry -------------------------------------------------------------------------
class RegistryTests(RegistryCase):
    def ig(self, name='example.account', **kwargs):
        return replace(propose_instagram('@' + name, self.registry().entries()).source, **kwargs)

    def test_base_file_is_never_rewritten_and_overlay_survives_restart(self):
        before = hashlib.sha256(self.config.read_bytes()).hexdigest()
        registry = self.registry()
        registry.add(self.ig(enabled=True, disabled_reason=None))
        registry.set_enabled('vadoostan_instagram', False)
        registry.set_archived('emrooz_events_instagram', True)
        self.assertEqual(hashlib.sha256(self.config.read_bytes()).hexdigest(), before)
        fresh = {s.id: s for s in load_sources(self.config)}  # what the CLI reads
        self.assertTrue(fresh['example_account_instagram'].enabled)
        self.assertEqual(fresh['vadoostan_instagram'].disabled_reason, 'owner')
        self.assertTrue(fresh['emrooz_events_instagram'].archived)
        self.assertFalse(fresh['emrooz_events_instagram'].enabled)
        self.assertEqual({s.id for s in load_base_sources(self.config)} | {'example_account_instagram'}, set(fresh))

    def test_policy_and_unsupported_sources_can_never_be_enabled(self):
        registry = self.registry()
        with self.assertRaises(RegistryError) as caught:
            registry.set_enabled('davvvat_website', True)
        self.assertEqual(caught.exception.code, 'locked')
        # Even a hand-edited overlay cannot clear a robots reason.
        self.overlay.write_text(json.dumps({'version': 1, 'sources': [], 'states': {
            'davvvat_website': {'enabled': True}}}), encoding='utf-8')
        davvvat = next(s for s in load_sources(self.config) if s.id == 'davvvat_website')
        self.assertFalse(davvvat.enabled)
        self.assertEqual(davvvat.disabled_reason, 'robots')
        unsupported = propose_website('https://example.org/e', registry.entries(), resolver=self.resolver).source
        registry.add(unsupported)
        with self.assertRaises(RegistryError):
            registry.set_enabled(unsupported.id, True)

    def test_archive_and_restore_are_reversible_and_restore_comes_back_paused(self):
        registry = self.registry()
        registry.set_archived('vadoostan_website', True)
        catalog = SourceCatalog(self.config)
        self.assertNotIn('vadoostan_website', {v.id for v in catalog.list()})
        self.assertTrue(catalog.get('vadoostan_website').archived)
        with self.assertRaises(RegistryError):
            registry.set_enabled('vadoostan_website', True)  # restore first
        restored = registry.set_archived('vadoostan_website', False)
        self.assertFalse(restored.source.archived)
        self.assertFalse(restored.source.enabled)
        self.assertTrue(registry.set_enabled('vadoostan_website', True).source.enabled)
        # Archiving a robots-blocked source keeps its policy reason after restore.
        registry.set_archived('davvvat_website', True)
        self.assertEqual(registry.set_archived('davvvat_website', False).source.disabled_reason, 'robots')

    def test_duplicates_are_refused_and_base_wins_after_a_pull(self):
        registry = self.registry()
        source = self.ig()
        registry.add(source)
        with self.assertRaises(RegistryError) as caught:
            registry.add(source)
        self.assertEqual(caught.exception.code, 'duplicate_id')
        with self.assertRaises(RegistryError) as caught:
            registry.add(replace(source, id='other_id_instagram'))  # same account, new id
        self.assertEqual(caught.exception.code, 'duplicate_source')
        # Upstream later ships the same account in the base file: no duplicate crawl, nothing lost.
        text = self.config.read_text(encoding='utf-8') + (
            '\n  - id: example_upstream\n    publisher_key: example\n    name: Example\n    type: instagram\n'
            '    url: https://www.instagram.com/example.account/\n    username: example.account\n    enabled: true\n')
        self.config.write_text(text, encoding='utf-8')
        ids = [s.id for s in load_sources(self.config)]
        self.assertIn('example_upstream', ids)
        self.assertNotIn('example_account_instagram', ids)
        self.assertIn('example_account_instagram', json.loads(self.overlay.read_text(encoding='utf-8'))['sources'][0]['id'])

    def test_atomic_write_keeps_a_backup_and_recovers_from_corruption(self):
        registry = self.registry()
        registry.add(self.ig())
        registry.set_enabled('vadoostan_instagram', False)
        backup = self.overlay.with_name(self.overlay.name + '.bak')
        self.assertTrue(backup.exists())
        self.overlay.write_text('{"version": 1, "sources": [', encoding='utf-8')  # torn write
        ids = {s.id for s in load_sources(self.config)}
        self.assertIn('example_account_instagram', ids)  # recovered from the last good version
        backup.unlink()
        with self.assertRaises(ValueError):
            load_sources(self.config)  # fail closed: never crawl with an unknown registry
        self.assertEqual(list(self.overlay.parent.glob('*.tmp')), [])

    def test_invalid_overlay_records_are_rejected_before_writing(self):
        self.overlay.write_text(json.dumps({'version': 1, 'sources': [{'id': '../x', 'publisher_key': 'p',
                                'name': 'n', 'type': 'instagram', 'url': 'https://www.instagram.com/x/',
                                'username': 'x'}], 'states': {}}), encoding='utf-8')
        with self.assertRaises(ValueError):
            load_sources(self.config)

    def test_no_overlay_means_exactly_the_base_registry(self):
        self.assertEqual(load_sources(self.config), load_base_sources(self.config))
        with mock.patch.dict(os.environ, {OVERLAY_ENV: 'none'}):
            self.registry().entries()
            with self.assertRaises(RegistryError):
                SourceRegistry(self.config).set_enabled('vadoostan_instagram', False)


# -- bot management flows -----------------------------------------------------------------
class ManagementFlowTests(BotFlowCase):
    def add(self, kind, text, mode='a'):
        return (callback(ui.ADD), callback(f'{ui.ADD}:{kind}'), text_message(text),
                lambda: callback(self.button(ui.SAVE)[:-1] + mode))

    def test_add_instagram_preview_save_and_no_crawl(self):
        runner = FakeRunner()
        ops = self.operations(runner=runner)
        self.session(*self.add('i', 'https://www.instagram.com/New.Account/'), ops=ops)
        preview = next(p['text'] for p in self.sends() if 'منبع جدید' in p['text'])
        for expected in ('نوع: Instagram', 'شناسه: <code>new_account_instagram</code>',
                         'آدرس: https://www.instagram.com/new.account/', 'وضعیت: نیازمند بررسی',
                         'آیا این منبع اضافه شود؟', 'هنوز بررسی نشده'):
            self.assertIn(expected, preview)
        self.assertIn('منبع ذخیره شد', self.edits()[-1]['text'])
        self.assertEqual(runner.calls, [])  # registration never crawls
        source = next(s for s in load_sources(self.config) if s.id == 'new_account_instagram')
        self.assertTrue(source.enabled)
        self.assertIn('new_account_instagram', ops.resolve_scope(None))  # same selection logic as crawls
        self.assertNotIn('password', json.dumps(self.fake.calls, ensure_ascii=False).lower())

    def test_invalid_input_keeps_the_step_then_valid_input_continues(self):
        self.session(callback(ui.ADD), callback(ui.ADD + ':i'), text_message('https://www.instagram.com/p/abc/'),
                     text_message('@vadoostan'), text_message('@fine_name'),
                     lambda: callback(self.button(ui.SAVE)[:-1] + 'p'))
        replies = [p['text'] for p in self.sends()]
        self.assertIn(ui.ERRORS['ig_not_profile'], replies[0])
        self.assertIn('مرحله ۲ از ۳', replies[0])
        self.assertIn('vadoostan_instagram', replies[1])
        self.assertIn('منبع جدید', replies[2])
        saved = next(s for s in load_sources(self.config) if s.id == 'fine_name_instagram')
        self.assertFalse(saved.enabled)
        self.assertEqual(saved.disabled_reason, 'owner')

    def test_unsupported_website_is_saved_inactive_and_never_runnable(self):
        ops = self.operations()
        holder = {}

        def forged_activate():
            preview = self.sends()[-1]
            holder['preview'] = preview
            saves = [b['callback_data'] for b in self.buttons(preview) if b['callback_data'].startswith(ui.SAVE)]
            holder['saves'] = saves
            return callback(saves[0][:-1] + 'a')  # a forged "activate" for this preview
        self.session(callback(ui.ADD), callback(ui.ADD + ':w'), text_message('https://example.org/events'),
                     forged_activate, ops=ops)
        self.assertIn('Adapter اختصاصی', holder['preview']['text'])
        self.assertEqual(len(holder['saves']), 1)
        self.assertTrue(holder['saves'][0].endswith(':p'))
        self.assertIn('این وب‌سایت ثبت شد، اما ساختار آن هنوز توسط GatherRadar پشتیبانی نمی‌شود',
                      self.edits()[-1]['text'])
        source = next(s for s in load_sources(self.config) if s.publisher_key == 'example_org')
        self.assertEqual((source.enabled, source.disabled_reason), (False, 'unsupported'))
        self.assertNotIn(source.id, ops.resolve_scope(None))
        with self.assertRaises(ValueError):
            ops.resolve_scope((source.id,))

    def test_disable_enable_archive_restore_and_history_is_untouched(self):
        history = {self.data / 'state' / 'gatherradar.sqlite3': b'db', self.data / 'raw' / 'x.jsonl': b'raw',
                   self.data / 'review' / 'GatherRadar.xlsx': b'xlsx', self.data / 'evidence' / 'ocr.jsonl': b'ocr'}
        for path, content in history.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        ops = self.operations()
        self.session(callback(ui.MANAGE_VIEW + 'vadoostan_instagram'),
                     callback(ui.MANAGE_ACT + 'd:vadoostan_instagram'), lambda: callback(self.button(ui.MANAGE_OK)),
                     callback(ui.MANAGE_ACT + 'x:vadoostan_instagram'), lambda: callback(self.button(ui.MANAGE_OK)),
                     ops=ops)
        archive_confirm = next(p['text'] for p in self.edits() if 'حذف منبع از فهرست' in p['text'])
        for expected in ('در Crawlهای آینده شرکت نمی‌کند', 'اطلاعات و اجراهای قبلی حفظ می‌شوند', 'آیا مطمئن هستید؟'):
            self.assertIn(expected, archive_confirm)
        labels = [b['text'] for p in self.edits() if 'حذف منبع از فهرست' in p['text'] for b in self.buttons(p)]
        self.assertIn('تأیید حذف', labels)
        self.assertIn('انصراف', labels)
        self.assertNotIn('vadoostan_instagram', ops.resolve_scope(None))
        self.assertNotIn('vadoostan_instagram', {v.id for v in ops.enabled_sources()})
        self.assertIn('vadoostan_instagram', {v.id for v in ui.filter_views(ops.catalog.all(), 'x')})
        self.session(callback(ui.MANAGE_ACT + 'r:vadoostan_instagram'), lambda: callback(self.button(ui.MANAGE_OK)),
                     callback(ui.MANAGE_ACT + 'e:vadoostan_instagram'), lambda: callback(self.button(ui.MANAGE_OK)),
                     ops=ops)
        self.assertIn('vadoostan_instagram', ops.resolve_scope(None))
        for path, content in history.items():
            self.assertEqual(path.read_bytes(), content)

    def test_robots_blocked_source_has_no_enable_button_and_forged_enable_is_refused(self):
        self.session(callback(ui.MANAGE_VIEW + 'davvvat_website'), callback(ui.MANAGE_ACT + 'e:davvvat_website'))
        detail = self.edits()[0]
        self.assertIn('robots.txt', detail['text'])
        self.assertFalse(any(b['callback_data'].startswith(ui.MANAGE_ACT + 'e:') for b in self.buttons(detail)))
        self.assertIn(ui.ERRORS['locked'], self.answers())
        self.assertFalse(next(s for s in load_sources(self.config) if s.id == 'davvvat_website').enabled)

    def test_enabling_a_local_website_rechecks_robots(self):
        ops = self.operations()
        proposal = ops.propose_source('website', 'https://jabama.events/all?city=isfahan')
        entry = ops.register_source(proposal, activate=False)
        self.robots_allowed = False
        with self.assertRaises(RegistryError) as caught:
            ops.change_source(entry.source.id, 'enable')
        self.assertEqual(caught.exception.code, 'robots_disallowed')
        self.robots_allowed = True
        self.assertTrue(ops.change_source(entry.source.id, 'enable').source.enabled)

    def test_one_time_confirmations_old_callbacks_and_forged_ids(self):
        ops = self.operations()
        holder = {}

        def confirm():
            holder['ok'] = self.button(ui.MANAGE_OK)
            return callback(holder['ok'])
        self.session(callback(ui.MANAGE_ACT + 'd:vadoostan_website'), confirm, lambda: callback(holder['ok']),
                     callback(ui.MANAGE_ACT + 'd:no_such_source'), callback(ui.MANAGE_VIEW + 'no_such_source'),
                     callback(ui.SAVE + 'deadbeef0000:a'), callback(ui.MANAGE_ACT + 'd:vadoostan_website'),
                     ops=ops)
        answers = self.answers()
        self.assertGreaterEqual(answers.count(ui.INVALID), 4)  # replayed nonce, forged ids, already disabled
        self.assertIn(ui.ERRORS['expired'], answers)  # a save with no live conversation commits nothing
        self.assertEqual(json.loads(self.overlay.read_text(encoding='utf-8'))['sources'], [])

    def test_expired_conversation_or_restart_commits_nothing(self):
        ops = self.operations()
        self.session(callback(ui.ADD), callback(ui.ADD + ':i'), text_message('@later_one'), ops=ops)
        save = self.button(ui.SAVE)
        self.handlers.conversation.started -= CONVERSATION_TTL + 1
        self.fake = Telegram()
        self.session(callback(save), ops=ops)  # a new process: no conversation in memory
        self.assertIn(ui.ERRORS['expired'], self.answers())
        self.assertFalse(self.overlay.exists())

    def test_cancel_and_back_leave_no_dead_end(self):
        self.session(callback(ui.ADD), callback(ui.ADD + ':w'), text_message('https://example.org/e'),
                     callback(ui.ADD_BACK), callback(ui.ADD_CANCEL), text_message('hello'))
        texts = [p['text'] for p in self.edits()]
        self.assertIn('مرحله ۲ از ۳', texts[-2])
        self.assertIn('چیزی ذخیره نشد', texts[-1])
        self.assertIn('برای شروع', self.sends()[-1]['text'])  # free text outside a conversation
        self.assertFalse(self.overlay.exists())

    def test_strangers_cannot_manage_or_add(self):
        actions = (ui.MANAGE, ui.MANAGE_LIST + 'l:0', ui.MANAGE_VIEW + 'vadoostan_website',
                   ui.MANAGE_ACT + 'd:vadoostan_website', ui.MANAGE_OK + 'deadbeef0000', ui.ADD, ui.ADD + ':i',
                   ui.SAVE + 'deadbeef0000:a', ui.SETTINGS)
        self.session(*(callback(a, STRANGER) for a in actions), text_message('@x_account', STRANGER))
        self.assertEqual(self.answers(), [ui.PRIVATE_ONLY] * len(actions))
        self.assertEqual(self.edits(), [])
        self.assertFalse(self.overlay.exists())

    def test_registry_changes_wait_for_the_running_crawl_and_its_scope_is_fixed(self):
        gate = threading.Event()
        runner = FakeRunner(block=gate)
        ops = self.operations(runner=runner)
        job = ops.start_crawl(None)
        try:
            with self.assertRaises(RegistryBusyError):
                ops.change_source('vadoostan_website', 'disable')
            proposal = ops.propose_source('instagram', '@during_crawl')
            with self.assertRaises(RegistryBusyError):
                ops.register_source(proposal, activate=True)
            self.session(callback(ui.MANAGE_ACT + 'd:vadoostan_website'), callback(ui.ADD), ops=ops)
            self.assertEqual(self.answers().count(ui.ERRORS['busy']), 2)
        finally:
            gate.set()
            ops.jobs.wait(5)
        self.assertEqual(runner.calls[0][0], job.scope)
        self.assertIn('vadoostan_website', load_sources(self.config)[2].id)

    def test_stale_selection_and_changed_snapshot_never_crawl_disabled_sources(self):
        runner = FakeRunner()
        ops = self.operations(runner=runner)
        holder = {}

        def disable_then_go():
            holder['go'] = self.button(ui.GO)
            SourceRegistry(self.config).set_enabled('vadoostan_website', False)  # e.g. from another device
            return callback(holder['go'])
        self.session(callback(ui.SELECT + 't:vadoostan_website:0'), callback(ui.SELECT + 't:jabama_events_website:0'),
                     callback(ui.SELECT + 'ok'), disable_then_go, ops=ops)
        self.assertEqual(runner.calls, [])
        self.assertTrue(any('تغییر کرده است' in (a or '') for a in self.answers()))
        self.fake = Telegram()
        self.session(callback(ui.CRAWL_ALL), lambda: callback(self.button(ui.GO)), ops=ops)
        (scope, all_enabled), = runner.calls
        self.assertNotIn('vadoostan_website', scope)
        self.assertNotIn('davvvat_website', scope)

    def test_cli_and_bot_read_the_same_registry(self):
        from gatherradar.cli import main
        ops = self.operations()
        ops.register_source(ops.propose_source('instagram', '@shared_view'), activate=True)
        ops.change_source('emrooz_events_instagram', 'archive')
        with mock.patch('sys.stdout', new_callable=__import__('io').StringIO) as out:
            self.assertEqual(main(['sources', 'list', '--config', str(self.config)]), 0)
        printed = out.getvalue()
        self.assertIn('shared_view_instagram\tinstagram\tenabled\tlocal', printed)
        self.assertNotIn('emrooz_events_instagram', printed)
        self.assertIn(f'All-enabled crawl would include {len(ops.resolve_scope(None))} source(s).', printed)


if __name__ == '__main__':
    unittest.main()
