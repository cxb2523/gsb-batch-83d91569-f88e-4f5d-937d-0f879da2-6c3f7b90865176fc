"""Runtime status exposure contract for the private browser worker.

The fake worker below listens on an ephemeral localhost port instead of a Unix
socket so the same suite runs on platforms without ``socket.AF_UNIX``. It never
contacts Reddit and never uses real cookies.
"""
import hashlib
import http.client
import http.server
import json
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from webmirage.platforms.reddit import browser
from webmirage.platforms.reddit.browser import SUPPORTED_TOOLS, runtime_status, worker_call
from webmirage.platforms.reddit.client import RedditError


class FakeWorkerHandler(http.server.BaseHTTPRequestHandler):
    """Returns canned worker envelopes and records every request body."""

    envelope = {'ok': True, 'status': {}}
    requests = []

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length)
        self.requests.append(json.loads(raw))
        body = json.dumps(self.envelope).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ThreadedHttpServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class TcpConnection(http.client.HTTPConnection):
    """Drop-in for UnixConnection that dials a 127.0.0.1 port instead of a socket."""

    def __init__(self, url, timeout):
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        super().__init__(parts.hostname, parts.port, timeout=timeout)


class fake_worker_socket:
    """Point worker_call's UnixConnection at the TCP fake worker."""

    def __init__(self, url):
        self.url = url

    def __enter__(self):
        self.patch = patch.object(browser, 'UnixConnection',
                                  lambda path, timeout: TcpConnection(self.url, timeout))
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()
        return False


