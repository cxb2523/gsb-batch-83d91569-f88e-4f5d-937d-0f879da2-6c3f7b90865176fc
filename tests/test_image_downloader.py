"""Tests for the per-image detailed image-download entry point.

The network layer is replaced by a small in-memory fake session, so no real
HTTP traffic is produced: each URL is mapped to either a 200 response with a
tiny payload, a non-200 response, or a raised exception.
"""

from __future__ import annotations

import asyncio

import pytest

from services.image_downloader import (
    ImageDownloadReport,
    ImageDownloadResult,
    ImageDownloadStatus,
    _safe_name,
    download_images,
    download_images_detailed,
)


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"", content_type: str | None = None):
        self.status_code = status_code
        self.content = content
        self.headers = {"content-type": content_type} if content_type else {}


class FakeSession:
    """Stand-in for curl_cffi's AsyncSession used by the downloader.

    ``routes`` maps a URL to either an ``_FakeResponse`` or an Exception
    instance/type that ``get`` should raise.
    """

    def __init__(self, routes: dict):
        self.routes = routes
        self.requested_urls: list[str] = []

    async def get(self, url, **kwargs):
        self.requested_urls.append(url)
        outcome = self.routes[url]
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, type) and issubclass(outcome, BaseException):
            raise outcome("simulated failure")
        return outcome

    # AsyncSession is normally used as an async context manager; the detailed
    # entry point receives this instance directly, but keep the protocol shape.
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


URLS = [
    "https://cdn.example.com/a.jpg",
    "https://cdn.example.com/b.png",
    "https://cdn.example.com/c.webp",
    "https://cdn.example.com/d.gif",
]


def _routes():
    return {
        URLS[0]: _FakeResponse(200, b"aaa", "image/jpeg"),
        URLS[1]: _FakeResponse(404),
        URLS[2]: _FakeResponse(200, b"ccc", "image/webp"),
        URLS[3]: RuntimeError("connection reset"),
    }


@pytest.mark.asyncio
async def test_detailed_mixed_outcomes_order_and_counts(tmp_path):
    session = FakeSession(_routes())

    report = await download_images_detailed("fake-mp", "sku-1", URLS, base_dir=tmp_path, session=session)

    assert isinstance(report, ImageDownloadReport)
    assert report.total == 4
    assert report.downloaded_count == 2
    assert report.skipped_count == 0
    assert report.failed_count == 2
    assert report.success_count == 2

    # One record per URL, strictly in input order, with original indices.
    assert [r.index for r in report.results] == [1, 2, 3, 4]
    assert [r.url for r in report.results] == URLS
    assert [r.status for r in report.results] == [
        ImageDownloadStatus.downloaded,
        ImageDownloadStatus.http_error,
        ImageDownloadStatus.downloaded,
        ImageDownloadStatus.error,
    ]

    # Failures carry reasons and no local path; successes carry a path.
    assert report.results[1].reason == "HTTP 404"
    assert report.results[1].local_path is None
    assert report.results[3].reason and "connection reset" in report.results[3].reason
    assert report.results[3].local_path is None
    assert report.results[0].ok and report.results[2].ok
    assert not report.results[1].ok and not report.results[3].ok

    # The success list never contains failed records.
    assert report.local_paths == [r.local_path for r in report.results if r.ok]
    assert len(report.local_paths) == 2
    assert all(r.local_path not in report.local_paths for r in report.failures)

    # Files actually landed on disk with Content-Type-inferred extensions.
    target = tmp_path / "fake-mp" / "sku-1"
    assert (target / "1.jpg").read_bytes() == b"aaa"
    assert (target / "3.webp").read_bytes() == b"ccc"
    assert not (target / "2.png").exists()
    assert not (target / "4.gif").exists()


@pytest.mark.asyncio
async def test_detailed_existing_files_are_skipped_without_request(tmp_path):
    session = FakeSession(_routes())
    target = tmp_path / "fake-mp" / "sku-1"
    target.mkdir(parents=True)
    # Simulate a file from a previous successful run at position 1.
    (target / "1.jpg").write_bytes(b"old")

    report = await download_images_detailed("fake-mp", "sku-1", URLS, base_dir=tmp_path, session=session)

    skipped = report.results[0]
    assert skipped.status == ImageDownloadStatus.skipped
    assert skipped.ok
    assert skipped.local_path and skipped.local_path.replace("\\", "/").endswith("fake-mp/sku-1/1.jpg")
    # Existing file is counted as success but never re-requested.
    assert URLS[0] not in session.requested_urls
    assert (target / "1.jpg").read_bytes() == b"old"
    assert report.skipped_count == 1
    assert report.downloaded_count == 1
    assert report.success_count == 2
    assert report.failed_count == 2


