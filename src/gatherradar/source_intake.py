"""Validate an owner-supplied Instagram account or website before registration.

Input is untrusted. Nothing here crawls a source or asks for credentials.

* Instagram: `@name`, `name` or a profile URL is normalized to one username.
  Access is not verified (that needs the owner's logged-in Chrome profile and a
  real crawl), and the preview says so.
* Website: the URL must be public http(s) without credentials, unusual ports,
  local/private/link-local/metadata addresses (also after DNS resolution). It is
  supported only when its host and listing path match a website source already
  configured with an existing adapter; GatherRadar never invents an adapter or
  scrapes an arbitrary layout. Only such a known host is ever contacted, and
  only for its robots.txt, through the existing transport (same-origin
  redirects only, every hop re-vetted, timeouts and size limits). Anything else
  is registered as `unsupported` and is never runnable.
"""
from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

from .domain.source import Source, SourceType
from .source_registry import RegistryEntry, identity, website_key

IG_HOSTS = {'instagram.com', 'www.instagram.com', 'm.instagram.com'}
IG_RESERVED = {'p', 'reel', 'reels', 'tv', 'explore', 'stories', 'accounts', 'direct', 'about', 'developer',
               'legal', 'web', 'api', 'challenge', 'emails', 'privacy', 'terms', 'session', 'login', 'oauth'}
_IG_USER = re.compile(r'(?!.*\.\.)(?!\.)[a-z0-9._]{1,30}(?<!\.)')
MAX_INPUT = 300
BLOCKED_SUFFIXES = ('.localhost', '.local', '.internal', '.lan', '.home', '.arpa', '.intranet', '.corp')
POLICY = ('robots', 'terms')

Resolver = Callable[[str], Iterable[str]]
RobotsCheck = Callable[[Source], bool]


