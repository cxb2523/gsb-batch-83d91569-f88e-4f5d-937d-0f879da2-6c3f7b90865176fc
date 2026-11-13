"""Protocol-layer tests for the Browser.agentFetch supervisor.

Drives ``tools/agent_fetch_client.AgentFetchClient`` with a fake CDP
transport that answers by method name from preset responses — no browser is
started and no build output is needed. Covers five paths:

1. normal completion (verifiable result fields),
2. caller cancellation (no body afterwards),
3. client-side timeout (releases the hidden page),
4. duplicate cancellation (idempotent),
5. cancellation of an unknown id (explicit error).

Run from anywhere with a stock Python 3:

    python tests/test_agent_fetch_client.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.agent_fetch_client import (  # noqa: E402
    DEFAULT_TIMEOUT_MS,
    REASON_CANCELLED,
    REASON_COMPLETED,
    REASON_TIMEOUT,
    AgentFetchClient,
    UnknownFetchIdError,
)


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeCDPTransport:
    """A CDP transport that answers commands from per-method presets.

    A preset is either a result dict or a callable taking the command and
    returning a result dict (or ``None`` to leave the command unanswered,
    simulating a fetch that is still in flight). Every command sent is
    recorded in ``sent`` for assertions.
    """

    def __init__(self):
        self.sent = []
        self._presets = {}
        self._pending = []

    def preset(self, method, response):
        self._presets[method] = response

    # -- transport interface used by AgentFetchClient --

    def send(self, command):
        self.sent.append(dict(command))
        preset = self._presets.get(command["method"])
        if preset is None:
            return
        result = preset(command) if callable(preset) else preset
        if result is not None:
            self._pending.append({"id": command["id"], "result": result})

    def recv(self):
        out, self._pending = self._pending, []
        return out

    # -- assertions helpers --

    def sent_methods(self):
        return [c["method"] for c in self.sent]

    def sent_to(self, method):
        return [c for c in self.sent if c["method"] == method]


OK_REPLY = {
    "outcome": "ok",
    "status": 200,
    "finalUrl": "https://example.com/article",
    "redirects": [],
    "contentType": "text/html",
    "kind": "html",
    "title": "An article",
    "extractor": "readability",
    "markdown": "# An article\n\nFirst paragraph...",
    "outline": [{"level": 1, "text": "An article", "offset": 0}],
    "truncated": False,
    "timings": {"navigate": 12, "commit": 210, "settle": 900, "total": 925},
}


def make_client(**kwargs):
    transport = FakeCDPTransport()
    clock = FakeClock()
    client = AgentFetchClient(transport, clock=clock, **kwargs)
    return client, transport, clock


class TestAgentFetchClient(unittest.TestCase):
    # 1. Normal completion -------------------------------------------------

    def test_completes_normally_with_verifiable_result(self):
        client, transport, clock = make_client()
        transport.preset("Browser.agentFetch", OK_REPLY)

        fetch_id = client.start_fetch("https://example.com/article", links=True)
        self.assertTrue(fetch_id)  # a stable id exists even before the reply

        command = transport.sent_to("Browser.agentFetch")[0]
        self.assertEqual(command["params"]["fetchId"], fetch_id)
        self.assertEqual(command["params"]["timeoutMs"], DEFAULT_TIMEOUT_MS)
        self.assertEqual(command["params"]["url"], "https://example.com/article")
        self.assertTrue(command["params"]["links"])

        clock.advance(0.925)
        finished = client.poll()

        self.assertEqual([r.fetch_id for r in finished], [fetch_id])
        result = client.result(fetch_id)
        self.assertEqual(result.reason, REASON_COMPLETED)
        self.assertEqual(result.outcome, "ok")
        self.assertEqual(result.elapsed_ms, 925)
        self.assertEqual(result.final_url, "https://example.com/article")
        self.assertEqual(result.status, 200)
        self.assertEqual(
            result.markdown_chars, len(OK_REPLY["markdown"])
        )
        self.assertFalse(result.truncated)
        self.assertFalse(result.render_failed)
        self.assertIs(result.response, OK_REPLY)

    def test_truncated_and_render_failure_flags(self):
        client, transport, _ = make_client()
        transport.preset(
            "Browser.agentFetch",
            {
                "outcome": "ok",
                "status": 200,
                "finalUrl": "https://example.com/big",
                "kind": "html",
                "truncated": True,
                # no markdown: the page rendered but extraction failed
            },
        )
        fetch_id = client.start_fetch("https://example.com/big")
        client.poll()
        result = client.result(fetch_id)
        self.assertTrue(result.truncated)
        self.assertTrue(result.render_failed)
        self.assertEqual(result.markdown_chars, 0)

    def test_timeout_ms_parameter_is_passed_through(self):
        client, transport, _ = make_client()
        client.start_fetch("https://example.com/", timeout_ms=5000)
        self.assertEqual(
            transport.sent_to("Browser.agentFetch")[0]["params"]["timeoutMs"], 5000
        )

    # 2. Caller cancellation ----------------------------------------------

    def test_caller_cancel_suppresses_late_body(self):
        client, transport, clock = make_client()
        # The fetch's reply only becomes available after the cancel.
        transport.preset("Browser.agentFetch", lambda cmd: None)
        transport.preset("Browser.agentFetchCancel", {"cancelled": True})

        fetch_id = client.start_fetch("https://example.com/slow")
        clock.advance(1.2)
        result = client.cancel(fetch_id)

        self.assertEqual(result.reason, REASON_CANCELLED)
        self.assertEqual(result.elapsed_ms, 1200)
        self.assertIsNone(result.response)
        self.assertEqual(result.markdown_chars, 0)
        cancel_commands = transport.sent_to("Browser.agentFetchCancel")
        self.assertEqual(len(cancel_commands), 1)
        self.assertEqual(cancel_commands[0]["params"]["fetchId"], fetch_id)

        # The browser's reply arrives late, carrying a full body.
        fetch_command = transport.sent_to("Browser.agentFetch")[0]
        transport._pending.append({"id": fetch_command["id"], "result": OK_REPLY})
        finished = client.poll()

        self.assertEqual(finished, [])  # nothing new finished
        result = client.result(fetch_id)
        self.assertEqual(result.reason, REASON_CANCELLED)
        self.assertIsNone(result.response)  # the late body was discarded
        self.assertEqual(result.markdown_chars, 0)

    # 3. Timeout -----------------------------------------------------------

    def test_timeout_stops_wait_and_releases_hidden_page(self):
        client, transport, clock = make_client()
        transport.preset("Browser.agentFetch", lambda cmd: None)  # never answers
        transport.preset("Browser.agentFetchCancel", {"cancelled": True})

        fetch_id = client.start_fetch("https://example.com/stuck", timeout_ms=1000)

        clock.advance(0.5)
        self.assertEqual(client.tick(), [])  # not yet due
        self.assertNotIn("Browser.agentFetchCancel", transport.sent_methods())

        clock.advance(0.6)  # now past the 1000 ms deadline
        finished = client.tick()

        self.assertEqual([r.fetch_id for r in finished], [fetch_id])
        result = client.result(fetch_id)
        self.assertEqual(result.reason, REASON_TIMEOUT)
        self.assertEqual(result.elapsed_ms, 1100)
        self.assertIsNone(result.response)

        # The timeout really stopped the fetch: the browser was told to
        # cancel, which is the call that closes the hidden page.
        cancel_commands = transport.sent_to("Browser.agentFetchCancel")
        self.assertEqual(len(cancel_commands), 1)
        self.assertEqual(cancel_commands[0]["params"]["fetchId"], fetch_id)

        # A reply straggling in afterwards is discarded, body and all.
        fetch_command = transport.sent_to("Browser.agentFetch")[0]
        transport._pending.append({"id": fetch_command["id"], "result": OK_REPLY})
        self.assertEqual(client.poll(), [])
        self.assertIsNone(client.result(fetch_id).response)

    # 4. Duplicate cancellation -------------------------------------------

    def test_duplicate_cancel_is_idempotent(self):
        client, transport, _ = make_client()
        transport.preset("Browser.agentFetch", lambda cmd: None)
        transport.preset("Browser.agentFetchCancel", {"cancelled": True})

        fetch_id = client.start_fetch("https://example.com/slow")
        first = client.cancel(fetch_id)
        second = client.cancel(fetch_id)

        self.assertEqual(first, second)
        self.assertEqual(second.reason, REASON_CANCELLED)
        # Only one cancel command ever went out.
        self.assertEqual(len(transport.sent_to("Browser.agentFetchCancel")), 1)

    # 5. Unknown id ----------------------------------------------------------

    def test_cancel_unknown_id_is_an_explicit_error(self):
        client, transport, _ = make_client()
        with self.assertRaises(UnknownFetchIdError) as ctx:
            client.cancel("no-such-fetch")
        self.assertEqual(ctx.exception.fetch_id, "no-such-fetch")
        self.assertEqual(transport.sent, [])  # nothing was sent

        # A forgotten fetch is unknown again.
        transport.preset("Browser.agentFetch", OK_REPLY)
        fetch_id = client.start_fetch("https://example.com/article")
        client.poll()
        client.forget(fetch_id)
        with self.assertRaises(UnknownFetchIdError):
            client.cancel(fetch_id)


if __name__ == "__main__":
    unittest.main()