@pytest.mark.asyncio
async def test_legacy_download_images_keeps_path_list_contract(tmp_path, monkeypatch):
    import services.image_downloader as mod

    captured = {}

    async def fake_detailed(marketplace, sku, image_urls, **kwargs):
        captured["args"] = (marketplace, sku, image_urls)
        return await download_images_detailed(
            marketplace, sku, image_urls, base_dir=tmp_path, session=FakeSession(_routes())
        )

    monkeypatch.setattr(mod, "download_images_detailed", fake_detailed)

    paths = await download_images("fake-mp", "sku-2", URLS)

    # Same call shape as before; only successful relative paths come back.
    assert captured["args"] == ("fake-mp", "sku-2", URLS)
    assert isinstance(paths, list)
    assert len(paths) == 2
    assert all(isinstance(p, str) for p in paths)
    assert all("fake-mp" in p and "sku-2" in p for p in paths)

    # Empty input still short-circuits to an empty list.
    assert await download_images("fake-mp", "sku-2", []) == []


@pytest.mark.asyncio
async def test_resume_failed_urls_lands_on_original_indices(tmp_path):
    session = FakeSession(_routes())

    # First run: URLs at positions 2 (HTTP 404) and 4 (exception) fail.
    first = await download_images_detailed("fake-mp", "sku-3", URLS, base_dir=tmp_path, session=session)
    failed = first.failures
    assert [r.index for r in failed] == [2, 4]

    # The CDN recovers: retry only the failed URLs, pinning their original
    # positions via (index, url) pairs.
    retry_routes = {
        URLS[1]: _FakeResponse(200, b"bbb", "image/png"),
        URLS[3]: _FakeResponse(200, b"ddd", "image/gif"),
    }
    retry_session = FakeSession(retry_routes)
    retry_inputs = [(r.index, r.url) for r in failed]

    second = await download_images_detailed("fake-mp", "sku-3", retry_inputs, base_dir=tmp_path, session=retry_session)

    assert [r.index for r in second.results] == [2, 4]
    assert all(r.status == ImageDownloadStatus.downloaded for r in second.results)
    assert second.failed_count == 0
    assert second.downloaded_count == 2

    target = tmp_path / "fake-mp" / "sku-3"
    # Retried files keep their original numbers — nothing was written as 1.jpg,
    # and the first run's files are untouched.
    assert (target / "2.png").read_bytes() == b"bbb"
    assert (target / "4.gif").read_bytes() == b"ddd"
    assert (target / "1.jpg").read_bytes() == b"aaa"
    assert (target / "3.webp").read_bytes() == b"ccc"
    assert sorted(p.name for p in target.iterdir()) == [
        "1.jpg",
        "2.png",
        "3.webp",
        "4.gif",
    ]


@pytest.mark.asyncio
async def test_start_index_numbers_plain_urls(tmp_path):
    routes = {
        "https://cdn.example.com/x.jpg": _FakeResponse(200, b"x", "image/jpeg"),
        "https://cdn.example.com/y.jpg": _FakeResponse(200, b"y", "image/jpeg"),
    }
    report = await download_images_detailed(
        "fake-mp",
        "sku-4",
        ["https://cdn.example.com/x.jpg", "https://cdn.example.com/y.jpg"],
        start_index=5,
        base_dir=tmp_path,
        session=FakeSession(routes),
    )

    assert [r.index for r in report.results] == [5, 6]
    target = tmp_path / "fake-mp" / "sku-4"
    assert (target / "5.jpg").exists()
    assert (target / "6.jpg").exists()


@pytest.mark.asyncio
async def test_single_failure_does_not_stop_remaining_downloads(tmp_path):
    # Every URL fails: the loop must still produce one record per URL.
    routes = {url: RuntimeError("boom") for url in URLS}
    report = await download_images_detailed("fake-mp", "sku-5", URLS, base_dir=tmp_path, session=FakeSession(routes))

    assert report.total == 4
    assert report.failed_count == 4
    assert report.success_count == 0
    assert report.local_paths == []
    assert all(r.status == ImageDownloadStatus.error for r in report.results)
    assert all("RuntimeError" in (r.reason or "") for r in report.results)
    target = tmp_path / "fake-mp" / "sku-5"
    # The target directory exists (it is created up front) but holds no files.
    assert target.is_dir()
    assert list(target.iterdir()) == []


