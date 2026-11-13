"""Regressions for successful MCP/HTTP transport carrying failed business results."""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2]))
from platform_monitor import PlatformMonitor
from platform_worker import PROBES, classify, parse_health
from webmirage import health


RISK = '闲鱼接口错误: 闲鱼风控拦截(RGV587)：重试后仍被拒绝。通常是请求频率过高或 cookie 签名 token(_m_h5_tk) 过期。'


class BusinessErrorTests(unittest.TestCase):
    def test_xianyu_soft_failure_is_not_a_successful_business_call(self):
        self.assertTrue(health.looks_like_error(RISK))

    def test_gateway_probe_does_not_require_mcp_is_error_for_xianyu_failure(self):
        self.assertEqual(classify(RISK, False), 'risk')
        self.assertEqual(classify('闲鱼接口错误: 闲鱼接口返回错误: FAIL_SYS_TOKEN_EXOIRED::令牌过期', False), 'auth')
        self.assertEqual(classify('闲鱼接口错误: 闲鱼接口返回非 JSON: invalid', False), 'interface')

    def test_successful_search_text_mentioning_a_risk_is_not_failed(self):
        result = '搜索结果：RGV587 风控说明，共 2 个商品。'
        self.assertFalse(health.looks_like_error(result))
        self.assertEqual(classify(result), 'ok')


class BusinessEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_passive_failure_cannot_impersonate_a_unified_check_result(self):
        with tempfile.TemporaryDirectory() as td:
            now = time.time()
            monitor = PlatformMonitor(Path(td) / 'platforms.sqlite3')
            try:
                monitor.connected = True
                monitor.cache = {'registered': list(PROBES), 'credentials': {'xianyu': {
                    'configured': True, 'revision': 'same', 'anonymous': False}},
                    'passive': parse_health('- xianyu: credential=ok, calls=3 (ok=2 fail=1), last_success=5m ago last_error=1s ago: ' + RISK)}
                for name in PROBES:
                    if name.startswith('xianyu_'):
                        monitor.insert_check('xianyu', name, 'ok', 10, 'same')
                # Recorded active checks predate the observed business failure.
                with monitor.db() as db:
                    db.execute('UPDATE checks SET timestamp=?', (now - 60,))
                platform = next(p for p in monitor.snapshot()['platforms'] if p['id'] == 'xianyu')
                self.assertEqual(platform['category'], 'ok')
                self.assertEqual(platform['evidence_source'], 'mcp_check')
                self.assertEqual(monitor.platform_plan('xianyu')['reuse_until'], 0)
                # Invalidated legacy evidence and passive counters cannot
                # substitute for the authoritative structured checker.
                with monitor.db() as db:
                    db.execute('UPDATE checks SET classifier_version=0')
                platform = next(p for p in monitor.snapshot()['platforms'] if p['id'] == 'xianyu')
                self.assertEqual(platform['category'], 'unknown')
            finally:
                await monitor.close()

    async def test_legacy_success_counts_and_old_probes_cannot_keep_xianyu_green(self):
        with tempfile.TemporaryDirectory() as td:
            monitor = PlatformMonitor(Path(td) / 'platforms.sqlite3')
            try:
                monitor.connected = True
                monitor.cache = {'registered': list(PROBES), 'credentials': {'xianyu': {
                    'configured': True, 'revision': 'same', 'anonymous': False}},
                    'passive': parse_health('- xianyu: credential=ok, calls=130 (ok=130 fail=0), last_success=1s ago')}
                for name in PROBES:
                    if name.startswith('xianyu_'):
                        monitor.insert_check('xianyu', name, 'ok', 10, 'same')
                        monitor.schedules[name] = {'revision': 'same', 'last_at': time.time(), 'next_at': time.time()+1800, 'failures': 0}
                with monitor.db() as db:
                    db.execute('UPDATE checks SET classifier_version=0')
                platform = next(p for p in monitor.snapshot()['platforms'] if p['id'] == 'xianyu')
                self.assertEqual(platform['category'], 'unknown')
                self.assertIn('规则', platform['message'])
                self.assertEqual(monitor.platform_plan('xianyu')['reuse_until'], 0)
                self.assertEqual(monitor.schedule_for('xianyu_search_products', 'same')['next_at'], 0)
                history = monitor.snapshot('xianyu')['history']['rows']
                self.assertTrue(all(r['category'] == 'unknown' for r in history))
                self.assertTrue(all('旧版' in r['message'] for r in history))
                # Preserve what was originally recorded for auditing.
                with monitor.db() as db:
                    self.assertEqual(db.execute('SELECT category FROM checks LIMIT 1').fetchone()[0], 'ok')
            finally:
                await monitor.close()

    async def test_business_aware_counters_do_not_replace_authoritative_checks(self):
        with tempfile.TemporaryDirectory() as td:
            monitor = PlatformMonitor(Path(td) / 'platforms.sqlite3')
            try:
                monitor.connected = True
                monitor.cache = {'registered': list(PROBES), 'credentials': {'xianyu': {
                    'configured': True, 'revision': 'same', 'anonymous': False}},
                    'passive': parse_health('outcome_policy=business-v1\n- xianyu: credential=ok, calls=3 (ok=3 fail=0), last_success=1s ago')}
                self.assertEqual(monitor.platform_plan('xianyu')['reuse_until'], 0)
                platform = next(p for p in monitor.snapshot()['platforms'] if p['id'] == 'xianyu')
                self.assertEqual(platform['category'], 'unknown')
                self.assertIsNone(platform['evidence_source'])
            finally:
                await monitor.close()
