"""
Searches operations with rich IDE support and smart input coercion.
"""

from __future__ import annotations

from typing import Any

from .._log import get_logger
from ..backend.api_endpoints import SEARCHES_CREATE
from ..backend.caller import EndpointCaller
from ..frontend.client_state import SearchesResult
from ..models.response import SearchesResponse

logger = get_logger("frontend.searches_menu")


class SearchesMenu:
    """Web search operations with rich IDE support.

    This class provides methods for searching the web with natural language
    queries and optionally embedding scraped content for each returned link.
    """

    def __init__(self, caller: EndpointCaller, validate_request: bool = True) -> None:
        self._caller = caller
        self._validate_request = validate_request

    async def create(
        self,
        query: str,
        *,
        limit: int | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        scrape_options: dict[str, Any] | None = None,
        validate_request: bool | None = None,
    ) -> SearchesResult:
        """Search the web with a natural language query.

        Sends a query in plain English and gets back a deduplicated list of
        relevant links with titles and descriptions. Optionally scrapes every
        returned URL in one round-trip and embeds `markdown_content` /
        `html_content` directly into each link.

        Args:
            query: The search query in natural language (e.g., "Best AEO startups").
            limit: Maximum number of links to return after deduplication.
                Must be between 1 and 25. Defaults to 12 server-side.
            include_domains: Restrict results to these domains. Bare hosts only.
            exclude_domains: Exclude results from these domains. Bare hosts only.
            scrape_options: When provided, every returned link is also scraped
                and its content embedded in the response. Supported keys:

                - ``formats``: list[str] - subset of ``["html", "markdown"]``
                - ``remove_css_selectors``: str - "default", "none", or a
                  JSON-stringified list of selectors
                - ``timeout``: int - 1 to 60 seconds; bounds the entire scrape
                  phase, not each individual link

            validate_request: Override the global validation setting for this request.

        Returns:
            SearchesResult: Search id, query, list of links, credits consumed.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Basic search
            result = await client.searches.create("Best AEO startups")
            print(f"{len(result.links)} links")

            # Search with domain filtering and inline scraping
            result = await client.searches.create(
                query="OpenAI Sora shutdown analysis",
                limit=5,
                include_domains=["bbc.com", "nytimes.com"],
                exclude_domains=["pinterest.com"],
                scrape_options={"formats": ["markdown"], "timeout": 25},
            )
            for link in result.links:
                print(link["url"], len(link.get("markdown_content") or ""))
        """
        body_params: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "include_domains": include_domains,
            "exclude_domains": exclude_domains,
            "scrape_options": scrape_options,
        }

        validate_request = (
            self._validate_request if validate_request is None else validate_request
        )

        res: SearchesResponse = await self._caller.invoke(
            SEARCHES_CREATE,
            body_params=body_params,
            validate_request=validate_request,
        )

        return SearchesResult(res)

    __call__ = create  # shorthand for create

    async def get(self, search_id: str) -> SearchesResult:
        """Get an existing search result by ID.

        Returns whatever was persisted at search time, including any scraped
        content. This is a pure idempotent read - no re-scraping, no re-billing.

        Args:
            search_id: The unique identifier of the search to retrieve.

        Returns:
            SearchesResult: The search content and metadata.

        Examples:
            result = await client.searches.get("search_9bi0sbj9xa")
            print(result.query, len(result.links))
        """
        from ..backend.api_endpoints import SEARCHES_GET

        path_params = {"search_id": search_id}
        res: SearchesResponse = await self._caller.invoke(
            SEARCHES_GET,
            path_params=path_params,
            validate_request=self._validate_request,
        )
        return SearchesResult(res)
