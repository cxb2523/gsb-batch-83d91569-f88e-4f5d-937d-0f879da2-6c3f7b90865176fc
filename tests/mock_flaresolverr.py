#!/usr/bin/env python3
"""Black-box mock of FlareSolverr v3.5.2 for FlareProxy behaviour tests.

Usage::

    python tests/mock_flaresolverr.py <port>

The mock speaks the JSON-in / JSON-out ``POST /v1`` protocol used by
FlareSolverr and additionally exposes control endpoints that only the test
harness is expected to call::

    GET /__state                      -> JSON snapshot of counters + events
    GET /__reset                      -> zero all counters and forget sessions
    GET /__kill_session?session=<id>  -> drop a session out-of-band, as if the
                                         upstream browser had been reaped
    GET /__fail_requests?count=<n>    -> make the next n request.get/post
                                         commands fail with an ordinary
                                         (non-session) solve error
    GET /__stale_sessions?count=<n>   -> make the next n request.get/post
                                         commands fail with a "session not
                                         found" error regardless of whether
                                         the session exists (deterministic
                                         stale-session simulation)

When a ``request.*`` command references a session the mock does not know
about, it answers ``status=error`` with a "session not found" message, the
same way a real FlareSolverr instance reacts to a stale session id.

Environment:
    MOCK_DELAY  float seconds to sleep before answering any ``request.*``
                command (used to exercise single-flight coalescing).

Only the standard library is used.
"""

import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MOCK_DELAY = float(os.getenv("MOCK_DELAY", "0") or 0)
VERSION = "3.5.2"


