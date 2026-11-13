"""
Test file to document existing API bugs and issues.

This file contains tests that document known bugs in the API where the API
behaves differently than expected. These tests serve as documentation of
current API limitations and should be updated when the API is fixed.
"""


import pytest

from olostep.backend.api_endpoints import CONTRACTS
from olostep.errors import (
    OlostepClientError_RequestValidationFailed,
    OlostepServerError_RequestUnprocessable,
    OlostepServerError_ResourceNotFound,
    OlostepServerError_TemporaryIssue,
)
from olostep.models.response import (
    BatchCreateResponse,
    BatchInfoResponse,
)
from tests.fixtures.api.requests.batch import (
    GET_BATCH_INFO_REQUEST_ID,
)
from tests.fixtures.api.requests.batch import (
    MINIMAL_REQUEST_BODY as BATCH_MINIMAL_REQUEST_BODY,
)
from tests.fixtures.api.requests.crawl import (
    CRAWL_SEARCH_QUERY,
    CURSOR,
    EXCLUDE_URLS,
    GET_CRAWL_PAGES_REQUEST_ID,
    INCLUDE_EXTERNAL,
    INCLUDE_SUBDOMAIN,
    INCLUDE_URLS,
    LIMIT,
    MAX_DEPTH,
    MAX_PAGES,
    MINIMAL_REQUEST_BODY,
    SEARCH_QUERY,
    START_URL,
    TOP_N,
    WEBHOOK_URL,
)

CRAWL_START_CONTRACT = CONTRACTS[('crawl', 'start')]
CRAWL_PAGES_CONTRACT = CONTRACTS[('crawl', 'pages')]
BATCH_START_CONTRACT = CONTRACTS[('batch', 'start')]
BATCH_INFO_CONTRACT = CONTRACTS[('batch', 'info')]
BASE_URL = "https://api.olostep.com/v1"


########################################
# --- Test Existing API Bugs ---
# a passing test in this file means that the API bug has been fixed
########################################


class TestExistingAPIBugs:
    """Test cases documenting existing API bugs and limitations."""

#     @pytest.mark.asyncio
#     async def test_crawl_start_param_exclude_urls_glob_is_broken(self, endpoint_caller):
#         """
#         Test documenting that exclude_urls with glob patterns like ["*.pdf", "*.jpg"] 
#         now works correctly.
        
#         This test was originally created to document a bug where the API would reject
#         glob patterns, but the bug has since been fixed.
#         """
#         # First, verify that all valid EXCLUDE_URLS patterns work correctly
#         for valid_exclude_urls in EXCLUDE_URLS["param_values"]["valids"]:
#             body_params = {**MINIMAL_REQUEST_BODY, "exclude_urls": valid_exclude_urls}
            
#             validated_request = endpoint_caller.validate_request(
#                 CRAWL_START_CONTRACT, body_params=body_params
#             )
            
#             assert "exclude_urls" in validated_body
#             assert validated_body["exclude_urls"] == valid_exclude_urls
            
#             request = endpoint_caller._prepare_request(
#                 CRAWL_START_CONTRACT, **validated_request
#             )
            
#             try:
#                 model = await retry_request(
#                     endpoint_caller, request, CRAWL_START_CONTRACT
#                 )
#                 assert isinstance(model, CreateCrawlResponse)
#             except OlostepTransientBackendError:
#                 pytest.skip("API raised a temporary error")
#             except (OlostepRequestUnprocessableError, OlostepResponseValidationError, OlostepUnknowServerIssuedError):
#                 # API rejects valid values - this indicates a bug
#                 pytest.fail("API BUG: API should reject valid exclude_urls values")
#                 pass
        
#         # Now test the specific glob patterns that were previously broken
#         glob_patterns = ["*.pdf", "*.jpg"]
#         body_params = {**MINIMAL_REQUEST_BODY, "exclude_urls": glob_patterns}
        
#         validated_request = endpoint_caller.validate_request(
#             CRAWL_START_CONTRACT, body_params=body_params
#         )
        
#         assert "exclude_urls" in validated_body
#         assert validated_body["exclude_urls"] == glob_patterns
        
