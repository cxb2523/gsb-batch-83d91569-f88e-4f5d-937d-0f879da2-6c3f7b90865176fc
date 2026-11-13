"""
Caller layer tests for Olostep SDK.

Tests the EndpointCaller class to ensure it properly handles retry logic
and error handling for API requests.
"""

from __future__ import annotations

import warnings
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from olostep.backend.api_endpoints import EndpointContract
from olostep.backend.caller import EndpointCaller
from olostep.backend.transport_protocol import RawAPIRequest, RawAPIResponse
from olostep.errors import Olostep_APIConnectionError
from olostep.retry_strategy import RetryStrategy


@pytest.mark.unit
class TestEndpointCallerRetryLogic:
    """Test retry logic with exponential backoff for connection errors."""

    @pytest.fixture
    def mock_transport(self) -> AsyncMock:
        """Create mock transport for testing."""
        transport = AsyncMock()
        # max_duration is a synchronous method, not async
        transport.max_duration = MagicMock(return_value=0.0)
        return transport

    @pytest.fixture
    def caller(self, mock_transport: AsyncMock) -> EndpointCaller:
        """Create caller instance with mock transport."""
        return EndpointCaller(
            transport=mock_transport, 
            base_url="https://api.test.com", 
            api_key="test_key",
            retry_strategy=RetryStrategy(max_retries=3)
        )
    

    @pytest.mark.asyncio
    async def test_successful_request(
        self, caller: EndpointCaller, mock_transport: AsyncMock
    ) -> None:
        """Test that successful requests work correctly."""
        expected_response = RawAPIResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body='{"success": true}'
        )
        mock_transport.request.return_value = expected_response

        # Create a simple contract for testing
        class TestResponse(BaseModel):
            success: bool
        
        contract = EndpointContract(
            key=("test", "endpoint"),
            name="Test Endpoint",
            description="Test endpoint for unit testing",
            method="GET",
            path="/test",
            response_model=TestResponse
        )

        result = await caller._invoke(contract)

        assert isinstance(result, TestResponse)
        assert result.success is True
        # Verify transport.request was called with a RawAPIRequest
        assert mock_transport.request.called
        call_args = mock_transport.request.call_args[0][0]
        assert isinstance(call_args, RawAPIRequest)
        assert call_args.method == "GET"
        assert call_args.url == "https://api.test.com/test"

    @pytest.mark.asyncio
    async def test_connection_error_propagated(
        self, caller: EndpointCaller, mock_transport: AsyncMock
    ) -> None:
        """Test that connection errors are propagated from transport."""
        mock_transport.request.side_effect = Olostep_APIConnectionError()

        # Create a simple contract for testing
        class EmptyResponse(BaseModel):
            pass
        
        contract = EndpointContract(
            key=("test", "endpoint"),
            name="Test Endpoint",
            description="Test endpoint for unit testing",
            method="GET",
            path="/test",
            response_model=EmptyResponse
        )

        with pytest.raises(Olostep_APIConnectionError):
            await caller._invoke(contract)

        mock_transport.request.assert_called_once()


@pytest.mark.unit
class TestExtraFieldWarnings:
    """Test extra field detection and warning system."""

    @pytest.fixture
    def mock_transport(self) -> AsyncMock:
        """Create mock transport for testing."""
        transport = AsyncMock()
        transport.max_duration = MagicMock(return_value=0.0)
        return transport

    @pytest.fixture
    def caller(self, mock_transport: AsyncMock) -> EndpointCaller:
        """Create caller instance with mock transport."""
        return EndpointCaller(
            transport=mock_transport,
            base_url="https://api.test.com",
            api_key="test_key",
            retry_strategy=RetryStrategy(max_retries=3)
        )

    @pytest.mark.asyncio
    async def test_extra_field_triggers_warning(
        self, caller: EndpointCaller, mock_transport: AsyncMock
    ) -> None:
        """Test that truly extra fields (not handled by validators) trigger warnings."""
        from olostep.models.base import OlostepResponseBaseModel

        class TestResponse(OlostepResponseBaseModel):
            id: str
            name: str

        contract = EndpointContract(
            key=("test", "endpoint"),
            name="Test Endpoint",
            description="Test endpoint for unit testing",
            method="GET",
            path="/test",
            response_model=TestResponse
        )

        # Response with an extra field that's not in the model and not handled by validators
        response_with_extra = RawAPIResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body='{"id": "test_123", "name": "Test", "unknown_field": "extra_value"}'
        )
        mock_transport.request.return_value = response_with_extra

        request = RawAPIRequest(
            method="GET",
            url="https://api.test.com/test",
            query=None,
            json=None,
            headers=None
        )

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = caller._handle_response(request, response_with_extra, contract)

            assert len(w) == 1
            assert issubclass(w[0].category, UserWarning)
            assert "extra field(s)" in str(w[0].message)
            assert "unknown_field" in str(w[0].message)

        assert isinstance(result, TestResponse)
        assert result.id == "test_123"
        assert result.name == "Test"

    @pytest.mark.asyncio
    async def test_normalized_field_no_warning(
        self, caller: EndpointCaller, mock_transport: AsyncMock
    ) -> None:
        """Test that fields handled by validators (like batch_id) don't trigger warnings."""
        from olostep.models.response import BatchInfoResponse

        contract = EndpointContract(
            key=("batch", "info"),
            name="Get Batch Info",
            description="Get batch info for testing",
            method="GET",
            path="/batches/{batch_id}",
            response_model=BatchInfoResponse
        )

        # Response with batch_id which is normalized by validator
        response_with_batch_id = RawAPIResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body='{"id": "batch_123", "batch_id": "batch_123", "object": "batch", "status": "completed", "created": 1234567890, "total_urls": 5, "completed_urls": 5, "number_retried": 0, "parser": "none", "start_date": "2023-01-01"}'
        )
        mock_transport.request.return_value = response_with_batch_id

        request = RawAPIRequest(
            method="GET",
            url="https://api.test.com/batches/batch_123",
            query=None,
            json=None,
            headers=None
        )

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = caller._handle_response(request, response_with_batch_id, contract)

            # Should have no warnings - batch_id is handled by validator
            extra_field_warnings = [
                warning for warning in w
                if issubclass(warning.category, UserWarning)
                and "extra field" in str(warning.message).lower()
            ]
            assert len(extra_field_warnings) == 0

        assert isinstance(result, BatchInfoResponse)
        assert result.id == "batch_123"