class IntakeError(ValueError):
    def __init__(self, code: str, source_id: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.source_id = source_id


@dataclass(frozen=True)
class Proposal:
    source: Source            # what would be saved (enabled state chosen at confirmation)
    status: str               # ready | needs_review | unsupported | policy_blocked
    reason: str | None = None  # disabled reason when saved inactive (robots/terms/unsupported)
    template: str | None = None  # base source whose adapter/scope is reused
    robots: str = 'not_checked'  # allowed | disallowed | unknown | not_checked

    @property
    def runnable(self) -> bool:
        return self.status in ('ready', 'needs_review')


def _slug(text: str) -> str:
    return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', text.lower())).strip('_') or 'source'


def _unique(base: str, suffix: str, taken: set[str]) -> str:
    stem = base[:40 - len(suffix)].rstrip('_')
    candidate = stem + suffix
    number = 2
    while candidate in taken:
        tail = f'_{number}{suffix}'
        candidate = base[:40 - len(tail)].rstrip('_') + tail
        number += 1
    return candidate


def _check_text(text: object) -> str:
    if not isinstance(text, str):
        raise IntakeError('empty')
    text = text.strip()
    if not text:
        raise IntakeError('empty')
    if len(text) > MAX_INPUT or any(ord(c) < 32 or c.isspace() for c in text):
        raise IntakeError('format')
    return text


# -- Instagram ------------------------------------------------------------------
def parse_instagram(text: object) -> str:
    text = _check_text(text)
    lowered = text.lower()
    if lowered.startswith(('http://', 'https://', 'www.', 'instagram.com', 'm.instagram.com')) or '/' in text:
        url = text if lowered.startswith(('http://', 'https://')) else 'https://' + text
        parts = urlsplit(url)
        try:
            port = parts.port
        except ValueError:
            raise IntakeError('ig_url') from None
        if parts.scheme not in ('http', 'https') or (parts.hostname or '') not in IG_HOSTS:
            raise IntakeError('ig_url')
        if parts.username or parts.password or port is not None:
            raise IntakeError('credentials')
        segments = [s for s in parts.path.split('/') if s]
        if len(segments) != 1 or segments[0].lower() in IG_RESERVED:
            raise IntakeError('ig_not_profile')
        name = segments[0]
    else:
        name = text[1:] if text.startswith('@') else text
    name = name.lower()
    if not _IG_USER.fullmatch(name) or name in IG_RESERVED:
        raise IntakeError('ig_username')
    return name


def propose_instagram(text: object, entries: list[RegistryEntry]) -> Proposal:
    username = parse_instagram(text)
    for entry in entries:
        source = entry.source
        if source.source_type is SourceType.INSTAGRAM and (source.username or '').lower() == username:
            raise IntakeError('duplicate', source.id)
    taken_ids = {e.source.id for e in entries}
    publishers = {e.source.publisher_key for e in entries}
    slug = _slug(username)
    source_id = _unique(slug, '_instagram', taken_ids)
    publisher = slug if slug not in publishers else _unique(slug, '_ig', publishers)
    source = Source(id=source_id, publisher_key=publisher, name=f'{username} Instagram',
                    source_type=SourceType.INSTAGRAM, url=f'https://www.instagram.com/{username}/',
                    username=username, enabled=False, disabled_reason='owner')
    return Proposal(source, 'needs_review')


# -- Website --------------------------------------------------------------------
def _default_resolver(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]


def _public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split('%', 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not (address.is_multicast or address.is_reserved or address.is_link_local)


def check_public_host(host: str, resolver: Resolver | None = None) -> None:
    """Refuse local, private, link-local, metadata and unresolvable hosts."""
    host = host.lower().rstrip('.')
    try:
        literal = ipaddress.ip_address(host.strip('[]'))
    except ValueError:
        literal = None
    if literal is not None:
        if not _public_address(str(literal)):
            raise IntakeError('private')
        return
    if (host == 'localhost' or '.' not in host or host.endswith(BLOCKED_SUFFIXES)
            or host in ('metadata.google.internal', 'metadata')):
        raise IntakeError('private')
    try:
        host.encode('idna')
    except UnicodeError:
        raise IntakeError('format') from None
    try:
        addresses = list((resolver or _default_resolver)(host))
    except (OSError, UnicodeError):
        raise IntakeError('dns') from None
    if not addresses:
        raise IntakeError('dns')
    if any(not _public_address(a) for a in addresses):
        raise IntakeError('private')


def parse_website(text: object) -> str:
    text = _check_text(text)
    url = text if re.match(r'[A-Za-z][A-Za-z0-9+.-]*://', text) else 'https://' + text
    parts = urlsplit(url)
    if parts.scheme.lower() not in ('http', 'https'):
        raise IntakeError('scheme')
    if '@' in parts.netloc or parts.username or parts.password:
        raise IntakeError('credentials')
    try:
        port = parts.port
    except ValueError:
        raise IntakeError('format') from None
    if port not in (None, 80, 443) or not parts.hostname or '\\' in url:
        raise IntakeError('port' if port not in (None, 80, 443) else 'format')
    host = parts.hostname.lower()
    if host in IG_HOSTS:
        raise IntakeError('is_instagram')
    return urlunsplit((parts.scheme.lower(), host, parts.path or '/', parts.query, ''))


def _bare(host: str) -> str:
    return host[4:] if host.startswith('www.') else host


def _template(url: str, entries: list[RegistryEntry]) -> RegistryEntry | None:
    """A configured website source on the same host whose listing path the URL
    shares; only its existing adapter and URL scope may be reused."""
    parts = urlsplit(url)
    host, segments = _bare(parts.hostname or ''), [s for s in parts.path.split('/') if s]
    best, best_len = None, -1
    for entry in entries:
        source = entry.source
        if entry.origin != 'base' or source.source_type is not SourceType.WEBSITE or source.website is None:
            continue
        theirs = urlsplit(source.url)
        if _bare(theirs.hostname or '') != host:
            continue
        prefix = [s for s in theirs.path.split('/') if s]
        if segments[:len(prefix)] != prefix and not (prefix and segments[:1] == prefix[:1]):
            continue
        if source.website.adapter == 'generic':
            continue  # a generic selector set was tuned for one listing, not a whole site
        if len(prefix) > best_len:
            best, best_len = entry, len(prefix)
    return best


def default_robots_check(source: Source, resolver: Resolver | None = None) -> bool:
    from .collectors.websites.transport import HttpTransport
    host = urlsplit(source.url).hostname or ''

    def vetted(url: str) -> bool:
        if (urlsplit(url).hostname or '') != host:
            return False
        try:
            check_public_host(host, resolver)
        except IntakeError:
            return False
        return True

    return HttpTransport(source.url).policy(allowed=vetted).allows(source.url)


def propose_website(text: object, entries: list[RegistryEntry], *, resolver: Resolver | None = None,
                    robots_check: RobotsCheck | None = None) -> Proposal:
    url = parse_website(text)
    parts = urlsplit(url)
    check_public_host(parts.hostname or '', resolver)
    key = website_key(url)
    for entry in entries:
        if entry.source.source_type is SourceType.WEBSITE and website_key(entry.source.url) == key:
            raise IntakeError('duplicate', entry.source.id)
    taken_ids = {e.source.id for e in entries}
    host = _bare(parts.hostname or '')
    digest = hashlib.sha256(key.encode()).hexdigest()[:6]
    source_id = _unique(f'{_slug(host)}_{digest}', '_website', taken_ids)
    template = _template(url, entries)
    name = f'{host}{parts.path.rstrip("/")}'[:60] + ' Website'
    if template is None:
        publishers = {e.source.publisher_key for e in entries}
        publisher = _slug(host) if _slug(host) not in publishers else _unique(_slug(host), '_web', publishers)
        source = Source(id=source_id, publisher_key=publisher, name=name, source_type=SourceType.WEBSITE,
                        url=url, enabled=False, disabled_reason='unsupported')
        return Proposal(source, 'unsupported', 'unsupported')
    base = template.source
    theirs = urlsplit(base.url)
    # The approved listing's scheme and host spelling are kept (e.g. https, no "www.").
    url = urlunsplit((theirs.scheme, theirs.netloc, parts.path or '/', parts.query, ''))
    common = dict(id=source_id, publisher_key=base.publisher_key, name=name, source_type=SourceType.WEBSITE,
                  url=url, website=base.website, timezone=base.timezone, locale=base.locale)
    if base.disabled_reason in POLICY:
        return Proposal(Source(**common, enabled=False, disabled_reason=base.disabled_reason),
                        'policy_blocked', base.disabled_reason, base.id)
    draft = Source(**common, enabled=False, disabled_reason='owner')
    try:
        allowed = (robots_check or default_robots_check)(draft)
    except Exception:  # network, size, timeout, redirect refusal: unknown, never "allowed"
        return Proposal(draft, 'needs_review', None, base.id, 'unknown')
    if not allowed:
        return Proposal(Source(**common, enabled=False, disabled_reason='robots'),
                        'policy_blocked', 'robots', base.id, 'disallowed')
    return Proposal(draft, 'ready', None, base.id, 'allowed')


def duplicate_of(source: Source, entries: list[RegistryEntry]) -> str | None:
    key = identity(source)
    return next((e.source.id for e in entries if e.source.id == source.id or identity(e.source) == key), None)
