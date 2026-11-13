"""Pin AnyAPI calls to the cheapest upstream source.

One AnyAPI SKU is served by several upstream sources whose prices differ by up to 200x, and by default a
failing cheap source fails over to a dearer one at the dearer price. pin() names one source, the cheapest,
and turns fallbacks off, so a dearer source never serves silently: when it cannot serve, AnyAPI refuses with
no charge and the caller waits for it or stops. Listing two is not safe: on 2026-11-06 a two-source list was
served by the dearer one, and an empty result reported as the cheap one was charged the dearer price. Only a
person raises max_ratio to let dearer sources in.

Lane prices are cached on disk (prices/anyapi.json). Comparing routes reads the cache; a paid run always
refetches the SKU it is about to call, so spending never relies on a stale price.

A local baseline keeps the lowest cheapest-price seen per SKU. When today's cheapest is more than
BASELINE_MAX_RISE times it (the cheap source left, or every source got dearer), pin() stops before any
spend until a person accepts the new price with accept_price().
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from getcheapapi.core import DROPPED, USER_AGENT, home, http, now, read_json, write_json

BASE = "https://api.getanyapi.com/v1"
DEFAULT_MAX_RATIO = 1.0
BASELINE_MAX_RISE = 1.5
ACCEPT_HINT = "getcheapapi accept-price {sku}"


class PricierOnly(Exception):
    """The cheapest source cannot serve this body; a person must accept the dearer price."""


class PriceRose(PricierOnly):
    """The cheapest source now costs well above the baseline; a person must accept the new price."""


def cache_path() -> Path:
    return home() / "prices" / "anyapi.json"


def baseline_path() -> Path:
    return home() / "price-baseline.json"


def fetch_lanes(sku: str, key: str, max_age: float = 0) -> list:
    """Lanes of one SKU; served from the disk cache when younger than max_age seconds."""
    cache = read_json(cache_path(), {})
    hit = cache.get(sku)
    if hit and max_age > 0 and time.time() - datetime.fromisoformat(hit["at"]).timestamp() < max_age:
        return hit["lanes"]
    for attempt in range(3):  # reading prices is free, and connections drop now and then
        try:
            info = http("GET", f"{BASE}/apis/{sku}", {"X-API-Key": key, "User-Agent": USER_AGENT}, timeout=60)
            break
        except DROPPED:
            if attempt == 2:
                raise
            time.sleep(2)
    lanes = info.get("lanes") or []
    cache = read_json(cache_path(), {})  # reread: another process may have written meanwhile
    cache[sku] = {"at": now(), "lanes": lanes}
    write_json(cache_path(), cache)
    return lanes


def lane_price(lane: dict, body: dict) -> float:
    p = lane.get("pricing") or {}
    if p.get("model") == "linear" and body.get("limit"):
        price = float(p.get("baseUsd") or 0) + float(p.get("perUnitUsd") or 0) * int(body["limit"])
        return min(price, float(p["maxUsd"])) if p.get("maxUsd") else price
    return float(p.get("maxUsd") or p.get("baseUsd") or 0)


def cheapest(lanes: list, body: dict) -> float:
    """Price of the cheapest lane that returns every requireFields field (inf when none)."""
    need = set(body.get("requireFields") or [])
    prices = [lane_price(l, body) for l in lanes if need <= set(l.get("fields") or need)]
    return min(prices, default=float("inf"))


def price_table(sku: str, body: dict, lanes: list) -> str:
    floor = min((lane_price(l, body) for l in lanes), default=0) or 1e-9
    need = set(body.get("requireFields") or [])
    rows = [f"{sku} sources (price per call, x cheapest, missing requireFields):"]
    for lane in sorted(lanes, key=lambda l: lane_price(l, body)):
        missing = sorted(need - set(lane.get("fields") or need))
        rows.append(f"  {lane['source']['id']:32} ${lane_price(lane, body):.5f}  x{lane_price(lane, body) / floor:.1f}"
                    + (f"  missing {missing}" if missing else ""))
    return "\n".join(rows)


def load_baseline(path: Path | None = None) -> dict:
    return read_json(path or baseline_path(), {})


def accept_price(sku: str, lanes: list, path: Path | None = None) -> tuple[float | None, float]:
    """Set the baseline to today's cheapest price; return (old, new)."""
    path = path or baseline_path()
    data = load_baseline(path)
    old = (data.get(sku) or {}).get("usd")
    new = min(lane_price(l, {}) for l in lanes)
    data[sku] = {"usd": new, "at": now()}
    write_json(path, data)
    return old, new


def check_baseline(sku: str, lanes: list, path: Path | None) -> None:
    """Record the first or a lower cheapest price; stop when it rose past BASELINE_MAX_RISE."""
    if path is None or not lanes:
        return
    floor = min(lane_price(l, {}) for l in lanes)
    seen = load_baseline(path).get(sku)
    if seen is None or floor < seen["usd"] - 1e-12:
        accept_price(sku, lanes, path)
    elif floor > seen["usd"] * BASELINE_MAX_RISE + 1e-12:
        raise PriceRose(f"{sku}: cheapest price rose from ${seen['usd']} (baseline {seen['at'][:10]}) to ${floor}, "
                        f"x{floor / seen['usd']:.1f}\n{price_table(sku, {}, lanes)}\n"
                        f"After the user accepts the new price: {ACCEPT_HINT.format(sku=sku)}")


def pin(sku: str, body: dict, lanes: list, max_ratio: float = DEFAULT_MAX_RATIO,
        baseline: Path | None | bool = True) -> tuple[dict, set, float]:
    """Return (body pinned to the cheap sources, allowed source ids, max price per call).

    baseline=True uses the default baseline file, None/False skips the baseline check.
    """
    if baseline is True:
        baseline = baseline_path()
    if body.get("source"):  # sources chosen explicitly: only those, unless the caller asked for fallbacks
        body = {"allowFallbacks": False, **body}
        chosen = lanes if body["allowFallbacks"] else [l for l in lanes if l["source"]["id"] in body["source"]]
        return body, {l["source"]["id"] for l in chosen}, max((lane_price(l, body) for l in chosen), default=0)
    if not lanes:
        raise PricierOnly(f"{sku}: the catalog lists no sources, so the price cannot be capped")
    check_baseline(sku, lanes, baseline or None)
    floor = min(lane_price(l, body) for l in lanes)
    need = set(body.get("requireFields") or [])
    ok = sorted((l for l in lanes if lane_price(l, body) <= floor * max_ratio + 1e-12
                 and need <= set(l.get("fields") or need)), key=lambda l: lane_price(l, body))
    if not ok:
        raise PricierOnly(f"no source within x{max_ratio} of the cheapest returns {sorted(need)}\n"
                          + price_table(sku, body, lanes)
                          + "\nAfter the user accepts a price, rerun with a higher --max-ratio or name the source.")
    if max_ratio <= 1:
        ok = ok[:1]
    ids = [l["source"]["id"] for l in ok]
    return {**body, "source": ids, "allowFallbacks": False}, set(ids), lane_price(ok[-1], body)


def served_ok(result: dict, allowed: set, max_usd: float) -> str | None:
    """None when an allowed source served within the price, else why not."""
    source = (result.get("source") or {}).get("id")
    cost = float(result.get("costUsd") or 0)
    if source not in allowed or cost > max_usd + 1e-9:
        return f"served by {source} at ${cost} (expected one of {sorted(allowed)} <= ${max_usd})"
    return None
