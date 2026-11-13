import asyncio
import json
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
from webmirage.check_health import HealthChecks
from webmirage.checks import CHECK_TOOL, PROBES
sys.path.insert(0, str(Path(__file__).parents[1]))
from platform_worker import decode_health_report, probe_health, credentials
from platform_monitor import PlatformMonitor


class FakePlatform:
    name = 'xianyu'

    def __init__(self):
        self.calls = []
        self.available = True
        self.wait = None

    def is_available(self):
        return self.available

    def get_tool_definitions(self):
        return [{'name': name} for name in PROBES if name.startswith('xianyu_')]

    async def handle_call(self, name, arguments):
        self.calls.append((name, arguments))
        if self.wait:
            await self.wait.wait()
        return '闲鱼接口错误: 闲鱼风控拦截(RGV587)，token 可能过期 SECRET-RESPONSE' if name.endswith('search_products') else '你的闲鱼账号下没有在售商品。'


class UnifiedHealthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.platform = FakePlatform()
        self.config = {'xianyu_cookie': '_m_h5_tk=SECRET-CREDENTIAL; _m_h5_tk_enc=test-enc; cookie2=test-session; unb=1'}
        self.path = Path(self.temp.name) / 'checks.sqlite3'
        self.checker = HealthChecks(lambda: [self.platform], self.path, lambda: self.config)
        self.checker.probe_gap = 0

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_real_business_failure_and_independent_success_are_structured_and_private(self):
        report = await self.checker.run({'platform': 'xianyu'})
        self.assertEqual(report['checker'], CHECK_TOOL)
        self.assertEqual([r['category'] for r in report['checks']], ['risk', 'ok'])
        self.assertEqual(len(report['history']), 2)
        self.assertNotIn('SECRET', json.dumps(report))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    async def test_status_is_passive_and_history_survives_restart(self):
        self.assertEqual((await self.checker.run({'mode': 'status'}))['checks'], [])
        self.assertEqual(self.platform.calls, [])
        first = await self.checker.run({'tool': 'xianyu_get_items'})
        reopened = HealthChecks(lambda: [self.platform], self.path, lambda: self.config)
        second = await reopened.run({'mode': 'status', 'after_id': first['cursor']})
        self.assertEqual(first['store_id'], second['store_id'])
        self.assertEqual(first['checks'][0]['id'], second['checks'][0]['id'])
        self.assertEqual(second['history'], [])
        self.assertEqual(len(self.platform.calls), 1)

    async def test_cooldown_is_shared_across_callers_and_restarts(self):
        first = await self.checker.run({'tool': 'xianyu_search_products'})
        reopened = HealthChecks(lambda: [self.platform], self.path, lambda: self.config)
        second = await reopened.run({'tool': 'xianyu_search_products'})
        self.assertEqual(first['checks'][0]['id'], second['checks'][0]['id'])
        self.assertTrue(second['checks'][0]['cached'])
        self.assertEqual(len(self.platform.calls), 1)

    async def test_credentials_change_invalidates_cache_without_exposing_values(self):
        first = await self.checker.run({'tool': 'xianyu_get_items'})
        self.config['xianyu_cookie'] = '_m_h5_tk=NEW-SECRET; _m_h5_tk_enc=new-enc; cookie2=new-session; unb=2'
        status = await self.checker.run({'mode': 'status'})
        self.assertEqual(status['checks'], [])
        self.assertFalse(status['history'][0]['credential_current'])
        second = await self.checker.run({'tool': 'xianyu_get_items'})
        self.assertNotEqual(first['checks'][0]['id'], second['checks'][0]['id'])
        self.assertNotIn('SECRET', json.dumps(second))

    async def test_reddit_backend_change_invalidates_cooldown_and_history_is_labeled(self):
        self.platform.name = 'reddit'
        self.platform.get_tool_definitions = lambda: [{'name': n} for n in PROBES if n.startswith('reddit_')]
        self.config = {'reddit_cookie': 'SECRET'}
        first = await self.checker.run({'tool': 'reddit_search'})
        self.assertEqual(first['checks'][0]['backend'], 'http')
        self.config['reddit_backend'] = 'opencli'
        self.assertEqual((await self.checker.run({'mode': 'status', 'platform': 'reddit'}))['checks'], [])
        second = await self.checker.run({'tool': 'reddit_search'})
        self.assertEqual(second['checks'][0]['backend'], 'opencli')
        self.assertNotEqual(second['checks'][0]['id'], first['checks'][0]['id'])
        self.assertFalse(second['checks'][0]['cached'])
        self.assertEqual(len(self.platform.calls), 2)

    async def test_restoring_backend_recognizes_previously_imported_native_history(self):
        self.platform.name = 'reddit'
        self.platform.get_tool_definitions = lambda: [{'name': n} for n in PROBES if n.startswith('reddit_')]
        self.config = {'reddit_cookie': 'SECRET'}
        first = await self.checker.run({'tool': 'reddit_search'})
        self.config['reddit_backend'] = 'opencli'
        await self.checker.run({'tool': 'reddit_search'})
        async def inventory(payload):
            report = await self.checker.run({'mode': 'status', 'after_id': payload.get('after_id', 0)})
            return {'credentials': {'reddit': credentials(self.config, 'reddit')}, 'registered': ['reddit_search'],
                    'active_health': decode_health_report(SimpleNamespace(is_error=False, structured_content=report))}
        monitor = PlatformMonitor(Path(self.temp.name) / 'gateway-rollback.sqlite3', inventory)
        try:
            await monitor.refresh()
            self.config['reddit_backend'] = 'http'
            await monitor.refresh()
            state = monitor.snapshot('reddit')
            reddit = next(p for p in state['platforms'] if p['id'] == 'reddit')
            self.assertEqual(reddit['checked_count'], 1)
            self.assertEqual(next(e for e in reddit['endpoints'] if e['name'] == 'reddit_search')['backend'], 'http')
            self.assertEqual(len(state['history']['rows']), 2)
        finally:
            await monitor.close()

    async def test_write_tools_and_unknown_selectors_never_make_a_request(self):
        for args in ({'tool': 'xianyu_confirm_delivery'}, {'platform': 'unknown'},
                     {'platform': 'github', 'tool': 'xianyu_get_items'}, {'after_id': True}):
            with self.assertRaises(ValueError):
                await self.checker.run(args)
        self.assertEqual(self.platform.calls, [])

    async def test_concurrent_request_is_pending_without_recording_a_false_failure(self):
        self.platform.wait = asyncio.Event()
        running = asyncio.create_task(self.checker.run({'tool': 'xianyu_get_items'}))
        for _ in range(100):
            if self.platform.calls:
                break
            await asyncio.sleep(.001)
        second = await self.checker.run({'tool': 'xianyu_search_products'})
        self.assertTrue(second['checks'][0]['pending'])
        self.assertEqual(second['history'], [])
        self.platform.wait.set()
        await running
        self.assertEqual(len(self.platform.calls), 1)

    async def test_missing_and_timeout_are_explicit(self):
        self.platform.available = False
        result = await self.checker.run({'tool': 'xianyu_get_items'})
        self.assertEqual(result['checks'][0]['category'], 'missing')
        self.assertEqual(self.platform.calls, [])
        self.platform.available = True
        self.platform.wait = asyncio.Event()
        self.checker.timeout = .01
        result = await self.checker.run({'tool': 'xianyu_search_products'})
        self.assertEqual(result['checks'][0]['category'], 'network')

    async def test_gateway_and_mcp_share_results_without_duplicate_probes_or_history(self):
        checker = self.checker
        calls = []
        class Session:
            async def call_tool(self, name, arguments, **options):
                calls.append(name)
                self_report = await checker.run(arguments)
                return SimpleNamespace(is_error=False, structured_content=self_report)
        session = Session()
        direct = await checker.run({'tool': 'xianyu_search_products'})
        async def runner(payload):
            if payload['action'] == 'probe':
                return await probe_health(session, payload['tool'])
            result = await session.call_tool(CHECK_TOOL, {'mode': 'status', 'after_id': payload.get('after_id', 0)})
            return {'registered': list(PROBES), 'timestamp': time.time(), 'check_tool_available': True,
                    'credentials': {'xianyu': credentials(self.config, 'xianyu')},
                    'passive': {'xianyu': {'category': 'ok', 'calls': 130, 'last_success_at': time.time()}},
                    'active_health': decode_health_report(result)}
        monitor = PlatformMonitor(Path(self.temp.name) / 'gateway.sqlite3', runner)
        try:
            await monitor.refresh()
            platform = next(p for p in monitor.snapshot()['platforms'] if p['id'] == 'xianyu')
            self.assertEqual(platform['category'], 'risk')
            self.assertEqual(platform['evidence_source'], 'mcp_check')
            self.assertEqual(monitor.snapshot('xianyu')['history']['total'], 1)
            await monitor._check(['xianyu_search_products'], 'manual')
            report = monitor.snapshot('xianyu')
            self.assertEqual(report['history']['total'], 1)
            self.assertEqual(report['history']['rows'][0]['source'], 'mcp')
            self.assertEqual(report['history']['rows'][0]['timestamp'], direct['checks'][0]['timestamp'])
            self.assertEqual(monitor.schedule_for('xianyu_search_products', credentials(self.config, 'xianyu')['revision'])['failures'], 1)
            self.assertEqual(len(self.platform.calls), 1)
            self.assertTrue(all(name == CHECK_TOOL for name in calls))
        finally:
            await monitor.close()

    async def test_invalid_or_failed_protocol_is_not_accepted_as_a_healthy_interface(self):
        report = await self.checker.run({'tool': 'xianyu_get_items'})
        for field, value in [('checker', 'other'), ('schema_version', 99), ('store_id', 'secret')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                decode_health_report(SimpleNamespace(is_error=False, structured_content={**report, field: value}))
        with self.assertRaises(ValueError):
            decode_health_report(SimpleNamespace(is_error=True, structured_content=report))
        bad = json.loads(json.dumps(report))
        bad['checks'][0]['category'] = 'anything'
        with self.assertRaises(ValueError):
            decode_health_report(SimpleNamespace(is_error=False, structured_content=bad))
