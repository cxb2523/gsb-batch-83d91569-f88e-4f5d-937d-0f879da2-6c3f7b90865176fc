from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import AliasChoices, Field, field_validator, model_validator

# =============================================================================
# RESPONSE MODELS
# =============================================================================
from .base import OlostepResponseBaseModel
from .common import Country

# =============================================================================
# =============================================================================
# COMMON SUB MODELS
# =============================================================================
# =============================================================================


class Status(str, Enum):
    """Common status values."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"

    def __str__(self) -> str:
        return self.value


# =============================================================================
# =============================================================================
# SCRAPES API MODELS
# =============================================================================
# =============================================================================


# Unified result model for both create/get scrape responses.
# Fields are optional when the corresponding content was not requested,
# not generated, or offloaded to hosted URLs due to size constraints.
class ScrapeOutputs(OlostepResponseBaseModel):
    html_content: str | None = None
    markdown_content: str | None = None
    text_content: str | None = None  # never observed to be not None
    json_content: dict[str, Any] | None = None

    html_hosted_url: str | None = None
    markdown_hosted_url: str | None = None
    json_hosted_url: str | None = None
    text_hosted_url: str | None = None
    file_hosted_url: str | None = None

    screenshot_hosted_url: str | None = None  # Beta feature

    links_on_page: list[str] | None = None
    page_metadata: dict[str, Any] | None = None
    llm_extract: dict[str, Any] | None = None
    network_calls: list[dict[str, Any]] | None = None
    size_exceeded: bool | None = None
    image_queued: bool | None = None
    success: bool | None = None

    @field_validator("json_content", mode="before")
    @classmethod
    def parse_json_content(cls, v):
        """Parse JSON string to dictionary if needed."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # If it's not valid JSON, return as-is (let Pydantic handle the error)
                return v
        return v  # return all other types as is


# Scrapes - Response Models
class ScrapeStorageResponse(OlostepResponseBaseModel):
    """Storage retention info returned on every scrape response."""

    expires_in: str = "7d"
    """Effective retention duration. One of: ``"7d"``, ``"10d"``, ``"30d"``,
    ``"60d"``, ``"90d"``, ``"180d"``, ``"365d"``, ``"never"``."""


class CreateScrapeResponse(OlostepResponseBaseModel):
    """Response from POST /scrapes (create scrape)."""

    id: str
    object: str = "scrape"
    created: int
    metadata: dict[str, Any] | None = None
    retrieve_id: str | None = None
    url: str
    result: ScrapeOutputs
    credits_consumed: int | None = None
    storage: ScrapeStorageResponse | None = None
    """Storage retention config. Always present; defaults to ``{"expires_in": "7d"}``."""
    # image_queued: bool | None = None


class GetScrapeResponse(CreateScrapeResponse):
    """Response from GET /scrapes/{id} (get scrape)."""

    # this seems to be nothing else but the CreateScrapeResponse model
    pass
    # id: str
    # object: str = "scrape"
    # created: int
    # metadata: dict[str, Any] | None = None # user defined metadata
    # retrieve_id: str | None = None
    # url_to_scrape: str
    # result: ScrapeOutputs


# =============================================================================
# =============================================================================
# BATCHES API MODELS
# =============================================================================
# =============================================================================


class Parser(OlostepResponseBaseModel):
    """Parser configuration."""

    id: str | None = None




class BatchCreateResponse(OlostepResponseBaseModel):
    """Response from POST /batches (create batch)."""

    # model_config = ConfigDict(extra='allow')  # Allow extra fields from API
    id: str
    object: str = "batch"
    status: Status
    created: int  # unix timestamp
    total_urls: int
    number_retried: int | None = None
    completed_urls: int
    # The API sends "parser" and "country"; "batch_parser" and "batch_country" are still accepted.
    batch_parser: str | None = Field(
        default=None, validation_alias=AliasChoices("parser", "batch_parser")
    )
    batch_country: Country | None = Field(
        default=None, validation_alias=AliasChoices("country", "batch_country")
    )
    start_date: str

    @field_validator("batch_parser", mode="after")
    @classmethod
    def parser_literal_none_string_to_none_type(cls, v: str | None) -> str | None:
        return None if v == "none" else v

    # this has never been observed and is here only on suspicion
    @field_validator("batch_country", mode="before")
    @classmethod
    def country_literal_none_string_to_none_type(cls, v: Any | None) -> str | None:
        """in case the country behaves like the parser we type-normalize here"""
        if isinstance(v, str) and v == "none":
            return None
        return v


