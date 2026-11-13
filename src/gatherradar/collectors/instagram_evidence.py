from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..domain import MediaArtifact, MediaKind, RawItem, Source, SourceType
from ..storage.media import MediaArtifactStore
from .base import SourceDisabledError, SourceTypeMismatchError
from .instagram_browser import (
    BrowserSessionExpiredError,
    InstagramCheckpointError,
    PlaywrightChromeLauncher,
    SESSION_EXPIRED_MESSAGE,
    _ensure_location_allowed,
    _goto,
    _wait_for_optional,
    browser_profile_path,
    has_instagram_session_cookie,
    open_authenticated_browser,
)

DEFAULT_MAX_CAROUSEL_SLIDES = 20
DEFAULT_MAX_REEL_FRAMES = 6
MAX_CAPTURE_ATTEMPTS = 3
VISUAL_SELECTOR = 'article img, main img, article video, main video'

# is_visible() includes slides outside an overflow-clipped carousel and thumbnails
# below the viewport. Only score the rendered portion of a loaded media element.
_VISIBLE_MEDIA_AREA = '''(element) => {
    if (element.closest('a[href*="/p/"], a[href*="/reel/"]')) return 0;
    if (element.tagName === 'IMG' && (!element.complete || !element.naturalWidth)) return 0;
    if (element.tagName === 'VIDEO' && element.readyState < 2) return 0;
    const box = element.getBoundingClientRect();
    let left = Math.max(0, box.left), top = Math.max(0, box.top);
    let right = Math.min(innerWidth, box.right), bottom = Math.min(innerHeight, box.bottom);
    for (let node = element; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') return 0;
        if (node === element) continue;
        const rect = node.getBoundingClientRect();
        if (/(hidden|clip|scroll|auto)/.test(style.overflowX)) {
            left = Math.max(left, rect.left); right = Math.min(right, rect.right);
        }
        if (/(hidden|clip|scroll|auto)/.test(style.overflowY)) {
            top = Math.max(top, rect.top); bottom = Math.min(bottom, rect.bottom);
        }
    }
    // Reject a slide still entering/leaving the horizontally clipped carousel.
    return right-left >= 120 && bottom-top >= 120 && right-left >= box.width * .98
        ? (right-left)*(bottom-top) : 0;
}'''


class MediaPageDriver(Protocol):
    def capture_current_visual(self) -> bytes: ...
    def has_next_carousel(self) -> bool: ...
    def advance_carousel(self) -> bool: ...
    def video_duration_ms(self) -> int | None: ...
    def capture_frame(self, timestamp_ms: int) -> bytes: ...


@dataclass(frozen=True, slots=True)
class MediaCaptureFailure:
    raw_item_id: str
    reason: str
    source_id: str = ''
    slide_index: int | None = None
    category: str = 'capture_failed'
    retry_count: int = 0
    frame_timestamp_ms: int | None = None

    def report(self) -> str:
        return (f'source_id={self.source_id} raw_item_id={self.raw_item_id} '
                f'slide_index={self.slide_index} category={self.category} '
                f'retry_count={self.retry_count}: {self.reason}')


class VisualCaptureError(RuntimeError):
    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


@dataclass(frozen=True, slots=True)
class MediaCaptureResult:
    artifacts: tuple[MediaArtifact, ...] = ()
    failures: tuple[MediaCaptureFailure, ...] = ()

    @property
    def images(self) -> int:
        return sum(item.kind is MediaKind.IMAGE for item in self.artifacts)

    @property
    def carousel_slides(self) -> int:
        return sum(item.kind is MediaKind.CAROUSEL_SLIDE for item in self.artifacts)

    @property
    def reel_frames(self) -> int:
        return sum(item.kind is MediaKind.REEL_FRAME for item in self.artifacts)


