"""The pipeline: list pages -> gallery pages -> image pages -> files and SQLite.

Workers only fetch and parse; every database write happens on the calling
thread, so one SQLite connection is enough.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from tqdm import tqdm

from .db import Database, format_time, parse_time
from .errors import BannedError, CrawlerError, GalleryUnavailableError, SettingsError
from .fetch import Fetcher, host_of
from .parse import (
    GalleryInfo,
    Thumbnail,
    content_warning_url,
    is_quota_placeholder,
    parse_gallery_info,
    parse_gallery_url,
    parse_image_page,
    parse_list_page,
    parse_thumbnail_page,
)
from .settings import Settings

log = logging.getLogger(__name__)

#: How long to wait when the list is blocked and the page does not say for how long
#: (the 2019 version always slept one hour here).
DEFAULT_BAN_WAIT = 60 * 60
#: Characters Windows, macOS or Linux refuse in file names.
UNSAFE_FILE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class CrawlControl:
    """Flags shared by the worker threads."""

    #: Set once the site serves its "quota exceeded" image; later galleries only get tags.
    quota_exceeded: threading.Event = field(default_factory=threading.Event)
    #: Set to make workers stop at the next image (ban, Ctrl+C).
    stop: threading.Event = field(default_factory=threading.Event)


class StopReason(str, Enum):
    """Why a gallery's image download ended, so a rerun can tell what to resume.

    The value rides along on every :class:`DownloadResult`; galleries that only
    got tags have no download result at all.
    """

    #: Every image was saved or already present.
    NORMAL = "normal"
    #: The site served the 509 quota placeholder; images already on disk stay there.
    QUOTA = "quota"
    #: :attr:`CrawlControl.stop` was set (a ban elsewhere or Ctrl+C).
    STOPPED = "stopped"

    def __str__(self) -> str:
        return self.value


def wait_with_progress(seconds: float, reason: str, sleep: Callable[[float], None] = time.sleep) -> None:
    for _ in tqdm(range(round(seconds)), desc=reason, unit="s", ascii=True, leave=False):
        sleep(1)


# --- the gallery list (-c / -u) --------------------------------------------------------


@dataclass
class ListCrawlResult:
    pages: int = 0
    added: int = 0
    updated: int = 0
    reached_known: bool = False


def crawl_list(
    fetcher: Fetcher,
    db: Database,
    start_url: str,
    *,
    update_all: bool,
    sleep: Callable[[float], None] = time.sleep,
) -> ListCrawlResult:
    """Walk the list from ``start_url`` through its "next" links.

    Without ``update_all`` (``-c``) the walk stops at the first gallery older than
    the newest one already stored; with it (``-u``) every page is read again.
    """
    result = ListCrawlResult()
    newest = None if update_all else db.newest_list_time()
    known = db.gallery_ids()
    url: str | None = start_url
    with tqdm(desc="list pages", unit="page", ascii=True) as bar:
        while url is not None:
            try:
                html = fetcher.page(url)
            except BannedError as exc:
                wait = exc.expires_in or DEFAULT_BAN_WAIT
                log.warning("%s; waiting %.0f min before reading the list again", exc, wait / 60)
                wait_with_progress(wait, "banned, waiting", sleep)
                continue
            page = parse_list_page(html, url)
            with db.transaction():
                for entry in page.entries:
                    if newest is not None and entry.posted < newest:
                        log.info("reached galleries already stored (newest: %s); stopping", format_time(newest))
                        result.reached_known = True
                        break
                    if entry.gallery_id in known:
                        db.update_list_entry(entry)
                        result.updated += 1
                    else:
                        db.insert_list_entry(entry)
                        known.add(entry.gallery_id)
                        result.added += 1
            result.pages += 1
            bar.update()
            bar.set_postfix(added=result.added, updated=result.updated)
            if result.reached_known:
                break
            url = page.next_url
    return result


# --- galleries (-p / -to / -cu) --------------------------------------------------------


@dataclass
class DownloadResult:
    total: int
    saved: int = 0
    skipped: int = 0
    failed: int = 0
    #: Why the download loop ended (normal completion, quota placeholder, or an external stop).
    stop_reason: StopReason = StopReason.NORMAL

    @property
    def complete(self) -> bool:
        return self.saved + self.skipped == self.total

    @property
    def quota_exhausted(self) -> bool:
        return self.stop_reason is StopReason.QUOTA

    @property
    def interrupted(self) -> bool:
        """True when the gallery stopped before every image was handled."""
        return self.stop_reason is not StopReason.NORMAL and not self.complete


@dataclass
class GalleryResult:
    gallery_id: int
    info: GalleryInfo
    download: DownloadResult | None = None


def gallery_url(prefix: str, gallery_id: int, url_hash: str) -> str:
    return f"{prefix}{gallery_id}/{url_hash}/"


def gallery_page_url(url: str, page: int) -> str:
    """URL of the ``page``-th thumbnail page of a gallery (``?p=N``)."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(query=urlencode({"p": page})))


