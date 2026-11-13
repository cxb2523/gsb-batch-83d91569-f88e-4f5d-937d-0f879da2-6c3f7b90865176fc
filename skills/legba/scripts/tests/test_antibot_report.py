"""Tests for antibot.py's run report and its exit-code boundaries.

Everything here is local on purpose:
  * a thread HTTPServer plays BOTH the fake Legba API (proxy provision / rotate
    / release) and the fake target site (a "Just a moment..." challenge page
    that can either clear, stay stuck, or change after an exit rotation);
  * a fake ``camoufox`` package on PYTHONPATH shadows any real Camoufox, so no
    browser binary and no real Legba service is involved.

Run from anywhere:  python -m pytest skills/legba/scripts/tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ANTIBOT = os.path.join(SCRIPTS, "antibot.py")
FAKES_OK = os.path.join(HERE, "fakes_ok")
FAKES_BROKEN = os.path.join(HERE, "fakes_broken")

CHALLENGE_HTML = (
    "<!doctype html><html><head><title>Just a moment...</title></head>"
    "<body><h1>Checking your browser before accessing the site.</h1>"
    "<p>Verifying you are human. This may take a few seconds.</p></body></html>"
)
REAL_HTML = (
    "<!doctype html><html><head><title>Widget Co — Prices</title></head>"
    "<body><h1>Widget Co</h1><p>Premier widgets, delivered discreetly.</p>"
    "<ul><li>Basic — $9</li><li>Pro — $42</li></ul></body></html>"
)


class FakeLegbaState:
    """In-memory state for the fake API + fake target server."""

    def __init__(self, mode):
        # mode: "clear"         target serves the real page immediately
        #       "stuck"         target always serves the interstitial
        #       "rotate_ok"     interstitial until the first successful rotate,
        #                       then the real page
        #       "rotate_fail"   rotate endpoint answers 500; target stays stuck
        self.mode = mode
        self.rotations = 0
        self.releases = 0
        self.provisions = 0
        self.target_hits = 0
        self.lock = threading.Lock()


class FakeHandler(BaseHTTPRequestHandler):
    # Assigned on the class by the fixture, one fresh server per test.
    state = None

    def log_message(self, *args):  # silence per-request stderr noise
        pass

    # -- helpers -----------------------------------------------------------
    def _send(self, code, body, content_type="application/json"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json")

    # -- routing -----------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        st = self.state
        if parsed.path == "/proxy":  # provision an exit
            with st.lock:
                st.provisions += 1
            self._send_json(200, {
                "proxy_id": "px-test-1",
                "exit_ip": "203.0.113.7",
                "exit_city": "Testville",
                "ip_type": "residential",
                "rules": {"singleProxy": {"scheme": "http", "host": "127.0.0.1", "port": 8080}},
                "auth": {"username": "u", "password": "p"},
            })
        elif parsed.path == "/target":  # the "site" the browser fetches
            with st.lock:
                st.target_hits += 1
                mode = st.mode
                rotations = st.rotations
            if mode == "clear" or (mode == "rotate_ok" and rotations >= 1):
                self._send(200, REAL_HTML, "text/html; charset=utf-8")
            else:
                self._send(200, CHALLENGE_HTML, "text/html; charset=utf-8")
        else:
            self._send_json(404, {"error": f"unknown path {parsed.path}"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        st = self.state
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if parsed.path == "/proxy/px-test-1/rotate":
            if st.mode == "rotate_fail":
                self._send_json(500, {"error": "simulated rotate failure"})
                return
            with st.lock:
                st.rotations += 1
            self._send_json(200, {"ok": True, "exit_ip": "203.0.113.9"})
        elif parsed.path == "/proxy/px-test-1/release":
            with st.lock:
                st.releases += 1
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": f"unknown path {parsed.path}"})


@pytest.fixture
def fake_server():
    server = HTTPServer(("127.0.0.1", 0), FakeHandler)
    state = FakeLegbaState(mode="clear")
    FakeHandler.state = state  # server is per-test, so the class attr is safe
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _run_antibot(tmp_path, base_url, mode, *, extra_args=None, fake_pkg=FAKES_OK,
                 wait_ms=1500, rotate_attempts=None, extra_env=None):
    """Invoke antibot.py in a subprocess with the fake camoufox on PYTHONPATH."""
    # The fixture creates the server in neutral "clear" mode; each test picks
    # the target's behavior here, before the subprocess makes its first request.
    FakeHandler.state.mode = mode
    home = tmp_path / "home"
    home.mkdir()
    report = tmp_path / "run.json"
    out = tmp_path / "page.html"
    args = [
        sys.executable, ANTIBOT,
        f"{base_url}/target",
        "--wait", str(wait_ms),
        "--report", str(report),
        "--out", str(out),
    ]
    if extra_args:
        args.extend(extra_args)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),  # Windows: SSL/registry needs it
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LEGBA_API_KEY": "lk_test_fake",
        "LEGBA_BASE": base_url,
        "PYTHONPATH": fake_pkg,
        "PYTHONIOENCODING": "utf-8",
        # Never let a real ambient HTTP proxy intercept loopback test traffic.
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "FAKE_CAMOUFOX_TICK_SLEEP": "10",
    }
    if rotate_attempts is not None:
        env["LEGBA_ANTIBOT_ROTATE_ATTEMPTS"] = str(rotate_attempts)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(args, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=60)
    return proc, report, out, home


REPORT_KEYS = {"url", "title", "html_bytes", "cleared", "rotations", "exit_code"}


def _load_report(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Path 1: real page — challenge clears, exit 0, report says cleared.
# ---------------------------------------------------------------------------
def test_success_writes_cleared_report_and_matching_bytes(fake_server, tmp_path):
    server, state = fake_server
    base = f"http://127.0.0.1:{server.server_port}"
    proc, report, out, _ = _run_antibot(tmp_path, base, "clear")

    assert proc.returncode == 0, proc.stderr
    assert state.provisions == 1 and state.releases == 1 and state.rotations == 0

    data = _load_report(report)
    assert REPORT_KEYS.issubset(data.keys())
    assert data["cleared"] is True
    assert data["exit_code"] == 0
    assert data["title"] == "Widget Co — Prices"
    assert data["url"] == f"{base}/target"
    assert data["rotations"] == 0
    assert data["rotate_failed"] is False

    # html_bytes must be exactly what the --out file received — one source of truth.
    written = out.read_bytes()
    assert written == REAL_HTML.encode("utf-8")
    assert data["html_bytes"] == len(written)
    assert "Just a moment" not in written.decode("utf-8")


# ---------------------------------------------------------------------------
# Path 2: challenge never clears — exit 5, report says not cleared, and the
# interstitial (not the answer) is what the bytes describe.
# ---------------------------------------------------------------------------
def test_challenge_timeout_exit5_not_cleared(fake_server, tmp_path):
    server, state = fake_server
    base = f"http://127.0.0.1:{server.server_port}"
    # Stuck page: one attempt only, short ceiling so the test stays quick.
    proc, report, out, _ = _run_antibot(
        tmp_path, base, "stuck", wait_ms=300, rotate_attempts=0)

    assert proc.returncode == 5, proc.stderr
    assert "did not clear" in proc.stderr
    assert state.rotations == 0

    data = _load_report(report)
    assert data["cleared"] is False
    assert data["exit_code"] == 5
    assert data["title"] == "Just a moment..."
    assert data["rotations"] == 0
    assert data["rotate_failed"] is False

    written = out.read_bytes()
    assert written == CHALLENGE_HTML.encode("utf-8")
    assert data["html_bytes"] == len(written)  # report counts the actual output


def test_report_bytes_match_stdout_when_no_out(fake_server, tmp_path):
    # Same byte-consistency rule on the stdout path: no separately computed size.
    server, _ = fake_server
    base = f"http://127.0.0.1:{server.server_port}"
    home = tmp_path / "home"; home.mkdir()
    report = tmp_path / "run.json"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "HOME": str(home), "USERPROFILE": str(home),
        "LEGBA_API_KEY": "lk_test_fake", "LEGBA_BASE": base,
        "PYTHONPATH": FAKES_OK, "PYTHONIOENCODING": "utf-8",
        "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        "FAKE_CAMOUFOX_TICK_SLEEP": "10",
    }
    proc = subprocess.run(
        [sys.executable, ANTIBOT, f"{base}/target", "--wait", "1500",
         "--report", str(report)],
        env=env, capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    data = _load_report(report)
    assert data["html_bytes"] == len(proc.stdout)
    assert proc.stdout == REAL_HTML.encode("utf-8")


# ---------------------------------------------------------------------------
# Path 3: the rotate request itself fails. The failure must be recorded,
# retries must stop, and the run must never claim it cleared.
# ---------------------------------------------------------------------------
def test_rotate_failure_is_recorded_and_stops_retries(fake_server, tmp_path):
    server, state = fake_server
    base = f"http://127.0.0.1:{server.server_port}"
    proc, report, out, _ = _run_antibot(
        tmp_path, base, "rotate_fail", wait_ms=300, rotate_attempts=2)

    assert proc.returncode == 5, proc.stderr
    assert "rotate failed" in proc.stderr
    data = _load_report(report)
    assert data["cleared"] is False
    assert data["exit_code"] == 5
    assert data["rotate_failed"] is True
    assert "500" in data["rotate_error"]
    assert data["rotations"] == 0  # no successful rotation was counted
    # Exactly one rotate was attempted; the failure ended the retry loop instead
    # of being swallowed and retried through the remaining attempts.
    assert state.rotations == 0
    assert state.releases == 1
    written = out.read_bytes()
    assert data["html_bytes"] == len(written)


def test_successful_rotation_is_counted_and_then_clears(fake_server, tmp_path):
    # Companion of the failure path: when rotate works, rotations counts the
    # actual exits used and the next attempt reaches the real page.
    server, state = fake_server
    base = f"http://127.0.0.1:{server.server_port}"
    proc, report, out, _ = _run_antibot(
        tmp_path, base, "rotate_ok", wait_ms=300, rotate_attempts=2)

    assert proc.returncode == 0, proc.stderr
    assert state.rotations == 1
    data = _load_report(report)
    assert data["cleared"] is True
    assert data["exit_code"] == 0
    assert data["rotations"] == 1
    assert data["rotate_failed"] is False
    assert out.read_bytes() == REAL_HTML.encode("utf-8")
    assert data["html_bytes"] == len(out.read_bytes())


# ---------------------------------------------------------------------------
# Exit 3: the machine cannot host the browser. A report must still land first
# so the collector can distinguish "environment broken" from "challenge stuck".
# ---------------------------------------------------------------------------
def test_browser_wont_start_exit3_still_writes_report(fake_server, tmp_path):
    server, state = fake_server
    base = f"http://127.0.0.1:{server.server_port}"
    proc, report, out, _ = _run_antibot(
        tmp_path, base, "clear",
        extra_env={"FAKE_CAMOUFOX_FAIL_START": "1"})

    assert proc.returncode == 3, proc.stderr
    assert "rung 3 unavailable" in proc.stderr
    data = _load_report(report)
    assert data["exit_code"] == 3
    assert data["cleared"] is False
    assert data["html_bytes"] == 0  # nothing was fetched
    assert data["title"] == ""
    assert "no_local_browser" in data["error"]
    # The exit was provisioned and must still be released on the way out.
    assert state.releases == 1
    assert not out.exists()  # no page was written, and no stray file created


def test_broken_camoufox_import_exit3_writes_report(fake_server, tmp_path):
    server, _ = fake_server
    base = f"http://127.0.0.1:{server.server_port}"
    proc, report, out, _ = _run_antibot(
        tmp_path, base, "clear", fake_pkg=FAKES_BROKEN)

    assert proc.returncode == 3, proc.stderr
    data = _load_report(report)
    assert data["exit_code"] == 3
    assert data["cleared"] is False
    assert data["html_bytes"] == 0
    assert "import" in data["error"].lower()


# ---------------------------------------------------------------------------
# Backward compatibility: without --report no report file appears and the
# observable behavior (output, exit code) is unchanged.
# ---------------------------------------------------------------------------
def test_no_report_creates_no_extra_files(fake_server, tmp_path):
    server, _ = fake_server
    base = f"http://127.0.0.1:{server.server_port}"
    home = tmp_path / "home"; home.mkdir()
    out = tmp_path / "page.html"
    before = set(os.listdir(tmp_path))
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "HOME": str(home), "USERPROFILE": str(home),
        "LEGBA_API_KEY": "lk_test_fake", "LEGBA_BASE": base,
        "PYTHONPATH": FAKES_OK, "PYTHONIOENCODING": "utf-8",
        "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        "FAKE_CAMOUFOX_TICK_SLEEP": "10",
    }
    proc = subprocess.run(
        [sys.executable, ANTIBOT, f"{base}/target", "--wait", "1500",
         "--out", str(out)],
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    after = set(os.listdir(tmp_path))
    # Without --report the only new top-level entry is the explicitly requested
    # --out file; no report or any other artifact appears.
    assert after - before == {"page.html"}
    assert not any(name.endswith(".json") for name in after)
    assert out.read_text(encoding="utf-8") == REAL_HTML


# ---------------------------------------------------------------------------
# A user-held proxy (--proxy): no Legba API is called at all, so there is
# nothing to rotate and the report must say rotations stayed at zero.
# ---------------------------------------------------------------------------
def test_user_supplied_proxy_skips_provisioning_and_rotation(fake_server, tmp_path):
    server, state = fake_server
    base = f"http://127.0.0.1:{server.server_port}"
    FakeHandler.state.mode = "clear"
    home = tmp_path / "home"; home.mkdir()
    report = tmp_path / "run.json"; out = tmp_path / "page.html"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "HOME": str(home), "USERPROFILE": str(home),
        # No LEGBA_API_KEY on purpose: this path must not need one.
        "PYTHONPATH": FAKES_OK, "PYTHONIOENCODING": "utf-8",
        "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        "FAKE_CAMOUFOX_TICK_SLEEP": "10",
    }
    proc = subprocess.run(
        [sys.executable, ANTIBOT, f"{base}/target", "--wait", "1500",
         "--proxy", "http://holder:secret@127.0.0.1:8080",
         "--out", str(out), "--report", str(report)],
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert state.provisions == 0 and state.rotations == 0 and state.releases == 0
    data = _load_report(report)
    assert data["cleared"] is True and data["exit_code"] == 0
    assert data["rotations"] == 0 and data["rotate_failed"] is False
    assert data["html_bytes"] == len(out.read_bytes())


# ---------------------------------------------------------------------------
# Provisioning itself fails: no browser work happens, but the report still
# lands so the collector sees a run that died on the environment, not a silent
# success over an empty page.
# ---------------------------------------------------------------------------
def test_provision_failure_writes_report_and_exits_nonzero(fake_server, tmp_path):
    server, state = fake_server
    base = f"http://127.0.0.1:{server.server_port}"
    # Turn the provision endpoint into a refusal for this run only.
    original_do_get = FakeHandler.do_GET

    def do_get_refuse(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/proxy":
            self._send_json(402, {"error": "plan does not cover this"})
            return
        return original_do_get(self)

    FakeHandler.do_GET = do_get_refuse
    try:
        proc, report, out, _ = _run_antibot(tmp_path, base, "clear")
    finally:
        FakeHandler.do_GET = original_do_get

    assert proc.returncode == 1, proc.stderr
    assert "provision 402" in proc.stderr
    data = _load_report(report)
    assert data["exit_code"] == 1
    assert data["cleared"] is False
    assert data["html_bytes"] == 0 and data["title"] == ""
    assert "provision 402" in data["error"]
    assert not out.exists()


def test_unexpected_runtime_error_still_leaves_a_report(fake_server, tmp_path):
    # The browser starts (so this is not exit 3), then blows up mid-run. The
    # catch-all must still write the report instead of a bare traceback.
    server, state = fake_server
    base = f"http://127.0.0.1:{server.server_port}"
    proc, report, out, _ = _run_antibot(
        tmp_path, base, "clear",
        extra_env={"FAKE_CAMOUFOX_FAIL_NEWPAGE": "1"})

    assert proc.returncode == 1, proc.stderr
    assert "unexpected failure" in proc.stderr
    data = _load_report(report)
    assert data["exit_code"] == 1 and data["cleared"] is False
    assert data["html_bytes"] == 0
    assert "simulated failure after the browser started" in data["error"]
    assert state.releases == 1  # the provisioned exit is still released


def test_report_creates_missing_parent_directory(fake_server, tmp_path):
    server, _ = fake_server
    base = f"http://127.0.0.1:{server.server_port}"
    nested = tmp_path / "reports" / "nested" / "run.json"
    home = tmp_path / "home"; home.mkdir()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "HOME": str(home), "USERPROFILE": str(home),
        "LEGBA_API_KEY": "lk_test_fake", "LEGBA_BASE": base,
        "PYTHONPATH": FAKES_OK, "PYTHONIOENCODING": "utf-8",
        "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        "FAKE_CAMOUFOX_TICK_SLEEP": "10",
    }
    proc = subprocess.run(
        [sys.executable, ANTIBOT, f"{base}/target", "--wait", "1500",
         "--report", str(nested)],
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    data = _load_report(nested)
    assert data["cleared"] is True and data["exit_code"] == 0
    # Untrusted-temp hygiene: nothing should have landed next to the script.
    assert not os.path.exists(os.path.join(SCRIPTS, "run.json"))
    shutil.rmtree(tmp_path / "reports", ignore_errors=True)
