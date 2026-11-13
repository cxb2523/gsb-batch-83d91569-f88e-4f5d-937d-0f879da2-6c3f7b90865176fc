"""
Map endpoint contract validation tests.

This test suite validates map endpoint contracts against the API using httpx transport directly.
"""

import pytest

from olostep.backend.api_endpoints import CONTRACTS
from olostep.errors import (
    OlostepClientError_RequestValidationFailed,
    OlostepServerError_RequestUnprocessable,
    OlostepServerError_ResourceNotFound,
    OlostepServerError_TemporaryIssue,
)
from olostep.models.response import MapResponse
from tests.conftest import extract_request_parameters, retry_request
from tests.fixtures.api.requests.map import (
    CURSOR,
    EXCLUDE_URLS,
    INCLUDE_SUBDOMAIN,
    INCLUDE_URLS,
    MINIMAL_REQUEST_BODY,
    PAGINATION_REQUEST_BODY,
    SEARCH_QUERY,
    TOP_N,
    URL,
)

MAP_CREATE_CONTRACT = CONTRACTS[('map', 'create')]

BASE_URL = "https://api.olostep.com/v1"


class TestMapCreate:
    """Test map create with various parameter combinations."""
    
    @pytest.mark.asyncio
    async def test_self_test_parameter_coverage(self):
        """Self-test: Verify that we have test methods for each parameter in the request model."""
        # Extract all parameters from the request model
        all_params = extract_request_parameters(MAP_CREATE_CONTRACT.request_model)
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
        }
        
        # Our validation should refuse this request due to the unknown parameters
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(MAP_CREATE_CONTRACT, body_params=body_params)
        
        # But if we bypass validation and send it to the API anyway, the API should ignore the unknown parameters
        request = endpoint_caller._prepare_request(
            MAP_CREATE_CONTRACT, {}, {}, body_params
        )
        
        # The API should accept the request and ignore the unknown parameters
        try:
            model = await retry_request(
                endpoint_caller, request, MAP_CREATE_CONTRACT
            )
            assert isinstance(model, MapResponse)
            # Verify the response is valid despite the unknown parameters
            assert model.urls_count >= 0
            assert isinstance(model.urls, list)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_url_valid(self, endpoint_caller):
        """Test url parameter with valid values from fixtures"""
        for valid_url in URL["param_values"]["valids"]:
            body_params = {"url": valid_url}
            
            validated_request = endpoint_caller.validate_request(
                MAP_CREATE_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "url" in validated_body
            assert validated_body["url"] == valid_url
            
            request = endpoint_caller._prepare_request(
                MAP_CREATE_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, MAP_CREATE_CONTRACT
                )
                assert isinstance(model, MapResponse)
                assert model.urls_count >= 0
                assert isinstance(model.urls, list)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_url_invalid(self, endpoint_caller):
        """Test url parameter with invalid values from fixtures"""
        for invalid_url in URL["param_values"]["invalids"]:
            body_params = {"url": invalid_url}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(MAP_CREATE_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                MAP_CREATE_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, MAP_CREATE_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, MapResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejects invalid values or server errors - also acceptable
                pass
            except OlostepServerError_ResourceNotFound:
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_url_null(self, endpoint_caller):
        """Test url parameter with null value"""
        body_params = {"url": None}
        
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(MAP_CREATE_CONTRACT, body_params=body_params)
        
        # Test API behavior with null request (bypass validation)
        request = endpoint_caller._prepare_request(
            MAP_CREATE_CONTRACT, {}, {}, body_params
        )
        response = await endpoint_caller._transport.request(request)
        
        # API returns 500 error for this null requests
        with pytest.raises(OlostepServerError_RequestUnprocessable):
            endpoint_caller._handle_response(request, response, MAP_CREATE_CONTRACT)
    
    @pytest.mark.asyncio
    async def test_parameter_search_query_valid(self, endpoint_caller):
        """Test search_query parameter with valid values from fixtures"""
        for valid_query in SEARCH_QUERY["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "search_query": valid_query}
            
            validated_request = endpoint_caller.validate_request(
                MAP_CREATE_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "search_query" in validated_body
            assert validated_body["search_query"] == valid_query
            
            request = endpoint_caller._prepare_request(
                MAP_CREATE_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, MAP_CREATE_CONTRACT
                )
                assert isinstance(model, MapResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_search_query_invalid(self, endpoint_caller):
        """Test search_query parameter with invalid values from fixtures"""
        for invalid_query in SEARCH_QUERY["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "search_query": invalid_query}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(MAP_CREATE_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                MAP_CREATE_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, MAP_CREATE_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, MapResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejects invalid values or server errors - also acceptable
                pass
            except OlostepServerError_ResourceNotFound:
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_search_query_null(self, endpoint_caller):
        """Test search_query parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "search_query": None}
        
        validated_request = endpoint_caller.validate_request(
            MAP_CREATE_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "search_query" not in validated_body
        
        request = endpoint_caller._prepare_request(
            MAP_CREATE_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, MAP_CREATE_CONTRACT
            )
            assert isinstance(model, MapResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_top_n_valid(self, endpoint_caller):
        """Test top_n parameter with valid values from fixtures"""
        print("🚀 Starting top_n validation test...")
        
        for valid_top_n in TOP_N["param_values"]["valids"]:
            print(f"📝 Testing with top_n={valid_top_n}")
            body_params = {**MINIMAL_REQUEST_BODY, "top_n": valid_top_n}
            
            validated_request = endpoint_caller.validate_request(
                MAP_CREATE_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "top_n" in validated_body
            assert validated_body["top_n"] == valid_top_n
            
            request = endpoint_caller._prepare_request(
                MAP_CREATE_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, MAP_CREATE_CONTRACT
                )
                assert isinstance(model, MapResponse)
                print(f"✅ Map with top_n={valid_top_n} returned {model.urls_count} URLs")
                
                # Verify the limit was respected (should be <= top_n)
                if model.urls_count > valid_top_n:
                    print(f"⚠️  Warning: Server returned {model.urls_count} URLs but top_n was {valid_top_n}")
                else:
                    print(f"✅ Limit respected: {model.urls_count} <= {valid_top_n} URLs")
                
                # Check if cursor is provided when limit is reached
                if model.cursor is not None:
                    print(f"📄 Cursor provided: {model.cursor} (more URLs available)")
                else:
                    print("📄 No cursor - all URLs returned within limit")
                    
            except OlostepServerError_TemporaryIssue:
                print(f"⚠️  Transient error during top_n={valid_top_n} test")
                # Continue with next value instead of skipping entire test
                continue
        
        print("🎉 Top_n validation test completed successfully!")
    
    @pytest.mark.asyncio
    async def test_parameter_top_n_invalid(self, endpoint_caller):
        """Test top_n parameter with invalid values from fixtures"""
        for invalid_top_n in TOP_N["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "top_n": invalid_top_n}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(MAP_CREATE_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                MAP_CREATE_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, MAP_CREATE_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, MapResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_top_n_null(self, endpoint_caller):
        """Test top_n parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "top_n": None}
        
        validated_request = endpoint_caller.validate_request(
            MAP_CREATE_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "top_n" not in validated_body
        
        request = endpoint_caller._prepare_request(
            MAP_CREATE_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, MAP_CREATE_CONTRACT
            )
            assert isinstance(model, MapResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_include_subdomain_valid(self, endpoint_caller):
        """Test include_subdomain parameter with valid values from fixtures"""
        for valid_include_subdomain in INCLUDE_SUBDOMAIN["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_subdomain": valid_include_subdomain}
            
            validated_request = endpoint_caller.validate_request(
                MAP_CREATE_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "include_subdomain" in validated_body
            assert validated_body["include_subdomain"] == valid_include_subdomain
            
            request = endpoint_caller._prepare_request(
                MAP_CREATE_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, MAP_CREATE_CONTRACT
                )
                assert isinstance(model, MapResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_include_subdomain_invalid(self, endpoint_caller):
        """Test include_subdomain parameter with invalid values from fixtures"""
        for invalid_include_subdomain in INCLUDE_SUBDOMAIN["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_subdomain": invalid_include_subdomain}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                print(body_params)
                validated_request = endpoint_caller.validate_request(MAP_CREATE_CONTRACT, body_params=body_params)
                validated_body = validated_request["body_params"]
                print(validated_body)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                MAP_CREATE_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, MAP_CREATE_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, MapResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_include_subdomain_null(self, endpoint_caller):
        """Test include_subdomain parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "include_subdomain": None}
        
        validated_request = endpoint_caller.validate_request(
            MAP_CREATE_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "include_subdomain" not in validated_body
        
        request = endpoint_caller._prepare_request(
            MAP_CREATE_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, MAP_CREATE_CONTRACT
            )
            assert isinstance(model, MapResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_include_urls_valid(self, endpoint_caller):
        """Test include_urls parameter with valid values from fixtures"""
        for valid_include_urls in INCLUDE_URLS["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_urls": valid_include_urls}
            
            validated_request = endpoint_caller.validate_request(
                MAP_CREATE_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "include_urls" in validated_body
            assert validated_body["include_urls"] == valid_include_urls
            
            request = endpoint_caller._prepare_request(
                MAP_CREATE_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, MAP_CREATE_CONTRACT
                )
                assert isinstance(model, MapResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_ResourceNotFound:
                # example.com does not have any paths so most things will be 404
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_include_urls_invalid(self, endpoint_caller):
        """Test include_urls parameter with invalid values from fixtures"""
        for invalid_include_urls in INCLUDE_URLS["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "include_urls": invalid_include_urls}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(MAP_CREATE_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                MAP_CREATE_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, MAP_CREATE_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, MapResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejects invalid values or server errors - also acceptable
                pass
            except OlostepServerError_ResourceNotFound:
                # example.com does not have any paths so most things will be 404
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_include_urls_null(self, endpoint_caller):
        """Test include_urls parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "include_urls": None}
        
        validated_request = endpoint_caller.validate_request(
            MAP_CREATE_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "include_urls" not in validated_body
        
        request = endpoint_caller._prepare_request(
            MAP_CREATE_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, MAP_CREATE_CONTRACT
            )
            assert isinstance(model, MapResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_exclude_urls_valid(self, endpoint_caller):
        """Test exclude_urls parameter with valid values from fixtures"""
        for valid_exclude_urls in EXCLUDE_URLS["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "exclude_urls": valid_exclude_urls}
            
            validated_request = endpoint_caller.validate_request(
                MAP_CREATE_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "exclude_urls" in validated_body
            assert validated_body["exclude_urls"] == valid_exclude_urls
            
            request = endpoint_caller._prepare_request(
                MAP_CREATE_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, MAP_CREATE_CONTRACT
                )
                assert isinstance(model, MapResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")

            except OlostepServerError_ResourceNotFound:
                # example.com does not have any paths so most things will be 404
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_exclude_urls_invalid(self, endpoint_caller):
        """Test exclude_urls parameter with invalid values from fixtures"""
        for invalid_exclude_urls in EXCLUDE_URLS["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "exclude_urls": invalid_exclude_urls}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(MAP_CREATE_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                MAP_CREATE_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, MAP_CREATE_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, MapResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejects invalid values or server errors - also acceptable
                pass
            except OlostepServerError_ResourceNotFound:
                # example.com does not have any paths so most things will be 404
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_exclude_urls_null(self, endpoint_caller):
        """Test exclude_urls parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "exclude_urls": None}
        
        validated_request = endpoint_caller.validate_request(
            MAP_CREATE_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "exclude_urls" not in validated_body
        
        request = endpoint_caller._prepare_request(
            MAP_CREATE_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, MAP_CREATE_CONTRACT
            )
            assert isinstance(model, MapResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_cursor_valid(self, endpoint_caller):
        """Test cursor parameter by exhausting all pagination until no more cursors."""
        print("🚀 Starting cursor exhaustion test...")
        
        # Step 1: Create initial map with parameters that should trigger pagination
        print("📝 Step 1: Creating initial map to start pagination")
        create_body_params = PAGINATION_REQUEST_BODY
        
        validated_request = endpoint_caller.validate_request(
            MAP_CREATE_CONTRACT, body_params=create_body_params
        )
        
        create_request = endpoint_caller._prepare_request(
            MAP_CREATE_CONTRACT, **validated_request
        )
        
        try:
            current_model = await retry_request(
                endpoint_caller, create_request, MAP_CREATE_CONTRACT
            )
            assert isinstance(current_model, MapResponse)
            print(f"✅ Initial map created with {current_model.urls_count} URLs")
            
            # Track all URLs collected across all pages
            all_urls = set(current_model.urls) if current_model.urls else set()
            page_count = 1
            total_urls = current_model.urls_count
            
            print(f"📄 Page {page_count}: {current_model.urls_count} URLs, cursor: {current_model.cursor}")
            
            # Step 2: Continue paginating until cursor is exhausted
            max_pages = 20  # Safety limit to prevent infinite loops
            while current_model.cursor is not None and page_count < max_pages:
                page_count += 1
                print(f"📄 Step {page_count}: Following cursor {current_model.cursor}")
                
                # Create request with current cursor
                cursor_body_params = {
                    **PAGINATION_REQUEST_BODY,
                    "cursor": current_model.cursor
                }
                
                validated_request = endpoint_caller.validate_request(
                    MAP_CREATE_CONTRACT, body_params=cursor_body_params
                )
                
                # Verify cursor parameter is properly validated
                validated_body = validated_request["body_params"]
                assert "cursor" in validated_body
                assert validated_body["cursor"] == current_model.cursor
                
                cursor_request = endpoint_caller._prepare_request(
                    MAP_CREATE_CONTRACT, **validated_request
                )
                
                try:
                    current_model = await retry_request(
                        endpoint_caller, cursor_request, MAP_CREATE_CONTRACT
                    )
                    assert isinstance(current_model, MapResponse)
                    
                    print(f"✅ Page {page_count}: {current_model.urls_count} URLs, cursor: {current_model.cursor}")
                    total_urls += current_model.urls_count
                    
                    # Add URLs to our collection (checking for duplicates)
                    if current_model.urls:
                        new_urls = set(current_model.urls)
                        before_count = len(all_urls)
                        all_urls.update(new_urls)
                        after_count = len(all_urls)
                        duplicates = before_count + len(new_urls) - after_count
                        
                        if duplicates > 0:
                            print(f"⚠️  Warning: {duplicates} duplicate URLs found on page {page_count}")
                        else:
                            print(f"✅ No duplicate URLs on page {page_count}")
                    
                    # Check if we've reached the end
                    if current_model.cursor is None:
                        print("📄 No more cursor - pagination exhausted!")
                        break
                        
                except OlostepServerError_TemporaryIssue:
                    print(f"⚠️  Transient error on page {page_count}")
                    pytest.skip("API raised a temporary error during pagination")
            
            # Step 3: Validate pagination results
            print("🔍 Step 3: Validating pagination results...")
            print("📊 Pagination Summary:")
            print(f"   - Total pages fetched: {page_count}")
            print(f"   - Total URLs across all pages: {total_urls}")
            print(f"   - Unique URLs collected: {len(all_urls)}")
            
            # Verify we got some results
            assert total_urls > 0, "Should have fetched at least some URLs"
            assert len(all_urls) > 0, "Should have collected unique URLs"
            
            # Check for reasonable pagination behavior
            if page_count == 1:
                print("📄 Only one page - no pagination needed")
            elif page_count >= max_pages:
                print(f"⚠️  Reached maximum page limit ({max_pages}) - pagination may not be exhausted")
                if current_model.cursor is not None:
                    print(f"📄 Still have cursor: {current_model.cursor}")
            else:
                print(f"✅ Successfully paginated through {page_count} pages")
                
                # Verify no duplicate URLs across pages
                if total_urls == len(all_urls):
                    print("✅ No duplicate URLs across all pages")
                else:
                    duplicates = total_urls - len(all_urls)
                    print(f"⚠️  Found {duplicates} duplicate URLs across pages")
            
            # Test assertion: We should have exhausted the cursor
            assert current_model.cursor is None, f"Expected cursor to be exhausted, but got: {current_model.cursor}"
            print("✅ Cursor exhaustion test passed - no more cursors available")
            
            print("🎉 Cursor validation test completed successfully!")
            
        except OlostepServerError_TemporaryIssue:
            print("⚠️  Transient error during initial map creation")
            pytest.skip("API raised a temporary error during initial map creation")
    
    @pytest.mark.asyncio
    async def test_parameter_cursor_invalid(self, endpoint_caller):
        """Test cursor parameter with invalid values from fixtures"""
        for invalid_cursor in CURSOR["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "cursor": invalid_cursor}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(MAP_CREATE_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                MAP_CREATE_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, MAP_CREATE_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, MapResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_cursor_null(self, endpoint_caller):
        """Test cursor parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "cursor": None}
        
        validated_request = endpoint_caller.validate_request(
            MAP_CREATE_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "cursor" not in validated_body
        
        request = endpoint_caller._prepare_request(
            MAP_CREATE_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, MAP_CREATE_CONTRACT
            )
            assert isinstance(model, MapResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")

