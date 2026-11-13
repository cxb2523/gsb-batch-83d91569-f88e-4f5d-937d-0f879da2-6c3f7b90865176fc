"""
Searches endpoint contract validation tests.

Validates the POST /searches and GET /searches/{id} contracts against the
real API using httpx transport directly.
"""


import pytest

from olostep.backend.api_endpoints import CONTRACTS
from olostep.errors import (
    OlostepClientError_RequestValidationFailed,
    OlostepClientError_ResponseValidationFailed,
    OlostepServerError_NoResultInResponse,
    OlostepServerError_RequestUnprocessable,
    OlostepServerError_ResourceNotFound,
    OlostepServerError_TemporaryIssue,
)
from olostep.models.response import SearchesResponse
from tests.conftest import extract_request_parameters, retry_request
from tests.fixtures.api.requests.searches import (
    EXCLUDE_DOMAINS,
    GET_SEARCH_REQUEST_ID,
    INCLUDE_DOMAINS,
    LIMIT,
    MINIMAL_REQUEST_BODY,
    QUERY,
    SCRAPE_OPTIONS,
)

SEARCHES_CREATE_CONTRACT = CONTRACTS[("searches", "create")]
SEARCHES_GET_CONTRACT = CONTRACTS[("searches", "get")]


class TestSearchesCreate:
    """Test POST /searches with various parameter combinations."""

    @pytest.mark.asyncio
    async def test_self_test_parameter_coverage(self):
        """Self-test: verify every body field has _valid, _invalid and _null cases."""
        all_params = extract_request_parameters(SEARCHES_CREATE_CONTRACT.request_model)
        body_params = all_params["body"]

        test_methods = [m for m in dir(self) if m.startswith("test_parameter_")]
        param_tests: dict[str, set[str]] = {}
        for method_name in test_methods:
            for suffix in ("_valid", "_invalid", "_null"):
                if method_name.endswith(suffix):
                    param = method_name[len("test_parameter_"):-len(suffix)]
                    param_tests.setdefault(param, set()).add(suffix.lstrip("_"))
                    break

        missing, incomplete = [], []
        for param in body_params:
            if param not in param_tests:
                missing.append(param)
                continue
            for kind in ("valid", "invalid", "null"):
                if kind not in param_tests[param]:
                    incomplete.append(f"{param} (missing _{kind} test)")

        errors = []
        if missing:
            errors.append(f"Missing test methods for parameters: {missing}")
        if incomplete:
            errors.append(f"Incomplete test coverage: {incomplete}")

        assert not errors, "; ".join(errors)

    @pytest.mark.asyncio
    async def test_unknown_parameter_ignored_by_api(self, endpoint_caller):
        """SDK rejects unknown params locally; API tolerates them when bypassed."""
        body_params = {
            **MINIMAL_REQUEST_BODY,
            "made_up_parameter": "this_should_be_ignored",
            "another_fake_param": {"nested": "value", "number": 123},
        }

        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(
                SEARCHES_CREATE_CONTRACT, body_params=body_params
            )

        # Bypass validation; API should still accept and return a valid response
        request = endpoint_caller._prepare_request(
            SEARCHES_CREATE_CONTRACT, {}, {}, body_params
        )
        try:
            model = await retry_request(
                endpoint_caller, request, SEARCHES_CREATE_CONTRACT
            )
            assert isinstance(model, SearchesResponse)
            assert model.id is not None
            assert model.object == "search"
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error")

    # -------------------------------------------------------------------------
    # query
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_parameter_query_valid(self, endpoint_caller):
        for valid_query in QUERY["param_values"]["valids"]:
            body_params = {"query": valid_query}
            validated = endpoint_caller.validate_request(
                SEARCHES_CREATE_CONTRACT, body_params=body_params
            )
            assert validated["body_params"]["query"] == valid_query

            request = endpoint_caller._prepare_request(
                SEARCHES_CREATE_CONTRACT, **validated
            )
            try:
                model = await retry_request(
                    endpoint_caller, request, SEARCHES_CREATE_CONTRACT
                )
                assert isinstance(model, SearchesResponse)
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")

    @pytest.mark.asyncio
    async def test_parameter_query_invalid(self, endpoint_caller):
        for invalid_query in QUERY["param_values"]["invalids"]:
            body_params = {"query": invalid_query}
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(
                    SEARCHES_CREATE_CONTRACT, body_params=body_params
                )

            request = endpoint_caller._prepare_request(
                SEARCHES_CREATE_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            try:
                endpoint_caller._handle_response(
                    request, response, SEARCHES_CREATE_CONTRACT
                )
            except (
                OlostepServerError_RequestUnprocessable,
                OlostepServerError_NoResultInResponse,
                OlostepClientError_ResponseValidationFailed,
                OlostepServerError_TemporaryIssue,
            ):
                pass

    @pytest.mark.asyncio
    async def test_parameter_query_null(self, endpoint_caller):
        body_params = {"query": None}
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(
                SEARCHES_CREATE_CONTRACT, body_params=body_params
            )

        request = endpoint_caller._prepare_request(
            SEARCHES_CREATE_CONTRACT, {}, {}, body_params
        )
        response = await endpoint_caller._transport.request(request)
        with pytest.raises(
            (
                OlostepServerError_RequestUnprocessable,
                OlostepServerError_NoResultInResponse,
            )
        ):
            endpoint_caller._handle_response(
                request, response, SEARCHES_CREATE_CONTRACT
            )

    # -------------------------------------------------------------------------
    # limit
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_parameter_limit_valid(self, endpoint_caller):
        for valid_limit in LIMIT["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "limit": valid_limit}
            validated = endpoint_caller.validate_request(
                SEARCHES_CREATE_CONTRACT, body_params=body_params
            )
            assert validated["body_params"]["limit"] == valid_limit

    @pytest.mark.asyncio
    async def test_parameter_limit_invalid(self, endpoint_caller):
        for invalid_limit in LIMIT["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "limit": invalid_limit}
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(
                    SEARCHES_CREATE_CONTRACT, body_params=body_params
                )

    @pytest.mark.asyncio
    async def test_parameter_limit_null(self, endpoint_caller):
        body_params = {**MINIMAL_REQUEST_BODY, "limit": None}
        validated = endpoint_caller.validate_request(
            SEARCHES_CREATE_CONTRACT, body_params=body_params
        )
        # None values should be stripped from the validated body
        assert "limit" not in validated["body_params"]

    # -------------------------------------------------------------------------
    # include_domains
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_parameter_include_domains_valid(self, endpoint_caller):
        for domains in INCLUDE_DOMAINS["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_domains": domains}
            endpoint_caller.validate_request(
                SEARCHES_CREATE_CONTRACT, body_params=body_params
            )

    @pytest.mark.asyncio
    async def test_parameter_include_domains_invalid(self, endpoint_caller):
        for domains in INCLUDE_DOMAINS["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_domains": domains}
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(
                    SEARCHES_CREATE_CONTRACT, body_params=body_params
                )

    @pytest.mark.asyncio
    async def test_parameter_include_domains_null(self, endpoint_caller):
        body_params = {**MINIMAL_REQUEST_BODY, "include_domains": None}
        validated = endpoint_caller.validate_request(
            SEARCHES_CREATE_CONTRACT, body_params=body_params
        )
        assert "include_domains" not in validated["body_params"]

    # -------------------------------------------------------------------------
    # exclude_domains
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_parameter_exclude_domains_valid(self, endpoint_caller):
        for domains in EXCLUDE_DOMAINS["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "exclude_domains": domains}
            endpoint_caller.validate_request(
                SEARCHES_CREATE_CONTRACT, body_params=body_params
            )

    @pytest.mark.asyncio
    async def test_parameter_exclude_domains_invalid(self, endpoint_caller):
        for domains in EXCLUDE_DOMAINS["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "exclude_domains": domains}
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(
                    SEARCHES_CREATE_CONTRACT, body_params=body_params
                )

    @pytest.mark.asyncio
    async def test_parameter_exclude_domains_null(self, endpoint_caller):
        body_params = {**MINIMAL_REQUEST_BODY, "exclude_domains": None}
        validated = endpoint_caller.validate_request(
            SEARCHES_CREATE_CONTRACT, body_params=body_params
        )
        assert "exclude_domains" not in validated["body_params"]

    # -------------------------------------------------------------------------
    # scrape_options
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_parameter_scrape_options_valid(self, endpoint_caller):
        for opts in SCRAPE_OPTIONS["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "scrape_options": opts}
            endpoint_caller.validate_request(
                SEARCHES_CREATE_CONTRACT, body_params=body_params
            )

    @pytest.mark.asyncio
    async def test_parameter_scrape_options_invalid(self, endpoint_caller):
        for opts in SCRAPE_OPTIONS["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "scrape_options": opts}
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(
                    SEARCHES_CREATE_CONTRACT, body_params=body_params
                )

    @pytest.mark.asyncio
    async def test_parameter_scrape_options_null(self, endpoint_caller):
        body_params = {**MINIMAL_REQUEST_BODY, "scrape_options": None}
        validated = endpoint_caller.validate_request(
            SEARCHES_CREATE_CONTRACT, body_params=body_params
        )
        assert "scrape_options" not in validated["body_params"]

    # -------------------------------------------------------------------------
    # full happy paths
    # -------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_minimal_request_round_trip(self, endpoint_caller):
        """Minimal request body produces a valid SearchesResponse."""
        validated = endpoint_caller.validate_request(
            SEARCHES_CREATE_CONTRACT, body_params=MINIMAL_REQUEST_BODY
        )
        request = endpoint_caller._prepare_request(SEARCHES_CREATE_CONTRACT, **validated)

        try:
            model = await retry_request(endpoint_caller, request, SEARCHES_CREATE_CONTRACT)
            assert isinstance(model, SearchesResponse)
            assert model.id is not None
            assert model.object == "search"
            assert model.query == MINIMAL_REQUEST_BODY["query"]
            assert isinstance(model.result.links, list)
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error")

    @pytest.mark.asyncio
    async def test_full_request_with_scrape_options(self, endpoint_caller):
        """End-to-end: search + inline scrape returns links with markdown content."""
        body_params = {
            "query": "OpenAI Sora shutdown",
            "limit": 5,
            "scrape_options": {"formats": ["markdown"], "timeout": 25},
        }
        validated = endpoint_caller.validate_request(
            SEARCHES_CREATE_CONTRACT, body_params=body_params
        )
        request = endpoint_caller._prepare_request(SEARCHES_CREATE_CONTRACT, **validated)

        try:
            model = await retry_request(endpoint_caller, request, SEARCHES_CREATE_CONTRACT)
            assert isinstance(model, SearchesResponse)
            assert len(model.result.links) > 0
            assert any(
                link.markdown_content for link in model.result.links
            ), "expected at least one link with markdown_content"
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error")


class TestSearchesGet:
    """Test GET /searches/{search_id}."""

    @pytest.mark.asyncio
    async def test_get_existing_search(self, endpoint_caller):
        """Round-trip: create a search, then fetch it by ID."""
        create_validated = endpoint_caller.validate_request(
            SEARCHES_CREATE_CONTRACT, body_params=MINIMAL_REQUEST_BODY
        )
        create_req = endpoint_caller._prepare_request(
            SEARCHES_CREATE_CONTRACT, **create_validated
        )

        try:
            create_model = await retry_request(
                endpoint_caller, create_req, SEARCHES_CREATE_CONTRACT
            )
            assert isinstance(create_model, SearchesResponse)
            search_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during search creation")

        get_validated = endpoint_caller.validate_request(
            SEARCHES_GET_CONTRACT, path_params={"search_id": search_id}
        )
        get_req = endpoint_caller._prepare_request(
            SEARCHES_GET_CONTRACT, **get_validated
        )

        try:
            get_model = await retry_request(endpoint_caller, get_req, SEARCHES_GET_CONTRACT)
            assert isinstance(get_model, SearchesResponse)
            assert get_model.id == search_id
            assert get_model.object == "search"
            assert get_model.query == MINIMAL_REQUEST_BODY["query"]
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during retrieval")

    @pytest.mark.asyncio
    async def test_get_nonexistent_search(self, endpoint_caller):
        """Non-existent search id raises ResourceNotFound."""
        invalid_id = GET_SEARCH_REQUEST_ID["param_values"]["invalids"][0]
        validated = endpoint_caller.validate_request(
            SEARCHES_GET_CONTRACT, path_params={"search_id": invalid_id}
        )
        request = endpoint_caller._prepare_request(SEARCHES_GET_CONTRACT, **validated)
        response = await endpoint_caller._transport.request(request)

        with pytest.raises(OlostepServerError_ResourceNotFound):
            endpoint_caller._handle_response(request, response, SEARCHES_GET_CONTRACT)
