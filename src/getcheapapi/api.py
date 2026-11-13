"""Library entry for scripts: the same guards as `getcheapapi call`, one call at a time, or one per keyword.

call() prices on fresh prices, refuses past max_usd, pins AnyAPI to its cheapest source, and writes the ledger
line, so spend made from a script shows up in `getcheapapi spend`. batch_call() applies that same protection
to each keyword on its own and reports every keyword's outcome instead of stopping the whole list on the first
trouble.

Stop is the base of what it raises: Refused means nothing was spent, NotServed means this call failed
without a charge and a batch may go on (Unavailable, a NotServed, says the source is down for now; wait=N
keeps trying it for N seconds); any other Stop (out of balance, served by an unexpected source) ends the batch.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from getcheapapi import lanes as L
from getcheapapi.core import EXIT_NO_BALANCE, DROPPED, NotServed, Refused, Stop, Unavailable, load_env, now, record
from getcheapapi.providers import PROVIDERS, AnyAPI, Provider

__all__ = ["DEFAULT_MAX_USD", "NotServed", "Refused", "Stop", "Unavailable", "batch_call", "call", "quote"]

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


def batch_call(provider: str, endpoint: str, keywords: list[str], *, body_for=None,
               max_usd: float = DEFAULT_MAX_USD, max_ratio: float = L.DEFAULT_MAX_RATIO,
               project: str | None = None, retries: int = 0, wait: float = 0) -> dict:
    """Collect one keyword per call, each call guarded and ledgered exactly as call() does.

    Every keyword goes through call(): its own prepare/estimate on fresh prices (AnyAPI still pinned to its
    cheap source), its own max_usd check, its own wait, and its own ledger line when it is sent. One keyword
    past the cap is refused on its own without a call, and the rest still run. A failure that concerns only
    that call (invalid input, an unavailable source, a price that needs a person, a charged response that
    failed) is reported for that keyword and the batch goes on. Only running out of balance (exit code 2)
    stops the batch: the keyword that hit it and everything after it are marked failed or not_run, and the
    keywords already done keep their results and costs.

    body_for turns one keyword into that call's body; the default {"keyword": keyword} fits endpoints such as
    goanyapi keyword-search-volume. Returns, for every submitted keyword in order:

        {"keyword": str, "status": "success" | "refused" | "failed" | "not_run",
         "charged": bool, "costUsd": float, "error": str | None, "result": the raw response when succeeded}

    plus the counts "success", "failed", "refused" and "not_run", "totalUsd", and "stoppedForBalance".
    """
    load_env()
    if isinstance(keywords, str) or not isinstance(keywords, (list, tuple)) or not all(
            isinstance(term, str) and term.strip() for term in keywords):
        raise Stop("batch_call: keywords must be a list of non-empty strings")
    make_body = body_for or (lambda term: {"keyword": term})
    project = project or Path.cwd().name
    items: list[dict] = []
    stopped = False
    for term in keywords:
        item = {"keyword": term, "status": "not_run", "charged": False, "costUsd": 0.0,
                "error": None, "result": None}
        items.append(item)
        if stopped:
            continue
        try:
            body = make_body(term)
            if not isinstance(body, dict):
                raise Stop("batch_call: body_for must return a JSON object")
            result, cost = call(provider, endpoint, body, max_usd=max_usd, max_ratio=max_ratio,
                                project=project, retries=retries, wait=wait)
        except Refused as exc:  # nothing was sent: over the cap, or a price a person must accept first
            item.update(status="refused", charged=exc.cost > 0, costUsd=round(exc.cost, 6), error=str(exc)[:300])
            stopped = exc.code == EXIT_NO_BALANCE
            continue
        except Stop as exc:  # this call failed; the charge it may have taken is kept with this keyword
            item.update(status="failed", charged=exc.cost > 0, costUsd=round(exc.cost, 6), error=str(exc)[:300])
            stopped = exc.code == EXIT_NO_BALANCE
            continue
        item.update(status="success", charged=cost > 0, costUsd=round(cost, 6), result=result)
    if stopped:
        for item in items:
            if item["status"] == "not_run":
                item["error"] = f"not run: the batch stopped earlier, out of balance (exit code {EXIT_NO_BALANCE})"
    counts = {status: sum(1 for item in items if item["status"] == status)
              for status in ("success", "failed", "refused", "not_run")}
    return {"provider": provider, "endpoint": endpoint, "items": items, **counts,
            "totalUsd": round(sum(item["costUsd"] for item in items), 6), "stoppedForBalance": stopped}
