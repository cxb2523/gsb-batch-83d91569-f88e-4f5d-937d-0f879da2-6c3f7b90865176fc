"""
Unit tests for the rich SearchesResult client_state wrapper.
"""

from olostep.frontend.client_state import SearchesResult
from olostep.models.response import SearchesResponse
from tests.fixtures.api.responses.searches import (
    SEARCHES_CREATE_RESPONSE,
    SEARCHES_CREATE_RESPONSE_NO_SCRAPE,
)


class TestSearchesResultStateful:
    """Verify SearchesResult behavior."""

    def test_create_from_response_with_scrape(self) -> None:
        response = SearchesResponse(**SEARCHES_CREATE_RESPONSE)
        result = SearchesResult(response)

        assert result.id == "search_9bi0sbj9xa"
        assert result.object == "search"
        assert result.query == "What's going on with OpenAI's Sora shutting down?"
        assert result.credits_consumed == 10
        assert result.size_exceeded is False
        assert isinstance(result.links, list)
        assert len(result.links) == 2

        # Each link is a plain dict (per design decision: SearchLink stays plain)
        first = result.links[0]
        assert isinstance(first, dict)
        assert first["url"].startswith("https://")
        assert first["markdown_content"]

    def test_create_from_response_no_scrape(self) -> None:
        response = SearchesResponse(**SEARCHES_CREATE_RESPONSE_NO_SCRAPE)
        result = SearchesResult(response)

        assert result.credits_consumed == 5
        assert len(result.links) == 1
        link = result.links[0]
        assert link["markdown_content"] is None
        assert link["html_content"] is None

    def test_repr_contains_key_fields(self) -> None:
        response = SearchesResponse(**SEARCHES_CREATE_RESPONSE)
        result = SearchesResult(response)
        text = repr(result)
        assert "SearchesResult" in text
        assert result.id in text
        assert "links=2" in text

    def test_str_summary(self) -> None:
        response = SearchesResponse(**SEARCHES_CREATE_RESPONSE)
        result = SearchesResult(response)
        text = str(result)
        assert "Search:" in text
        assert "2 links" in text

    def test_metadata_defaults_to_empty_dict(self) -> None:
        # Build a response with metadata set to None
        payload = {**SEARCHES_CREATE_RESPONSE, "metadata": None}
        response = SearchesResponse(**payload)
        result = SearchesResult(response)
        assert result.metadata == {}
