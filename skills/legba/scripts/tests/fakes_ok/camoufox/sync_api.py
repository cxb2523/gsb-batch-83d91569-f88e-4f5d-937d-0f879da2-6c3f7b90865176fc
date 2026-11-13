"""Test double for ``camoufox.sync_api``.

This is NOT a browser. It fetches the target URL straight over urllib from a
local fake server, so antibot.py's whole flow -- provision, challenge
detection, exit rotation, page write-out, report writing -- can be exercised
with no Camoufox install, no real residential exit, and no traffic beyond
127.0.0.1.

Behaviour switches are environment variables, because antibot.py runs this in
a subprocess that has no test harness inside it:

  FAKE_CAMOUFOX_FAIL_START=1  every Camoufox launch raises (browser unusable)
  FAKE_CAMOUFOX_TICK_SLEEP    cap for wait_for_timeout, ms (default 20)
"""
import os
import re
import time
import urllib.request
import urllib.error


def _http_get(url):
    # Never honor ambient proxy settings: the "target" is a loopback test server.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=15) as r:
        return r.read().decode("utf-8")


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_BODY_RE = re.compile(r"<body[^>]*>(.*?)</body>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class _FakePage:
    """Stand-in for a Playwright/Camoufox page."""

    def __init__(self):
        self._url = ""
        self._html = ""

    def goto(self, url, wait_until=None, timeout=None):
        self._url = url
        self._html = _http_get(url)

    def _refetch(self):
        # A real interstitial re-renders/re-fetches while the challenge runs.
        # Model that by asking the local target again on every wait tick, so a
        # server-side exit rotation can change what the page shows.
        if not self._url:
            return
        try:
            self._html = _http_get(self._url)
        except urllib.error.URLError:
            pass

    def wait_for_timeout(self, ms):
        cap = float(os.environ.get("FAKE_CAMOUFOX_TICK_SLEEP", "20"))
        time.sleep(min(ms, cap) / 1000.0)
        self._refetch()

    def title(self):
        m = _TITLE_RE.search(self._html or "")
        return _TAG_RE.sub("", m.group(1)).strip() if m else ""

    def inner_text(self, selector):
        m = _BODY_RE.search(self._html or "")
        text = m.group(1) if m else (self._html or "")
        return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()

    def content(self):
        return self._html

    def wait_for_load_state(self, state, timeout=None):
        return None

    def screenshot(self, path=None, **kwargs):
        if path:
            with open(path, "wb") as f:
                f.write(b"fake-screenshot")

    def close(self):
        return None


class _FakeContext:
    def new_page(self):
        if os.environ.get("FAKE_CAMOUFOX_FAIL_NEWPAGE") == "1":
            raise RuntimeError("simulated failure after the browser started")
        return _FakePage()


class Camoufox:
    """Mirrors the real Camoufox context-manager surface antibot.py touches."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._ctx = None

    def __enter__(self):
        if os.environ.get("FAKE_CAMOUFOX_FAIL_START") == "1":
            raise RuntimeError("simulated browser launch failure")
        self._ctx = _FakeContext()
        return self._ctx

    def __exit__(self, *exc):
        self._ctx = None
        return False
