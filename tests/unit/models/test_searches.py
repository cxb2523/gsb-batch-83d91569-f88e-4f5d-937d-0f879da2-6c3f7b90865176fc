"""
Unit tests for the Search request/response Pydantic models.

These verify that local validation catches invalid inputs before they
ever leave the SDK, and that response parsing handles the documented
shape correctly.
"""

import pytest
from pydantic import ValidationError

from olostep.models.request import (
    SearchesBodyParams,
    SearchesGetPathParams,
    SearchesScrapeOptions,
)
from olostep.models.response import (
    SearchesResponse,
    SearchesResult,
    SearchLink,
)
from tests.fixtures.api.requests.searches import (
    EXCLUDE_DOMAINS,
    INCLUDE_DOMAINS,
    LIMIT,
    QUERY,
    SCRAPE_OPTIONS,
)
from tests.fixtures.api.responses.searches import (
    SEARCHES_CREATE_RESPONSE,
    SEARCHES_CREATE_RESPONSE_NO_SCRAPE,
)


# =============================================================================
# Request model validation
# =============================================================================


class TestSearchesBodyParams:
    """Validate POST /searches request body."""

    def test_minimal_valid(self) -> None:
        body = SearchesBodyParams(query="hello world")
        assert body.query == "hello world"
        assert body.limit is None
        assert body.scrape_options is None

    @pytest.mark.parametrize("query", QUERY["param_values"]["valids"])
    def test_query_valid(self, query: str) -> None:
        body = SearchesBodyParams(query=query)
        assert body.query == query

    @pytest.mark.parametrize("query", QUERY["param_values"]["invalids"])
    def test_query_invalid(self, query) -> None:
        with pytest.raises(ValidationError):
            SearchesBodyParams(query=query)

    @pytest.mark.parametrize("limit", LIMIT["param_values"]["valids"])
    def test_limit_valid(self, limit: int) -> None:
        body = SearchesBodyParams(query="x", limit=limit)
        assert body.limit == limit

    @pytest.mark.parametrize("limit", LIMIT["param_values"]["invalids"])
    def test_limit_invalid(self, limit) -> None:
        with pytest.raises(ValidationError):
            SearchesBodyParams(query="x", limit=limit)

    @pytest.mark.parametrize("domains", INCLUDE_DOMAINS["param_values"]["valids"])
    def test_include_domains_valid(self, domains) -> None:
        body = SearchesBodyParams(query="x", include_domains=domains)
        assert body.include_domains == domains

    @pytest.mark.parametrize("domains", INCLUDE_DOMAINS["param_values"]["invalids"])
    def test_include_domains_invalid(self, domains) -> None:
        with pytest.raises(ValidationError):
            SearchesBodyParams(query="x", include_domains=domains)

    @pytest.mark.parametrize("domains", EXCLUDE_DOMAINS["param_values"]["valids"])
    def test_exclude_domains_valid(self, domains) -> None:
        body = SearchesBodyParams(query="x", exclude_domains=domains)
        assert body.exclude_domains == domains

    @pytest.mark.parametrize("domains", EXCLUDE_DOMAINS["param_values"]["invalids"])
    def test_exclude_domains_invalid(self, domains) -> None:
        with pytest.raises(ValidationError):
            SearchesBodyParams(query="x", exclude_domains=domains)


