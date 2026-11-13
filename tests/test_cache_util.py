"""
Tests for the TTL cache and rate limiter used by the web search tool.
"""
import time

from agent.tools.cache_util import TTLCache, RateLimiter


def test_cache_hit_and_miss():
    c = TTLCache(ttl=10)
    assert c.get("k") is None
    c.set("k", "v")
    assert c.get("k") == "v"


def test_cache_expires():
    c = TTLCache(ttl=0.05)
    c.set("k", "v")
    time.sleep(0.1)
    assert c.get("k") is None


def test_cache_allow_stale_returns_expired():
    c = TTLCache(ttl=0.05)
    c.set("k", "v")
    time.sleep(0.1)
    assert c.get("k") is None              # fresh miss
    c.set("k", "v2")
    time.sleep(0.1)
    assert c.get("k", allow_stale=True) == "v2"  # stale still available


def test_cache_evicts_when_full():
    c = TTLCache(ttl=100, max_entries=2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)  # triggers eviction
    # At most max_entries remain.
    remaining = [k for k in ("a", "b", "c") if c.get(k) is not None]
    assert len(remaining) <= 2


def test_stale_age_none_for_missing_and_fresh():
    c = TTLCache(ttl=10)
    assert c.stale_age_seconds("absent") is None
    c.set("k", "v")
    assert c.stale_age_seconds("k") is None  # still fresh


def test_stale_age_reports_expiry_seconds():
    c = TTLCache(ttl=0.05)
    c.set("k", "v")
    time.sleep(0.1)
    age = c.stale_age_seconds("k")
    assert age is not None
    assert age >= 0.05
    # The probe must be read-only: the expired entry stays available for a
    # subsequent allow_stale get and is not evicted.
    assert c.get("k", allow_stale=True) == "v"
    assert c.stale_age_seconds("k") is not None


def test_get_still_evicts_expired_entries():
    # Existing get() semantics are preserved: a plain get() on an expired
    # entry removes it and returns None.
    c = TTLCache(ttl=0.05)
    c.set("k", "v")
    time.sleep(0.1)
    assert c.get("k") is None
    assert c.stale_age_seconds("k") is None


def test_rate_limiter_allows_up_to_max():
    rl = RateLimiter(max_calls=3, period=60)
    assert rl.acquire() is True
    assert rl.acquire() is True
    assert rl.acquire() is True
    assert rl.acquire() is False  # 4th call blocked


def test_rate_limiter_time_until_next():
    rl = RateLimiter(max_calls=1, period=60)
    assert rl.acquire() is True
    assert rl.acquire() is False
    assert rl.time_until_next() > 0


def test_rate_limiter_window_slides():
    rl = RateLimiter(max_calls=1, period=0.05)
    assert rl.acquire() is True
    assert rl.acquire() is False
    time.sleep(0.1)
    assert rl.acquire() is True  # window expired, slot freed