class BatchInfoResponse(OlostepResponseBaseModel):
    """Response from GET /batches/{id} (get batch info)."""

    id: str
    # batch_id: str # same as id, undocumented in the docs, will be accepted but suppressed by the client
    object: str = "batch"
    status: Status
    created: int
    total_urls: int
    completed_urls: int
    number_retried: int
    parser: str | None = None  # The API omits it for batches created without a parser
    start_date: str
    country: Country | None = None

    @field_validator("parser", mode="after")
    @classmethod
    def parser_literal_none_string_to_none_type(cls, v: str | None) -> str | None:
        return None if v == "none" else v

    @field_validator("country", mode="before")
    @classmethod
    def country_literal_none_string_to_none_type(cls, v: Any | None) -> Any:
        """Type-normalize country field: convert 'none' string to None."""
        if isinstance(v, str) and v == "none":
            return None
        return v

    @model_validator(mode="before")
    def normalize_batch_id(cls, data: dict[str, Any]) -> dict[str, Any]:
        # batch_id is an alias to id - API sometimes returns both, but they're the same value
        # This allows the SDK to accept batch_id from the API without warnings
        if isinstance(data, dict) and "batch_id" in data:
            if "id" not in data:
                data["id"] = data["batch_id"]
            # Remove batch_id after normalizing to id to avoid extra field warning
            data.pop("batch_id", None)
        return data


class BatchItemsResponseStatus(str, Enum):
    """Common status values."""

    FAILED = "failed"  # used for filtering batch items
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"


class BatchItemsResponseListItem(OlostepResponseBaseModel):
    """Basic batch item info from GET /batches/{id}/items."""

    custom_id: str | None = None
    retrieve_id: str | None = None  # for failed items and items in progress
    url: str


class BatchItemsResponse(OlostepResponseBaseModel):
    """Response from get batch items."""

    id: str
    object: str = "batch"
    status: BatchItemsResponseStatus
    items: list[BatchItemsResponseListItem]
    items_count: int
    cursor: int | None = None


