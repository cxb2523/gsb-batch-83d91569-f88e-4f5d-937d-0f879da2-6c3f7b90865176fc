from __future__ import annotations

from ..backend.caller import EndpointCaller
from ..backend.transport import HttpxTransport
from ..backend.transport_protocol import Transport
from ..config import API_KEY_ENV, BASE_API_URL
from ..frontend.answers_menu import AnswersMenu
from ..frontend.batch_menu import BatchMenu
from ..frontend.crawl_menu import CrawlMenu
from ..frontend.monitor_menu import MonitorMenu
from ..frontend.retrieve_menu import RetrieveMenu
from ..frontend.scrape_menu import ScrapeMenu
from ..frontend.searches_menu import SearchesMenu
from ..frontend.sitemap_menu import SitemapMenu
from ..retry_strategy import RetryStrategy


class AsyncOlostep:
    """
    Default async client that wires the transport, caller, and namespaced frontend.
    This is the main client for the Olostep SDK.

    The client supports two usage patterns:

    1. **Context Manager (Recommended for one-off usage):**
       Automatically handles resource cleanup when exiting the context.

       ```python
       async with AsyncOlostep(api_key="your-api-key") as client:
           result = await client.scrape.url(
               url_to_scrape="https://example.com",
               formats=["html", "markdown"]
           )
       # Transport is automatically closed here
       ```

    2. **Explicit Close (For long-lived services):**
       Requires manual resource cleanup using the close() method.

       ```python
       client = AsyncOlostep(api_key="your-api-key")
       try:
           result = await client.scrape.url(
               url_to_scrape="https://example.com",
               formats=["html", "markdown"]
           )
       finally:
           await client.close()  # Manually close the transport
       ```

    For most use cases, prefer the context manager pattern as it ensures
    proper resource cleanup and is less error-prone.
    """

    def __init__(
        self,
        api_key: str | None = None,
        retry_strategy: RetryStrategy | None = None,
        *,
        _base_url: str | None = None,
        _transport: Transport | None = None,
        _caller: EndpointCaller | None = None,
    ) -> None:
        """Initialize the async Olostep client.

        Args:
            api_key: Your Olostep API key. If not provided, reads from OLOSTEP_API_KEY env var.
            retry_strategy: Retry configuration for API calls. If not provided, uses sensible defaults.
            _base_url: Override the base API URL (for internal testing only).
            _transport: Custom transport layer (internal use only, not documented).
            _caller: Custom caller (internal use only, not documented).
        """
        self._api_key: str = (api_key or API_KEY_ENV or "").strip()
        self._base_url: str = (_base_url or BASE_API_URL).rstrip("/")
        self._retry_strategy = retry_strategy or RetryStrategy()

        # Validate API key for real transport
        if _transport is None and _caller is None and not self._api_key:
            raise ValueError("API key is required when using the real HTTP transport")

        # Use custom caller if provided (for testing)
        if _caller is not None:
            self._caller = _caller
        else:
            # Use custom transport or create default
            self._transport: Transport = _transport or HttpxTransport(self._api_key)
            self._caller = EndpointCaller(
                self._transport, self._base_url, self._api_key, self._retry_strategy
            )

        # Menu items (plural naming convention)
        self.scrapes = ScrapeMenu(self._caller)
        self.batches = BatchMenu(self._caller)
        self.crawls = CrawlMenu(self._caller)
        self.maps = SitemapMenu(self._caller)
        self.answers = AnswersMenu(self._caller)
        self.searches = SearchesMenu(self._caller)
        self.retrieve = RetrieveMenu(self._caller)
        self.monitors = MonitorMenu(self._caller)

    async def __aenter__(self) -> "AsyncOlostep":
        return self

    async def close(self) -> None:
        """
        Close the underlying transport connection.

        This method closes the HTTP transport and releases associated resources.
        Only needed if not using the client as an async context manager.

        For one-off usage, prefer the context manager pattern:

            async with AsyncOlostep(api_key="...") as client:
                result = await client.scrape.url("https://example.com")

        For long-lived services, use explicit close:

            client = AsyncOlostep(api_key="...")
            try:
                result = await client.scrape.url("https://example.com")
            finally:
                await client.close()
        """
        await self._transport.close()

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        await self.close()
