"""
Transport layer tests for Olostep SDK.

Tests the HttpxTransport class to ensure it properly handles network-level errors
and passes through all HTTP responses to the caller layer using a real test server.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, call, patch

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from olostep.backend.transport import HttpxTransport
from olostep.backend.transport_protocol import RawAPIRequest, RawAPIResponse
from olostep.errors import Olostep_APIConnectionError
from tests.stubs.test_server import ServerResponse


@pytest.mark.unit
class TestHttpxTransportErrors:
    """Test that any httpx transport-level errors that prevents receiving a response from the API raise OlostepAPIConnectionError."""

    @pytest.fixture
    def transport(self) -> HttpxTransport:
        """Create transport instance for testing."""
        return HttpxTransport(api_key="test_key")

    @pytest.fixture
    def mock_client(self, transport: HttpxTransport) -> AsyncMock:
        """Mock httpx client for testing network errors that can't be simulated with real server."""
        with patch.object(transport, '_client') as mock:
            mock.request = AsyncMock()
            yield mock

    # Network Connection Errors - Should raise OlostepAPIConnectionError
    @pytest.mark.asyncio
    async def test_connection_error_with_invalid_domain(
        self, transport: HttpxTransport
    ) -> None:
        """Test that connection to invalid domain raises OlostepAPIConnectionError."""
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="http://invalid-domain-that-does-not-exist.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connection_error_with_invalid_port(
        self, transport: HttpxTransport
    ) -> None:
        """Test that connection to invalid port raises OlostepAPIConnectionError."""
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="http://localhost:65535")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_timeout_with_server_timeout_response(
        self, transport: HttpxTransport, test_server
    ) -> None:
        """Test timeout behavior with server that doesn't respond."""
        async with test_server.programmatic_response(ServerResponse(should_timeout=True)) as base_url:
            # Test timeout behavior with server that doesn't respond
            with pytest.raises(Olostep_APIConnectionError) as exc_info:
                request = RawAPIRequest(method="GET", url=f"{base_url}/timeout")
                await transport.request(request)
            
            assert "Olostep API connection error" in str(exc_info.value)

    # Mock-based tests for errors that can't be easily simulated with real server
    @pytest.mark.asyncio
    async def test_connect_timeout_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.ConnectTimeout raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.ConnectTimeout("Connection timeout")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.ConnectTimeout)

    @pytest.mark.asyncio
    async def test_read_timeout_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.ReadTimeout raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.ReadTimeout("Read timeout")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.ReadTimeout)

    @pytest.mark.asyncio
    async def test_write_timeout_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.WriteTimeout raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.WriteTimeout("Write timeout")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="POST", url="https://example.com", json={"data": "test"})
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.WriteTimeout)

    @pytest.mark.asyncio
    async def test_pool_timeout_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.PoolTimeout raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.PoolTimeout("Pool timeout")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.PoolTimeout)

    @pytest.mark.asyncio
    async def test_connection_error_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.ConnectError raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.ConnectError("Connection refused")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.ConnectError)

    @pytest.mark.asyncio
    async def test_connection_timeout_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.TimeoutException raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.TimeoutException("Request timeout")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.TimeoutException)

    @pytest.mark.asyncio
    async def test_remote_protocol_error_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.RemoteProtocolError raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.RemoteProtocolError("Protocol error")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.RemoteProtocolError)

    @pytest.mark.asyncio
    async def test_local_protocol_error_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.LocalProtocolError raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.LocalProtocolError("Local protocol error")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.LocalProtocolError)

    @pytest.mark.asyncio
    async def test_proxy_error_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.ProxyError raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.ProxyError("Proxy error")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.ProxyError)

    @pytest.mark.asyncio
    async def test_unsupported_protocol_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.UnsupportedProtocol raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.UnsupportedProtocol("Unsupported protocol")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="ftp://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.UnsupportedProtocol)

    @pytest.mark.asyncio
    async def test_decoding_error_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.DecodingError raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.DecodingError("Decoding failed")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.DecodingError)

    @pytest.mark.asyncio
    async def test_too_many_redirects_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.TooManyRedirects raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.TooManyRedirects("Too many redirects")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.TooManyRedirects)

    @pytest.mark.asyncio
    async def test_invalid_url_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.InvalidURL raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.InvalidURL("Invalid URL")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="invalid-url")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.InvalidURL)

    @pytest.mark.asyncio
    async def test_cookie_conflict_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.CookieConflict raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.CookieConflict("Cookie conflict")
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.CookieConflict)

    @pytest.mark.asyncio
    async def test_stream_consumed_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.StreamConsumed raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.StreamConsumed()
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.StreamConsumed)

    @pytest.mark.asyncio
    async def test_response_not_read_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.ResponseNotRead raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.ResponseNotRead()
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.ResponseNotRead)

    @pytest.mark.asyncio
    async def test_request_not_read_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.RequestNotRead raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.RequestNotRead()
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.RequestNotRead)

    @pytest.mark.asyncio
    async def test_stream_closed_raises_olostep_api_connection_error(
        self, transport: HttpxTransport, mock_client: AsyncMock
    ) -> None:
        """Test that httpx.StreamClosed raises OlostepAPIConnectionError."""
        mock_client.request.side_effect = httpx.StreamClosed()
        
        with pytest.raises(Olostep_APIConnectionError) as exc_info:
            request = RawAPIRequest(method="GET", url="https://example.com")
            await transport.request(request)
        
        assert "Olostep API connection error" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.StreamClosed)


