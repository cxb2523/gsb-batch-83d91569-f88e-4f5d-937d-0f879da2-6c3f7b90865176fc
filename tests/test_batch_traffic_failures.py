#!/usr/bin/env python3
"""Failure attribution tests for the batch traffic metering forwarder.

Scenarios use only local fake upstreams:
  * a closed port (upstream connection refused),
  * an upstream answering CONNECT with 407,
  * an upstream answering CONNECT with 503 (non-200, non-407),
  * an upstream that accepts then closes without replying (transport error),
  * a request whose headers exceed 64 KiB,
  * a healthy 200 CONNECT tunnel (must not be counted as a failure).
"""

from __future__ import annotations

import base64
import json
import os
import socket
import socketserver
import stat
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import batch_traffic as bt
from secure_files import atomic_write_json


UPSTREAM_USER = "upstream-secret-user-7071"
UPSTREAM_PASS = "upstream-secret-pass-7071"


def _read_headers(sock: socket.socket) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(8192)
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


class _FakeUpstreamHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        request = _read_headers(self.request)
        self.server.requests.append(request)  # type: ignore[attr-defined]
        mode = self.server.mode  # type: ignore[attr-defined]
        if mode == "407":
            self.request.sendall(
                b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                b'Proxy-Authenticate: Basic realm="upstream"\r\n'
                b"Connection: close\r\nContent-Length: 0\r\n\r\n"
            )
            return
        if mode == "503":
            self.request.sendall(
                b"HTTP/1.1 503 Service Unavailable\r\n"
                b"Connection: close\r\nContent-Length: 0\r\n\r\n"
            )
            return
        if mode == "close":
            # Accept the connection, swallow the request and vanish without
            # any CONNECT response: a transport-level failure.
            return
        if request.startswith(b"CONNECT "):
            self.request.sendall(
                b"HTTP/1.1 200 Connection Established\r\n\r\n"
            )
            if self.request.recv(4) == b"ping":
                self.request.sendall(b"pong")
            return
        body = b"hello"
        self.request.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\n"
            + body
        )


