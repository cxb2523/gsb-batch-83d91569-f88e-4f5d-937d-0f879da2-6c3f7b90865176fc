"""Offline sample for the full collection flow in playwright_scrape.collect_target.

Everything is faked: no browser is launched and no network is touched. A tiny
in-memory Playwright double stands in for the remote browser, and each
connection is scripted with the same observations a real run produces
(status code, headers, final URL, body, page-handler terminal state).

It verifies the policy around the verdict layer:

  A. a plain ok page ends immediately (1 attempt, page_handler stays off)
  B. a blocked plain attempt is retried on a new connection with page_handler=true,
     a handled challenge ends the run as "challenged" and page_handler is kept on
  C. blocked -> close, back off 10 s then 20 s, fresh identity, at most 2 more
     tries, then stop (4 attempts total, delays [10, 20])
  D. not-public stops at once, with no backoff and no retry
  E. oxylabs-network is retried as a network error and then succeeds
  F. a connection URL with the password inside an error string is always redacted

Run it:

    cd skills/agent-browser/scripts
    python collect_flow_sample.py            # exit code 0 means every check held

or, fully isolated, from the repository root:

    python -I skills/agent-browser/scripts/collect_flow_sample.py
"""

import contextlib
import io
import os
import sys

os.environ.setdefault("OXY_AB_USERNAME", "demo-user")
os.environ.setdefault("OXY_AB_PASSWORD", "s3cr3t-pw")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import playwright_scrape as ps  # noqa: E402


class FakeResponse:
    def __init__(self, outcome):
        self.status = outcome["status"]
        self.headers = dict(outcome.get("headers") or {})
        self.url = outcome["url"]


class FakeHandle:
    def __init__(self, state):
        self._state = state

    def json_value(self):
        return self._state


class FakePage:
    def __init__(self, outcome):
        self._outcome = outcome
        self.url = outcome["url"]

    def set_default_timeout(self, *_):
        pass

    def route(self, *_):
        pass

    def on(self, *_):
        pass

    def goto(self, *_args, **_kwargs):
        if self._outcome.get("goto_error"):
            raise self._outcome["goto_error"]
        return FakeResponse(self._outcome)

    def wait_for_timeout(self, *_):
        pass

    def content(self):
        return self._outcome["body"]

    def evaluate(self, *_):
        pass

    def wait_for_function(self, *_args, **_kwargs):
        state = self._outcome.get("state")
        if state is None:  # scripted "no terminal state in 90 s"
            raise RuntimeError("CHALLENGE_HANDLING_TIMEOUT")
        return FakeHandle(state)


class FakeCDP:
    def __init__(self, session_id):
        self._session_id = session_id

    def send(self, method):
        if method == "__session_id":
            return {"value": self._session_id}
        return {}


class FakeContext:
    def __init__(self, session_id, outcome):
        self._session_id = session_id
        self._outcome = outcome

    def add_init_script(self, *_):
        pass

    def new_page(self):
        return FakePage(self._outcome)

    def new_cdp_session(self, _page):
        return FakeCDP(self._session_id)


class FakeBrowser:
    def __init__(self, session_id, outcome):
        self.contexts = []
        self._session_id = session_id
        self._outcome = outcome
        self.closed = False

    def new_context(self):
        ctx = FakeContext(self._session_id, self._outcome)
        self.contexts.append(ctx)
        return ctx

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, outcomes):
        self._outcomes = outcomes
        self._next = 0
        self.connections = []  # (params dict, browser) for assertions

    def connect_over_cdp(self, _url, timeout=None):
        idx = self._next
        self._next += 1
        outcome = self._outcomes[idx]
        browser = FakeBrowser(f"sess-{idx + 1}", outcome)
        self.connections.append((dict(outcome.get("params") or {}), browser))
        return browser


class FakePlaywright:
    def __init__(self, outcomes):
        self.chromium = FakeChromium(outcomes)


@contextlib.contextmanager
def fake_pw(outcomes):
    pw = FakePlaywright(outcomes)
    yield pw


def run_scenario(name, outcomes):
    """Run collect_target against a scripted browser; capture logs and sleep delays."""
    delays = []

    def fake_sleep(seconds):
        delays.append(seconds)

    pw_cm = fake_pw(outcomes)
    real_pw = ps.sync_playwright
    ps.sync_playwright = lambda: pw_cm
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            result = ps.collect_target("https://shop.example.com/products/42", sleeper=fake_sleep)
    finally:
        ps.sync_playwright = real_pw
    return result, delays, buf.getvalue()


# Scripted per-connection observations. Connection 1 is always the plain
# page_handler=false attempt; the rest are page_handler=true connections.
BLOCKED_BODY = "<html><body>Access denied</body></html>"
OK_BODY = "<html><body><h1>Acme wireless mouse</h1></body></html>"

scenarios = []

# A. plain page is fine: nothing else should happen.
scenarios.append(("A plain ok ends on attempt 1", [
    {"status": 200, "headers": {}, "url": "https://shop.example.com/products/42", "body": OK_BODY,
     "state": None},
], lambda r, d, log: (
    r["verdict"] == ps.OK and r["attempt_count"] == 1 and r["challenged"] is False
    and r["attempts"][0]["page_handler"] is False and r["session_id"] == "sess-1"
    and r["last_page_status"] is None and d == []
)))

