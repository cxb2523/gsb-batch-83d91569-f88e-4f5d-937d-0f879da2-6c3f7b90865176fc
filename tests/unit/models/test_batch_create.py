"""
BatchCreateResponse parsing, against the shape POST /batches returns today.
"""

from __future__ import annotations

import pytest

from olostep.models.common import Country
from olostep.models.response import BatchCreateResponse

# Shape returned for a batch created with a parser and a country.
BATCH_CREATED = {
    "id": "batch_123",
    "object": "batch",
    "status": "in_progress",
    "created": 1794155237,
    "total_urls": 1,
    "completed_urls": 0,
    "number_retried": 0,
    "parser": "@olostep/google-search",
    "country": "US",
    "start_date": "2026-11-08",
    "metadata": {},
    "credits_consumed": None,
    "cost_usd": None,
}


@pytest.mark.unit
class TestBatchCreateParserAndCountry:
    def test_parser_and_country_are_read(self) -> None:
        response = BatchCreateResponse(**BATCH_CREATED)
        assert response.batch_parser == "@olostep/google-search"
        assert response.batch_country == Country.US

    def test_older_field_names_are_still_read(self) -> None:
        data = {k: v for k, v in BATCH_CREATED.items() if k not in ("parser", "country")}
        response = BatchCreateResponse(**data, batch_parser="@olostep/google-search", batch_country="US")
        assert response.batch_parser == "@olostep/google-search"
        assert response.batch_country == Country.US

    def test_missing_parser_and_country_are_none(self) -> None:
        data = {k: v for k, v in BATCH_CREATED.items() if k not in ("parser", "country")}
        response = BatchCreateResponse(**data)
        assert response.batch_parser is None
        assert response.batch_country is None

    def test_literal_none_parser_becomes_none(self) -> None:
        response = BatchCreateResponse(**{**BATCH_CREATED, "parser": "none"})
        assert response.batch_parser is None