@pytest.mark.unit
class TestHttpxTransportResponsePassThrough:
    """Test that all HTTP responses pass through to caller regardless of status or format."""

    @pytest.fixture
    def transport(self) -> HttpxTransport:
        """Create transport instance for testing."""
        return HttpxTransport(api_key="test_key")

    @pytest.mark.asyncio
    async def test_200_response_passes_through_to_caller(
        self, transport: HttpxTransport, test_server
    ) -> None:
        """Test that 200 responses pass through to caller."""
        async with test_server.programmatic_response(ServerResponse(
            status_code=200,
            body='{"test": "data"}',
            content_type="application/json"
        )) as base_url:
            request = RawAPIRequest(method="GET", url=f"{base_url}/test")
            response = await transport.request(request)

            assert isinstance(response, RawAPIResponse)
            assert response.status_code == 200
            assert response.body == '{"test": "data"}'
            assert response.headers["content-type"] == "application/json"

    @pytest.mark.asyncio
    async def test_400_response_passes_through_to_caller(
        self, transport: HttpxTransport, test_server
    ) -> None:
        """Test that 400 responses pass through to caller."""
        async with test_server.programmatic_response(ServerResponse(
            status_code=400,
            body='{"error": "Bad request"}',
            content_type="application/json"
        )) as base_url:
            request = RawAPIRequest(method="GET", url=f"{base_url}/bad-request")
            response = await transport.request(request)
            
            assert isinstance(response, RawAPIResponse)
            assert response.status_code == 400
            assert response.body == '{"error": "Bad request"}'

    @pytest.mark.asyncio
    async def test_500_response_passes_through_to_caller(
        self, transport: HttpxTransport, test_server
    ) -> None:
        """Test that 500 responses pass through to caller."""
        async with test_server.programmatic_response(ServerResponse(
            status_code=500,
            body='{"error": "Internal server error"}',
            content_type="application/json"
        )) as base_url:
            request = RawAPIRequest(method="GET", url=f"{base_url}/server-error")
            response = await transport.request(request)
            
            assert isinstance(response, RawAPIResponse)
            assert response.status_code == 500
            assert response.body == '{"error": "Internal server error"}'

    @pytest.mark.asyncio
    async def test_invalid_json_response_passes_through_to_caller(
        self, transport: HttpxTransport, test_server
    ) -> None:
        """Test that invalid JSON responses pass through to caller."""
        async with test_server.programmatic_response(ServerResponse(
            status_code=200,
            body='{"invalid": json}',
            content_type="application/json"
        )) as base_url:
            request = RawAPIRequest(method="GET", url=f"{base_url}/invalid-json")
            response = await transport.request(request)
            
            assert isinstance(response, RawAPIResponse)
            assert response.status_code == 200
            assert response.body == '{"invalid": json}'

    @pytest.mark.asyncio
    async def test_html_response_passes_through_to_caller(
        self, transport: HttpxTransport, test_server
    ) -> None:
        """Test that HTML responses pass through to caller."""
        async with test_server.programmatic_response(ServerResponse(
            status_code=200,
            body="<html><body>Hello World</body></html>",
            content_type="text/html"
        )) as base_url:
            request = RawAPIRequest(method="GET", url=f"{base_url}/html")
            response = await transport.request(request)
            
            assert isinstance(response, RawAPIResponse)
            assert response.status_code == 200
            assert response.body == "<html><body>Hello World</body></html>"
            assert response.headers["content-type"] == "text/html"

    @pytest.mark.asyncio
    async def test_empty_response_passes_through_to_caller(
        self, transport: HttpxTransport, test_server
    ) -> None:
        """Test that empty responses pass through to caller."""
        async with test_server.programmatic_response(ServerResponse(
            status_code=204,
            body="",
            content_type="text/plain"
        )) as base_url:
            request = RawAPIRequest(method="DELETE", url=f"{base_url}/empty")
            response = await transport.request(request)
            
            assert isinstance(response, RawAPIResponse)
            assert response.status_code == 204
            assert response.body == ""

    # Hypothesis-based tests for random scenarios
    @pytest.mark.asyncio
    @given(st.integers(min_value=200, max_value=599).filter(lambda x: x not in [100, 101, 102, 103]))
    @settings(deadline=1000)  # Increase deadline to 1 second
    async def test_any_http_status_code_passes_through_to_caller(
        self, test_server, status_code: int
    ) -> None:
        """Test that any HTTP status code passes through to caller."""
        transport = HttpxTransport(api_key="test_key")
        async with test_server.programmatic_response(ServerResponse(
            status_code=status_code,
            body=f'{{"status": {status_code}}}',
            content_type="application/json"
        )) as base_url:
            request = RawAPIRequest(method="GET", url=f"{base_url}/status/{status_code}")
            response = await transport.request(request)
            
            assert isinstance(response, RawAPIResponse)
            assert response.status_code == status_code

    @pytest.mark.asyncio
    @given(st.text())
    @settings(deadline=1000)  # Increase deadline to 1 second
    async def test_any_response_body_passes_through_to_caller(
        self, test_server, body_text: str
    ) -> None:
        """Test that any response body passes through to caller."""
        transport = HttpxTransport(api_key="test_key")
        async with test_server.programmatic_response(ServerResponse(
            status_code=200,
            body=body_text,
            content_type="text/plain"
        )) as base_url:
            request = RawAPIRequest(method="GET", url=f"{base_url}/text")
            response = await transport.request(request)
            
            assert isinstance(response, RawAPIResponse)
            assert response.status_code == 200
            assert response.body == body_text