class _State:
    """Mutable, thread-safe mock state."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.session_creates = 0
        self.requests = 0
        self.requests_with_session = 0
        self.requests_without_session = 0
        self.urls = {}
        self.sessions = []          # insertion-ordered session ids
        self.session_set = set()
        self.events = []
        self.session_visits = {}    # session id -> monotonic visit counter
        self.fresh_visits = 0       # cold "fresh browser" visit counter
        # Remaining request.* commands that must fail with an ordinary
        # (non-session) solve error; 0 means all requests succeed.
        self.fail_requests_remaining = 0
        self.request_failures = 0
        # Remaining request.* commands that must fail with a stale-session
        # error even if a session with that id still exists upstream.
        self.stale_sessions_remaining = 0
        self.stale_session_failures = 0

    def snapshot(self):
        with self.lock:
            return {
                "version": VERSION,
                "session_creates": self.session_creates,
                "requests": self.requests,
                "requests_with_session": self.requests_with_session,
                "requests_without_session": self.requests_without_session,
                "urls": dict(self.urls),
                "sessions": list(self.sessions),
                "session_visits": dict(self.session_visits),
                "fresh_visits": self.fresh_visits,
                "fail_requests_remaining": self.fail_requests_remaining,
                "request_failures": self.request_failures,
                "stale_sessions_remaining": self.stale_sessions_remaining,
                "stale_session_failures": self.stale_session_failures,
                "events": list(self.events),
            }


STATE = _State()


def _record(event):
    STATE.events.append(event)


def _kill_session(sid):
    """Forget a session out-of-band, like an upstream reaper would."""
    with STATE.lock:
        existed = sid in STATE.session_set
        STATE.session_set.discard(sid)
        STATE.sessions = [s for s in STATE.sessions if s != sid]
        if existed:
            _record({"type": "control_session_killed", "session": sid})
    return existed


def _arm_request_failures(count):
    """Make the next ``count`` request.* commands fail with a solve error."""
    with STATE.lock:
        STATE.fail_requests_remaining = max(0, int(count))
    return STATE.fail_requests_remaining


def _arm_stale_sessions(count):
    """Make the next ``count`` request.* commands fail as stale-session errors."""
    with STATE.lock:
        STATE.stale_sessions_remaining = max(0, int(count))
    return STATE.stale_sessions_remaining


def _handle_command(payload):
    cmd = payload.get("cmd", "")
    if cmd == "sessions.create":
        sid = payload.get("session")
        if not sid:
            return {"status": "error", "message": "session name is required"}
        with STATE.lock:
            if sid in STATE.session_set:
                _record({"type": "session_exists", "session": sid})
                return {
                    "status": "ok",
                    "message": "Session already exists.",
                    "session": sid,
                    "version": VERSION,
                }
            STATE.session_set.add(sid)
            STATE.sessions.append(sid)
            STATE.session_visits.setdefault(sid, 0)
            STATE.session_creates += 1
            _record({"type": "session_create", "session": sid})
        return {
            "status": "ok",
            "message": "Session created successfully.",
            "session": sid,
            "version": VERSION,
        }

    if cmd == "sessions.list":
        with STATE.lock:
            sessions = list(STATE.sessions)
        return {"status": "ok", "message": "", "sessions": sessions}

    if cmd == "sessions.destroy":
        sid = payload.get("session")
        with STATE.lock:
            if sid in STATE.session_set:
                STATE.session_set.discard(sid)
                STATE.sessions = [s for s in STATE.sessions if s != sid]
                _record({"type": "session_destroy", "session": sid})
                return {"status": "ok", "message": "The session has been removed."}
        return {"status": "error", "message": "Session not found."}

    if cmd in ("request.get", "request.post"):
        if MOCK_DELAY > 0:
            time.sleep(MOCK_DELAY)
        url = payload.get("url", "")
        sid = payload.get("session") or None
        with STATE.lock:
            STATE.requests += 1
            STATE.urls[url] = STATE.urls.get(url, 0) + 1
            if STATE.stale_sessions_remaining > 0:
                # Deterministic stale-session simulation: even an existing
                # session id is reported as gone for the next few requests.
                STATE.stale_sessions_remaining -= 1
                STATE.stale_session_failures += 1
                _record(
                    {
                        "type": "stale_session_error",
                        "method": cmd,
                        "url": url,
                        "session": sid,
                    }
                )
                return {
                    "status": "error",
                    "message": (
                        "Session not found. Please create a session first."
                    ),
                }
            if STATE.fail_requests_remaining > 0:
                # An ordinary solve failure: no mention of the session being
                # gone, so the proxy must treat it as a non-session error.
                STATE.fail_requests_remaining -= 1
                STATE.request_failures += 1
                _record(
                    {
                        "type": "request_error",
                        "method": cmd,
                        "url": url,
                        "session": sid,
                        "reason": "injected_solve_failure",
                    }
                )
                return {
                    "status": "error",
                    "message": (
                        "Error solving the challenge. Unable to solve "
                        "the challenge."
                    ),
                }
            if sid:
                STATE.requests_with_session += 1
                if sid not in STATE.session_set:
                    # The browser behind this id has been destroyed/reaped.
                    # Mimic a real FlareSolverr answering a stale session
                    # instead of silently resurrecting it.
                    _record(
                        {
                            "type": "missing_session",
                            "method": cmd,
                            "url": url,
                            "session": sid,
                        }
                    )
                    return {
                        "status": "error",
                        "message": (
                            "Session not found. Please create a session first."
                        ),
                    }
                STATE.session_visits[sid] = STATE.session_visits.get(sid, 0) + 1
                visit = STATE.session_visits[sid]
                label = sid
            else:
                STATE.requests_without_session += 1
                STATE.fresh_visits += 1
                visit = STATE.fresh_visits
                label = "none"
                _record(
                    {
                        "type": "fresh_browser",
                        "url": url,
                        "method": cmd,
                        "visit": visit,
                        "max_timeout": payload.get("maxTimeout"),
                    }
                )
            _record(
                {
                    "type": "request",
                    "method": cmd,
                    "url": url,
                    "session": sid,
                    "visit": visit,
                    "max_timeout": payload.get("maxTimeout"),
                }
            )
        body = "visits=%d,session=%s" % (visit, label)
        return {
            "status": "ok",
            "message": "Challenge not detected!",
            "solution": {
                "status": 200,
                "headers": {"Content-Type": "text/html"},
                "response": body,
                "userAgent": "Mozilla/5.0 (MockFlareSolverr)",
            },
        }

    return {"status": "error", "message": "Unknown command: %s" % cmd}


class MockHandler(BaseHTTPRequestHandler):
    server_version = "MockFlareSolverr/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # silence access logging
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if path == "/__state":
            self._send_json(STATE.snapshot())
            return
        if path == "/__reset":
            with STATE.lock:
                STATE.reset()
            self._send_json({"status": "ok"})
            return
        if path == "/__kill_session":
            sid = (query.get("session") or [""])[0]
            if not sid:
                self._send_json(
                    {"status": "error", "message": "session parameter required"},
                    status=400,
                )
                return
            existed = _kill_session(sid)
            self._send_json({"status": "ok", "session": sid, "existed": existed})
            return
        if path == "/__fail_requests":
            try:
                count = int((query.get("count") or ["1"])[0])
            except ValueError:
                count = 1
            armed = _arm_request_failures(count)
            self._send_json({"status": "ok", "fail_requests_remaining": armed})
            return
        if path == "/__stale_sessions":
            try:
                count = int((query.get("count") or ["1"])[0])
            except ValueError:
                count = 1
            armed = _arm_stale_sessions(count)
            self._send_json(
                {"status": "ok", "stale_sessions_remaining": armed}
            )
            return
        self._send_json({"status": "error", "message": "not found"}, status=404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            self._send_json({"status": "error", "message": "invalid json"}, status=400)
            return
        if not isinstance(payload, dict):
            self._send_json({"status": "error", "message": "invalid payload"}, status=400)
            return
        self._send_json(_handle_command(payload))


def main(argv):
    if len(argv) != 2:
        print("usage: mock_flaresolverr.py <port>", file=sys.stderr)
        return 2
    port = int(argv[1])
    server = ThreadingHTTPServer(("127.0.0.1", port), MockHandler)
    server.daemon_threads = True
    print("Mock FlareSolverr v%s listening on 127.0.0.1:%d" % (VERSION, port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
