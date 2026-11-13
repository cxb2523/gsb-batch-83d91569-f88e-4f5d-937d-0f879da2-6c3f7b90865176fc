"""
Web crawling operations with smart pagination.
"""

from __future__ import annotations

from typing import AsyncIterator

from pydantic import HttpUrl

from .._log import get_logger
from ..backend.api_endpoints import CRAWL_INFO, CRAWL_START
from ..backend.caller import EndpointCaller
from ..frontend.client_state import Crawl, CrawlInfo, CrawlPage
from ..frontend.input_coersion import coerce_to_list
from ..models.response import CrawlInfoResponse, CreateCrawlResponse

logger = get_logger("frontend.crawl_menu")


class CrawlMenu:
    """Web crawling operations with smart pagination.

    This class provides methods for creating and managing web crawling operations
    that can discover and process multiple pages from a starting URL. It supports
    various filtering options, pagination, and provides rich type hints for better IDE support.
    """

    def __init__(self, caller: EndpointCaller, validate_request: bool = True) -> None:
        self._validate_request = validate_request
        self._caller = caller

    async def create(
        self,
        start_url: HttpUrl | str | None = None,
        *,
        url: HttpUrl | str | None = None, # Alias for start_url (univerals naming convention)
        max_pages: int | None = None,
        include_urls: list[str] | str | None = None,
        exclude_urls: list[str] | str | None = None,
        max_depth: int | None = None,
        include_external: bool | None = None,
        include_subdomain: bool | None = None,
        search_query: str | None = None,
        top_n: int | None = None,
        webhook_url: HttpUrl | str | None = None,
        follow_robots_txt: bool = True,
        validate_request: bool | None = None,
    ) -> Crawl:
        """Create a web crawling operation with smart input coercion.

        Creates a new web crawling job that will discover and process pages
        starting from the specified URL. Supports various filtering options
        and provides smart coercion for better usability.

        Args:
            url: URL to start crawling from (supports bare domains like "example.com").
            start_url: Alternative parameter name for url (for documentation compatibility).
                If both url and start_url are provided, ValueError is raised.
            max_pages: Maximum number of pages to crawl (must be positive).
                If None, no limit is applied.
            include_urls: URL patterns to include (string or list of strings).
                Supports glob patterns like "/blog/**".
            exclude_urls: URL patterns to exclude (string or list of strings).
                Supports glob patterns like "/admin/**".
            max_depth: Maximum crawl depth from the starting URL (must be positive).
                If None, no depth limit is applied.
            include_external: Whether to include external links in the crawl.
            include_subdomain: Whether to include subdomain links in the crawl.
            search_query: Search query to filter pages during crawling.
                Only pages matching the query will be processed.
            top_n: Maximum number of results to return (must be positive).
                If None, no limit is applied.
            webhook_url: Webhook URL for receiving notifications about crawl progress.
            follow_robots_txt: Whether to follow robots.txt rules when crawling.
                Defaults to True. Set to False to ignore robots.txt restrictions.
            validate_request: Override the global validation setting for this request.
                If None, uses the instance's default validation setting.

        Returns:
            Crawl: A Crawl object that provides methods for monitoring progress,
                retrieving pages, and waiting for completion.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Basic crawling
            crawl = await client.crawl("example.com", max_pages=10)

            # With URL filtering
            crawl = await client.crawl(
                "example.com",
                max_pages=50,
                include_urls=["/blog/**"],
                exclude_urls=["/admin/**"]
            )

            # With search and limits
            crawl = await client.crawl(
                "example.com",
                search_query="news",
                top_n=20,
                max_depth=3
            )
        """
        # Normalize start_url to url
        if url is not None and start_url is not None:
            raise ValueError("Cannot specify both 'url' and 'start_url' parameters. Use only one.")
        if url is None and start_url is not None:
            url = start_url
        if url is None:
            raise ValueError("Either 'url' or 'start_url' parameter must be provided.")

        body_params = {
            "start_url": url,
            "max_pages": max_pages,
            "include_urls": coerce_to_list(include_urls),
            "exclude_urls": coerce_to_list(exclude_urls),
            "max_depth": max_depth,
            "include_external": include_external,
            "include_subdomain": include_subdomain,
            "search_query": search_query,
            "top_n": top_n,
            "webhook_url": webhook_url,
            "follow_robots_txt": follow_robots_txt,
        }

        # local validation setting overrides global validation setting
        validate_request = (
            self._validate_request if validate_request is None else validate_request
        )

        res: CreateCrawlResponse = await self._caller.invoke(
            CRAWL_START, body_params=body_params, validate_request=validate_request
        )

        return Crawl(self._caller, res)

    __call__ = create

    async def info(self, crawl_id: str) -> CrawlInfo:
        """Get detailed information about a crawl operation.

        Retrieves current status, progress, and metadata for a specific crawl.
        Useful for monitoring crawl progress and checking completion status.

        Args:
            crawl_id: The unique identifier of the crawl to get information for.
                This is returned when creating a crawl with the create() method.

        Returns:
            CrawlInfo: An object containing crawl status, progress metrics,
                and timing information.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Get crawl information
            info = await client.crawl.info("crawl_123")
            print(f"Status: {info.status}")
            print(f"Pages discovered: {info.pages_count}")
        """
        res: CrawlInfoResponse = await self._caller.invoke(
            CRAWL_INFO,
            path_params={"crawl_id": crawl_id},
            validate_request=self._validate_request,
        )
        return CrawlInfo(res)

    async def pages(
        self,
        crawl_id: str,
        *,
        batch_size: int = 50,
        search_query: str | None = None,
        wait_for_completion: bool = True,
    ) -> AsyncIterator[CrawlPage]:
        """Get an async iterator for crawl pages with automatic pagination.

        Returns an async iterator that yields CrawlPage objects for all pages
        discovered during the crawl. Handles pagination automatically and can filter
        by search query. Optionally waits for crawl completion before starting iteration.

        Args:
            crawl_id: The unique identifier of the crawl to get pages for.
                This is returned when creating a crawl with the create() method.
            batch_size: Number of pages to fetch per API request (default: 50).
                Larger values reduce API calls but use more memory.
            search_query: Optional filter to only return pages matching the search query.
                If None, returns all discovered pages.
            wait_for_completion: Whether to wait for the crawl to complete before
                starting iteration (default: True). If False, starts immediately
                and may return partial results.

        Yields:
            CrawlPage: Individual crawl pages with URL, retrieve_id, and external status.
                Each page can be used to retrieve scraped content.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Get all discovered pages
            async for page in client.crawl.pages("crawl_123"):
                result = await page.retrieve()
                print(f"Retrieved: {page.url}")

            # Get pages matching a search query
            async for page in client.crawl.pages("crawl_123", search_query="news"):
                print(f"News page: {page.url}")
        """
        # looks hacky, maybe it is. Reason: Nobody expects to synchronously get an async iterator.
        async for page in Crawl._pages_async_iterator(
            self._caller,
            crawl_id,
            batch_size=batch_size,
            search_query=search_query,
            wait_for_completion=wait_for_completion,
        ):
            yield page