#         request = endpoint_caller._prepare_request(
#             CRAWL_START_CONTRACT, **validated_request
#         )
        
#         # This should now work correctly (bug has been fixed)
#         try:
#             model = await retry_request(
#                 endpoint_caller, request, CRAWL_START_CONTRACT
#             )
#             assert isinstance(model, CreateCrawlResponse)
#             # Test passes - glob patterns now work correctly
#         except OlostepTransientBackendError:
#             pytest.skip("API raised a temporary error")
#         except (OlostepRequestUnprocessableError, OlostepResponseValidationError, OlostepUnknowServerIssuedError):
#             # If we get here, the bug might have returned
#             pytest.fail("Glob patterns are failing again - API bug may have returned")

    @pytest.mark.asyncio
    async def test_api_accepts_invalid_start_url_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts invalid start_url values instead of rejecting them.
        
        The API should reject invalid URLs with OlostepRequestUnprocessableError,
        but it currently accepts them and returns successful responses.
        """
        for invalid_url in START_URL["param_values"]["invalids"]:
            body_params = {
                "start_url": invalid_url,
                "max_pages": MAX_PAGES["param_values"]["valids"][0]
            }
            
            # Our validation correctly rejects this
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # BUG: API should reject this but doesn't
                pytest.fail(f"API BUG: Should reject invalid start_url '{invalid_url}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This is the correct behavior - API should reject invalid URLs
                pass

    @pytest.mark.asyncio
    async def test_api_accepts_invalid_max_pages_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts invalid max_pages values instead of rejecting them.
        
        The API should reject invalid max_pages with OlostepRequestUnprocessableError,
        but it currently accepts them and returns successful responses.
        """
        for invalid_max_pages in MAX_PAGES["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "max_pages": invalid_max_pages}
            
            # Our validation correctly rejects this
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # BUG: API should reject this but doesn't
                pytest.fail(f"API BUG: Should reject invalid max_pages '{invalid_max_pages}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This is the correct behavior - API should reject invalid max_pages
                pass

    @pytest.mark.asyncio
    async def test_api_accepts_invalid_include_urls_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts invalid include_urls values instead of rejecting them.
        
        The API should reject invalid include_urls with OlostepRequestUnprocessableError,
        but it currently accepts them and returns successful responses.
        """
        for invalid_include_urls in INCLUDE_URLS["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_urls": invalid_include_urls}
            
            # Our validation correctly rejects this
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # BUG: API should reject this but doesn't
                pytest.fail(f"API BUG: Should reject invalid include_urls '{invalid_include_urls}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This is the correct behavior - API should reject invalid include_urls
                pass

    @pytest.mark.asyncio
    async def test_api_accepts_invalid_exclude_urls_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts invalid exclude_urls values instead of rejecting them.
        
        The API should reject invalid exclude_urls with OlostepRequestUnprocessableError,
        but it currently accepts them and returns successful responses.
        """
        for invalid_exclude_urls in EXCLUDE_URLS["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "exclude_urls": invalid_exclude_urls}
            
            # Our validation correctly rejects this
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # BUG: API should reject this but doesn't
                pytest.fail(f"API BUG: Should reject invalid exclude_urls '{invalid_exclude_urls}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This is the correct behavior - API should reject invalid exclude_urls
                pass

    @pytest.mark.asyncio
    async def test_api_accepts_invalid_max_depth_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts invalid max_depth values instead of rejecting them.
        
        The API should reject invalid max_depth with OlostepRequestUnprocessableError,
        but it currently accepts them and returns successful responses.
        """
        for invalid_max_depth in MAX_DEPTH["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "max_depth": invalid_max_depth}
            
            # Our validation correctly rejects this
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # BUG: API should reject this but doesn't
                pytest.fail(f"API BUG: Should reject invalid max_depth '{invalid_max_depth}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This is the correct behavior - API should reject invalid max_depth
                pass

    @pytest.mark.asyncio
    async def test_api_accepts_invalid_include_external_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts invalid include_external values instead of rejecting them.
        
        The API should reject invalid include_external with OlostepRequestUnprocessableError,
        but it currently accepts them and returns successful responses.
        """
        for invalid_include_external in INCLUDE_EXTERNAL["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_external": invalid_include_external}
            
            # Our validation correctly rejects this
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # BUG: API should reject this but doesn't
                pytest.fail(f"API BUG: Should reject invalid include_external '{invalid_include_external}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This is the correct behavior - API should reject invalid include_external
                pass

    @pytest.mark.asyncio
    async def test_api_accepts_invalid_include_subdomain_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts invalid include_subdomain values instead of rejecting them.
        
        The API should reject invalid include_subdomain with OlostepRequestUnprocessableError,
        but it currently accepts them and returns successful responses.
        """
        for invalid_include_subdomain in INCLUDE_SUBDOMAIN["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_subdomain": invalid_include_subdomain}
            
            # Our validation correctly rejects this
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # BUG: API should reject this but doesn't
                pytest.fail(f"API BUG: Should reject invalid include_subdomain '{invalid_include_subdomain}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This is the correct behavior - API should reject invalid include_subdomain
                pass

    @pytest.mark.asyncio
    async def test_api_accepts_invalid_search_query_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts invalid search_query values instead of rejecting them.
        
        The API should reject invalid search_query with OlostepRequestUnprocessableError,
        but it currently accepts them and returns successful responses.
        """
        for invalid_search_query in SEARCH_QUERY["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "search_query": invalid_search_query}
            
            # Our validation correctly rejects this
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # BUG: API should reject this but doesn't
                pytest.fail(f"API BUG: Should reject invalid search_query '{invalid_search_query}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This is the correct behavior - API should reject invalid search_query
                pass

    @pytest.mark.asyncio
    async def test_api_accepts_invalid_top_n_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts invalid top_n values instead of rejecting them.
        
        The API should reject invalid top_n with OlostepRequestUnprocessableError,
        but it currently accepts them and returns successful responses.
        """
        for invalid_top_n in TOP_N["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "top_n": invalid_top_n}
            
            # Our validation correctly rejects this
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # BUG: API should reject this but doesn't
                pytest.fail(f"API BUG: Should reject invalid top_n '{invalid_top_n}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This is the correct behavior - API should reject invalid top_n
                pass

    @pytest.mark.asyncio
    async def test_api_accepts_invalid_webhook_url_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts invalid webhook_url values instead of rejecting them.
        
        The API should reject invalid webhook_url with OlostepRequestUnprocessableError,
        but it currently accepts them and returns successful responses.
        """
        for invalid_webhook_url in WEBHOOK_URL["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "webhook_url": invalid_webhook_url}
            
            # Our validation correctly rejects this
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # BUG: API should reject this but doesn't
                pytest.fail(f"API BUG: Should reject invalid webhook_url '{invalid_webhook_url}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This is the correct behavior - API should reject invalid webhook_url
                pass

    @pytest.mark.asyncio
    async def test_api_accepts_invalid_cursor_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts invalid cursor values instead of rejecting them.
        
        The API should reject invalid cursor with OlostepRequestUnprocessableError,
        but it currently accepts them and returns successful responses.
        """
        # First create a crawl to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=create_body_params
        )
        
        create_request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        try:
            create_response = await endpoint_caller._transport.request(create_request)
            create_model = endpoint_caller._handle_response(create_request, create_response, CRAWL_START_CONTRACT)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Test with invalid cursor values
        for invalid_cursor in CURSOR["param_values"]["invalids"]:
            crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
            get_path_params = {crawl_id_param_name: valid_crawl_id}
            get_query_params = {"cursor": invalid_cursor}
            
            # Our validation correctly rejects this
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params)
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_PAGES_CONTRACT, get_path_params, get_query_params, {}
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_PAGES_CONTRACT)
                # BUG: API should reject this but doesn't
                pytest.fail(f"API BUG: Should reject invalid cursor '{invalid_cursor}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This is the correct behavior - API should reject invalid cursor
                pass

    @pytest.mark.asyncio
    async def test_api_accepts_invalid_limit_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts invalid limit values instead of rejecting them.
        
        The API should reject invalid limit with OlostepRequestUnprocessableError,
        but it currently accepts them and returns successful responses.
        """
        # First create a crawl to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=create_body_params
        )
        
        create_request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        try:
            create_response = await endpoint_caller._transport.request(create_request)
            create_model = endpoint_caller._handle_response(create_request, create_response, CRAWL_START_CONTRACT)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Test with invalid limit values
        for invalid_limit in LIMIT["param_values"]["invalids"]:
            crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
            get_path_params = {crawl_id_param_name: valid_crawl_id}
            get_query_params = {"limit": invalid_limit}
            
            # Our validation correctly rejects this
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params)
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_PAGES_CONTRACT, get_path_params, get_query_params, {}
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_PAGES_CONTRACT)
                # BUG: API should reject this but doesn't
                pytest.fail(f"API BUG: Should reject invalid limit '{invalid_limit}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This is the correct behavior - API should reject invalid limit
                pass

    @pytest.mark.asyncio
    async def test_api_accepts_invalid_crawl_pages_search_query_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts invalid search_query values for crawl pages instead of rejecting them.
        
        The API should reject invalid search_query with OlostepRequestUnprocessableError,
        but it currently accepts them and returns successful responses.
        """
        # First create a crawl to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=create_body_params
        )
        
        create_request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        try:
            create_response = await endpoint_caller._transport.request(create_request)
            create_model = endpoint_caller._handle_response(create_request, create_response, CRAWL_START_CONTRACT)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Test with invalid search_query values
        for invalid_search_query in CRAWL_SEARCH_QUERY["param_values"]["invalids"]:
            crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
            get_path_params = {crawl_id_param_name: valid_crawl_id}
            get_query_params = {"search_query": invalid_search_query}
            
            # Our validation correctly rejects this
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params)
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_PAGES_CONTRACT, get_path_params, get_query_params, {}
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_PAGES_CONTRACT)
                # BUG: API should reject this but doesn't
                pytest.fail(f"API BUG: Should reject invalid search_query '{invalid_search_query}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This is the correct behavior - API should reject invalid search_query
                pass

    @pytest.mark.asyncio
    async def test_api_accepts_cursor_and_limit_together(self, endpoint_caller):
        """
        BUG: API incorrectly accepts both cursor and limit parameters together.
        
        According to the API's cursor-based pagination design, these parameters should be
        mutually exclusive. The API should reject requests with both parameters and return
        OlostepRequestUnprocessableError, but it currently accepts them.
        """
        # First create a crawl to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=create_body_params
        )
        
        create_request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        try:
            create_response = await endpoint_caller._transport.request(create_request)
            create_model = endpoint_caller._handle_response(create_request, create_response, CRAWL_START_CONTRACT)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Test that our validation correctly rejects both parameters
        crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
        get_path_params = {crawl_id_param_name: valid_crawl_id}
        get_query_params = {"cursor": 123, "limit": 10}
        
        # Our validation correctly rejects this
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params)
        
        # But the API incorrectly accepts it (bypass validation)
        request = endpoint_caller._prepare_request(
            CRAWL_PAGES_CONTRACT, get_path_params, get_query_params, {}
        )
        response = await endpoint_caller._transport.request(request)
        
        try:
            model = endpoint_caller._handle_response(request, response, CRAWL_PAGES_CONTRACT)
            # BUG: API should reject both cursor and limit together but doesn't
            pytest.fail("API BUG: Should reject both cursor and limit parameters together but accepted them")
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error")
        except OlostepServerError_RequestUnprocessable:
            # This would be the correct behavior
            pass

    @pytest.mark.asyncio
    async def test_api_accepts_nonsense_cursor_values(self, endpoint_caller):
        """
        BUG: API incorrectly accepts nonsense cursor values instead of rejecting them.
        
        The API should reject invalid cursor values (like negative numbers, strings, etc.)
        with OlostepRequestUnprocessableError, but it currently accepts them and returns
        successful responses.
        """
        # First create a crawl to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=create_body_params
        )
        
        create_request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        try:
            create_response = await endpoint_caller._transport.request(create_request)
            create_model = endpoint_caller._handle_response(create_request, create_response, CRAWL_START_CONTRACT)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Test with nonsense cursor values that should be rejected
        nonsense_cursors = [
            -1,           # Negative cursor
            -999,         # Large negative cursor
            "invalid",    # String cursor
            "abc123",     # Alphanumeric string
            None,         # Null cursor
            [],           # Empty list
            {},           # Empty object
            True,         # Boolean cursor
            False,        # Boolean cursor
        ]
        
        for nonsense_cursor in nonsense_cursors:
            crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
            get_path_params = {crawl_id_param_name: valid_crawl_id}
            get_query_params = {"cursor": nonsense_cursor}
            
            # Our validation correctly rejects most of these
            try:
                endpoint_caller.validate_request(CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params)
                # If validation passes, that's also a bug in our validation
                print(f"WARNING: Our validation should reject cursor '{nonsense_cursor}' but didn't")
            except OlostepClientError_RequestValidationFailed:
                # This is expected - our validation should reject invalid cursors
                pass
            
            # But the API incorrectly accepts it (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_PAGES_CONTRACT, get_path_params, get_query_params, {}
            )
            response = await endpoint_caller._transport.request(request)
            
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_PAGES_CONTRACT)
                # BUG: API should reject nonsense cursor values but doesn't
                pytest.fail(f"API BUG: Should reject nonsense cursor '{nonsense_cursor}' but accepted it")
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # This would be the correct behavior
                pass

    @pytest.mark.asyncio
    async def test_api_returns_extra_batch_id_field(self, endpoint_caller):
        """
        BUG: API incorrectly returns an extra 'batch_id' field in batch info responses.
        
        The API should only return the 'id' field, but it currently also returns a
        redundant 'batch_id' field with the same value. This is documented as
        "undocumented in the docs, will be accepted but suppressed by the client"
        in the validation model.
        
        Our client validation correctly removes this field, but the API should not
        return it in the first place.
        """
        # First create a batch to get a valid ID
        create_body_params = BATCH_MINIMAL_REQUEST_BODY
        
        validated_request = endpoint_caller.validate_request(
            BATCH_START_CONTRACT, body_params=create_body_params
        )
        
        create_request = endpoint_caller._prepare_request(
            BATCH_START_CONTRACT, **validated_request
        )
        
        try:
            create_response = await endpoint_caller._transport.request(create_request)
            create_model = endpoint_caller._handle_response(create_request, create_response, BATCH_START_CONTRACT)
            assert isinstance(create_model, BatchCreateResponse)
            batch_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch creation")
        
        # Now get the batch info
        batch_id_param_name = GET_BATCH_INFO_REQUEST_ID["param_name"]
        get_path_params = {batch_id_param_name: batch_id}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_INFO_CONTRACT, path_params=get_path_params
        )
        
        get_request = endpoint_caller._prepare_request(
            BATCH_INFO_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, BATCH_INFO_CONTRACT)
            assert isinstance(get_model, BatchInfoResponse)
            
            # Our client validation should have removed the batch_id field
            assert not hasattr(get_model, "batch_id"), "Client validation should remove batch_id field"
            
            # But let's check the raw response to see if the API returned it
            raw_response_data = get_response.body
            
            # Parse JSON if it's a string
            if isinstance(raw_response_data, str):
                import json
                try:
                    parsed_response = json.loads(raw_response_data)
                    print(f"🔍 Raw API response keys: {list(parsed_response.keys())}")
                    
                    if "batch_id" in parsed_response:
                        # BUG: API should not return batch_id field
                        pytest.fail(f"API BUG: API incorrectly returned 'batch_id' field with value '{parsed_response['batch_id']}' - this field should not exist")
                    else:
                        # API correctly did not return batch_id field
                        print("✅ API correctly did not return 'batch_id' field")
                        
                except json.JSONDecodeError:
                    print(f"⚠️  Could not parse response as JSON: {raw_response_data[:100]}...")
            elif isinstance(raw_response_data, dict):
                print(f"🔍 Raw API response keys: {list(raw_response_data.keys())}")
                
                if "batch_id" in raw_response_data:
                    # BUG: API should not return batch_id field
                    pytest.fail(f"API BUG: API incorrectly returned 'batch_id' field with value '{raw_response_data['batch_id']}' - this field should not exist")
                else:
                    # API correctly did not return batch_id field
                    print("✅ API correctly did not return 'batch_id' field")
            else:
                # Response is not a dict or string, can't check for batch_id
                print(f"⚠️  Response is not a dict or string: {type(raw_response_data)}")
                
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch info retrieval")

    @pytest.mark.asyncio
    async def test_api_validation_bugs_summary(self, endpoint_caller):
        """
        SUMMARY: API has widespread validation bugs where invalid parameter values are accepted.
        
        This test documents the overall issue: The API should reject invalid parameter values
        with OlostepRequestUnprocessableError (422), but instead it accepts them and returns
        successful responses. This affects multiple parameters across different endpoints.
        
        Affected parameters:
        - Crawl Start endpoint: start_url, max_pages, include_urls, exclude_urls, max_depth,
          include_external, include_subdomain, search_query, top_n, webhook_url
        - Crawl Pages endpoint: cursor, limit, search_query
        
        Specific pagination bugs:
        - API accepts both cursor and limit together (should be mutually exclusive)
        - API accepts nonsense cursor values (negative numbers, strings, booleans, etc.)
        
        This is a significant API contract violation that affects data integrity and
        user experience. The API should implement proper server-side validation to
        reject invalid values consistently.
        """
        # This is a documentation test - the individual parameter tests above
        # demonstrate the specific bugs. This test serves as a summary and
        # can be used to track when the overall validation issue is fixed.
        
        # Test one example to demonstrate the pattern
        invalid_url = "not-a-valid-url"
        body_params = {
            "start_url": invalid_url,
            "max_pages": MAX_PAGES["param_values"]["valids"][0]
        }
        
        # Our client validation correctly rejects this
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
        
        # But the API incorrectly accepts it
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, {}, {}, body_params
        )
        response = await endpoint_caller._transport.request(request)
        
        try:
            model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
            # This demonstrates the bug - API should reject invalid URLs
            pytest.fail("API BUG: Should reject invalid start_url but accepted it - validation is broken")
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error")
        except OlostepServerError_RequestUnprocessable:
            # This would be the correct behavior
            pass

    @pytest.mark.asyncio
    async def test_api_accepts_any_invalid_retrieve_id(self, endpoint_caller):
        """
        BUG: API incorrectly returns 200 responses for invalid retrieve IDs instead of 404.
        
        The API should return OlostepRequestedResourceNotFoundError (404) for invalid
        retrieve IDs, but it currently returns successful 200 responses with valid
        RetrieveResponse shapes for any imaginative ID.
        """
        from olostep.backend.api_endpoints import CONTRACTS
        from olostep.backend.validation import RetrieveFormat
        
        RETRIEVE_GET_CONTRACT = CONTRACTS[('retrieve', 'get')]
        
        # Test with a made-up invalid ID
        invalid_batch_id = "iMaDEd_tHis_UP"
        
        retrieve_query_params = {
            "retrieve_id": invalid_batch_id,
            "formats": [RetrieveFormat.HTML],
        }
        
        # Our validation correctly accepts this (ID format is valid)
        validated_request = endpoint_caller.validate_request(
            RETRIEVE_GET_CONTRACT, query_params=retrieve_query_params
        )
        
        retrieve_request = endpoint_caller._prepare_request(
            RETRIEVE_GET_CONTRACT, **validated_request
        )
        
        # BUG: API should return 404 for invalid ID but returns 200 instead
        try:
            response = await endpoint_caller._transport.request(retrieve_request)
            model = endpoint_caller._handle_response(retrieve_request, response, RETRIEVE_GET_CONTRACT)
            # BUG: API should reject invalid batch ID but doesn't
            pytest.fail(f"API BUG: Should return 404 for invalid batch ID '{invalid_batch_id}' but returned 200 with valid response")
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error")
        except OlostepServerError_ResourceNotFound:
            # This is the correct behavior - API should return 404 for invalid IDs
            pass
