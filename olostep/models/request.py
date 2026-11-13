from __future__ import annotations

import json
import warnings
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import (
    HttpUrl,
    StrictBool,
    field_validator,
    model_serializer,
    model_validator,
)

# =============================================================================
# REQUEST MODELS
# =============================================================================
from .base import OlostepBaseModel
from .common import Country

if TYPE_CHECKING:
    from olostep.backend.api_endpoints import EndpointContract
else:
    EndpointContract = Any


# =============================================================================
# =============================================================================
# BASE REQUEST MODELS
# =============================================================================
# =============================================================================


class PathParams(OlostepBaseModel):
    """Base class for path parameters (e.g., {scrape_id}, {batch_id})."""

    pass


class QueryParams(OlostepBaseModel):
    """Base class for query parameters (e.g., ?retrieve_id=123&formats=html)."""

    pass


class BodyParams(OlostepBaseModel):
    """Base class for request body parameters (POST/PUT/PATCH only)."""

    pass


class BaseRequestModel(OlostepBaseModel):
    """Base class for all request models with separate parameter types."""

    pass

    path_params: PathParams | None = None
    query_params: QueryParams | None = None
    body_params: BodyParams | None = None

    def get_path_params(self) -> dict[str, Any]:
        """Extract path parameters as dict."""
        return (
            self.path_params.model_dump(exclude_none=True, exclude_unset=True)
            if self.path_params
            else {}
        )

    def get_query_params(self) -> dict[str, Any]:
        """Extract query parameters as dict."""
        return (
            self.query_params.model_dump(exclude_none=True, exclude_unset=True)
            if self.query_params
            else {}
        )

    def get_body_params(self) -> dict[str, Any]:
        """Extract body parameters as dict."""
        return (
            self.body_params.model_dump(exclude_none=True, exclude_unset=True)
            if self.body_params
            else {}
        )

    def model_dump(self, **kwargs) -> dict[str, Any]:
        # Explicitly dump submodels for path_params, query_params, and body_params
        data: dict[str, Any] = {}
        if self.path_params is not None:
            data["path_params"] = self.path_params.model_dump(**kwargs)
        if self.query_params is not None:
            data["query_params"] = self.query_params.model_dump(**kwargs)
        if self.body_params is not None:
            data["body_params"] = self.body_params.model_dump(**kwargs)
        return data


# =============================================================================
# MODEL FOR UNVALIDATED REQUESTS
# =============================================================================
class RawRequest:
    """Holds request parameters without validation for skip-validation mode.
    Is not a Pydantic model because it is not validated and we want raw behavior."""

    def __init__(
        self,
        path_params: dict[str, Any] | None,
        query_params: dict[str, Any] | None,
        body_params: dict[str, Any] | None,
    ) -> None:
        self.path_params = path_params or {}
        self.query_params = query_params or {}
        self.body_params = body_params or {}

    def get_path_params(self) -> dict[str, Any]:
        return self.path_params

    def get_query_params(self) -> dict[str, Any]:
        return self.query_params

    def get_body_params(self) -> dict[str, Any]:
        return self.body_params


# =============================================================================
# BASIC METHODS
# =============================================================================

# not used, exists in the caller now.
# def validate_request(
#     contract: EndpointContract,
#     *,
#     path_params: dict[str, Any] | None = None,
#     query_params: dict[str, Any] | None = None,
#     body_params: dict[str, Any] | None = None
# ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
#     """
#     Validate request parameters and return validated path, query, and body params.
#     """
#     path_params = path_params or {}
#     query_params = query_params or {}


#     # If no request model is defined (e.g., for GET requests), skip validation
#     if contract.request_model is None:
#         validated_path = path_params
#         validated_query = query_params
#         validated_body = body_params if contract.method != "GET" else None
#     else:
#         try:
#             # Create the request model with all parameters
#             request_data = {}

#             if path_params:
#                 request_data['path_params'] = path_params

#             if query_params:
#                 request_data['query_params'] = query_params

#             if body_params:
#                 request_data['body_params'] = body_params

#             # Validate the complete request
#             req = contract.request_model(**request_data)

#             # Extract validated parameters
#             validated_path = req.get_path_params()
#             validated_query = req.get_query_params()
#             validated_body = req.get_body_params() if contract.method != "GET" else None

