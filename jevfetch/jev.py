"""HTTP client for TypeSafe's System One model, Jev.

Responses are cached on disk under the SHA-1 of the request body (JEVFETCH_CACHE_DIR, default
~/.cache/jevfetch). The key includes the model name, so with the default alias "jev-latest" a cached
answer can predate a model update; pass a pinned model name for reproducible runs."""

import asyncio
import email.utils
import hashlib
import json
import os
import time
from pathlib import Path

import httpx

URL = "https://api.typesafe.ai/v1/systemone"
RETRY_STATUS = {429, 529}
MAX_ATTEMPTS = 6


class JevError(RuntimeError):
    """A Jev call that failed for a reason retries cannot fix: missing or invalid key, no credit, bad request."""


def cache_dir() -> Path:
    return Path(os.environ.get("JEVFETCH_CACHE_DIR", Path.home() / ".cache" / "jevfetch")) / "jev"


def _retry_after(value: str | None, attempt: int) -> float:
    if value:
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                return max(0.0, email.utils.parsedate_to_datetime(value).timestamp() - time.time())
            except (TypeError, ValueError):
                pass
    return float(2**attempt)


class Jev:
    """Counts requests and input tokens separately for fresh calls and cache hits."""

    def __init__(
        self,
        concurrency: int = 16,
        model: str = "jev-latest",
        use_cache: bool = True,
        api_key: str | None = None,
        timeout: float = 60,
    ):
        self._key = api_key or os.environ.get("TYPESAFE_API_KEY")
        self.model = model
        self.use_cache = use_cache
        self.sem = asyncio.Semaphore(concurrency)
        self.client = httpx.AsyncClient(timeout=timeout)
        self.cache = cache_dir()
        self.requests = self.cached = 0
        self.keys: set[str] = set()  # cache keys of every request made through this client
        self.input_tokens = self.cached_input_tokens = 0
        self.models: set[str] = set()

    async def ask(self, state, questions: dict) -> dict:
        body = {"state": state, "model": self.model, "questions": questions}
        key = hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path = self.cache / f"{key}.json"
        self.requests += 1
        self.keys.add(key)
        if self.use_cache and path.exists():
            data = json.loads(path.read_text())
            self.cached += 1
            self.cached_input_tokens += data["usage"]["input_tokens"]
        else:
            data = await self._post(body)
            self.input_tokens += data["usage"]["input_tokens"]
            if self.use_cache:
                self.cache.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(f".{os.getpid()}.tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False))
                os.replace(tmp, path)
        if data.get("model"):
            self.models.add(data["model"])
        return data["answers"]

    async def _post(self, body) -> dict:
        if not self._key:
            raise JevError("TYPESAFE_API_KEY is not set")
        headers = {"Authorization": f"Bearer {self._key}"}
        async with self.sem:
            last = ""
            for attempt in range(MAX_ATTEMPTS):
                try:
                    r = await self.client.post(URL, json=body, headers=headers)
                except httpx.TransportError as e:
                    last = f"{type(e).__name__}: {e}"
                    await asyncio.sleep(2**attempt)
                    continue
                if r.status_code in RETRY_STATUS or r.status_code >= 500:
                    last = f"{r.status_code}: {r.text[:200]}"
                    await asyncio.sleep(_retry_after(r.headers.get("retry-after"), attempt))
                    continue
                if r.status_code != 200:
                    raise JevError(f"{r.status_code}: {r.text[:500]}")
                return r.json()
            raise JevError(f"retries exhausted ({last})")

    async def aclose(self) -> None:
        await self.client.aclose()
