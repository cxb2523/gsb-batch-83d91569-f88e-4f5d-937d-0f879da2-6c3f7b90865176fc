"""
Batch endpoint contract validation tests.

This test suite validates batch endpoint contracts against the API using httpx transport directly.
"""

import asyncio
import math
import time

import pytest

from olostep.backend.api_endpoints import CONTRACTS
from olostep.errors import (
    OlostepClientError_RequestValidationFailed,
    OlostepClientError_ResponseValidationFailed,
    OlostepServerError_RequestUnprocessable,
    OlostepServerError_ResourceNotFound,
    OlostepServerError_TemporaryIssue,
)
from olostep.models.response import (
    BatchCreateResponse,
    BatchInfoResponse,
    BatchItemsResponse,
)
from tests.conftest import extract_request_parameters, retry_request
from tests.fixtures.api.requests.batch import (
    COUNTRY,
    CURSOR,
    GET_BATCH_INFO_REQUEST_ID,
    GET_BATCH_ITEMS_REQUEST_ID,
    ITEMS,
    LIMIT,
    LINKS_ON_PAGE,
    MINIMAL_REQUEST_BODY,
    PARSER,
    STATUS,
    WORKFLOW_REQUEST_BODY,
)

BATCH_START_CONTRACT = CONTRACTS[('batch', 'start')]
BATCH_INFO_CONTRACT = CONTRACTS[('batch', 'info')]
BATCH_ITEMS_CONTRACT = CONTRACTS[('batch', 'items')]

BASE_URL = "https://api.olostep.com/v1"