#         except ValidationError as e:
#             raise OlostepRequestValidationError(e.errors()) from e

#     return validated_path, validated_query, validated_body


# =============================================================================
# =============================================================================
# COMMON SUB MODELS
# =============================================================================
# =============================================================================


class Format(str, Enum):
    """Output formats for scraping."""

    HTML = "html"
    MARKDOWN = "markdown"
    TEXT = "text"
    JSON = "json"
    SCREENSHOT = "screenshot"  # not officially supported yet

    def __str__(self) -> str:
        return self.value


# =============================================================================
# =============================================================================
# SCRAPES API MODELS
# =============================================================================
# =============================================================================


# =============================================================================
# SCRAPES CREATE MODELS
# =============================================================================

# Suppress the schema field shadowing warning
warnings.filterwarnings(
    "ignore",
    message='Field name "schema" in "LLMExtract" shadows an attribute in parent "OlostepBaseModel"',
)


class ActionType(OlostepBaseModel):
    type: Literal["wait"] | Literal["click"] | Literal["fill_input"] | Literal["scroll"]


class WaitAction(ActionType):
    """Wait action configuration."""

    type: Literal["wait"] = "wait"
    milliseconds: int

    @field_validator("milliseconds")
    @classmethod
    def validate_milliseconds(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Milliseconds must be non-negative")
        return v


class ClickAction(ActionType):
    """Click action configuration."""

    type: Literal["click"] = "click"
    selector: str


class FillInputAction(ActionType):
    """Fill input action configuration."""

    type: Literal["fill_input"] = "fill_input"
    selector: str
    value: str


class ScrollDirection(str, Enum):
    """Scroll directions."""

    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"

    def __str__(self) -> str:
        return self.value


class ScrollAction(ActionType):
    """Scroll action configuration."""

    type: Literal["scroll"] = "scroll"
    direction: ScrollDirection
    amount: int


# class ActionType(str, Enum):
#     """Types of actions that can be performed on a page."""
#     WAIT = "wait"
#     CLICK = "click"
#     FILL_INPUT = "fill_input"
#     SCROLL = "scroll"


# Action classes are now imported from ..types

# Union type for all actions - use WaitAction | ClickAction | FillInputAction | ScrollAction directly

# class ParserType(str, Enum):
#     """Available parser types for Olostep search API."""
#     GOOGLE_SHORTS = "google-shorts"
#     GOOGLE_VIDEOS = "google-videos"
#     GOOGLE_SHOPPING = "google-shopping"
#     GOOGLE_NEWS = "google-news"
#     GOOGLE_MAPS = "google-maps"
#     GOOGLE_AI_OVERVIEW = "google-ai-overview"
#     GOOGLE_ADVANCED_SEARCH = "google-advanced-search"
#     GOOGLE_SEARCH = "google-search"

#     # Predefined parsers for Olostep structured scraping
#     AMAZON_IT_PRODUCT = "amazon-it-product"

#     # Reserved parsers (may require contact)
#     LINKEDIN_PROFILE = "linkedin-profile"
#     TIKTOK_DATA = "tiktok-data"

#     def __str__(self) -> str:
#         return self.value


Transformer = Literal["postlight"] | None


class Parser(OlostepBaseModel):
    """Parser configuration."""

    id: str | None = None
    # config: dict[str, Any] | None = None


class LLMExtract(OlostepBaseModel):
    """LLM extraction configuration.

    `schema` must be a JSON Schema object at the top level, e.g.
    {"type": "object", "properties": {"title": {"type": "string"}}}.
    """

    schema: dict[str, Any]


class LinksOnPage(OlostepBaseModel):
    """
    Configuration for extracting links from a scraped page.

    With this option, you can get all the links present on the page you scrape.
    """

    absolute_links: bool = True
    query_to_order_links_by: str | None = None
    include_links: list[str] | None = None
    exclude_links: list[str] | None = None


class ScreenSize(OlostepBaseModel):
    """Browser viewport configuration for screenshots.

    Supports both preset screen types and custom dimensions:
    - desktop: 1920x1080 pixels
    - mobile: 414x896 pixels
    - tablet: 768x1024 pixels
    - or pass in screen_width and screen_height
    """

    screen_type: Literal["desktop", "mobile", "default"] | None = None
    screen_width: int | None = None
    screen_height: int | None = None

    @model_validator(mode="after")
    @classmethod
    def validate_screen_config(cls, values: "ScreenSize") -> "ScreenSize":
        screen_type = values.screen_type
        screen_width = values.screen_width
        screen_height = values.screen_height

        if screen_type is not None:
            if screen_width is not None or screen_height is not None:
                raise ValueError(
                    "Specify either 'screen_type' or both 'screen_width' and 'screen_height', not both."
                )

        else:  # screen_type is None
            if screen_width is not None or screen_height is not None:
                if screen_width is None or screen_height is None:
                    raise ValueError(
                        "Both 'screen_width' and 'screen_height' must be set if specifying custom dimensions."
                    )
                if screen_width <= 0 or screen_height <= 0:
                    raise ValueError(
                        "'screen_width' and 'screen_height' must be positive"
                    )
            else:
                raise ValueError(
                    "You must specify either 'screen_type' or both 'screen_width' and 'screen_height'."
                )

        # else:
        #     if screen_width is not None or screen_height is not None:
        #         if screen_width is None or screen_height is None:
        #             raise ValueError("Both 'screen_width' and 'screen_height' must be set if specifying custom dimensions.")
        #         if screen_width <= 0 or screen_height <= 0:
        #             raise ValueError("'screen_width' and 'screen_height' must be positive")
        #     else:
        #         raise ValueError("You must specify either 'screen_type' or both 'screen_width' and 'screen_height'.")
        return values


class ScrapeStorage(OlostepBaseModel):
    """Storage retention configuration for a scrape.

    Controls how long Olostep retains the scraped content on S3.
    Defaults to ``"7d"`` when omitted.
    """

    expires_in: str
    """Retention duration. One of: ``"7d"``, ``"10d"``, ``"30d"``, ``"60d"``,
    ``"90d"``, ``"180d"``, ``"365d"``, ``"never"``."""

    @field_validator("expires_in")
    @classmethod
    def validate_expires_in(cls, v: str) -> str:
        allowed = {"7d", "10d", "30d", "60d", "90d", "180d", "365d", "never"}
        if v not in allowed:
            raise ValueError(
                f"Invalid storage.expires_in '{v}'. "
                f"Allowed values: {', '.join(sorted(allowed))}."
            )
        return v


class ScrapeUrlBodyParams(BodyParams):
    """Body parameters for POST /scrapes."""

    url_to_scrape: HttpUrl
    wait_before_scraping: int | None = None
    formats: list[Format] | None = None
    remove_css_selectors: str | None = None
    actions: list[WaitAction | ClickAction | FillInputAction | ScrollAction] | None = (
        None
    )
    country: Country | None = None
    transformer: Transformer | None = None
    remove_images: bool | None = None
    remove_class_names: list[str] | None = None
    parser: Parser | None = None
    llm_extract: LLMExtract | None = None
    links_on_page: LinksOnPage | None = None
    screen_size: ScreenSize | None = None
    storage: ScrapeStorage | None = None
    """Optional storage retention config. Omit to use the default (7 days)."""
    metadata: dict[str, Any] | None = (
        None  # Docs mention that this is not yet supported
    )

    @field_validator("wait_before_scraping")
    @classmethod
    def validate_wait_before_scraping(cls, v):
        if v is not None and v < 0:
            raise ValueError("wait_before_scraping must be non-negative")
        return v

    @field_validator("remove_css_selectors")
    @classmethod
    def validate_remove_css_selectors(cls, v: str | None) -> str | None:
        if v is None:
            return v

        if v in ["default", "none"]:
            return v

        # For any other string, validate it's a valid JSON array of strings
        try:
            parsed = json.loads(v)
            if not isinstance(parsed, list):
                raise ValueError("Must be a JSON array")
            if not all(isinstance(item, str) for item in parsed):
                raise ValueError("Array must contain only strings")
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(
                f"Must be 'default', 'none', or a valid JSON array of strings: {e}"
            ) from e

        return v

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Custom serialization to handle special fields."""
        data = super().model_dump(**kwargs)

        # Convert HttpUrl to string
        if "url_to_scrape" in data and isinstance(self.url_to_scrape, HttpUrl):
            data["url_to_scrape"] = str(self.url_to_scrape)

        # Handle ParserConfig serialization
        if "parser" in data and isinstance(self.parser, Parser):
            parser_data = self.parser.model_dump()
            if parser_data:  # Only include if not empty
                data["parser"] = parser_data
            else:
                del data["parser"]  # Remove if empty

        return data


class ScrapeUrlRequest(BaseRequestModel):
    """Request for POST /scrapes."""

    body_params: ScrapeUrlBodyParams


# =============================================================================
# SCRAPES GET MODELS
# =============================================================================


class ScrapeGetPathParams(PathParams):
    """Path parameters for GET /scrapes/{scrape_id}."""

    scrape_id: str


class ScrapeGetRequest(BaseRequestModel):
    """Request for GET /scrapes/{scrape_id}."""

    path_params: ScrapeGetPathParams


# =============================================================================
# =============================================================================
# BATCHES API MODELS
# =============================================================================
# =============================================================================


# =============================================================================
# BATCHES CREATE MODELS
# =============================================================================


class BatchItem(OlostepBaseModel):
    """Individual item in a batch.

    NOTE: This class serves as a Pydantic validation model for API requests.
    There is a separate frontend wrapper class called BatchItemResult in
    olostep.frontend.client_state that handles API responses. The naming was
    separated to avoid conflicts between the request model (BatchItem) and
    the response wrapper (BatchItemResult).
    """

    url: HttpUrl
    custom_id: str | None = None

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Custom serialization to convert HttpUrl to string."""
        data = super().model_dump(**kwargs)
        if "url" in data and hasattr(self.url, "__str__"):
            data["url"] = str(self.url)
        return data


class BatchStartBodyParams(BodyParams):
    """Body parameters for POST /batches."""

    items: list[BatchItem]
    country: Country | None = None
    parser: Parser | None = None
    links_on_page: LinksOnPage | None = None

    @field_validator("items")
    @classmethod
    def items_must_not_be_empty(cls, v: list[BatchItem]) -> list[BatchItem]:
        if not v:
            raise ValueError("items must not be empty")
        return v

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Custom serialization to handle special fields."""
        kwargs["exclude_none"] = True
        data = super().model_dump(**kwargs)

        # Handle items serialization - convert each item to dict
        if "items" in data and isinstance(self.items, list):
            data["items"] = [item.model_dump() for item in self.items]

        # Handle ParserConfig serialization
        if "parser" in data and isinstance(self.parser, Parser):
            data["parser"] = self.parser.model_dump()
        return data


class BatchStartRequest(BaseRequestModel):
    """Request for POST /batches."""

    body_params: BatchStartBodyParams


# =============================================================================
# BATCHES INFO MODELS
# =============================================================================


class BatchInfoPathParams(PathParams):
    """Path parameters for GET /batches/{batch_id}."""

    batch_id: str


class BatchInfoRequest(BaseRequestModel):
    """Request for GET /batches/{batch_id}."""

    path_params: BatchInfoPathParams


# =============================================================================
# BATCHES ITEMS MODELS
# =============================================================================


class BatchItemsPathParams(PathParams):
    """Path parameters for GET /batches/{batch_id}/items."""

    batch_id: str


class BatchItemsQueryStatus(str, Enum):
    """Common status values."""

    FAILED = "failed"
    COMPLETED = "completed"
    # IN_PROGRESS = "in_progress" # not used for filtering batch items

    def __str__(self) -> str:
        return self.value


class BatchItemsQueryParams(QueryParams):
    """
    Query parameters for GET /batches/{batch_id}/items.

    Pagination Behavior:
    ===================

    The Olostep API uses a cursor-based pagination system with the following rules:

    1. **First Request**: Send only `limit` parameter (no cursor)
       - Example: `?limit=10`
       - API returns first batch of items + cursor token

    2. **Subsequent Requests**: Send only `cursor` parameter (no limit)
       - Example: `?cursor=1758303369342`
       - API remembers the limit from the first request
       - Returns next batch of items + new cursor token

    3. **Pagination Complete**: When cursor is null/None
       - No more items available
       - Stop pagination

    **Important**: Never send both `cursor` and `limit` in the same request.
    The API will ignore the limit if cursor is provided, which can lead to
    unexpected pagination behavior.
    """

    status: BatchItemsQueryStatus | None = None
    cursor: int | None = None
    limit: int | None = None

    @field_validator("cursor")
    @classmethod
    def cursor_must_be_positive(cls, v: int | None) -> int | None:
        """Validate that cursor is a positive integer if provided."""
        if v is not None and v < 0:
            raise ValueError("cursor must be a positive integer")
        return v

    @field_validator("limit")
    @classmethod
    def limit_must_be_positive(cls, v: int | None) -> int | None:
        """Validate that limit is a positive integer if provided."""
        if v is not None and v <= 0:
            raise ValueError("limit must be a positive integer")
        return v

    @model_validator(mode="after")
    def cursor_and_limit_mutually_exclusive(self) -> "BatchItemsQueryParams":
        """
        Enforce that cursor and limit cannot be sent together.

        This prevents confusion about pagination behavior and ensures
        the API's cursor-based pagination works correctly.
        """
        if self.cursor is not None and self.limit is not None:
            raise ValueError(
                "Cannot specify both 'cursor' and 'limit' parameters. "
                "Use 'limit' for the first request, then 'cursor' for subsequent requests. "
                "The API remembers the limit from the first request."
            )
        return self

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Custom serialization to convert status to string."""
        data = super().model_dump(**kwargs)
        if "status" in data and isinstance(self.status, BatchItemsQueryStatus):
            data["status"] = self.status.value
        return data


class BatchItemsRequest(BaseRequestModel):
    """Request for GET /batches/{batch_id}/items."""

    path_params: BatchItemsPathParams
    query_params: BatchItemsQueryParams | None = None


# =============================================================================
# =============================================================================
# CRAWLS API MODELS
# =============================================================================
# =============================================================================


# =============================================================================
# CRAWLS START MODELS
# =============================================================================


class CrawlStartBodyParams(BodyParams):
    """Body parameters for POST /crawls."""

    start_url: HttpUrl
    max_pages: int | None = None
    include_urls: list[str] | None = None
    exclude_urls: list[str] | None = None
    max_depth: int | None = None
    include_external: bool | None = None
    include_subdomain: bool | None = None
    search_query: str | None = None
    top_n: int | None = None
    webhook_url: HttpUrl | None = None
    follow_robots_txt: bool = True

    @field_validator("max_pages")
    @classmethod
    def max_pages_must_be_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("max_pages must be positive")
        return v

    @field_validator("max_depth")
    @classmethod
    def max_depth_must_be_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("max_depth must be positive")
        return v

    @model_validator(mode="after")
    def at_least_one_limit_must_be_set(self) -> "CrawlStartBodyParams":
        if self.max_pages is None and self.max_depth is None:
            raise ValueError("At least one of max_pages or max_depth must be set")
        return self

    @field_validator("top_n")
    @classmethod
    def top_n_must_be_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("top_n must be positive")
        return v

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Custom serialization to remove empty keys and convert all HttpUrl fields to string."""
        kwargs["exclude_none"] = True
        data = super().model_dump(**kwargs)

        for key, value in data.items():
            if isinstance(value, HttpUrl):
                data[key] = str(value)
            elif isinstance(value, list):
                # Convert HttpUrl in lists to string
                data[key] = [
                    str(item) if isinstance(item, HttpUrl) else item for item in value
                ]
        return data


class CrawlStartRequest(BaseRequestModel):
    """Request for POST /crawls."""

    body_params: CrawlStartBodyParams


# =============================================================================
# CRAWLS INFO MODELS
# =============================================================================


class CrawlInfoPathParams(PathParams):
    """Path parameters for GET /crawls/{crawl_id}."""

    crawl_id: str


class CrawlInfoRequest(BaseRequestModel):
    """Request for GET /crawls/{crawl_id}."""

    path_params: CrawlInfoPathParams


# =============================================================================
# CRAWLS PAGES MODELS
# =============================================================================


class CrawlPagesPathParams(PathParams):
    """Path parameters for GET /crawls/{crawl_id}/pages."""

    crawl_id: str


class CrawlPagesQueryParams(QueryParams):
    """
    Query parameters for GET /crawls/{crawl_id}/pages.

    Pagination Behavior:
    ===================

    The Olostep API uses a cursor-based pagination system with the following rules:

    1. **First Request**: Send only `limit` parameter (no cursor)
       - Example: `?limit=10`
       - API returns first batch of pages + cursor token

    2. **Subsequent Requests**: Send only `cursor` parameter (no limit)
       - Example: `?cursor=1758303369342`
       - API remembers the limit from the first request
       - Returns next batch of pages + new cursor token

    3. **Pagination Complete**: When cursor is null/None
       - No more pages available
       - Stop pagination

    **Important**: Never send both `cursor` and `limit` in the same request.
    The API will ignore the limit if cursor is provided, which can lead to
    unexpected pagination behavior.
    ```
    """

    cursor: int | None = None
    limit: int | None = None
    search_query: str | None = None

    @field_validator("cursor")
    @classmethod
    def cursor_must_be_positive(cls, v: int | None) -> int | None:
        """Validate that cursor is a positive integer if provided."""
        if v is not None and v < 0:
            raise ValueError("cursor must be a positive integer")
        return v

    @field_validator("limit")
    @classmethod
    def limit_must_be_positive(cls, v: int | None) -> int | None:
        """Validate that limit is a positive integer if provided."""
        if v is not None and v <= 0:
            raise ValueError("limit must be a positive integer")
        return v

    @model_validator(mode="after")
    def cursor_and_limit_mutually_exclusive(self) -> "CrawlPagesQueryParams":
        """
        Enforce that cursor and limit cannot be sent together.

        This prevents confusion about pagination behavior and ensures
        the API's cursor-based pagination works correctly.
        """
        if self.cursor is not None and self.limit is not None:
            raise ValueError(
                "Cannot specify both 'cursor' and 'limit' parameters. "
                "Use 'limit' for the first request, then 'cursor' for subsequent requests. "
                "The API remembers the limit from the first request."
            )
        return self


class CrawlPagesRequest(BaseRequestModel):
    """Request for GET /crawls/{crawl_id}/pages."""

    path_params: CrawlPagesPathParams
    query_params: CrawlPagesQueryParams | None = None


# =============================================================================
# =============================================================================
# MAPS API MODELS
# =============================================================================
# =============================================================================


# There is only one endpoint for maps, so no need to split it into multiple markers.
class MapCreateBodyParams(BodyParams):
    """Body parameters for POST /maps."""

    url: HttpUrl
    search_query: str | None = None
    top_n: int | None = None
    include_subdomain: StrictBool | None = None
    include_urls: list[str] | None = None
    exclude_urls: list[str] | None = None
    cursor: str | None = None

    @field_validator("top_n")
    @classmethod
    def top_n_must_be_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("top_n must be positive")
        return v

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """Custom serialization to remove empty keys and convert HttpUrl to string."""
        kwargs["exclude_none"] = True
        data = super().model_dump(**kwargs)

        # Convert HttpUrl to string
        if "url" in data and isinstance(self.url, HttpUrl):
            data["url"] = str(self.url)

        return data


class MapCreateRequest(BaseRequestModel):
    """Request for POST /maps."""

    body_params: MapCreateBodyParams


# =============================================================================
# =============================================================================
# RETRIEVE API MODELS
# =============================================================================
# =============================================================================


# In an ideal world the retrieve format would be predeterminated by the original scrape/crawl/batch config.
class RetrieveFormat(str, Enum):
    """Output formats for retrieve content endpoint."""

    HTML = "html"
    MARKDOWN = "markdown"
    JSON = "json"

    def __str__(self) -> str:
        return self.value


class RetrieveGetQueryParams(QueryParams):
    """Query parameters for GET /retrieve."""

    retrieve_id: str
    formats: list[RetrieveFormat] | None = None

    # @model_validator(mode="after")
    # def set_default_formats(self) -> "RetrieveGetQueryParams":
    #     if self.formats is None:
    #         object.__setattr__(self, "formats", [])
    #     return self


class RetrieveGetRequest(BaseRequestModel):
    """Request for GET /retrieve."""

    query_params: RetrieveGetQueryParams


# =============================================================================
# =============================================================================
# ANSWERS API MODELS
# =============================================================================
# =============================================================================


class AnswersBodyParams(BodyParams):
    """Body parameters for POST /answers."""

    task: str
    json_format: dict[str, Any] | None = None

    @field_validator("json_format", mode="before")
    @classmethod
    def validate_json_format(cls, v: Any) -> dict[str, Any] | None:
        """Ensure json_format is either None or a dict with meaningful structure."""
        if v is None:
            return None
        if not isinstance(v, dict):
            raise ValueError(f"json_format must be a dict or None, got {type(v).__name__}")
        if not v:
            raise ValueError("json_format cannot be an empty dict")
        
        def has_meaningful_structure(d: dict[str, Any]) -> bool:
            """Check if dict has at least one key with meaningful structure.
            
            A dict with keys is meaningful structure (even if values are empty strings, as they're placeholders).
            Empty lists are also valid as they define structure. An empty dict is not meaningful.
            """
            if not d:
                return False
            for value in d.values():
                if (isinstance(value, dict) and value) or isinstance(value, list) or value is not None:
                    return True
            return False
        
        if not has_meaningful_structure(v):
            raise ValueError("json_format must have at least one key with meaningful structure (non-empty nested dict, list, or non-empty value)")
        return v


class AnswersRequest(BaseRequestModel):
    """Request for POST /answers."""

    body_params: AnswersBodyParams


# =============================================================================
# ANSWERS GET MODELS
# =============================================================================


class AnswersGetPathParams(PathParams):
    """Path parameters for GET /answers/{answer_id}."""

    answer_id: str


class AnswersGetRequest(BaseRequestModel):
    """Request for GET /answers/{answer_id}."""

    path_params: AnswersGetPathParams


# =============================================================================
# =============================================================================
# SEARCHES API MODELS
# =============================================================================
# =============================================================================


class SearchesScrapeOptions(OlostepBaseModel):
    """Optional scrape configuration embedded inside POST /searches.

    The /v1/searches endpoint rejects request bodies that contain explicit
    null values for optional fields (e.g. ``"remove_css_selectors": null``),
    so this model strips None values from its serialized output. Pydantic's
    internal serializer doesn't recurse through ``OlostepBaseModel.model_dump``
    overrides on nested models, so we use ``@model_serializer`` instead.
    """

    formats: list[Literal["html", "markdown"]] | None = None
    remove_css_selectors: str | None = None
    timeout: int | None = None

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not 1 <= v <= 60:
            raise ValueError("timeout must be between 1 and 60 seconds")
        return v

    @field_validator("formats")
    @classmethod
    def validate_formats_non_empty(
        cls, v: list[str] | None
    ) -> list[str] | None:
        if v is None:
            return None
        if not v:
            raise ValueError("formats must contain at least one of 'html' or 'markdown'")
        return v

    @model_serializer(mode="wrap")
    def _drop_none(self, handler) -> dict[str, Any]:
        return {k: v for k, v in handler(self).items() if v is not None}


class SearchesBodyParams(BodyParams):
    """Body parameters for POST /searches."""

    query: str
    limit: int | None = None
    include_domains: list[str] | None = None
    exclude_domains: list[str] | None = None
    scrape_options: SearchesScrapeOptions | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("query must be a non-empty string")
        return v

    @field_validator("limit")
    @classmethod
    def validate_limit(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not 1 <= v <= 25:
            raise ValueError("limit must be between 1 and 25")
        return v

    @model_serializer(mode="wrap")
    def _drop_empty(self, handler) -> dict[str, Any]:
        # Drops top-level Nones AND empty-dict values (e.g. when
        # SearchesScrapeOptions._drop_none reduces all-None inputs to {}),
        # keeping the validate_request and _compress_request paths in sync.
        out: dict[str, Any] = {}
        for k, v in handler(self).items():
            if v is None:
                continue
            if isinstance(v, dict) and not v:
                continue
            out[k] = v
        return out


class SearchesRequest(BaseRequestModel):
    """Request for POST /searches."""

    body_params: SearchesBodyParams


# =============================================================================
# SEARCHES GET MODELS
# =============================================================================


class SearchesGetPathParams(PathParams):
    """Path parameters for GET /searches/{search_id}."""

    search_id: str


class SearchesGetRequest(BaseRequestModel):
    """Request for GET /searches/{search_id}."""

    path_params: SearchesGetPathParams
