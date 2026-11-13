"""Shared plumbing: local state dir, .env loading, HTTP with 402 detection, the spend ledger."""
from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from getcheapapi import __version__

EXIT_NO_BALANCE = 2  # batch loops calling the CLI stop on it
EXIT_UNAVAILABLE = 3  # the cheapest source is down, nothing charged: wait and run the same command again
DROPPED = (OSError, http.client.HTTPException)  # connection lost, including mid-response
USER_AGENT = f"getcheapapi/{__version__}"


def home() -> Path:
    """Local state: price cache, price baseline, ledger, saved results. Never committed anywhere."""
    return Path(os.environ.get("GETCHEAPAPI_HOME") or Path.home() / ".getcheapapi")


class Stop(Exception):
    """Stop the run before (or right after) spending more; code 2 means out of balance."""

    def __init__(self, msg: str, code: int = 1, cost: float = 0.0):
        super().__init__(msg)
        self.code = code
        self.cost = cost  # charged before stopping, e.g. served by an unexpected source


class Refused(Stop):
    """Stopped before spending: the price needs a person, or the estimate passes the cap."""


class NotServed(Stop):
    """This one call failed and nothing was charged; a batch may go on to the next item."""


class Unavailable(NotServed):
    """The chosen source refused for now, with no charge: wait for it rather than pay another."""


KEY_SOURCES: dict[str, str] = {}  # variable -> .env file it was loaded from


def _load_file(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            KEY_SOURCES[key] = str(path)


def load_env() -> list[Path]:
    """Load KEY=VALUE lines from .env in the working dir and its parents, then ~/.getcheapapi/.env.

    GETCHEAPAPI_ENV_FILE (set in the environment or in any of those files) names one more .env to read,
    so keys kept elsewhere need no second copy. Existing environment variables win; nothing is printed.
    """
    candidates = [d / ".env" for d in (Path.cwd(), *Path.cwd().parents)] + [home() / ".env"]
    loaded: list[Path] = []
    for path in candidates:
        if path.is_file():
            _load_file(path)
            loaded.append(path)
    extra = os.environ.get("GETCHEAPAPI_ENV_FILE", "").strip()
    if extra:
        path = Path(extra).expanduser()
        if not path.is_file():
            raise Stop(f"GETCHEAPAPI_ENV_FILE points to a missing file: {path}")
        if path.resolve() not in {p.resolve() for p in loaded}:
            _load_file(path)
            loaded.append(path)
    return loaded


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise Stop(f"{name} is not configured; add it to .env (see .env.example) or ~/.getcheapapi/.env.")
    return value


def key_source(*names: str) -> str:
    """Where these variables came from (file paths or "environment"), never their values."""
    sources = dict.fromkeys(KEY_SOURCES.get(n, "environment") for n in names if os.environ.get(n, "").strip())
    return ", ".join(sources) or "not configured"


def has_env(*names: str) -> bool:
    return all(os.environ.get(n, "").strip() for n in names)


def http(method: str, url: str, headers: dict | None = None, body=None, timeout: int = 180) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:1500]
        raise Stop(f"HTTP {exc.code}: {detail}", EXIT_NO_BALANCE if exc.code == 402 else 1) from None


def list_len(data) -> int:
    """Rows in the first list field of a response payload."""
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return next((len(v) for v in data.values() if isinstance(v, list)), 0)
    return 0


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ledger_path() -> Path:
    return home() / "ledger.jsonl"


def record(row: dict) -> None:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