def safe_file_name(name: str | None) -> str | None:
    """The site's file name, minus spaces (as the 2019 version saved them) and
    characters no file system accepts."""
    if not name:
        return None
    cleaned = UNSAFE_FILE_CHARS.sub("_", name.replace(" ", "")).strip(". ")
    return cleaned or None


def _fallback_name(thumb: Thumbnail, image_url: str) -> str:
    suffix = Path(urlsplit(image_url).path).suffix
    return f"{thumb.page_number:04d}{suffix}"


def _has_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def galleries_to_crawl(db: Database, *, tag_only: bool) -> list[tuple[int, str]]:
    """``(gallery id, url hash)`` of galleries that need a visit.

    A gallery is due when it was never crawled or the list shows a newer time
    than the last crawl; with downloads on, also when its images are incomplete.
    Galleries marked removed are skipped.
    """
    pages = db.page_rows()
    due: list[tuple[int, str]] = []
    for gid, stored in db.list_rows().items():
        if stored.removed:
            continue
        page = pages.get(gid)
        if (
            page is None
            or stored.entry.posted > parse_time(page.last_update_time)
            or (not tag_only and not page.all_downloaded_check)
        ):
            due.append((gid, stored.entry.url_hash))
    return due


def crawl_gallery(
    fetcher: Fetcher,
    gallery_id: int,
    url: str,
    *,
    image_root: Path,
    tag_only: bool,
    control: CrawlControl,
    show_progress: bool = False,
) -> GalleryResult:
    html = fetcher.page(url)
    skip_warning = content_warning_url(html, url)
    if skip_warning is not None:
        html = fetcher.page(skip_warning)
    info = parse_gallery_info(html)
    if tag_only or control.quota_exceeded.is_set():
        return GalleryResult(gallery_id, info)
    download = _download_images(fetcher, gallery_id, url, html, image_root / str(gallery_id), control, show_progress)
    return GalleryResult(gallery_id, info, download)


def _thumbnails(fetcher: Fetcher, url: str, first_html: str) -> tuple[list[Thumbnail], int]:
    page = parse_thumbnail_page(first_html, url)
    thumbnails, total, last, number = list(page.thumbnails), page.total, page.last, 0
    while last < total:
        number += 1
        page = parse_thumbnail_page(fetcher.page(gallery_page_url(url, number)), url)
        if page.last <= last:
            log.warning("%s: thumbnail page %d did not move past image %d; stopping there", url, number, last)
            break
        thumbnails.extend(page.thumbnails)
        last = page.last
    return thumbnails, total


def _download_images(
    fetcher: Fetcher,
    gallery_id: int,
    url: str,
    first_html: str,
    folder: Path,
    control: CrawlControl,
    show_progress: bool,
) -> DownloadResult:
    thumbnails, total = _thumbnails(fetcher, url, first_html)
    result = DownloadResult(total)
    folder.mkdir(parents=True, exist_ok=True)
    for thumb in tqdm(thumbnails, desc=f"gallery {gallery_id}", unit="img", ascii=True, disable=not show_progress):
        if control.stop.is_set():
            result.stop_reason = StopReason.STOPPED
            log.warning(
                "gallery %s: download stopped at image %d; saved images are kept", gallery_id, thumb.page_number
            )
            break
        if control.quota_exceeded.is_set():
            # Another thread already saw the 509 placeholder: this gallery never gets one of its own.
            result.stop_reason = StopReason.QUOTA
            log.warning("gallery %s: image quota already used up; tags saved, no images downloaded", gallery_id)
            break
        known = safe_file_name(thumb.file_name)
        if known and _has_file(folder / known):
            result.skipped += 1  # resume: already saved, no need to open its page
            continue
        try:
            image = parse_image_page(fetcher.page(thumb.page_url), thumb.page_url)
            if is_quota_placeholder(image.image_url):
                log.warning(
                    "image quota used up at gallery %s, image %d; the remaining galleries get tags only",
                    gallery_id,
                    thumb.page_number,
                )
                control.quota_exceeded.set()
                result.stop_reason = StopReason.QUOTA
                break
            dest = folder / (safe_file_name(image.file_name) or _fallback_name(thumb, image.image_url))
            if _has_file(dest):
                result.skipped += 1
                continue
            fetcher.download(image.image_url, dest)
            result.saved += 1
        except BannedError:
            raise
        except CrawlerError as exc:
            result.failed += 1
            log.warning("gallery %s, image %d: %s", gallery_id, thumb.page_number, exc)
    return result


@dataclass
class GalleryCrawlResult:
    crawled: int = 0
    complete: int = 0
    removed: int = 0
    failed: int = 0
    quota_exceeded: bool = False
    #: Galleries whose image download ended on the 509 quota placeholder, ids ascending.
    quota_stopped: list[int] = field(default_factory=list)
    #: Galleries whose image download ended because CrawlControl.stop was set, ids ascending.
    control_stopped: list[int] = field(default_factory=list)

    def finalize(self, control: CrawlControl) -> GalleryCrawlResult:
        """Sort the per-gallery stop lists and mirror the shared quota flag."""
        self.quota_exceeded = control.quota_exceeded.is_set()
        self.quota_stopped.sort()
        self.control_stopped.sort()
        return self


