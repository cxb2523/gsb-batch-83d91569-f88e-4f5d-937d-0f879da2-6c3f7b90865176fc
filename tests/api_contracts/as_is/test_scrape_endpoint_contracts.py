"""
Scrape endpoint contract validation tests.

This test suite validates scrape endpoint contracts against the API using httpx transport directly.
"""


import pytest

from olostep.backend.api_endpoints import CONTRACTS
from olostep.errors import (
    OlostepClientError_RequestValidationFailed,
    OlostepServerError_NoResultInResponse,
    OlostepServerError_ParserNotFound,
    OlostepServerError_RequestUnprocessable,
    OlostepServerError_ResourceNotFound,
    OlostepServerError_TemporaryIssue,
    OlostepServerError_UnknownIssue,
)
from olostep.models.response import (
    CreateScrapeResponse,
    GetScrapeResponse,
)
from tests.conftest import extract_request_parameters, retry_request
from tests.fixtures.api.requests.scrape import (
    ACTIONS,
    COUNTRY,
    FORMATS,
    GET_SCRAPE_REQUEST_ID,
    LINKS_ON_PAGE,
    LLM_EXTRACT,
    METADATA,
    MINIMAL_REQUEST_BODY,
    PARSER,
    REMOVE_CLASS_NAMES,
    REMOVE_CSS_SELECTORS,
    REMOVE_IMAGES,
    SCREEN_SIZE,
    TRANSFORMER,
    URL_TO_SCRAPE,
    WAIT_BEFORE_SCRAPING,
)

SCRAPE_URL_CONTRACT = CONTRACTS[('scrape', 'url')]
GET_SCRAPE_CONTRACT = CONTRACTS[('scrape', 'get')]

BASE_URL = "https://api.olostep.com/v1"