class FakeWorker:
    def __init__(self, envelope):
        FakeWorkerHandler.envelope = envelope
        FakeWorkerHandler.requests = []
        self.server = ThreadedHttpServer(('127.0.0.1', 0), FakeWorkerHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        host, port = self.server.server_address
        return f'http://{host}:{port}'

    @property
    def requests(self):
        return FakeWorkerHandler.requests

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def full_status(**overrides):
    status = {
        'available': True, 'version': '2.0.2', 'running': True,
        'session_imported': True, 'busy': False, 'last_activity': 1_700_000_000,
        'last_failure': None, 'cooldown_until': 0, 'idle_seconds': 600,
        'supported_tools': list(SUPPORTED_TOOLS), 'session_current': True,
    }
    status.update(overrides)
    return {'ok': True, 'status': status}


class RuntimeStatusTests(unittest.TestCase):
    def setUp(self):
        self.config = {'reddit_backend': 'opencli', 'reddit_cookie': 'reddit_session=CURRENT'}

    def test_healthy_worker_exposes_whitelisted_fields_and_matching_session(self):
        worker = FakeWorker(full_status())
        try:
            with fake_worker_socket(worker.url):
                status = runtime_status(self.config)
        finally:
            worker.stop()
        self.assertTrue(status['available'])
        self.assertTrue(status['running'])
        self.assertTrue(status['session_imported'])
        self.assertTrue(status['session_current'])
        self.assertEqual(status['version'], '2.0.2')
        self.assertFalse(status['busy'])
        self.assertEqual(status['last_activity'], 1_700_000_000)
        self.assertIsNone(status['last_failure'])
        self.assertEqual(status['cooldown_until'], 0)
        self.assertEqual(status['idle_seconds'], 600)
        self.assertEqual(status['supported_tools'], list(SUPPORTED_TOOLS))
        self.assertEqual(status['backend'], 'opencli')
        # The passive status call carries only the cookie digest, never the cookie.
        request = worker.requests[0]
        self.assertEqual(request['action'], 'status')
        self.assertEqual(request['revision'], hashlib.sha256(b'reddit_session=CURRENT').hexdigest())
        self.assertNotIn('cookie', request)
        self.assertNotIn('CURRENT', json.dumps(request))

    def test_changed_config_cookie_reports_session_not_current(self):
        worker = FakeWorker(full_status(session_current=False))
        try:
            with fake_worker_socket(worker.url):
                status = runtime_status(self.config)
        finally:
            worker.stop()
        self.assertTrue(status['session_imported'])
        self.assertFalse(status['session_current'])

    def test_unknown_failure_category_falls_back_to_unknown(self):
        worker = FakeWorker(full_status(last_failure='mystery_blob_9f3a'))
        try:
            with fake_worker_socket(worker.url):
                status = runtime_status(self.config)
        finally:
            worker.stop()
        self.assertEqual(status['last_failure'], 'unknown')
        self.assertNotIn('mystery_blob_9f3a', json.dumps(status))

    def test_known_failure_categories_pass_through_unchanged(self):
        for category in ('rate_limit', 'forbidden', 'risk', 'auth', 'network',
                         'interface', 'browser', 'missing', 'busy'):
            worker = FakeWorker(full_status(last_failure=category))
            try:
                with fake_worker_socket(worker.url):
                    status = runtime_status(self.config)
            finally:
                worker.stop()
            self.assertEqual(status['last_failure'], category)

    def test_non_whitelisted_fields_are_stripped_even_when_worker_sends_them(self):
        secret_status = full_status()
        secret_status.update({'cookie': 'reddit_session=RAW-COOKIE',
                              'revision': hashlib.sha256(b'x').hexdigest(),
                              'traceback': 'boom: SECRET-DETAIL', 'unexpected': 1})
        worker = FakeWorker({'ok': True, 'status': secret_status})
        try:
            with fake_worker_socket(worker.url):
                status = runtime_status(self.config)
        finally:
            worker.stop()
        rendered = json.dumps(status)
        for leaked in ('RAW-COOKIE', 'SECRET-DETAIL', 'traceback', 'unexpected'):
            self.assertNotIn(leaked, rendered)
        self.assertNotIn('cookie', status)
        self.assertNotIn('revision', status)

    def test_cooldown_state_is_surfaced_with_running_false(self):
        worker = FakeWorker(full_status(running=False, last_failure='rate_limit',
                                        cooldown_until=4_000_000_000))
        try:
            with fake_worker_socket(worker.url):
                status = runtime_status(self.config)
        finally:
            worker.stop()
        self.assertTrue(status['available'])
        self.assertFalse(status['running'])
        self.assertEqual(status['last_failure'], 'rate_limit')
        self.assertEqual(status['cooldown_until'], 4_000_000_000)


class MissingWorkerTests(unittest.TestCase):
    def test_missing_socket_returns_unavailable_without_raising_or_leaking(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = str(Path(folder) / 'absent.sock')
            with patch.dict('os.environ', {'REDDIT_BROWSER_SOCKET': missing}):
                status = runtime_status({'reddit_backend': 'opencli',
                                         'reddit_cookie': 'reddit_session=PRIVATE'})
        self.assertFalse(status['available'])
        self.assertFalse(status['running'])
        self.assertFalse(status['session_imported'])
        self.assertEqual(status['backend'], 'opencli')
        self.assertNotIn('PRIVATE', json.dumps(status))

    def test_missing_socket_query_raises_categorised_error_without_cookie(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RedditError) as error:
                worker_call({'action': 'query', 'cookie': 'PRIVATE'},
                            path=str(Path(folder) / 'absent.sock'))
        self.assertNotIn('PRIVATE', str(error.exception))
        self.assertIn('browser', str(error.exception))

    def test_runtime_without_af_unix_does_not_raise(self):
        # Simulates Windows builds where socket.AF_UNIX is absent.
        original = getattr(browser.socket, 'AF_UNIX', None)
        try:
            if hasattr(browser.socket, 'AF_UNIX'):
                del browser.socket.AF_UNIX
            with tempfile.TemporaryDirectory() as folder:
                with patch.dict('os.environ',
                                {'REDDIT_BROWSER_SOCKET': str(Path(folder) / 'absent.sock')}):
                    status = runtime_status({'reddit_cookie': 'PRIVATE'})
            self.assertFalse(status['available'])
        finally:
            if original is not None:
                browser.socket.AF_UNIX = original


if __name__ == '__main__':
    unittest.main()
