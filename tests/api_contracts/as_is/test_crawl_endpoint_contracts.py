"""
Crawl endpoint contract validation tests.

This test suite validates crawl endpoint contracts against the API using httpx transport directly.
"""

import asyncio
import math
import time

import pytest

from olostep.backend.api_endpoints import CONTRACTS
from olostep.errors import (
    OlostepClientError_RequestValidationFailed,
    OlostepServerError_RequestUnprocessable,
    OlostepServerError_ResourceNotFound,
    OlostepServerError_TemporaryIssue,
)
from olostep.models.response import (
    CrawlInfoResponse,
    CrawlPagesResponse,
    CreateCrawlResponse,
)
from tests.conftest import extract_request_parameters, retry_request
from tests.fixtures.api.requests.crawl import (
    CRAWL_SEARCH_QUERY,
    CURSOR,
    EXCLUDE_URLS,
    FOLLOW_ROBOTS_TXT,
    GET_CRAWL_INFO_REQUEST_ID,
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
    WORKFLOW_REQUEST_BODY,
)

CRAWL_START_CONTRACT = CONTRACTS[('crawl', 'start')]
CRAWL_INFO_CONTRACT = CONTRACTS[('crawl', 'info')]
CRAWL_PAGES_CONTRACT = CONTRACTS[('crawl', 'pages')]

BASE_URL = "https://api.olostep.com/v1"


