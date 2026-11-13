from __future__ import annotations

import re
import time
import math
import socket
import ssl
from http.client import HTTPException
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from ..base import SourceAccessRestrictedError, SourceUnavailableError
from .urls import canonical_url

USER_AGENT = 'GatherRadar/0.1'
MAX_BYTES = 3_000_000


@dataclass(frozen=True)
class Page:
    url: str
    html: str
    transport: str = 'http'


class PageTransport(Protocol):
    def fetch(self, url: str, *, allowed: Callable[[str], bool] | None = None) -> Page: ...


class RobotsPolicy:
    """Applicable robots groups with longest-path precedence and wildcard support."""

    def __init__(self, text: str) -> None:
        groups: list[tuple[list[str], list[tuple[str, str]]]] = []
        agents: list[str] = []
        directives: list[tuple[str, str]] = []
        for line in text.splitlines():
            key, separator, value = line.partition('#')[0].partition(':')
            if not separator:
                continue
            key, value = key.strip().lower(), value.strip()
            if key == 'user-agent':
                if directives:
                    groups.append((agents, directives))
                    agents, directives = [], []
                agents.append(value.lower())
            elif agents and key in ('allow', 'disallow', 'crawl-delay'):
                directives.append((key, value))
        groups.append((agents, directives))
        applicable = [(max((len(a) if a != '*' else 0) for a in agents
                           if a == '*' or a in USER_AGENT.lower()), directives)
                      for agents, directives in groups
                      if any(a == '*' or a in USER_AGENT.lower() for a in agents)]
        best = max((rank for rank, _ in applicable), default=-1)
        self.rules = [rule for rank, rules in applicable if rank == best for rule in rules]
        self.delay = 1.0
        for key, value in self.rules:
            if key == 'crawl-delay':
                try:
                    delay = float(value)
                    if not math.isfinite(delay) or delay < 0:
                        raise ValueError
                    self.delay = max(self.delay, delay)
                except ValueError:
                    raise SourceUnavailableError('invalid robots crawl-delay') from None
        if not 1 <= self.delay <= 30:
            raise SourceAccessRestrictedError('robots crawl-delay exceeds bounded collection budget')

    def allows(self, url: str) -> bool:
        parts = urlsplit(url)
        path = unquote(parts.path + ('?' + parts.query if parts.query else ''))
        matched = []
        for key, value in self.rules:
            if key not in ('allow', 'disallow') or not value:
                continue
            pattern = re.escape(unquote(value)).replace(r'\*', '.*')
            if value.endswith('$'):
                pattern = pattern[:-2] + '$'
            if re.match(pattern, path):
                matched.append((len(value.replace('*', '').rstrip('$')), key == 'allow'))
        return max(matched, default=(0, True))[1]


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class HttpTransport:
    """Public static HTML only. No cookies, login profile, retries, or browser."""

    def __init__(self, source_url: str) -> None:
        self.source_url = canonical_url(source_url, source_url)
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self._policy: RobotsPolicy | None = None
        self._last_request: float | None = None

    def _request(self, url: str) -> tuple[int, dict[str, str], bytes]:
        delay = self._policy.delay if self._policy else 1.0
        if self._last_request is not None:
            time.sleep(max(0, delay - (time.monotonic() - self._last_request)))
        self._last_request = time.monotonic()
        try:
            try:
                response = self._opener.open(Request(url, headers={
                    'User-Agent': USER_AGENT, 'Accept': 'text/html,text/plain',
                }), timeout=15)
            except HTTPError as exc:
                response = exc
            with response:
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise SourceUnavailableError('response exceeds size bound')
                return response.code, {k.lower(): v for k, v in response.headers.items()}, data
        except (URLError, OSError, TimeoutError, HTTPException) as exc:
            cause = exc.reason if isinstance(exc, URLError) else exc
            category = ('dns' if isinstance(cause, socket.gaierror) else
                        'timeout' if isinstance(cause, TimeoutError) else
                        'tls' if isinstance(cause, ssl.SSLError) else 'network')
            raise SourceUnavailableError('public HTTP request failed', category=category, operation='request') from None

    def _read(self, url: str, *, robots: bool = False,
              allowed: Callable[[str], bool] | None = None) -> tuple[str, str]:
        for _ in range(4):
            url = canonical_url(url, self.source_url)
            if allowed is not None and not allowed(url):
                raise SourceAccessRestrictedError('redirect left the permitted detail layout',category='redirect')
            if not robots and self._policy is not None and not self._policy.allows(url):
                raise SourceAccessRestrictedError('robots.txt disallows page', category='robots', operation='robots')
            status, headers, data = self._request(url)
            if status in (301, 302, 303, 307, 308):
                location = headers.get('location')
                if not location:
                    raise SourceUnavailableError('redirect lacks Location',category='redirect')
                url = canonical_url(location, url)
                continue
            if robots and status in (404, 410):
                return url, ''
            if status in (401, 403, 429):
                raise SourceAccessRestrictedError(f'public HTTP access refused ({status})', category='http_status', operation='robots' if robots else 'request', http_status=status)
            if status != 200:
                raise SourceUnavailableError(f'public HTTP status {status}', category='http_status', operation='robots' if robots else 'request', http_status=status)
            mime = headers.get('content-type', '').split(';')[0].strip().lower()
            if mime not in (('text/plain', 'text/html') if robots else ('text/html', 'application/xhtml+xml')):
                raise SourceUnavailableError('unexpected response content type', category='content_type', operation='robots' if robots else 'request')
            if headers.get('content-disposition', '').lower().startswith('attachment'):
                raise SourceAccessRestrictedError('download response refused')
            # These approved sites serve UTF-8; unknown encodings fail instead of corrupting evidence.
            try:
                text = data.decode('utf-8-sig')
            except UnicodeError:
                raise SourceUnavailableError('response is not valid UTF-8', category='encoding') from None
            if robots and re.search(r'<(?:!doctype|html|body)\b', text, re.IGNORECASE):
                raise SourceUnavailableError('robots URL returned HTML instead of directives', category='robots', operation='robots')
            return url, text
        raise SourceUnavailableError('redirect limit exceeded',category='redirect')

    def policy(self, *, allowed: Callable[[str], bool] | None = None) -> RobotsPolicy:
        """This origin's robots rules for GatherRadar; fetched once per transport.
        `allowed` vets every hop (including same-origin redirects) before a request."""
        if self._policy is None:
            _, text = self._read('/robots.txt', robots=True, allowed=allowed)
            self._policy = RobotsPolicy(text)
        return self._policy

    def fetch(self, url: str, *, allowed: Callable[[str], bool] | None = None) -> Page:
        self.policy()
        final_url, html = self._read(url, allowed=allowed)
        return Page(final_url, html)
