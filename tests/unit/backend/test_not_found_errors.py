"""
How the caller maps 404 responses: an unknown route vs a missing resource.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from olostep.backend.api_endpoints import EndpointContract
from olostep.backend.caller import EndpointCaller
from olostep.backend.transport_protocol import RawAPIResponse
from olostep.errors import (
    OlostepServerError_InvalidEndpointCalled,
    OlostepServerError_ResourceNotFound,
)
from olostep.retry_strategy import RetryStrategy


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
        status_code=404, headers={"content-type": "application/json"}, body=body
    )
    return EndpointCaller(
        transport=transport,
        base_url="https://api.test.com",
        api_key="olostep_test_key",
        retry_strategy=RetryStrategy(max_retries=0),
    )


@pytest.mark.unit
class TestNotFoundResponses:
    @pytest.mark.asyncio
    async def test_unknown_route_raises_invalid_endpoint(self) -> None:
        body = '{"object": "error", "code": "not_found", "status": 404, "title": "route not found", "metadata": {}}'
        with pytest.raises(OlostepServerError_InvalidEndpointCalled):
            await _caller(body)._invoke(CONTRACT)

    @pytest.mark.asyncio
    async def test_missing_resource_raises_resource_not_found(self) -> None:
        body = (
            '{"object": "error", "code": "not_found", "status": 404, "title": "batch not found", '
            '"metadata": {"resource": "batch", "id": "batch_1"}}'
        )
        with pytest.raises(OlostepServerError_ResourceNotFound):
            await _caller(body)._invoke(CONTRACT)

    @pytest.mark.asyncio
    async def test_older_not_found_body_raises_resource_not_found(self) -> None:
        with pytest.raises(OlostepServerError_ResourceNotFound):
            await _caller('{"error_code": "not_found", "error_message": "Crawl not found"}')._invoke(CONTRACT)
