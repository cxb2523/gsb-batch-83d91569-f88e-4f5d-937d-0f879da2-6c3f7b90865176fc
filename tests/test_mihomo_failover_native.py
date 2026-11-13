"""Opt-in real-kernel fault injection, isolated from the production gateway.

MIHOMO_INTEGRATION=1 python3 -m unittest discover -s tests -p '*native.py' -v
Uses only local mock proxies/targets, with a separate temporary Docker container.
"""
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml


class MockProxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        if not self.server.download_available:
            self.send_error(503)
            return
        body = yaml.safe_dump({"proxies": [{"name": self.server.node_name, "type": "http",
                                           "server": "127.0.0.1", "port": self.server.server_port}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_CONNECT(self):
        if not self.server.healthy:
            self.send_error(502)
            return
        self.send_response(200)
        self.end_headers()
        # Terminate the HTTP health check locally; no public network needed.
        while True:
            line = self.rfile.readline()
            if not line or line in (b"\r\n", b"\n"):
                break
        self.wfile.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
        self.wfile.flush()
        self.close_connection = True


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(os.environ.get("MIHOMO_INTEGRATION") == "1", "opt-in real Mihomo integration")
class NativeFailoverTest(unittest.TestCase):
    def test_primary_failure_switches_to_backup_and_recovery_returns_to_primary(self):
        servers = []
        container = "webmirage-failover-test-" + uuid.uuid4().hex[:8]
        proc = None
        try:
            for node_name in ["primary", "backup"]:
                server = ThreadingHTTPServer(("127.0.0.1", 0), MockProxy)
                server.healthy = True
                server.download_available = True
                server.node_name = node_name
                threading.Thread(target=server.serve_forever, daemon=True).start()
                servers.append(server)
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                providers = {}
                health = {"enable": True, "url": "http://health.invalid/check", "interval": 1,
                          "timeout": 500, "lazy": False, "expected-status": 204}
                for name, server in zip(["primary", "backup"], servers):
                    payload = {"proxies": [{"name": name, "type": "http", "server": "127.0.0.1",
                                             "port": server.server_port}]}
                    (root / (name + ".yaml")).write_text(yaml.safe_dump(payload))
                    providers[name] = {"type": "http", "url": f"http://127.0.0.1:{server.server_port}/sub",
                                       "path": "./" + name + ".yaml", "interval": 1,
                                       "proxy": "DIRECT", "health-check": health}
                port = unused_port()
                config = {"mixed-port": unused_port(), "bind-address": "127.0.0.1", "mode": "rule",
                          "external-controller": f"127.0.0.1:{port}", "secret": "test-only",
                          "profile": {"store-selected": True},
                          "proxy-providers": providers, "proxy-groups": [
                              {"name": "XFLTD", "type": "select", "proxies": ["auto", "manual"]},
                              {"name": "manual", "type": "select", "use": ["primary", "backup"]},
                              {"name": "auto", "type": "fallback", "use": ["primary", "backup"],
                               "url": health["url"], "interval": 1, "lazy": False, "timeout": 500,
                               "expected-status": 204}], "rules": ["MATCH,XFLTD"]}
                (root / "config.yaml").write_text(yaml.safe_dump(config))
                with (root / "kernel.log").open("w") as log:
                    proc = subprocess.Popen(["docker", "run", "--rm", "--name", container,
                                             "--network", "host", "-v", f"{td}:/root/.config/mihomo",
                                             os.environ.get("MIHOMO_IMAGE", "local/mihomo:v1.19.31")],
                                            stdout=log, stderr=log)
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

                    def wait_for(expected):
                        deadline = time.monotonic() + 15
                        while time.monotonic() < deadline:
                            try:
                                request = urllib.request.Request(f"http://127.0.0.1:{port}/proxies",
                                                                 headers={"Authorization": "Bearer test-only"})
                                with opener.open(request, timeout=1) as response:
                                    nodes = json.load(response)["proxies"]
                                selected = "XFLTD"
                                for _ in range(5):
                                    if selected not in nodes or "now" not in nodes[selected]:
                                        break
                                    selected = nodes[selected]["now"]
                                if selected == expected:
                                    return
                            except Exception:
                                pass
                            time.sleep(0.2)
                        log.flush()
                        self.fail(f"kernel did not select {expected} within 15 seconds; "
                                  + (root / "kernel.log").read_text()[-1800:])

                    wait_for("primary")
                    # A subscription outage must not remove the cached working nodes.
                    for server in servers:
                        server.download_available = False
                    time.sleep(2)
                    wait_for("primary")
                    servers[0].healthy = False
                    wait_for("backup")
                    servers[0].healthy = True
                    wait_for("primary")
                    def select(group, name):
                        request = urllib.request.Request(f"http://127.0.0.1:{port}/proxies/{group}",
                                                         headers={"Authorization": "Bearer test-only", "Content-Type": "application/json"},
                                                         data=json.dumps({"name": name}).encode(), method="PUT")
                        with opener.open(request, timeout=3):
                            pass
                    select("manual", "backup")
                    select("XFLTD", "manual")
                    wait_for("backup")
                    time.sleep(2)  # allow the native selection cache to flush
                    # Cold-start while both subscription endpoints are unavailable.
                    subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=15)
                    proc.wait(timeout=10)
                    proc = subprocess.Popen(["docker", "run", "--rm", "--name", container,
                                             "--network", "host", "-v", f"{td}:/root/.config/mihomo",
                                             os.environ.get("MIHOMO_IMAGE", "local/mihomo:v1.19.31")],
                                            stdout=log, stderr=log)
                    wait_for("backup")
                    select("XFLTD", "auto")
                    wait_for("primary")
        finally:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=15)
            if proc:
                proc.wait(timeout=10)
            for server in servers:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
