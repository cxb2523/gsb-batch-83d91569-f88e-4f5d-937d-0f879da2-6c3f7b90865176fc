"""Fetching pages. Pages whose static HTML has almost no text are rendered with headless Chrome."""

import glob
import hashlib
import mimetypes
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

import httpx

try:
    _VERSION = version("jevfetch")
except PackageNotFoundError:
    _VERSION = "dev"
USER_AGENT = os.environ.get(
    "JEVFETCH_USER_AGENT", f"Mozilla/5.0 (compatible; jevfetch/{_VERSION}; +https://github.com/a2sys-ai/jevfetch)"
)
# Text types outside text/* and the +xml and +json suffixes, which _unsupported_kind accepts by pattern.
TEXT_TYPES = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/ecmascript",
    "application/yaml",
    "application/x-yaml",
    "application/toml",
    "application/x-ndjson",
}
UNLABELED = {"", "application/octet-stream", "binary/octet-stream"}

# Fetch failures, as `FetchResult.error_kind`. Rendering is a second step of the fetch, so a page whose static
# HTML was kept because Chrome was missing or timed out has `error_kind == ""` and `render_status` "render_failed".
ErrorKind = Literal["", "network_error", "http_error", "unsupported_content", "empty_content"]
RenderStatus = Literal["", "rendered", "render_failed"]


@dataclass(frozen=True)
class FetchResult:
    """What a fetch produced, including how it failed, so that a caller never has to parse an exception.

    `url` is the final URL after redirects (the requested URL when no response arrived); `final_url` is an alias.
    `media_type` is the declared Content-Type ("" if none); `kind` is the content kind the rules decided, which is
    the declared type for an accepted page but "application/pdf" for a body starting with %PDF- even when it was
    declared text/plain. `ok` is False when the fetch failed; `error_kind` and `error` then say how, in a category
    and in a readable sentence. `saved` is the path of the downloaded file and is non-empty only for binary
    content. `render_status` is "" when no headless browser was needed, "rendered" when its DOM was used, and
    "render_failed" when it could not be used (Chrome missing, a timeout, or a failed run); `render_error` then
    says why, and the static text is kept."""

    url: str
    media_type: str = ""
    kind: str = ""
    ok: bool = False
    error_kind: ErrorKind = ""
    error: str = ""
    status_code: int = 0
    text: str = ""
    saved: str = ""
    render_status: RenderStatus = ""
    render_error: str = ""

    @property
    def final_url(self) -> str:
        return self.url

    @property
    def success(self) -> bool:
        return self.ok

    @property
    def rendered(self) -> bool:
        return self.render_status == "rendered"

    def to_dict(self) -> dict:
        return asdict(self)


class UnsupportedContent(httpx.HTTPError):
    def __init__(self, kind: str, content: bytes, media_type: str = "", url: str = "", status_code: int = 0):
        super().__init__(f"{kind} is not an HTML or text page; read it with another tool")
        self.kind, self.content, self.media_type, self.url, self.status_code = (
            kind,
            content,
            media_type,
            url,
            status_code,
        )


def fetch_page(url: str, timeout: float = 30) -> tuple[str, str, str]:
    """The page text, its final URL after redirects, and its media type ("" if none is declared)."""
    r = _accepted(url, timeout)
    return r.text, str(r.url), _media_type(r)


def fetch_page_result(url: str, timeout: float = 30) -> FetchResult:
    """As `fetch_page`, but the outcome is a `FetchResult` instead of text or an exception.

    A failed status is reported before the content type, as the server's answer to the request is the first thing
    to know. Binary content is saved (under JEVFETCH_FILES_DIR, or a `jevfetch-<uid>` folder in the temporary
    directory) and its path put in `saved`, so that a file reader can open it."""
    try:
        r = _accepted(url, timeout)
    except UnsupportedContent as e:
        try:
            saved = save_file(url, e.kind, e.content)
        except OSError as save_error:
            return unsupported_result(url, e, save_error=str(save_error))
        return unsupported_result(url, e, saved=saved)
    except httpx.HTTPError as e:
        return failed_result(url, e)
    return text_result(url, r.text, str(r.url), _media_type(r), r.status_code)


def _accepted(url: str, timeout: float) -> httpx.Response:
    """The response if it is a page `fetch_page` returns: a successful status and accepted content. Raises
    `httpx.HTTPStatusError` for a failed status before any content-type decision, and `UnsupportedContent` for
    binary content."""
    r = httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=timeout)
    r.raise_for_status()
    kind = _unsupported_kind(r)
    if kind:
        raise UnsupportedContent(kind, r.content, _media_type(r), str(r.url), r.status_code)
    return r


def fetch(url: str, timeout: float = 30) -> str:
    return fetch_page(url, timeout)[0]


def text_result(url: str, text: str, final_url: str = "", media_type: str = "", status_code: int = 0) -> FetchResult:
    if not text.strip():
        return FetchResult(
            url=final_url or url,
            media_type=media_type,
            kind=media_type,
            error_kind="empty_content",
            error=f"the response body is empty (Content-Type: {media_type or 'none'})",
            status_code=status_code,
        )
    return FetchResult(
        url=final_url or url, media_type=media_type, kind=media_type, ok=True, text=text, status_code=status_code
    )


