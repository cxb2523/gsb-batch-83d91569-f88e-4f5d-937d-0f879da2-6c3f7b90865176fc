"""Offline tests for the auditable resume conclusion produced by download_raw.

Every transport in this module is a hand-built fake; no real network access is
performed.  All downloaded data is generated into per-test temporary directories.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
from pathlib import Path

import pytest

from base_api import RawOutcome
from base_api.modules.config import DownloadConfigRAW
from base_api.modules.errors import DownloadCancelled, NetworkRequestError
from base_api.modules.raw_download import download_raw

URL = "https://cdn.test/video.bin"
ETAG = '"etag-v1"'
LAST_MODIFIED = "Wed, 21 Oct 2025 07:28:00 GMT"


class FakeResponse:
    """Minimal stand-in for a curl_cffi streaming response."""

    def __init__(self, status_code, headers, payload=b"", stream_chunk=4, content_range=None):
        self.status_code = status_code
        self.headers = headers
        self.url = URL
        self._payload = payload
        self._stream_chunk = stream_chunk
        self._content_range = content_range
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise NetworkRequestError(f"HTTP {self.status_code}")

    async def aclose(self):
        self.closed = True

    async def aiter_content(self):
        if self.status_code == 206 and self._content_range is not None:
            start, end = self._content_range
            data = self._payload[start:end + 1]
        else:
            data = self._payload
        for index in range(0, len(data), self._stream_chunk):
            await asyncio.sleep(0)
            yield data[index:index + self._stream_chunk]


class FakeSession:
    """Session fake recording the request headers each call receives."""

    def __init__(self, payload, *, head_error=None, get_error=None, force_200_on_range=False,
                 response_override=None):
        self.payload = payload
        self.head_error = head_error
        self.get_error = get_error
        self.force_200_on_range = force_200_on_range
        self.response_override = response_override
        self.requests: list[dict] = []

    async def head(self, url, **kwargs):
        if self.head_error is not None:
            raise self.head_error
        return FakeResponse(
            200,
            {"Content-Length": str(len(self.payload)), "Accept-Ranges": "bytes",
             "ETag": ETAG, "Last-Modified": LAST_MODIFIED},
        )

    async def request(self, method, url, *, headers=None, stream=False, **kwargs):
        headers = headers or {}
        self.requests.append({"method": method, "headers": dict(headers)})
        if self.get_error is not None:
            raise self.get_error
        if self.response_override is not None:
            return self.response_override
        range_header = headers.get("Range")
        if range_header and not self.force_200_on_range:
            text = range_header.removeprefix("bytes=")
            start_text, end_text = text.split("-")
            start = int(start_text)
            end = int(end_text) if end_text else len(self.payload) - 1
            return FakeResponse(
                206,
                {"Content-Range": f"bytes {start}-{end}/{len(self.payload)}",
                 "Content-Length": str(end - start + 1),
                 "ETag": ETAG, "Last-Modified": LAST_MODIFIED},
                payload=self.payload, content_range=(start, end),
            )
        return FakeResponse(
            200,
            {"Content-Length": str(len(self.payload)), "ETag": ETAG,
             "Last-Modified": LAST_MODIFIED},
            payload=self.payload,
        )


class FakeCore:
    def __init__(self, session):
        self.session = session
        self.logger = logging.getLogger("tests.raw_download")

    def initialize_session(self):
        # The fake session is already "open"; keep the real initializer out of the test.
        return None


def expected_width(size: int, configured_chunk_size: int) -> int:
    return max(configured_chunk_size, min(10 * 1024 * 1024, max(1, size // 10)))


def write_checkpoint(path: Path, output: Path, *, mode, size, chunk_size, progress,
                     etag=ETAG, last_modified=LAST_MODIFIED):
    payload = {
        "version": 1,
        "source": hashlib.sha256(URL.encode()).hexdigest(),
        "output": str(output.resolve()),
        "mode": mode,
        "size": size,
        "chunk_size": chunk_size,
        "progress": progress,
        "etag": etag,
        "last_modified": last_modified,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_config(tmp_path: Path, **overrides) -> DownloadConfigRAW:
    output = tmp_path / "video.bin"
    config = DownloadConfigRAW(
        quality="best",
        path=str(output),
        resume_state_path=str(tmp_path / "video.bin.raw-state.json"),
        max_retries=0,
        read_timeout=5.0,
        **overrides,
    )
    return config


@pytest.mark.asyncio
async def test_fresh_multipart_download_records_fresh_conclusion(tmp_path):
    payload = bytes(range(256)) * 10  # 2560 bytes -> several multipart ranges
    session = FakeSession(payload)
    core = FakeCore(session)
    config = make_config(tmp_path, allow_multipart=True, max_workers=3)

    result = await download_raw(core, URL, config)

    assert result is True  # existing boolean behaviour is preserved
    conclusion = config.download_conclusion
    assert conclusion is not None
    assert conclusion.outcome == RawOutcome.FRESH
    assert conclusion.mode == "multipart"
    assert conclusion.reused_progress is False
    assert conclusion.retained_bytes == 0
    assert conclusion.total_bytes == len(payload)
    assert conclusion.failed is False
    assert Path(conclusion.output_path).read_bytes() == payload
    # A finished download removes its checkpoint.
    assert not Path(config.resume_state_path).exists()
    # Multipart mode always fetches explicit byte ranges, first one from zero.
    range_headers = [request["headers"]["Range"] for request in session.requests]
    assert range_headers
    assert all(header.startswith("bytes=") for header in range_headers)
    assert range_headers[0].startswith("bytes=0-")


@pytest.mark.asyncio
async def test_resumed_multipart_download_reuses_saved_progress(tmp_path):
    payload = bytes(range(256)) * 10
    width = expected_width(len(payload), 1024)
    output = tmp_path / "video.bin"
    checkpoint = tmp_path / "video.bin.raw-state.json"
    # First range fully retained, second range half retained, rest untouched.
    partial = bytearray(len(payload))
    partial[:width] = payload[:width]
    partial[width:width + width // 2] = payload[width:width + width // 2]
    output.write_bytes(bytes(partial))
    retained = width + width // 2
    write_checkpoint(
        checkpoint, output, mode="multipart", size=len(payload), chunk_size=width,
        progress=[width, width // 2] + [0] * (math.ceil(len(payload) / width) - 2),
    )

    session = FakeSession(payload)
    core = FakeCore(session)
    config = make_config(tmp_path, allow_multipart=True, max_workers=2)

    assert await download_raw(core, URL, config) is True

    conclusion = config.download_conclusion
    assert conclusion.outcome == RawOutcome.RESUMED
    assert conclusion.mode == "multipart"
    assert conclusion.reused_progress is True
    assert conclusion.retained_bytes == retained
    assert conclusion.total_bytes == len(payload)
    assert conclusion.failed is False
    assert output.read_bytes() == payload
    assert not checkpoint.exists()
    # No request may re-fetch bytes below the retained offset of its range.
    range_requests = [request["headers"]["Range"] for request in session.requests
                      if "Range" in request["headers"]]
    assert range_requests
    assert any(range_header.startswith(f"bytes={width + width // 2}-") for range_header in range_requests)
    # The fully retained first range must never be requested again.
    assert not any(range_header.startswith(f"bytes=0-") for range_header in range_requests)


@pytest.mark.asyncio
async def test_changed_validator_discards_progress_and_restarts(tmp_path):
    payload = b"0123456789ABCDEF" * 8
    output = tmp_path / "video.bin"
    checkpoint = tmp_path / "video.bin.raw-state.json"
    output.write_bytes(payload[:40])
    write_checkpoint(
        checkpoint, output, mode="linear", size=len(payload), chunk_size=1024, progress=[40],
        etag='"stale-etag"', last_modified=LAST_MODIFIED,
    )

    # HEAD now answers with a different ETag, so the checkpoint must be rejected.
    session = FakeSession(payload)
    core = FakeCore(session)
    config = make_config(tmp_path, allow_multipart=False)

    assert await download_raw(core, URL, config) is True

    conclusion = config.download_conclusion
    assert conclusion.outcome == RawOutcome.VALIDATOR_MISMATCH
    assert conclusion.mode == "linear"
    assert conclusion.reused_progress is False
    assert conclusion.retained_bytes == 0
    assert conclusion.total_bytes == len(payload)
    assert output.read_bytes() == payload
    assert not checkpoint.exists()
    # The restart must request from byte zero, never from the old offset 40.
    assert all(request["headers"].get("Range") is None for request in session.requests)


@pytest.mark.asyncio
async def test_server_ignoring_range_forces_linear_redownload(tmp_path):
    payload = b"linear-resume-payload" * 4
    output = tmp_path / "video.bin"
    checkpoint = tmp_path / "video.bin.raw-state.json"
    output.write_bytes(payload[:20])
    write_checkpoint(
        checkpoint, output, mode="linear", size=len(payload), chunk_size=1024, progress=[20],
    )

    session = FakeSession(payload, force_200_on_range=True)
    core = FakeCore(session)
    config = make_config(tmp_path, allow_multipart=False)

    assert await download_raw(core, URL, config) is True

    conclusion = config.download_conclusion
    assert conclusion.outcome == RawOutcome.RANGE_IGNORED
    assert conclusion.mode == "linear"
    assert conclusion.reused_progress is False
    # The bytes kept before the run are still reported, even though they were overwritten.
    assert conclusion.retained_bytes == 20
    assert conclusion.total_bytes == len(payload)
    assert conclusion.failed is False
    assert output.read_bytes() == payload
    # The client did ask for a resume first; the server answered with the whole body.
    assert any(request["headers"].get("Range") == "bytes=20-" for request in session.requests)
    assert not checkpoint.exists()


@pytest.mark.asyncio
async def test_stop_signal_cancels_multipart_with_cancelled_conclusion(tmp_path):
    payload = bytes(range(256)) * 8
    stop = asyncio.Event()

    class StoppingResponse(FakeResponse):
        async def aiter_content(self):
            stop.set()  # signal cancellation as soon as the first bytes flow
            async for chunk in super().aiter_content():
                yield chunk

    class CancellingSession(FakeSession):
        async def request(self, method, url, *, headers=None, stream=False, **kwargs):
            headers = headers or {}
            self.requests.append({"method": method, "headers": dict(headers)})
            start_text, end_text = headers["Range"].removeprefix("bytes=").split("-")
            start, end = int(start_text), int(end_text)
            return StoppingResponse(
                206,
                {"Content-Range": f"bytes {start}-{end}/{len(self.payload)}",
                 "Content-Length": str(end - start + 1),
                 "ETag": ETAG, "Last-Modified": LAST_MODIFIED},
                payload=self.payload, content_range=(start, end),
            )

    session = CancellingSession(payload)
    core = FakeCore(session)
    config = make_config(tmp_path, allow_multipart=True, max_workers=1, stop_event=stop)

    with pytest.raises(DownloadCancelled):
        await download_raw(core, URL, config)

    conclusion = config.download_conclusion
    assert conclusion.outcome == RawOutcome.CANCELLED
    assert conclusion.mode == "multipart"
    assert conclusion.reused_progress is False
    assert conclusion.failed is False  # cancellation is not a failure
    # The partial transfer remains on disk so a later run can resume it.
    assert Path(config.resume_state_path).exists()


@pytest.mark.asyncio
async def test_preset_stop_event_cancels_before_any_request(tmp_path):
    stop = asyncio.Event()
    stop.set()
    session = FakeSession(b"")
    core = FakeCore(session)
    config = make_config(tmp_path, stop_event=stop)

    with pytest.raises(DownloadCancelled):
        await download_raw(core, URL, config)

    conclusion = config.download_conclusion
    assert conclusion.outcome == RawOutcome.CANCELLED
    assert conclusion.failed is False
    assert session.requests == []


@pytest.mark.asyncio
async def test_head_failure_with_checkpoint_fails_without_fallback(tmp_path):
    payload = b"unreachable-payload"
    output = tmp_path / "video.bin"
    checkpoint = tmp_path / "video.bin.raw-state.json"
    output.write_bytes(payload[:5])
    write_checkpoint(
        checkpoint, output, mode="linear", size=len(payload), chunk_size=1024, progress=[5],
    )

    session = FakeSession(payload, head_error=ConnectionError("network down"))
    core = FakeCore(session)
    config = make_config(tmp_path)

    with pytest.raises(ConnectionError):
        await download_raw(core, URL, config)

    conclusion = config.download_conclusion
    # Must be flagged as a failure, never masquerade as a fresh start.
    assert conclusion.outcome == RawOutcome.METADATA_FAILED
    assert conclusion.failed is True
    assert conclusion.outcome != RawOutcome.FRESH
    assert "network down" in conclusion.error
    # Strict behaviour: the persisted partial download and checkpoint stay untouched.
    assert output.read_bytes() == payload[:5]
    assert checkpoint.exists()
    assert session.requests == []


@pytest.mark.asyncio
async def test_head_failure_without_checkpoint_falls_back_to_linear(tmp_path):
    payload = b"metadata was unavailable but the body streams fine"

    class NoHeadSession(FakeSession):
        async def head(self, url, **kwargs):
            raise ConnectionError("metadata endpoint down")

    session = NoHeadSession(payload)
    core = FakeCore(session)
    config = make_config(tmp_path, allow_multipart=True)  # multipart cannot be chosen without metadata

    assert await download_raw(core, URL, config) is True

    conclusion = config.download_conclusion
    assert conclusion.outcome == RawOutcome.FRESH
    assert conclusion.mode == "linear"
    assert conclusion.failed is False
    assert Path(conclusion.output_path).read_bytes() == payload
    assert not Path(config.resume_state_path).exists()


@pytest.mark.asyncio
async def test_conclusion_exposes_machine_readable_dict(tmp_path):
    payload = b"abcdefgh"
    core = FakeCore(FakeSession(payload))
    config = make_config(tmp_path, allow_multipart=False)

    await download_raw(core, URL, config)

    report = config.download_conclusion.as_dict()
    assert report == {
        "output_path": str((tmp_path / "video.bin").resolve()),
        "mode": "linear",
        "reused_progress": False,
        "retained_bytes": 0,
        "total_bytes": len(payload),
        "outcome": RawOutcome.FRESH,
        "error": None,
    }


@pytest.mark.asyncio
async def test_short_linear_stream_records_incomplete_conclusion(tmp_path):
    payload = b"complete-payload-here"
    output = tmp_path / "video.bin"
    checkpoint = tmp_path / "video.bin.raw-state.json"

    class ShortResponse(FakeResponse):
        async def aiter_content(self):
            yield self._payload[:7]  # fewer bytes than the advertised Content-Length

    session = FakeSession(payload, response_override=ShortResponse(
        200, {"Content-Length": str(len(payload)), "ETag": ETAG, "Last-Modified": LAST_MODIFIED},
        payload=payload,
    ))
    core = FakeCore(session)
    config = make_config(tmp_path, allow_multipart=False)

    with pytest.raises(NetworkRequestError):
        await download_raw(core, URL, config)

    conclusion = config.download_conclusion
    assert conclusion.outcome == RawOutcome.INCOMPLETE
    assert conclusion.mode == "linear"
    assert conclusion.failed is True
    assert conclusion.reused_progress is False
    assert conclusion.total_bytes == len(payload)
    assert checkpoint.exists()