class TestScrapeUrlCreation:
    """Test scrape URL creation with various parameter combinations."""
    
    @pytest.mark.asyncio
    async def test_self_test_parameter_coverage(self):
        """Self-test: Verify that we have test methods for each parameter in the request model."""
        # Extract all parameters from the request model
        all_params = extract_request_parameters(SCRAPE_URL_CONTRACT.request_model)
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
            "another_fake_param": {"nested": "value", "number": 123}
        }
        
        # Our validation should refuse this request due to the unknown parameters
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
        
        # But if we bypass validation and send it to the API anyway, the API should ignore the unknown parameters
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, {}, {}, body_params
        )
        
        # The API should accept the request and ignore the unknown parameters
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
            # Verify the response is valid despite the unknown parameters
            assert model.id is not None
            assert model.object == "scrape"
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
        
    @pytest.mark.asyncio
    async def test_parameter_url_to_scrape_valid(self, endpoint_caller):
        """Test url_to_scrape parameter with valid values from fixtures"""
        for valid_url in URL_TO_SCRAPE["param_values"]["valids"]:
            body_params = {"url_to_scrape": valid_url}
            
            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "url_to_scrape" in validated_body
            assert validated_body["url_to_scrape"].startswith(valid_url) #trailing slash is added by the API
            
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, SCRAPE_URL_CONTRACT
                )
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_url_to_scrape_invalid(self, endpoint_caller):
        """Test url_to_scrape parameter with invalid values from fixtures"""
        for invalid_url in URL_TO_SCRAPE["param_values"]["invalids"]:
            body_params = {"url_to_scrape": invalid_url}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass
        
    
    @pytest.mark.asyncio
    async def test_parameter_url_to_scrape_null(self, endpoint_caller):
        """Test url_to_scrape parameter with null value"""
        body_params = {"url_to_scrape": None}
        
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
        
        # Test API behavior with null request (bypass validation)
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, {}, {}, body_params
        )
        response = await endpoint_caller._transport.request(request)
        
        # API returns 500 error for this null requests
        with pytest.raises(OlostepServerError_RequestUnprocessable):
            endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
        
    
    @pytest.mark.asyncio
    async def test_parameter_wait_before_scraping_valid(self, endpoint_caller):
        """Test wait_before_scraping parameter with valid values from fixtures"""
        for valid_wait in WAIT_BEFORE_SCRAPING["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "wait_before_scraping": valid_wait}
            
            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "wait_before_scraping" in validated_body
            assert validated_body["wait_before_scraping"] == valid_wait
            
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, SCRAPE_URL_CONTRACT
                )
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")

    
    @pytest.mark.asyncio
    async def test_parameter_wait_before_scraping_invalid(self, endpoint_caller):
        """Test wait_before_scraping parameter with invalid values from fixtures"""
        for invalid_wait in WAIT_BEFORE_SCRAPING["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "wait_before_scraping": invalid_wait}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            # Note: API is more lenient than our validation model and accepts invalid values
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API accepts invalid values and returns success (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except OlostepServerError_NoResultInResponse:
                # Timeout is also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_wait_before_scraping_null(self, endpoint_caller):
        """Test wait_before_scraping parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "wait_before_scraping": None}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )

        validated_body = validated_request["body_params"]
        assert "wait_before_scraping" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_formats_valid(self, endpoint_caller):
        """Test formats parameter with valid values from fixtures
        
        API OBSERVED BEHAVIOR: The API rejects requests with 'json' format when no parser
        or llm_extract is provided, returning 400 with message: "When requesting 'json'
        format, you must provide either a 'parser' (pre-defined or custom) or an 'llm_extract'
        object to define how data should be extracted."
        
        This test uses all Format enum values including 'json', which requires additional
        parameters. The test should exclude 'json' from the formats list or add parser/llm_extract.
        """
        # Exclude 'json' format as it requires parser or llm_extract
        valid_formats = [f for f in FORMATS["param_values"]["valids"] if f != "json"]
        body_params = {**MINIMAL_REQUEST_BODY, "formats": valid_formats}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "formats" in validated_body
        assert validated_body["formats"] == valid_formats
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_formats_invalid(self, endpoint_caller):
        """Test formats parameter with invalid values from fixtures"""
        for invalid_formats in FORMATS["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "formats": [invalid_formats]}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_formats_null(self, endpoint_caller):
        """Test formats parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "formats": None}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "formats" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_remove_css_selectors_valid(self, endpoint_caller):
        """Test remove_css_selectors parameter with valid values from fixtures"""
        for valid_selector in REMOVE_CSS_SELECTORS["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "remove_css_selectors": valid_selector}
            
            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            if valid_selector is not None:
                assert "remove_css_selectors" in validated_body
            else:
                assert "remove_css_selectors" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_remove_css_selectors_invalid(self, endpoint_caller):
        """Test remove_css_selectors parameter with invalid values from fixtures"""
        for invalid_selector in REMOVE_CSS_SELECTORS["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "remove_css_selectors": invalid_selector}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_remove_css_selectors_null(self, endpoint_caller):
        """Test remove_css_selectors parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "remove_css_selectors": None}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "remove_css_selectors" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_actions_valid(self, endpoint_caller):
        """Test actions parameter with valid values from fixtures"""
        for valid_action in ACTIONS["param_values"]["valid"]:
            body_params = {**MINIMAL_REQUEST_BODY, "actions": [valid_action]}
            
            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "actions" in validated_body
            assert len(validated_body["actions"]) == 1
            
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, SCRAPE_URL_CONTRACT
                )
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_actions_invalid(self, endpoint_caller):
        """Test actions parameter with invalid values from fixtures"""
        for invalid_action in ACTIONS["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "actions": [invalid_action]}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_actions_null(self, endpoint_caller):
        """Test actions parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "actions": None}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "actions" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_country_valid(self, endpoint_caller):
        """Test country parameter with valid values from fixtures"""
        # Truncate to representative sample to avoid 250 API calls
        valid_countries = COUNTRY["param_values"]["valids"][:5] + ["RANDOM"]
        for valid_country in valid_countries:
            body_params = {**MINIMAL_REQUEST_BODY, "country": valid_country}
            
            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "country" in validated_body
            assert validated_body["country"] == valid_country
            
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, SCRAPE_URL_CONTRACT
                )
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_country_invalid(self, endpoint_caller):
        """Test country parameter with invalid values from fixtures"""
        for invalid_country in COUNTRY["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "country": invalid_country}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_country_null(self, endpoint_caller):
        """Test country parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "country": None}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "country" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_transformer_valid(self, endpoint_caller):
        """Test transformer parameter with valid values from fixtures"""
        for valid_transformer in TRANSFORMER["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "transformer": valid_transformer}
            
            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "transformer" in validated_body
            assert validated_body["transformer"] == valid_transformer
            
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, SCRAPE_URL_CONTRACT
                )
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_transformer_invalid(self, endpoint_caller):
        """Test transformer parameter with invalid values from fixtures"""
        for invalid_transformer in TRANSFORMER["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "transformer": invalid_transformer}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_transformer_null(self, endpoint_caller):
        """Test transformer parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "transformer": None}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "transformer" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    

    @pytest.mark.asyncio
    async def test_parameter_storage_valid(self, endpoint_caller):
        """Test storage parameter with valid values"""
        for valid_storage in [{"expires_in": "30d"}, {"expires_in": "never"}]:
            body_params = {**MINIMAL_REQUEST_BODY, "storage": valid_storage}

            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )

            validated_body = validated_request["body_params"]
            assert "storage" in validated_body

            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, **validated_request
            )

            try:
                model = await retry_request(
                    endpoint_caller, request, SCRAPE_URL_CONTRACT
                )
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                pytest.skip("API raised a temporary error")

    @pytest.mark.asyncio
    async def test_parameter_storage_invalid(self, endpoint_caller):
        """Test storage parameter with invalid values (client validation rejects them)"""
        for invalid_storage in [{"expires_in": "3d"}, {"expires_in": "1y"}]:
            body_params = {**MINIMAL_REQUEST_BODY, "storage": invalid_storage}

            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)

    @pytest.mark.asyncio
    async def test_parameter_storage_null(self, endpoint_caller):
        """Test storage parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "storage": None}

        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )

        validated_body = validated_request["body_params"]
        assert "storage" not in validated_body

        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )

        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error")

    @pytest.mark.asyncio
    async def test_parameter_remove_images_valid(self, endpoint_caller):
        """Test remove_images parameter with valid values from fixtures"""
        for valid_remove_images in REMOVE_IMAGES["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "remove_images": valid_remove_images}
            
            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "remove_images" in validated_body
            assert validated_body["remove_images"] == valid_remove_images
            
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, SCRAPE_URL_CONTRACT
                )
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_remove_images_invalid(self, endpoint_caller):
        """Test remove_images parameter with invalid values from fixtures"""
        for invalid_remove_images in REMOVE_IMAGES["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "remove_images": invalid_remove_images}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_remove_images_null(self, endpoint_caller):
        """Test remove_images parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "remove_images": None}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )
        
        # remove_images is now optional and None values are excluded to save bandwidth
        validated_body = validated_request["body_params"]
        assert "remove_images" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")


    @pytest.mark.asyncio
    async def test_parameter_remove_class_names_valid(self, endpoint_caller):
        """Test remove_class_names parameter with valid values from fixtures"""
        for valid_class_names in REMOVE_CLASS_NAMES["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "remove_class_names": [valid_class_names]}
            
            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "remove_class_names" in validated_body
            assert validated_body["remove_class_names"] == [valid_class_names]
            
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, SCRAPE_URL_CONTRACT
                )
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_remove_class_names_invalid(self, endpoint_caller):
        """Test remove_class_names parameter with invalid values from fixtures"""
        for invalid_class_names in REMOVE_CLASS_NAMES["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "remove_class_names": [invalid_class_names]}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_remove_class_names_null(self, endpoint_caller):
        """Test remove_class_names parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "remove_class_names": None}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "remove_class_names" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_parser_valid(self, endpoint_caller):
        """Test parser parameter with valid values from fixtures"""
        param_key = PARSER["param_name"]
        for valid_parser in PARSER["param_values"]["valids"]:
            # Use Google search URL for google-search parser (parser requires matching URL type)
            url = "https://www.google.com/search?q=test&gl=us&hl=en" if isinstance(valid_parser, dict) and valid_parser.get("id") == "@olostep/google-search" else MINIMAL_REQUEST_BODY["url_to_scrape"]
            body_params = {"url_to_scrape": url, param_key: valid_parser}
            
            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert param_key in validated_body
            
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, SCRAPE_URL_CONTRACT
                )
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")

    @pytest.mark.asyncio
    async def test_parameter_parser_invalid(self, endpoint_caller):
        """Test parser parameter with invalid values from fixtures"""
        param_key = PARSER["param_name"]
        for invalid_parser in PARSER["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, param_key: invalid_parser}
            

            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)

            
            # Test API behavior with the request
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept or reject the values
            try:
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse, OlostepServerError_UnknownIssue, OlostepServerError_ParserNotFound):
                # API rejects invalid values or server errors - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_parser_null(self, endpoint_caller):
        """Test parser parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "parser": None}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "parser" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_llm_extract_valid(self, endpoint_caller):
        """Test llm_extract parameter with valid values from fixtures"""
        for valid_llm_extract in LLM_EXTRACT["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "llm_extract": valid_llm_extract}
            
            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "llm_extract" in validated_body
            assert validated_body["llm_extract"] == valid_llm_extract
            
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, SCRAPE_URL_CONTRACT
                )
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_llm_extract_invalid(self, endpoint_caller):
        """Test llm_extract parameter with invalid values from fixtures"""
        for invalid_llm_extract in LLM_EXTRACT["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "llm_extract": invalid_llm_extract}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_llm_extract_null(self, endpoint_caller):
        """Test llm_extract parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "llm_extract": None}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "llm_extract" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_links_on_page_valid(self, endpoint_caller):
        """Test links_on_page parameter with valid values from fixtures"""
        for valid_links_config in LINKS_ON_PAGE["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "links_on_page": valid_links_config}
            
            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "links_on_page" in validated_body
            
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, SCRAPE_URL_CONTRACT
                )
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_links_on_page_invalid(self, endpoint_caller):
        """Test links_on_page parameter with invalid values from fixtures"""
        for invalid_links_config in LINKS_ON_PAGE["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "links_on_page": invalid_links_config}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_links_on_page_null(self, endpoint_caller):
        """Test links_on_page parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "links_on_page": None}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )

        validated_body = validated_request["body_params"]
        assert "links_on_page" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_screen_size_valid(self, endpoint_caller):
        """Test screen_size parameter with valid values from fixtures"""
        for valid_screen_config in SCREEN_SIZE["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "screen_size": valid_screen_config}
            
            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "screen_size" in validated_body
            
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, SCRAPE_URL_CONTRACT
                )
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_screen_size_invalid(self, endpoint_caller):
        """Test screen_size parameter with invalid values from fixtures"""
        for invalid_screen_config in SCREEN_SIZE["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "screen_size": invalid_screen_config}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                response = await endpoint_caller._transport.request(request)
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_screen_size_null(self, endpoint_caller):
        """Test screen_size parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "screen_size": None}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )

        validated_body = validated_request["body_params"]
        assert "screen_size" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, SCRAPE_URL_CONTRACT
            )
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_metadata_valid(self, endpoint_caller):
        """Test metadata parameter with valid values from fixtures"""
        for valid_metadata in METADATA["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "metadata": valid_metadata}
            
            validated_request = endpoint_caller.validate_request(
                SCRAPE_URL_CONTRACT, body_params=body_params
            )
            
            validated_body = validated_request["body_params"]
            assert "metadata" in validated_body
            assert validated_body["metadata"] == valid_metadata
            
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, **validated_request
            )
            
            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, SCRAPE_URL_CONTRACT
                )
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
    
    @pytest.mark.asyncio
    async def test_parameter_metadata_invalid(self, endpoint_caller):
        """Test metadata parameter with invalid values from fixtures"""
        for invalid_metadata in METADATA["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "metadata": invalid_metadata}
            
            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(SCRAPE_URL_CONTRACT, body_params=body_params)
            
            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                SCRAPE_URL_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)
            
            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, CreateScrapeResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass
    
    @pytest.mark.asyncio
    async def test_parameter_metadata_null(self, endpoint_caller):
        """Test metadata parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "metadata": None}
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=body_params
        )
        
        validated_body = validated_request["body_params"]
        assert "metadata" not in validated_body
        
        request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        response = await endpoint_caller._transport.request(request)
        
        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = endpoint_caller._handle_response(request, response, SCRAPE_URL_CONTRACT)
            assert isinstance(model, CreateScrapeResponse)
        except OlostepServerError_TemporaryIssue:
            # Transient errors, capacity errors, and network busy errors are acceptable for contract testing - the important thing is validation passed
            pass


