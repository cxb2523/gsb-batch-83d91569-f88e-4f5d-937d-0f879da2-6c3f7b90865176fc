"""Library entry for scripts: the same guards as `getcheapapi call`, one call at a time.

call() prices on fresh prices, refuses past max_usd, pins AnyAPI to its cheapest source, and writes the ledger
line, so spend made from a script shows up in `getcheapapi spend`.

Stop is the base of what it raises: Refused means nothing was spent, NotServed means this call failed
without a charge and a batch may go on (Unavailable, a NotServed, says the source is down for now; wait=N
keeps trying it for N seconds); any other Stop (out of balance, served by an unexpected source) ends the batch.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from getcheapapi import lanes as L
from getcheapapi.core import DROPPED, NotServed, Refused, Stop, Unavailable, load_env, now, record
from getcheapapi.providers import PROVIDERS, AnyAPI, Provider

__all__ = ["DEFAULT_MAX_USD", "NotServed", "Refused", "Stop", "Unavailable", "call", "quote"]

DEFAULT_MAX_USD = 0.1
FIRST_WAIT = 5  # seconds before trying an unavailable source again; doubles each time. Rate limits clear in seconds


def client_for(provider: str, max_ratio: float = L.DEFAULT_MAX_RATIO) -> Provider:
    return AnyAPI(max_ratio) if provider == "anyapi" else PROVIDERS[provider]()


def charged_call(client: Provider, endpoint: str, body: dict, project: str, extra: dict | None = None, retries: int = 0,
                 wait: float = 0):
    """One call, trying the same source again for up to wait seconds while it is unavailable. Nothing else is
    tried: a source that is down is waited for, never replaced."""
    waited, pause = 0.0, float(FIRST_WAIT)
    while True:
        try:
            return ledgered_call(client, endpoint, body, project, extra, retries)
        except Unavailable:
            if waited >= wait:
                raise
            pause = min(pause, wait - waited)
            print(f"{client.name} {endpoint}: unavailable, no charge; trying the same source again in {pause:.0f}s", file=sys.stderr)
            time.sleep(pause)
            waited += pause
            pause *= 2


def ledgered_call(client: Provider, endpoint: str, body: dict, project: str, extra: dict | None, retries: int):
    """client.call plus its ledger line. retries repeats a dropped connection, which may charge twice."""
    row = {"at": now(), "provider": client.name, "endpoint": endpoint, "project": project,
           "input": {k: v for k, v in body.items() if k not in ("source", "allowFallbacks")}, **(extra or {})}
    for attempt in range(retries + 1):
        try:
            result, cost, rows, ok = client.call(endpoint, body)
            break
        except Stop as exc:
            record({**row, "costUsd": round(exc.cost, 6), "error": str(exc)[:300]})
            raise
        except DROPPED as exc:
            if attempt == retries:
                record({**row, "costUsd": 0, "error": f"connection: {exc}"[:300]})
                raise NotServed(f"{client.name} {endpoint}: connection failed: {exc}") from None
    source = (result.get("source") or {}).get("id") if isinstance(result, dict) else None
    record({**row, "costUsd": round(cost, 6), "rows": rows, **({"source": source} if source else {}),
            **({} if ok else {"error": "call failed"})})
    return result, cost, rows, ok


def prepared(client: Provider, endpoint: str, body: dict) -> tuple[dict, float]:
    try:
        body = client.prepare(endpoint, body)
        return body, client.estimate(endpoint, body)
    except DROPPED as exc:
        raise Refused(f"{client.name} {endpoint}: could not read prices: {exc}") from None


def quote(provider: str, endpoint: str, body: dict, *, max_ratio: float = L.DEFAULT_MAX_RATIO) -> float:
    """USD upper bound for one call on fresh prices; spends nothing."""
    load_env()
    return prepared(client_for(provider, max_ratio), endpoint, body)[1]


def call(provider: str, endpoint: str, body: dict, *, max_usd: float = DEFAULT_MAX_USD,
         max_ratio: float = L.DEFAULT_MAX_RATIO, project: str | None = None, retries: int = 0,
         wait: float = 0) -> tuple[dict, float]:
    """One guarded, ledgered call. Returns (raw result, charged USD)."""
    load_env()
    client = client_for(provider, max_ratio)
    body, estimate = prepared(client, endpoint, body)
    if estimate > max_usd:
        raise Refused(f"{provider} {endpoint}: estimate ${estimate:.4f} exceeds the ${max_usd} cap")
    result, cost, _, ok = charged_call(client, endpoint, body, project or Path.cwd().name, retries=retries, wait=wait)
    if not ok:
        raise Stop(f"{provider} {endpoint}: call failed: {str(result)[:300]}", cost=cost)
    return result, cost
