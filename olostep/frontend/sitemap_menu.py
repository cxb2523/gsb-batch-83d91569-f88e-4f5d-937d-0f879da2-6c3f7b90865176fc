"""
Site mapping operations.
"""

from __future__ import annotations

from .._log import get_logger
from ..backend.api_endpoints import MAP_CREATE
from ..backend.caller import EndpointCaller
from ..frontend.client_state import Sitemap
from ..frontend.input_coersion import coerce_to_list
from ..models.response import MapResponse

logger = get_logger("frontend.map_menu")


class SitemapMenu:
    """Site mapping operations.

    This class provides methods for creating site maps that extract and organize
    links from websites. It supports various filtering options and provides
    smart input coercion for better usability.
    """

    def __init__(self, caller: EndpointCaller, validate_request: bool = True) -> None:
        self._caller = caller
        self._validate_request = validate_request

    async def create(
        self,
        url: str,
        *,
        search_query: str | None = None,
        top_n: int | None = None,
        include_subdomain: bool | None = None,
        include_urls: list[str] | str | None = None,
        exclude_urls: list[str] | str | None = None,
        validate_request: bool | None = None,
    ) -> Sitemap:
        """Create a site map with smart input coercion.

        Creates a new site map that extracts and organizes links from the specified
        URL. Supports various filtering options and provides smart coercion for
        better usability.

        Args:
            url: URL to map (supports bare domains like "example.com").
            search_query: Search query to filter links during extraction.
                Only links matching the query will be included.
            top_n: Maximum number of links to return (must be positive).
                If None, no limit is applied.
            include_subdomain: Whether to include subdomain links in the sitemap.
                If None, uses default behavior.
            include_urls: URL patterns to include (string or list of strings).
                Supports glob patterns like "/blog/**".
            exclude_urls: URL patterns to exclude (string or list of strings).
                Supports glob patterns like "/admin/**".
            validate_request: Override the global validation setting for this request.
                If None, uses the instance's default validation setting.

        Returns:
            Sitemap: A Sitemap object that provides methods for iterating over
                discovered URLs and accessing sitemap metadata.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Basic mapping
            sitemap = await client.sitemap("example.com")

            # With search query
            sitemap = await client.sitemap("example.com", search_query="blog")

            # With filtering
            sitemap = await client.sitemap(
                "example.com",
                search_query="news",
                top_n=10,
                include_urls=["/blog/**"],
                exclude_urls=["/admin/**"]
            )
        """

        # local validation setting overrides global validation setting
        validate_request = (
            self._validate_request if validate_request is None else validate_request
        )

        body_params = {
            "url": url,
            "search_query": search_query,
            "top_n": top_n,
            "include_subdomain": include_subdomain,
            "include_urls": coerce_to_list(include_urls),
            "exclude_urls": coerce_to_list(exclude_urls),
        }

        res: MapResponse = await self._caller.invoke(
            MAP_CREATE, body_params=body_params, validate_request=validate_request
        )

        return Sitemap(self._caller, res, url)

    __call__ = create  # shorthand for create
