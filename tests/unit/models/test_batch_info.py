"""
BatchInfoResponse parsing, against the shapes GET /batches/{id} returns today.
"""

from __future__ import annotations

import pytest

from olostep.models.response import BatchInfoResponse

# Shape returned for a batch created without a parser (no "parser" key at all).
BATCH_INFO_WITHOUT_PARSER = {
    "id": "batch_123",
    "object": "batch",
    "status": "completed",
    "created": 1793791655,
    "total_urls": 1,
    "completed_urls": 1,
    "completed_at": 1793792737,
    "number_retried": 0,
    "start_date": "2026-11-06",
    "metadata": {},
    "credits_consumed": None,
    "cost_usd": None,
}


@pytest.mark.unit
class TestBatchInfoParser:
    def test_missing_parser_is_none(self) -> None:
        info = BatchInfoResponse(**BATCH_INFO_WITHOUT_PARSER)
        assert info.parser is None

    def test_parser_is_kept(self) -> None:
        info = BatchInfoResponse(**{**BATCH_INFO_WITHOUT_PARSER, "parser": "@olostep/google-search"})
        assert info.parser == "@olostep/google-search"

    def test_literal_none_string_becomes_none(self) -> None:
        info = BatchInfoResponse(**{**BATCH_INFO_WITHOUT_PARSER, "parser": "none"})
        assert info.parser is None
