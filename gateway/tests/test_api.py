import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.parse import unquote

import httpx
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1]))
spec = importlib.util.spec_from_file_location("gateway_app", Path(__file__).parents[1] / "app.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.groups = {"XFLTD": {"type": "Selector", "now": "自动故障转移", 'all': ['自动故障转移', '手动节点']},
                       "自动故障转移": {"type": "Fallback", "now": "优选-primary", "all": ["优选-primary"]},
                       '优选-primary': {'type': 'URLTest', 'now': '[primary] node-a'},
                       "手动节点": {"type": "Selector", "now": "[primary] node-a"}}
        self.providers = {"managed-primary": {"proxies": [
            {"name": "[primary] node-a", "type": "AnyTLS", "alive": True,
             "password": "NODE-PASSWORD-NEVER-EXPOSE", "history": [{"time": "2026-10-30T00:00:00Z", "delay": 55}]},
            {"name": "[primary] node-b", "type": "AnyTLS", "alive": True, "history": [{"delay": 90}]},
            {"name": "[primary] bad", "type": "AnyTLS", "alive": False, "history": [{"delay": 0}]},
        ]}}
        self.calls = []
        self.fail_next_switch = False
        self.offline = False
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name) / "config.yaml"
        self.config.write_text(yaml.safe_dump({"secret": "CONFIG-SECRET-NEVER-EXPOSE", "proxy-providers": {
            "managed-primary": {"url": "https://provider.example/sub?token=URL-TOKEN-NEVER-EXPOSE"}}}))

        def handler(request):
            if self.offline:
                raise httpx.ConnectError("sensitive upstream details", request=request)
            path = unquote(request.url.path)
            self.calls.append((request.method, path))
            if request.method == "PUT":
                if self.fail_next_switch and path == "/proxies/XFLTD":
                    self.fail_next_switch = False
                    return httpx.Response(500, text="upstream secret")
                name = path.removeprefix("/proxies/")
                self.groups[name]["now"] = json.loads(request.content)["name"]
                return httpx.Response(204)
            responses = {"/proxies": {"proxies": self.groups},
                         "/providers/proxies": {"providers": self.providers},
                         "/connections": {"connections": [], "uploadTotal": 123, "downloadTotal": 456},
                         "/version": {"version": "v1.19.31"}}
            return httpx.Response(200, json=copy.deepcopy(responses[path]))

        self.app = module.create_app(admin_password="admin-test", controller_secret="CONTROLLER-SECRET",
                                     controller_url="http://controller", transport=httpx.MockTransport(handler),
                                     config_path=self.config, history_path=Path(self.temp.name) / 'history.sqlite3')
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self):
        response = self.client.post("/api/login", json={"password": "admin-test"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("httponly", response.headers["set-cookie"].lower())
        self.assertIn("samesite=strict", response.headers["set-cookie"].lower())

    def switch(self, **body):
        return self.client.post("/api/policy", json=body, headers={"X-Gateway-Request": "1"})

    def test_authentication_and_request_source_are_required(self):
        self.assertEqual(self.client.get("/api/snapshot").status_code, 401)
        self.assertEqual(self.client.get('/api/healthcheck').status_code, 401)
        self.assertEqual(self.client.post('/api/healthcheck', json={'scope': 'all'}).status_code, 401)
        self.assertEqual(self.client.get('/api/history?start=1&end=2').status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={"password": "wrong"}).status_code, 401)
        self.login()
        self.assertEqual(self.client.post("/api/policy", json={"mode": "auto"}).status_code, 403)
        self.assertEqual(self.client.post('/api/healthcheck', json={'scope': 'all'}).status_code, 403)

    def test_status_reads_do_not_probe_and_unknown_nodes_are_rejected(self):
        self.login()
        self.assertEqual(self.client.get('/api/healthcheck').json()['status'], 'idle')
        self.client.get('/api/snapshot')
        self.assertFalse(any('healthcheck' in path for _, path in self.calls))
        for body in ({'scope': 'page', 'nodes': ['forged']}, {'scope': 'page', 'nodes': []},
                     {'scope': 'provider', 'provider': 'unmanaged'}, {'scope': 'page', 'nodes': ['a'] * 13}):
            response = self.client.post('/api/healthcheck', json=body, headers={'X-Gateway-Request': '1'})
            self.assertIn(response.status_code, (400, 422))
        self.assertFalse(any('healthcheck' in path for _, path in self.calls))

    def test_per_url_state_quality_and_staleness(self):
        import time
        from datetime import datetime, timezone
        node = self.providers['managed-primary']['proxies'][0]
        old = datetime.fromtimestamp(time.time() - 2000, timezone.utc).isoformat()
        node['extra'] = {module.CHECK_URL: {'alive': False, 'history': [
            {'delay': 40, 'time': old}, {'delay': 60, 'time': old}, {'delay': 0, 'time': old}]}}
        self.login()
        row = self.client.get('/api/snapshot').json()['nodes'][0]
        self.assertFalse(row['alive'])
        self.assertTrue(row['stale'])
        self.assertEqual(row['samples'], 3)
        self.assertEqual(row['success_rate'], 66.7)
        self.assertEqual(row['median_delay'], 50)
        self.assertEqual(row['jitter'], 20)

    def test_manual_probe_scopes_select_only_requested_loaded_nodes(self):
        self.login()
        manager = self.app.state.probes
        headers = {'X-Gateway-Request': '1'}
        for body, expected in [
            ({'scope': 'current'}, [('managed-primary', '[primary] node-a')]),
            ({'scope': 'page', 'nodes': ['[primary] node-b']}, [('managed-primary', '[primary] node-b')]),
            ({'scope': 'provider', 'provider': 'managed-primary'},
             [('managed-primary', '[primary] node-a'), ('managed-primary', '[primary] node-b'), ('managed-primary', '[primary] bad')]),
            ({'scope': 'all'}, [('managed-primary', '[primary] node-a'), ('managed-primary', '[primary] node-b'), ('managed-primary', '[primary] bad')]),
        ]:
            with patch.object(manager, 'start', return_value={'status': 'running'}) as start:
                response = self.client.post('/api/healthcheck', json=body, headers=headers)
                self.assertEqual(response.status_code, 202)
                start.assert_called_once_with(expected, body['scope'])

    def test_platform_monitor_auth_and_write_tool_exclusion(self):
        self.assertEqual(self.client.get('/api/platforms').status_code, 401)
        self.assertEqual(self.client.post('/api/platforms/check', json={}).status_code, 401)
        self.login()
        self.assertEqual(self.client.post('/api/platforms/check', json={}).status_code, 403)
        response = self.client.post('/api/platforms/check', json={'tool': 'xianyu_confirm_delivery'},
                                    headers={'X-Gateway-Request': '1'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/api/platforms?platform=unknown').status_code, 400)
        self.assertEqual(self.client.get('/api/platforms?page=0').status_code, 422)
        response = self.client.get('/api/platforms')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['platforms']), 5)

    def test_platform_status_polling_does_not_schedule_mcp_connections(self):
        self.login()
        with patch.object(self.app.state.platforms, 'request_refresh') as refresh:
            for _ in range(3):
                self.assertEqual(self.client.get('/api/platforms').status_code, 200)
            refresh.assert_not_called()
            self.assertEqual(self.client.post('/api/platforms/refresh').status_code, 403)
            self.assertEqual(self.client.post('/api/platforms/refresh', headers={'X-Gateway-Request': '1'}).status_code, 202)
            refresh.assert_called_once()

    def test_monitoring_policy_requires_login_csrf_and_bounded_interval(self):
        path = '/api/platforms/monitoring'
        body = {'enabled': False, 'interval_minutes': 60}
        self.assertEqual(self.client.post(path, json=body).status_code, 401)
        self.login()
        self.assertEqual(self.client.post(path, json=body).status_code, 403)
        headers = {'X-Gateway-Request': '1'}
        with patch.object(self.app.state.platforms, 'launch_checks') as launch:
            response = self.client.post(path, json=body, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.client.get('/api/platforms').json()['monitoring']['interval_minutes'], 60)
            self.assertFalse(self.app.state.platforms.read_state('auto_policy', {})['enabled'])
            self.assertEqual(self.client.post(path, json={**body, 'interval_minutes': 1}, headers=headers).status_code, 422)
            launch.assert_not_called()

    def test_credential_validation_never_echoes_secret_input(self):
        self.login()
        headers = {'X-Gateway-Request': '1'}
        for body in ({'platform': 'xueqiu', 'updates': 'SECRET-INPUT'},
                     {'platform': 'xueqiu', 'updates': {'wrong': 'SECRET-INPUT'}},
                     {'platform': 'xueqiu', 'updates': {'xueqiu_cookie': 'SECRET-INPUT\nINJECTED'}},
                     {'updates': {'xueqiu_cookie': 'SECRET-INPUT'}}):
            response = self.client.post('/api/platforms/credentials', json=body, headers=headers)
            self.assertIn(response.status_code, (400, 422))
            self.assertNotIn('SECRET-INPUT', response.text)

    def test_platform_storage_failure_does_not_break_gateway_session(self):
        import sqlite3
        application = module.create_app(admin_password='admin-test', controller_secret='test',
                                        history_path=Path(self.temp.name) / 'isolated-history.sqlite3')
        with patch.object(module, 'PlatformMonitor', side_effect=sqlite3.OperationalError('unavailable')):
            with TestClient(application) as client:
                self.assertTrue(client.get('/api/session').json()['configured'])
                self.assertEqual(client.post('/api/login', json={'password': 'admin-test'}).status_code, 200)
                self.assertEqual(client.get('/api/platforms').status_code, 503)
                self.assertEqual(client.get('/api/session').status_code, 200)

    def test_history_queries_survive_controller_outage_and_validate_ranges(self):
        from history_store import HistoryStore
        store = HistoryStore(Path(self.temp.name) / 'history.sqlite3', 100)
        store.ingest({'connections': []}, 100)
        store.close()
        self.login()
        self.offline = True
        response = self.client.get('/api/history?start=1&end=200')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['totals']['upload'], 0)
        self.assertFalse(response.json()['collector']['healthy'])
        self.assertEqual(self.client.get('/api/history?start=200&end=1').status_code, 400)
        self.assertEqual(self.client.get('/api/history?start=1&end=200&group_by=secret').status_code, 422)
        self.assertEqual(self.client.get('/api/history?start=1&end=200&page_size=99999').status_code, 422)

    def test_snapshot_sanitizes_secrets_and_resolves_actual_node(self):
        self.login()
        response = self.client.get("/api/snapshot")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["policy"]["node"], "[primary] node-a")
        self.assertTrue(data["policy"]["ready"])
        self.assertEqual(data["providers"][0]["host"], "provider.example")
        self.assertEqual(data["providers"][0]["alive"], 2)
        for secret in ["NODE-PASSWORD", "CONFIG-SECRET", "URL-TOKEN", "CONTROLLER-SECRET"]:
            self.assertNotIn(secret, response.text)

    def test_manual_selection_and_restore_automatic(self):
        self.login()
        response = self.switch(mode="manual", node="[primary] node-b")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.groups["XFLTD"]["now"], "手动节点")
        self.assertEqual(self.groups["手动节点"]["now"], "[primary] node-b")
        self.assertEqual(self.client.get("/api/snapshot").json()["policy"]["mode"], "manual")
        response = self.switch(mode="auto")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.groups["XFLTD"]["now"], "自动故障转移")

    def test_auto_combines_source_priority_and_nested_latency_selection(self):
        self.login()
        policy = self.client.get('/api/snapshot').json()['policy']
        self.assertTrue(policy['optimized'])
        self.assertEqual(policy['mode'], 'auto')
        self.assertEqual(policy['node'], '[primary] node-a')
        self.assertEqual(policy['latency_tolerance_ms'], 30)
        self.groups['优选-primary']['now'] = '[primary] node-b'
        self.app.state.snapshot = None
        self.assertEqual(self.client.get('/api/snapshot').json()['policy']['node'], '[primary] node-b')
        self.assertEqual(self.switch(mode='latency').status_code, 422)

    def test_auto_switch_rolls_back_on_failure(self):
        self.login()
        self.assertEqual(self.switch(mode='manual', node='[primary] node-b').status_code, 200)
        self.fail_next_switch = True
        self.assertEqual(self.switch(mode='auto').status_code, 503)
        self.assertEqual(self.groups['XFLTD']['now'], '手动节点')
        self.assertEqual(self.groups['手动节点']['now'], '[primary] node-b')

    def test_provider_priority_comes_from_config_not_alphabetic_api_order(self):
        self.providers = {"managed-backup1": {"proxies": []}, **self.providers}
        self.config.write_text(yaml.safe_dump({"proxy-providers": {
            "managed-primary": {"url": "https://primary.example"},
            "managed-backup1": {"url": "https://backup.example"},
        }}, sort_keys=False))
        self.login()
        data = self.client.get("/api/snapshot").json()
        self.assertEqual([p["id"] for p in data["providers"]], ["managed-primary", "managed-backup1"])

    def test_forged_session_is_rejected(self):
        self.client.cookies.set("mirage_session", "9999999999.forged")
        self.assertEqual(self.client.get("/api/snapshot").status_code, 401)

    def test_unknown_and_failed_nodes_are_rejected_before_mutation(self):
        self.login()
        for node in ["not-real", "[primary] bad"]:
            self.assertEqual(self.switch(mode="manual", node=node).status_code, 400)
        self.assertFalse(any(method == "PUT" for method, _ in self.calls))

    def test_failed_switch_rolls_back_both_selectors(self):
        self.login()
        self.fail_next_switch = True
        response = self.switch(mode="manual", node="[primary] node-b")
        self.assertEqual(response.status_code, 503)
        self.assertIn("已恢复原出口", response.json()["detail"])
        self.assertEqual(self.groups["手动节点"]["now"], "[primary] node-a")
        self.assertEqual(self.groups["XFLTD"]["now"], "自动故障转移")

    def test_controller_outage_is_not_reported_as_empty_success(self):
        self.login()
        self.offline = True
        response = self.client.get("/api/snapshot")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("sensitive", response.text)

    def test_logout_and_login_rate_limit(self):
        self.login()
        self.assertEqual(self.client.post("/api/logout", headers={"X-Gateway-Request": "1"}).status_code, 200)
        self.assertFalse(self.client.get("/api/session").json()["authenticated"])
        for _ in range(5):
            self.client.post("/api/login", json={"password": "wrong"})
        self.assertEqual(self.client.post("/api/login", json={"password": "admin-test"}).status_code, 429)


if __name__ == "__main__":
    unittest.main()
