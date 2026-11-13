"""AutoThrottleMiddleware tests with a fake clock and locally built objects.

These tests never touch the network: requests and responses are constructed
in-process and the monotonic/wall clocks plus ``asyncio.sleep`` are replaced
with deterministic fakes so timing assertions are exact rather than flaky.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from silkworm import Engine, Request, Response, Spider
from silkworm._middlewares import autothrottle as autothrottle_mod
from silkworm._middlewares.autothrottle import (
    AutoThrottleMiddleware,
    ThrottleSlot,
)
from silkworm.middlewares import RetryMiddleware

_URL_A = "http://a.test/resource"
_URL_B = "http://b.test/resource"


@dataclass
class _FakeClock:
    """Deterministic stand-in for ``time.monotonic`` / ``time.time``.

    ``sleep`` advances the clock by the requested duration instead of really
    waiting, so serial-slot and backoff timing can be asserted exactly.
    """

    instant: float = 1000.0

    def monotonic(self) -> float:
        return self.instant

    def time(self) -> float:
        return self.instant

    async def sleep(self, delay: float) -> None:
        self.instant += delay


@dataclass
class _RecordingLogger:
    records: list[dict[str, object]] = field(default_factory=list)

    def debug(self, message: str, **context: object) -> None:
        self.records.append({"message": message, **context})

    def info(self, message: str, **context: object) -> None:
        pass

    def warning(self, message: str, **context: object) -> None:
        pass

    def error(self, message: str, **context: object) -> None:
        pass

    def exception(self, message: str, **context: object) -> None:
        pass

    def configure(self, **kwargs: object) -> None:
        pass

    def bind(self, **context: object) -> "_RecordingLogger":
        return self

    def complete(self) -> None:
        pass


def _response(
    request: Request,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> Response:
    return Response(
        url=request.url,
        status=status,
        headers=headers or {},
        body=b"",
        request=request,
    )


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(autothrottle_mod, "_MonotonicClock", clock.monotonic)
    monkeypatch.setattr(autothrottle_mod, "_WallClock", clock.time)
    monkeypatch.setattr(autothrottle_mod.asyncio, "sleep", clock.sleep)
    return clock


def _throttle(**kwargs: object) -> AutoThrottleMiddleware:
    throttle = AutoThrottleMiddleware(**kwargs)  # type: ignore[arg-type]
    throttle.logger = _RecordingLogger()
    return throttle


# -- construction validation ---------------------------------------------------------------


def test_invalid_construction_raises_value_error() -> None:
    with pytest.raises(ValueError, match="start_delay must be between"):
        AutoThrottleMiddleware(start_delay=10.0, min_delay=0.0, max_delay=5.0)
    with pytest.raises(ValueError, match="start_delay must be between"):
        AutoThrottleMiddleware(start_delay=-1.0, min_delay=0.0, max_delay=5.0)
    with pytest.raises(ValueError, match="min_delay must be non-negative"):
        AutoThrottleMiddleware(min_delay=-0.1)
    with pytest.raises(
        ValueError,
        match="max_delay must be greater than or equal to min_delay",
    ):
        AutoThrottleMiddleware(min_delay=10.0, max_delay=5.0)
    with pytest.raises(ValueError, match="target_concurrency must be positive"):
        AutoThrottleMiddleware(target_concurrency=0)
    with pytest.raises(ValueError, match="target_concurrency must be positive"):
        AutoThrottleMiddleware(target_concurrency=-2.0)


# -- public observability ------------------------------------------------------------------


def test_slot_for_reports_delay_and_next_release_on_monotonic_clock(
    fake_clock: _FakeClock,
) -> None:
    throttle = _throttle(start_delay=2.0, min_delay=0.5, max_delay=10.0)

    unseen = throttle.slot_for(_URL_A)
    assert isinstance(unseen, ThrottleSlot)
    assert unseen.host == "a.test"
    assert unseen.delay == 2.0
    assert unseen.next_request_at == 0.0

    request = asyncio.run(throttle.process_request(Request(url=_URL_A), Spider()))
    slot = throttle.slot_for(_URL_A)
    assert slot.delay == 2.0
    # Released at 1000.0; the next slot opens one delay later.
    assert slot.next_request_at == pytest.approx(1002.0)
    assert slot.next_request_at > fake_clock.monotonic()
    assert request.meta["_autothrottle_start"] == pytest.approx(1000.0)


# -- normal latency convergence -------------------------------------------------------------


async def test_delay_converges_toward_latency_over_target_concurrency(
    fake_clock: _FakeClock,
) -> None:
    throttle = _throttle(
        start_delay=1.0,
        min_delay=0.0,
        max_delay=60.0,
        target_concurrency=2.0,
    )
    spider = Spider()

    # A fast host (0.2 s latency, target 2 -> target delay 0.1) should have its
    # delay shrink toward latency / target_concurrency on success responses.
    delays: list[float] = []
    for _ in range(6):
        request = await throttle.process_request(Request(url=_URL_A), spider)
        fake_clock.instant += 0.2  # the fetch itself takes 0.2 s
        await throttle.process_response(_response(request, 200), spider)
        delays.append(throttle.delay_for(_URL_A))

    assert delays[0] == pytest.approx((1.0 + 0.1) / 2)
    assert delays == sorted(delays, reverse=True)  # monotonically decreasing
    assert delays[-1] == pytest.approx(0.1, abs=0.02)
    assert 0.0 <= delays[-1] <= 60.0


async def test_delay_grows_toward_a_slow_host(fake_clock: _FakeClock) -> None:
    throttle = _throttle(
        start_delay=0.5,
        min_delay=0.0,
        max_delay=60.0,
        target_concurrency=1.0,
    )
    spider = Spider()

    request = await throttle.process_request(Request(url=_URL_A), spider)
    fake_clock.instant += 4.0  # slow response
    await throttle.process_response(_response(request, 200), spider)

    # (0.5 + 4.0) / 2 == 2.25
    assert throttle.delay_for(_URL_A) == pytest.approx(2.25)


async def test_plain_error_responses_never_lower_the_delay(
    fake_clock: _FakeClock,
) -> None:
    throttle = _throttle(start_delay=2.0, min_delay=0.0, max_delay=60.0)
    spider = Spider()

    # A fast 500 (not in backoff_statuses) must not speed the host up.
    request = await throttle.process_request(Request(url=_URL_A), spider)
    fake_clock.instant += 0.01
    await throttle.process_response(_response(request, 500), spider)
    assert throttle.delay_for(_URL_A) == 2.0

    # A 404 behaves the same way.
    request = await throttle.process_request(Request(url=_URL_A), spider)
    fake_clock.instant += 0.01
    await throttle.process_response(_response(request, 404), spider)
    assert throttle.delay_for(_URL_A) == 2.0


# -- backoff: doubling, Retry-After, clamping ----------------------------------------------


async def test_backoff_status_doubles_delay_and_clamps_to_max(
    fake_clock: _FakeClock,
) -> None:
    throttle = _throttle(
        start_delay=1.0,
        min_delay=0.0,
        max_delay=8.0,
        backoff_statuses=(429, 503),
    )
    spider = Spider()

    request = await throttle.process_request(Request(url=_URL_A), spider)
    await throttle.process_response(_response(request, 429), spider)
    assert throttle.delay_for(_URL_A) == pytest.approx(2.0)

    request = await throttle.process_request(Request(url=_URL_A), spider)
    await throttle.process_response(_response(request, 503), spider)
    assert throttle.delay_for(_URL_A) == pytest.approx(4.0)

    for _ in range(3):
        request = await throttle.process_request(Request(url=_URL_A), spider)
        await throttle.process_response(_response(request, 429), spider)
    # 8 -> clamped at max_delay instead of growing to 16.
    assert throttle.delay_for(_URL_A) == 8.0


async def test_retry_after_seconds_doubles_and_is_truncated_by_max_delay(
    fake_clock: _FakeClock,
) -> None:
    throttle = _throttle(start_delay=1.0, min_delay=0.0, max_delay=8.0)
    spider = Spider()

    request = await throttle.process_request(Request(url=_URL_A), spider)
    release_time = fake_clock.monotonic()
    await throttle.process_response(
        _response(request, 429, headers={"retry-after": "30"}),
        spider,
    )

    # Delay doubled and clamped to the upper bound.
    assert throttle.delay_for(_URL_A) == pytest.approx(2.0)
    slot = throttle.slot_for(_URL_A)
    # Retry-After (30 s) is itself truncated to max_delay (8 s).
    assert slot.next_request_at == pytest.approx(release_time + 8.0)


async def test_retry_after_http_date_form_is_honoured(fake_clock: _FakeClock) -> None:
    throttle = _throttle(start_delay=1.0, min_delay=0.0, max_delay=60.0)
    spider = Spider()

    request = await throttle.process_request(Request(url=_URL_A), spider)
    release_time = fake_clock.monotonic()
    # An HTTP date five seconds past the current (fake) wall-clock instant.
    # The fake wall clock reads 1000.0, so epoch 1005.0 is that date.
    await throttle.process_response(
        _response(
            request,
            503,
            headers={"retry-after": "Thu, 01 Jan 1970 00:16:45 GMT"},
        ),
        spider,
    )
    slot = throttle.slot_for(_URL_A)
    assert slot.next_request_at == pytest.approx(release_time + 5.0)


async def test_retry_after_never_waits_less_than_min_delay(
    fake_clock: _FakeClock,
) -> None:
    throttle = _throttle(start_delay=2.0, min_delay=2.0, max_delay=10.0)
    spider = Spider()

    request = await throttle.process_request(Request(url=_URL_A), spider)
    release_time = fake_clock.monotonic()
    # A 1-second Retry-After is below min_delay; the slot must stay closed for
    # at least min_delay, and the earlier regular reservation must not win.
    await throttle.process_response(
        _response(request, 429, headers={"retry-after": "1"}),
        spider,
    )
    slot = throttle.slot_for(_URL_A)
    assert slot.next_request_at >= release_time + 2.0 - 1e-9
    # The header itself is clamped up to the min_delay floor.
    assert slot.next_request_at == pytest.approx(release_time + 2.0)
    # Doubling 2 stays inside the bounds.
    assert slot.delay == pytest.approx(4.0)


async def test_unparseable_retry_after_is_ignored(fake_clock: _FakeClock) -> None:
    throttle = _throttle(start_delay=1.0, min_delay=0.0, max_delay=60.0)
    spider = Spider()

    request = await throttle.process_request(Request(url=_URL_A), spider)
    release_time = fake_clock.monotonic()
    await throttle.process_response(
        _response(request, 429, headers={"retry-after": "not-a-date"}),
        spider,
    )
    # Delay still doubled; the slot simply follows the normal delay spacing.
    assert throttle.delay_for(_URL_A) == pytest.approx(2.0)
    slot = throttle.slot_for(_URL_A)
    assert slot.next_request_at == pytest.approx(release_time + 1.0)


# -- serial per-host waits, independent hosts ------------------------------------------------


async def test_requests_to_one_host_queue_serially(fake_clock: _FakeClock) -> None:
    throttle = _throttle(start_delay=2.0, min_delay=0.0, max_delay=10.0)
    spider = Spider()
    released: list[float] = []

    async def send(url: str) -> None:
        await throttle.process_request(Request(url=url), spider)
        released.append(fake_clock.monotonic())

    await asyncio.gather(
        send("http://a.test/1"),
        send("http://a.test/2"),
        send("http://a.test/3"),
    )

    assert released == [1000.0, 1002.0, 1004.0]
    slot = throttle.slot_for("http://a.test/")
    assert slot.next_request_at == pytest.approx(1006.0)


async def test_different_hosts_do_not_block_each_other(
    fake_clock: _FakeClock,
) -> None:
    throttle = _throttle(start_delay=10.0, min_delay=0.0, max_delay=60.0)
    spider = Spider()
    released: list[tuple[str, float]] = []

    async def send(url: str) -> None:
        await throttle.process_request(Request(url=url), spider)
        released.append((url, fake_clock.monotonic()))

    await asyncio.gather(
        send(_URL_B),  # different host: must go out immediately
        send("http://a.test/1"),
        send("http://a.test/2"),  # waits 10 s for host A's slot
    )

    a_times = sorted(t for url, t in released if "a.test" in url)
    b_time = next(t for url, t in released if "b.test" in url)
    assert a_times == [1000.0, 1010.0]
    assert b_time == 1000.0  # never waited on host A


# -- retry integration ----------------------------------------------------------------------


async def test_retry_requests_go_through_the_same_host_slot(
    fake_clock: _FakeClock,
) -> None:
    throttle = _throttle(start_delay=2.0, min_delay=0.0, max_delay=60.0)
    retry = RetryMiddleware(max_times=2, backoff_base=0.0)
    spider = Spider()
    releases: list[tuple[int, float]] = []

    # First attempt: released immediately and stamped by the throttle.
    request = await throttle.process_request(Request(url=_URL_A), spider)
    retry_raw = request.meta.get("retry_times", 0)
    attempt_0 = int(retry_raw) if isinstance(retry_raw, (int, float, str)) else 0
    releases.append((attempt_0, fake_clock.monotonic()))

    # A 429 doubles the delay (2 -> 4), then RetryMiddleware re-enqueues a
    # dont_filter request whose meta was copied from the original.
    response = _response(request, 429)
    await throttle.process_response(response, spider)
    retried = await retry.process_response(response, spider)
    assert isinstance(retried, Request)
    assert retried.dont_filter is True
    assert retried.meta["retry_times"] == 1

    # The retry still waits for host A's slot; its dont_filter flag and copied
    # meta cannot bypass the throttle. It also gets a fresh release stamp.
    retried = await throttle.process_request(retried, spider)
    releases.append((1, fake_clock.monotonic()))
    assert retried.meta["_autothrottle_start"] == pytest.approx(1002.0)
    assert releases == [(0, 1000.0), (1, 1002.0)]

    # Retry-After closes the slot even longer than the regular spacing: the
    # next attempt waits out the header instead of just the doubled delay.
    response = _response(retried, 503, headers={"retry-after": "20"})
    await throttle.process_response(response, spider)
    second_retry = await retry.process_response(response, spider)
    assert isinstance(second_retry, Request)
    second_retry = await throttle.process_request(second_retry, spider)
    # Released at 1002; Retry-After asks for 20 more seconds (slot at 1022),
    # while the doubled delay (2 -> 4 -> 8) spacing would only open at 1010.
    # Retry-After wins, so the retry waits for the host slot either way.
    assert fake_clock.monotonic() == pytest.approx(1022.0)
    assert second_retry.meta["retry_times"] == 2


async def test_retry_does_not_reuse_a_stale_release_stamp(
    fake_clock: _FakeClock,
) -> None:
    throttle = _throttle(start_delay=1.0, min_delay=0.0, max_delay=60.0)
    spider = Spider()

    request = await throttle.process_request(Request(url=_URL_A), spider)
    first_stamp = request.meta["_autothrottle_start"]
    fake_clock.instant += 3.0  # time passes before the retry is reprocessed

    retried = request.replace(dont_filter=True, meta={**request.meta})
    retried = await throttle.process_request(retried, spider)

    assert retried.meta["_autothrottle_start"] != first_stamp
    assert retried.meta["_autothrottle_start"] == pytest.approx(1003.0)


# -- debug log fields -----------------------------------------------------------------------


async def test_debug_log_keeps_existing_fields_when_delay_changes(
    fake_clock: _FakeClock,
) -> None:
    throttle = _throttle(start_delay=1.0, min_delay=0.0, max_delay=60.0)
    logger = _RecordingLogger()
    throttle.logger = logger
    spider = Spider()

    request = await throttle.process_request(Request(url=_URL_A), spider)
    await throttle.process_response(_response(request, 429), spider)

    adjustment_logs = [
        record
        for record in logger.records
        if record["message"] == "Adjusted host delay"
    ]
    assert len(adjustment_logs) == 1
    record = adjustment_logs[0]
    assert record["host"] == "a.test"
    assert record["status"] == 429
    assert record["delay"] == 2.0
    assert record["previous_delay"] == 1.0


async def test_no_debug_log_when_delay_is_unchanged(fake_clock: _FakeClock) -> None:
    throttle = _throttle(start_delay=2.0, min_delay=0.0, max_delay=60.0)
    logger = _RecordingLogger()
    throttle.logger = logger
    spider = Spider()

    request = await throttle.process_request(Request(url=_URL_A), spider)
    # A fast, non-backoff error cannot change the delay, so nothing is logged.
    await throttle.process_response(_response(request, 500), spider)

    assert logger.records == []


# -- end-to-end engine integration ----------------------------------------------------------


class _RecordingSpider(Spider):
    name = "recording"
    start_urls = ("http://a.test/",)

    def __init__(self) -> None:
        super().__init__()
        self.seen_statuses: list[int] = []

    async def parse(self, response: Response) -> None:
        self.seen_statuses.append(response.status)
        await self.emit({"status": response.status})


async def test_engine_retry_waits_in_the_host_slot_and_doubles_delay(
    fake_clock: _FakeClock,
) -> None:
    """A re-enqueued retry (dont_filter, copied meta) still passes the throttle.

    Uses the real engine with a stubbed HTTP client and the fake clock, so the
    whole pipeline (request mw -> fetch -> throttle response mw -> retry mw ->
    re-enqueue -> request mw again) is exercised with deterministic timing.
    """
    throttle = AutoThrottleMiddleware(
        start_delay=0.02,
        min_delay=0.0,
        max_delay=5.0,
    )
    retry = RetryMiddleware(max_times=2, backoff_base=0.0)
    spider = _RecordingSpider()
    engine = Engine(
        spider,
        concurrency=1,
        request_middlewares=[throttle],
        # Throttle must run before Retry so the 429 adjusts the slot first.
        response_middlewares=[throttle, retry],
    )

    statuses = [429, 429, 200]
    fetch_times: list[float] = []

    async def fetch(req: Request) -> Response:
        fetch_times.append(fake_clock.monotonic())
        return _response(req, status=statuses.pop(0))

    engine.http.fetch = fetch  # type: ignore[method-assign]
    result = await engine.run()

    assert spider.seen_statuses == [200]
    assert result.stats["retries"] == 2
    assert result.items_scraped == 1
    assert len(fetch_times) == 3  # original + two retries
    # Only the throttle's slot waits advance the fake clock, so the gaps are
    # exact: the first retry waits one start_delay, the second waits the
    # doubled delay. Retries cannot bypass the per-host slot.
    gaps = [fetch_times[i] - fetch_times[i - 1] for i in range(1, len(fetch_times))]
    assert gaps == pytest.approx([0.02, 0.04])
    # Two 429 responses doubled the start delay twice (0.02 -> 0.04 -> 0.08);
    # the final 200 only averages it down slightly.
    assert throttle.delay_for("http://a.test/") > 0.02
    slot = throttle.slot_for("http://a.test/")
    assert isinstance(slot, ThrottleSlot)
    assert slot.host == "a.test"
    assert 0.0 < slot.delay <= 5.0


async def test_engine_throttle_keeps_different_hosts_independent(
    fake_clock: _FakeClock,
) -> None:
    throttle = AutoThrottleMiddleware(
        start_delay=0.05,
        min_delay=0.0,
        max_delay=5.0,
    )

    class TwoHostSpider(Spider):
        name = "two-host"

        async def start_requests(self) -> None:
            await self.follow(Request(url="http://a.test/"))
            await self.follow(Request(url="http://b.test/"))

        async def parse(self, response: Response) -> None:
            await self.emit({"url": response.url})

    spider = TwoHostSpider()
    engine = Engine(
        spider,
        concurrency=4,
        request_middlewares=[throttle],
        response_middlewares=[throttle],
    )

    first_release: dict[str, float] = {}

    async def fetch(req: Request) -> Response:
        host = req.url.split("//", 1)[1].split("/", 1)[0]
        first_release.setdefault(host, fake_clock.monotonic())
        return _response(req, status=200)

    engine.http.fetch = fetch  # type: ignore[method-assign]
    result = await engine.run()

    assert result.items_scraped == 2
    # Both hosts are first-time requests (no slot wait), so neither advances
    # the fake clock: they release at the same instant regardless of real
    # scheduling, proving different hosts never block each other.
    hosts = sorted(first_release)
    assert hosts == ["a.test", "b.test"]
    assert first_release["a.test"] == first_release["b.test"]
