"""End-to-end behavior of the read-only Docker proxy chain: collector -> proxy -> fake Docker daemon, all over
temporary Unix domain sockets (no real Docker needed).

Each round the collector must give a checkable verdict: a successful round with a container count and the
proxy's field filtering intact, or a failed round with a fixed, readable reason -- never a silent empty list or
an uncaught exception. A failure of one container only costs that container.
"""
import http.client
import json
import socket
import socketserver
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

# The proxy module binds a Unix stream server at import time, so skip before importing it where Unix domain
# sockets are unavailable (some Windows builds). CI and Linux run every test below.
if not hasattr(socket, "AF_UNIX") or not hasattr(socketserver, "ThreadingUnixStreamServer"):
    pytest.skip("Unix domain sockets are not available on this platform", allow_module_level=True)

from src.collector import collector, docker_proxy as proxy

CID_A, CID_B = "a" * 64, "b" * 64
SECRET = "SUPER_SECRET_TOKEN_123"

INSPECT_A = {
    "Id": CID_A, "Name": "/web", "RestartCount": 1, "Image": "sha256:" + "ab" * 32,
    "Config": {"Image": "nginx:1", "Env": [f"DB_PASSWORD={SECRET}"], "Labels": {"secret": SECRET, "com.docker.compose.project": "shop"}},
    "State": {"Status": "running", "StartedAt": "2026-01-01T00:00:00Z", "ExitCode": 0, "OOMKilled": False, "FinishedAt": "0001-01-01T00:00:00Z",
              "Health": {"Status": "healthy"}},
    "NetworkSettings": {"Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}},
    "Mounts": [{"Type": "bind", "Source": "/srv/web", "Destination": "/data", "Mode": SECRET}],
}
INSPECT_B = {
    "Id": CID_B, "Name": "/db", "RestartCount": 0, "Image": "sha256:" + "cd" * 32,
    "Config": {"Image": "postgres:16", "Env": [f"POSTGRES_PASSWORD={SECRET}"], "Labels": {"com.docker.compose.project": "shop"}},
    "State": {"Status": "running", "StartedAt": "2026-01-01T00:00:00Z", "ExitCode": 0, "OOMKilled": False, "FinishedAt": "0001-01-01T00:00:00Z",
              "Health": {"Status": "starting"}},
    "NetworkSettings": {"Ports": None}, "Mounts": [],
}
STATS = {"cpu_stats": {"cpu_usage": {"total_usage": 10}, "system_cpu_usage": 100, "online_cpus": 2},
         "precpu_stats": {}, "memory_stats": {"usage": 1048576, "limit": 2097152, "stats": {"inactive_file": 0}},
         "networks": {"eth0": {"rx_bytes": 1, "tx_bytes": 2}}, "blkio_stats": {"io_service_bytes_recursive": []}, "pids_stats": {"current": 3}}


def _listing(*ids):
    return [{"Id": cid, "Names": [f"/{name}"], "Image": "img", "State": "running", "Labels": {"secret": SECRET}}
            for cid, name in zip(ids, ("web", "db", "worker"))]


class FakeDocker(BaseHTTPRequestHandler):
    """A scriptable fake Docker daemon. Class knobs configure what the next request sees; ``seen`` records every
    request that reached it, so a proxy refusal can be proven not to have arrived upstream."""

    seen: list[str] = []
    fail_paths: set[str] = set()          # these answer HTTP 500
    invalid_json_paths: set[str] = set()  # these answer 200 with a body that is not JSON
    stall_paths: set[str] = set()         # these never answer (proxy upstream timeout)
    oversized_paths: set[str] = set()     # these answer 200 with more than the proxy's 8 MiB cap
    delay_connections = threading.Event()  # when set, accept connections but hold the response until cleared

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        FakeDocker.seen.append(self.path)
        if self.delay_connections.is_set():
            # Hold the request open: exercises the proxy's upstream timeout without slowing the default case.
            self.delay_connections.wait(15)
        if self.path in self.stall_paths:
            time.sleep(15)
            return
        if self.path in self.oversized_paths:
            self._send(200, b"[" + b"0," * (proxy.MAX_RESPONSE_BYTES // 2 + 16) + b"0]")
            return
        if self.path in self.fail_paths:
            self._send(500, b"upstream exploded: " + SECRET.encode(), "text/plain")
            return
        if self.path in self.invalid_json_paths:
            self._send(200, b"this is not json " + SECRET.encode(), "text/plain")
            return
        routes = {
            "/containers/json?all=1": _listing(CID_A, CID_B),
            f"/containers/{CID_A}/json": INSPECT_A,
            f"/containers/{CID_B}/json": INSPECT_B,
            f"/containers/{CID_A}/stats?stream=false&one-shot=true": STATS,
            f"/containers/{CID_B}/stats?stream=false&one-shot=true": STATS,
            "/version": {"Version": "27.3.1", "ApiVersion": "1.47"},
            "/system/df": {"LayersSize": 1000, "Images": [], "BuildCache": []},
        }
        if self.path not in routes:
            self._send(404, b"no such container", "text/plain")
            return
        self._send(200, json.dumps(routes[self.path]).encode())

    do_POST = do_PUT = do_DELETE = do_GET

    def log_message(self, *args):
        pass


@pytest.fixture(autouse=True)
def _fresh_collector_state():
    collector._cpu_previous.clear()
    collector._one_shot_unsupported = False
    FakeDocker.seen = []
    FakeDocker.fail_paths = set()
    FakeDocker.invalid_json_paths = set()
    FakeDocker.stall_paths = set()
    FakeDocker.oversized_paths = set()
    FakeDocker.delay_connections = threading.Event()
    yield
    FakeDocker.delay_connections.set()  # release any held handler threads
    collector._cpu_previous.clear()
    collector._one_shot_unsupported = False


def _start_stack(tmp_path):
    """Build the fake daemon and its proxy. Called from a fixture, or directly after monkeypatching a limit."""
    daemon_path = str(tmp_path / "docker.sock")
    daemon = socketserver.ThreadingUnixStreamServer(daemon_path, FakeDocker)
    daemon.daemon_threads = True
    listen_path = str(tmp_path / "proxy" / "docker.sock")
    server = proxy.make_server(listen_path, daemon_path)
    for item in (daemon, server):
        threading.Thread(target=item.serve_forever, daemon=True).start()
    return listen_path, daemon, server


def _stop_stack(daemon, server):
    for item in (server, daemon):
        item.shutdown()
        item.server_close()


@pytest.fixture
def stack(tmp_path):
    listen_path, daemon, server = _start_stack(tmp_path)
    yield listen_path, daemon, server
    _stop_stack(daemon, server)


def _raw(socket_path, method, path):
    connection = collector._UnixHTTPConnection(socket_path)
    connection.request(method, path)
    response = connection.getresponse()
    return response.status, response.read()


# --- 1. a normal round succeeds, with a count, and secrets never leave the proxy ----------------------

def test_a_successful_round_reports_the_count_and_no_sensitive_values(stack):
    listen_path, _, _ = stack

    containers, verdict = collector.collect_docker(listen_path)

    assert verdict["docker_status"] == "ok" and verdict["docker_reason"] is None and verdict["docker_reason_text"] is None
    assert verdict["docker_container_count"] == 2 and verdict["docker_container_errors"] == []
    assert isinstance(verdict["docker_latency_ms"], int) and verdict["docker_latency_ms"] >= 0
    assert {c["name"] for c in containers} == {"web", "db"}
    # The proxy stripped Config.Env, extra labels and mount options: nothing sensitive reached the collector.
    assert SECRET not in json.dumps(containers)
    assert all("Env" not in json.dumps(c) for c in containers)
    assert all(c["project"] == "shop" for c in containers)  # the one allowed label still arrives


# --- 2. a refused request never reaches upstream and fails the round with a readable reason -----------

def test_a_refused_request_fails_the_round_and_never_reaches_the_daemon(stack):
    listen_path, _, _ = stack

    # A direct attack on the proxy: 403, and the fake daemon's request log stays empty.
    status, body = _raw(listen_path, "POST", "/containers/create")
    assert status == 403 and body == b"Forbidden"
    assert FakeDocker.seen == []

    # A fake proxy that answers 403 itself (no upstream involved): the collector marks the round failed.
    class RefusingProxy(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(403)
            self.send_header("Content-Length", "9")
            self.end_headers()
            self.wfile.write(b"Forbidden")

        def log_message(self, *args):
            pass

    refusing_path = str(Path(tempfile.mkdtemp()) / "refusing.sock")
    refusing = socketserver.ThreadingUnixStreamServer(refusing_path, RefusingProxy)
    threading.Thread(target=refusing.serve_forever, daemon=True).start()
    try:
        containers, verdict = collector.collect_docker(refusing_path)
    finally:
        refusing.shutdown()
        refusing.server_close()

    assert containers == []
    assert verdict["docker_status"] == "unreachable"
    assert verdict["docker_reason"] == "forbidden"
    assert verdict["docker_reason_text"] == collector.DOCKER_REASON_TEXT["forbidden"]
    assert verdict["docker_container_count"] == 0


# --- 3. every upstream failure mode comes back as a generic 502 ---------------------------------------

@pytest.mark.parametrize("knob, path", [
    ("fail_paths", "/version"),                 # upstream non-200
    ("invalid_json_paths", "/version"),         # upstream 200 but illegal JSON
    ("oversized_paths", "/containers/json?all=1"),  # upstream answer over 8 MiB
])
def test_upstream_failures_become_a_generic_502_without_details(stack, knob, path):
    listen_path, _, _ = stack
    setattr(FakeDocker, knob, {path})

    status, body = _raw(listen_path, "GET", path)

    assert (status, body) == (502, b"Upstream error")
    assert SECRET not in body.decode(errors="replace")


def test_an_upstream_timeout_becomes_a_generic_502(stack, monkeypatch):
    listen_path, _, _ = stack
    # Shrink the proxy's upstream timeout so the stalled daemon trips it quickly instead of after 10 seconds.
    monkeypatch.setattr(proxy, "UPSTREAM_TIMEOUT_SECONDS", 0.3)

    class QuickConnection(proxy._UnixHTTPConnection):
        def __init__(self, socket_path):
            super().__init__(socket_path)
            self.timeout = 0.3  # the base class read the module constant before it was patched

    monkeypatch.setattr(proxy, "_UnixHTTPConnection", QuickConnection)
    FakeDocker.stall_paths = {"/version"}

    started = time.monotonic()
    status, body = _raw(listen_path, "GET", "/version")

    assert (status, body) == (502, b"Upstream error")
    assert time.monotonic() - started < 5  # it gave up after the short patched timeout, not the default 10 s


def test_a_502_on_the_listing_fails_the_round_with_a_fixed_reason(stack):
    listen_path, _, _ = stack
    FakeDocker.fail_paths = {"/containers/json?all=1"}

    containers, verdict = collector.collect_docker(listen_path)

    assert containers == [] and verdict["docker_status"] == "unreachable"
    assert verdict["docker_reason"] == "upstream"
    assert verdict["docker_reason_text"] == collector.DOCKER_REASON_TEXT["upstream"]


# --- 4. one container failing its detail or stats only costs that container ---------------------------

def test_one_container_detail_failure_leaves_the_other_and_is_listed_apart(stack):
    listen_path, _, _ = stack
    FakeDocker.fail_paths = {f"/containers/{CID_A}/json"}

    containers, verdict = collector.collect_docker(listen_path)

    assert verdict["docker_status"] == "ok"  # the round itself worked
    assert verdict["docker_container_count"] == 1
    assert [c["name"] for c in containers] == ["db"]
    assert verdict["docker_container_errors"] == [
        {"container_id": CID_A, "stage": "inspect", "reason": "upstream"},
    ]


def test_one_container_stats_failure_keeps_its_detail_and_marks_the_stats_stage(stack):
    listen_path, _, _ = stack
    FakeDocker.fail_paths = {f"/containers/{CID_B}/stats?stream=false&one-shot=true",
                             f"/containers/{CID_B}/stats?stream=false"}

    containers, verdict = collector.collect_docker(listen_path)

    by_name = {c["name"]: c for c in containers}
    assert set(by_name) == {"web", "db"}
    assert "cpu_pct" not in by_name["db"] and "memory_used_mb" not in by_name["db"]  # usage missing...
    assert by_name["db"]["status"] == "running" and by_name["db"]["healthcheck_status"] == "starting"  # ...detail kept
    assert by_name["web"]["pids"] == 3  # the healthy container's stats came through
    assert verdict["docker_status"] == "ok" and verdict["docker_container_count"] == 2
    assert verdict["docker_container_errors"] == [
        {"container_id": CID_B, "stage": "stats", "reason": "upstream"},
    ]


# --- 5. once the connection limit is reached, new connections close and the collector survives --------

def test_a_connection_closed_by_the_proxy_fails_the_round_without_raising(tmp_path, monkeypatch):
    # The proxy's semaphore is sized at construction, so lower the limit before building the server.
    monkeypatch.setattr(proxy, "MAX_CONNECTIONS", 1)
    listen_path, daemon, server = _start_stack(tmp_path)
    holder = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    holder.settimeout(5)
    holder.connect(listen_path)  # the single slot; never send a request, so it stays occupied
    try:
        # The collector must report a failed round, not raise an uncaught exception.
        containers, verdict = collector.collect_docker(listen_path)
    finally:
        holder.close()
        _stop_stack(daemon, server)

    assert containers == [] and verdict["docker_status"] == "unreachable"
    assert verdict["docker_reason"] == "closed"
    assert verdict["docker_reason_text"] == collector.DOCKER_REASON_TEXT["closed"]


def test_over_limit_connections_are_closed_and_capacity_recovers(tmp_path, monkeypatch):
    monkeypatch.setattr(proxy, "MAX_CONNECTIONS", 2)
    listen_path, daemon, server = _start_stack(tmp_path)
    holders = []
    try:
        for _ in range(2):
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.settimeout(5)
            client.connect(listen_path)
            holders.append(client)

        with pytest.raises((http.client.RemoteDisconnected, ConnectionError)):
            _raw(listen_path, "GET", "/containers/json?all=1")  # third connection closed immediately
    finally:
        for client in holders:
            client.close()

    deadline = time.monotonic() + 5
    try:
        while True:
            status, _ = _raw(listen_path, "GET", "/version")
            if status == 200:
                break
            assert time.monotonic() < deadline
            time.sleep(0.05)
    finally:
        _stop_stack(daemon, server)