# B. blocked plain attempt -> handler connection handles a challenge -> challenged.
scenarios.append(("B blocked plain attempt, then a handled challenge", [
    {"status": 403, "headers": {}, "url": "https://shop.example.com/products/42", "body": BLOCKED_BODY,
     "state": None},
    {"status": 200, "headers": {}, "url": "https://shop.example.com/products/42", "body": OK_BODY,
     "state": {"status": "open", "error": None, "challenged": True, "sawClosed": True}},
], lambda r, d, log: (
    r["verdict"] == ps.CHALLENGED and r["attempt_count"] == 2 and r["challenged"] is True
    and [a["page_handler"] for a in r["attempts"]] == [False, True]
    and r["attempts"][1]["terminal_status"] == "open" and r["attempts"][1]["session_id"] == "sess-2"
    and all(a["started_at"] and a["ended_at"] for a in r["attempts"])
)))

# C. blocked three identities in a row: 10 s then 20 s backoff, max 2 retries, then stop.
scenarios.append(("C blocked: 10s/20s backoff, two fresh identities, then stop", [
    {"status": 403, "headers": {}, "url": "https://shop.example.com/products/42", "body": BLOCKED_BODY,
     "state": None},
    {"status": 403, "headers": {}, "url": "https://shop.example.com/products/42", "body": BLOCKED_BODY,
     "state": {"status": "failed", "error": "bad_token", "challenged": True}},
    {"status": 200, "headers": {}, "url": "https://shop.example.com/blocked",
     "body": "<html>Verify you are human</html>",
     "state": {"status": "open", "error": None, "challenged": False}},
    {"status": 503, "headers": {}, "url": "https://shop.example.com/blocked", "body": BLOCKED_BODY,
     "state": {"status": "open", "error": None, "challenged": False}},
], lambda r, d, log: (
    r["verdict"] == ps.BLOCKED and r["attempt_count"] == 4 and d == [10, 20]
    and [a["page_handler"] for a in r["attempts"]] == [False, True, True, True]
    and r["last_page_status"] == "open" and "stop" in r["stopped_reason"]
    and r["attempts"][1]["page_error"] == "bad_token"
)))

# D. sign-in wall on the handler connection: stop immediately, no backoff.
scenarios.append(("D not-public stops without retry or backoff", [
    {"status": 403, "headers": {}, "url": "https://shop.example.com/products/42", "body": BLOCKED_BODY,
     "state": None},
    {"status": 200, "headers": {}, "url": "https://account.example.com/login?next=/products/42",
     "body": "<html>sign in</html>",
     "state": {"status": "open", "error": None, "challenged": False}},
], lambda r, d, log: (
    r["verdict"] == ps.NOT_PUBLIC and r["attempt_count"] == 2 and d == []
    and "not public" in r["stopped_reason"]
)))

# E. Oxylabs network error on the handler connection: network retry, then ok.
scenarios.append(("E oxylabs-network retried as a network error, then ok", [
    {"status": 403, "headers": {}, "url": "https://shop.example.com/products/42", "body": BLOCKED_BODY,
     "state": None},
    {"status": 502, "headers": {"X-Error-Description": "upstream timeout"},
     "url": "https://shop.example.com/products/42", "body": "Bad Gateway",
     "state": None},
    {"status": 200, "headers": {}, "url": "https://shop.example.com/products/42", "body": OK_BODY,
     "state": {"status": "open", "error": None, "challenged": False}},
], lambda r, d, log: (
    r["verdict"] == ps.OK and r["attempt_count"] == 3 and d == [10]
    and r["attempts"][1]["verdict"] == ps.OXYLABS_NETWORK
)))

# F. an error string carrying the connection URL must never leak the password.
secret_url = f"WebSocket error: wss://demo-user:{os.environ['OXY_AB_PASSWORD']}@hb.oxylabs.io/ 503"
scenarios.append(("F password-bearing errors are redacted everywhere", [
    {"status": 200, "headers": {}, "url": "https://shop.example.com/products/42", "body": OK_BODY,
     "state": None, "goto_error": RuntimeError(secret_url)},
    {"status": 200, "headers": {}, "url": "https://shop.example.com/products/42", "body": OK_BODY,
     "state": {"status": "open", "error": None, "challenged": False}},
], lambda r, d, log: (
    os.environ["OXY_AB_PASSWORD"] not in log
    and os.environ["OXY_AB_PASSWORD"] not in str(r)
    and "***" in log and r["attempts"][0]["verdict"] == ps.OXYLABS_NETWORK
)))


def main():
    failures = 0
    for name, outcomes, check in scenarios:
        result, delays, log = run_scenario(name, outcomes)
        try:
            held = check(result, delays, log)
        except Exception as err:  # noqa: BLE001
            held = False
            log = f"{log}\ncheck raised: {err!r}"
        print(f"[{'PASS' if held else 'FAIL'}] {name}")
        print(f"        verdict={result['verdict']} attempts={result['attempt_count']} "
              f"backoff={delays} challenged={result['challenged']}")
        if not held:
            failures += 1
            print("        record:", result)
    print()
    if failures:
        print(f"{failures} scenario(s) failed")
        sys.exit(1)
    print(f"all {len(scenarios)} flow scenarios passed; no browser was launched and no network was used")


if __name__ == "__main__":
    main()
