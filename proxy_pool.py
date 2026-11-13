#!/usr/bin/env python3
"""proxy_pool.py — proxy pool, rotation policy, credential masking, argv
safety. No site knowledge lives here.

Accepted proxy formats (one per line in --proxy-file, or a single value on
--proxy):

    http://login:password@host:port
    host:port:login:password
    host:port                          (no auth)

Credentials NEVER reach argv or a command line — see PROHIBITED_FLAG_STYLE
below and the `*_auth()` helpers, which hand credentials to the driver's own
authenticated fields instead. Logs get host:port; credentials are masked.

Rotation (`ProxyPool`) is one proxy per fetch session: `next_untried()`
picks it, the session is retried on THAT proxy, and `rotate(current)` is
called only after the session was blocked with no products. `None` from
`rotate()` means "no further proxy"; `len(pool)` tells the single-proxy
case (unchanged old behaviour) from a genuinely exhausted list.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

# Chromium reports a dead upstream proxy as one of these — NOT as a timeout.
# A caller must retry a *timeout* at the same exit, and a *dead proxy* error
# at a different one; conflating them wastes retries on a proxy that will
# never answer.
PROXY_DEAD_MARKERS = (
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_PROXY_AUTH_UNSUPPORTED",
    "ERR_HTTP_RESPONSE_CODE_FAILURE",
    "net::ERR_NO_SUPPORTED_PROXIES",
)

# A literal command-line flag shaped like this leaks the password to `ps`,
# shell history and any crash report that includes argv. Never build one.
PROHIBITED_FLAG_STYLE = "--proxy-server=http://login:password@host:port"

_LINE_RE = re.compile(
    r"^(?:(?P<scheme>\w+)://)?"
    r"(?:(?P<login>[^:@/]+):(?P<password>[^:@/]*)@)?"
    r"(?P<host>[^:/@]+):(?P<port>\d+)"
    r"(?::(?P<login2>[^:@/]+):(?P<password2>[^:@/]*))?$"
)


class ProxyParseError(ValueError):
    pass


@dataclass(frozen=True)
class Proxy:
    host: str
    port: int
    login: Optional[str] = None
    password: Optional[str] = None
    scheme: str = "http"

    @property
    def has_auth(self) -> bool:
        return bool(self.login)

    def masked(self) -> str:
        """The only representation of a proxy that may be logged or written
        to the sidecar: scheme, host and port. The USERNAME is a credential
        too — printing `login=***` still tells a reader who owns the exit,
        and a username shared across a provider's proxies identifies the
        account. Neither the login nor the password appears here."""
        return f"{self.scheme}://{self.host}:{self.port}"

    def __repr__(self) -> str:
        """A Proxy accidentally formatted with `%s`/an f-string must not
        leak the credentials through the dataclass-generated repr (which
        would print `login='user', password='secret'`)."""
        return f"Proxy({self.masked()})"

    def server_only(self) -> str:
        """host:port with NO credentials — safe to pass as a bare
        `--proxy-server` / `proxyServer` value on engines that cannot
        authenticate that way (Selenium's --proxy-server takes no auth)."""
        return f"{self.scheme}://{self.host}:{self.port}"

    def playwright_proxy_dict(self) -> dict:
        """Playwright's native `proxy=` field — credentials never touch argv."""
        d = {"server": self.server_only()}
        if self.login:
            d["username"] = self.login
            d["password"] = self.password or ""
        return d

    def pyppeteer_launch_arg(self) -> str:
        """pyppeteer/puppeteer: server goes on the launch args (no creds);
        call `page.authenticate({...})` separately for credentials."""
        return f"--proxy-server={self.server_only()}"

    def pyppeteer_auth_dict(self) -> Optional[dict]:
        if not self.login:
            return None
        return {"username": self.login, "password": self.password or ""}


def parse_proxy_line(line: str) -> Proxy:
    line = line.strip()
    if not line or line.startswith("#"):
        raise ProxyParseError("blank/comment proxy line")
    m = _LINE_RE.match(line)
    if m:
        g = m.groupdict()
        port = int(g["port"])
        if not 1 <= port <= 65535:
            m = None  # syntactically a port, but not a usable one
    if not m:
        # Never echo the raw line: a malformed line can still carry a real
        # `user:password@...` (or `host:port:user:password`) fragment, and
        # this exception text is printed to stderr and may be logged.
        raise ProxyParseError(f"unrecognised proxy format: {redact_proxy_line(line)}")
    g = m.groupdict()
    login = g["login"] or g["login2"]
    password = g["password"] if g["login"] else g["password2"]
    return Proxy(
        host=g["host"],
        port=port,
        login=login,
        password=password,
        scheme=g["scheme"] or "http",
    )


def load_proxies(proxy: Optional[str], proxy_file: Optional[str]) -> List[Proxy]:
    """Parse `--proxy` and every non-comment line of `--proxy-file`.

    A bad line ABORTS the load with `ProxyParseError` — it is never
    silently skipped, and the whole file is never silently dropped. The
    caller maps that exception to exit 2. The exception names the line
    NUMBER and a redacted form, never the credential-bearing raw text.
    """
    out: List[Proxy] = []
    if proxy:
        try:
            out.append(parse_proxy_line(proxy))
        except ProxyParseError as exc:
            raise ProxyParseError(f"--proxy: {exc}") from None
    if proxy_file:
        try:
            text = Path(proxy_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise ProxyParseError(f"cannot read --proxy-file {proxy_file!r}: {exc.strerror or exc}") from None
        counted = 0
        for line_number, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            counted += 1
            try:
                out.append(parse_proxy_line(line))
            except ProxyParseError as exc:
                raise ProxyParseError(f"{proxy_file}: line {line_number}: {exc}") from None
        if counted == 0:
            # An empty/comment-only file is not "no proxies were asked for"
            # by accident; refusing it beats starting a direct-connection
            # run the caller believed was proxied.
            raise ProxyParseError(f"{proxy_file}: no proxy entries found")
    return out


class ProxyPool:
    """Round-robin pool with per-proxy failure tracking and an EXPLICIT
    rotation step.

    A proxy is pinned to one fetch session: `next_untried()` picks it, the
    caller keeps using it through that session's proxy-side retries, and
    the caller calls `rotate(current)` ONLY after the session was
    definitively blocked with zero products. `rotate()` records the current
    proxy as blocked and hands back the next proxy that has not been tried
    yet; `None` means every configured proxy has been used (the run is
    "proxy exhausted") or there is only a single proxy (which keeps the
    pre-existing single-proxy behaviour: retry it, then exit 3 with a
    plain `blocked`). A `None` from `next_untried()` is reported the same
    way (`exhausted` / `len(self)`), never by silently connecting directly.

    Concurrency contract (see engines' --concurrency): call `.worker_view(i,
    n)` once per worker to get an independent `ProxyPool` rotated to a
    different starting offset over the SAME underlying proxy list. Each
    worker then only ever calls `.next()` on its own view, so no lock is
    needed anywhere — the safety comes from construction, not discipline.
    """

    def __init__(self, proxies: Sequence[Proxy], shuffle: bool = False, block_retries: int = 3):
        proxies = list(proxies)
        if shuffle:
            proxies = proxies[:]
            random.shuffle(proxies)
        self._proxies: List[Proxy] = proxies
        self._shuffled = bool(shuffle) and len(proxies) > 1
        self._blocked_count = {id(p): 0 for p in proxies}
        self._dead = {id(p): False for p in proxies}
        # Order in which proxies were handed out, for the sidecar's
        # `proxies_tried` (masked only) and the exhaustion decision.
        self._tried: List[Proxy] = []
        self._blocked: List[Proxy] = []
        self.rotations = 0
        self.exhausted = False
        # Two separate numbers, deliberately:
        #  - `block_retries`  — consecutive dead-proxy reports before the
        #    exit is considered dead at all (never < 1: a proxy must be
        #    able to fail once and still be tried again);
        #  - `rotation_retries` — the `--proxy-block-retries` policy: how
        #    many extra retries a blocked-with-no-products session gets on
        #    the SAME proxy before it is retired and the next one used
        #    (0 = rotate on the first block).
        self.block_retries = max(1, block_retries)
        self.rotation_retries = max(0, block_retries)
        self._cursor = 0

    def __len__(self) -> int:
        return len(self._proxies)

    @property
    def shuffled(self) -> bool:
        return self._shuffled

    def worker_view(self, worker_index: int, total_workers: int) -> "ProxyPool":
        if not self._proxies:
            return ProxyPool([], block_retries=self.block_retries)
        offset = worker_index % len(self._proxies)
        rotated = self._proxies[offset:] + self._proxies[:offset]
        return ProxyPool(rotated, block_retries=self.block_retries)

    def _live_proxies(self) -> List[Proxy]:
        return [p for p in self._proxies if not self._dead[id(p)]]

    def next(self) -> Optional[Proxy]:
        """The next live proxy in plain rotation, marked as tried. `None` when
        no proxy is live any more (all were reported dead). Used for the
        first pick and for the unchanged single-proxy path."""
        live = self._live_proxies()
        if not live:
            return None
        p = live[self._cursor % len(live)]
        self._cursor = (self._cursor + 1) % len(live)
        return self._record_tried(p)

    def is_live(self, proxy: Proxy) -> bool:
        """False once the driver reported this exit dead (auth failure /
        connection refused / 403-429 past `block_retries`)."""
        return not self._dead.get(id(proxy), True)

    def next_untried(self, after: Optional[Proxy] = None) -> Optional[Proxy]:
        """The next configured proxy (in the run's order, shuffled or not)
        that is neither dead nor already tried, starting just after
        `after`. Sets `exhausted` and returns `None` when none is left."""
        n = len(self._proxies)
        if n == 0:
            return None
        start = -1
        if after is not None:
            try:
                start = self._proxies.index(after)
            except ValueError:
                start = -1
        for step in range(1, n + 1):
            cand = self._proxies[(start + step) % n]
            if self._dead[id(cand)] or any(cand == t for t in self._tried):
                continue
            return self._record_tried(cand)
        self.exhausted = True
        return None

    def retire(self, proxy: Proxy) -> None:
        """Record `proxy` as having been given up on (blocked, or reported
        dead by the driver). Idempotent; affects only the sidecar's
        `proxies_blocked` list."""
        if id(proxy) not in self._blocked_count:
            return
        if not any(c == proxy for c in self._blocked):
            self._blocked.append(proxy)

    def rotate(self, current: Proxy) -> Optional[Proxy]:
        """Retire `current` as blocked and return the next UNTRIED, live
        proxy in configured (possibly shuffled) order, or `None`.

        `None` means "no further proxy" and the caller MUST use
        `len(self)` to tell the two cases apart:
          - `len(self) == 1` — a single proxy: nothing to rotate to, so the
            pre-existing single-proxy behaviour is unchanged (exit 3 with
            a plain `blocked` stop reason);
          - otherwise — every configured proxy has been tried (`self.
            exhausted` is now True) and the run must end as
            `proxy_blocked_exhausted`, never fall back to a direct
            connection or a plain `blocked`.
        """
        if id(current) not in self._blocked_count:  # not a pool member
            return None
        self.retire(current)
        if len(self._proxies) < 2:
            return None
        nxt = self.next_untried(after=current)
        if nxt is not None:
            self.rotations += 1
        return nxt

    def sidecar(self) -> dict:
        """Masked, JSON-safe description of what the pool did — this is
        what goes into `.meta.json`; no login or password ever appears in
        it, only scheme://host:port."""
        return {
            "proxies_configured": len(self._proxies),
            "proxy_shuffle": self._shuffled,
            "proxies_tried": [p.masked() for p in self._tried],
            "proxies_blocked": [p.masked() for p in self._blocked],
            "proxy_rotations": self.rotations,
            "proxy_exhausted": self.exhausted,
        }

    def _record_tried(self, proxy: Proxy) -> Proxy:
        self._tried.append(proxy)
        return proxy

    def report_failure(self, proxy: Proxy, dead: bool) -> None:
        """`dead=True` for a PROXY_DEAD_MARKERS error or a 403/429 (kills
        the exit after `block_retries` in a row); `dead=False` (a blocked
        gateway page / a timeout / non-proxy error) does not count against
        the exit at all."""
        key = id(proxy)
        if key not in self._blocked_count:
            return
        if not dead:
            return
        self._blocked_count[key] += 1
        if self._blocked_count[key] >= self.block_retries:
            self._dead[key] = True

    def report_success(self, proxy: Proxy) -> None:
        self._blocked_count[id(proxy)] = 0


def is_proxy_dead_error(message: str) -> bool:
    return any(marker in message for marker in PROXY_DEAD_MARKERS)


# --------------------------------------------------------------------------- #
# Redacting a credential OUT OF an arbitrary string — not the Proxy dataclass
# above, but a driver/HTTP library's own exception message.
# "an EXCEPTION MESSAGE is a log" — Playwright's connect_over_cdp repeats a
# failed ws:// endpoint (login:password embedded) up to five times in one
# error (message + a four-line call log), and `requests` puts the full URL,
# query string included, into every HTTPError/connection-error message. Any
# endpoint whose credential rides in the URL — a --cdp-endpoint connection
# string, or 2Captcha's fingerprint/random which takes `?key=...` — leaks it
# the moment the call fails, independent of the `Proxy.masked()` path above,
# which only ever sees a *successful* parse, never a driver's own error text.
# Live-reproduced (2026-09-14): a bad connect_over_cdp call put the fake
# login AND password into the exception's "Call log" four times over.
_URL_CREDENTIAL_RE = re.compile(r"(?P<scheme>\w+://)[^\s/@]+@")
_KEY_PARAM_RE = re.compile(r"(?i)\b((?:client)?key|token|api[_-]?key)=[^&\s'\"]+")
# `host:port:login:password` (the second accepted proxy shape) carries no
# `://` marker, so the URL rule above never sees it. A line that has been
# identified as proxy-shaped is scrubbed whole: keep host:port, drop the
# trailing credential fields.
_COLON_PROXY_RE = re.compile(r"^(?P<host>[^:/@\s]+):(?P<port>\d+)(?P<rest>:[^\s]*)?$")


def redact_proxy_line(line: str) -> str:
    """Mask a possibly-invalid proxy LINE for a log/error message: the
    `--proxy` value or the `host:port:login:password` form, neither of
    which an exception's URL-shaped scrub reaches. Best-effort by design —
    a line this cannot parse is replaced wholesale rather than echoed."""
    if not line:
        return line
    redacted = redact_credentials(line)
    if redacted != line:
        return redacted
    m = _COLON_PROXY_RE.match(line.strip())
    if m and m.group("rest"):
        return f"{m.group('host')}:{m.group('port')}:***"
    if m:
        return line
    return "(malformed proxy line, credentials withheld)"

def redact_credentials(text: str) -> str:
    """Scrub every credential shape this family's own endpoints can leak
    into a driver/HTTP exception's message, GLOBALLY (re.sub, not just the
    first occurrence — a masker that stops after one hit prints the
    password the other four times and looks like it is working). Call this
    on `str(exc)` BEFORE re-raising or logging — never pass the original
    exception through afterwards (chain with `from None`), or its own
    unredacted text still reaches the traceback."""
    if not text:
        return text
    text = _URL_CREDENTIAL_RE.sub(lambda m: f"{m.group('scheme')}***:***@", text)
    text = _KEY_PARAM_RE.sub(lambda m: f"{m.group(1)}=***", text)
    return text
