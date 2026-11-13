"""Offline safety/transaction tests; no credentials or external network needed."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mihomo"))
import configure_failover as failover


class FailoverTests(unittest.TestCase):
    def setUp(self):
        self.sources = [failover.Source("primary", "https://one.example/sub"),
                        failover.Source("backup1", "https://two.example/sub")]
        self.base = {"mode": "rule", "mixed-port": 7890, "dns": {"enable": True},
                     "proxies": [{"name": "same", "type": "http", "server": "localhost", "port": 1}],
                     "proxy-groups": [{"name": "XFLTD", "type": "select", "proxies": ["same"]}],
                     "rules": ["IP-CIDR,10.0.0.0/8,DIRECT,no-resolve", "MATCH,XFLTD"]}

    def test_requires_two_different_sources(self):
        with self.assertRaises(ValueError):
            failover.sources_from({"MIHOMO_SUBSCRIPTION_URL": "https://one.example"})
        with self.assertRaises(ValueError):
            failover.sources_from({"MIHOMO_SUBSCRIPTION_URL": "https://one.example",
                                   "MIHOMO_BACKUP_SUBSCRIPTION_URL": "https://one.example"})

    def test_more_backups_have_numeric_priority(self):
        values = {"MIHOMO_SUBSCRIPTION_URL": "https://one.example"}
        for suffix in ["_10", "_2", ""]:
            values["MIHOMO_BACKUP_SUBSCRIPTION_URL" + suffix] = "https://backup.example/" + suffix
        self.assertEqual([s.name for s in failover.sources_from(values)],
                         ["primary", "backup1", "backup2", "backup10"])

    def test_root_is_automatic_and_sources_are_namespaced(self):
        before = copy.deepcopy(self.base)
        c = failover.build_config(self.base, self.sources, "rev")
        self.assertEqual(self.base, before)
        self.assertEqual(c["proxy-groups"][0]["type"], "select")
        self.assertEqual(c["proxy-groups"][0]["proxies"], ["自动故障转移", "手动节点"])
        self.assertEqual(c["proxy-groups"][1]["type"], "fallback")
        self.assertNotIn('use', c['proxy-groups'][1])
        self.assertEqual(c['proxy-groups'][1]['proxies'], ['优选-primary', '优选-backup1', '优选-rescue'])
        self.assertTrue(c["profile"]["store-selected"])
        self.assertFalse(c["proxy-providers"]["managed-backup1"]["health-check"]["lazy"])
        self.assertNotEqual(c["proxy-providers"]["managed-primary"]["override"],
                            c["proxy-providers"]["managed-backup1"]["override"])
        self.assertEqual(c['proxy-providers']['managed-primary']['health-check']['timeout'], 20000)
        self.assertEqual(c['proxy-groups'][1]['timeout'], 20000)
        self.assertEqual(c['proxy-groups'][1]['interval'], 120)
        self.assertEqual(c['proxy-providers']['managed-primary']['health-check']['interval'], 900)
        groups = {g['name']: g for g in c['proxy-groups']}
        for source in ('primary', 'backup1', 'rescue'):
            fastest = groups['优选-' + source]
            self.assertEqual(fastest['type'], 'url-test')
            self.assertEqual(fastest['tolerance'], 30)
            self.assertEqual(fastest['interval'], 900)
            self.assertFalse(fastest['interrupt-existing-connections'])
            self.assertEqual(fastest['use'], ['managed-' + source])
        self.assertEqual(groups['自动选择']['proxies'], ['自动故障转移'])
        self.assertEqual(c["rules"], before["rules"])
        self.assertEqual(c["dns"], before["dns"])
        self.assertEqual(c["proxies"], [])

    def test_rejects_unknown_routing_without_overwriting(self):
        self.base["rules"].append("DOMAIN,example.com,CustomGroup")
        with self.assertRaises(ValueError):
            failover.build_config(self.base, self.sources, "rev")

    def test_invalid_payload_cannot_replace_cache(self):
        for value in [b"<html>failure</html>", b"proxies: []", b"proxies: [{name: a}, {name: a}]"]:
            with self.assertRaises(ValueError):
                failover.provider_payload(value)
        payload = failover.provider_payload(b"proxies: [{name: a, reality-opts: {short-id: abc}}]")
        self.assertEqual(payload["proxies"][0]["reality-opts"]["short-id"], "0abc")

    def test_backup_never_inherits_primary_nodes(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(failover.cached_payload(self.base, Path(td), self.sources[0]))
            self.assertIsNone(failover.cached_payload(self.base, Path(td), self.sources[1]))

    def test_rescue_nodes_survive_reconfiguration(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            payload = failover.rescue_payload(self.base, d)
            failover.write_private(d / "rescue.yaml", payload)
            managed = {"proxy-providers": {"managed-rescue": {"path": "rescue.yaml"}}}
            self.assertEqual(failover.rescue_payload(managed, d), payload)

    def test_duplicate_subscription_content_is_reported(self):
        payload = {"proxies": self.base["proxies"]}
        changed_name = copy.deepcopy(payload)
        changed_name["proxies"][0]["name"] = "renamed"
        self.assertEqual(failover.overlapping_nodes([payload, changed_name]), 1)

    def test_cache_must_match_subscription_and_stay_inside_data_dir(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            failover.write_private(d / "cache.yaml", {"proxies": self.base["proxies"]})
            base = {"proxy-providers": {"managed-backup1": {"url": self.sources[1].url, "path": "cache.yaml"}}}
            self.assertIsNotNone(failover.cached_payload(base, d, self.sources[1]))
            base["proxy-providers"]["managed-backup1"]["url"] = "https://changed.example"
            self.assertIsNone(failover.cached_payload(base, d, self.sources[1]))

    def test_failed_publish_restores_file_and_reloads_previous_config(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            failover.write_private(d / "config.yaml", self.base)
            original = (d / "config.yaml").read_bytes()
            failover.write_private(d / "candidate.yaml", {"mode": "invalid"})
            with patch.object(failover, "api", return_value={}) as api, \
                 patch.object(failover, "verify", return_value=False), \
                 patch.object(failover.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "previous configuration reloaded"):
                    failover.apply_candidate(d, d / "candidate.yaml", "http://localhost", "secret", "http://localhost", [])
                reloads = [call for call in api.call_args_list if call.args[2] == '/configs?force=true']
                self.assertEqual(len(reloads), 2)
            self.assertEqual((d / "config.yaml").read_bytes(), original)

    def test_node_dns_is_scoped_to_each_subscription_and_survives_cache(self):
        import yaml
        config = {'dns': {'enable': True, 'respect-rules': True, 'nameserver': ['223.5.5.5'],
                          'default-nameserver': ['223.5.5.5'],
                          'proxy-server-nameserver': ['https://private.example/dns-query/private-token']}}
        first = failover.provider_payload(yaml.safe_dump({'proxies': [
            {'name': 'one', 'server': 'a.public.example'}, {'name': 'literal', 'server': '192.0.2.1'}],
            'dns': {'proxy-server-nameserver': ['119.29.29.29']}}).encode())
        second = {'proxies': [{'name': 'two', 'server': 'a.private.example'}],
                  'dns': {'proxy-server-nameserver': ['https://private.example/dns-query/private-token']}}
        before = copy.deepcopy(config)
        self.assertEqual(failover.configure_node_dns(config, [first, second]), 2)
        dns = config['dns']
        self.assertEqual(dns['proxy-server-nameserver'], ['223.5.5.5'])
        self.assertEqual(dns['proxy-server-nameserver-policy']['a.public.example'], ['119.29.29.29'])
        self.assertEqual(dns['proxy-server-nameserver-policy']['a.private.example'], second['dns']['proxy-server-nameserver'])
        self.assertNotIn('192.0.2.1', dns['proxy-server-nameserver-policy'])
        self.assertEqual(dns['nameserver'], before['dns']['nameserver'])
        self.assertTrue(dns['respect-rules'])
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'provider.yaml'
            failover.write_private(path, first)
            self.assertEqual(failover.provider_payload(path.read_bytes()), first)
        again = copy.deepcopy(config)
        failover.configure_node_dns(again, [first, second])
        self.assertEqual(again, config)

    def test_conflicting_node_dns_is_rejected_and_rescue_cannot_override_current_source(self):
        config = {'dns': {'enable': True}}
        payload = {'proxies': [{'name': 'one', 'server': 'shared.example'}],
                   'dns': {'proxy-server-nameserver': ['223.5.5.5']}}
        rescue = copy.deepcopy(payload)
        rescue['dns']['proxy-server-nameserver'] = ['119.29.29.29']
        with self.assertRaises(ValueError):
            failover.configure_node_dns(copy.deepcopy(config), [payload, rescue])
        failover.configure_node_dns(config, [payload], rescue)
        self.assertEqual(config['dns']['proxy-server-nameserver-policy']['shared.example'], ['223.5.5.5'])

    def test_publish_temporarily_holds_working_backup_and_restores_selectors(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            failover.write_private(d / 'config.yaml', self.base)
            failover.write_private(d / 'candidate.yaml', self.base)
            before = {'proxies': {'XFLTD': {'now': '自动故障转移'},
                                  '自动故障转移': {'now': '[backup1] working'},
                                  '手动节点': {'now': '[primary] saved'}}}
            def response(controller, secret, path, payload=None):
                if path == '/proxies':
                    return before
                if path == '/providers/proxies':
                    return {'providers': {'managed-backup1': {'proxies': [{'name': '[backup1] working', 'alive': True, 'history': [{}]}]}}}
                return {}
            with patch.object(failover, 'api', side_effect=response) as api, patch.object(failover, 'verify', return_value=True):
                failover.apply_candidate(d, d / 'candidate.yaml', 'http://controller', 'secret', 'http://proxy', [])
            selected = [(call.args[2], call.args[3]['name']) for call in api.call_args_list if len(call.args) > 3 and call.args[2].startswith('/proxies/')]
            self.assertEqual(selected[0][1], '[backup1] working')
            self.assertEqual(selected[1][1], '手动节点')
            self.assertEqual(selected[-2][1], '自动故障转移')
            self.assertEqual(selected[-1][1], '[primary] saved')

    def test_publish_waits_for_nested_auto_cache_before_releasing_working_exit(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            failover.write_private(d / 'config.yaml', self.base)
            failover.write_private(d / 'candidate.yaml', self.base)
            warm_reads = 0
            restored = False
            reloaded = False
            def response(controller, secret, path, payload=None):
                nonlocal warm_reads, restored, reloaded
                if path.startswith('/configs'):
                    reloaded = True
                if path.startswith('/proxies/') and payload and payload['name'] == '自动故障转移':
                    self.assertGreaterEqual(warm_reads, 3)
                    restored = True
                if path == '/proxies':
                    if reloaded:
                        warm_reads += 1
                    return {'proxies': {'XFLTD': {'now': '自动故障转移'},
                        '自动故障转移': {'now': '优选-primary'},
                        '优选-primary': {'now': 'COMPATIBLE' if reloaded and warm_reads < 3 else '[primary] ready'},
                        '手动节点': {'now': '[primary] saved'}}}
                if path == '/providers/proxies':
                    return {'providers': {'managed-primary': {'proxies': [{'name': '[primary] ready', 'alive': True, 'history': [{}]}]}}}
                return {}
            with patch.object(failover, 'api', side_effect=response), patch.object(failover, 'verify', return_value=True), patch.object(failover.time, 'sleep') as sleep:
                failover.apply_candidate(d, d / 'candidate.yaml', 'http://controller', 'secret', 'http://proxy', [])
            self.assertTrue(restored)
            self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