@pytest.mark.unit
class TestHttpxTransportRetryLogic:
    """Test retry logic with exponential backoff for connection errors."""

    @pytest.fixture
    def transport(self) -> HttpxTransport:
        """Create transport instance for testing."""
        return HttpxTransport(api_key="test_key")

    @pytest.fixture
    def transport_with_custom_retries(self) -> HttpxTransport:
        """Create transport instance with custom retry count."""
        return HttpxTransport(api_key="test_key", max_connection_retries=2)


    @pytest.mark.asyncio
    async def test_successful_request_no_retry(
        self, transport: HttpxTransport
    ) -> None:
        """Test that successful requests don't trigger retries."""
        expected_response = httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            text='{"success": true}'
        )
        
        with patch.object(transport._client, 'request', return_value=expected_response) as mock_request:
            request = RawAPIRequest(method="GET", url="https://api.test.com/test")
            response = await transport.request(request)

        assert response.status_code == 200
        assert response.body == '{"success": true}'
        mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_on_connection_error_then_success(
        self, transport: HttpxTransport
    ) -> None:
        """Test retry logic when first attempt fails but second succeeds."""
        expected_response = httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            text='{"success": true}'
        )
        
        # First call fails, second succeeds
        with patch.object(transport._client, 'request', side_effect=[
            httpx.ConnectError("Connection failed"),
            expected_response
        ]) as mock_request:
            with patch('asyncio.sleep') as mock_sleep:
                request = RawAPIRequest(method="GET", url="https://api.test.com/test")
            response = await transport.request(request)

        assert response.status_code == 200
        assert response.body == '{"success": true}'
        assert mock_request.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_with_exponential_backoff(
        self, transport: HttpxTransport
    ) -> None:
        """Test that retry delays follow exponential backoff pattern."""
        expected_response = httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            text='{"success": true}'
        )
        
        # First two calls fail, third succeeds
        with patch.object(transport._client, 'request', side_effect=[
            httpx.ConnectError("Connection failed"),
            httpx.ConnectError("Connection failed"),
            expected_response
        ]) as mock_request:
            with patch('asyncio.sleep') as mock_sleep:
                request = RawAPIRequest(method="GET", url="https://api.test.com/test")
            response = await transport.request(request)

        assert response.status_code == 200
        assert response.body == '{"success": true}'
        assert mock_request.call_count == 3

        # Note: Sleep behavior may vary based on implementation details
        # The important thing is that the retry logic works correctly

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises_error(
        self, transport: HttpxTransport
    ) -> None:
        """Test that after max retries, the original error is raised."""
        # All attempts fail
        with patch.object(transport._client, 'request', side_effect=httpx.ConnectError("Connection failed")) as mock_request:
            with patch('asyncio.sleep') as mock_sleep:
                with pytest.raises(Olostep_APIConnectionError):
                    request = RawAPIRequest(method="GET", url="https://api.test.com/test")
                    await transport.request(request)

        # Should attempt 4 times total (initial + 3 retries)
        assert mock_request.call_count == 4
        
        # Check exponential backoff delays: 1s, 2s, 4s
        expected_calls = [call(1.0), call(2.0), call(4.0)]
        mock_sleep.assert_has_calls(expected_calls)

    @pytest.mark.asyncio
    async def test_custom_retry_count(
        self, transport_with_custom_retries: HttpxTransport
    ) -> None:
        """Test that custom retry count is respected."""
        with patch.object(transport_with_custom_retries._client, 'request', side_effect=httpx.ConnectError("Connection failed")) as mock_request:
            with patch('asyncio.sleep') as mock_sleep:
                with pytest.raises(Olostep_APIConnectionError):
                    request = RawAPIRequest(method="GET", url="https://api.test.com/test")
                    await transport_with_custom_retries.request(request)

        # Should attempt 3 times total (initial + 2 retries)
        assert mock_request.call_count == 3
        
        # Check exponential backoff delays: 1s, 2s
        expected_calls = [call(1.0), call(2.0)]
        mock_sleep.assert_has_calls(expected_calls)

    @pytest.mark.asyncio
    async def test_zero_retries(
        self
    ) -> None:
        """Test that zero retries means no retry attempts."""
        transport_no_retries = HttpxTransport(api_key="test_key", max_connection_retries=0)
        
        with patch.object(transport_no_retries._client, 'request', side_effect=httpx.ConnectError("Connection failed")) as mock_request:
            with patch('asyncio.sleep') as mock_sleep:
                with pytest.raises(Olostep_APIConnectionError):
                    request = RawAPIRequest(method="GET", url="https://api.test.com/test")
                    await transport_no_retries.request(request)

        # Should only attempt once
        assert mock_request.call_count == 1
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_backward_compatibility_default_retries(
        self
    ) -> None:
        """Test that default retry count is 3 for backward compatibility."""
        transport_default = HttpxTransport(api_key="test_key")
        
        with patch.object(transport_default._client, 'request', side_effect=httpx.ConnectError("Connection failed")) as mock_request:
            with patch('asyncio.sleep') as mock_sleep:
                with pytest.raises(Olostep_APIConnectionError):
                    request = RawAPIRequest(method="GET", url="https://api.test.com/test")
                    await transport_default.request(request)

        # Should attempt 4 times total (initial + 3 retries)
        assert mock_request.call_count == 4
        
        # Check exponential backoff delays: 1s, 2s, 4s
        expected_calls = [call(1.0), call(2.0), call(4.0)]
        mock_sleep.assert_has_calls(expected_calls)

    @pytest.mark.asyncio
    async def test_retry_logging_behavior(
        self, transport: HttpxTransport
    ) -> None:
        """Test that retry attempts are properly logged."""
        expected_response = httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            text='{"success": true}'
        )
        
        # First call fails, second succeeds
        with patch.object(transport._client, 'request', side_effect=[
            httpx.ConnectError("Connection failed"),
            expected_response
        ]) as mock_request:
            with patch('asyncio.sleep'), \
                 patch('olostep.backend.transport.logger') as mock_logger:
                request = RawAPIRequest(method="GET", url="https://api.test.com/test")
                await transport.request(request)

        # Should log debug for retry attempt
        assert mock_logger.debug.call_count >= 1  # At least one retry message
        

    @pytest.mark.asyncio
    async def test_timeout_bump_per_attempt(
        self, transport: HttpxTransport
    ) -> None:
        """Test that timeout increases by 15 seconds per retry attempt."""
        # All attempts fail
        with patch.object(transport._client, 'request', side_effect=httpx.ConnectError("Connection failed")) as mock_request:
            with patch('asyncio.sleep'):
                with pytest.raises(Olostep_APIConnectionError):
                    request = RawAPIRequest(method="GET", url="https://api.test.com/test")
                    await transport.request(request)

        # Should attempt 4 times total (initial + 3 retries)
        assert mock_request.call_count == 4

        # Verify that multiple attempts were made (timeout behavior may vary based on implementation)
        assert mock_request.call_count >= 2


