"""
Answers endpoint contract validation tests.

This test suite validates answers endpoint contracts against the API using httpx transport directly.
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
from olostep.models.response import AnswersResponse
from tests.conftest import extract_request_parameters, retry_request
from tests.fixtures.api.requests.answers import (
    GET_ANSWER_REQUEST_ID,
    JSON_FORMAT,
    MINIMAL_REQUEST_BODY,
    TASK,
)

ANSWERS_CREATE_CONTRACT = CONTRACTS[('answers', 'create')]
ANSWERS_GET_CONTRACT = CONTRACTS[('answers', 'get')]

BASE_URL = "https://api.olostep.com/v1"


class TestAnswersCreate:
    """Test answers creation with various parameter combinations."""

    @pytest.mark.asyncio
    async def test_self_test_parameter_coverage(self):
        """Self-test: Verify that we have test methods for each parameter in the request model."""
        # Extract all parameters from the request model
        all_params = extract_request_parameters(ANSWERS_CREATE_CONTRACT.request_model)
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
            endpoint_caller.validate_request(ANSWERS_CREATE_CONTRACT, body_params=body_params)

        # But if we bypass validation and send it to the API anyway, the API should ignore the unknown parameters
        request = endpoint_caller._prepare_request(
            ANSWERS_CREATE_CONTRACT, {}, {}, body_params
        )

        # The API should accept the request and ignore the unknown parameters
        try:
            model = await retry_request(
                endpoint_caller, request, ANSWERS_CREATE_CONTRACT
            )
            assert isinstance(model, AnswersResponse)
            # Verify the response is valid despite the unknown parameters
            assert model.id is not None
            assert model.object == "answer"
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")

    @pytest.mark.asyncio
    async def test_parameter_task_valid(self, endpoint_caller):
        """Test task parameter with valid values from fixtures"""
        for valid_task in TASK["param_values"]["valids"]:
            body_params = {"task": valid_task}

            validated_request = endpoint_caller.validate_request(
                ANSWERS_CREATE_CONTRACT, body_params=body_params
            )

            validated_body = validated_request["body_params"]
            assert "task" in validated_body
            assert validated_body["task"] == valid_task

            request = endpoint_caller._prepare_request(
                ANSWERS_CREATE_CONTRACT, **validated_request
            )

            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, ANSWERS_CREATE_CONTRACT
                )
                assert isinstance(model, AnswersResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")

    @pytest.mark.asyncio
    async def test_parameter_task_invalid(self, endpoint_caller):
        """Test task parameter with invalid values from fixtures"""
        for invalid_task in TASK["param_values"]["invalids"]:
            body_params = {"task": invalid_task}

            with pytest.raises(OlostepClientError_RequestValidationFailed):
                endpoint_caller.validate_request(ANSWERS_CREATE_CONTRACT, body_params=body_params)

            # Test API behavior with invalid request (bypass validation)
            request = endpoint_caller._prepare_request(
                ANSWERS_CREATE_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)

            # API may accept invalid values (our validation is stricter than API)
            try:
                model = endpoint_caller._handle_response(request, response, ANSWERS_CREATE_CONTRACT)
                # If API accepts invalid values, that's also acceptable for contract testing
                assert isinstance(model, AnswersResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass

    @pytest.mark.asyncio
    async def test_parameter_task_null(self, endpoint_caller):
        """Test task parameter with null value"""
        body_params = {"task": None}

        with pytest.raises(OlostepClientError_RequestValidationFailed):
            endpoint_caller.validate_request(ANSWERS_CREATE_CONTRACT, body_params=body_params)

        # Test API behavior with null request (bypass validation)
        request = endpoint_caller._prepare_request(
            ANSWERS_CREATE_CONTRACT, {}, {}, body_params
        )
        response = await endpoint_caller._transport.request(request)

        # API returns 500 error for this null requests
        with pytest.raises(OlostepServerError_RequestUnprocessable):
            endpoint_caller._handle_response(request, response, ANSWERS_CREATE_CONTRACT)

    @pytest.mark.asyncio
    async def test_parameter_json_format_valid(self, endpoint_caller):
        """Test json_format parameter with valid values from fixtures"""
        for valid_json_format in JSON_FORMAT["param_values"]["valids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "json_format": valid_json_format}

            validated_request = endpoint_caller.validate_request(
                ANSWERS_CREATE_CONTRACT, body_params=body_params
            )

            validated_body = validated_request["body_params"]
            if valid_json_format is not None:
                assert "json_format" in validated_body
            else:
                assert "json_format" not in validated_body

            request = endpoint_caller._prepare_request(
                ANSWERS_CREATE_CONTRACT, **validated_request
            )

            # Valid requests should either succeed or have transient errors (not server errors)
            try:
                model = await retry_request(
                    endpoint_caller, request, ANSWERS_CREATE_CONTRACT
                )
                assert isinstance(model, AnswersResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")

    @pytest.mark.asyncio
    async def test_parameter_json_format_invalid(self, endpoint_caller):
        """Test json_format parameter with invalid values from fixtures
        
        API OBSERVED BEHAVIOR: The SDK's request validation accepts some invalid json_format
        values (like strings and numbers) that should be dicts. The API also accepts these
        invalid values and returns 200 OK responses. This test documents the "as is" behavior
        where both SDK validation and API are lenient with json_format parameter types.
        """
        for invalid_json_format in JSON_FORMAT["param_values"]["invalids"]:
            body_params = {**MINIMAL_REQUEST_BODY, "json_format": invalid_json_format}

            # SDK validation may or may not catch invalid values - test documents actual behavior
            try:
                endpoint_caller.validate_request(ANSWERS_CREATE_CONTRACT, body_params=body_params)
                # If validation passes, continue to test API behavior
            except OlostepClientError_RequestValidationFailed:
                # If validation fails, that's also acceptable - skip API test for this value
                continue

            # Test API behavior with invalid request (bypass validation if needed)
            # The API accepts invalid json_format values and returns 200 OK
            request = endpoint_caller._prepare_request(
                ANSWERS_CREATE_CONTRACT, {}, {}, body_params
            )
            response = await endpoint_caller._transport.request(request)

            # API accepts invalid values and returns successful responses
            try:
                model = endpoint_caller._handle_response(request, response, ANSWERS_CREATE_CONTRACT)
                # API accepts invalid values - documented "as is" behavior
                assert isinstance(model, AnswersResponse)
            except OlostepServerError_TemporaryIssue:
                # API raised a temporary error - skip this test
                pytest.skip("API raised a temporary error")
            except (OlostepServerError_RequestUnprocessable, OlostepServerError_NoResultInResponse):
                # API rejects invalid values - also acceptable
                pass
            except OlostepClientError_ResponseValidationFailed:
                # API returns garbage/malformed responses when given invalid json_format - expected behavior
                pass

    @pytest.mark.asyncio
    async def test_parameter_json_format_null(self, endpoint_caller):
        """Test json_format parameter with null value"""
        body_params = {**MINIMAL_REQUEST_BODY, "json_format": None}

        validated_request = endpoint_caller.validate_request(
            ANSWERS_CREATE_CONTRACT, body_params=body_params
        )

        validated_body = validated_request["body_params"]
        assert "json_format" not in validated_body

        request = endpoint_caller._prepare_request(
            ANSWERS_CREATE_CONTRACT, **validated_request
        )

        # Valid requests should either succeed or have transient errors (not server errors)
        try:
            model = await retry_request(
                endpoint_caller, request, ANSWERS_CREATE_CONTRACT
            )
            assert isinstance(model, AnswersResponse)
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")

    @pytest.mark.asyncio
    async def test_basic_functionality_with_fixture_data(self, endpoint_caller):
        """Test basic functionality using the fixture data"""
        body_params = MINIMAL_REQUEST_BODY

        validated_request = endpoint_caller.validate_request(
            ANSWERS_CREATE_CONTRACT, body_params=body_params
        )

        request = endpoint_caller._prepare_request(
            ANSWERS_CREATE_CONTRACT, **validated_request
        )

        try:
            model = await retry_request(
                endpoint_caller, request, ANSWERS_CREATE_CONTRACT
            )
            assert isinstance(model, AnswersResponse)
            assert model.id is not None
            assert model.object == "answer"
            assert model.task is not None
            assert model.result is not None
            assert model.result.json_content is not None or model.result.json_hosted_url is not None
        except OlostepServerError_TemporaryIssue:
            # API raised a temporary error - skip this test
            pytest.skip("API raised a temporary error")


class TestAnswersGet:
    """Test cases for GET /answers/{answer_id} endpoint."""

    @pytest.mark.asyncio
    async def test_get_existing_answer(self, endpoint_caller):
        """Test getting an existing answer by ID"""
        # First, create an answer using MINIMAL_REQUEST_BODY and wait for it to be ready
        create_body_params = MINIMAL_REQUEST_BODY

        validated_request = endpoint_caller.validate_request(
            ANSWERS_CREATE_CONTRACT, body_params=create_body_params
        )

        create_request = endpoint_caller._prepare_request(
            ANSWERS_CREATE_CONTRACT, **validated_request
        )

        try:
            create_model = await retry_request(
                endpoint_caller, create_request, ANSWERS_CREATE_CONTRACT
            )
            assert isinstance(create_model, AnswersResponse)
            answer_id = create_model.id
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during answer creation")

        # Now get the answer using the ID we just created
        answer_id_param_name = GET_ANSWER_REQUEST_ID["param_name"]
        get_path_params = {answer_id_param_name: answer_id}

        validated_request = endpoint_caller.validate_request(
            ANSWERS_GET_CONTRACT, path_params=get_path_params
        )

        validated_path = validated_request["path_params"]
        assert answer_id_param_name in validated_path
        assert validated_path[answer_id_param_name] == answer_id

        get_request = endpoint_caller._prepare_request(
            ANSWERS_GET_CONTRACT, **validated_request
        )

        try:
            get_model = await retry_request(
                endpoint_caller, get_request, ANSWERS_GET_CONTRACT
            )
            assert isinstance(get_model, AnswersResponse)
            assert get_model.id == answer_id
            assert get_model.object == "answer"
            assert get_model.task is not None
        except OlostepServerError_TemporaryIssue:
            pytest.skip("API raised a temporary error during answer retrieval")

    @pytest.mark.asyncio
    async def test_get_nonexistent_answer(self, endpoint_caller):
        """Test getting a non-existent answer by ID"""
        # Try to get an answer with an invalid ID from GET_ANSWER_REQUEST_ID fixture
        answer_id_param_name = GET_ANSWER_REQUEST_ID["param_name"]
        invalid_answer_id = GET_ANSWER_REQUEST_ID["param_values"]["invalids"][0]
        get_path_params = {answer_id_param_name: invalid_answer_id}

        validated_request = endpoint_caller.validate_request(
            ANSWERS_GET_CONTRACT, path_params=get_path_params
        )

        validated_path = validated_request["path_params"]
        assert answer_id_param_name in validated_path
        assert validated_path[answer_id_param_name] == invalid_answer_id

        get_request = endpoint_caller._prepare_request(
            ANSWERS_GET_CONTRACT, **validated_request
        )

        get_response = await endpoint_caller._transport.request(get_request)

        # Should raise an error for non-existent answer
        with pytest.raises(OlostepServerError_ResourceNotFound):
            endpoint_caller._handle_response(get_request, get_response, ANSWERS_GET_CONTRACT)
