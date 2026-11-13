import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
from platform_monitor import PlatformMonitor
from platform_worker import PLATFORMS, PROBES, credentials


class PlatformScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.calls = []
        self.probed = asyncio.Event()
        self.revision = 'initial'
        self.category = 'ok'
        self.passive = {}
        self.registered = list(PROBES)
        self.stop_after_first = False
        gap = patch('platform_monitor.PROBE_GAP_SECONDS', 0)
        gap.start()
        self.addCleanup(gap.stop)
        self.config = {'twitter_auth_token': 'test', 'twitter_ct0': 'test',
                       'xueqiu_cookie': 'xq_a_token=test', 'xianyu_cookie': '_m_h5_tk=test; _m_h5_tk_enc=test-enc; cookie2=test-session; unb=1'}

        async def runner(payload):
            self.calls.append(payload.copy())
            if payload['action'] == 'inventory':
                return {'timestamp': time.time(), 'registered': self.registered,
                        'credentials': {p: credentials(self.config, p) | {'revision': self.revision} for p in PLATFORMS},
                        'passive': self.passive}
            if payload['action'] == 'probe':
                self.probed.set()
                if self.stop_after_first:
                    self.monitor.configure_auto(False, 30)
                return {'category': self.category, 'elapsed_ms': 10}
            raise AssertionError('unexpected action')

        self.runner = runner
        self.monitor = PlatformMonitor(Path(self.temp.name) / 'platforms.sqlite3', runner)
        await self.monitor.refresh()

    async def asyncTearDown(self):
        await self.monitor.close()
        self.temp.cleanup()

    async def test_background_loop_probes_without_a_browser_request(self):
        await self.monitor.start()
        await asyncio.wait_for(self.probed.wait(), .5)

    async def test_expired_result_is_distinguished_from_never_checked(self):
        with patch('platform_monitor.time.time', return_value=time.time() - 7200):
            self.monitor.insert_check('xueqiu', 'xueqiu_quote', 'ok', 10, self.revision)
        row = next(p for p in self.monitor.snapshot()['platforms'] if p['id'] == 'xueqiu')
        self.assertIn('已过期', row['message'])
        row = next(p for p in self.monitor.snapshot()['platforms'] if p['id'] == 'twitter')
        self.assertIn('尚未检测', row['message'])

    async def test_auto_results_are_recorded_and_restart_does_not_repeat(self):
        self.monitor.run_due_checks()
        await self.monitor.job_task
        self.assertEqual(self.monitor.job['passed'], 10)
        self.assertTrue(all(r['source'] == 'auto' for r in self.monitor.snapshot()['history']['rows']))
        count = len(self.calls)
        self.monitor.run_due_checks()
        self.assertEqual(len(self.calls), count)
        reopened = PlatformMonitor(self.monitor.path, self.runner)
        await reopened.refresh()
        self.assertIsNone(reopened.run_due_checks())
        self.assertIsNone(reopened.job_task)
        await reopened.close()

    async def test_busy_native_checker_does_not_create_evidence_or_delay_a_whole_cycle(self):
        async def busy_runner(payload):
            if payload['action'] == 'probe':
                return {'tool': payload['tool'], 'deferred': True}
            return await self.runner(payload)
        self.monitor.runner = busy_runner
        self.monitor.run_due_checks()
        await self.monitor.job_task
        self.assertEqual(self.monitor.snapshot()['history']['total'], 0)
        plan = self.monitor.schedule_for('twitter_me', self.revision)
        self.assertEqual(plan['last_at'], 0)
        self.assertLessEqual(plan['next_at'], time.time() + 60)
        self.assertEqual(self.monitor.job['status'], 'error')

    async def test_policy_persists_and_reads_and_settings_never_probe(self):
        self.monitor.configure_auto(False, 60)
        count = len(self.calls)
        for _ in range(3):
            self.monitor.snapshot()
            self.monitor.run_due_checks()
        self.assertEqual(len(self.calls), count)
        reopened = PlatformMonitor(self.monitor.path, self.runner)
        self.assertEqual(reopened.auto_settings()['enabled'], False)
        self.assertEqual(reopened.auto_settings()['interval_minutes'], 60)
        await reopened.close()
        for minutes in (0, 1, 5, 30.5, True):
            with self.assertRaises(ValueError):
                self.monitor.configure_auto(True, minutes)

    async def test_business_counts_do_not_replace_unified_checks_or_clear_failures(self):
        now = time.time()
        self.passive['xueqiu'] = {'calls': 3, 'category': 'ok', 'last_success_at': now}
        await self.monitor.refresh()
        self.monitor.run_due_checks()
        await self.monitor.job_task
        self.assertTrue(any(c.get('tool', '').startswith('xueqiu_') for c in self.calls))
        row = next(p for p in self.monitor.snapshot()['platforms'] if p['id'] == 'xueqiu')
        self.assertEqual(row['evidence_source'], 'mcp_check')
        self.monitor.record_schedule('xueqiu_quote', self.revision, 'risk')
        self.monitor.insert_check('xueqiu', 'xueqiu_quote', 'risk', 10, self.revision)
        self.passive['xueqiu']['last_success_at'] = time.time() + 1
        await self.monitor.refresh()
        row = next(p for p in self.monitor.snapshot()['platforms'] if p['id'] == 'xueqiu')
        self.assertEqual(row['category'], 'risk')
        self.assertEqual(row['monitoring']['state'], 'backoff')

    async def test_failure_backoff_survives_restart_and_manual_success_restores_interval(self):
        self.category = 'rate_limit'
        now = time.time()
        with patch('platform_monitor.time.time', return_value=now):
            self.monitor.run_due_checks()
            await self.monitor.job_task
        plan = self.monitor.schedule_for('twitter_me', self.revision)
        self.assertEqual(plan['failures'], 1)
        self.assertEqual(plan['next_at'], now + 3600)
        with patch('platform_monitor.time.time', return_value=now + 1801):
            self.assertIsNone(self.monitor.run_due_checks())
        with patch('platform_monitor.time.time', return_value=now + 3601):
            self.monitor.run_due_checks()
            await self.monitor.job_task
        self.assertEqual(self.monitor.schedule_for('twitter_me', self.revision)['failures'], 2)
        reopened = PlatformMonitor(self.monitor.path, self.runner)
        self.assertEqual(reopened.schedule_for('twitter_me', self.revision)['failures'], 2)
        await reopened.close()
        self.category = 'ok'
        with patch('platform_monitor.time.time', return_value=now + 3700):
            self.monitor.start_checks('twitter', 'twitter_me')
            await self.monitor.job_task
        plan = self.monitor.schedule_for('twitter_me', self.revision)
        self.assertEqual(plan['failures'], 0)
        self.assertEqual(plan['next_at'], now + 3700 + 1800)

    async def test_old_failed_tool_is_not_cleared_by_another_tools_recent_success(self):
        with patch('platform_monitor.time.time', return_value=time.time() - 3600):
            self.monitor.insert_check('reddit', 'reddit_search', 'risk', 10, self.revision)
        self.monitor.insert_check('reddit', 'reddit_subreddit_posts', 'ok', 10, self.revision, source='auto')
        self.passive['reddit'] = {'calls': 3, 'category': 'ok', 'last_success_at': time.time() + 1}
        await self.monitor.refresh()
        row = next(p for p in self.monitor.snapshot()['platforms'] if p['id'] == 'reddit')
        self.assertEqual(row['category'], 'risk')
        self.assertEqual(row['message'], '部分接口旧异常待复测')
        self.assertEqual(row['freshness'], 'stale')

    async def test_pause_during_auto_job_stops_remaining_requests(self):
        self.stop_after_first = True
        self.monitor.run_due_checks()
        await self.monitor.job_task
        self.assertEqual(self.monitor.job['completed'], 1)
        self.assertEqual(self.monitor.job['status'], 'cancelled')

    async def test_missing_credentials_unregistered_and_mcp_outage_skip_auto(self):
        self.config['twitter_auth_token'] = ''
        self.registered = [n for n in PROBES if not n.startswith('github_')]
        await self.monitor.refresh()
        self.monitor.run_due_checks()
        await self.monitor.job_task
        names = [c['tool'] for c in self.calls if c['action'] == 'probe']
        self.assertFalse(any(n.startswith(('twitter_', 'github_')) for n in names))
        self.monitor.connected = False
        self.assertIsNone(self.monitor.run_due_checks())

    async def test_credential_revision_invalidates_schedule_and_reprobes_new_credentials(self):
        self.monitor.run_due_checks()
        await self.monitor.job_task
        self.revision = 'new-credential'
        await self.monitor.refresh()
        row = next(p for p in self.monitor.snapshot()['platforms'] if p['id'] == 'twitter')
        self.assertEqual(row['message'], '凭证变更，待复测')
        self.assertTrue(all(e['freshness'] == 'credentials_changed' for e in row['endpoints']))
        with patch('platform_monitor.time.time', return_value=time.time() + 61):
            self.monitor.run_due_checks()
            await self.monitor.job_task
        row = next(p for p in self.monitor.snapshot()['platforms'] if p['id'] == 'twitter')
        self.assertFalse(row['credential_changed'])
        self.assertEqual(row['category'], 'ok')