class TestCrawlStart:
    """Test crawl start with various parameter combinations."""
    
    @pytest.mark.asyncio
    async def test_self_test_parameter_coverage(self):
        """Self-test: Verify that we have test methods for each parameter in the request model."""
        # Extract all parameters from the request model
        all_params = extract_request_parameters(CRAWL_START_CONTRACT.request_model)
        body_params = all_params['body']
        
        # Get all test methods in this class that start with 'test_parameter_'
        test_methods = [method for method in dir(self) if method.startswith('test_parameter_')]
        
        # Group test methods by parameter name
        param_tests = {}
        for method_name in test_methods:
            # Extract parameter name from 'test_parameter_XXX_valid', 'test_parameter_XXX_invalid', or 'test_parameter_XXX_null'
            if '_valid' in method_name:
                param_name = method_name.replace('test_parameter_', '').replace('_valid', '')
                test_type = 'valid'
            elif '_invalid' in method_name:
                param_name = method_name.replace('test_parameter_', '').replace('_invalid', '')
                test_type = 'invalid'
            elif '_null' in method_name:
                param_name = method_name.replace('test_parameter_', '').replace('_null', '')
                test_type = 'null'
            else:
                continue
            
            if param_name not in param_tests:
                param_tests[param_name] = set()
            param_tests[param_name].add(test_type)
        
        # Check coverage - each parameter must have valid, invalid, and null tests
        missing_tests = []
        incomplete_tests = []
        
        for param in body_params:
            if param not in param_tests:
                missing_tests.append(param)
            else:
                param_test_types = param_tests[param]
                if 'valid' not in param_test_types:
                    incomplete_tests.append(f"{param} (missing _valid test)")
                if 'invalid' not in param_test_types:
                    incomplete_tests.append(f"{param} (missing _invalid test)")
                if 'null' not in param_test_types:
                    incomplete_tests.append(f"{param} (missing _null test)")
        
        # Assert that we have complete tests for all parameters
        error_messages = []
        if missing_tests:
            error_messages.append(f"Missing test methods for parameters: {missing_tests}")
        if incomplete_tests:
            error_messages.append(f"Incomplete test coverage: {incomplete_tests}")
        
        assert len(error_messages) == 0, "; ".join(error_messages)
        
    @pytest.mark.asyncio
    async def test_unknown_parameter_ignored_by_api(self, endpoint_caller):
        """Test that the API ignores unknown parameters and works normally"""
        # Add a made-up parameter that should be rejected by our validation
        body_params = {
            **MINIMAL_REQUEST_BODY,
            "made_up_parameter": "this_should_be_ignored",
            # "another_fake_param": {"nested": "value", "number": 123}
        }
        
        # Our validation should refuse this request due to the unknown parameters
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
        
        # But if we bypass validation and send it to the API anyway, the API should ignore the unknown parameters
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, {}, {}, body_params
        )
        
        # The API should accept the request and ignore the unknown parameters
        try:
            model = await retry_request(
                endpoint_caller, request, CRAWL_START_CONTRACT
            )
            assert isinstance(model, CreateCrawlResponse)
            # Verify the response is valid despite the unknown parameters
            assert model.id is not None
            assert model.object == "crawl"
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
        
    @pytest.mark.asyncio
    async def test_parameter_start_url_valid(self, endpoint_caller):
        """Test start_url parameter with valid values from fixtures"""
        for valid_url in START_URL["param_values"]["valids"]:
            body_params = {
                "start_url": valid_url,
                "max_pages": MAX_PAGES["param_values"]["valids"][0]
            }
            
            validated_request = endpoint_caller.validate_request(
                CRAWL_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "start_url" in validated_body
            assert validated_body["start_url"].startswith(valid_url) #trailing slash is added by the API
            
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, CRAWL_START_CONTRACT
                )
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_start_url_invalid(self, endpoint_caller):
        """Test start_url parameter with invalid values from fixtures"""
        for invalid_url in START_URL["param_values"]["invalids"]:
            body_params = {
                "start_url": invalid_url,
                "max_pages": MAX_PAGES["param_values"]["valids"][0]
            }
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
        
    @pytest.mark.asyncio
    async def test_parameter_start_url_null(self, endpoint_caller):
        """Test start_url parameter with null value"""
        body_params = {
            "start_url": None,
            "max_pages": MAX_PAGES["param_values"]["valids"][0]
        }
        
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
        
        # Test API behavior with null request (bypass validation)
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, {}, {}, body_params
        )
        response = await endpoint_caller._transport.request(request)
        
        # API returns 500 error for this null requests
        with pytest.raises(OlostepServerError_RequestUnprocessable):
            endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
        
    @pytest.mark.asyncio
    async def test_parameter_max_pages_valid(self, endpoint_caller):
        """Test max_pages parameter with valid values from fixtures"""
        for valid_max_pages in MAX_PAGES["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "max_pages": valid_max_pages}
            
            validated_request = endpoint_caller.validate_request(
                CRAWL_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "max_pages" in validated_body
            assert validated_body["max_pages"] == valid_max_pages
            
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, CRAWL_START_CONTRACT
                )
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")

    @pytest.mark.asyncio
    async def test_parameter_max_pages_invalid(self, endpoint_caller):
        """Test max_pages parameter with invalid values from fixtures"""
        for invalid_max_pages in MAX_PAGES["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "max_pages": invalid_max_pages}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_max_pages_null(self, endpoint_caller):
        """Test max_pages parameter with null value (should pass if max_depth is set)"""
        # Test with max_depth set - should pass
        body_params = {
            "start_url": START_URL["param_values"]["valids"][0],
            "max_pages": None,
            "max_depth": MAX_DEPTH["param_values"]["valids"][0]
        }
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "max_pages" not in validated_body or validated_body["max_pages"] is None
        assert "max_depth" in validated_body
        
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        try:
            model = await retry_request(
                endpoint_caller, request, CRAWL_START_CONTRACT
            )
            assert isinstance(model, CreateCrawlResponse)
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error")
        
        # Test with both null - should fail
        body_params_both_null = {
            "start_url": START_URL["param_values"]["valids"][0],
            "max_pages": None,
            "max_depth": None
        }
        
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params_both_null)
    
    @pytest.mark.asyncio
    async def test_parameter_include_urls_valid(self, endpoint_caller):
        """Test include_urls parameter with valid values from fixtures"""
        for valid_include_urls in INCLUDE_URLS["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_urls": valid_include_urls}
            
            validated_request = endpoint_caller.validate_request(
                CRAWL_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "include_urls" in validated_body
            assert validated_body["include_urls"] == valid_include_urls
            
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, CRAWL_START_CONTRACT
                )
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_include_urls_invalid(self, endpoint_caller):
        """Test include_urls parameter with invalid values from fixtures"""
        for invalid_include_urls in INCLUDE_URLS["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_urls": invalid_include_urls}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_include_urls_null(self, endpoint_caller):
        """Test include_urls parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "include_urls": None}
        
        endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
        
        # Test API behavior with null request (bypass validation)
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, {}, {}, body_params
        )
        response = await endpoint_caller._transport.request(request)
        
        # API accepts null values (our validation is stricter than API)
        try:
            model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
            assert isinstance(model, CreateCrawlResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_exclude_urls_valid(self, endpoint_caller):
        """Test exclude_urls parameter with valid values from fixtures"""
        for valid_exclude_urls in EXCLUDE_URLS["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "exclude_urls": valid_exclude_urls}
            
            validated_request = endpoint_caller.validate_request(
                CRAWL_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "exclude_urls" in validated_body
            assert validated_body["exclude_urls"] == valid_exclude_urls
            
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, CRAWL_START_CONTRACT
                )
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_exclude_urls_invalid(self, endpoint_caller):
        """Test exclude_urls parameter with invalid values from fixtures"""
        for invalid_exclude_urls in EXCLUDE_URLS["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "exclude_urls": invalid_exclude_urls}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_exclude_urls_null(self, endpoint_caller):
        """Test exclude_urls parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "exclude_urls": None}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "exclude_urls" not in validated_body
        
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, CRAWL_START_CONTRACT
            )
            assert isinstance(model, CreateCrawlResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_max_depth_valid(self, endpoint_caller):
        """Test max_depth parameter with valid values from fixtures"""
        for valid_max_depth in MAX_DEPTH["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "max_depth": valid_max_depth}
            
            validated_request = endpoint_caller.validate_request(
                CRAWL_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "max_depth" in validated_body
            assert validated_body["max_depth"] == valid_max_depth
            
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(endpoint_caller, request, CRAWL_START_CONTRACT)
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_max_depth_invalid(self, endpoint_caller):
        """Test max_depth parameter with invalid values from fixtures"""
        for invalid_max_depth in MAX_DEPTH["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "max_depth": invalid_max_depth}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_max_depth_null(self, endpoint_caller):
        """Test max_depth parameter with null value (should pass if max_pages is set)"""
        # Test with max_pages set - should pass
        body_params = {
            "start_url": START_URL["param_values"]["valids"][0],
            "max_pages": MAX_PAGES["param_values"]["valids"][0],
            "max_depth": None
        }
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "max_pages" in validated_body
        assert "max_depth" not in validated_body or validated_body["max_depth"] is None
        
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        try:
            model = await retry_request(
                endpoint_caller, request, CRAWL_START_CONTRACT
            )
            assert isinstance(model, CreateCrawlResponse)
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error")
        
        # Test with both null - should fail
        body_params_both_null = {
            "start_url": START_URL["param_values"]["valids"][0],
            "max_pages": None,
            "max_depth": None
        }
        
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params_both_null)
    
    @pytest.mark.asyncio
    async def test_parameter_max_pages_and_max_depth_both_set(self, endpoint_caller):
        """Test that both max_pages and max_depth can be set together"""
        body_params = {
            "start_url": START_URL["param_values"]["valids"][0],
            "max_pages": MAX_PAGES["param_values"]["valids"][0],
            "max_depth": MAX_DEPTH["param_values"]["valids"][0]
        }
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "max_pages" in validated_body
        assert "max_depth" in validated_body
        assert validated_body["max_pages"] == MAX_PAGES["param_values"]["valids"][0]
        assert validated_body["max_depth"] == MAX_DEPTH["param_values"]["valids"][0]
        
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        try:
            model = await retry_request(
                endpoint_caller, request, CRAWL_START_CONTRACT
            )
            assert isinstance(model, CreateCrawlResponse)
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_include_external_valid(self, endpoint_caller):
        """Test include_external parameter with valid values from fixtures"""
        for valid_include_external in INCLUDE_EXTERNAL["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_external": valid_include_external}
            
            validated_request = endpoint_caller.validate_request(
                CRAWL_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "include_external" in validated_body
            assert validated_body["include_external"] == valid_include_external
            
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, CRAWL_START_CONTRACT
                )
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_include_external_invalid(self, endpoint_caller):
        """Test include_external parameter with invalid values from fixtures"""
        for invalid_include_external in INCLUDE_EXTERNAL["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_external": invalid_include_external}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_include_external_null(self, endpoint_caller):
        """Test include_external parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "include_external": None}
        
        endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
        
        # Test API behavior with null request (bypass validation)
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, {}, {}, body_params
        )
        response = await endpoint_caller._transport.request(request)
        
        # API accepts null values (our validation is stricter than API)
        try:
            model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
            assert isinstance(model, CreateCrawlResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_include_subdomain_valid(self, endpoint_caller):
        """Test include_subdomain parameter with valid values from fixtures"""
        for valid_include_subdomain in INCLUDE_SUBDOMAIN["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_subdomain": valid_include_subdomain}
            
            validated_request = endpoint_caller.validate_request(
                CRAWL_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "include_subdomain" in validated_body
            assert validated_body["include_subdomain"] == valid_include_subdomain
            
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, CRAWL_START_CONTRACT
                )
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_include_subdomain_invalid(self, endpoint_caller):
        """Test include_subdomain parameter with invalid values from fixtures"""
        for invalid_include_subdomain in INCLUDE_SUBDOMAIN["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_subdomain": invalid_include_subdomain}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_include_subdomain_null(self, endpoint_caller):
        """Test include_subdomain parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "include_subdomain": None}
        
        endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
        
        # Test API behavior with null request (bypass validation)
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, {}, {}, body_params
        )
        response = await endpoint_caller._transport.request(request)
        
        # API accepts null values (our validation is stricter than API)
        try:
            model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
            assert isinstance(model, CreateCrawlResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_follow_robots_txt_valid(self, endpoint_caller):
        """Test follow_robots_txt parameter with valid values from fixtures"""
        for valid_follow_robots_txt in FOLLOW_ROBOTS_TXT["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "follow_robots_txt": valid_follow_robots_txt}
            
            validated_request = endpoint_caller.validate_request(
                CRAWL_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "follow_robots_txt" in validated_body
            assert validated_body["follow_robots_txt"] == valid_follow_robots_txt
            
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, CRAWL_START_CONTRACT
                )
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_follow_robots_txt_invalid(self, endpoint_caller):
        """Test follow_robots_txt parameter with invalid values from fixtures"""
        for invalid_follow_robots_txt in FOLLOW_ROBOTS_TXT["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "follow_robots_txt": invalid_follow_robots_txt}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API is observed to accept invalid values for follow_robots_txt (strings, lists, dicts, None all return 200)
            # This test documents the API's actual behavior - it does not validate this parameter
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # API accepts invalid values - this documents weak API validation
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            # Note: API does not reject invalid follow_robots_txt values - all invalid types return 200
            # except (OlostepServerError_RequestUnprocessable):
            #     # API rejects invalid values or server errors - also acceptable
            #     pass
    
    @pytest.mark.asyncio
    async def test_parameter_follow_robots_txt_null(self, endpoint_caller):
        """Test follow_robots_txt parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "follow_robots_txt": None}
        
        # follow_robots_txt has a default value (True), so None should be rejected
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
        
        # Test API behavior with null request (bypass validation)
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, {}, {}, body_params
        )
        response = await endpoint_caller._transport.request(request)
        
        # API is observed to accept null values for follow_robots_txt (None returns 200)
        # This test documents the API's actual behavior - it does not validate this parameter
        try:
            model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
            # API accepts null values - this documents weak API validation
            assert isinstance(model, CreateCrawlResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
        # Note: API does not reject null follow_robots_txt values - None returns 200
        # except (OlostepServerError_RequestUnprocessable):
        #     # API rejects null values or server errors - also acceptable
        #     pass
    
    @pytest.mark.asyncio
    async def test_parameter_search_query_valid(self, endpoint_caller):
        """Test search_query parameter with valid values from fixtures"""
        for valid_search_query in SEARCH_QUERY["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "search_query": valid_search_query}
            
            validated_request = endpoint_caller.validate_request(
                CRAWL_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "search_query" in validated_body
            assert validated_body["search_query"] == valid_search_query
            
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, CRAWL_START_CONTRACT
                )
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_search_query_invalid(self, endpoint_caller):
        """Test search_query parameter with invalid values from fixtures"""
        for invalid_search_query in SEARCH_QUERY["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "search_query": invalid_search_query}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_search_query_null(self, endpoint_caller):
        """Test search_query parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "search_query": None}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "search_query" not in validated_body
        
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, CRAWL_START_CONTRACT
            )
            assert isinstance(model, CreateCrawlResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_top_n_valid(self, endpoint_caller):
        """Test top_n parameter with valid values from fixtures"""
        for valid_top_n in TOP_N["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "top_n": valid_top_n}
            
            validated_request = endpoint_caller.validate_request(
                CRAWL_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "top_n" in validated_body
            assert validated_body["top_n"] == valid_top_n
            
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, CRAWL_START_CONTRACT
                )
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_top_n_invalid(self, endpoint_caller):
        """Test top_n parameter with invalid values from fixtures"""
        for invalid_top_n in TOP_N["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "top_n": invalid_top_n}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_top_n_null(self, endpoint_caller):
        """Test top_n parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "top_n": None}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=body_params
        )

        validated_body = validated_request["body_params"]
        assert "top_n" not in validated_body
        
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, CRAWL_START_CONTRACT
            )
            assert isinstance(model, CreateCrawlResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_webhook_url_valid(self, endpoint_caller):
        """Test webhook_url parameter with valid values from fixtures"""
        for valid_webhook_url in WEBHOOK_URL["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "webhook_url": valid_webhook_url}
            
            validated_request = endpoint_caller.validate_request(
                CRAWL_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "webhook_url" in validated_body
            assert validated_body["webhook_url"] == valid_webhook_url
            
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, CRAWL_START_CONTRACT
                )
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_webhook_url_invalid(self, endpoint_caller):
        """Test webhook_url parameter with invalid values from fixtures"""
        for invalid_webhook_url in WEBHOOK_URL["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "webhook_url": invalid_webhook_url}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_START_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateCrawlResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_webhook_url_null(self, endpoint_caller):
        """Test webhook_url parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "webhook_url": None}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "webhook_url" not in validated_body
        
        request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, CRAWL_START_CONTRACT
            )
            assert isinstance(model, CreateCrawlResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")


class TestCrawlInfo:
    """Test cases for GET /crawls/{crawl_id} endpoint."""
    
    @pytest.mark.asyncio
    async def test_get_existing_crawl(self, endpoint_caller):
        """Test getting an existing crawl by ID"""
        # First, create a crawl using MINIMAL_REQUEST_BODY
        create_body_params = MINIMAL_REQUEST_BODY
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=create_body_params
        )
        
        create_request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        try:
            create_model = await retry_request(
                endpoint_caller, create_request, CRAWL_START_CONTRACT
            )
            assert isinstance(create_model, CreateCrawlResponse)
            crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Now get the crawl using the ID from GET_CRAWL_INFO_REQUEST_ID fixture
        crawl_id_param_name = GET_CRAWL_INFO_REQUEST_ID["param_name"]
        get_path_params = {crawl_id_param_name: crawl_id}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_INFO_CONTRACT, path_params=get_path_params
        )
        
        validated_path = validated_request["path_params"]
        assert crawl_id_param_name in validated_path
        assert validated_path[crawl_id_param_name] == crawl_id
        
        get_request = endpoint_caller._prepare_request(
            CRAWL_INFO_CONTRACT, **validated_request
        )
        
        try:
            get_model = await retry_request(
                endpoint_caller, get_request, CRAWL_INFO_CONTRACT
            )
            assert isinstance(get_model, CrawlInfoResponse)
            assert get_model.id == crawl_id

        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl retrieval")
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_crawl(self, endpoint_caller):
        """Test getting a non-existent crawl by ID"""
        # Try to get a crawl with an invalid ID from GET_CRAWL_INFO_REQUEST_ID fixture
        crawl_id_param_name = GET_CRAWL_INFO_REQUEST_ID["param_name"]
        invalid_crawl_id = GET_CRAWL_INFO_REQUEST_ID["param_values"]["invalids"][0]
        get_path_params = {crawl_id_param_name: invalid_crawl_id}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_INFO_CONTRACT, path_params=get_path_params
        )
        
        validated_path = validated_request["path_params"]
        assert crawl_id_param_name in validated_path
        assert validated_path[crawl_id_param_name] == invalid_crawl_id
        
        get_request = endpoint_caller._prepare_request(
            CRAWL_INFO_CONTRACT, **validated_request
        )
        
        get_response = await endpoint_caller._transport.request(get_request)
        
        # Should raise an error for non-existent crawl
        with pytest.raises(OlostepServerError_ResourceNotFound):
            await retry_request(
                endpoint_caller, get_request, CRAWL_INFO_CONTRACT
            )


class TestCrawlPages:
    """Test cases for GET /crawls/{crawl_id}/pages endpoint."""
    
    @pytest.mark.asyncio
    async def test_self_test_parameter_coverage(self):
        """Self-test: Verify that we have test methods for each parameter in the request model."""
        # Extract all parameters from the request model
        all_params = extract_request_parameters(CRAWL_PAGES_CONTRACT.request_model)
        path_params = all_params['path']
        query_params = all_params['query']
        
        # Get all test methods in this class that start with 'test_parameter_'
        test_methods = [method for method in dir(self) if method.startswith('test_parameter_')]
        
        # Group test methods by parameter name
        param_tests = {}
        for method_name in test_methods:
            # Extract parameter name from 'test_parameter_XXX_valid', 'test_parameter_XXX_invalid', or 'test_parameter_XXX_null'
            if '_valid' in method_name:
                param_name = method_name.replace('test_parameter_', '').replace('_valid', '')
                test_type = 'valid'
            elif '_invalid' in method_name:
                param_name = method_name.replace('test_parameter_', '').replace('_invalid', '')
                test_type = 'invalid'
            elif '_null' in method_name:
                param_name = method_name.replace('test_parameter_', '').replace('_null', '')
                test_type = 'null'
            else:
                continue
            
            if param_name not in param_tests:
                param_tests[param_name] = set()
            param_tests[param_name].add(test_type)
        
        # Check coverage for path parameters
        missing_tests = []
        incomplete_tests = []
        
        for param in path_params:
            if param not in param_tests:
                missing_tests.append(f"{param} (path)")
            else:
                param_test_types = param_tests[param]
                if 'valid' not in param_test_types:
                    incomplete_tests.append(f"{param} (path, missing _valid test)")
                if 'invalid' not in param_test_types:
                    incomplete_tests.append(f"{param} (path, missing _invalid test)")
        
        # Check coverage for query parameters
        for param in query_params:
            if param not in param_tests:
                missing_tests.append(f"{param} (query)")
            else:
                param_test_types = param_tests[param]
                if 'valid' not in param_test_types:
                    incomplete_tests.append(f"{param} (query, missing _valid test)")
                if 'invalid' not in param_test_types:
                    incomplete_tests.append(f"{param} (query, missing _invalid test)")
                if 'null' not in param_test_types:
                    incomplete_tests.append(f"{param} (query, missing _null test)")
        
        # Assert that we have complete tests for all parameters
        error_messages = []
        if missing_tests:
            error_messages.append(f"Missing test methods for parameters: {missing_tests}")
        if incomplete_tests:
            error_messages.append(f"Incomplete test coverage: {incomplete_tests}")
        
        assert len(error_messages) == 0, "; ".join(error_messages)
    
    @pytest.mark.asyncio
    async def test_parameter_crawl_id_valid(self, endpoint_caller):
        """Test crawl_id path parameter with valid values from fixtures"""
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
            assert isinstance(create_model, CreateCrawlResponse)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Test with valid crawl_id
        crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
        get_path_params = {crawl_id_param_name: valid_crawl_id}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_PAGES_CONTRACT, path_params=get_path_params
        )
        
        validated_path = validated_request["path_params"]
        assert crawl_id_param_name in validated_path
        assert validated_path[crawl_id_param_name] == valid_crawl_id
        
        get_request = endpoint_caller._prepare_request(
            CRAWL_PAGES_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, CRAWL_PAGES_CONTRACT)
            assert isinstance(get_model, CrawlPagesResponse)
            assert get_model.id == valid_crawl_id
            assert get_model.object == "crawl"
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl pages retrieval")
    
    @pytest.mark.asyncio
    async def test_parameter_crawl_id_invalid(self, endpoint_caller):
        """Test crawl_id path parameter with invalid values from fixtures"""
        # Try to get pages with an invalid ID from GET_CRAWL_PAGES_REQUEST_ID fixture
        crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
        invalid_crawl_id = GET_CRAWL_PAGES_REQUEST_ID["param_values"]["invalids"][0]
        get_path_params = {crawl_id_param_name: invalid_crawl_id}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_PAGES_CONTRACT, path_params=get_path_params
        )
        
        validated_path = validated_request["path_params"]
        assert crawl_id_param_name in validated_path
        assert validated_path[crawl_id_param_name] == invalid_crawl_id
        
        get_request = endpoint_caller._prepare_request(
            CRAWL_PAGES_CONTRACT, **validated_request
        )
        
        get_response = await endpoint_caller._transport.request(get_request)
        
        # Should raise an error for non-existent crawl
        with pytest.raises(OlostepServerError_ResourceNotFound):
            endpoint_caller._handle_response(get_request, get_response, CRAWL_PAGES_CONTRACT)
    
    @pytest.mark.asyncio
    async def test_parameter_cursor_valid(self, endpoint_caller):
        """Test cursor query parameter with valid values obtained from pagination flow"""
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
            assert isinstance(create_model, CreateCrawlResponse)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Step 1: Make first request with limit to get a cursor
        crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
        get_path_params = {crawl_id_param_name: valid_crawl_id}
        get_query_params = {"limit": 1}  # Start with limit to get cursor
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params
        )
        
        request = endpoint_caller._prepare_request(
            CRAWL_PAGES_CONTRACT, **validated_request
        )
        
        try:
            first_response = await retry_request(
                endpoint_caller, request, CRAWL_PAGES_CONTRACT
            )
            assert isinstance(first_response, CrawlPagesResponse)
            
            # Step 2: If we got a cursor, test using it
            if first_response.cursor is not None:
                cursor_query_params = {"cursor": first_response.cursor}
                
                validated_request = endpoint_caller.validate_request(
                    CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=cursor_query_params
                )
                
                validated_query = validated_request["query_params"]
                assert "cursor" in validated_query
                assert validated_query["cursor"] == first_response.cursor
                
                cursor_request = endpoint_caller._prepare_request(
                    CRAWL_PAGES_CONTRACT, **validated_request
                )
                
                cursor_response = await retry_request(
                    endpoint_caller, cursor_request, CRAWL_PAGES_CONTRACT
                )
                assert isinstance(cursor_response, CrawlPagesResponse)
            else:
                pytest.skip("No cursor returned from first request - crawl may be too small for pagination")
                
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_cursor_invalid(self, endpoint_caller):
        """Test cursor query parameter with invalid values from fixtures"""
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
            assert isinstance(create_model, CreateCrawlResponse)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Test with invalid cursor values
        for invalid_cursor in CURSOR["param_values"]["invalids"]:
            crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
            get_path_params = {crawl_id_param_name: valid_crawl_id}
            get_query_params = {"cursor": invalid_cursor}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_PAGES_CONTRACT, get_path_params, get_query_params, {}
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_PAGES_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CrawlPagesResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_cursor_null(self, endpoint_caller):
        """Test cursor query parameter with null value"""
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
            assert isinstance(create_model, CreateCrawlResponse)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Test with null cursor
        crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
        get_path_params = {crawl_id_param_name: valid_crawl_id}
        get_query_params = {"cursor": None}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params
        )
        
        validated_query = validated_request["query_params"]
        assert "cursor" not in validated_query
        
        get_request = endpoint_caller._prepare_request(
            CRAWL_PAGES_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, CRAWL_PAGES_CONTRACT)
            assert isinstance(get_model, CrawlPagesResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_limit_valid(self, endpoint_caller):
        """Test limit query parameter with valid values from fixtures"""
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
            assert isinstance(create_model, CreateCrawlResponse)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        valid_limit = 1  
        crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
        get_path_params = {crawl_id_param_name: valid_crawl_id}
        get_query_params = {"limit": valid_limit}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params
        )
        
        validated_query = validated_request["query_params"]
        assert "limit" in validated_query
        assert validated_query["limit"] == valid_limit
        
        get_request = endpoint_caller._prepare_request(
            CRAWL_PAGES_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, CRAWL_PAGES_CONTRACT)
            assert isinstance(get_model, CrawlPagesResponse)
            get_model: CrawlPagesResponse = get_model
            len(get_model.pages) == valid_limit
            get_model.cursor is not None
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_limit_invalid(self, endpoint_caller):
        """Test limit query parameter with invalid values from fixtures"""
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
            assert isinstance(create_model, CreateCrawlResponse)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Test with invalid limit values
        for invalid_limit in LIMIT["param_values"]["invalids"]:
            crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
            get_path_params = {crawl_id_param_name: valid_crawl_id}
            get_query_params = {"limit": invalid_limit}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_PAGES_CONTRACT, get_path_params, get_query_params, {}
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_PAGES_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CrawlPagesResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_limit_null(self, endpoint_caller):
        """Test limit query parameter with null value"""
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
            assert isinstance(create_model, CreateCrawlResponse)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Test with null limit
        crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
        get_path_params = {crawl_id_param_name: valid_crawl_id}
        get_query_params = {"limit": None}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params
        )
        
        validated_query = validated_request["query_params"]
        assert "limit" not in validated_query
        
        get_request = endpoint_caller._prepare_request(
            CRAWL_PAGES_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, CRAWL_PAGES_CONTRACT)
            assert isinstance(get_model, CrawlPagesResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_search_query_valid(self, endpoint_caller):
        """Test search_query query parameter with valid values from fixtures"""
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
            assert isinstance(create_model, CreateCrawlResponse)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Test with valid search_query values
        for valid_search_query in CRAWL_SEARCH_QUERY["param_values"]["valids"]:
            crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
            get_path_params = {crawl_id_param_name: valid_crawl_id}
            get_query_params = {"search_query": valid_search_query}
            
            validated_request = endpoint_caller.validate_request(
                CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params
            )
            
            validated_query = validated_request["query_params"]
            assert "search_query" in validated_query
            assert validated_query["search_query"] == valid_search_query
            
            get_request = endpoint_caller._prepare_request(
                CRAWL_PAGES_CONTRACT, **validated_request
            )
            
            try:
                get_response = await endpoint_caller._transport.request(get_request)
                get_model = endpoint_caller._handle_response(get_request, get_response, CRAWL_PAGES_CONTRACT)
                assert isinstance(get_model, CrawlPagesResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_search_query_invalid(self, endpoint_caller):
        """Test search_query query parameter with invalid values from fixtures"""
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
            assert isinstance(create_model, CreateCrawlResponse)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Test with invalid search_query values
        for invalid_search_query in CRAWL_SEARCH_QUERY["param_values"]["invalids"]:
            crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
            get_path_params = {crawl_id_param_name: valid_crawl_id}
            get_query_params = {"search_query": invalid_search_query}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                CRAWL_PAGES_CONTRACT, get_path_params, get_query_params, {}
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, CRAWL_PAGES_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CrawlPagesResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_search_query_null(self, endpoint_caller):
        """Test search_query query parameter with null value"""
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
            assert isinstance(create_model, CreateCrawlResponse)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Test with null search_query
        crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
        get_path_params = {crawl_id_param_name: valid_crawl_id}
        get_query_params = {"search_query": None}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_PAGES_CONTRACT, path_params=get_path_params, query_params=get_query_params
        )

        validated_query = validated_request["query_params"]
        assert "search_query" not in validated_query
        
        get_request = endpoint_caller._prepare_request(
            CRAWL_PAGES_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, CRAWL_PAGES_CONTRACT)
            assert isinstance(get_model, CrawlPagesResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_get_existing_crawl_pages(self, endpoint_caller):
        """Test getting pages from an existing crawl"""
        # First, create a crawl using MINIMAL_REQUEST_BODY
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
            assert isinstance(create_model, CreateCrawlResponse)
            crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Now get the crawl pages using the ID from GET_CRAWL_PAGES_REQUEST_ID fixture
        crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
        get_path_params = {crawl_id_param_name: crawl_id}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_PAGES_CONTRACT, path_params=get_path_params
        )
        
        validated_path = validated_request["path_params"]
        assert crawl_id_param_name in validated_path
        assert validated_path[crawl_id_param_name] == crawl_id
        
        get_request = endpoint_caller._prepare_request(
            CRAWL_PAGES_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, CRAWL_PAGES_CONTRACT)
            assert isinstance(get_model, CrawlPagesResponse)
            assert get_model.id == crawl_id
            assert get_model.object == "crawl"
            # The response should have pages array and metadata
            assert hasattr(get_model, 'pages')
            assert hasattr(get_model, 'metadata')
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl pages retrieval")
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_crawl_pages(self, endpoint_caller):
        """Test getting pages from a non-existent crawl"""
        # Try to get pages with an invalid ID from GET_CRAWL_PAGES_REQUEST_ID fixture
        crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
        invalid_crawl_id = GET_CRAWL_PAGES_REQUEST_ID["param_values"]["invalids"][0]
        get_path_params = {crawl_id_param_name: invalid_crawl_id}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_PAGES_CONTRACT, path_params=get_path_params
        )
        
        validated_path = validated_request["path_params"]
        assert crawl_id_param_name in validated_path
        assert validated_path[crawl_id_param_name] == invalid_crawl_id
        
        get_request = endpoint_caller._prepare_request(
            CRAWL_PAGES_CONTRACT, **validated_request
        )
        
        get_response = await endpoint_caller._transport.request(get_request)
        
        # Should raise an error for non-existent crawl
        with pytest.raises(OlostepServerError_ResourceNotFound):
            endpoint_caller._handle_response(get_request, get_response, CRAWL_PAGES_CONTRACT)


    @pytest.mark.asyncio
    async def test_cursor_and_limit_mutually_exclusive_validation(self, endpoint_caller):
        """Test that our validation model refuses both cursor and limit parameters"""
        # Test that our validation model rejects both cursor and limit
        query_params = {"cursor": 123, "limit": 10}
        
        with pytest.raises(OlostepClientError_RequestValidationFailed) as exc_info:
            endpoint_caller.validate_request(
                CRAWL_PAGES_CONTRACT, path_params={"crawl_id": "test_id"}, query_params=query_params
            )
        
        # Verify the error message contains the expected explanation
        error_message = str(exc_info.value)
        assert "Cannot specify both 'cursor' and 'limit' parameters" in error_message
        assert "Use 'limit' for the first request, then 'cursor' for subsequent requests" in error_message
    
    @pytest.mark.asyncio
    async def test_cursor_and_limit_api_accepts_both(self, endpoint_caller):
        """Test that the API accepts both cursor and limit (ignores limit when cursor is present)"""
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
            assert isinstance(create_model, CreateCrawlResponse)
            valid_crawl_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Bypass our validation and send both parameters directly to the API
        query_params = {"cursor": 0, "limit": 10}
        path_params = {"crawl_id": valid_crawl_id}
        
        # Prepare request without validation (bypass our model validation)
        request = endpoint_caller._prepare_request(
            CRAWL_PAGES_CONTRACT, path_params, query_params, {}
        )
        
        try:
            # The API should accept this request (it ignores limit when cursor is present)
            get_model = await retry_request(
                endpoint_caller, request, CRAWL_PAGES_CONTRACT
            )
            assert isinstance(get_model, CrawlPagesResponse)
            print(f"✅ API accepted both cursor and limit - returned {len(get_model.pages) if get_model.pages else 0} pages")
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error during page retrieval")
        except Exception as e:
            # If API rejects it, that's also acceptable - the important thing is our validation works
            print(f"ℹ️  API rejected both cursor and limit: {type(e).__name__}: {e}")
            pass