class TestScrapeGet:
    """Test cases for GET /scrapes/{scrape_id} endpoint."""
    
    @pytest.mark.asyncio
    async def test_get_existing_scrape(self, endpoint_caller):
        """Test getting an existing scrape by ID"""
        # First, create a scrape using MINIMAL_REQUEST_BODY
        create_body_params = MINIMAL_REQUEST_BODY
        
        validated_request = endpoint_caller.validate_request(
            SCRAPE_URL_CONTRACT, body_params=create_body_params
        )
        
        create_request = endpoint_caller._prepare_request(
            SCRAPE_URL_CONTRACT, **validated_request
        )
        
        try:
            create_response = await endpoint_caller._transport.request(create_request)
            create_model = endpoint_caller._handle_response(create_request, create_response, SCRAPE_URL_CONTRACT)
            assert isinstance(create_model, CreateScrapeResponse)
            scrape_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during scrape creation")
        
        # Now get the scrape using the ID from GET_SCRAPE_REQUEST_ID fixture
        scrape_id_param_name = GET_SCRAPE_REQUEST_ID["param_name"]
        get_path_params = {scrape_id_param_name: scrape_id}
        
        validated_request = endpoint_caller.validate_request(
            GET_SCRAPE_CONTRACT, path_params=get_path_params
        )
        
        validated_path = validated_request["path_params"]
        assert scrape_id_param_name in validated_path
        assert validated_path[scrape_id_param_name] == scrape_id
        
        get_request = endpoint_caller._prepare_request(
            GET_SCRAPE_CONTRACT, **validated_request
        )
        
        try:
            get_response = await endpoint_caller._transport.request(get_request)
            get_model = endpoint_caller._handle_response(get_request, get_response, GET_SCRAPE_CONTRACT)
            assert isinstance(get_model, GetScrapeResponse)
            assert get_model.id == scrape_id
            assert get_model.object == "scrape"
            # The API may modify the URL (add parameters), so just check it contains the original URL
            assert "example.com" in get_model.url
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during scrape retrieval")
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_scrape(self, endpoint_caller):
        """Test getting a non-existent scrape by ID"""
        # Try to get a scrape with an invalid ID from GET_SCRAPE_REQUEST_ID fixture
        scrape_id_param_name = GET_SCRAPE_REQUEST_ID["param_name"]
        invalid_scrape_id = GET_SCRAPE_REQUEST_ID["param_values"]["invalids"][0]
        get_path_params = {scrape_id_param_name: invalid_scrape_id}
        
        validated_request = endpoint_caller.validate_request(
            GET_SCRAPE_CONTRACT, path_params=get_path_params
        )
        
        validated_path = validated_request["path_params"]
        assert scrape_id_param_name in validated_path
        assert validated_path[scrape_id_param_name] == invalid_scrape_id
        
        get_request = endpoint_caller._prepare_request(
            GET_SCRAPE_CONTRACT, **validated_request
        )
        
        get_response = await endpoint_caller._transport.request(get_request)
        
        # Should raise an error for non-existent scrape
        with pytest.raises(OlostepServerError_ResourceNotFound):
            endpoint_caller._handle_response(get_request, get_response, GET_SCRAPE_CONTRACT)
    
