"""
Data retrieval operations with rich IDE support.
"""

from __future__ import annotations

from .._log import get_logger
from ..backend.api_endpoints import RETRIEVE_GET
from ..backend.caller import EndpointCaller
from ..frontend.client_state import ScrapeResult  # , RetrievableID
from ..frontend.input_coersion import coerce_to_list
from ..models.request import RetrieveFormat
from ..models.response import RetrieveResponse

logger = get_logger("frontend.retrieve_menu")


class RetrieveMenu:
    """Data retrieval operations with rich IDE support.

    This class provides methods for retrieving previously scraped content using
    retrieve IDs. It supports format filtering and provides rich type hints
    for better IDE support.
    """

    def __init__(self, caller: EndpointCaller, validate_request: bool = True) -> None:
        self._validate_request = validate_request
        self._caller = caller

    async def get(
        self,
        retrieve_id: str,
        formats: list[RetrieveFormat] | list[str] | RetrieveFormat | str | None = None,
        validate_request: bool | None = None,
    ) -> ScrapeResult:
        """Retrieve content by ID with rich type hints and smart input coercion.

        Fetches previously scraped content using a retrieve ID. Supports format
        filtering and provides smart coercion for better usability.

        Note: This endpoint has known issues:
        - Bug 1: Invalid IDs (expired, wrong type, etc.) return empty results instead of errors
        - Bug 2: The formats parameter behavior is unpredictable - consider leaving it blank

        Args:
            retrieve_id: The unique identifier of the content to retrieve.
                This is typically obtained from scrape results or batch/crawl items.
            formats: Single format or list of formats to retrieve.
                Can be RetrieveFormat enum values, strings, or mixed lists.
                If None, returns all available formats.
            validate_request: Override the global validation setting for this request.
                If None, uses the instance's default validation setting.

        Returns:
            ScrapeResult: The scraped content in the requested formats.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Retrieve all available formats
            result = await client.retrieve.get("ret_123")

            # Single format (may not work reliably due to API bugs)
            result = await client.retrieve.get("ret_123", RetrieveFormat.HTML)

            # Multiple formats (may not work reliably due to API bugs)
            result = await client.retrieve.get("ret_123", [RetrieveFormat.HTML, RetrieveFormat.MARKDOWN])
        """

        query_params = {
            "retrieve_id": retrieve_id,
            "formats": coerce_to_list(formats),
        }

        # local validation setting overrides global validation setting
        validate_request = (
            self._validate_request if validate_request is None else validate_request
        )

        res: RetrieveResponse = await self._caller.invoke(
            RETRIEVE_GET, query_params=query_params, validate_request=validate_request
        )
        return ScrapeResult(res)

    __call__ = get  # shorthand for get