class TestSearchesScrapeOptions:
    """Validate the nested scrape_options object."""

    def test_minimal_valid(self) -> None:
        opts = SearchesScrapeOptions(formats=["markdown"])
        assert opts.formats == ["markdown"]
        assert opts.timeout is None

    @pytest.mark.parametrize(
        "options",
        [o for o in SCRAPE_OPTIONS["param_values"]["valids"] if o is not None],
    )
    def test_scrape_options_valid(self, options: dict) -> None:
        opts = SearchesScrapeOptions(**options)
        # round-trip survives
        dumped = opts.model_dump(exclude_none=True)
        for k, v in options.items():
            assert dumped.get(k) == v

    @pytest.mark.parametrize(
        "options",
        [o for o in SCRAPE_OPTIONS["param_values"]["invalids"] if isinstance(o, dict)],
    )
    def test_scrape_options_invalid_dict(self, options: dict) -> None:
        with pytest.raises(ValidationError):
            SearchesScrapeOptions(**options)

    def test_formats_rejects_json(self) -> None:
        with pytest.raises(ValidationError):
            SearchesScrapeOptions(formats=["json"])

    def test_formats_rejects_text(self) -> None:
        with pytest.raises(ValidationError):
            SearchesScrapeOptions(formats=["text"])

    def test_formats_accepts_html_and_markdown(self) -> None:
        opts = SearchesScrapeOptions(formats=["html", "markdown"])
        assert sorted(opts.formats) == ["html", "markdown"]

    @pytest.mark.parametrize("timeout", [0, 61, -1, 300])
    def test_timeout_out_of_range(self, timeout: int) -> None:
        with pytest.raises(ValidationError):
            SearchesScrapeOptions(formats=["markdown"], timeout=timeout)

    @pytest.mark.parametrize("timeout", [1, 25, 60])
    def test_timeout_in_range(self, timeout: int) -> None:
        opts = SearchesScrapeOptions(formats=["markdown"], timeout=timeout)
        assert opts.timeout == timeout


class TestSearchesGetPathParams:
    def test_path_params(self) -> None:
        path = SearchesGetPathParams(search_id="search_abc123")
        assert path.search_id == "search_abc123"


class TestSearchesSerialization:
    """Verify the @model_serializer hooks behave as documented.

    These guard the behavior the model docstrings claim: nested ``None``
    values must be dropped (the API rejects explicit nulls), and an
    all-None ``scrape_options`` must not surface as ``"scrape_options": {}``
    in the request body — that would diverge from the validate=False path
    which strips it via ``_compress_request``.
    """

    def test_scrape_options_drops_none_fields_when_serialized(self) -> None:
        opts = SearchesScrapeOptions(
            formats=["markdown"],
            remove_css_selectors=None,
            timeout=25,
        )
        dumped = opts.model_dump()
        assert dumped == {"formats": ["markdown"], "timeout": 25}
        assert "remove_css_selectors" not in dumped

    def test_scrape_options_with_only_none_serializes_to_empty(self) -> None:
        # Direct serialization of an all-None nested model is {}; the
        # parent model is responsible for stripping that empty dict.
        opts = SearchesScrapeOptions()
        assert opts.model_dump() == {}

    def test_body_strips_empty_scrape_options(self) -> None:
        """Bug fix: validate_request and _compress_request must agree.

        When every field of scrape_options is None the parent must drop
        the key entirely rather than emit ``"scrape_options": {}``.
        """
        body = SearchesBodyParams(
            query="hi",
            scrape_options={"formats": None, "remove_css_selectors": None, "timeout": None},
        )
        dumped = body.model_dump(mode="json")
        assert dumped == {"query": "hi"}

    def test_body_strips_top_level_none_fields(self) -> None:
        body = SearchesBodyParams(
            query="hi",
            limit=None,
            include_domains=None,
            exclude_domains=None,
            scrape_options=None,
        )
        assert body.model_dump(mode="json") == {"query": "hi"}

    def test_body_keeps_partial_scrape_options(self) -> None:
        body = SearchesBodyParams(
            query="hi",
            scrape_options={"formats": ["markdown"], "timeout": None},
        )
        assert body.model_dump(mode="json") == {
            "query": "hi",
            "scrape_options": {"formats": ["markdown"]},
        }


# =============================================================================
# Response parsing
# =============================================================================


class TestSearchesResponse:
    def test_parse_full_response_with_scrape(self) -> None:
        response = SearchesResponse(**SEARCHES_CREATE_RESPONSE)
        assert response.id == "search_9bi0sbj9xa"
        assert response.object == "search"
        assert response.query == "What's going on with OpenAI's Sora shutting down?"
        assert response.credits_consumed == 10
        assert isinstance(response.result, SearchesResult)
        assert len(response.result.links) == 2
        assert response.result.size_exceeded is False
        first = response.result.links[0]
        assert isinstance(first, SearchLink)
        assert first.url.startswith("https://")
        assert first.markdown_content is not None

    def test_parse_response_without_scrape(self) -> None:
        response = SearchesResponse(**SEARCHES_CREATE_RESPONSE_NO_SCRAPE)
        assert response.credits_consumed == 5
        assert len(response.result.links) == 1
        assert response.result.links[0].markdown_content is None
        assert response.result.links[0].html_content is None
