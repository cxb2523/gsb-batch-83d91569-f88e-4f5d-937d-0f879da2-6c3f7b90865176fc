"""Elapsed time and an evidence-based remaining-time estimate for bot crawls.

Elapsed time comes from a monotonic clock. The estimate uses only local,
non-sensitive history (`data/telegram/timings.json`): per source, how many
seconds a finished source took, its outcome, the item limit and whether
Instagram media/OCR was acquired; and how long analysis + persistence +
export took after collection. No ML, no external data.

Rules (an ETA is never invented):
* Only `success` samples with the same limit and media mode form a baseline.
  `partial`, `failed` and unusually slow samples (more than 3x the median of
  the other baseline samples) are kept for inspection but excluded.
* A source needs at least `MIN_SAMPLES` baseline samples of its own; otherwise
  the median range of its kind (Instagram or website) is used when that kind
  has enough samples. Any remaining source without either means no estimate.
* Ranges sum per-source low/high (the smallest/largest of the recent baseline
  samples), so they stay wide where history varies, and shrink only as real
  time passes or sources finish.
"""
from __future__ import annotations

import json
import math
import statistics
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

VERSION = 1
MAX_SAMPLES = 20          # per source, and for the post-collection stage
MIN_SAMPLES = 3
WINDOW = 10               # most recent baseline samples considered
SLOW_FACTOR = 3.0
MAX_SECONDS = 6 * 3600    # a sample longer than this is not plausible and is ignored


@dataclass(frozen=True)
class Range:
    low: float
    typical: float
    high: float
    basis: str  # 'source' | 'kind' | 'stage'


@dataclass(frozen=True)
class Estimate:
    low: float
    high: float
    current_overrun: bool = False   # the current source passed its usual maximum
    bases: tuple[str, ...] = ()


class TimingStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def read(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(payload, dict) or payload.get('version') != VERSION:
                raise ValueError
            sources = payload.get('sources') if isinstance(payload.get('sources'), dict) else {}
            post = payload.get('post') if isinstance(payload.get('post'), list) else []
            return {'version': VERSION, 'sources': sources, 'post': post}
        except (OSError, ValueError, TypeError):
            return {'version': VERSION, 'sources': {}, 'post': []}

    def _write(self, payload: dict) -> None:
        from ..review.io import atomic_json
        atomic_json(self.path, payload)

    def record_source(self, source_id: str, *, kind: str, seconds: float, status: str, limit: int,
                      media: bool) -> None:
        if not (0 <= seconds <= MAX_SECONDS) or not isinstance(source_id, str):
            return
        sample = {'seconds': round(float(seconds), 1), 'status': status, 'kind': kind, 'limit': int(limit),
                  'media': bool(media), 'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        with self._lock:
            payload = self.read()
            samples = [s for s in payload['sources'].get(source_id, []) if isinstance(s, dict)] + [sample]
            payload['sources'][source_id] = samples[-MAX_SAMPLES:]
            self._write(payload)

    def record_post(self, *, seconds: float, status: str, sources: int) -> None:
        if not 0 <= seconds <= MAX_SECONDS:
            return
        sample = {'seconds': round(float(seconds), 1), 'status': status, 'sources': int(sources),
                  'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        with self._lock:
            payload = self.read()
            payload['post'] = ([s for s in payload['post'] if isinstance(s, dict)] + [sample])[-MAX_SAMPLES:]
            self._write(payload)


def _seconds(samples: list) -> list[float]:
    values = []
    for sample in samples:
        value = sample.get('seconds') if isinstance(sample, dict) else None
        if isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= MAX_SECONDS:
            values.append(float(value))
    return values


def _baseline(values: list[float]) -> list[float]:
    """Drop unusually slow samples (tracked, not trusted for the estimate)."""
    kept = []
    for index, value in enumerate(values):
        others = values[:index] + values[index + 1:]
        if len(others) >= MIN_SAMPLES - 1 and others and value > SLOW_FACTOR * statistics.median(others):
            continue
        kept.append(value)
    return kept[-WINDOW:]


def _range(values: list[float], basis: str) -> Range | None:
    if len(values) < MIN_SAMPLES:
        return None
    return Range(min(values), statistics.median(values), max(values), basis)


class CrawlDurationEstimator:
    def __init__(self, store: TimingStore) -> None:
        self.store = store

    def _eligible(self, samples: list, limit: int, media: bool) -> list[float]:
        return _seconds([s for s in samples if isinstance(s, dict) and s.get('status') == 'success'
                         and s.get('limit') == limit and bool(s.get('media')) == media])

    def source_range(self, source_id: str, kind: str, *, limit: int, media: bool,
                     payload: dict | None = None) -> Range | None:
        payload = payload or self.store.read()
        own = _range(_baseline(self._eligible(payload['sources'].get(source_id, []), limit, media)), 'source')
        if own is not None:
            return own
        # The kind's typical source: the median of each other source's own median.
        medians = []
        for other, samples in payload['sources'].items():
            values = _baseline(self._eligible([s for s in samples if isinstance(s, dict) and s.get('kind') == kind],
                                              limit, media))
            if len(values) >= MIN_SAMPLES:
                medians.append((min(values), statistics.median(values), max(values)))
        if len(medians) < 1:
            return None
        pooled = [v for low, mid, high in medians for v in (low, mid, high)]
        return Range(min(m[0] for m in medians), statistics.median(pooled), max(m[2] for m in medians), 'kind')

    def post_range(self, payload: dict | None = None) -> Range | None:
        payload = payload or self.store.read()
        values = _seconds([s for s in payload['post'] if isinstance(s, dict) and s.get('status') in ('success', 'partial')])
        return _range(_baseline(values), 'stage')

    def estimate(self, *, pending: list[tuple[str, str]], current: tuple[str, str, float] | None,
                 post_elapsed: float | None, limit: int, media: bool) -> Estimate | None:
        """`pending`: sources not started yet (id, kind). `current`: the running
        source (id, kind, seconds so far). `post_elapsed`: seconds into the
        post-collection stage, or None while collection is still going."""
        payload = self.store.read()
        low = high = 0.0
        bases: list[str] = []
        overrun = False
        if current is not None:
            source_id, kind, elapsed = current
            expected = self.source_range(source_id, kind, limit=limit, media=media and kind == 'instagram',
                                         payload=payload)
            if expected is None:
                return None
            bases.append(expected.basis)
            if elapsed > expected.high:
                overrun = True  # no defensible bound for the rest of this source
            else:
                low += max(0.0, expected.low - elapsed)
                high += expected.high - elapsed
        for source_id, kind in pending:
            expected = self.source_range(source_id, kind, limit=limit, media=media and kind == 'instagram',
                                         payload=payload)
            if expected is None:
                return None
            bases.append(expected.basis)
            low += expected.low
            high += expected.high
        post = self.post_range(payload)
        if post is None:
            return None
        bases.append(post.basis)
        if post_elapsed is None:
            low += post.low
            high += post.high
        elif post_elapsed > post.high:
            overrun = True
        else:
            low += max(0.0, post.low - post_elapsed)
            high += post.high - post_elapsed
        return Estimate(low, max(high, low), overrun, tuple(bases))
