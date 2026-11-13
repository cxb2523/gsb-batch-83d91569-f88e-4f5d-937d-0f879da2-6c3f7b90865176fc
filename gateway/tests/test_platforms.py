import asyncio
import copy
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
from platform_monitor import PlatformMonitor, PlatformError
from platform_worker import PLATFORMS, PROBES, classify, credentials, parse_health, update_credentials, result_failed


class PlatformPureTests(unittest.TestCase):
    def test_latest_success_is_not_overridden_by_an_older_passive_error(self):
        summary = parse_health('- reddit: credential=ok, calls=3 (ok=2 fail=1), last_success=1m ago last_error=2h ago: Reddit API error: 403 forbidden')
        self.assertEqual(summary['reddit']['category'], 'ok')

    def test_sdk_error_field_supports_v2_python_names_and_legacy_results(self):
        self.assertTrue(result_failed(types.SimpleNamespace(is_error=True)))
        self.assertFalse(result_failed(types.SimpleNamespace(is_error=False)))
        self.assertTrue(result_failed(types.SimpleNamespace(isError=True)))

    def test_failure_classification_does_not_guess_expired_cookies_from_403_or_risk(self):
        for text, expected in [('Reddit API error: 403 forbidden', 'forbidden'),
                               ('闲鱼接口返回错误: RGV587 token expired', 'risk'),
                               ('GitHub API error: HTTP 429', 'rate_limit'),
                               ('Error: unauthorized HTTP 401', 'auth'),
                               ('Error: connection timed out', 'network'),
                               ('Xueqiu API error: HTTP 503', 'upstream'),
                               ('Search: no results', 'ok')]:
            self.assertEqual(classify(text), expected)
        self.assertEqual(classify('Search: OpenAI\nA user says API error 401'), 'ok')

    def test_passive_summary_does_not_leak_error_text_or_claim_old_success_is_current(self):
        text = '- reddit: credential=ok, calls=3 (ok=1 fail=2), last_success=6.0d ago last_error=3h ago: Reddit API error: 403 Cookie=SECRET'
        summary = parse_health(text)['reddit']
        self.assertEqual(summary['category'], 'forbidden')
        self.assertGreater(time.time() - summary['last_success_at'], 5 * 86400)
        self.assertNotIn('SECRET', json.dumps(summary))

    def test_cookie_field_names_are_checked_without_returning_values(self):
        c = {'xianyu_cookie': 'm_h5_tk=SECRET; unb=123'}
        meta = credentials(c, 'xianyu')
        self.assertFalse(meta['configured'])
        self.assertIn('_m_h5_tk', meta['missing'])
        self.assertNotIn('SECRET', json.dumps(meta))
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'SECRET'}):
            self.assertEqual(credentials({}, 'github')['locked'], ['github_tokens'])


class PlatformMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'platforms.sqlite3'
        self.calls = []
        self.revision = 'initial'
        self.outage = False
        self.config = {'twitter_auth_token': 'SECRET', 'twitter_ct0': 'SECRET', 'xueqiu_cookie': 'xq_a_token=SECRET',
                       'xianyu_cookie': '_m_h5_tk=SECRET; _m_h5_tk_enc=test-enc; cookie2=test-session; unb=123', 'reddit_cookie': 'reddit_session=SECRET'}
        async def runner(payload):
            self.calls.append(copy.deepcopy(payload))
            if self.outage:
                raise PlatformError('offline')
            if payload['action'] == 'inventory':
                return {'timestamp': time.time(), 'registered': list(PROBES) + ['xianyu_confirm_delivery'],
                        'credentials': {p: credentials(self.config, p) | {'revision': self.revision} for p in PLATFORMS},
                        'passive': {'reddit': {'calls': 3, 'ok': 1, 'fail': 2, 'category': 'forbidden', 'last_error_at': time.time() - 7200}}}
            if payload['action'] == 'credentials':
                self.revision = 'new'
                self.config.update(payload['updates'])
                return {'saved': True, 'reloaded': True}
            if payload['action'] == 'probe':
                return {'category': 'ok', 'elapsed_ms': 100}
            raise AssertionError('unexpected action')
        self.runner = runner
        self.monitor = PlatformMonitor(self.path, runner)
        await self.monitor.refresh()

    async def asyncTearDown(self):
        await self.monitor.close()
        self.temp.cleanup()

    async def test_reddit_backend_can_switch_and_rejects_arbitrary_commands(self):
        for backend in ('opencli', 'http'):
            result = await self.monitor.update_credentials('reddit', {'reddit_backend': backend})
            self.assertTrue(result['saved'])
            self.assertEqual(self.config['reddit_backend'], backend)
        for backend in ('latest', 'sh -c echo', '../browser'):
            with self.assertRaises(ValueError):
                await self.monitor.update_credentials('reddit', {'reddit_backend': backend})

    async def test_browser_lifecycle_uses_fixed_actions_without_starting_platform_probes(self):
        async def browser_runner(payload):
            if payload['action'] == 'reddit_browser':
                self.calls.append(copy.deepcopy(payload))
                return {'reddit_runtime': {'backend': 'http', 'available': True, 'running': payload['operation'] == 'start'}}
            return await self.runner(payload)
        self.monitor.runner = browser_runner
        self.calls.clear()
        self.assertTrue((await self.monitor.reddit_browser('start'))['reddit_runtime']['running'])
        self.assertFalse((await self.monitor.reddit_browser('stop'))['reddit_runtime']['running'])
        self.assertEqual([p['action'] for p in self.calls], ['reddit_browser', 'reddit_browser'])
        self.assertFalse(self.monitor.snapshot()['reddit_runtime']['running'])
        with self.assertRaises(ValueError):
            await self.monitor.reddit_browser('open arbitrary page')

    async def test_refresh_and_repeated_reads_are_passive_only(self):
        for _ in range(3):
            self.monitor.snapshot()
            await self.monitor.refresh()
        self.assertTrue(all(c['action'] == 'inventory' for c in self.calls))
        reddit = next(p for p in self.monitor.snapshot()['platforms'] if p['id'] == 'reddit')
        self.assertEqual(reddit['category'], 'unknown', 'old failures must not be advertised as current')

    async def test_manual_checks_are_allowlisted_deduplicated_and_persisted(self):
        with self.assertRaises(ValueError):
            self.monitor.start_checks('xianyu', 'xianyu_confirm_delivery')
        job = self.monitor.start_checks('xueqiu')
        self.assertEqual(job['total'], 2)
        task = self.monitor.job_task
        self.monitor.start_checks('twitter')
        self.assertIs(task, self.monitor.job_task)
        await task
        self.assertEqual(self.monitor.job['passed'], 2)
        self.assertEqual([c['tool'] for c in self.calls if c['action'] == 'probe'], ['xueqiu_quote', 'xueqiu_hot_posts'])
        with self.assertRaises(PlatformError):
            self.monitor.start_checks()
        reopened = PlatformMonitor(self.path, self.runner)
        self.assertEqual(reopened.snapshot('xueqiu')['history']['total'], 2)
        await reopened.close()

    async def test_credential_change_invalidates_old_results_without_storing_secret(self):
        self.monitor.start_checks('xueqiu', 'xueqiu_quote')
        await self.monitor.job_task
        await self.monitor.update_credentials('xueqiu', {'xueqiu_cookie': 'xq_a_token=NEW-SECRET'})
        public = self.monitor.snapshot()
        xq = next(p for p in public['platforms'] if p['id'] == 'xueqiu')
        self.assertEqual(xq['category'], 'unknown')
        self.assertTrue(all(e['checked_at'] is None for e in xq['endpoints']))
        encoded = json.dumps(public)
        self.assertNotIn('SECRET', encoded)
        self.assertNotIn('revision', encoded)
        self.assertNotIn(b'NEW-SECRET', self.path.read_bytes())

    async def test_bridge_outage_keeps_cached_metadata_and_does_not_report_auth_failure(self):
        self.outage = True
        await self.monitor.refresh()
        self.assertFalse(self.monitor.snapshot()['mcp_connected'])
        self.assertEqual(len(self.monitor.snapshot()['platforms']), 5)
        self.monitor.start_checks('twitter')
        await self.monitor.job_task
        self.assertEqual(self.monitor.job['completed'], 1)
        self.assertEqual(self.monitor.snapshot()['history']['rows'][0]['category'], 'mcp')

    async def test_atomic_credential_update_retains_unrelated_config_and_excludes_env_overrides(self):
        import yaml
        path = Path(self.temp.name) / 'config.yaml'
        path.write_text(yaml.safe_dump({'xueqiu_cookie': 'old', 'twitter_watchlist': ['example']}))
        fake = types.ModuleType('webmirage.config')
        fake.CONFIG_FILE = path
        fake.get_config = lambda: yaml.safe_load(path.read_text())
        session = types.SimpleNamespace()
        async def call(*args):
            return types.SimpleNamespace(isError=False, content=[types.SimpleNamespace(text='Reloaded')])
        session.call_tool = call
        with patch.dict(sys.modules, {'webmirage.config': fake}):
            result = await update_credentials(session, {'platform': 'xueqiu', 'updates': {'xueqiu_cookie': 'xq_a_token=NEW'}}, {'webmirage_reload_config'})
            self.assertTrue(result['saved'])
            self.assertEqual(yaml.safe_load(path.read_text())['twitter_watchlist'], ['example'])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with patch.dict(os.environ, {'XUEQIU_COOKIE': 'override'}):
                result = await update_credentials(session, {'platform': 'xueqiu', 'updates': {'xueqiu_cookie': 'other'}}, {'webmirage_reload_config'})
                self.assertFalse(result['saved'])
            async def broken(*args):
                raise RuntimeError('private detail')
            session.call_tool = broken
            before = path.read_bytes()
            with self.assertRaises(RuntimeError):
                await update_credentials(session, {'platform': 'xueqiu', 'updates': {'xueqiu_cookie': 'bad'}}, {'webmirage_reload_config'})
            self.assertEqual(path.read_bytes(), before)

    async def test_reddit_session_value_preserves_other_cookies_and_rolls_back(self):
        import yaml
        path = Path(self.temp.name) / 'reddit-config.yaml'
        path.write_text(yaml.safe_dump({'reddit_cookie': 'other=keep%3D; reddit_session=old; prefs=a=b==; reddit_session=duplicate',
                                        'twitter_watchlist': ['example']}))
        fake = types.ModuleType('webmirage.config')
        fake.CONFIG_FILE = path
        fake.get_config = lambda: yaml.safe_load(path.read_text())
        calls = []
        async def call(name, args):
            calls.append((name, args))
            return types.SimpleNamespace(is_error=False, content=[types.SimpleNamespace(text='Reloaded')])
        session = types.SimpleNamespace(call_tool=call)
        payload = {'platform': 'reddit', 'updates': {'reddit_session': 'new%2Fvalue==', 'token_v2': 'token==', 'csrf_token': 'csrf', 'session_tracker': 'tracker', 'loid': 'id%3D', 'edgebucket': 'bucket', 'csv': '2'}}
        with patch.dict(sys.modules, {'webmirage.config': fake}):
            result = await update_credentials(session, payload, {'webmirage_reload_config'})
            self.assertTrue(result['saved'])
            config = yaml.safe_load(path.read_text())
            self.assertEqual(config['reddit_cookie'], 'other=keep%3D; prefs=a=b==; reddit_session=new%2Fvalue==; token_v2=token==; csrf_token=csrf; session_tracker=tracker; loid=id%3D; edgebucket=bucket; csv=2')
            self.assertNotIn('reddit_session', config)
            self.assertEqual(config['twitter_watchlist'], ['example'])
            self.assertEqual(calls, [('webmirage_reload_config', {})])
            self.assertNotIn('new%2Fvalue', json.dumps(result))
            before = path.read_bytes()
            with patch.dict(os.environ, {'REDDIT_COOKIE': 'override'}):
                self.assertFalse((await update_credentials(session, payload, {'webmirage_reload_config'}))['saved'])
            self.assertEqual(path.read_bytes(), before)
            for updates in ({'reddit_session': 'reddit_session=wrong'}, {'reddit_session': 'value; other=injection'},
                            {'reddit_session': 'value', 'reddit_cookie': 'reddit_session=conflict'}):
                with self.assertRaises(ValueError):
                    await update_credentials(session, {'platform': 'reddit', 'updates': updates}, {'webmirage_reload_config'})
                self.assertEqual(path.read_bytes(), before)
            async def broken(*args):
                raise RuntimeError('private detail')
            session.call_tool = broken
            with self.assertRaises(RuntimeError):
                await update_credentials(session, {'platform': 'reddit', 'updates': {'reddit_session': 'failed-new'}}, {'webmirage_reload_config'})
            self.assertEqual(path.read_bytes(), before)

    async def test_monitor_only_accepts_session_value_for_reddit(self):
        await self.monitor.update_credentials('reddit', {'reddit_session': 'VALUE-ONLY'})
        self.assertTrue(any(c.get('updates') == {'reddit_session': 'VALUE-ONLY'} for c in self.calls))
        for platform, updates in [('xueqiu', {'reddit_session': 'value'}),
                                  ('reddit', {'reddit_session': 'reddit_session=wrong'})]:
            before = len(self.calls)
            with self.assertRaises(ValueError):
                await self.monitor.update_credentials(platform, updates)
            self.assertEqual(len(self.calls), before)

    async def test_other_platform_value_updates_merge_lock_and_rollback(self):
        import yaml
        cases = [
            ('xueqiu', 'xueqiu_cookie', 'device_id=keep%3D; xq_a_token=old; acw_tc=keep',
             {'xq_a_token': 'new%2F=='}, 'device_id=keep%3D; acw_tc=keep; xq_a_token=new%2F==', 'XUEQIU_COOKIE'),
            ('xianyu', 'xianyu_cookie', '_m_h5_tk=old; unb=1; cookie2=keep==; sgcookie=keep%2F',
             {'_m_h5_tk': 'new_123456', 'unb': '2', '_m_h5_tk_enc': 'encoded%3D', 'cookie2': 'new-session=='},
             'sgcookie=keep%2F; _m_h5_tk=new_123456; unb=2; _m_h5_tk_enc=encoded%3D; cookie2=new-session==', 'XIANYU_COOKIE'),
            ('twitter', 'twitter_auth_token', 'old', {'twitter_auth_token': 'new-auth', 'twitter_ct0': 'new-csrf'}, 'new-auth', 'TWITTER_AUTH_TOKEN'),
            ('github', 'github_tokens', ['old'], {'github_tokens': 'new-token'}, ['new-token'], 'GITHUB_TOKEN'),
        ]
        for platform, field, old, updates, expected, env in cases:
            with self.subTest(platform=platform):
                path = Path(self.temp.name) / f'{platform}-values.yaml'
                path.write_text(yaml.safe_dump({field: old, 'twitter_watchlist': ['keep']}))
                fake = types.ModuleType('webmirage.config')
                fake.CONFIG_FILE = path
                fake.get_config = lambda: yaml.safe_load(path.read_text())
                async def call(name, args):
                    self.assertEqual((name, args), ('webmirage_reload_config', {}))
                    return types.SimpleNamespace(is_error=False, content=[types.SimpleNamespace(text='Reloaded')])
                session = types.SimpleNamespace(call_tool=call)
                payload = {'platform': platform, 'updates': updates}
                with patch.dict(sys.modules, {'webmirage.config': fake}):
                    result = await update_credentials(session, payload, {'webmirage_reload_config'})
                    self.assertTrue(result['saved'])
                    config = yaml.safe_load(path.read_text())
                    self.assertEqual(config[field], expected)
                    self.assertEqual(config['twitter_watchlist'], ['keep'])
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    for key in updates:
                        if key != field and key not in ('twitter_ct0',):
                            self.assertNotIn(key, config)
                    before = path.read_bytes()
                    with patch.dict(os.environ, {env: 'override'}):
                        self.assertFalse((await update_credentials(session, payload, {'webmirage_reload_config'}))['saved'])
                    self.assertEqual(path.read_bytes(), before)
                    async def broken(*args):
                        raise RuntimeError('private details')
                    session.call_tool = broken
                    with self.assertRaises(RuntimeError):
                        await update_credentials(session, payload, {'webmirage_reload_config'})
                    self.assertEqual(path.read_bytes(), before)

    async def test_all_platforms_reject_wrong_value_formats_before_bridge(self):
        cases = [('xueqiu', {'xq_a_token': 'xq_a_token=value'}),
                 ('xueqiu', {'xq_a_token': 'value', 'xueqiu_cookie': 'xq_a_token=other'}),
                 ('xianyu', {'unb': 'unb=1'}), ('xianyu', {'sgcookie': 'value; unb=1'}),
                 ('twitter', {'twitter_ct0': 'ct0=value'}), ('github', {'github_tokens': 'Bearer value'}),
                 ('reddit', {'xq_a_token': 'wrong-platform'}),
                 ('xianyu', {key: 'x' * 15000 for key in ('_m_h5_tk', 'unb', 'sgcookie')})]
        for platform, updates in cases:
            with self.subTest(platform=platform, fields=list(updates)):
                count = len(self.calls)
                with self.assertRaises(ValueError):
                    await self.monitor.update_credentials(platform, updates)
                self.assertEqual(len(self.calls), count)
