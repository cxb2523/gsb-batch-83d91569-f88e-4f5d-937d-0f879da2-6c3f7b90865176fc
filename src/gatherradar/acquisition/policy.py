"""Infrequent, cached re-check of policy-disabled website channels.

Only the origin's robots.txt is requested — never a page, feed or sitemap. A
result is advisory: a channel is never re-enabled automatically. When robots now
permits GatherRadar, the owner is told to change `enabled` explicitly.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ..collectors.base import safe_failure
from ..collectors.websites.transport import HttpTransport
from ..domain import Source, SourceType
from ..review.io import atomic_json

RECHECK_INTERVAL = timedelta(days=7)


@dataclass(frozen=True)
class PolicyNotice:
    source_id: str
    state: str  # still_blocked | now_allowed | check_failed
    checked_at: str
    fresh: bool  # False: reused from the cache without a request
    detail: str | None = None

    def record(self) -> dict:
        return {'source_id': self.source_id, 'state': self.state, 'checked_at': self.checked_at,
                'fresh': self.fresh, 'detail': self.detail}


def robots_allows(source: Source) -> bool:
    return HttpTransport(source.url).policy().allows(source.url)


def recheck_policies(sources: Iterable[Source], *, state_path: Path, now: datetime,
                     allows: Callable[[Source], bool] = robots_allows,
                     interval: timedelta = RECHECK_INTERVAL) -> tuple[PolicyNotice, ...]:
    targets = [s for s in sources if s.source_type is SourceType.WEBSITE and not s.enabled
               and s.disabled_reason == 'robots']
    try:
        cache = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    notices = []
    for source in targets:
        cached = cache.get(source.id)
        try:
            last = datetime.fromisoformat(cached['checked_at']) if isinstance(cached, dict) else None
        except (KeyError, TypeError, ValueError):
            last = None
        if last is not None and last.tzinfo is not None and now - last < interval and cached.get('state') in (
                'still_blocked', 'now_allowed'):
            notices.append(PolicyNotice(source.id, cached['state'], cached['checked_at'], False))
            continue
        try:
            state, detail = ('now_allowed' if allows(source) else 'still_blocked'), None
        except Exception as exc:
            # A transient failure never changes the recorded policy decision.
            state, detail = 'check_failed', safe_failure(exc)
        notice = PolicyNotice(source.id, state, now.isoformat(), True, detail)
        notices.append(notice)
        if state != 'check_failed':
            cache[source.id] = {'state': state, 'checked_at': notice.checked_at}
    if any(n.fresh and n.state != 'check_failed' for n in notices):
        atomic_json(state_path, cache)
    return tuple(notices)