def crawl_galleries(
    fetcher: Fetcher,
    db: Database,
    settings: Settings,
    *,
    tag_only: bool,
    rng: random.Random | None = None,
) -> GalleryCrawlResult:
    """Visit every gallery that is due, ``NUMBER_OF_THREAD`` at a time, in random order.

    A ban aborts the run (the exception keeps propagating, as before), but the
    galleries that finished after :attr:`CrawlControl.stop` was set are recorded
    first and their ids travel on the exception as
    ``exc.partial_result`` so the caller can still say what was interrupted.
    """
    targets = galleries_to_crawl(db, tag_only=tag_only)
    (rng or random.Random()).shuffle(targets)
    log.info("%d galleries to visit with %d workers", len(targets), settings.number_of_thread)
    control = CrawlControl()
    result = GalleryCrawlResult()
    pool = ThreadPoolExecutor(max_workers=settings.number_of_thread, thread_name_prefix="gallery")
    pending: dict[Future[GalleryResult], int] = {
        pool.submit(
            crawl_gallery,
            fetcher,
            gid,
            gallery_url(settings.gallery_url, gid, url_hash),
            image_root=settings.image_folder_path,
            tag_only=tag_only,
            control=control,
        ): gid
        for gid, url_hash in targets
    }
    recorded: set[Future[GalleryResult]] = set()
    abort: BannedError | None = None
    try:
        with tqdm(total=len(pending), desc="galleries", unit="gallery", ascii=True) as bar:
            for future in as_completed(list(pending)):
                gid = pending[future]
                if abort is not None:
                    break
                try:
                    _record(db, gid, future, result)
                except BannedError as exc:
                    # Stop the remaining workers, but wait out the ones already on the wire:
                    # their STOPPED results are part of the verifiable story of this run.
                    abort = exc
                    control.stop.set()
                    break
                recorded.add(future)
                bar.update()
    except BaseException:
        # Ctrl+C and anything else: behave like the old code - signal the workers,
        # let them wind down, and propagate without touching more database rows.
        control.stop.set()
        pool.shutdown(wait=True, cancel_futures=True)
        raise

    pool.shutdown(wait=True, cancel_futures=True)
    # Normal or ban-aborted finish: every gallery that actually completed gets recorded,
    # so its stop reason is attributable even when the ban fired in another thread.
    for future, gid in pending.items():
        if future in recorded or future.cancelled():
            continue
        try:
            _record(db, gid, future, result)
        except BannedError as exc:
            # The gallery that hit the ban page carries no result; keep the first one.
            abort = abort or exc
        recorded.add(future)
    result.finalize(control)
    if abort is not None:
        abort.partial_result = result
        raise abort
    return result


def _record(db: Database, gid: int, future: Future[GalleryResult], result: GalleryCrawlResult) -> None:
    try:
        gallery = future.result()
    except GalleryUnavailableError:
        log.warning("gallery %s was removed or is unavailable; marking it removed", gid)
        with db.transaction():
            db.mark_removed(gid)
        result.removed += 1
        return
    except BannedError:
        raise
    except CrawlerError as exc:
        log.warning("gallery %s skipped: %s", gid, exc)
        result.failed += 1
        return
    with db.transaction():
        db.save_page_info(gid, gallery.info)
        if gallery.download is not None:
            db.set_downloaded(gid, gallery.download.complete)
    result.crawled += 1
    result.complete += bool(gallery.download and gallery.download.complete)
    download = gallery.download
    if download is not None and download.stop_reason is StopReason.QUOTA:
        result.quota_stopped.append(gid)
    if download is not None and download.stop_reason is StopReason.STOPPED:
        result.control_stopped.append(gid)


def resolve_gallery_url(settings: Settings, url: str) -> tuple[int, str]:
    """Return ``(gallery id, canonical URL)`` for a gallery on one of the configured sites."""
    prefixes = {host_of(prefix): prefix for prefix in (settings.ehentai_gallery, settings.exhentai_gallery)}
    try:
        gallery_id, url_hash = parse_gallery_url(url)
        prefix = prefixes[host_of(url)]
    except (ValueError, KeyError):
        example = gallery_url(settings.exhentai_gallery, 123456, "0123456789")
        raise SettingsError(f"not a gallery URL: {url} (expected something like {example})") from None
    return gallery_id, gallery_url(prefix, gallery_id, url_hash)


def crawl_single(fetcher: Fetcher, settings: Settings, url: str) -> GalleryResult:
    """Download one gallery given by URL (``-cu``); nothing is written to the database."""
    gallery_id, canonical = resolve_gallery_url(settings, url)
    settings.check_access(canonical)
    return crawl_gallery(
        fetcher,
        gallery_id,
        canonical,
        image_root=settings.image_folder_path,
        tag_only=False,
        control=CrawlControl(),
        show_progress=True,
    )
