"""
Test fixtures and configuration for Olostep SDK tests.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Generator

import pytest
import pytest_asyncio

from olostep._log import _enable_file_logging, _enable_stderr_debug
from olostep.backend.api_endpoints import EndpointContract
from olostep.backend.caller import EndpointCaller
from olostep.backend.transport_protocol import RawAPIRequest
from olostep.clients.async_client import AsyncOlostep
from olostep.clients.sync_client import Olostep
from olostep.errors import (
    OlostepServerError_NoResultInResponse,
    OlostepServerError_RequestUnprocessable,
)
from tests.stubs.fake_transport import FakeTransportSmart
from tests.stubs.test_server import StubServer, cleanup_test_server, get_test_server

_enable_stderr_debug()
_enable_file_logging()

def pytest_configure(config):
    """Configure pytest markers for test categorization."""
    config.addinivalue_line(
        "markers", "api: marks tests that require API calls (deselect with '-m \"not api\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks integration tests that test multiple components together"
    )
    config.addinivalue_line(
        "markers", "unit: marks unit tests that test individual components in isolation"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests that take a long time to run"
    )
    config.addinivalue_line(
        "markers", "contracts: marks API contract tests that validate API behavior"
    )


@pytest.fixture(scope="session")
def test_server() -> Generator[StubServer, None, None]:
    """High-quality test server fixture that starts once per test session."""
    server = get_test_server()
    yield server
    # Cleanup is handled by pytest session teardown


@pytest.fixture(autouse=True, scope="session")
def cleanup_test_server_session():
    """Ensure test server is cleaned up after all tests."""
    yield
    cleanup_test_server()


@pytest.fixture
def hacker_news_urls(request) -> Generator[list[str], None, None]:
    """Generate N random Hacker News article URLs for testing.
    
    Usage: @pytest.mark.parametrize("hacker_news_urls", [5], indirect=True)
    """
    n = getattr(request, 'param', 5)  # Default to 5 URLs
    article_ids = random.sample(range(20000000, 25000001), n)
    urls = [f"https://news.ycombinator.com/item?id={article_id}" for article_id in article_ids]
    yield urls


@pytest.fixture
def fake_transport() -> FakeTransportSmart:
    """Create a fake transport for testing."""
    return FakeTransportSmart()


@pytest.fixture
def real_api_key() -> str:
    """Get real API key from environment for contract testing."""
    import os
    api_key = os.getenv("OLOSTEP_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OLOSTEP_API_KEY environment variable is not set. "
            "Please set it to a valid test API key before running contract tests."
        )
    return api_key


# Fake transport clients
@pytest.fixture
def async_client_fake(fake_transport: FakeTransportSmart) -> AsyncOlostep:
    """Create an async AsyncOlostep with fake transport."""
    return AsyncOlostep(_transport=fake_transport)


@pytest.fixture
def sync_client_fake(fake_transport: FakeTransportSmart) -> Olostep:
    """Create a sync Olostep with fake transport."""
    return Olostep(_transport=fake_transport)


# Real transport clients
@pytest.fixture
def async_client_real(real_api_key: str) -> AsyncOlostep:
    """Create an async AsyncOlostep with real transport."""
    return AsyncOlostep(api_key=real_api_key)


@pytest.fixture
def sync_client_real(real_api_key: str) -> Olostep:
    """Create a sync Olostep with real transport."""
    return Olostep(api_key=real_api_key)


# Transport fixtures for API contract testing
@pytest_asyncio.fixture
async def transport_with_real_key(real_api_key: str):
    """Create httpx transport with real API key and logging enabled."""
    from olostep.backend.transport import HttpxTransport
    
    transport = HttpxTransport(real_api_key)
    
    try:
        yield transport
    finally:
        await transport.close()

@pytest_asyncio.fixture
async def transport_with_fake_key():
    """Create httpx transport with fake API key and logging enabled."""
    from olostep.backend.transport import HttpxTransport
    
    fake_key = "fake_api_key_12345"
    transport = HttpxTransport(fake_key)
    
    try:
        yield transport
    finally:
        await transport.close()


# =============================================================================
# COMMON TEST UTILITIES
# =============================================================================

def extract_request_parameters(request_model) -> dict[str, list[str]]:
    """Extract all parameter names from a request model (path, query, body).
    
    Args:
        request_model: The request model class
        
    Returns:
        Dictionary with 'path', 'query', 'body' keys containing parameter lists
    """
    params = {'path': [], 'query': [], 'body': []}
    
    if hasattr(request_model, 'model_fields'):
        for field_name, field_info in request_model.model_fields.items():
            if field_name == 'path_params' and hasattr(field_info.annotation, 'model_fields'):
                params['path'] = list(field_info.annotation.model_fields.keys())
            elif field_name == 'query_params' and hasattr(field_info.annotation, 'model_fields'):
                params['query'] = list(field_info.annotation.model_fields.keys())
            elif field_name == 'body_params' and hasattr(field_info.annotation, 'model_fields'):
                params['body'] = list(field_info.annotation.model_fields.keys())
    
    return params


async def retry_request(
    endpoint_caller: EndpointCaller,
    request: RawAPIRequest,
    contract: EndpointContract,
    max_retries: int = 3
) -> Any:
    """
    Retry request with exponential backoff for transient errors.
    
    We usually don't catch this error as it's unclear if the api bugged or if this was an invalid request.
    But here we know the request is valid, so we can retry to make the tests run smoother.    
    """

    
    for attempt in range(max_retries + 1):  # +1 for initial attempt
        try:
            response = await endpoint_caller._transport.request(request)
            model = endpoint_caller._handle_response(request, response, contract)
            return model
        except (OlostepServerError_NoResultInResponse, OlostepServerError_RequestUnprocessable) as e:
            if attempt < max_retries:
                # Exponential backoff: 1s, 2s, 4s
                wait_time = 2 ** attempt
                await asyncio.sleep(wait_time)
                continue
            else:
                # All retries exhausted, re-raise the exception
                raise e


# =============================================================================
# COMMON ENDPOINT CALLER FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def endpoint_caller(transport_with_real_key, real_api_key):
    """Create EndpointCaller instance for testing."""
    from olostep.backend.caller import EndpointCaller
    from olostep.retry_strategy import RetryStrategy
    
    return EndpointCaller(
        transport=transport_with_real_key,
        base_url="https://api.olostep.com/v1",
        api_key=real_api_key,
        retry_strategy=RetryStrategy(max_retries=1)
    )


@pytest_asyncio.fixture
async def caller_with_fake_key(transport_with_fake_key):
    """Create EndpointCaller with fake API key for testing."""
    from olostep.backend.caller import EndpointCaller
    from olostep.retry_strategy import RetryStrategy
    
    fake_key = "fake_api_key_12345"
    return EndpointCaller(
        transport=transport_with_fake_key,
        base_url="https://api.olostep.com/v1",
        api_key=fake_key,
        retry_strategy=RetryStrategy(max_retries=1)
    )