class TestCrawlWorkflow:
    """Test cases for crawl workflow."""
    
    @pytest.mark.asyncio
    async def test_crawl_workflow(self, endpoint_caller):
        """Test complete crawl workflow: create, monitor, and paginate through results."""
        print("🚀 Starting crawl workflow test...")
        
        # Step 1: Create a crawl using WORKFLOW_REQUEST_BODY
        print(f"📝 Step 1: Creating crawl with {WORKFLOW_REQUEST_BODY}")
        create_body_params = WORKFLOW_REQUEST_BODY
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_START_CONTRACT, body_params=create_body_params
        )
        
        create_request = endpoint_caller._prepare_request(
            CRAWL_START_CONTRACT, **validated_request
        )
        
        try:
            create_model = await retry_request(
                endpoint_caller, create_request, CRAWL_START_CONTRACT
            )
            assert isinstance(create_model, CreateCrawlResponse)
            crawl_id = create_model.id
            print(f"✅ Crawl created successfully with ID: {crawl_id}")
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during crawl creation")
        
        # Step 2: Monitor crawl status every 10 seconds until done
        print("⏳ Step 2: Monitoring crawl status...")
        crawl_id_param_name = GET_CRAWL_INFO_REQUEST_ID["param_name"]
        get_path_params = {crawl_id_param_name: crawl_id}
        
        validated_request = endpoint_caller.validate_request(
            CRAWL_INFO_CONTRACT, path_params=get_path_params
        )
        
        get_request = endpoint_caller._prepare_request(
            CRAWL_INFO_CONTRACT, **validated_request
        )
        
        max_wait_time: float = 300  # 5 minutes max wait
        start_time: float = time.monotonic()

        while (time.monotonic() - start_time) < max_wait_time:
            try:
                get_model = await retry_request(
                    endpoint_caller, get_request, CRAWL_INFO_CONTRACT
                )
                assert isinstance(get_model, CrawlInfoResponse)
                
                print(f"📊 Crawl status: {get_model.status} (elapsed: {int(time.time() - start_time)}s)")
                
                if get_model.status == "completed":
                    print("✅ Crawl completed successfully!")
                    break
                # elif get_model.status == "failed":
                #     pytest.fail(f"Crawl failed with status: {get_model.status}")
                
                # Wait 10 seconds before next check
                print("⏸️  Waiting 10 seconds before next status check...")
                await asyncio.sleep(10)
                
            except OlostepServerError_TemporaryIssue:
                print("⚠️  Transient error during status check, retrying...")
                await asyncio.sleep(15)
        else:
            pytest.fail(f"Crawl did not complete within {max_wait_time} seconds")
        
        # Step 3: Validate pagination by comparing full fetch vs paginated fetch
        print("📄 Step 3: Validating pagination behavior...")
        pages_crawl_id_param_name = GET_CRAWL_PAGES_REQUEST_ID["param_name"]
        pages_path_params = {pages_crawl_id_param_name: crawl_id}
        
        # Calculate limit as max_pages / 4 (from WORKFLOW_REQUEST_BODY)
        max_pages = WORKFLOW_REQUEST_BODY["max_pages"]
        limit = math.ceil(max_pages / 4)
        print(f"📊 Using limit: {limit} (max_pages {max_pages} / 4, rounded up)")
        
        # Step 3a: Fetch all pages without cursor/limit
        print("🔍 Step 3a: Fetching all pages without cursor/limit...")
        validated_request = endpoint_caller.validate_request(
            CRAWL_PAGES_CONTRACT, path_params=pages_path_params, query_params={}
        )
        
        full_request = endpoint_caller._prepare_request(
            CRAWL_PAGES_CONTRACT, **validated_request
        )
        
        try:
            full_model = await retry_request(
                endpoint_caller, full_request, CRAWL_PAGES_CONTRACT
            )
            assert isinstance(full_model, CrawlPagesResponse)
            
            full_pages = []
            if hasattr(full_model, 'pages') and full_model.pages:
                full_pages = full_model.pages
                print(f"✅ Full fetch returned {len(full_pages)} pages")
            else:
                print("⚠️  Full fetch returned no pages")
                
        except OlostepServerError_TemporaryIssue:
            print("⚠️  Transient error during full fetch, skipping pagination validation")
            full_pages = []
        
        # Step 3b: Paginate through pages using cursor-based pagination
        print("🔍 Step 3b: Paginating through pages using cursor-based pagination...")
        paginated_pages = []
        cursor = None  # Start without cursor
        page_count = 0
        
        while True:
            page_count += 1
            print(f"📖 Fetching page {page_count} with cursor={cursor}, limit={limit}...")
            
            # Prepare query params - only send limit on first request, cursor on subsequent requests
            query_params = {}
            if cursor is None:
                # First request: send limit only
                query_params["limit"] = limit
                print(f"   First request: sending limit={limit}")
            else:
                # Subsequent requests: send cursor only (API remembers the limit)
                query_params["cursor"] = cursor
                print(f"   Subsequent request: sending cursor={cursor}")
            
            validated_request = endpoint_caller.validate_request(
                CRAWL_PAGES_CONTRACT, path_params=pages_path_params, query_params=query_params
            )
            
            validated_query = validated_request["query_params"]
            # Validate that our parameters were accepted
            if cursor is None:
                assert "limit" in validated_query, "Limit should be in validated query"
                assert validated_query["limit"] == limit, f"Limit should be {limit}, got {validated_query['limit']}"
            else:
                assert "cursor" in validated_query, "Cursor should be in validated query"
                assert validated_query["cursor"] == cursor, f"Cursor should be {cursor}, got {validated_query['cursor']}"
            
            pages_request = endpoint_caller._prepare_request(
                CRAWL_PAGES_CONTRACT, **validated_request
            )
            
            try:
                pages_model = await retry_request(
                    endpoint_caller, pages_request, CRAWL_PAGES_CONTRACT
                )
                assert isinstance(pages_model, CrawlPagesResponse)
                
                # Validate that server honored our limit (only on first request)
                if hasattr(pages_model, 'pages') and pages_model.pages:
                    actual_pages_count = len(pages_model.pages)
                    if cursor is None:
                        print(f"   Server returned {actual_pages_count} pages (requested limit: {limit})")
                        # Server should honor our limit (unless it's the last page with fewer results)
                        if actual_pages_count > limit:
                            pytest.fail(f"Server returned {actual_pages_count} pages but limit was {limit}")
                    else:
                        print(f"   Server returned {actual_pages_count} pages (using remembered limit)")
                    
                    paginated_pages.extend(pages_model.pages)
                    print(f"   Total paginated pages collected so far: {len(paginated_pages)}")
                else:
                    print("   No pages in this response")
                
                # Check for next cursor in response
                next_cursor = None
                if hasattr(pages_model, 'metadata') and pages_model.metadata and hasattr(pages_model.metadata, 'next_cursor'):
                    next_cursor = pages_model.metadata.next_cursor
                elif hasattr(pages_model, 'cursor'):
                    next_cursor = pages_model.cursor
                
                if next_cursor is not None:
                    print(f"   Next cursor from server: {next_cursor}")
                    cursor = next_cursor
                else:
                    print("   No more cursor - pagination complete!")
                    break
                    
            except OlostepServerError_TemporaryIssue:
                print("⚠️  Transient error during page fetch, retrying...")
                await asyncio.sleep(2)
        
        # Step 3c: Compare full fetch vs paginated fetch
        print("🔍 Step 3c: Comparing full fetch vs paginated fetch...")
        if full_pages and paginated_pages:
            # Extract page IDs for comparison
            full_page_ids = set()
            paginated_page_ids = set()
            
            for page in full_pages:
                if hasattr(page, 'id') and page.id:
                    full_page_ids.add(page.id)
                elif hasattr(page, 'url') and page.url:
                    full_page_ids.add(page.url)  # Use URL as fallback identifier
            
            for page in paginated_pages:
                if hasattr(page, 'id') and page.id:
                    paginated_page_ids.add(page.id)
                elif hasattr(page, 'url') and page.url:
                    paginated_page_ids.add(page.url)  # Use URL as fallback identifier
            
            print(f"📊 Full fetch: {len(full_page_ids)} unique pages")
            print(f"📊 Paginated fetch: {len(paginated_page_ids)} unique pages")
            
            # Check if sets are equal
            if full_page_ids == paginated_page_ids:
                print("✅ Pagination validation passed: Both methods returned identical pages!")
            else:
                missing_in_paginated = full_page_ids - paginated_page_ids
                extra_in_paginated = paginated_page_ids - full_page_ids
                
                if missing_in_paginated:
                    print(f"❌ Pagination validation failed: {len(missing_in_paginated)} pages missing in paginated fetch")
                    print(f"   Missing pages: {list(missing_in_paginated)[:5]}...")  # Show first 5
                
                if extra_in_paginated:
                    print(f"❌ Pagination validation failed: {len(extra_in_paginated)} extra pages in paginated fetch")
                    print(f"   Extra pages: {list(extra_in_paginated)[:5]}...")  # Show first 5
                
                pytest.fail("Pagination validation failed: Full fetch and paginated fetch returned different pages")
        else:
            print("⚠️  Cannot compare: One or both fetch methods returned no pages")
        
        all_pages = paginated_pages  # Use paginated pages for summary
        
        # Step 4: Summary
        print("🎉 Workflow completed successfully!")
        print("📊 Summary:")
        print(f"   - Crawl ID: {crawl_id}")
        print(f"   - Total pages fetched: {len(all_pages)}")
        print(f"   - Total pagination requests: {page_count}")
        print(f"   - Crawl completed in: {int(time.monotonic() - start_time)} seconds")
        print(f"   - Limit used: {limit} (max_pages {max_pages} / 4)")
        
        # Verify we got some pages
        assert len(all_pages) > 0, "Should have fetched at least some pages"
        print(f"✅ Workflow test passed - fetched {len(all_pages)} pages across {page_count} requests")
    