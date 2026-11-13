from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

from .._domains import url_host
from ..logging import Logger, get_logger
from ..request import Request
from ..response import Response

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..spiders import Spider

# Request meta key holding the monotonic time a request was released.
_START_META_KEY = "_autothrottle_start"

# A zero-argument callable returning a monotonically increasing clock reading.
# Module-level binding so tests (and alternative event loops) can replace it.
_MonotonicClock: Callable[[], float] = time.monotonic
# Wall-clock time, used only to translate absolute HTTP-date ``Retry-After``
# headers into a duration measured on the monotonic clock.
_WallClock: Callable[[], float] = time.time


@dataclass(slots=True)
class ThrottleSlot:
    """Current throttle state of one host, with monotonic-clock timestamps.

    Attributes:
        host: Host the slot belongs to.
        delay: Current spacing between requests in seconds.
        next_request_at: Monotonic time at which the next request to the host
            may be released; a value at or below the current clock means now.
    """

    host: str
    delay: float
    next_request_at: float


@dataclass(slots=True)
class _HostState:
    delay: float
    next_request_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class AutoThrottleMiddleware:
    """Space requests per host and adapt the spacing to the host's latency.

    Register the same instance as both a request and a response middleware::

        throttle = AutoThrottleMiddleware(start_delay=1.0, max_delay=30.0)
        run_spider(
            MySpider,
            request_middlewares=[throttle],
            response_middlewares=[throttle, RetryMiddleware(max_times=3)],
        )

    Requests to one host are released at least ``delay`` seconds apart, and the
    per-host wait is serial: concurrent requests to the same host queue behind
    one another while different hosts never block each other. Retry requests
    re-enqueued by :class:`~silkworm.middlewares.RetryMiddleware` go through
    the same request pipeline, so they wait in the host's slot like any other
    request regardless of ``dont_filter`` or copied meta. After each response
    the delay moves toward ``latency / target_concurrency`` (an average of the
    previous and new estimate), so slow hosts are crawled more gently and fast
    hosts more quickly. Throttling statuses (429/503 by default) double the
    delay and honour a ``Retry-After`` header; other error responses never
    lower it. The delay always stays within ``[min_delay, max_delay]``.

    When combined with :class:`~silkworm.middlewares.RetryMiddleware`, place
    this middleware first in ``response_middlewares`` so throttling responses
    adjust the slot before the retry request is enqueued.

    Args:
        start_delay: Initial per-host delay in seconds.
        min_delay: Lower bound for the delay.
        max_delay: Upper bound for the delay.
        target_concurrency: Average number of requests to keep in flight per
            host; higher values crawl faster.
        backoff_statuses: Statuses that signal the host is overloaded.
    """

    def __init__(
        self,
        *,
        start_delay: float = 1.0,
        min_delay: float = 0.0,
        max_delay: float = 60.0,
        target_concurrency: float = 1.0,
        backoff_statuses: Iterable[int] = (429, 503),
    ) -> None:
        if min_delay < 0:
            msg = "min_delay must be non-negative"
            raise ValueError(msg)
        if max_delay < min_delay:
            msg = "max_delay must be greater than or equal to min_delay"
            raise ValueError(msg)
        if not min_delay <= start_delay <= max_delay:
            msg = "start_delay must be between min_delay and max_delay"
            raise ValueError(msg)
        if target_concurrency <= 0:
            msg = "target_concurrency must be positive"
            raise ValueError(msg)
        self.start_delay: float = start_delay
        self.min_delay: float = min_delay
        self.max_delay: float = max_delay
        self.target_concurrency: float = target_concurrency
        self.backoff_statuses: frozenset[int] = frozenset(backoff_statuses)
        self._hosts: dict[str, _HostState] = {}
        self.logger: Logger = get_logger(component="AutoThrottleMiddleware")

    def delay_for(self, url: str) -> float:
        """Return the current delay for ``url``'s host (the start delay if unseen)."""
        state = self._hosts.get(url_host(url))
        return state.delay if state is not None else self.start_delay

    def slot_for(self, url: str) -> ThrottleSlot:
        """Return the host's current delay and next allowed release time.

        Both timestamps use the same monotonic clock as
        :meth:`process_request`, so the result is safe to compare against
        ``time.monotonic()`` in logs and tests. An unseen host reports the
        start delay and a release time of ``0.0`` (i.e. immediately).
        """
        host = url_host(url)
        state = self._hosts.get(host)
        if state is None:
            return ThrottleSlot(
                host=host,
                delay=self.start_delay,
                next_request_at=0.0,
            )
        return ThrottleSlot(
            host=host,
            delay=state.delay,
            next_request_at=state.next_request_at,
        )

    def _state(self, url: str) -> _HostState:
        host = url_host(url)
        state = self._hosts.get(host)
        if state is None:
            state = self._hosts[host] = _HostState(delay=self.start_delay)
        return state

    def _clamp(self, delay: float) -> float:
        return min(self.max_delay, max(self.min_delay, delay))

    async def process_request(self, request: Request, spider: Spider) -> Request:
        """Wait for the host's next slot, then release the request.

        The lock makes the wait serial per host: only one request at a time can
        reserve the host's next slot, while each host keeps its own lock.
        """
        state = self._state(request.url)
        async with state.lock:
            wait = state.next_request_at - _MonotonicClock()
            if wait > 0:
                await asyncio.sleep(wait)
            now = _MonotonicClock()
            state.next_request_at = now + state.delay
        # A fresh release stamp on every attempt, including retries, so the
        # latency is measured from this request's own release, never from a
        # stale stamp copied through a retry's meta.
        return request.replace(
            meta={**request.meta, _START_META_KEY: now},
        )

    async def process_response(
        self,
        response: Response,
        spider: Spider,
    ) -> Response | Request:
        """Adjust the host's delay from the response latency and status."""
        state = self._state(response.request.url)
        host = url_host(response.request.url)
        started = response.request.meta.get(_START_META_KEY)
        now = _MonotonicClock()
        previous = state.delay

        if response.status in self.backoff_statuses:
            # Overloaded host: back off exponentially, never below the current
            # delay and always inside the configured bounds.
            state.delay = self._clamp(max(state.delay * 2.0, self.min_delay))
            retry_after = self._retry_after(response)
            if retry_after is not None:
                # The host asked for room; keep the slot closed at least that
                # long, bounded by the same min/max window as the delay.
                wait = self._clamp(retry_after)
                state.next_request_at = max(state.next_request_at, now + wait)
            self._log_adjustment(host, response.status, state.delay, previous)
            return response

        if isinstance(started, (int, float)) and not isinstance(started, bool):
            latency = max(0.0, now - float(started))
            target = latency / self.target_concurrency
            new_delay = (state.delay + target) / 2
            # Error responses are often fast; never let them speed up crawling.
            if response.status < 400 or new_delay > state.delay:
                state.delay = self._clamp(new_delay)

        self._log_adjustment(host, response.status, state.delay, previous)
        return response

    def _log_adjustment(
        self,
        host: str,
        status: int,
        delay: float,
        previous: float,
    ) -> None:
        if delay == previous:
            return
        self.logger.debug(
            "Adjusted host delay",
            host=host,
            status=status,
            delay=round(delay, 3),
            previous_delay=round(previous, 3),
        )

    def _retry_after(self, response: Response) -> float | None:
        """Parse a ``Retry-After`` header into seconds to wait.

        Accepts both the delta-seconds form and the absolute HTTP-date form.
        Returns ``None`` when the header is absent or unparseable. The value is
        a duration, so it stays meaningful on the monotonic clock used for slot
        scheduling even though the HTTP-date form is read on the wall clock.
        """
        raw = response.headers.get("retry-after", "").strip()
        if not raw:
            return None
        if raw.isdigit():
            return max(0.0, float(raw))
        try:
            retry_at = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at is None:
            return None
        # RFC 9110 dates carry GMT timezone info; treat a naive value as UTC.
        retry_wall = (
            retry_at.timestamp()
            if retry_at.tzinfo is not None
            else retry_at.replace(tzinfo=timezone.utc).timestamp()
        )
        return max(0.0, retry_wall - _WallClock())