# =============================================================================
# =============================================================================
# CRAWLS API MODELS
# =============================================================================
# =============================================================================
class CrawlResponseStatus(str, Enum):
    """Common status values."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

    def __str__(self) -> str:
        return self.value


# Crawls - Response Models
class CreateCrawlResponse(OlostepResponseBaseModel):
    """Response from POST /v1/crawls (create crawl)."""

    id: str
    object: str = "crawl"
    status: CrawlResponseStatus
    created: int
    start_date: str
    start_url: str
    max_pages: int | None = None
    max_depth: int | None = None
    exclude_urls: list[str] | None = None
    include_urls: list[str] | None = None
    include_external: bool
    search_query: str | None = None
    top_n: int | None = None
    current_depth: int | None = None
    pages_count: int
    webhook_url: str | None = None

    @field_validator("max_pages", mode="before")
    @classmethod
    def validate_max_pages(cls, v):
        """Handle API returning invalid max_pages values."""
        if not isinstance(v, int):
            return None
        return v

    @field_validator("exclude_urls", mode="before")
    @classmethod
    def validate_exclude_urls(cls, v):
        """Handle API returning invalid exclude_urls values."""
        if not isinstance(v, list):
            # If not a list, return None (empty list)
            return None
        return v

    @field_validator("include_urls", mode="before")
    @classmethod
    def validate_include_urls(cls, v):
        """Handle API returning invalid include_urls values."""
        if not isinstance(v, list):
            # If not a list, return default value
            return None
        return v

    @field_validator("search_query", mode="before")
    @classmethod
    def validate_search_query(cls, v):
        """Handle API returning invalid search_query values."""
        if v is not None and not isinstance(v, str):
            # If not a string, return None
            return None
        return v

    @field_validator("webhook_url", mode="before")
    @classmethod
    def validate_webhook_url(cls, v):
        """Handle API returning invalid webhook_url values."""
        if v is not None and not isinstance(v, str):
            # If not a string, return None
            return None
        return v

    @field_validator("max_depth", mode="before")
    @classmethod
    def validate_max_depth(cls, v):
        """Handle API returning invalid max_depth values."""
        if v is not None and not isinstance(v, int):
            # If not an integer, return None (optional field)
            return None
        return v

    @field_validator("top_n", mode="before")
    @classmethod
    def validate_top_n(cls, v):
        """Handle API returning invalid top_n values."""
        if v is not None and not isinstance(v, int):
            # If not an integer, return None (optional field)
            return None
        return v

    @field_validator("include_external", mode="before")
    @classmethod
    def validate_include_external(cls, v):
        """Handle API returning invalid include_external values."""
        if not isinstance(v, bool):
            # If not a boolean, return default value False
            return False
        return v


# For GET /v1/crawls/{id}
class CrawlInfoResponse(CreateCrawlResponse):
    """Response from GET /v1/crawls/{id} (crawl info)."""

    pass


class CrawlPagesResponseListItem(OlostepResponseBaseModel):
    """Item returned by GET /v1/crawls/{crawl_id}/pages."""

    id: str
    retrieve_id: str
    url: str
    is_external: bool


class CrawlPagesResponseMetadata(OlostepResponseBaseModel):
    """Metadata for crawl pages response."""

    external_urls: list[str]
    failed_urls: list[str]
    # model_config = ConfigDict(extra='allow')


class CrawlPagesResponse(OlostepResponseBaseModel):
    """The response returned by GET /v1/crawls/{crawl_id}/pages."""

    id: str
    object: str = "crawl"
    status: Status
    search_query: str | None = None
    pages_count: int
    pages: list[CrawlPagesResponseListItem]
    metadata: CrawlPagesResponseMetadata
    cursor: int | None = (
        None  # needs to be passed back to the server in combo with limit
    )
    # limit: int is not returned


# =============================================================================
# =============================================================================
# MAPS API MODELS
# =============================================================================
# =============================================================================
class MapResponse(OlostepResponseBaseModel):
    """Response from create map (link extraction)."""

    urls_count: int
    urls: list[str]
    id: str | None = None
    cursor: str | None = (
        None  # according to the docs, this is the cursor is set if the response contains more then 100k urls / 10MB
    )


# =============================================================================
# =============================================================================
# RETRIEVE API MODELS
# =============================================================================
# =============================================================================
class RetrieveResponse(ScrapeOutputs):
    """Response from retrieve content (GET /v1/retrieve)."""

    # this seems to be nothing else but the ScrapeOutputs model
    pass


# =============================================================================
# =============================================================================
# ANSWERS API MODELS
# =============================================================================
# =============================================================================


class AnswersResult(OlostepResponseBaseModel):
    """Result object containing the answer data."""

    json_content: str | None = None # should be dict[str, Any] | None but the API returns such inconsistent types that is hopeless. sorry @ users.
    json_hosted_url: str | None = None
    sources: list[str] | None = None

    # @field_validator("json_content", mode="before")
    # @classmethod
    # def parse_json_content(cls, v):
    #     """Parse JSON string to dictionary if needed."""
    #     if isinstance(v, str):
    #         try:
    #             return json.loads(v)
    #         except json.JSONDecodeError:
    #             # If it's not valid JSON, return as-is (let Pydantic handle the error)
    #             return v
    #     return v  # return all other types as is


class AnswersResponse(OlostepResponseBaseModel):
    """Response from POST /answers."""

    id: str
    object: str = "answer"
    created: int
    metadata: dict[str, Any] | None = None
    task: str
    result: AnswersResult


# =============================================================================
# =============================================================================
# SEARCHES API MODELS
# =============================================================================
# =============================================================================


class SearchLink(OlostepResponseBaseModel):
    """A single deduplicated search result link."""

    url: str
    title: str | None = None
    description: str | None = None
    markdown_content: str | None = None
    html_content: str | None = None


class SearchesResult(OlostepResponseBaseModel):
    """Result object containing the search data."""

    json_content: str | None = None
    json_hosted_url: str | None = None
    size_exceeded: bool | None = None
    credits_consumed: int | None = None
    links: list[SearchLink] = []


class SearchesResponse(OlostepResponseBaseModel):
    """Response from POST /searches and GET /searches/{search_id}."""

    id: str
    object: str = "search"
    created: int
    metadata: dict[str, Any] | None = None
    query: str
    credits_consumed: int = 0
    result: SearchesResult


# =============================================================================
# =============================================================================
# MONITORS API MODELS
# =============================================================================
# =============================================================================


class MonitorSchedule(OlostepResponseBaseModel):
    """Schedule configuration returned on a monitor object."""

    frequency: str | None = None
    cron: str | None = None
    timezone: str | None = None
    next_run_at: str | None = None  # ISO 8601; null when not active


class MonitorTracked(OlostepResponseBaseModel):
    """Tracked target information returned on a monitor object."""

    type: str | None = None
    urls: list[str] | None = None
    web_query: str | None = None


class MonitorNotificationChannel(OlostepResponseBaseModel):
    """A single notification channel entry."""

    type: str  # "email" | "slack" | "sms"
    target: str
    events: list[str] | None = None


class MonitorNotification(OlostepResponseBaseModel):
    """Notification configuration on a monitor object."""

    events: list[str] | None = None
    channels: list[MonitorNotificationChannel] | None = None


class MonitorWebhook(OlostepResponseBaseModel):
    """Webhook configuration on a monitor object."""

    url: str


class MonitorLastRun(OlostepResponseBaseModel):
    """Most recent run summary, included on GET /monitors/{id}."""

    id: str
    status: str  # "completed" | "failed"
    change_detected: bool
    ran_at: str | None = None  # ISO 8601


class MonitorAgentRef(OlostepResponseBaseModel):
    """Reference to the shadow agent backing this monitor."""

    id: str | None = None


class MonitorSourcePolicy(OlostepResponseBaseModel):
    """Source URL policy on a monitor object."""

    include_urls: list[str] | None = None
    exclude_urls: list[str] | None = None
    include_domains: list[str] | None = None
    exclude_domains: list[str] | None = None


class MonitorResponse(OlostepResponseBaseModel):
    """Response for a single monitor (create, get, update, pause, resume, delete)."""

    id: str
    object: str = "monitor"
    query: str
    status: str  # provisioning | active | paused | failed | deleted
    tracked: MonitorTracked | None = None
    source_policy: MonitorSourcePolicy | None = None
    schedule: MonitorSchedule | None = None
    notification: MonitorNotification | None = None
    webhook: MonitorWebhook | None = None
    output_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    agent: MonitorAgentRef | None = None
    last_run: MonitorLastRun | None = None
    total_count: int | None = None
    mermaid_diagram: str | None = None
    error_message: str | None = None
    created: int | None = None   # Unix seconds
    updated: int | None = None   # Unix seconds


class MonitorListResponse(OlostepResponseBaseModel):
    """Response from GET /monitors (list monitors)."""

    monitors: list[MonitorResponse] = []
    count: int = 0


class MonitorDeleteResponse(OlostepResponseBaseModel):
    """Response from DELETE /monitors/{id}."""

    message: str
    monitor_id: str


class MonitorEvent(OlostepResponseBaseModel):
    """A single snapshot event entry from GET /monitors/{id}/events."""

    id: str
    run_id: str | None = None
    created: int | None = None   # Unix seconds
    changed: bool | None = None
    summary: str | None = None
    snapshot_url: str | None = None  # pre-signed S3 URL


class MonitorEventsResponse(OlostepResponseBaseModel):
    """Response from GET /monitors/{id}/events."""

    data: list[MonitorEvent] = []
    has_more: bool = False
    next_cursor: str | None = None
    total_count: int | None = None