def unsupported_result(url: str, exc: UnsupportedContent, saved: str = "", save_error: str = "") -> FetchResult:
    error = f"{type(exc).__name__}: {exc}"
    if save_error:
        error = f"{error}; could not save it: {save_error}"
    return FetchResult(
        url=exc.url or url,
        media_type=exc.media_type,
        kind=exc.kind,
        error_kind="unsupported_content",
        error=error,
        status_code=exc.status_code,
        saved=saved,
    )


def failed_result(url: str, exc: httpx.HTTPError) -> FetchResult:
    """The result of an `httpx.HTTPError`: an HTTP status error carries the final URL, the media type, and the
    status code; a network error has no response, so the requested URL stands in for the final one."""
    response = getattr(exc, "response", None)
    if isinstance(exc, httpx.HTTPStatusError) and response is not None:
        code = response.status_code
        return FetchResult(
            url=str(response.url),
            media_type=_media_type(response),
            error_kind="http_error",
            error=f"HTTP {code} {response.reason_phrase} for {response.url}",
            status_code=code,
        )
    return FetchResult(url=url, error_kind="network_error", error=f"{type(exc).__name__}: {exc}")


def save_file(url: str, kind: str, content: bytes) -> str:
    """The extension follows the type so that a tool that reads PDFs or other files can open the file."""
    owner = f"-{os.getuid()}" if hasattr(os, "getuid") else ""  # Linux shares /tmp between users
    folder = Path(os.environ.get("JEVFETCH_FILES_DIR", Path(tempfile.gettempdir()) / f"jevfetch{owner}"))
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    extension = mimetypes.guess_extension(kind) or ".bin"
    path = folder / f"{key}{extension}"
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)
    return str(path)


def _unsupported_kind(r: httpx.Response) -> str | None:
    """A declared HTML or text type skips the undecodable-byte check: legacy-encoded pages often omit their
    charset, and httpx then decodes them as UTF-8 with replacement characters."""
    if r.content.startswith(b"%PDF-"):
        return "application/pdf"
    media = _media_type(r)
    if media.startswith("image/"):
        return media
    if media.startswith("text/") or media in TEXT_TYPES or media.endswith(("+xml", "+json")):
        return None
    if media not in UNLABELED:
        return media
    text = r.text
    if text.count("\ufffd") + text.count("\x00") > 0.1 * len(text):
        return f"binary data ({media or 'no Content-Type'})"
    return None


def _media_type(r: httpx.Response) -> str:
    values = r.headers.get_list("content-type")
    return values[-1].split(";")[0].strip().lower() if values else ""


def find_chrome() -> str | None:
    """JEVFETCH_CHROME, then Playwright's headless shell, then an installed Chrome or Chromium."""
    candidates = [os.environ.get("JEVFETCH_CHROME", "")]
    for pattern in (
        "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac*/chrome-headless-shell",
        "~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux*/chrome-headless-shell",
    ):
        candidates += sorted(glob.glob(os.path.expanduser(pattern)))[-1:]
    candidates += [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ]
    return next((c for c in candidates if c and os.path.exists(c)), None)


def fetch_rendered(url: str, budget_ms: int = 8000, timeout: float = 60) -> str | None:
    """The DOM after rendering, or None if no Chrome is found, rendering times out, or the browser fails.

    A DOM Chrome dumped is returned even if it then exited non-zero, as this function always did; a caller that
    wants the reason for a missing DOM asks `fetch_rendered_result`."""
    return fetch_rendered_result(url, budget_ms, timeout).dom or None


@dataclass(frozen=True)
class RenderResult:
    """The DOM a headless browser rendered, and why it is empty when it is.

    `error` is "" only when `dom` holds a page. A caller keeps the static HTML it fetched when `error` is set, so
    a missing browser or a timeout is reported rather than treated as a successful render."""

    dom: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.dom) and not self.error

    def to_dict(self) -> dict:
        return asdict(self)


def fetch_rendered_result(url: str, budget_ms: int = 8000, timeout: float = 60) -> RenderResult:
    """As `fetch_rendered`, but the reason for a missing DOM is reported in `RenderResult.error`."""
    chrome = find_chrome()
    if not chrome:
        return RenderResult(error="no Chrome or Chromium found; set JEVFETCH_CHROME or install one")
    try:
        r = subprocess.run(
            [chrome, "--headless", "--disable-gpu", f"--virtual-time-budget={budget_ms}", "--dump-dom", url],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return RenderResult(error=f"rendering timed out after {timeout:g} s")
    except OSError as e:
        return RenderResult(error=f"the browser could not be run: {e}")
    if r.stdout:
        return RenderResult(dom=r.stdout)
    if r.returncode:
        detail = (r.stderr or "").strip().splitlines()
        return RenderResult(
            error=f"the browser exited with code {r.returncode}" + (f": {detail[-1]}" if detail else "")
        )
    return RenderResult(error="the browser returned an empty DOM")
