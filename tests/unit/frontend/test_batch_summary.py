"""
Tests for batch result summaries (``batches.create_summary`` / ``Batch.summary``).

Every test uses a local fake transport, so no API key and no network access is
required. The fake transport only implements the three batch endpoints plus
retrieve, and every response is built from fixtures in this module.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from olostep.backend.transport_protocol import RawAPIRequest, RawAPIResponse, Transport
from olostep.clients.async_client import AsyncOlostep
from olostep.clients.sync_client import Olostep
from olostep.errors import OlostepClientError_BatchItemFailed
from olostep.frontend.client_state import BatchSummary, BatchSummaryItem

BATCH_ID = "batch_summary_1"


def _create_body(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": BATCH_ID,
        "object": "batch",
        "status": "in_progress",
        "created": 1,
        "total_urls": len(items),
        "completed_urls": 0,
        "number_retried": 0,
        "parser": None,
        "start_date": "2024-01-01T00:00:00Z",
    }


def _info_body(status: str = "completed", total: int = 0, completed: int = 0) -> dict[str, Any]:
    return {
        "id": BATCH_ID,
        "object": "batch",
        "status": status,
        "created": 1,
        "total_urls": total,
        "completed_urls": completed,
        "number_retried": 0,
        "parser": None,
        "start_date": "2024-01-01T00:00:00Z",
    }


class BatchSummaryFakeTransport(Transport):
    """Deterministic in-memory transport for batch summary tests.

    Implements only:
    - ``POST /batches``
    - ``GET /batches/{id}``
    - ``GET /batches/{id}/items`` (single page unless ``pages`` is supplied)
    - ``GET /retrieve``

    Item dictionaries are returned verbatim so tests can model API quirks such
    as extra error fields or missing ``retrieve_id`` values.
    """

    def __init__(
        self,
        items: list[dict[str, Any]],
        *,
        pages: list[list[dict[str, Any]]] | None = None,
        final_status: str = "completed",
        info_statuses: list[str] | None = None,
        create_error: dict[str, Any] | None = None,
    ) -> None:
        self.items = items
        self.pages = pages
        self.final_status = final_status
        self.info_statuses = list(info_statuses or [])
        self.create_error = create_error
        self.requests: list[RawAPIRequest] = []
        self._create_items: list[dict[str, Any]] = []
        self._page_index = 0
        self.info_index = 0

    async def request(self, request: RawAPIRequest) -> RawAPIResponse:
        # Model an async I/O boundary so event-loop blocking would be visible.
        await asyncio.sleep(0)
        self.requests.append(request)
        path = request.url.split("://", 1)[-1].split("/v1", 1)[-1] if "://" in request.url else request.url
        # Normalise to the interesting suffixes regardless of base URL.
        if request.method == "POST" and path.rstrip("/").endswith("/batches"):
            if self.create_error is not None:
                return RawAPIResponse(
                    status_code=self.create_error.get("status", 500),
                    headers={},
                    body=json.dumps(self.create_error.get("body", {})),
                )
            self._create_items = list((request.json or {}).get("items", []))
            return RawAPIResponse(
                status_code=200, headers={}, body=json.dumps(_create_body(self._create_items))
            )

        if request.method == "GET" and path.rstrip("/").endswith("/items"):
            if self.pages is not None:
                page = self.pages[self._page_index]
                cursor = self._page_index + 1 if self._page_index < len(self.pages) - 1 else None
                self._page_index += 1
            else:
                page = self.items
                cursor = None
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=json.dumps(
                    {
                        "id": BATCH_ID,
                        "object": "batch",
                        "status": "completed",
                        "items": page,
                        "items_count": len(page),
                        "cursor": cursor,
                    }
                ),
            )

        if request.method == "GET" and "/batches/" in path:
            # Optionally report a non-terminal status first, then become terminal,
            # so tests can exercise polling without hanging.
            if self.info_index < len(self.info_statuses):
                status = self.info_statuses[self.info_index]
                self.info_index += 1
            else:
                status = self.final_status
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=json.dumps(
                    _info_body(
                        status=status,
                        total=len(self._create_items),
                        completed=len(self._create_items),
                    )
                ),
            )

        if request.method == "GET" and path.rstrip("/").endswith("/retrieve"):
            retrieve_id = (request.query or {}).get("retrieve_id")
            formats = (request.query or {}).get("formats") or []
            body: dict[str, Any] = {"size_exceeded": False}
            if "html" in formats or not formats:
                body["html_content"] = f"<html>{retrieve_id}</html>"
            if "markdown" in formats or not formats:
                body["markdown_content"] = f"# {retrieve_id}"
            return RawAPIResponse(status_code=200, headers={}, body=json.dumps(body))

        raise AssertionError(f"Unhandled fake request: {request.method} {request.url}")

    async def close(self) -> None:
        pass


class EmptyContentFakeTransport(BatchSummaryFakeTransport):
    """Fake transport whose /retrieve response carries no content."""

    async def request(self, request: RawAPIRequest) -> RawAPIResponse:
        path = request.url.split("://", 1)[-1].split("/v1", 1)[-1] if "://" in request.url else request.url
        if request.method == "GET" and path.rstrip("/").endswith("/retrieve"):
            self.requests.append(request)
            await asyncio.sleep(0)
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=json.dumps({"size_exceeded": False}),
            )
        return await super().request(request)


def _ok_item(custom_id: str, url: str, retrieve_id: str) -> dict[str, Any]:
    return {"custom_id": custom_id, "url": url, "retrieve_id": retrieve_id}


def _failed_item(custom_id: str, url: str, reason: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"custom_id": custom_id, "url": url}
    if reason is not None:
        item["error"] = reason
    return item


def _input(custom_id: str, url: str) -> dict[str, str]:
    return {"url": url, "custom_id": custom_id}


# =============================================================================
# Async summary behaviour
# =============================================================================


class TestAsyncBatchSummary:
    @pytest.mark.asyncio
    async def test_all_success(self) -> None:
        transport = BatchSummaryFakeTransport(
            items=[
                _ok_item("a", "https://a.example", "ret_a"),
                _ok_item("b", "https://b.example", "ret_b"),
            ]
        )
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary(
                [_input("a", "https://a.example"), _input("b", "https://b.example")]
            )

        assert isinstance(summary, BatchSummary)
        assert summary.total_count == 2
        assert summary.success_count == 2
        assert summary.failed_count == 0
        assert summary.failed_items == []
        assert [item.custom_id for item in summary.items] == ["a", "b"]
        assert all(item.succeeded for item in summary.items)

        content = await summary.get_by_custom_id("a").retrieve(["markdown"])
        assert content.markdown_content == "# ret_a"

    @pytest.mark.asyncio
    async def test_partial_failure_keeps_failed_items(self) -> None:
        transport = BatchSummaryFakeTransport(
            items=[
                _ok_item("news", "https://news.example", "ret_news"),
                _failed_item("broken", "https://broken.example", "DNS resolution failed"),
                {"custom_id": "noid", "url": "https://noid.example"},
            ]
        )
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary(
                [
                    _input("news", "https://news.example"),
                    _input("broken", "https://broken.example"),
                    _input("noid", "https://noid.example"),
                ]
            )

        assert summary.total_count == 3
        assert summary.success_count == 1
        assert summary.failed_count == 2
        assert len(summary.items) == 3  # nothing dropped

        broken = summary.get_by_custom_id("broken")
        assert broken.succeeded is False
        assert broken.url == "https://broken.example"
        assert broken.reason == "DNS resolution failed"

        noid = summary.get_by_custom_id("noid")
        assert noid.succeeded is False
        assert noid.reason  # readable, non-empty reason
        assert "retrieve_id" in noid.reason

        with pytest.raises(OlostepClientError_BatchItemFailed):
            await broken.retrieve(["html"])

    @pytest.mark.asyncio
    async def test_all_failed(self) -> None:
        transport = BatchSummaryFakeTransport(
            items=[
                _failed_item("x", "https://x.example", "robots.txt disallowed"),
                _failed_item("y", "https://y.example", "upstream timeout"),
            ]
        )
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary(
                [_input("x", "https://x.example"), _input("y", "https://y.example")]
            )

        assert summary.success_count == 0
        assert summary.failed_count == 2
        assert summary.successful_items == []
        for item in summary:
            with pytest.raises(OlostepClientError_BatchItemFailed):
                await item.retrieve()

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_summary_without_api_calls(self) -> None:
        transport = BatchSummaryFakeTransport(items=[])
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary([])

        assert summary.total_count == 0
        assert summary.success_count == 0
        assert summary.failed_count == 0
        assert summary.items == []
        assert transport.requests == []  # no POST /batches was issued

    @pytest.mark.asyncio
    async def test_none_input_returns_empty_summary(self) -> None:
        transport = BatchSummaryFakeTransport(items=[])
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary(None)
        assert summary.total_count == 0
        assert transport.requests == []

    @pytest.mark.asyncio
    async def test_duplicate_custom_ids_are_preserved(self) -> None:
        transport = BatchSummaryFakeTransport(
            items=[
                _ok_item("dup", "https://first.example", "ret_1"),
                _failed_item("dup", "https://second.example", "blocked"),
            ]
        )
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary(
                [
                    _input("dup", "https://first.example"),
                    _input("dup", "https://second.example"),
                ]
            )

        assert summary.total_count == 2
        assert summary.success_count == 1
        assert summary.failed_count == 1
        assert [i.url for i in summary.get_all_by_custom_id("dup")] == [
            "https://first.example",
            "https://second.example",
        ]
        # get_by_custom_id returns the first match; no duplication is lost.
        assert summary.get_by_custom_id("dup").url == "https://first.example"

    @pytest.mark.asyncio
    async def test_single_string_input_is_coerced(self) -> None:
        transport = BatchSummaryFakeTransport(
            items=[{"url": "https://single.example", "retrieve_id": "ret_single"}]
        )
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary("https://single.example")

        assert summary.total_count == 1
        assert summary.success_count == 1
        assert summary.items[0].url == "https://single.example"

    @pytest.mark.asyncio
    async def test_auto_generated_custom_id_is_reported_once(self) -> None:
        # A plain URL string gets an auto custom_id. Even if the API echoes a
        # different id, URL matching must keep exactly one entry per request.
        transport = BatchSummaryFakeTransport(
            items=[{"custom_id": "api_id", "url": "https://auto.example", "retrieve_id": "ret"}]
        )
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary("https://auto.example")

        assert summary.total_count == 1
        assert summary.items[0].succeeded is True
        assert summary.items[0].url == "https://auto.example"

    @pytest.mark.asyncio
    async def test_api_returns_unknown_extra_item(self) -> None:
        # An item the API reports but nobody requested stays visible, and the
        # requested items are still matched correctly.
        transport = BatchSummaryFakeTransport(
            items=[
                _ok_item("a", "https://a.example", "ret_a"),
                _ok_item("ghost", "https://ghost.example", "ret_ghost"),
            ]
        )
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary([_input("a", "https://a.example")])

        assert summary.total_count == 2
        assert summary.success_count == 2
        assert [i.custom_id for i in summary.items] == ["a", "ghost"]

    @pytest.mark.asyncio
    async def test_locally_invalid_url_does_not_abort_batch(self) -> None:
        # A malformed URL fails client-side validation. It must not abort the
        # batch nor be lost: the valid URL is still processed.
        transport = BatchSummaryFakeTransport(
            items=[_ok_item("ok", "https://ok.example", "ret_ok")]
        )
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary(
                [_input("ok", "https://ok.example"), _input("bad", "not a url")]
            )

        assert summary.total_count == 2
        assert summary.success_count == 1
        assert summary.failed_count == 1
        bad = summary.get_by_custom_id("bad")
        assert bad.url == "not a url"
        assert bad.succeeded is False
        assert "invalid URL" in bad.reason

        create_calls = [r for r in transport.requests if r.method == "POST"]
        assert len(create_calls) == 1
        sent = create_calls[0].json["items"]
        assert [item["custom_id"] for item in sent] == ["ok"]

    @pytest.mark.asyncio
    async def test_all_inputs_invalid_returns_summary_without_api_call(self) -> None:
        transport = BatchSummaryFakeTransport(items=[])
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary(
                [_input("a", "not a url"), _input("b", "also bad")]
            )

        assert summary.total_count == 2
        assert summary.success_count == 0
        assert summary.failed_count == 2
        assert all("invalid URL" in item.reason for item in summary.items)
        assert transport.requests == []

    @pytest.mark.asyncio
    async def test_success_item_with_empty_content_raises(self) -> None:
        # A successful item whose retrieve call yields no content must not
        # silently hand back an empty result.
        transport = EmptyContentFakeTransport(
            items=[_ok_item("ok", "https://ok.example", "ret_ok")]
        )
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary([_input("ok", "https://ok.example")])

        item = summary.get_by_custom_id("ok")
        assert item.succeeded is True
        with pytest.raises(OlostepClientError_BatchItemFailed) as exc_info:
            await item.retrieve(["html"])
        assert "no content" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_item_missing_from_api_response_is_still_in_summary(self) -> None:
        # Only one of two requested URLs is reported back by the API.
        transport = BatchSummaryFakeTransport(
            items=[_ok_item("present", "https://present.example", "ret_present")]
        )
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary(
                [
                    _input("present", "https://present.example"),
                    _input("absent", "https://absent.example"),
                ]
            )

        assert summary.total_count == 2
        assert summary.success_count == 1
        assert summary.failed_count == 1
        absent = summary.get_by_custom_id("absent")
        assert absent.url == "https://absent.example"
        assert absent.succeeded is False
        assert "not reported" in absent.reason

    @pytest.mark.asyncio
    async def test_pagination_collects_all_items(self) -> None:
        transport = BatchSummaryFakeTransport(
            items=[],
            pages=[
                [_ok_item("p1", "https://p1.example", "ret_p1")],
                [
                    _ok_item("p2", "https://p2.example", "ret_p2"),
                    _failed_item("p3", "https://p3.example", "404"),
                ],
            ],
        )
        async with AsyncOlostep(_transport=transport) as client:
            summary = await client.batches.create_summary(
                [
                    _input("p1", "https://p1.example"),
                    _input("p2", "https://p2.example"),
                    _input("p3", "https://p3.example"),
                ]
            )

        assert summary.total_count == 3
        assert summary.success_count == 2
        assert summary.failed_count == 1
        # Cursor-based pagination: only one limit on the first call.
        item_requests = [r for r in transport.requests if r.url.rstrip("/").endswith("/items")]
        assert "limit" in (item_requests[0].query or {})
        assert "cursor" in (item_requests[1].query or {})
        assert "limit" not in (item_requests[1].query or {})

    @pytest.mark.asyncio
    async def test_summary_from_existing_batch(self) -> None:
        transport = BatchSummaryFakeTransport(
            items=[_ok_item("a", "https://a.example", "ret_a")]
        )
        async with AsyncOlostep(_transport=transport) as client:
            batch = await client.batches.create([_input("a", "https://a.example")])
            summary = await batch.summary()
        assert isinstance(summary, BatchSummary)
        assert summary.total_count == 1
        assert summary.batch is not None

    @pytest.mark.asyncio
    async def test_async_summary_does_not_block_event_loop(self) -> None:
        # The batch reports "in_progress" a few times before completing, so the
        # polling and sleep path runs while the ticker coroutine is alive.
        transport = BatchSummaryFakeTransport(
            items=[_ok_item("a", "https://a.example", "ret_a")],
            info_statuses=["in_progress", "in_progress", "in_progress"],
            final_status="completed",
        )

        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0)
                if ticks > 5000:
                    return

        async with AsyncOlostep(_transport=transport) as client:
            task = asyncio.create_task(ticker())
            summary = await client.batches.create_summary(
                [_input("a", "https://a.example")], check_every_n_secs=0
            )
            assert summary.total_count == 1
            await task

        assert ticks > 3  # other coroutines ran while the summary was built
        assert len(transport.info_statuses) == 3  # polling actually happened


# =============================================================================
# Summary object semantics
# =============================================================================


class TestBatchSummaryObject:
    def _summary(self) -> BatchSummary:
        items = [
            BatchSummaryItem(
                None, url="https://ok.example", custom_id="ok", retrieve_id="ret_ok",
                succeeded=True,
            ),
            BatchSummaryItem(
                None, url="https://bad.example", custom_id="bad", succeeded=False,
                reason="blocked by robots.txt",
            ),
        ]
        return BatchSummary(None, items)

    def test_counts_and_partitions(self) -> None:
        summary = self._summary()
        assert summary.total_count == 2
        assert summary.success_count == 1
        assert summary.failed_count == 1
        assert [i.custom_id for i in summary.successful_items] == ["ok"]
        assert [i.custom_id for i in summary.failed_items] == ["bad"]

    def test_lookup_by_custom_id(self) -> None:
        summary = self._summary()
        assert summary.get_by_custom_id("ok").succeeded is True
        assert summary.find_by_custom_id("missing") is None
        with pytest.raises(KeyError):
            summary.get_by_custom_id("missing")
        with pytest.raises(KeyError):
            summary["missing"]
        assert summary["ok"].custom_id == "ok"

    def test_empty_summary(self) -> None:
        empty = BatchSummary(None, [])
        assert len(empty) == 0
        assert empty.total_count == empty.success_count == empty.failed_count == 0
        assert list(empty) == []

    @pytest.mark.asyncio
    async def test_failed_item_retrieve_raises(self) -> None:
        summary = self._summary()
        with pytest.raises(OlostepClientError_BatchItemFailed) as exc_info:
            await summary["bad"].retrieve(["html"])
        assert "blocked by robots.txt" in str(exc_info.value)


# =============================================================================
# Sync client parity
# =============================================================================


class TestSyncBatchSummary:
    def test_sync_summary_matches_async_semantics(self) -> None:
        transport = BatchSummaryFakeTransport(
            items=[
                _ok_item("ok", "https://ok.example", "ret_ok"),
                _failed_item("bad", "https://bad.example", "connection refused"),
            ]
        )
        client = Olostep(_transport=transport)
        summary = client.batches.create_summary(
            [_input("ok", "https://ok.example"), _input("bad", "https://bad.example")]
        )

        assert summary.total_count == 2
        assert summary.success_count == 1
        assert summary.failed_count == 1
        assert len(summary) == 2
        assert [i.custom_id for i in summary] == ["ok", "bad"]

        ok = summary.get_by_custom_id("ok")
        content = ok.retrieve(["html"])
        assert content.html_content == "<html>ret_ok</html>"

        with pytest.raises(OlostepClientError_BatchItemFailed):
            summary.get_by_custom_id("bad").retrieve(["html"])

    def test_sync_empty_input(self) -> None:
        transport = BatchSummaryFakeTransport(items=[])
        summary = Olostep(_transport=transport).batches.create_summary([])
        assert summary.total_count == 0
        assert transport.requests == []

    def test_sync_all_failed(self) -> None:
        transport = BatchSummaryFakeTransport(
            items=[
                _failed_item("a", "https://a.example", "timeout"),
                _failed_item("b", "https://b.example", "ssl error"),
            ]
        )
        summary = Olostep(_transport=transport).batches.create_summary(
            [_input("a", "https://a.example"), _input("b", "https://b.example")]
        )
        assert summary.success_count == 0
        assert summary.failed_count == 2
        assert summary.get_by_custom_id("a").reason == "timeout"
        assert summary.get_by_custom_id("b").reason == "ssl error"

    def test_sync_duplicate_custom_ids(self) -> None:
        transport = BatchSummaryFakeTransport(
            items=[
                _ok_item("dup", "https://one.example", "ret_1"),
                _failed_item("dup", "https://two.example", "blocked"),
            ]
        )
        summary = Olostep(_transport=transport).batches.create_summary(
            [_input("dup", "https://one.example"), _input("dup", "https://two.example")]
        )
        assert summary.total_count == 2
        assert [i.url for i in summary.get_all_by_custom_id("dup")] == [
            "https://one.example",
            "https://two.example",
        ]
        assert len(summary) == 2
