"""Fetching pages. Pages whose static HTML has almost no text are rendered with headless Chrome."""

import glob
import hashlib
import mimetypes
import os
import subprocess
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

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


class UnsupportedContent(httpx.HTTPError):
    def __init__(self, kind: str, content: bytes):
        super().__init__(f"{kind} is not an HTML or text page; read it with another tool")
        self.kind, self.content = kind, content


def fetch_page(url: str, timeout: float = 30) -> tuple[str, str, str]:
    """The page text, its final URL after redirects, and its media type ("" if none is declared)."""
    r = httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=timeout)
    r.raise_for_status()
    kind = _unsupported_kind(r)
    if kind:
        raise UnsupportedContent(kind, r.content)
    return r.text, str(r.url), _media_type(r)


def fetch(url: str, timeout: float = 30) -> str:
    return fetch_page(url, timeout)[0]


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
    """The DOM after rendering, or None if no Chrome is found or rendering times out."""
    chrome = find_chrome()
    if not chrome:
        return None
    try:
        r = subprocess.run(
            [chrome, "--headless", "--disable-gpu", f"--virtual-time-budget={budget_ms}", "--dump-dom", url],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None
    return r.stdout or None
