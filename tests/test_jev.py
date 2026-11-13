import httpx
import pytest

from jevfetch import jev as jev_mod
from jevfetch.jev import Jev, JevError, _retry_after

OK = {"answers": {"q": {"probability": 0.9}}, "usage": {"input_tokens": 42}, "model": "jev-x"}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def sleep(_):
        return None

    monkeypatch.setattr(jev_mod.asyncio, "sleep", sleep)


def client(tmp_path, monkeypatch, responses):
    monkeypatch.setenv("JEVFETCH_CACHE_DIR", str(tmp_path))
    seen = []

    def handler(request):
        seen.append(request)
        r = responses[min(len(seen) - 1, len(responses) - 1)]
        return r if isinstance(r, httpx.Response) else r(request)

    j = Jev(api_key="test-key")
    j.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return j, seen


async def test_retries_rate_limit_then_succeeds_and_caches(tmp_path, monkeypatch):
    j, seen = client(
        tmp_path,
        monkeypatch,
        [httpx.Response(429, headers={"retry-after": "1"}), httpx.Response(503), httpx.Response(200, json=OK)],
    )
    assert await j.ask("state", {"q": "x"}) == OK["answers"]
    assert len(seen) == 3 and j.input_tokens == 42 and j.models == {"jev-x"}
    assert await j.ask("state", {"q": "x"}) == OK["answers"]
    assert len(seen) == 3 and j.cached == 1 and j.cached_input_tokens == 42 and j.requests == 2
    await j.aclose()


async def test_client_error_is_not_retried(tmp_path, monkeypatch):
    j, seen = client(tmp_path, monkeypatch, [httpx.Response(402, text="billing_error")])
    with pytest.raises(JevError, match="402"):
        await j.ask("state", {"q": "x"})
    assert len(seen) == 1 and not list((tmp_path / "jev").glob("*.json"))
    await j.aclose()


async def test_transport_errors_exhaust_retries(tmp_path, monkeypatch):
    def fail(request):
        raise httpx.ConnectError("down", request=request)

    j, seen = client(tmp_path, monkeypatch, [fail])
    with pytest.raises(JevError, match="retries exhausted"):
        await j.ask("state", {"q": "x"})
    assert len(seen) == jev_mod.MAX_ATTEMPTS
    await j.aclose()


async def test_missing_key_raises_only_when_a_request_is_needed(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("JEVFETCH_CACHE_DIR", str(tmp_path))
    j = Jev()
    with pytest.raises(JevError, match="TYPESAFE_API_KEY"):
        await j.ask("state", {"q": "x"})
    await j.aclose()


async def test_cache_hit_needs_no_key(tmp_path, monkeypatch):
    j, seen = client(tmp_path, monkeypatch, [httpx.Response(200, json=OK)])
    await j.ask("state", {"q": "x"})
    await j.aclose()
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    offline = Jev()
    assert await offline.ask("state", {"q": "x"}) == OK["answers"] and offline.cached == 1
    await offline.aclose()
    assert len(offline.keys) == 1 and (offline.cache / f"{next(iter(offline.keys))}.json").exists()


def test_retry_after_parsing():
    assert _retry_after("3", 0) == 3.0
    assert _retry_after("Wed, 21 Oct 2015 07:28:00 GMT", 0) == 0.0
    assert _retry_after("garbage", 2) == 4.0
    assert _retry_after(None, 1) == 2.0
