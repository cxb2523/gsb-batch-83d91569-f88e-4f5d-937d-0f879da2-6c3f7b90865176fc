"""Client-side supervisor for ``Browser.agentFetch`` / ``Browser.agentFetchCancel``.

This module is the protocol-layer companion to the browser's tab-less fetch
(see ``CDP.md``, "Browser domain"). It speaks plain CDP JSON over any
transport with ``send(command: dict)`` and ``recv() -> list[dict]`` — a
WebSocket adapter in production, a preset fake in tests — and adds the
collection guarantees a caller needs around the raw commands:

* **Stable identity.** Every fetch carries a ``fetchId``. The caller may
  choose one; otherwise the client assigns one (``fetch-<n>``) before the
  command is sent, so the id is known even before the browser replies.
* **Termination reason and elapsed time.** Each fetch ends in exactly one
  :class:`FetchResult` with ``reason`` = ``completed`` / ``cancelled`` /
  ``timeout`` and ``elapsed_ms`` measured by the client's clock.
* **Cancellable.** :meth:`AgentFetchClient.cancel` issues
  ``Browser.agentFetchCancel``. A body that arrives after cancellation is
  discarded — a cancelled fetch never produces content. Cancelling the same
  id twice is idempotent (the recorded result is returned, no second command
  is sent); cancelling an unknown id raises :class:`UnknownFetchIdError`.
* **Verifiable.** A completed result exposes ``final_url`` (after redirects),
  ``status``, ``markdown_chars``, and the explicit flags ``truncated`` and
  ``render_failed``.
* **Real timeout.** The timeout (``timeout_ms`` per call, default 30000 as
  in the browser) is enforced by :meth:`AgentFetchClient.tick`: when the
  deadline passes, the client sends ``Browser.agentFetchCancel`` so the
  browser tears the hidden page down — it does not merely stop waiting
  locally while the fetch keeps running in the background.

The client is synchronous and poll-driven: the caller (or an event-loop
adapter) pumps it with :meth:`poll` when the transport has data and with
:meth:`tick` periodically (or at least before awaiting results).
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# Termination reasons.
REASON_COMPLETED = "completed"
REASON_CANCELLED = "cancelled"
REASON_TIMEOUT = "timeout"

# Matches the browser's own default for Browser.agentFetch (CDP.md).
DEFAULT_TIMEOUT_MS = 30_000


class UnknownFetchIdError(KeyError):
    """Raised when cancelling a fetch id this client has never seen.

    Cancelling an id that does not exist is an explicit error, never a
    silent success.
    """

    def __init__(self, fetch_id: str):
        super().__init__(fetch_id)
        self.fetch_id = fetch_id

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"no agentFetch with fetchId {self.fetch_id!r}"


@dataclass
class FetchResult:
    """The single terminal record of a fetch.

    ``response`` is the browser's raw ``Browser.agentFetch`` reply. It is
    ``None`` when the fetch ended by cancellation or client-side timeout
    before a reply was consumed: a cancelled or timed-out fetch never
    surfaces body content.
    """

    fetch_id: str
    reason: str  # REASON_COMPLETED | REASON_CANCELLED | REASON_TIMEOUT
    elapsed_ms: int
    outcome: Optional[str] = None  # raw browser outcome, when a reply came
    error: Optional[str] = None
    final_url: Optional[str] = None
    status: Optional[int] = None
    markdown_chars: int = 0
    truncated: bool = False
    render_failed: bool = False
    response: Optional[Dict[str, Any]] = None


@dataclass
class _Job:
    fetch_id: str
    command_id: int
    started_at: float
    timeout_ms: int
    done: bool = False
    result: Optional[FetchResult] = None

    @property
    def deadline_at(self) -> float:
        return self.started_at + self.timeout_ms / 1000.0


class AgentFetchClient:
    """Drives ``Browser.agentFetch`` calls over a CDP transport.

    ``transport`` must provide ``send(command: dict)`` (a CDP command with
    ``id``/``method``/``params``) and ``recv() -> list[dict]`` (CDP responses
    available now, each with an ``id`` and a ``result`` or ``error``).
    ``clock`` is a monotonic seconds source, injectable for tests.
    """

    def __init__(
        self,
        transport: Any,
        clock: Callable[[], float] = time.monotonic,
        default_timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ):
        if default_timeout_ms <= 0:
            raise ValueError("default_timeout_ms must be positive")
        self._transport = transport
        self._clock = clock
        self._default_timeout_ms = default_timeout_ms
        self._command_ids = itertools.count(1)
        self._fetch_seq = itertools.count(1)
        self._jobs: Dict[str, _Job] = {}
        self._by_command: Dict[int, str] = {}  # command id -> fetch id

    # -- issuing ---------------------------------------------------------

    def start_fetch(
        self,
        url: str,
        *,
        fetch_id: Optional[str] = None,
        timeout_ms: Optional[int] = None,
        **params: Any,
    ) -> str:
        """Start a fetch of ``url`` and return its stable fetch id.

        ``timeout_ms`` defaults to the browser's own default (30000). Any
        other ``Browser.agentFetch`` parameter (``mode``, ``method``,
        ``headers``, ``body``, ``settleMs``, ``links``, ...) passes through.
        """
        if fetch_id is None:
            fetch_id = f"fetch-{next(self._fetch_seq)}"
        if fetch_id in self._jobs:
            raise ValueError(f"fetchId {fetch_id!r} is already in use")
        if timeout_ms is None:
            timeout_ms = self._default_timeout_ms
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")

        command_id = next(self._command_ids)
        self._transport.send(
            {
                "id": command_id,
                "method": "Browser.agentFetch",
                "params": {"url": url, "fetchId": fetch_id, "timeoutMs": timeout_ms, **params},
            }
        )
        self._jobs[fetch_id] = _Job(
            fetch_id=fetch_id,
            command_id=command_id,
            started_at=self._clock(),
            timeout_ms=timeout_ms,
        )
        self._by_command[command_id] = fetch_id
        return fetch_id

    # -- cancelling ------------------------------------------------------

    def cancel(self, fetch_id: str) -> FetchResult:
        """Cancel ``fetch_id``; idempotent for ids this client knows.

        The first call sends ``Browser.agentFetchCancel`` (which makes the
        browser destroy the hidden page) and records the terminal result;
        later calls for the same id return that recorded result without
        sending anything. An id this client never started raises
        :class:`UnknownFetchIdError`.
        """
        job = self._jobs.get(fetch_id)
        if job is None:
            raise UnknownFetchIdError(fetch_id)
        if job.done:
            return job.result
        self._transport.send(
            {
                "id": next(self._command_ids),
                "method": "Browser.agentFetchCancel",
                "params": {"fetchId": fetch_id},
            }
        )
        return self._finish(job, REASON_CANCELLED, outcome="cancelled")

    # -- pumping ---------------------------------------------------------

    def poll(self) -> List[FetchResult]:
        """Consume available transport responses.

        Returns the results of fetches that finished with this batch. A
        reply for a fetch that already ended (cancelled or timed out) is
        dropped: its body is never surfaced.
        """
        finished: List[FetchResult] = []
        for message in self._transport.recv():
            fetch_id = self._by_command.get(message.get("id"))
            if fetch_id is None:
                continue  # a cancel reply, or not ours
            job = self._jobs[fetch_id]
            if job.done:
                continue  # late reply after cancel/timeout: discard the body
            if "error" in message:
                error = message["error"]
                text = (
                    error.get("message", str(error))
                    if isinstance(error, dict)
                    else str(error)
                )
                finished.append(
                    self._finish(
                        job,
                        REASON_COMPLETED,
                        outcome="error",
                        error=text,
                        render_failed=True,
                    )
                )
            else:
                finished.append(self._finish_from_reply(job, message.get("result") or {}))
        return finished

    def tick(self) -> List[FetchResult]:
        """Enforce timeouts; returns the results of fetches that timed out.

        A fetch past its deadline is cancelled at the browser with
        ``Browser.agentFetchCancel`` — the call that releases the hidden
        page — so the wait truly stops instead of only being abandoned
        locally.
        """
        now = self._clock()
        finished: List[FetchResult] = []
        for job in list(self._jobs.values()):
            if job.done or now < job.deadline_at:
                continue
            self._transport.send(
                {
                    "id": next(self._command_ids),
                    "method": "Browser.agentFetchCancel",
                    "params": {"fetchId": job.fetch_id},
                }
            )
            finished.append(self._finish(job, REASON_TIMEOUT, outcome="timeout"))
        return finished

    # -- inspecting ------------------------------------------------------

    def result(self, fetch_id: str) -> Optional[FetchResult]:
        """The terminal result for ``fetch_id``, or ``None`` while running."""
        job = self._jobs.get(fetch_id)
        return job.result if job and job.done else None

    def forget(self, fetch_id: str) -> None:
        """Drop a finished fetch's record. The id becomes unknown again, so
        a later :meth:`cancel` of it raises :class:`UnknownFetchIdError`."""
        job = self._jobs.get(fetch_id)
        if job is not None and job.done:
            self._by_command.pop(job.command_id, None)
            del self._jobs[fetch_id]

    # -- internals -------------------------------------------------------

    def _finish(self, job: _Job, reason: str, **fields: Any) -> FetchResult:
        result = FetchResult(
            fetch_id=job.fetch_id,
            reason=reason,
            elapsed_ms=self._elapsed_ms(job),
            **fields,
        )
        job.done = True
        job.result = result
        return result

    def _finish_from_reply(self, job: _Job, reply: Dict[str, Any]) -> FetchResult:
        outcome = reply.get("outcome")
        if outcome == "cancelled":
            reason = REASON_CANCELLED
        elif outcome == "timeout":
            reason = REASON_TIMEOUT
        else:
            reason = REASON_COMPLETED
        markdown = reply.get("markdown") or ""
        render_failed = outcome == "error" or (
            reply.get("kind") == "html" and not markdown
        )
        return self._finish(
            job,
            reason,
            outcome=outcome,
            error=reply.get("error"),
            final_url=reply.get("finalUrl"),
            status=reply.get("status"),
            markdown_chars=len(markdown),
            truncated=bool(reply.get("truncated", False)),
            render_failed=render_failed,
            response=reply,
        )

    def _elapsed_ms(self, job: _Job) -> int:
        return int(round((self._clock() - job.started_at) * 1000))
