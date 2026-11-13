"""
How the caller maps 401 responses, and how the auth error masks the API key.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from olostep.backend.api_endpoints import EndpointContract
from olostep.backend.caller import EndpointCaller
from olostep.backend.transport_protocol import RawAPIResponse
from olostep.errors import (
    OlostepServerError_AuthFailed,
    OlostepServerError_BlacklistedDomain,
)
from olostep.retry_strategy import RetryStrategy

API_KEY = "olostep_test_key_abcdefghijklmnop1234"


class _Response(BaseModel):
    success: bool


CONTRACT = EndpointContract(
    key=("test", "endpoint"),
    name="Test Endpoint",
    description="Test endpoint for unit testing",
    method="GET",
    path="/test",
    response_model=_Response,
)


def _caller(body: str) -> EndpointCaller:
    transport = AsyncMock()
    transport.max_duration = MagicMock(return_value=0.0)
    transport.request.return_value = RawAPIResponse(
        status_code=401, headers={"content-type": "application/json"}, body=body
    )
    return EndpointCaller(
        transport=transport,
        base_url="https://api.test.com",
        api_key=API_KEY,
        retry_strategy=RetryStrategy(max_retries=0),
    )


@pytest.mark.unit
class TestUnauthorizedResponses:
    @pytest.mark.asyncio
    async def test_invalid_key_flag_raises_auth_failed(self) -> None:
        with pytest.raises(OlostepServerError_AuthFailed):
            await _caller('{"invalid_api_key": true, "message": "Your API key is invalid."}')._invoke(CONTRACT)

    @pytest.mark.asyncio
    async def test_invalid_key_code_raises_auth_failed(self) -> None:
        """Newer endpoints (batches, crawls) send an RFC-style body with code=invalid_api_key."""
        with pytest.raises(OlostepServerError_AuthFailed):
            await _caller('{"object": "error", "code": "invalid_api_key", "status": 401}')._invoke(CONTRACT)

    @pytest.mark.asyncio
    async def test_other_401_raises_blacklisted_domain(self) -> None:
        with pytest.raises(OlostepServerError_BlacklistedDomain):
            await _caller('{"message": "This domain is not allowed."}')._invoke(CONTRACT)


@pytest.mark.unit
class TestAuthFailedMasking:
    def test_message_shows_only_last_four_characters(self) -> None:
        message = str(OlostepServerError_AuthFailed(api_key=API_KEY))
        assert "1234" in message
        assert "olostep_test_key" not in message

    def test_short_key_is_fully_masked(self) -> None:
        message = str(OlostepServerError_AuthFailed(api_key="short"))
        assert "short" not in message
