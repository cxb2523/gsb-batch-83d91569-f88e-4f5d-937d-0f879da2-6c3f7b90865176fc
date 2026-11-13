from __future__ import annotations

import re
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from ..base import SourceAccessRestrictedError

_ACCOUNT_PARTS = {'login', 'logout', 'signin', 'signup', 'auth', 'account', 'profile',
                  'checkout', 'tickets', 'wallet', 'admin'}


def canonical_url(url: str, base: str, drop_query_params: tuple[str, ...] = ()) -> str:
    """Keep meaningful query bytes/order; discard only declared tracking keys."""
    if any(c.isspace() or ord(c) < 32 for c in url):
        raise SourceAccessRestrictedError('URL contains whitespace or control characters')
    absolute = urljoin(base, url)
    parsed = urlsplit(absolute)
    approved = urlsplit(base)
    try:
        origin = (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
        base_origin = (approved.scheme, approved.hostname, approved.port or (443 if approved.scheme == 'https' else 80))
    except ValueError:
        raise SourceAccessRestrictedError('invalid URL port') from None
    if (origin != base_origin or parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or '\\' in absolute
            or any(c.isspace() or ord(c) < 32 for c in absolute)):
        raise SourceAccessRestrictedError('URL is outside the approved public origin')
    decoded = unquote(parsed.path)
    if '%' in decoded or '\\' in decoded or any(ord(c) < 32 for c in decoded) or any(
        part.lower() in _ACCOUNT_PARTS or part in ('.', '..') for part in decoded.split('/')
    ):
        raise SourceAccessRestrictedError('account or ambiguous URL path refused')
    kept = []
    for part in parsed.query.split('&'):
        key = unquote(part.partition('=')[0]).lower()
        if part and not (key.startswith('utm_') or key in ('fbclid', 'gclid') or key in drop_query_params):
            kept.append(part)
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path or '/', '&'.join(kept), ''))


def detail_url(url: str, base: str, prefixes: tuple[str, ...], drop: tuple[str, ...] = ()) -> str | None:
    try:
        result = canonical_url(url, base, drop)
    except (SourceAccessRestrictedError, ValueError):
        return None
    path = urlsplit(result).path
    # One opaque item key after an allowed directory. No nested/account/download paths.
    if any(path.startswith(prefix) and re.fullmatch(r'[A-Za-z0-9_-]+/?', path[len(prefix):]) for prefix in prefixes):
        return result
    return None