@pytest.mark.asyncio
async def test_content_type_overrides_url_extension(tmp_path):
    routes = {
        # URL says .jpg but the CDN actually serves WebP.
        "https://cdn.example.com/misleading.jpg": _FakeResponse(200, b"webp-bytes", "image/webp"),
    }
    report = await download_images_detailed(
        "fake-mp",
        "sku-6",
        ["https://cdn.example.com/misleading.jpg"],
        base_dir=tmp_path,
        session=FakeSession(routes),
    )

    target = tmp_path / "fake-mp" / "sku-6"
    assert (target / "1.webp").exists()
    assert not (target / "1.jpg").exists()
    assert report.results[0].local_path.replace("\\", "/").endswith("fake-mp/sku-6/1.webp")


@pytest.mark.asyncio
async def test_safe_name_rules_applied_to_directories(tmp_path):
    routes = {
        "https://cdn.example.com/a.jpg": _FakeResponse(200, b"a", "image/jpeg"),
    }
    report = await download_images_detailed(
        "маркет/place",
        "SKU 123!",
        ["https://cdn.example.com/a.jpg"],
        base_dir=tmp_path,
        session=FakeSession(routes),
    )

    result = report.results[0]
    safe_dir = tmp_path / _safe_name("маркет/place") / _safe_name("SKU 123!")
    assert safe_dir.exists()
    assert (safe_dir / "1.jpg").exists()
    assert result.local_path


@pytest.mark.asyncio
async def test_invalid_indices_rejected(tmp_path):
    with pytest.raises(ValueError):
        await download_images_detailed(
            "fake-mp",
            "sku-7",
            [(0, "https://cdn.example.com/a.jpg")],
            base_dir=tmp_path,
            session=FakeSession({}),
        )

    with pytest.raises(ValueError):
        await download_images_detailed(
            "fake-mp",
            "sku-7",
            ["https://cdn.example.com/a.jpg"],
            start_index=0,
            base_dir=tmp_path,
            session=FakeSession({}),
        )


def test_report_and_result_serialization_shapes():
    result = ImageDownloadResult(
        index=2,
        url="https://cdn.example.com/b.png",
        status=ImageDownloadStatus.http_error,
        reason="HTTP 503",
    )
    payload = result.to_dict()
    assert payload == {
        "index": 2,
        "url": "https://cdn.example.com/b.png",
        "status": "http_error",
        "status_label": "HTTP 非 200",
        "local_path": None,
        "reason": "HTTP 503",
    }

    report = ImageDownloadReport(
        results=[
            ImageDownloadResult(
                index=1,
                url="https://cdn.example.com/a.jpg",
                status=ImageDownloadStatus.downloaded,
                local_path="resources/fake-mp/sku/1.jpg",
            ),
            result,
        ]
    )
    data = report.to_dict()
    assert data["total"] == 2
    assert data["downloaded"] == 1
    assert data["skipped"] == 0
    assert data["failed"] == 1
    assert data["success"] == 1
    assert data["local_paths"] == ["resources/fake-mp/sku/1.jpg"]
    assert len(data["results"]) == 2


@pytest.mark.asyncio
async def test_empty_input_returns_empty_report(tmp_path):
    report = await download_images_detailed("fake-mp", "sku-8", [], base_dir=tmp_path, session=FakeSession({}))
    assert report.total == 0
    assert report.local_paths == []
    assert report.failures == []
    # No directory tree created for empty input.
    assert not (tmp_path / "fake-mp").exists()


@pytest.mark.asyncio
async def test_legacy_runner_uses_real_session_when_none_injected(tmp_path):
    # Guards the session-ownership branch: without an injected session the
    # function builds its own AsyncSession. Patch the class at the import site
    # so no real network/socket is created.
    import services.image_downloader as mod

    class _NoopSession:
        def __init__(self, *args, **kwargs):
            self.entries = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            await asyncio.sleep(0)
            return _FakeResponse(200, b"z", "image/jpeg")

    original = mod.AsyncSession
    mod.AsyncSession = _NoopSession
    try:
        report = await download_images_detailed(
            "fake-mp",
            "sku-9",
            ["https://cdn.example.com/z.jpg"],
            base_dir=tmp_path,
        )
    finally:
        mod.AsyncSession = original

    assert report.downloaded_count == 1
    assert (tmp_path / "fake-mp" / "sku-9" / "1.jpg").exists()