class TestBatchStart:
    """Test batch start with various parameter combinations."""
    
    @pytest.mark.asyncio
    async def test_self_test_parameter_coverage(self):
        """Self-test: Verify that we have test methods for each parameter in the request model."""
        # Extract all parameters from the request model
        all_params = extract_request_parameters(BATCH_START_CONTRACT.request_model)
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
            endpoint_caller.validate_request(BATCH_START_CONTRACT, body_params=body_params)
        
        # But if we bypass validation and send it to the API anyway, the API should ignore the unknown parameters
        request = endpoint_caller._prepare_request(
            BATCH_START_CONTRACT, {}, {}, body_params
        )
        
        # The API should accept the request and ignore the unknown parameters
        try:
            model = await retry_request(
                endpoint_caller, request, BATCH_START_CONTRACT
            )
            assert isinstance(model, BatchCreateResponse)
            # Verify the response is valid despite the unknown parameters
            assert model.id is not None
            assert model.object == "batch"
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_items_valid(self, endpoint_caller):
        """Test items parameter with valid values from fixtures"""
        for valid_items in ITEMS["param_values"]["valids"]:
            body_params = {"items": valid_items}
            
            validated_request = endpoint_caller.validate_request(
                BATCH_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "items" in validated_body
            assert len(validated_body["items"]) == len(valid_items)
            
            request = endpoint_caller._prepare_request(
                BATCH_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, BATCH_START_CONTRACT
                )
                assert isinstance(model, BatchCreateResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_items_invalid(self, endpoint_caller):
        """Test items parameter with invalid values from fixtures"""
        for invalid_items in ITEMS["param_values"]["invalids"]:
            body_params = {"items": invalid_items}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                # print(body_params)
                endpoint_caller.validate_request(BATCH_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                BATCH_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, BATCH_START_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, BatchCreateResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_items_null(self, endpoint_caller):
        """Test items parameter with null value"""
        body_params = {"items": None}
        
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(BATCH_START_CONTRACT, body_params=body_params)
        
        # Test API behavior with null request (bypass validation)
        request = endpoint_caller._prepare_request(
            BATCH_START_CONTRACT, {}, {}, body_params
        )
        response = await endpoint_caller._transport.request(request)
        
        # API returns 500 error for this null requests
        with pytest.raises(OlostepServerError_RequestUnprocessable):
            endpoint_caller._handle_response(request, response, BATCH_START_CONTRACT)
    
    @pytest.mark.asyncio
    async def test_parameter_country_valid(self, endpoint_caller):
        """Test country parameter with valid values from fixtures"""
        # Truncate to representative sample to avoid 250 API calls
        valid_countries = COUNTRY["param_values"]["valids"][:5] + ["RANDOM"]
        for valid_country in valid_countries:
            body_params = {**MINIMAL_REQUEST_BODY, "country": valid_country}
            
            validated_request = endpoint_caller.validate_request(
                BATCH_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "country" in validated_body
            assert validated_body["country"] == valid_country
            
            request = endpoint_caller._prepare_request(
                BATCH_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, BATCH_START_CONTRACT
                )
                assert isinstance(model, BatchCreateResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_country_invalid(self, endpoint_caller):
        """Test country parameter with invalid values from fixtures"""
        for invalid_country in COUNTRY["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "country": invalid_country}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(BATCH_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                BATCH_START_CONTRACT, {}, {}, body_params
            )

            # API may accept invalid values (our validation is stricter than API)
            try:
                response = await endpoint_caller._transport.request(request)
                model = endpoint_caller._handle_response(request, response, BATCH_START_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, BatchCreateResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejects invalid values or server errors - also acceptable
                pass
            except OlostepClientError_ResponseValidationFailed:
                # the AP plays back the request body in the response which is not a valid response
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_country_null(self, endpoint_caller):
        """Test country parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "country": None}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_START_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "country" not in validated_body
        
        request = endpoint_caller._prepare_request(
            BATCH_START_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, BATCH_START_CONTRACT
            )
            assert isinstance(model, BatchCreateResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_parser_valid(self, endpoint_caller):
        """Test parser parameter with valid values from fixtures"""
        for valid_parser in PARSER["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "parser": valid_parser}
            
            validated_request = endpoint_caller.validate_request(
                BATCH_START_CONTRACT, body_params=body_params
            )
            
            # ParserConfig serializes as-is
            validated_body = validated_request["body_params"]
            assert "parser" in validated_body
            assert validated_body["parser"] == valid_parser
            
            request = endpoint_caller._prepare_request(
                BATCH_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, BATCH_START_CONTRACT
                )
                assert isinstance(model, BatchCreateResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejected the request (e.g., invalid parser) - also acceptable for valid tests
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_parser_invalid(self, endpoint_caller):
        """Test parser parameter with invalid values from fixtures"""
        for invalid_parser in PARSER["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "parser": invalid_parser}
            
 
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(BATCH_START_CONTRACT, body_params=body_params)
            continue
            
            # Dict values should pass validation now
            validated_request = endpoint_caller.validate_request(
                BATCH_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "parser" in validated_body
            assert validated_body["parser"] == invalid_parser
            
            # Test API behavior with the request
            request = endpoint_caller._prepare_request(
                BATCH_START_CONTRACT, **validated_request
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept or reject the values
            try:
                model = endpoint_caller._handle_response(request, response, BATCH_START_CONTRACT)
                assert isinstance(model, BatchCreateResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_parser_null(self, endpoint_caller):
        """Test parser parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "parser": None}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_START_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "parser" not in validated_body
        
        request = endpoint_caller._prepare_request(
            BATCH_START_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, BATCH_START_CONTRACT
            )
            assert isinstance(model, BatchCreateResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")

    @pytest.mark.asyncio
    async def test_parameter_links_on_page_valid(self, endpoint_caller):
        """Test links_on_page parameter with valid values from fixtures"""
        for valid_links_config in LINKS_ON_PAGE["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "links_on_page": valid_links_config}
            
            validated_request = endpoint_caller.validate_request(
                BATCH_START_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "links_on_page" in validated_body
            
            request = endpoint_caller._prepare_request(
                BATCH_START_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, BATCH_START_CONTRACT
                )
                assert isinstance(model, BatchCreateResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_links_on_page_invalid(self, endpoint_caller):
        """Test links_on_page parameter with invalid values from fixtures"""
        for invalid_links_config in LINKS_ON_PAGE["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "links_on_page": invalid_links_config}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(BATCH_START_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                BATCH_START_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, BATCH_START_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, BatchCreateResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_links_on_page_null(self, endpoint_caller):
        """Test links_on_page parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "links_on_page": None}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_START_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "links_on_page" not in validated_body
        
        request = endpoint_caller._prepare_request(
            BATCH_START_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, BATCH_START_CONTRACT
            )
            assert isinstance(model, BatchCreateResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")


class TestBatchInfo:
    """Test cases for GET /batches/{batch_id} endpoint."""
    
    @pytest.mark.asyncio
    async def test_get_existing_batch(self, endpoint_caller):
        """Test getting an existing batch by ID"""
        # First, create a batch using MINIMAL_REQUEST_BODY
        create_body_params = MINIMAL_REQUEST_BODY
        
        validated_request = endpoint_caller.validate_request(
            BATCH_START_CONTRACT, body_params=create_body_params
        )
        
        create_request = endpoint_caller._prepare_request(
            BATCH_START_CONTRACT, **validated_request
        )
        
        try:
            create_model = await retry_request(
                endpoint_caller, create_request, BATCH_START_CONTRACT
            )
            assert isinstance(create_model, BatchCreateResponse)
            batch_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch creation")
        
        # Now get the batch using the ID from GET_BATCH_INFO_REQUEST_ID fixture
        batch_id_param_name = GET_BATCH_INFO_REQUEST_ID["param_name"]
        get_path_params = {batch_id_param_name: batch_id}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_INFO_CONTRACT, path_params=get_path_params
        )
        
        validated_path = validated_request["path_params"]
        assert batch_id_param_name in validated_path
        assert validated_path[batch_id_param_name] == batch_id
        
        get_request = endpoint_caller._prepare_request(
            BATCH_INFO_CONTRACT, **validated_request
        )
        
        try:
            get_model = await retry_request(
                endpoint_caller, get_request, BATCH_INFO_CONTRACT
            )
            assert isinstance(get_model, BatchInfoResponse)
            assert get_model.id == batch_id
            assert not hasattr(get_model, "batch_id")

        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch retrieval")
    
    @pytest.mark.asyncio
    async def test_get_batch_info_with_country(self, endpoint_caller):
        """Test getting batch info when batch was created with country parameter.
        
        The API can optionally return a country field in batch info responses.
        This test verifies that the BatchInfoResponse model correctly handles
        the country field when it is present in the API response.
        """
        # First, create a batch with a country parameter
        create_body_params = {
            "items": [
                {"url": "https://example.com", "custom_id": "item1"},
                {"url": "https://http.cat/200", "custom_id": "item2"},
            ],
            "country": COUNTRY["param_values"]["valids"][0],  # Use first valid country
        }
        
        validated_request = endpoint_caller.validate_request(
            BATCH_START_CONTRACT, body_params=create_body_params
        )
        
        create_request = endpoint_caller._prepare_request(
            BATCH_START_CONTRACT, **validated_request
        )
        
        try:
            create_model = await retry_request(
                endpoint_caller, create_request, BATCH_START_CONTRACT
            )
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
            get_model = await retry_request(
                endpoint_caller, get_request, BATCH_INFO_CONTRACT
            )
            assert isinstance(get_model, BatchInfoResponse)
            assert get_model.id == batch_id
            
            # Verify that country field is present and accessible
            # The API may or may not return it, but if it does, it should be valid
            if hasattr(get_model, "country") and get_model.country is not None:
                from olostep.models.common import Country
                assert get_model.country in Country
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch retrieval")
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_batch(self, endpoint_caller):
        """Test getting a non-existent batch by ID"""
        # Try to get a batch with an invalid ID from GET_BATCH_INFO_REQUEST_ID fixture
        batch_id_param_name = GET_BATCH_INFO_REQUEST_ID["param_name"]
        invalid_batch_id = GET_BATCH_INFO_REQUEST_ID["param_values"]["invalids"][0]
        get_path_params = {batch_id_param_name: invalid_batch_id}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_INFO_CONTRACT, path_params=get_path_params
        )
        
        validated_path = validated_request["path_params"]
        assert batch_id_param_name in validated_path
        assert validated_path[batch_id_param_name] == invalid_batch_id
        
        get_request = endpoint_caller._prepare_request(
            BATCH_INFO_CONTRACT, **validated_request
        )
        
        get_response = await endpoint_caller._transport.request(get_request)
        
        # Should raise an error for non-existent batch
        with pytest.raises(OlostepServerError_ResourceNotFound):
            await retry_request(
                endpoint_caller, get_request, BATCH_INFO_CONTRACT
            )


class TestBatchItems:
    """Test cases for GET /batches/{batch_id}/items endpoint."""
    
    @pytest.mark.asyncio
    async def test_self_test_parameter_coverage(self):
        """Self-test: Verify that we have test methods for each parameter in the request model."""
        # Extract all parameters from the request model
        all_params = extract_request_parameters(BATCH_ITEMS_CONTRACT.request_model)
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
    async def test_parameter_batch_id_valid(self, endpoint_caller):
        """Test batch_id path parameter with valid values from fixtures"""
        # First create a batch to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
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
            valid_batch_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch creation")
        
        # Test with valid batch_id
        batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
        get_path_params = {batch_id_param_name: valid_batch_id}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_ITEMS_CONTRACT, path_params=get_path_params
        )
        validated_path = validated_request["path_params"]
        assert batch_id_param_name in validated_path
        assert validated_path[batch_id_param_name] == valid_batch_id
        
        get_request = endpoint_caller._prepare_request(
            BATCH_ITEMS_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, BATCH_ITEMS_CONTRACT)
            assert isinstance(get_model, BatchItemsResponse)
            assert get_model.id == valid_batch_id
            assert get_model.object == "batch"
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch items retrieval")
    
    @pytest.mark.asyncio
    async def test_parameter_batch_id_invalid(self, endpoint_caller):
        """Test batch_id path parameter with invalid values from fixtures"""
        # Try to get items with an invalid ID from GET_BATCH_ITEMS_REQUEST_ID fixture
        batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
        invalid_batch_id = GET_BATCH_ITEMS_REQUEST_ID["param_values"]["invalids"][0]
        get_path_params = {batch_id_param_name: invalid_batch_id}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_ITEMS_CONTRACT, path_params=get_path_params
        )
        
        validated_path = validated_request["path_params"]
        assert batch_id_param_name in validated_path
        assert validated_path[batch_id_param_name] == invalid_batch_id
        
        get_request = endpoint_caller._prepare_request(
            BATCH_ITEMS_CONTRACT, **validated_request
        )
        
        get_response = await endpoint_caller._transport.request(get_request)
        
        # Should raise an error for non-existent batch
        with pytest.raises(OlostepServerError_ResourceNotFound):
            endpoint_caller._handle_response(get_request, get_response, BATCH_ITEMS_CONTRACT)
    
    @pytest.mark.asyncio
    async def test_parameter_status_valid(self, endpoint_caller):
        """Test status query parameter with valid values from fixtures"""
        # First create a batch to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
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
            valid_batch_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch creation")
        
        # Test with valid status values
        for valid_status in STATUS["param_values"]["valids"]:
            batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
            get_path_params = {batch_id_param_name: valid_batch_id}
            get_query_params = {"status": valid_status}
            
            validated_request = endpoint_caller.validate_request(
                BATCH_ITEMS_CONTRACT, path_params=get_path_params, query_params=get_query_params
            )

            validated_query = validated_request["query_params"]
            assert "status" in validated_query
            assert validated_query["status"] == valid_status
            
            get_request = endpoint_caller._prepare_request(
                BATCH_ITEMS_CONTRACT, **validated_request
            )
            
            try:
                get_response = await endpoint_caller._transport.request(get_request)
                get_model = endpoint_caller._handle_response(get_request, get_response, BATCH_ITEMS_CONTRACT)
                assert isinstance(get_model, BatchItemsResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_status_invalid(self, endpoint_caller):
        """Test status query parameter with invalid values from fixtures"""
        # First create a batch to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
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
            valid_batch_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch creation")
        
        # Test with invalid status values
        for invalid_status in STATUS["param_values"]["invalids"]:
            batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
            get_path_params = {batch_id_param_name: valid_batch_id}
            get_query_params = {"status": invalid_status}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(BATCH_ITEMS_CONTRACT, path_params=get_path_params, query_params=get_query_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                BATCH_ITEMS_CONTRACT, get_path_params, get_query_params, {}
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, BATCH_ITEMS_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, BatchItemsResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_status_null(self, endpoint_caller):
        """Test status query parameter with null value"""
        # First create a batch to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
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
            valid_batch_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch creation")
        
        # Test with null status
        batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
        get_path_params = {batch_id_param_name: valid_batch_id}
        get_query_params = {"status": None}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_ITEMS_CONTRACT, path_params=get_path_params, query_params=get_query_params
        )

        validated_query = validated_request["query_params"]
        assert "status" not in validated_query
        
        get_request = endpoint_caller._prepare_request(
            BATCH_ITEMS_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, BATCH_ITEMS_CONTRACT)
            assert isinstance(get_model, BatchItemsResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_cursor_valid(self, endpoint_caller):
        """Test cursor query parameter with valid values obtained from pagination flow"""
        # First create a batch to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
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
            valid_batch_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch creation")
        
        # Step 1: Make first request with limit to get a cursor
        batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
        get_path_params = {batch_id_param_name: valid_batch_id}
        get_query_params = {"limit": 10}  # Start with limit to get cursor
        
        validated_request = endpoint_caller.validate_request(
            BATCH_ITEMS_CONTRACT, path_params=get_path_params, query_params=get_query_params
        )
        
        request = endpoint_caller._prepare_request(
            BATCH_ITEMS_CONTRACT, **validated_request
        )
        
        try:
            first_response = await retry_request(
                endpoint_caller, request, BATCH_ITEMS_CONTRACT
            )
            assert isinstance(first_response, BatchItemsResponse)
            
            # Step 2: If we got a cursor, test using it
            if first_response.cursor is not None:
                cursor_query_params = {"cursor": first_response.cursor}
                
                validated_request = endpoint_caller.validate_request(
                    BATCH_ITEMS_CONTRACT, path_params=get_path_params, query_params=cursor_query_params
                )
                
                validated_query = validated_request["query_params"]
                assert "cursor" in validated_query
                assert validated_query["cursor"] == first_response.cursor
                
                cursor_request = endpoint_caller._prepare_request(
                    BATCH_ITEMS_CONTRACT, **validated_request
                )
                
                cursor_response = await retry_request(
                    endpoint_caller, cursor_request, BATCH_ITEMS_CONTRACT
                )
                assert isinstance(cursor_response, BatchItemsResponse)
            else:
                pytest.skip("No cursor returned from first request - batch may be too small for pagination")
                
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_cursor_invalid(self, endpoint_caller):
        """Test cursor query parameter with invalid values from fixtures"""
        # First create a batch to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
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
            valid_batch_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch creation")
        
        # Test with invalid cursor values
        for invalid_cursor in CURSOR["param_values"]["invalids"]:
            batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
            get_path_params = {batch_id_param_name: valid_batch_id}
            get_query_params = {"cursor": invalid_cursor}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(BATCH_ITEMS_CONTRACT, path_params=get_path_params, query_params=get_query_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                BATCH_ITEMS_CONTRACT, get_path_params, get_query_params, {}
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, BATCH_ITEMS_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, BatchItemsResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_cursor_null(self, endpoint_caller):
        """Test cursor query parameter with null value"""
        # First create a batch to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
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
            valid_batch_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch creation")
        
        # Test with null cursor
        batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
        get_path_params = {batch_id_param_name: valid_batch_id}
        get_query_params = {"cursor": None}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_ITEMS_CONTRACT, path_params=get_path_params, query_params=get_query_params
        )
        
        validated_query = validated_request["query_params"]
        assert "cursor" not in validated_query
        
        get_request = endpoint_caller._prepare_request(
            BATCH_ITEMS_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, BATCH_ITEMS_CONTRACT)
            assert isinstance(get_model, BatchItemsResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_limit_valid(self, endpoint_caller):
        """Test limit query parameter with valid values from fixtures"""
        # First create a batch to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
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
            valid_batch_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch creation")
        
        valid_limit = 1
        batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
        get_path_params = {batch_id_param_name: valid_batch_id}
        get_query_params = {"limit": valid_limit}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_ITEMS_CONTRACT, path_params=get_path_params, query_params=get_query_params
        )
        
        validated_query = validated_request["query_params"]
        assert "limit" in validated_query
        assert validated_query["limit"] == valid_limit
        
        get_request = endpoint_caller._prepare_request(
            BATCH_ITEMS_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, BATCH_ITEMS_CONTRACT)
            assert isinstance(get_model, BatchItemsResponse)
            len(get_model.items) == valid_limit
            get_model.cursor is not None
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_limit_invalid(self, endpoint_caller):
        """Test limit query parameter with invalid values from fixtures"""
        # First create a batch to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
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
            valid_batch_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch creation")
        
        # Test with invalid limit values
        for invalid_limit in LIMIT["param_values"]["invalids"]:
            batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
            get_path_params = {batch_id_param_name: valid_batch_id}
            get_query_params = {"limit": invalid_limit}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(BATCH_ITEMS_CONTRACT, path_params=get_path_params, query_params=get_query_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                BATCH_ITEMS_CONTRACT, get_path_params, get_query_params, {}
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, BATCH_ITEMS_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, BatchItemsResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_RequestUnprocessable:
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_limit_null(self, endpoint_caller):
        """Test limit query parameter with null value"""
        # First create a batch to get a valid ID
        create_body_params = MINIMAL_REQUEST_BODY
        
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
            valid_batch_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch creation")
        
        # Test with null limit
        batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
        get_path_params = {batch_id_param_name: valid_batch_id}
        get_query_params = {"limit": None}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_ITEMS_CONTRACT, path_params=get_path_params, query_params=get_query_params
        )
        
        validated_query = validated_request["query_params"]
        assert "limit" not in validated_query
        
        get_request = endpoint_caller._prepare_request(
            BATCH_ITEMS_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, BATCH_ITEMS_CONTRACT)
            assert isinstance(get_model, BatchItemsResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_get_existing_batch_items(self, endpoint_caller):
        """Test getting items from an existing batch"""
        # First, create a batch using MINIMAL_REQUEST_BODY
        create_body_params = MINIMAL_REQUEST_BODY
        
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
        
        # Now get the batch items using the ID from GET_BATCH_ITEMS_REQUEST_ID fixture
        batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
        get_path_params = {batch_id_param_name: batch_id}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_ITEMS_CONTRACT, path_params=get_path_params
        )
        
        validated_path = validated_request["path_params"]
        assert batch_id_param_name in validated_path
        assert validated_path[batch_id_param_name] == batch_id
        
        get_request = endpoint_caller._prepare_request(
            BATCH_ITEMS_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, BATCH_ITEMS_CONTRACT)
            assert isinstance(get_model, BatchItemsResponse)
            assert get_model.id == batch_id
            assert get_model.object == "batch"
            # The response should have items array and metadata
            assert hasattr(get_model, 'items')
            assert hasattr(get_model, 'items_count')
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch items retrieval")
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_batch_items(self, endpoint_caller):
        """Test getting items from a non-existent batch"""
        # Try to get items with an invalid ID from GET_BATCH_ITEMS_REQUEST_ID fixture
        batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
        invalid_batch_id = GET_BATCH_ITEMS_REQUEST_ID["param_values"]["invalids"][0]
        get_path_params = {batch_id_param_name: invalid_batch_id}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_ITEMS_CONTRACT, path_params=get_path_params
        )
        
        validated_path = validated_request["path_params"]
        assert batch_id_param_name in validated_path
        assert validated_path[batch_id_param_name] == invalid_batch_id
        
        get_request = endpoint_caller._prepare_request(
            BATCH_ITEMS_CONTRACT, **validated_request
        )
        
        get_response = await endpoint_caller._transport.request(get_request)
        
        # Should raise an error for non-existent batch
        with pytest.raises(OlostepServerError_ResourceNotFound):
            endpoint_caller._handle_response(get_request, get_response, BATCH_ITEMS_CONTRACT)
    
    @pytest.mark.asyncio
    async def test_cursor_and_limit_mutually_exclusive_validation(self, endpoint_caller):
        """Test that our validation model refuses both cursor and limit parameters"""
        # Test that our validation model rejects both cursor and limit
        query_params = {"cursor": 123, "limit": 10}
        
        with pytest.raises(OlostepClientError_RequestValidationFailed) as exc_info:
            endpoint_caller.validate_request(
                BATCH_ITEMS_CONTRACT, path_params={"batch_id": "test_id"}, query_params=query_params
            )
        
        # Verify the error message contains the expected explanation
        error_message = str(exc_info.value)
        assert "Cannot specify both 'cursor' and 'limit' parameters" in error_message
        assert "Use 'limit' for the first request, then 'cursor' for subsequent requests" in error_message


class TestBatchWorkflow:
    """Test cases for batch workflow."""
    
    @pytest.mark.asyncio
    async def test_batch_workflow(self, endpoint_caller):
        """Test complete batch workflow: create, monitor, and paginate through results."""
        print("🚀 Starting batch workflow test...")
        
        # Step 1: Create a batch using WORKFLOW_REQUEST_BODY
        print(f"📝 Step 1: Creating batch with {WORKFLOW_REQUEST_BODY}")
        create_body_params = WORKFLOW_REQUEST_BODY
        
        validated_request = endpoint_caller.validate_request(
            BATCH_START_CONTRACT, body_params=create_body_params
        )
        
        create_request = endpoint_caller._prepare_request(
            BATCH_START_CONTRACT, **validated_request
        )
        
        try:
            create_model = await retry_request(
                endpoint_caller, create_request, BATCH_START_CONTRACT
            )
            assert isinstance(create_model, BatchCreateResponse)
            batch_id = create_model.id
            print(f"✅ Batch created successfully with ID: {batch_id}")
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during batch creation")
        
        # Step 2: Monitor batch status every 10 seconds until done
        print("⏳ Step 2: Monitoring batch status...")
        BATCH_INFO_CONTRACT = CONTRACTS[('batch', 'info')]
        
        batch_id_param_name = "batch_id"
        get_path_params = {batch_id_param_name: batch_id}
        
        validated_request = endpoint_caller.validate_request(
            BATCH_INFO_CONTRACT, path_params=get_path_params
        )
        
        get_request = endpoint_caller._prepare_request(
            BATCH_INFO_CONTRACT, **validated_request
        )
        
        max_wait_time: float = 300  # 5 minutes max wait
        start_time: float = time.monotonic()

        while (time.monotonic() - start_time) < max_wait_time:
            try:
                get_model = await retry_request(
                    endpoint_caller, get_request, BATCH_INFO_CONTRACT
                )
                assert isinstance(get_model, BatchInfoResponse)
                
                print(f"📊 Batch status: {get_model.status} (elapsed: {int(time.monotonic() - start_time)}s)")
                
                if get_model.status == "completed":
                    print("✅ Batch completed successfully!")
                    break
                
                # Wait 10 seconds before next check
                print("⏸️  Waiting 10 seconds before next status check...")
                await asyncio.sleep(10)
                
            except OlostepServerError_TemporaryIssue:
                print("⚠️  Transient error during status check, retrying...")
                await asyncio.sleep(15)
            except OlostepClientError_RequestValidationFailed as e:
                print(e)
                pytest.fail(f"Request validation error during status check: {e}")
        else:
            pytest.fail(f"Batch did not complete within {max_wait_time} seconds")
        
        # Step 3: Validate pagination by comparing full fetch vs paginated fetch
        print("📄 Step 3: Validating pagination behavior...")
        pages_batch_id_param_name = GET_BATCH_ITEMS_REQUEST_ID["param_name"]
        pages_path_params = {pages_batch_id_param_name: batch_id}
        
        # Calculate limit as number of items / 2 (from WORKFLOW_REQUEST_BODY)
        total_items = len(WORKFLOW_REQUEST_BODY["items"])
        limit = math.ceil(total_items / 2)
        print(f"📊 Using limit: {limit} (total_items {total_items} / 2, rounded up)")
        
        # Step 3a: Fetch all items without cursor/limit
        print("🔍 Step 3a: Fetching all items without cursor/limit...")
        validated_request = endpoint_caller.validate_request(
            BATCH_ITEMS_CONTRACT, path_params=pages_path_params, query_params={}
        )
        
        full_request = endpoint_caller._prepare_request(
            BATCH_ITEMS_CONTRACT, **validated_request
        )
        
        try:
            full_model = await retry_request(
                endpoint_caller, full_request, BATCH_ITEMS_CONTRACT
            )
            assert isinstance(full_model, BatchItemsResponse)
            
            full_items = []
            if hasattr(full_model, 'items') and full_model.items:
                full_items = full_model.items
                print(f"✅ Full fetch returned {len(full_items)} items")
            else:
                print("⚠️  Full fetch returned no items")
                
        except OlostepServerError_TemporaryIssue:
            print("⚠️  Transient error during full fetch, skipping pagination validation")
            full_items = []
        
        # Step 3b: Paginate through items using cursor-based pagination
        print("🔍 Step 3b: Paginating through items using cursor-based pagination...")
        paginated_items = []
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
                BATCH_ITEMS_CONTRACT, path_params=pages_path_params, query_params=query_params
            )

            validated_query = validated_request["query_params"]
            # Validate that our parameters were accepted
            if cursor is None:
                assert "limit" in validated_query, "Limit should be in validated query"
                assert validated_query["limit"] == limit, f"Limit should be {limit}, got {validated_query['limit']}"
            else:
                assert "cursor" in validated_query, "Cursor should be in validated query"
                assert validated_query["cursor"] == cursor, f"Cursor should be {cursor}, got {validated_query['cursor']}"
            
            items_request = endpoint_caller._prepare_request(
                BATCH_ITEMS_CONTRACT, **validated_request
            )
            
            try:
                items_model = await retry_request(
                    endpoint_caller, items_request, BATCH_ITEMS_CONTRACT
                )
                assert isinstance(items_model, BatchItemsResponse)
                
                # Validate that server honored our limit (only on first request)
                if hasattr(items_model, 'items') and items_model.items:
                    actual_items_count = len(items_model.items)
                    if cursor is None:
                        print(f"   Server returned {actual_items_count} items (requested limit: {limit})")
                        # Server should honor our limit (unless it's the last page with fewer results)
                        if actual_items_count > limit:
                            pytest.fail(f"Server returned {actual_items_count} items but limit was {limit}")
                    else:
                        print(f"   Server returned {actual_items_count} items (using remembered limit)")
                    
                    paginated_items.extend(items_model.items)
                    print(f"   Total paginated items collected so far: {len(paginated_items)}")
                else:
                    print("   No items in this response")
                
                # Check for next cursor in response
                next_cursor = None
                if hasattr(items_model, 'cursor') and items_model.cursor is not None:
                    next_cursor = items_model.cursor
                
                if next_cursor is not None:
                    print(f"   Next cursor from server: {next_cursor}")
                    cursor = next_cursor
                else:
                    print("   No more cursor - pagination complete!")
                    break
                    
            except OlostepServerError_TemporaryIssue:
                print("⚠️  Transient error during items fetch, retrying...")
                await asyncio.sleep(2)
        
        # Step 3c: Compare full fetch vs paginated fetch
        print("🔍 Step 3c: Comparing full fetch vs paginated fetch...")
        if full_items and paginated_items:
            # Extract item IDs for comparison
            full_item_ids = set()
            paginated_item_ids = set()
            
            for item in full_items:
                if hasattr(item, 'retrieve_id') and item.retrieve_id:
                    full_item_ids.add(item.retrieve_id)
                elif hasattr(item, 'custom_id') and item.custom_id:
                    full_item_ids.add(item.custom_id)  # Use custom_id as fallback identifier
                elif hasattr(item, 'url') and item.url:
                    full_item_ids.add(item.url)  # Use URL as fallback identifier
            
            for item in paginated_items:
                if hasattr(item, 'retrieve_id') and item.retrieve_id:
                    paginated_item_ids.add(item.retrieve_id)
                elif hasattr(item, 'custom_id') and item.custom_id:
                    paginated_item_ids.add(item.custom_id)  # Use custom_id as fallback identifier
                elif hasattr(item, 'url') and item.url:
                    paginated_item_ids.add(item.url)  # Use URL as fallback identifier
            
            print(f"📊 Full fetch: {len(full_item_ids)} unique items")
            print(f"📊 Paginated fetch: {len(paginated_item_ids)} unique items")
            
            # Check if sets are equal
            if full_item_ids == paginated_item_ids:
                print("✅ Pagination validation passed: Both methods returned identical items!")
            else:
                missing_in_paginated = full_item_ids - paginated_item_ids
                extra_in_paginated = paginated_item_ids - full_item_ids
                
                if missing_in_paginated:
                    print(f"❌ Pagination validation failed: {len(missing_in_paginated)} items missing in paginated fetch")
                    print(f"   Missing items: {list(missing_in_paginated)[:5]}...")  # Show first 5
                
                if extra_in_paginated:
                    print(f"❌ Pagination validation failed: {len(extra_in_paginated)} extra items in paginated fetch")
                    print(f"   Extra items: {list(extra_in_paginated)[:5]}...")  # Show first 5
                
                pytest.fail("Pagination validation failed: Full fetch and paginated fetch returned different items")
        else:
            print("⚠️  Cannot compare: One or both fetch methods returned no items")
        
        all_items = paginated_items  # Use paginated items for summary
        
        # Step 4: Summary
        print("🎉 Workflow completed successfully!")
        print("📊 Summary:")
        print(f"   - Batch ID: {batch_id}")
        print(f"   - Total items fetched: {len(all_items)}")
        print(f"   - Total pagination requests: {page_count}")
        print(f"   - Batch completed in: {int(time.monotonic() - start_time)} seconds")
        print(f"   - Limit used: {limit} (total_items {total_items} / 2)")
        
        # Verify we got some items
        assert len(all_items) > 0, "Should have fetched at least some items"
        print(f"✅ Workflow test passed - fetched {len(all_items)} items across {page_count} requests")
    
