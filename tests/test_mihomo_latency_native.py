"""Real kernel latency/failure/stream checks using only temporary loopback services.

Reads the existing kernel binary with docker cp; never creates a container or
changes production ports, networking, firewall, routes or proxy configuration.
"""
import json
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parents[1] / 'mihomo'))
spec = importlib.util.spec_from_file_location('native_failover', Path(__file__).parents[1] / 'mihomo/configure_failover.py')
failover = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = failover
spec.loader.exec_module(failover)


class Proxy(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.requests += 1
        if self.path.endswith('/stream'):
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            try:
                while not self.server.stop.is_set():
                    self.wfile.write(b'tick\n')
                    self.wfile.flush()
                    time.sleep(.1)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        time.sleep(self.server.delay)
        self.send_response(204 if self.server.healthy else 503)
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()

    do_HEAD = do_GET

    def do_CONNECT(self):
        if not self.server.healthy:
            self.send_error(502)
            return
        self.send_response(200)
        self.end_headers()
        request = self.rfile.readline().decode('ascii', errors='replace').split()
        if len(request) < 2:
            return
        while True:
            line = self.rfile.readline()
            if not line or line in (b'\r\n', b'\n'):
                break
        self.path = request[1]
        self.do_GET()
        self.close_connection = True


def unused_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@unittest.skipUnless(os.environ.get('MIHOMO_LATENCY_TEST') == '1', 'opt-in isolated native latency test')
class NativeLatencyTests(unittest.TestCase):
    def test_subscription_priority_latency_tolerance_failure_recovery_and_existing_stream(self):
        servers = []
        proc = None
        stream = None
        try:
            for delay in (.18, .04, .001):
                server = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
                server.daemon_threads = True
                server.delay = delay
                server.healthy = True
                server.requests = 0
                server.stop = threading.Event()
                threading.Thread(target=server.serve_forever, daemon=True).start()
                servers.append(server)
            with tempfile.TemporaryDirectory() as td:
                folder = Path(td)
                kernel = folder / 'mihomo'
                if os.environ.get('MIHOMO_BINARY'):
                    shutil.copy2(os.environ['MIHOMO_BINARY'], kernel)
                else:
                    subprocess.run(['docker', 'cp', 'mihomo:/mihomo', str(kernel)], capture_output=True, check=True)
                kernel.chmod(0o700)
                controller, proxy_port = unused_port(), unused_port()
                config = {'mixed-port': proxy_port, 'bind-address': '127.0.0.1', 'allow-lan': False,
                          'external-controller': f'127.0.0.1:{controller}', 'secret': 'local-test-only',
                          'mode': 'rule', 'log-level': 'warning', 'dns': {'enable': False},
                          'proxy-providers': {}, 'rules': ['MATCH,XFLTD']}
                nodes = [{'name': name, 'type': 'http', 'server': '127.0.0.1', 'port': server.server_port}
                         for name, server in zip(('a', 'b', 'c'), servers)]
                for source, pool in (('primary', nodes[:2]), ('backup1', nodes[2:])):
                    (folder / (source + '.yaml')).write_text(yaml.safe_dump({'proxies': pool}))
                    config['proxy-providers']['managed-' + source] = {
                        'type': 'file', 'path': './' + source + '.yaml',
                        'health-check': {'enable': True, 'url': 'http://health.invalid/check',
                                         'interval': 60, 'timeout': 1200, 'lazy': False, 'expected-status': 204}}
                failover.configure_auto_policy(config)
                for group in config['proxy-groups']:
                    if group['type'] in ('fallback', 'url-test'):
                        group.update(url='http://health.invalid/check', interval=1 if group['type'] == 'fallback' else 60, timeout=1200)
                file = folder / 'config.yaml'
                file.write_text(yaml.safe_dump(config))
                with (folder / 'kernel.log').open('w+') as log:
                    proc = subprocess.Popen([str(kernel), '-d', str(folder), '-f', str(file)], stdout=log, stderr=log)
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

                    def selected():
                        req = urllib.request.Request(f'http://127.0.0.1:{controller}/proxies',
                                                     headers={'Authorization': 'Bearer local-test-only'})
                        with opener.open(req, timeout=2) as response:
                            groups = json.load(response)['proxies']
                        name = 'XFLTD'
                        seen = set()
                        while name in groups and groups[name].get('now') and name not in seen:
                            seen.add(name)
                            name = groups[name]['now']
                        return name

                    def wait_for(name):
                        deadline = time.monotonic() + 12
                        while time.monotonic() < deadline:
                            try:
                                if selected() == name:
                                    return
                            except OSError:
                                pass
                            time.sleep(.15)
                        self.fail(f'isolated kernel did not select {name}')

                    wait_for('b')
                    # Backup c is faster, but must never preempt a healthy primary.
                    time.sleep(2)
                    self.assertEqual(selected(), 'b')
                    # Frequent outer checks probe just one exit per source, not
                    # all provider nodes. The unselected primary a stays idle.
                    counts = [s.requests for s in servers]
                    time.sleep(3)
                    self.assertEqual(servers[0].requests, counts[0])
                    self.assertGreater(servers[1].requests, counts[1])
                    self.assertGreater(servers[2].requests, counts[2])
                    # Speed up the full sweep only for the failure simulations.
                    for provider in config['proxy-providers'].values():
                        provider['health-check']['interval'] = 1
                    for group in config['proxy-groups']:
                        if group['type'] == 'url-test':
                            group['interval'] = 1
                    file.write_text(yaml.safe_dump(config))
                    reload_request = urllib.request.Request(f'http://127.0.0.1:{controller}/configs?force=true',
                        data=json.dumps({'path': str(file)}).encode(), method='PUT',
                        headers={'Authorization': 'Bearer local-test-only', 'Content-Type': 'application/json'})
                    with opener.open(reload_request, timeout=5):
                        pass
                    wait_for('b')
                    # Open a live stream on b before making a decisively faster.
                    proxy = urllib.request.build_opener(urllib.request.ProxyHandler({'http': f'http://127.0.0.1:{proxy_port}'}))
                    stream = proxy.open('http://stream.invalid/stream', timeout=5)
                    self.assertEqual(stream.readline(), b'tick\n')
                    servers[0].delay, servers[1].delay = .02, .04
                    time.sleep(3)
                    self.assertEqual(selected(), 'b', '20ms improvement must stay within 30ms tolerance')
                    servers[1].delay = .20
                    wait_for('a')
                    # Drain old buffered data, then require fresh data after switching.
                    time.sleep(.3)
                    for _ in range(45):
                        self.assertEqual(stream.readline(), b'tick\n', 'automatic selection interrupted an existing stream')
                    servers[0].healthy = False
                    servers[1].delay = .04
                    wait_for('b')
                    servers[1].healthy = False
                    wait_for('c')
                    # The stream on b survives both in-pool and subscription changes.
                    for _ in range(20):
                        self.assertEqual(stream.readline(), b'tick\n')
                    servers[0].healthy = True
                    servers[0].delay = .04
                    # Return to primary despite backup c remaining faster.
                    wait_for('a')
        finally:
            for server in servers:
                server.stop.set()
            if stream:
                stream.close()
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            for server in servers:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    unittest.main()
