"""
Batch processing operations with rich IDE support and elegant pagination.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from .._log import get_logger
from ..backend.api_endpoints import BATCH_INFO, BATCH_START
from ..backend.caller import EndpointCaller
from ..frontend.client_state import Batch, BatchInfo, BatchItemResult
from ..frontend.input_coersion import (
    coerce_country,
    coerce_to_batch_items,
    coerce_to_key_in_dict,
)
from ..models.common import Country
from ..models.request import BatchItem, LinksOnPage, Parser
from ..models.response import BatchCreateResponse, BatchInfoResponse

logger = get_logger("frontend.batch_menu")


class BatchMenu:
    """Batch processing operations with rich IDE support and elegant pagination.

    This class provides methods for creating and managing batch processing operations
    that can handle multiple URLs efficiently. It supports smart input coercion,
    validation, and provides rich type hints for better IDE support.
    """

    def __init__(self, caller: EndpointCaller, validate_request: bool = True) -> None:
        self._caller = caller
        self._validate_request = validate_request

    async def create(
        self,
        urls: list[BatchItem] | list[str] | BatchItem | str | list[dict[str, Any]],
        *,
        country: Country | str | None = None,
        parser: Parser | dict[str, Any] | str | None = None,
        links_on_page: LinksOnPage | dict[str, Any] | None = None,
        validate_request: bool | None = None,
    ) -> Batch:
        """Create new a batch processing operation. Supports rich type hints and smart input coercion.

        Creates a new batch processing job that can handle multiple URLs efficiently.
        Supports various input formats and provides smart coercion for better usability.

        Args:
            urls: Single URL string, list of URLs, or batch items with custom IDs.
                Can be a string, list of strings, BatchItem object, list of BatchItem objects,
                or list of dictionaries matching the BatchItem schema.
            country: Country for geolocation when scraping URLs. Can be a Country enum
                or string representation.
            parser: Parser configuration for content extraction. Can be a Parser object,
                dictionary with parser config, or parser ID string.
            links_on_page: Configuration for extracting links from pages. Can be a
                LinksOnPage object or dictionary with link extraction settings.
            validate_request: Override the global validation setting for this request.
                If None, uses the instance's default validation setting.

        Returns:
            Batch: A Batch object that provides methods for monitoring progress,
                retrieving items, and waiting for completion.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Single URL
            batch = await client.batch("example.com")

            # Multiple URLs
            batch = await client.batch(["example.com", "google.com"])

            # With custom IDs
            batch = await client.batch([
                {"url": "example.com", "custom_id": "news_1"},
                {"url": "google.com", "custom_id": "search_1"}
            ])

            # With country and parser
            batch = await client.batch(
                ["example.com", "google.com"],
                country=Country.US,
                parser="@olostep/google-news"
            )
        """

        body_params = {
            "items": coerce_to_batch_items(urls),
            "country": coerce_country(country),
            "parser": coerce_to_key_in_dict(parser, "id"),
            "links_on_page": links_on_page,
        }

        # local validation setting overrides global validation setting
        validate_request = (
            self._validate_request if validate_request is None else validate_request
        )

        res: BatchCreateResponse = await self._caller.invoke(
            BATCH_START, body_params=body_params, validate_request=validate_request
        )
        return Batch(self._caller, res)

    __call__ = create

    async def info(self, batch_id: str) -> BatchInfo:
        """Get detailed information about a batch processing operation.

        Retrieves current status, progress, and metadata for a specific batch.
        Useful for monitoring batch progress and checking completion status.

        Args:
            batch_id: The unique identifier of the batch to get information for.
                This is returned when creating a batch with the create() method.

        Returns:
            BatchInfo: An object containing batch status, progress metrics,
                and timing information.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Get batch information
            info = await client.batch.info("batch_123")
            print(f"Status: {info.status}")
            print(f"Progress: {info.completed_urls}/{info.total_urls}")
        """

        path_params = {"batch_id": batch_id}

        res: BatchInfoResponse = await self._caller.invoke(
            BATCH_INFO, path_params=path_params, validate_request=self._validate_request
        )

        return BatchInfo(res)

    async def items(
        self,
        batch_id: str,
        *,
        batch_size: int = 50,
        status: str | None = None,
        wait_for_completion: bool = True,
    ) -> AsyncIterator[BatchItemResult]:
        """Get an async iterator for batch items with automatic pagination.

        Returns an async iterator that yields BatchItemResult objects for all items
        in the specified batch. Handles pagination automatically and can filter
        by status. Optionally waits for batch completion before starting iteration.

        Args:
            batch_id: The unique identifier of the batch to get items for.
                This is returned when creating a batch with the create() method.
            batch_size: Number of items to fetch per API request (default: 50).
                Larger values reduce API calls but use more memory.
            status: Optional filter to only return items with specific status.
                Common values: "completed", "failed", "pending", "in_progress".
            wait_for_completion: Whether to wait for the batch to complete before
                starting iteration (default: True). If False, starts immediately
                and may return partial results.

        Yields:
            BatchItemResult: Individual batch items with URL, retrieve_id, and custom_id.
                Each item can be used to retrieve scraped content.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Get all completed items
            async for item in client.batch.items(batch_123):
                result = await item.retrieve()
                print(f"Retrieved: {item.url}")

            # Get items without waiting for completion
            async for item in client.batch.items(batch_123, wait_for_completion=False):
                print(f"Item: {item.url} - {item.retrieve_id}")
        """
        async for item in Batch._items_async_iterator(
            self._caller,
            batch_id,
            batch_size=batch_size,
            status=status,
            wait_for_completion=wait_for_completion,
        ):
            yield item
