"""Transport protocol definition for the Olostep SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

__all__ = ["Transport", "RawAPIRequest", "RawAPIResponse"]


@dataclass
class RawAPIRequest:
    """Raw API request containing method, url, query, json, and headers."""

    method: str
    url: str
    query: dict[str, Any] | None = None
    json: dict[str, Any] | None = None
    headers: dict[str, str] | None = None


@dataclass
class RawAPIResponse:
    """Raw API response containing status code, headers, and response text."""

    status_code: int
    headers: dict[str, str]
    body: str


class Transport(Protocol):
    """Protocol defining the interface for HTTP transport implementations."""

    async def request(
        self,
        request: RawAPIRequest,
    ) -> RawAPIResponse:
        """
        Make an HTTP request.

        Args:
            request: RawAPIRequest object containing method, url, json, query, and headers

        Returns:
            RawAPIResponse containing status_code, headers, and response_text
        """
        ...

    async def close(self) -> None:
        """
        Close any resources used by the transport.

        This method should be implemented by all transport implementations
        to ensure proper cleanup of connections, sessions, or other resources.
        """
        ...
