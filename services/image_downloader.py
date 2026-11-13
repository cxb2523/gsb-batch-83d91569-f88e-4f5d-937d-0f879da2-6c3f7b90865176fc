"""Image download service.

Downloads product images from remote URLs and saves them to the local
``resources/{marketplace}/{sku}/`` directory.

File naming: ``1.jpg``, ``2.webp``, … (1-based, preserving the original
extension; defaults to ``.jpg`` when the extension is unknown or absent).

Already-downloaded files are skipped (idempotent).

Two entry points are provided:

* :func:`download_images` — legacy contract, returns the list of relative
  local paths that were saved or already present (failures are omitted).
* :func:`download_images_detailed` — returns an :class:`ImageDownloadReport`
  with one :class:`ImageDownloadResult` per input URL, in input order,
  describing the per-image outcome (newly downloaded / already present /
  HTTP non-200 / exception) plus aggregate counters.  It also supports
  resuming a partial run: each URL may carry its original 1-based index,
  so re-sending only the previously failed URLs writes the files under
  their original numbers (``3.jpg``) instead of restarting at ``1.jpg``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Sequence, Union

import aiofiles
from curl_cffi.requests.session import AsyncSession
from loguru import logger

# Base directory for downloaded images, relative to the project root.
_RESOURCES_BASE = Path(__file__).parent.parent / "resources"

_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}

# Map response Content-Type → file extension (authoritative over the URL, which
# may say .jpg while the CDN actually returns WebP, e.g. citilink/imgproxy).
_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}

_HEADERS = {
    "accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "accept-language": "ru-RU,ru;q=0.9",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    ),
}


class ImageDownloadStatus(str, Enum):
    """Outcome of a single image download attempt."""

    downloaded = "downloaded"
    skipped = "skipped"
    http_error = "http_error"
    error = "error"


# Human-readable labels (kept in Russian to match project-facing wording;
# the enum values stay English/stable for programmatic use).
_STATUS_LABELS = {
    ImageDownloadStatus.downloaded: "新下载",
    ImageDownloadStatus.skipped: "已存在跳过",
    ImageDownloadStatus.http_error: "HTTP 非 200",
    ImageDownloadStatus.error: "异常",
}


@dataclass
class ImageDownloadResult:
    """Outcome for one input URL, keyed by its 1-based image position."""

    index: int
    url: str
    status: ImageDownloadStatus
    local_path: str | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        """True when the image is available locally (downloaded or skipped)."""
        return self.status in (
            ImageDownloadStatus.downloaded,
            ImageDownloadStatus.skipped,
        )

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "url": self.url,
            "status": self.status.value,
            "status_label": _STATUS_LABELS.get(self.status, self.status.value),
            "local_path": self.local_path,
            "reason": self.reason,
        }


@dataclass
class ImageDownloadReport:
    """Per-image results plus aggregate counters for one download call."""

    results: list[ImageDownloadResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def downloaded_count(self) -> int:
        return sum(1 for r in self.results if r.status == ImageDownloadStatus.downloaded)

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self.results if r.status == ImageDownloadStatus.skipped)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if r.status in (ImageDownloadStatus.http_error, ImageDownloadStatus.error))

    @property
    def success_count(self) -> int:
        """Downloaded + already-present — every record carrying a local path."""
        return sum(1 for r in self.results if r.ok)

    @property
    def local_paths(self) -> list[str]:
        """Relative paths of successful records only; failures never appear."""
        return [r.local_path for r in self.results if r.ok and r.local_path is not None]

    @property
    def failures(self) -> list[ImageDownloadResult]:
        return [r for r in self.results if r.status in (ImageDownloadStatus.http_error, ImageDownloadStatus.error)]

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "downloaded": self.downloaded_count,
            "skipped": self.skipped_count,
            "failed": self.failed_count,
            "success": self.success_count,
            "local_paths": self.local_paths,
            "results": [r.to_dict() for r in self.results],
        }


# A plain URL, or an explicit ``(index, url)`` pair for resuming a run.
ImageInput = Union[str, tuple[int, str]]


def _ext_from_content_type(content_type: str | None) -> str | None:
    """Return the file extension for a response Content-Type, or None."""
    ct = (content_type or "").split(";")[0].strip().lower()
    return _CONTENT_TYPE_EXT.get(ct)


def _safe_name(value: str) -> str:
    """Strip characters that are unsafe in directory / file names."""
    return re.sub(r"[^\w.\-]", "_", value)


def _get_extension(url: str) -> str:
    """Return the lowercase file extension from *url*, falling back to ``.jpg``."""
    path = url.split("?")[0].rstrip("/")
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in _ALLOWED_EXTENSIONS else ".jpg"


def _normalize_image_items(image_urls: Sequence[ImageInput], start_index: int) -> list[tuple[int, str]]:
    """Turn mixed URL / ``(index, url)`` inputs into ordered ``(index, url)``.

    Plain URLs are numbered sequentially from *start_index*; an explicit
    ``(index, url)`` pair pins that image's 1-based file number, which is
    what makes a retry of only the failed URLs land on their original
    positions instead of restarting at ``1``.
    """
    if start_index < 1:
        raise ValueError("start_index must be >= 1 (file numbers are 1-based)")

    items: list[tuple[int, str]] = []
    auto_index = start_index
    for item in image_urls:
        if isinstance(item, str):
            items.append((auto_index, item))
            auto_index += 1
        else:
            index, url = item
            if not isinstance(index, int) or isinstance(index, bool) or index < 1:
                raise ValueError(f"image index must be a positive int, got {index!r}")
            items.append((index, url))
            # Keep the implicit counter after any explicit pin to stay
            # deterministic even if callers mix both input shapes.
            auto_index = max(auto_index, index + 1)
    return items


async def download_images_detailed(
    marketplace: str,
    sku: str,
    image_urls: Sequence[ImageInput],
    start_index: int = 1,
    base_dir: Path | str | None = None,
    session: AsyncSession | None = None,
) -> ImageDownloadReport:
    """Download *image_urls* and report the per-image outcome.

    Behaves exactly like :func:`download_images` — same directory layout,
    same safe-name rules, same Content-Type-based extension inference,
    same idempotent skip of files already on disk — but instead of a bare
    path list it returns an :class:`ImageDownloadReport` containing one
    :class:`ImageDownloadResult` per input, in input order.

    Parameters
    ----------
    image_urls:
        URLs in input order. Each entry is either a plain URL string or an
        explicit ``(index, url)`` pair. On a resume, pass the previously
        failed URLs as pairs (e.g. ``[(3, "https://...")]``) so the file is
        still written as ``3.<ext>`` rather than ``1.<ext>``.
    start_index:
        1-based number assigned to the first plain URL (default ``1``).
    base_dir:
        Override the resources root (mainly for tests); defaults to the
        project's ``resources/`` directory.
    session:
        Optional pre-built ``AsyncSession`` (mainly for tests); when absent a
        Chrome-impersonating session is created and closed by this function.

    A failure on one image (HTTP non-200 or any raised exception) is recorded
    with a reason and never interrupts the remaining downloads.
    """
    report = ImageDownloadReport()
    if not image_urls:
        return report

    items = _normalize_image_items(image_urls, start_index)

    resources_root = Path(base_dir) if base_dir is not None else _RESOURCES_BASE
    project_root = resources_root.parent
    target_dir = resources_root / _safe_name(marketplace) / _safe_name(sku)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Per-source download context: some marketplaces (e.g. citilink) serve images
    # from an anti-bot CDN that needs browser-seeded cookies + a referer + proxy.
    headers = dict(_HEADERS)
    cookies = None
    proxy = None
    try:
        from crawlers.registry import CrawlerRegistry  # noqa: PLC0415

        crawler = CrawlerRegistry.get(marketplace)()
        if hasattr(crawler, "download_context"):
            ctx = await crawler.download_context() or {}
            headers.update(ctx.get("headers") or {})
            cookies = ctx.get("cookies") or None
            proxy = ctx.get("proxy") or None
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"No download context for {marketplace}: {exc}")

    async def _run(sess: AsyncSession) -> None:
        for index, url in items:
            # Idempotency: skip if any "{index}.<ext>" already exists (the
            # extension is decided from Content-Type, so glob across extensions).
            existing = sorted(target_dir.glob(f"{index}.*"))
            if existing:
                rel_path = str(existing[0].relative_to(project_root))
                logger.debug(f"Image already exists, skipping: {rel_path}")
                report.results.append(
                    ImageDownloadResult(
                        index=index,
                        url=url,
                        status=ImageDownloadStatus.skipped,
                        local_path=rel_path,
                    )
                )
                continue

            try:
                response = await sess.get(url, headers=headers, cookies=cookies, proxy=proxy, timeout=30)
                if response.status_code != 200:
                    reason = f"HTTP {response.status_code}"
                    logger.warning(f"Image download {reason} for {url}")
                    report.results.append(
                        ImageDownloadResult(
                            index=index,
                            url=url,
                            status=ImageDownloadStatus.http_error,
                            reason=reason,
                        )
                    )
                    continue

                ext = _ext_from_content_type(response.headers.get("content-type")) or _get_extension(url)
                filepath = target_dir / f"{index}{ext}"
                rel_path = str(filepath.relative_to(project_root))

                async with aiofiles.open(filepath, "wb") as fh:
                    await fh.write(response.content)

                report.results.append(
                    ImageDownloadResult(
                        index=index,
                        url=url,
                        status=ImageDownloadStatus.downloaded,
                        local_path=rel_path,
                    )
                )
                logger.debug(f"Image saved: {rel_path}")

            except Exception as exc:  # noqa: BLE001
                reason = f"{type(exc).__name__}: {exc}"
                logger.warning(f"Failed to download image {url}: {exc}")
                report.results.append(
                    ImageDownloadResult(
                        index=index,
                        url=url,
                        status=ImageDownloadStatus.error,
                        reason=reason,
                    )
                )

    if session is not None:
        await _run(session)
    else:
        async with AsyncSession(impersonate="chrome136") as owned_session:
            await _run(owned_session)

    logger.info(
        f"Images for {marketplace}/{sku}: "
        f"{report.success_count}/{report.total} available "
        f"({report.downloaded_count} new, {report.skipped_count} skipped, "
        f"{report.failed_count} failed) → {target_dir}"
    )
    return report


async def download_images(
    marketplace: str,
    sku: str,
    image_urls: list[str],
) -> list[str]:
    """Download *image_urls* and save them under ``resources/{marketplace}/{sku}/``.

    Returns a list of relative local paths for every successfully saved file.
    Already-present files are included in the result without re-downloading.
    Failed URLs (HTTP non-200 or exceptions) are simply absent from the list;
    use :func:`download_images_detailed` when per-image outcomes and failure
    reasons are needed.
    """
    if not image_urls:
        return []

    report = await download_images_detailed(marketplace, sku, image_urls)
    return report.local_paths
