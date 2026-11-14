#!/usr/bin/env python3
"""Pre-fetch declared data sources for a chart script into a local cache.

check_chart.py runs this before executing a chart script, so a fetch failure
is reported as a fetch failure instead of surfacing as an opaque script
exception that is indistinguishable from a broken chart.

Manifest (JSON, e.g. `my_chart.sources.json` next to `my_chart.py`):

    {
      "sources": [
        {"name": "population", "url": "https://example.gov/pop.csv",
         "required": true,  "format": "csv"},
        {"name": "notes",      "url": "https://example.com/notes.txt",
         "required": false}
      ]
    }

Each item: `name` (label used in the report and the paths map), `url`
(http(s)://, file://, or a plain local path), `required` (default true),
`format` (optional: "json", "csv", or "text" — the fetched body is parsed to
catch corrupt or truncated downloads; omit to accept any non-empty body).

Outcomes per item: "ok" (fetched, or "from_cache" when a previous run's file
is reused without a new request), "http_error" (detail carries the status
code), "timeout", "connection_error", "empty", "parse_error". Fetches time
out after `timeout` seconds and are retried up to `retries` extra times on
timeouts, connection errors, and HTTP 5xx; the outcome recorded is the final
one. Within one run the same URL is fetched once and later items reuse the
result ("deduped"). A required item that fails fails the whole collection;
an optional item that fails is only recorded.

The chart script reads the fetched files through two environment variables
the checker sets while it runs:

    EVIDENT_DATA_DIR    cache directory holding the fetched files
    EVIDENT_DATA_PATHS  JSON object mapping each source name to its local file

Only sources whose fetch succeeded appear in EVIDENT_DATA_PATHS.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "check-chart-fetch/1.0"
RETRYABLE_HTTP = frozenset({408, 429})  # plus any 5xx


def load_sources(path) -> list[dict]:
    """Read a sources manifest into a list of {name, url, required, format}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("sources", [])
    if not isinstance(data, list):
        raise ValueError("manifest must be a list or an object with a 'sources' list")
    items = []
    for i, it in enumerate(data):
        if not isinstance(it, dict) or not it.get("url"):
            raise ValueError(f"sources[{i}] needs at least a 'url'")
        items.append({
            "name": str(it.get("name") or f"source-{i}"),
            "url": str(it["url"]),
            "required": bool(it.get("required", True)),
            "format": it.get("format"),
        })
    return items


def _local_path(url: str):
    """Path for a file:// URL or a plain path, else None."""
    if url.startswith("file://"):
        p = urllib.parse.urlparse(url).path
        if len(p) >= 3 and p[0] == "/" and p[2] == ":":  # /C:/... on Windows
            p = p[1:]
        return Path(urllib.parse.unquote(p))
    if "://" not in url:
        return Path(url)
    return None


def _cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    local = _local_path(url)
    suffix = (local.suffix if local else Path(urllib.parse.urlparse(url).path).suffix)[:10]
    return cache_dir / f"{digest}{suffix or '.dat'}"


def _validate(content: bytes, fmt):
    """Raise ValueError if `content` does not parse as `fmt`."""
    text = content.decode("utf-8")  # UnicodeDecodeError is a ValueError
    if fmt == "json":
        json.loads(text)
    elif fmt == "csv":
        if not list(csv.reader(io.StringIO(text))):
            raise ValueError("no rows")
    # "text" and unknown formats: decodable non-empty UTF-8 is enough


def _fetch_bytes(url: str, timeout: float) -> bytes:
    local = _local_path(url)
    if local is not None:
        return local.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _is_timeout(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason).lower()


def fetch_item(item: dict, cache_dir: Path, timeout: float, retries: int) -> dict:
    """Fetch one source into the cache and return its report entry."""
    url = item["url"]
    path = _cache_path(cache_dir, url)
    result = {"name": item["name"], "url": url, "required": item["required"],
              "outcome": None, "detail": "", "elapsed_ms": 0.0, "path": None,
              "from_cache": False, "deduped": False, "attempts": 0}
    t0 = time.monotonic()
    if path.is_file() and path.stat().st_size > 0:
        result["from_cache"] = True
        try:
            _validate(path.read_bytes(), item["format"])
        except ValueError as e:
            result.update(outcome="parse_error", detail=f"cached file: {e}")
        else:
            result.update(outcome="ok", detail="from cache", path=str(path))
        result["elapsed_ms"] = (time.monotonic() - t0) * 1000
        return result

    for attempt in range(1, retries + 2):
        result["attempts"] = attempt
        try:
            content = _fetch_bytes(url, timeout)
        except urllib.error.HTTPError as e:
            result.update(outcome="http_error", detail=f"HTTP {e.code} {e.reason}")
            if e.code not in RETRYABLE_HTTP and e.code < 500:
                break  # 4xx (other than 408/429) will not change on a retry
        except (urllib.error.URLError, OSError) as e:
            kind = "timeout" if _is_timeout(e) else "connection_error"
            result.update(outcome=kind, detail=str(getattr(e, "reason", e)))
        else:
            if not content:
                result.update(outcome="empty", detail="server returned an empty body")
                break
            try:
                _validate(content, item["format"])
            except ValueError as e:
                result.update(outcome="parse_error", detail=str(e))
                break
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(content)
            tmp.replace(path)
            result.update(outcome="ok", detail=f"{len(content)} bytes", path=str(path))
            break
    result["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
    return result


def collect(sources: list[dict], cache_dir, timeout: float = 10.0, retries: int = 2) -> dict:
    """Fetch every source into `cache_dir` and summarize the run.

    Returns {"ok", "items", "failures", "paths", "cache_dir"}: ok is False
    when a required source failed; failures lists the required names that
    failed; paths maps each successfully fetched name to its local file.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    items, by_url, paths, failures = [], {}, {}, []
    for item in sources:
        if item["url"] in by_url:  # same URL twice in one run: fetch once
            entry = dict(by_url[item["url"]])
            entry.update(name=item["name"], required=item["required"], deduped=True, elapsed_ms=0.0)
        else:
            entry = fetch_item(item, cache_dir, timeout, retries)
            by_url[item["url"]] = entry
        items.append(entry)
        if entry["outcome"] == "ok":
            paths[entry["name"]] = entry["path"]
        elif entry["required"]:
            failures.append(entry["name"])
    return {"ok": not failures, "items": items, "failures": failures,
            "paths": paths, "cache_dir": str(cache_dir)}


def summary_lines(report: dict) -> list[str]:
    """Human-readable DATA lines, one per source plus a collection verdict."""
    lines = []
    for it in report["items"]:
        note = " (cache)" if it["from_cache"] else " (deduped)" if it["deduped"] else ""
        req = "" if it["required"] else " [optional]"
        if it["outcome"] == "ok":
            lines.append(f"DATA OK {it['name']}{req} | {it['url']} | {it['elapsed_ms']:.0f}ms{note} | {it['path']}")
        else:
            lines.append(f"DATA FAILED {it['name']}{req} | {it['url']} | {it['outcome']}: {it['detail']} | "
                         f"{it['elapsed_ms']:.0f}ms, {it['attempts']} attempt(s)")
    n_ok = sum(it["outcome"] == "ok" for it in report["items"])
    n_cache = sum(it["from_cache"] for it in report["items"])
    if report["ok"]:
        lines.append(f"DATA COLLECTION OK: {n_ok}/{len(report['items'])} source(s) ready "
                     f"({n_cache} from cache), cache dir {report['cache_dir']}")
    else:
        lines.append(f"DATA COLLECTION FAILED: required source(s) failed: {', '.join(report['failures'])}")
    return lines