def sample_reel_timestamps(duration_ms: int | None, max_frames: int) -> tuple[int, ...]:
    if isinstance(max_frames, bool) or max_frames < 1:
        raise ValueError('max_frames must be positive')
    if duration_ms is None or duration_ms <= 0:
        return ()
    count = min(max_frames, max(1, duration_ms // 1000 + 1))
    if count == 1:
        return (0,)
    final = max(0, duration_ms - 100)
    return tuple(dict.fromkeys(round(index * final / (count - 1)) for index in range(count)))


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def capture_post_artifacts(
    driver: MediaPageDriver, raw_item: RawItem, store: MediaArtifactStore, *,
    max_slides: int = DEFAULT_MAX_CAROUSEL_SLIDES,
) -> MediaCaptureResult:
    if max_slides < 1:
        raise ValueError('max_slides must be positive')
    failures: list[MediaCaptureFailure] = []
    artifacts: list[MediaArtifact] = []
    hashes: set[str] = set()
    for index in range(max_slides):
        content = None
        for attempt in range(MAX_CAPTURE_ATTEMPTS):
            try:
                content = driver.capture_current_visual()
                if _hash(content) in hashes:
                    raise VisualCaptureError('duplicate_visual')
                break
            except (BrowserSessionExpiredError, InstagramCheckpointError):
                raise
            except Exception as exc:
                content = None
                if attempt == MAX_CAPTURE_ATTEMPTS - 1:
                    category = getattr(exc, 'category', type(exc).__name__)
                    failures.append(MediaCaptureFailure(raw_item.id,
                        f'visual capture failed at slide {index} ({category}); remaining slides unconfirmed',
                        raw_item.source_id, index, category, attempt))
        if content is None:
            # A failed transition/capture does not prove the current position.
            # Retain earlier slides and stop, never relabel a later screenshot.
            break
        hashes.add(_hash(content))
        has_next = False
        try:
            if index + 1 < max_slides:
                has_next = driver.advance_carousel()
            elif driver.has_next_carousel():
                failures.append(MediaCaptureFailure(raw_item.id,
                    'carousel slide limit reached; remaining slides unconfirmed',
                    raw_item.source_id, index + 1, 'slide_limit', 0))
        except (BrowserSessionExpiredError, InstagramCheckpointError):
            raise
        except Exception as exc:
            failures.append(MediaCaptureFailure(raw_item.id,
                'carousel advance failed; remaining slides unconfirmed', raw_item.source_id,
                index + 1, getattr(exc, 'category', 'navigation_failed'), 0))
        kind = (MediaKind.CAROUSEL_SLIDE if index or has_next or failures
                or raw_item.content_type == 'carousel' else MediaKind.IMAGE)
        artifacts.append(store.write(raw_item, kind, content,
            slide_index=index if kind is MediaKind.CAROUSEL_SLIDE else None).artifact)
        if not has_next:
            break
    return MediaCaptureResult(tuple(artifacts), tuple(failures))


def capture_reel_artifacts(
    driver: MediaPageDriver, raw_item: RawItem, store: MediaArtifactStore, *,
    max_frames: int = DEFAULT_MAX_REEL_FRAMES,
) -> MediaCaptureResult:
    try:
        timestamps = sample_reel_timestamps(driver.video_duration_ms(), max_frames)
    except Exception as exc:
        return MediaCaptureResult(
            failures=(MediaCaptureFailure(raw_item.id, f'video inspection failed ({type(exc).__name__})',
                raw_item.source_id, category='video_inspection_' + type(exc).__name__),)
        )
    if not timestamps:
        return MediaCaptureResult(
            failures=(MediaCaptureFailure(raw_item.id, 'video duration is unavailable',
                raw_item.source_id, category='video_duration_unavailable'),)
        )
    artifacts: list[MediaArtifact] = []
    failures: list[MediaCaptureFailure] = []
    hashes: set[str] = set()
    for timestamp in timestamps:
        try:
            content = driver.capture_frame(timestamp)
            digest = _hash(content)
            if digest in hashes:
                continue
            hashes.add(digest)
            artifacts.append(
                store.write(
                    raw_item, MediaKind.REEL_FRAME, content,
                    frame_timestamp_ms=timestamp,
                ).artifact
            )
        except Exception as exc:
            failures.append(
                MediaCaptureFailure(raw_item.id, f'frame {timestamp} ms failed ({type(exc).__name__})',
                    raw_item.source_id, category='frame_capture_' + type(exc).__name__, frame_timestamp_ms=timestamp)
            )
    return MediaCaptureResult(tuple(artifacts), tuple(failures))


class PlaywrightMediaPageDriver:
    '''Small browser-specific layer around the bounded capture algorithms.'''

    def __init__(self, page: Any, *, timeout_ms: int = 5_000) -> None:
        self.page = page
        self._visual = None
        self._source = None
        self._advanced = False
        self.timeout_ms = timeout_ms

    def _largest_visible(self, selector: str) -> Any:
        self.page.wait_for_function(
            f'(selector) => [...document.querySelectorAll(selector)].some(el => ({_VISIBLE_MEDIA_AREA})(el) > 0)',
            arg=selector, timeout=10_000,
        )
        locator = self.page.locator(selector)
        choices: list[tuple[float, Any]] = []
        for index in range(locator.count()):
            item = locator.nth(index)
            if not item.is_visible():
                continue
            area = item.evaluate(_VISIBLE_MEDIA_AREA)
            if area > 0:
                choices.append((area, item))
        if not choices:
            raise ValueError('no displayed media element was found')
        return max(choices, key=lambda entry: entry[0])[1]

    def capture_current_visual(self) -> bytes:
        operation = 'visual_readiness'
        try:
            # Hold an element handle, not a live nth locator which can silently
            # point at another slide after React replaces/reorders DOM nodes.
            handle = self.page.wait_for_function(
                f'''(args) => {{
                    const choices = [...document.querySelectorAll(args.selector)]
                        .map(el => [({_VISIBLE_MEDIA_AREA})(el), el])
                        .filter(([area]) => area > 0).sort((a,b) => b[0]-a[0]);
                    const el = choices[0]?.[1];
                    if (!el || (args.advanced && el === args.previous &&
                        (el.currentSrc || el.src) === args.source)) return false;
                    return el;
                }}''', arg=dict(selector=VISUAL_SELECTOR, advanced=self._advanced,
                               previous=self._visual, source=self._source), timeout=self.timeout_ms)
            visual = handle.as_element()
            operation = 'visual_stability'
            visual.wait_for_element_state('stable', timeout=self.timeout_ms)
            source = visual.evaluate('(el) => el.currentSrc || el.src')
            operation = 'video_frame_readiness'
            if visual.evaluate('(el) => el.tagName') == 'VIDEO':
                # One deterministic poster frame per video slide; reels retain
                # their separate multi-frame sampler and timestamps.
                self._seek_video(visual, 0)
            operation = 'capture_bounds'
            if visual.evaluate(_VISIBLE_MEDIA_AREA) <= 0:
                raise VisualCaptureError('visual_changed')
            box = visual.bounding_box()
            if not box:
                raise VisualCaptureError('capture_bounds')
            operation = 'screenshot'
            content = self._screenshot(box)
            if (visual.evaluate('(el) => el.currentSrc || el.src') != source
                    or visual.evaluate(_VISIBLE_MEDIA_AREA) <= 0
                    or visual.bounding_box() != box):
                raise VisualCaptureError('visual_changed')
            self._visual, self._source, self._advanced = visual, source, False
            return content
        except VisualCaptureError:
            raise
        except Exception as exc:
            raise VisualCaptureError(operation + '_' + type(exc).__name__) from None

    def _screenshot(self, box: dict) -> bytes:
        # Locator screenshots round fractional edges outward, including a sliver
        # of the neighboring carousel slide. Keep only whole pixels inside it.
        left, top = math.ceil(box['x']), math.ceil(box['y'])
        return self.page.screenshot(type='png', timeout=self.timeout_ms, clip={
            'x': left, 'y': top,
            'width': math.floor(box['x'] + box['width']) - left,
            'height': math.floor(box['y'] + box['height']) - top,
        })

    def _next_control(self) -> Any | None:
        selector = (
            'article button[aria-label=Next], '
            'article button[aria-label=بعدی], '
            'article button:has(svg[aria-label=Next]), '
            'main button[aria-label=Next], main button[aria-label=بعدی], '
            'main button:has(svg[aria-label=Next])'
        )
        controls = self.page.locator(selector)
        for index in range(controls.count() - 1, -1, -1):
            control = controls.nth(index)
            if control.is_visible() and control.is_enabled():
                return control
        return None

    def has_next_carousel(self) -> bool:
        return self._next_control() is not None

    def advance_carousel(self) -> bool:
        control = self._next_control()
        if control is None:
            return False
        control.click(timeout=self.timeout_ms)
        self._advanced = True
        return True

    def _video(self) -> Any:
        return self._largest_visible('article video, main video')

    def video_duration_ms(self) -> int | None:
        duration = self._video().evaluate('(video) => video.duration')
        if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            return None
        return round(duration * 1000)

    def capture_frame(self, timestamp_ms: int) -> bytes:
        video = self._video()
        self._seek_video(video, timestamp_ms)
        return video.screenshot(type='png')

    def _seek_video(self, video: Any, timestamp_ms: int) -> None:
        video.evaluate('(video) => video.pause()')
        video.evaluate(
            '''(video, seconds) => new Promise((resolve, reject) => {
                const target = Math.min(seconds, Math.max(0, video.duration - 0.05));
                const cleanup = () => {
                    clearTimeout(timer);
                    video.removeEventListener('seeked', done);
                    video.removeEventListener('loadeddata', done);
                };
                const done = () => {
                    if (!video.seeking && video.readyState >= 2 &&
                        Math.abs(video.currentTime - target) < 0.05) {
                        video.pause();
                        cleanup();
                        resolve();
                    }
                };
                const timer = setTimeout(() => {
                    cleanup();
                    reject(new Error('video seek timed out'));
                }, 5000);
                video.addEventListener('seeked', done);
                video.addEventListener('loadeddata', done);
                video.currentTime = target;
                done();
            })''',
            timestamp_ms / 1000,
        )


class InstagramMediaEvidenceAcquirer:
    def __init__(
        self, *, data_dir: str | Path = 'data', launcher: Any | None = None,
        navigation_timeout_ms: int = 30_000,
        content_wait_ms: int = 10_000,
        max_carousel_slides: int = DEFAULT_MAX_CAROUSEL_SLIDES,
        max_reel_frames: int = DEFAULT_MAX_REEL_FRAMES,
    ) -> None:
        self.profile_dir = browser_profile_path(data_dir)
        self.launcher = launcher
        self.navigation_timeout_ms = navigation_timeout_ms
        self.content_wait_ms = content_wait_ms
        self.max_carousel_slides = max_carousel_slides
        self.max_reel_frames = max_reel_frames

    def acquire(
        self, raw_items: tuple[RawItem, ...], source: Source,
        store: MediaArtifactStore,
    ) -> MediaCaptureResult:
        if source.source_type is not SourceType.INSTAGRAM:
            raise SourceTypeMismatchError(f'source {source.id} is not an Instagram source')
        if not source.enabled:
            raise SourceDisabledError(f'source {source.id} is disabled in the registry')
        launcher = self.launcher or PlaywrightChromeLauncher(
            timeout_ms=self.navigation_timeout_ms
        )
        artifacts: list[MediaArtifact] = []
        failures: list[MediaCaptureFailure] = []
        with open_authenticated_browser(self.profile_dir.resolve(), launcher) as browser:
            for raw_item in raw_items:
                try:
                    _goto(browser.page, raw_item.content_url, self.navigation_timeout_ms)
                    _ensure_location_allowed(browser.page.url)
                    if not has_instagram_session_cookie(browser.context):
                        raise BrowserSessionExpiredError(SESSION_EXPIRED_MESSAGE)
                    _wait_for_optional(
                        browser.page, 'article img, main img, article video, main video',
                        self.content_wait_ms,
                    )
                    driver = PlaywrightMediaPageDriver(browser.page)
                    if raw_item.content_type == 'reel':
                        result = capture_reel_artifacts(
                            driver, raw_item, store, max_frames=self.max_reel_frames
                        )
                    else:
                        result = capture_post_artifacts(
                            driver, raw_item, store, max_slides=self.max_carousel_slides
                        )
                    artifacts.extend(result.artifacts)
                    failures.extend(result.failures)
                except BrowserSessionExpiredError:
                    raise
                except InstagramCheckpointError as exc:
                    # Stop for manual verification, retaining earlier captures.
                    failures.append(MediaCaptureFailure(raw_item.id, str(exc), source.id, category='access_checkpoint'))
                    break
                except Exception as exc:
                    failures.append(
                        MediaCaptureFailure(raw_item.id, f'media page failed ({type(exc).__name__})',
                            source.id, category='media_page_' + type(exc).__name__)
                    )
        from dataclasses import replace
        return MediaCaptureResult(tuple(artifacts), tuple(
            replace(f, source_id=source.id) if not f.source_id else f for f in failures))


__all__ = [
    'DEFAULT_MAX_CAROUSEL_SLIDES', 'DEFAULT_MAX_REEL_FRAMES',
    'InstagramMediaEvidenceAcquirer', 'MediaCaptureFailure', 'MediaCaptureResult',
    'MediaPageDriver', 'PlaywrightMediaPageDriver', 'capture_post_artifacts',
    'capture_reel_artifacts', 'sample_reel_timestamps',
]