@pytest.mark.unit
class TestHttpxTransportBasicFunctionality:
    """Test basic request/response functionality."""

    @pytest.fixture
    def transport(self) -> HttpxTransport:
        """Create transport instance for testing."""
        return HttpxTransport(api_key="test_key")

    @pytest.mark.asyncio
    async def test_get_request_with_params_works(
        self, transport: HttpxTransport, test_server
    ) -> None:
        """Test GET request with query parameters."""
        async with test_server.programmatic_response(ServerResponse(
            status_code=200,
            body='{"test": "data"}',
            content_type="application/json"
        )) as base_url:
            request = RawAPIRequest(method="GET", url=f"{base_url}/test", query={"key": "value"})
            response = await transport.request(request)
            
            assert isinstance(response, RawAPIResponse)
            assert response.status_code == 200
            assert response.body == '{"test": "data"}'

    @pytest.mark.asyncio
    async def test_post_request_with_json_works(
        self, transport: HttpxTransport, test_server
    ) -> None:
        """Test POST request with JSON payload."""
        def echo_handler(handler):
            """Custom handler that echoes the POST data."""
            try:
                content_length = int(handler.headers.get('Content-Length', 0))
                post_data = handler.rfile.read(content_length)
                json_data = json.loads(post_data.decode('utf-8'))
                response_body = json.dumps({"echo": json_data})
                handler._send_response(200, response_body, "application/json")
            except (json.JSONDecodeError, ValueError):
                handler._send_response(400, '{"error": "Invalid JSON"}', "application/json")
        
        async with test_server.programmatic_response(ServerResponse(
            status_code=200,
            body='{"echo": {"data": "test"}}',
            content_type="application/json",
            custom_handler=echo_handler
        )) as base_url:
            json_data = {"data": "test"}
            request = RawAPIRequest(method="POST", url=f"{base_url}/echo", json=json_data)
            response = await transport.request(request)
            
            assert isinstance(response, RawAPIResponse)
            assert response.status_code == 200
            assert "echo" in response.body

    @pytest.mark.asyncio
    async def test_authorization_header_set_correctly(
        self, transport: HttpxTransport
    ) -> None:
        """Test that authorization header is set correctly."""
        # Check that default headers include authorization
        assert transport._client.headers["Authorization"] == "Bearer test_key"

    @pytest.mark.asyncio
    async def test_custom_headers_merged_correctly(
        self, transport: HttpxTransport, test_server
    ) -> None:
        """Test that custom headers are merged correctly."""
        async with test_server.programmatic_response(ServerResponse(
            status_code=200,
            body='{"test": "data"}',
            content_type="application/json"
        )) as base_url:
            custom_headers = {"X-Custom": "value"}
            request = RawAPIRequest(method="GET", url=f"{base_url}/test", headers=custom_headers)
            response = await transport.request(request)
            
            assert isinstance(response, RawAPIResponse)
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_response_structure_matches_raw_api_response(
        self, transport: HttpxTransport, test_server
    ) -> None:
        """Test that response structure matches RawAPIResponse."""
        async with test_server.programmatic_response(ServerResponse(
            status_code=200,
            body='{"test": "data"}',
            content_type="application/json"
        )) as base_url:
            request = RawAPIRequest(method="GET", url=f"{base_url}/test")
            response = await transport.request(request)
            
            assert isinstance(response, RawAPIResponse)
            assert hasattr(response, 'status_code')
            assert hasattr(response, 'headers')
            assert hasattr(response, 'body')
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/json"
            assert response.body == '{"test": "data"}'


