"""
Tests for search_product's data-source contract (``source_kind``).

Every response must be verifiably tagged with one of:
fresh / stale_cache / rate_limited / error. These tests use a fake DDGS so
no real network calls are made.
"""
import json
import time

import pytest

from agent.tools import web_search as ws
from agent.tools.cache_util import TTLCache, RateLimiter


class _FakeDDGS:
    """In-process stand-in for ddgs.DDGS — records every instantiation."""
    instances = []
    payload = "products"

    def __init__(self, *args, **kwargs):
        type(self).instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def text(self, query, region=None, max_results=None):
        if type(self).payload == "empty":
            return []
        return [
            {
                "href": "https://tiki.vn/dien-thoai-iphone-16-p123456.html",
                "title": "iPhone 16 128GB - Tiki",
                "body": "Chinh hang, bao hanh 12 thang",
            },
            {
                "href": "https://shopee.vn/Apple-iPhone-16-i.88.999",
                "title": "Apple iPhone 16 | Shopee",
                "body": "Ban chinh hang gia tot",
            },
        ]


@pytest.fixture(autouse=True)
def _reset_search_state(monkeypatch):
    """Give every test isolated cache/limiter state and a fake DDGS."""
    monkeypatch.setattr(ws, "_search_cache", TTLCache(ttl=300, max_entries=256))
    monkeypatch.setattr(ws, "_rate_limiter", RateLimiter(max_calls=8, period=60))
    _FakeDDGS.instances.clear()
    _FakeDDGS.payload = "products"
    monkeypatch.setattr(ws, "DDGS", _FakeDDGS)
    yield


def _call(query="iPhone 16", max_results=10):
    return json.loads(ws.search_product(query, max_results=max_results))


# ── fresh fetch + write-through cache ──────────────────────────────────────

def test_fresh_fetch_keeps_existing_fields_and_writes_cache():
    data = _call()
    assert data["success"] is True
    assert data["source_kind"] == "fresh"
    assert data["total_results"] == 2
    assert set(data["sources_found"]) == {"Tiki", "Shopee"}
    assert len(data["results"]) == 2
    assert {r["source"] for r in data["results"]} == {"Tiki", "Shopee"}
    # The successful non-empty response was cached under the normalized key.
    assert ws._search_cache.get("iphone 16::10") is not None
    assert len(_FakeDDGS.instances) == 1


def test_cached_hit_does_not_call_ddgs_or_consume_rate_quota():
    first = _call()
    assert first["source_kind"] == "fresh"
    assert len(_FakeDDGS.instances) == 1

    # Limiter has 8 slots; the fresh fetch used one and the cache hit must
    # leave the remaining seven untouched.
    second = _call()
    assert second["success"] is True
    assert second["source_kind"] == "fresh"
    assert second["results"] == first["results"]
    assert len(_FakeDDGS.instances) == 1  # no second DDGS instantiation

    for _ in range(7):
        assert ws._rate_limiter.acquire() is True
    assert ws._rate_limiter.acquire() is False  # 1 fetch + 7 manual = 8 slots


# ── rate limited + stale cache fallback ────────────────────────────────────

def test_rate_limit_falls_back_to_stale_cache_with_age():
    short_cache = TTLCache(ttl=0.05)
    tight_limiter = RateLimiter(max_calls=1, period=60)
    ws._search_cache = short_cache
    ws._rate_limiter = tight_limiter

    fetched = _call()
    assert fetched["source_kind"] == "fresh"
    assert len(_FakeDDGS.instances) == 1

    # Let the cached entry expire. The fresh fetch already consumed the
    # limiter's single slot, so the next call is rate-limited immediately.
    time.sleep(0.1)
    assert short_cache.stale_age_seconds("iphone 16::10") is not None
    assert tight_limiter.acquire() is False

    data = _call()
    assert data["success"] is True
    assert data["source_kind"] == "stale_cache"
    # Old results are still served...
    assert data["total_results"] == 2
    assert len(data["results"]) == 2
    # ...and the expiry age is reported as a non-negative number.
    age = data["stale_age_seconds"]
    assert isinstance(age, (int, float)) and not isinstance(age, bool)
    assert age >= 0.05
    # Rate-limited path never reached DDGS.
    assert len(_FakeDDGS.instances) == 1


# ── rate limited, no cache ─────────────────────────────────────────────────

def test_rate_limited_without_cache_returns_rate_limited_kind():
    tight_limiter = RateLimiter(max_calls=1, period=60)
    ws._rate_limiter = tight_limiter
    assert tight_limiter.acquire() is True  # burn the only slot

    data = _call()
    assert data["success"] is False
    assert data["source_kind"] == "rate_limited"
    assert data["rate_limited"] is True
    assert data["results"] == []
    assert "qua nhanh" in data["message"]
    assert len(_FakeDDGS.instances) == 0  # blocked before any fetch


# ── fetch raises / fails ───────────────────────────────────────────────────

def test_exception_in_fetch_returns_error_kind(monkeypatch):
    def _boom(query, max_results=10):
        raise RuntimeError("ddgs exploded")

    monkeypatch.setattr(ws, "_do_search", _boom)

    data = _call("laptop x")
    assert data["success"] is False
    assert data["source_kind"] == "error"
    assert data["results"] == []
    assert "ddgs exploded" in data["message"]
    # Failures must not be cached.
    assert ws._search_cache.get("laptop x::10") is None


def test_failed_search_payload_is_tagged_error_and_not_cached(monkeypatch):
    # _do_search's own try/except returns a failure JSON instead of raising.
    failure = json.dumps({
        "success": False,
        "message": "Loi khi tim kiem: network down",
        "results": [],
    }, ensure_ascii=False)
    monkeypatch.setattr(ws, "_do_search", lambda q, m=10: failure)

    data = _call("laptop y")
    assert data["success"] is False
    assert data["source_kind"] == "error"
    assert data["results"] == []
    assert ws._search_cache.get("laptop y::10") is None


def test_empty_success_results_are_fresh_but_not_cached():
    _FakeDDGS.payload = "empty"

    data = _call("unknown gadget z")
    assert data["success"] is True
    assert data["source_kind"] == "fresh"
    assert data["total_results"] == 0
    assert data["results"] == []
    assert ws._search_cache.get("unknown gadget z::10") is None

    # Nothing was cached, so a second call performs a real fetch again.
    assert len(_FakeDDGS.instances) == 1
    _call("unknown gadget z")
    assert len(_FakeDDGS.instances) == 2


# ── input guard ────────────────────────────────────────────────────────────

def test_blank_query_is_error_kind():
    data = json.loads(ws.search_product("   "))
    assert data["success"] is False
    assert data["source_kind"] == "error"
    assert data["results"] == []
    assert len(_FakeDDGS.instances) == 0
