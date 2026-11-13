"""Comparison copies only: stored wording and URLs are never rewritten."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from urllib.parse import urlsplit, urlunsplit, unquote_plus

from ..normalization.text import fold

GENERIC = frozenset("event events workshop concert exhibition festival the a an of and in at for نمایشگاه رویداد ایونت کارگاه کنسرت جشنواره و در از به برای".split())
TRACKING = frozenset({"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"})


def text_key(value: str) -> str:
    text = fold(unicodedata.normalize("NFKC", value))
    return " ".join("".join(c if c.isalnum() else " " for c in text).split())


def distinctive_tokens(value: str | None) -> frozenset[str]:
    return frozenset(text_key(value or "").split()) - GENERIC


def title_relation(left: str | None, right: str | None) -> str:
    a, b = distinctive_tokens(left), distinctive_tokens(right)
    # A number plus a generic event label is not a distinctive name.
    if not any(not token.isdigit() for token in a) or not any(not token.isdigit() for token in b):
        return "weak"
    if text_key(left or "") == text_key(right or ""):
        return "exact"
    if {t for t in a if t.isdigit()} != {t for t in b if t.isdigit()}:
        return "different"
    overlap = a & b
    if len(overlap) >= 2 and len(overlap) / len(a | b) >= 0.85:
        return "strong"
    return "different" if not overlap else "partial"


def registration_key(value: str | None, homepages: tuple[str, ...] = ()) -> str | None:
    if not value or any(c.isspace() for c in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        parsed.port
    except ValueError:
        return None
    # Keep query order, repeated keys and all unknown parameters; don't equate
    # http/https, slash variants, fragments, or opaque ticket IDs.
    query = "&".join(part for part in parsed.query.split("&")
                     if unquote_plus(part.split("=", 1)[0]).casefold() not in TRACKING)
    key = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, query, parsed.fragment))
    if not parsed.path.strip("/") or key in {registration_key(home) for home in homepages}:
        return None
    return key


def stable_id(prefix: str, values: tuple[str, ...]) -> str:
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()