class _FakeUpstream(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _start_upstream(mode: str) -> _FakeUpstream:
    server = _FakeUpstream(("127.0.0.1", 0), _FakeUpstreamHandler)
    server.mode = mode
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _upstream_url(port: int) -> str:
    return f"http://{UPSTREAM_USER}:{UPSTREAM_PASS}@127.0.0.1:{port}"


def _connect_meter(meter_url: str) -> socket.socket:
    parsed = urlparse(meter_url)
    return socket.create_connection((parsed.hostname, parsed.port), timeout=5)


def _meter_auth(meter_url: str) -> bytes:
    parsed = urlparse(meter_url)
    token = base64.b64encode(
        f"{parsed.username}:{parsed.password}".encode("utf-8")
    ).decode("ascii")
    return f"Proxy-Authorization: Basic {token}\r\n".encode("ascii")


def _connect_request(meter_url: str, extra: bytes = b"") -> socket.socket:
    client = _connect_meter(meter_url)
    client.sendall(
        b"CONNECT example.test:443 HTTP/1.1\r\n"
        b"Host: example.test:443\r\n"
        + _meter_auth(meter_url)
        + b"\r\n"
        + extra
    )
    return client


def _refused_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _assert_private_mode(path: Path) -> None:
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    else:  # pragma: no cover - Windows has no POSIX mode bits
        assert path.is_file()


def _flush_runtime() -> None:
    manager = bt._RUNTIME_MANAGER
    assert manager is not None
    manager.state.flush()


def test_failure_attribution_categories_and_sanitized_summary() -> None:
    previous_file = os.environ.get(bt.TRAFFIC_FILE_ENV)
    previous_id = os.environ.get(bt.BATCH_ID_ENV)
    servers = [
        _start_upstream("407"),
        _start_upstream("503"),
        _start_upstream("close"),
        _start_upstream("ok"),
    ]
    dead_port = _refused_port()
    try:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "batch_traffic.json"
            bt.initialize_batch(path, "batch-fail", target=1, workers=1)
            os.environ[bt.TRAFFIC_FILE_ENV] = str(path)
            os.environ[bt.BATCH_ID_ENV] = "batch-fail"

            meter_407 = bt.meter_proxy_url(_upstream_url(servers[0].server_address[1]))
            meter_503 = bt.meter_proxy_url(_upstream_url(servers[1].server_address[1]))
            meter_close = bt.meter_proxy_url(
                _upstream_url(servers[2].server_address[1])
            )
            meter_ok = bt.meter_proxy_url(_upstream_url(servers[3].server_address[1]))
            meter_dead = bt.meter_proxy_url(_upstream_url(dead_port))

            # 1) Upstream port refuses connections -> 502 from the forwarder.
            client = _connect_request(meter_dead)
            head = _read_headers(client).split(b"\r\n", 1)[0]
            assert b" 502 " in head
            client.close()

            # 2) Upstream rejects CONNECT with 407 (proxy auth failure).
            client = _connect_request(meter_407)
            head = _read_headers(client).split(b"\r\n", 1)[0]
            assert b" 407 " in head
            client.close()

            # 3) Upstream rejects CONNECT with a non-200/non-407 status.
            client = _connect_request(meter_503)
            head = _read_headers(client).split(b"\r\n", 1)[0]
            assert b" 503 " in head
            client.close()

            # 4) Upstream accepts then vanishes without a CONNECT response.
            client = _connect_request(meter_close)
            head = _read_headers(client).split(b"\r\n", 1)[0]
            assert b" 502 " in head
            client.close()

            # 5) Headers larger than 64 KiB -> header_too_large, one 502.
            client = _connect_meter(meter_dead)
            oversized = (
                b"CONNECT example.test:443 HTTP/1.1\r\n"
                b"Host: example.test:443\r\n"
                + _meter_auth(meter_dead)
                + b"X-Big: "
                + b"a" * (bt.HEADER_LIMIT + 1024)
                + b"\r\n\r\n"
            )
            try:
                client.sendall(oversized)
                _read_headers(client)
            except OSError:
                pass
            client.close()

            # 6) A healthy tunnel must never be counted as a failure.
            client = _connect_request(meter_ok, extra=b"ping")
            head = _read_headers(client).split(b"\r\n", 1)[0]
            assert b" 200 " in head
            assert client.recv(4) == b"pong"
            client.close()

            # 7) Local forwarder auth rejection is not an upstream failure.
            client = _connect_meter(meter_ok)
            client.sendall(
                b"CONNECT example.test:443 HTTP/1.1\r\n"
                b"Host: example.test:443\r\n\r\n"
            )
            head = _read_headers(client).split(b"\r\n", 1)[0]
            assert b" 407 " in head
            client.close()

            _flush_runtime()
            metrics = bt.read_metrics(path)
            counts = metrics["failure_counts"]
            assert set(counts) == set(bt.FAILURE_REASONS)
            assert counts[bt.FAILURE_UPSTREAM_CONNECT] == 1
            assert counts[bt.FAILURE_PROXY_AUTH] == 1
            assert counts[bt.FAILURE_CONNECT_REJECTED] == 1
            assert counts[bt.FAILURE_TRANSPORT] == 1
            assert counts[bt.FAILURE_HEADER_TOO_LARGE] == 1
            assert sum(counts.values()) == 5
            # Seven accepted connections, five of them failed tunnels.
            assert metrics["connections"] == 7

            summary = metrics["failure_summary"]
            assert [entry["reason"] for entry in summary] == list(bt.FAILURE_REASONS)
            for entry in summary:
                assert set(entry) == {"reason", "count", "last_seen"}
                assert entry["count"] == counts[entry["reason"]]
                assert isinstance(entry["last_seen"], (int, float))
                assert not isinstance(entry["last_seen"], bool)
            assert all(entry["count"] > 0 for entry in summary)

            # Repeat the refused connection: counter increments and last_seen
            # is refreshed while the connection is still recorded exactly once.
            client = _connect_request(meter_dead)
            assert b" 502 " in _read_headers(client).split(b"\r\n", 1)[0]
            client.close()
            _flush_runtime()
            metrics = bt.read_metrics(path)
            assert metrics["failure_counts"][bt.FAILURE_UPSTREAM_CONNECT] == 2
            entry = next(
                item
                for item in metrics["failure_summary"]
                if item["reason"] == bt.FAILURE_UPSTREAM_CONNECT
            )
            assert entry["count"] == 2
            assert isinstance(entry["last_seen"], (int, float))

            bt.close_runtime()
            finalized = bt.finalize_batch(path, "batch-fail", 0)
            assert finalized["running"] is False
            finalized_metrics = bt.read_metrics(path)
            assert finalized_metrics["running"] is False
            assert finalized_metrics["failure_counts"] == metrics["failure_counts"]
            assert finalized_metrics["failure_summary"] == metrics["failure_summary"]
            _assert_private_mode(path)

            # The persisted file must contain no addresses or credentials.
            text = path.read_text(encoding="utf-8")
            on_disk = json.loads(text)
            assert UPSTREAM_USER not in text
            assert UPSTREAM_PASS not in text
            assert "127.0.0.1" not in text
            assert "@" not in text  # no proxy URLs / userinfo of any kind
            assert urlparse(meter_ok).password not in text
            for entry in on_disk["failure_summary"]:
                assert set(entry) == {"reason", "count", "last_seen"}
            assert set(on_disk["failure_counts"]) == set(bt.FAILURE_REASONS)

            # Starting a new batch clears all failure attribution state.
            reset = bt.initialize_batch(path, "batch-next", target=2, workers=2)
            assert reset["running"] is True
            assert reset["failure_counts"] == bt._empty_failure_counts()
            assert reset["failure_summary"] == []
            assert reset["connections"] == 0
    finally:
        bt.close_runtime()
        for server in servers:
            server.shutdown()
            server.server_close()
        if previous_file is None:
            os.environ.pop(bt.TRAFFIC_FILE_ENV, None)
        else:
            os.environ[bt.TRAFFIC_FILE_ENV] = previous_file
        if previous_id is None:
            os.environ.pop(bt.BATCH_ID_ENV, None)
        else:
            os.environ[bt.BATCH_ID_ENV] = previous_id


def test_read_metrics_backfills_and_sanitizes_failure_fields() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "legacy_batch_traffic.json"

        # A legacy file written before failure attribution existed.
        atomic_write_json(
            path,
            {
                "version": bt.SCHEMA_VERSION,
                "batch_id": "legacy-batch",
                "running": False,
                "bytes_up": 10,
                "bytes_down": 20,
                "connections": 3,
            },
        )
        metrics = bt.read_metrics(path)
        assert metrics["failure_counts"] == bt._empty_failure_counts()
        assert metrics["failure_summary"] == []
        assert metrics["bytes_total"] == 30
        _assert_private_mode(path)

        # Corrupt and partial values are cleaned into non-negative integers;
        # unknown reasons and summary-only fields never leak through.
        atomic_write_json(
            path,
            {
                "version": bt.SCHEMA_VERSION,
                "batch_id": "dirty-batch",
                "failure_counts": {
                    bt.FAILURE_PROXY_AUTH: -7,
                    bt.FAILURE_TRANSPORT: "not-a-number",
                    bt.FAILURE_HEADER_TOO_LARGE: 3,
                    "made_up_reason": 9,
                },
                "failure_summary": [
                    {
                        "reason": bt.FAILURE_PROXY_AUTH,
                        "count": 4,
                        "last_seen": 123.5,
                        "secret": "upstream-secret-pass-7071",
                    },
                    {"reason": "made_up_reason", "count": 1, "last_seen": 1.0},
                    {"reason": bt.FAILURE_TRANSPORT, "count": 0, "last_seen": 2.0},
                    "junk-entry",
                    {
                        "reason": bt.FAILURE_CONNECT_REJECTED,
                        "count": 2,
                        "last_seen": "bad-timestamp",
                    },
                ],
            },
        )
        metrics = bt.read_metrics(path)
        assert metrics["failure_counts"] == {
            bt.FAILURE_UPSTREAM_CONNECT: 0,
            bt.FAILURE_PROXY_AUTH: 0,
            bt.FAILURE_HEADER_TOO_LARGE: 3,
            bt.FAILURE_CONNECT_REJECTED: 0,
            bt.FAILURE_TRANSPORT: 0,
        }
        assert metrics["failure_summary"] == [
            {"reason": bt.FAILURE_PROXY_AUTH, "count": 4, "last_seen": 123.5},
            {"reason": bt.FAILURE_CONNECT_REJECTED, "count": 2, "last_seen": None},
        ]
        for entry in metrics["failure_summary"]:
            assert set(entry) == {"reason", "count", "last_seen"}
        text = path.read_text(encoding="utf-8")
        assert "upstream-secret-pass-7071" in text  # present only in raw fixture
        assert "upstream-secret-pass-7071" not in json.dumps(
            metrics["failure_summary"]
        )

        # A missing file still yields the complete structure with zeroed fields.
        missing = Path(temp) / "missing.json"
        empty = bt.read_metrics(missing)
        assert empty["failure_counts"] == bt._empty_failure_counts()
        assert empty["failure_summary"] == []
        assert empty["running"] is False


if __name__ == "__main__":
    test_failure_attribution_categories_and_sanitized_summary()
    test_read_metrics_backfills_and_sanitizes_failure_fields()
    print("OK batch traffic failures")
