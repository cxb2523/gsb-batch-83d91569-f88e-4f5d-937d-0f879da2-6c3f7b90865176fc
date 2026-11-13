"""
Stateful client objects for the Typed UI.

This layer provides quality-of-life wrappers that hold minimal client-side state
(e.g., ids, cursors, original request hints) and expose ergonomic shorthand
methods for follow-up operations (info, items/pages, next, retrieve). It also
presents response data via friendly properties and readable string
representations, while leaving all IO validation to the backend (Pydantic) and
all transport logic to the EndpointCaller.
"""

from __future__ import annotations

import asyncio
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from .._log import get_logger
from ..backend.api_endpoints import CONTRACTS
from ..backend.caller import EndpointCaller
from ..errors import OlostepClientError_BatchItemFailed, OlostepClientError_Timeout
from ..models.response import (
    AnswersResponse,
    BatchCreateResponse,
    BatchInfoResponse,
    BatchItemsResponse,
    BatchItemsResponseListItem,
    CrawlInfoResponse,
    CrawlPagesResponse,
    CrawlPagesResponseListItem,
    CrawlResponseStatus,
    CreateCrawlResponse,
    CreateScrapeResponse,
    GetScrapeResponse,
    MapResponse,
    MonitorDeleteResponse,
    MonitorEventsResponse,
    MonitorListResponse,
    MonitorResponse,
    RetrieveResponse,
    SearchesResponse,
)

logger = get_logger("frontend.client_state")


class ScrapeResult:
    """Unified result object for scrape and retrieve operations.

    This class provides a single interface for accessing the results of scrape-related
    API calls. It dynamically exposes content fields and metadata based on the response
    type and available data.

    The class handles two main response types:
    - /scrapes (create, get): Includes metadata fields plus content
    - /retrieve: Content fields only (if present and non-null)

    Attributes:
        id: Unique identifier for the scrape operation (scrapes endpoints only)
        created: Creation timestamp as Unix epoch (scrapes endpoints only)
        url: The URL that was scraped (scrapes endpoints only)
        metadata: Metadata dictionary (scrapes endpoints only)
        retrieve_id: Unique identifier for retrieve operations (scrapes endpoints only)
        credits_consumed: Number of credits consumed for this scrape (scrapes endpoints only)
        html_content: Raw HTML content of the scraped page (if available)
        markdown_content: Markdown-formatted content (if available)
        text_content: Plain text content (if available)
        json_content: Structured JSON data (if available)
        html_hosted_url: URL to hosted HTML content (if available)
        markdown_hosted_url: URL to hosted Markdown content (if available)
        json_hosted_url: URL to hosted JSON content (if available)
        text_hosted_url: URL to hosted text content (if available)
        file_hosted_url: URL to hosted file content (if available)
        screenshot_hosted_url: URL to screenshot (if available)
        links_on_page: List of links found on the page (if available)
        page_metadata: Page-level metadata (if available)
        llm_extract: LLM extraction results (if available)
        network_calls: List of network calls made during scraping (if available)
        size_exceeded: Whether content size exceeded limits (if available)
        image_queued: Whether an image was queued for processing (if available)
    """

    def __init__(
        self, response: CreateScrapeResponse | GetScrapeResponse | RetrieveResponse
    ) -> None:
        """Initialize ScrapeResult from an API response.

        Args:
            response: API response object from scrape or retrieve endpoints.
                Supports CreateScrapeResponse, GetScrapeResponse, or RetrieveResponse.

        Raises:
            ValueError: If the response type is not supported.
        """
        if isinstance(response, (CreateScrapeResponse, GetScrapeResponse)):
            self.id = response.id
            self.created = response.created
            self.url = response.url
            self.metadata = response.metadata
            self.retrieve_id = response.retrieve_id
            self.credits_consumed = response.credits_consumed
            self.storage = response.storage

            results = response.result  # result is nested for these endpoints
        elif isinstance(response, RetrieveResponse):
            results = response  # /retrieve returns content fields directly
        else:
            raise ValueError(
                f"Invalid response type: {type(response)} for ScrapeResult"
            )

        # Dynamically set attributes for all fields in the results model that are not null
        for k, v in results.model_dump().items():
            if v is not None:
                setattr(self, k, v)

    @property
    def url_to_scrape(self) -> str | None:
        """Deprecated: Use 'url' instead.
        
        This property is provided for backwards compatibility and will be removed
        in a future version. Use the 'url' attribute instead.
        
        Returns:
            The URL that was scraped, or None if not available (e.g., for RetrieveResponse).
        """
        warnings.warn(
            "The 'url_to_scrape' attribute is deprecated. Use 'url' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(self, 'url', None)

    def __repr__(self) -> str:
        content_keys = [
            attr
            for attr in vars(self)
            if (attr.endswith("_content") or attr.endswith("_hosted_url"))
            and getattr(self, attr, None) is not None
        ]
        _id = f"id={self.id!r}, " if hasattr(self, "id") and self.id else ""
        return f"ScrapeResult({_id}available={content_keys})"

    def __str__(self) -> str:
        html_len = (
            len(self.html_content)
            if hasattr(self, "html_content") and self.html_content
            else 0
        )
        md_len = (
            len(self.markdown_content)
            if hasattr(self, "markdown_content") and self.markdown_content
            else 0
        )
        txt_len = (
            len(self.text_content)
            if hasattr(self, "text_content") and self.text_content
            else 0
        )

        _id = f"id={self.id!r}, " if hasattr(self, "id") and self.id else ""
        return (
            f"ScrapeResult({_id}html={html_len}B, md={md_len}B, text={txt_len}B, "
            f"json={'yes' if hasattr(self, 'json_content') and bool(self.json_content) else 'no'})"
        )


class AnswersResult:
    """Result object for answers operations.

    This class provides a convenient interface for accessing the results of
    answer generation API calls. It exposes the answer data, metadata, and
    provides formatted representations for easy inspection.

    Attributes:
        id: Unique identifier for the answer operation
        object: Object type identifier ("answer")
        created: Creation timestamp as Unix epoch
        metadata: Metadata dictionary (if provided)
        task: The task that was performed
        json_content: Structured JSON content of the answer (if available)
        json_hosted_url: URL to hosted JSON content (if available)
        sources: List of source URLs used to generate the answer (if available)
    """

    def __init__(self, response: AnswersResponse) -> None:
        """Initialize AnswersResult from an API response.

        Args:
            response: API response object from answers endpoint.
        """
        # Copy all fields from response to reduce dependency
        self.id = response.id
        self.object = response.object
        self.created = response.created
        self.metadata = response.metadata or {}
        self.task = response.task

        # Copy result fields
        result = response.result
        self.json_content = result.json_content
        self.json_hosted_url = result.json_hosted_url
        if hasattr(result, "sources") and result.sources is not None:
            self.sources = result.sources
        else:
            self.sources = []
    
    @property
    def answer(self) -> str | None:
        """Alias for json_content to match documentation API."""
        if isinstance(self.json_content, str):
            return self.json_content
        return str(self.json_content) if self.json_content is not None else None

    def __repr__(self) -> str:
        """Return a string representation of the AnswersResult.

        Returns:
            str: String representation showing id, task, and content availability.
        """
        content_info = []
        if self.json_content:
            content_info.append(f"json_content={len(self.json_content)}chars")
        if self.json_hosted_url:
            content_info.append("hosted_url")

        content_str = f"({', '.join(content_info)})" if content_info else "(no content)"

        task_str = self.task[:50] + ("..." if len(self.task) > 50 else "")
        return f"AnswersResult(id={self.id!r}, task={task_str!r}, {content_str})"

    def __str__(self) -> str:
        """Return a human-readable string representation of the AnswersResult.

        Returns:
            str: Human-readable string showing key information.
        """
        return f"Answer: {self.task[:50]}{'...' if len(self.task) > 50 else ''} -> {len(self.sources)} sources"


class SearchesResult:
    """Result object for searches operations.

    Wraps the response of a `client.searches.create()` or `.get()` call,
    exposing the search id, query, and the list of returned links. When
    `scrape_options` were provided, each link in `links` carries
    `markdown_content` / `html_content` directly.

    Attributes:
        id: Unique identifier for the search operation
        object: Object type identifier ("search")
        created: Creation timestamp as Unix epoch
        metadata: Metadata dictionary (if provided)
        query: The original search query
        credits_consumed: Total credits billed for this search (search + any scrapes)
        links: List of result links (each with url/title/description and optional content)
        json_content: Inline JSON payload (when present)
        json_hosted_url: Hosted JSON URL (use when size_exceeded is True)
        size_exceeded: True when inline content exceeded 9MB and was offloaded
    """

    def __init__(self, response: SearchesResponse) -> None:
        """Initialize SearchesResult from an API response.

        Args:
            response: API response object from /searches endpoint.
        """
        self.id = response.id
        self.object = response.object
        self.created = response.created
        self.metadata = response.metadata or {}
        self.query = response.query
        self.credits_consumed = response.credits_consumed

        result = response.result
        self.json_content = result.json_content
        self.json_hosted_url = result.json_hosted_url
        self.size_exceeded = bool(result.size_exceeded) if result.size_exceeded is not None else False
        self.links = [link.model_dump() for link in (result.links or [])]

    def __repr__(self) -> str:
        """Return a string representation of the SearchesResult."""
        query_str = self.query[:50] + ("..." if len(self.query) > 50 else "")
        return (
            f"SearchesResult(id={self.id!r}, query={query_str!r}, "
            f"links={len(self.links)}, credits_consumed={self.credits_consumed})"
        )

    def __str__(self) -> str:
        """Return a human-readable string representation of the SearchesResult."""
        query_str = self.query[:50] + ("..." if len(self.query) > 50 else "")
        return f"Search: {query_str} -> {len(self.links)} links"


@dataclass
class RetrievableID:
    """Represents a retrievable ID with metadata and expiration checking.

    This class provides a convenient way to track and manage retrievable IDs
    with their associated metadata, including age calculation and expiration checking.

    Attributes:
        id: The unique identifier for the retrievable content.
        type: The type of retrievable content (e.g., "scrape", "batch_item").
        timestamp: Unix timestamp when the ID was created.
    """

    id: str
    type: str
    timestamp: int  # Unix timestamp

    def __repr__(self) -> str:
        """Return a string representation of the RetrievableID.

        Returns:
            str: String representation showing id, type, and age.
        """
        return f"RetrievableID(id={self.id!r}, type={self.type!r}, age={self.age})"

    @property
    def age(self) -> str:
        """Get human-readable age of this ID.

        Returns:
            str: Human-readable time delta (e.g., "2h ago", "3d ago").
        """
        return _format_time_delta(self.timestamp)

    def is_expired(self, retention_days: int = 7) -> bool:
        """Check if this ID is expired based on retention days.

        Args:
            retention_days: Number of days to retain the ID (default: 7).

        Returns:
            bool: True if the ID is expired, False otherwise.
        """
        if not self.timestamp:
            return True

        try:
            created_time = datetime.fromtimestamp(self.timestamp, tz=timezone.utc)
            now = datetime.now(tz=timezone.utc)
            expiry_time = created_time + timedelta(days=retention_days)
            return now > expiry_time
        except (ValueError, OSError):
            return True


class BatchItemResult:
    """Represents a single item in a batch processing operation.

    Each BatchItemResult corresponds to one URL that was processed as part of a batch.
    It provides access to the URL, custom ID, and allows retrieving the scraped
    content for that specific item.

    NOTE: This class was renamed from BatchItem to BatchItemResult to avoid naming
    conflicts with the BatchItem model in olostep.models.request. The frontend wrapper
    (BatchItemResult) handles API responses, while the model (BatchItem) validates API requests.

    Attributes:
        url: The URL that was processed.
        retrieve_id: Unique identifier for retrieving the scraped content.
        custom_id: Custom identifier provided when creating the batch.
    """

    def __init__(
        self, caller: EndpointCaller, item: BatchItemsResponseListItem
    ) -> None:
        """Initialize BatchItemResult from API response.

        Args:
            caller: EndpointCaller for making API requests.
            item: Batch item data from API response.
        """
        self._caller = caller
        # Copy fields from item to reduce dependency
        self.url = item.url
        self.retrieve_id = item.retrieve_id
        self.custom_id = item.custom_id or ""

    def __repr__(self) -> str:
        """Return a string representation of the BatchItemResult.

        Returns:
            str: String representation showing url, retrieve_id, and custom_id.
        """
        return f"BatchItemResult(url={self.url!r}, retrieve_id={self.retrieve_id!r}, custom_id={self.custom_id!r})"

    def __str__(self) -> str:
        """Return a human-readable string representation of the BatchItemResult.

        Returns:
            str: Human-readable string showing custom_id, url, and retrieve_id.
        """
        return f"BatchItemResult {self.custom_id or '-'} -> {self.url} ({self.retrieve_id})"

    async def retrieve(self, formats: list[str] | None = None) -> ScrapeResult:
        """Retrieve the scraped content for this batch item.

        Fetches the scraped content for this specific batch item using its
        retrieve_id. Supports filtering by content formats.

        Args:
            formats: List of content formats to retrieve (e.g., ["html", "markdown"]).
                If None, returns all available formats.

        Returns:
            ScrapeResult: The scraped content in the requested formats.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Retrieve all available formats
            result = await batch_item.retrieve()

            # Retrieve specific formats
            result = await batch_item.retrieve(["html", "markdown"])
        """
        return await _retrieve_content(self._caller, self.retrieve_id, formats)


async def _retrieve_content(
    caller: EndpointCaller,
    retrieve_id: str | None,
    formats: list[str] | None = None,
) -> ScrapeResult:
    """Fetch content for a retrieve id through the /retrieve endpoint."""
    c = CONTRACTS[("retrieve", "get")]
    # todo: if we had request validation for all endpoints we could put coersion into the models and
    # have endpoints like this support coersion for e.g. formats too.
    query_params: dict[str, Any] = {
        "retrieve_id": retrieve_id,
    }
    if formats is not None:
        query_params["formats"] = formats
    data: RetrieveResponse = await caller.invoke(c, query_params=query_params)
    return ScrapeResult(data)


def _scrape_result_has_content(result: ScrapeResult) -> bool:
    """Whether a retrieve result carries any usable scraped content."""
    content_or_hosted_fields = (
        "html_content",
        "markdown_content",
        "text_content",
        "json_content",
        "html_hosted_url",
        "markdown_hosted_url",
        "json_hosted_url",
        "text_hosted_url",
        "file_hosted_url",
    )
    return any(getattr(result, field, None) for field in content_or_hosted_fields)


# Fields the batch items API may use to describe why an item failed. The response
# model allows extra fields, so we read them without widening the contract model.
_BATCH_ITEM_ERROR_FIELDS = (
    "error",
    "error_message",
    "error_reason",
    "failure_reason",
    "reason",
    "message",
    "detail",
)

# Item statuses that mean "this URL could not be processed".
_BATCH_ITEM_FAILED_STATUSES = ("failed", "error", "errored")


def _raw_item_extra(item: BatchItemsResponseListItem) -> dict[str, Any]:
    """Return the extra (non-contract) fields the API attached to a batch item."""
    return dict(getattr(item, "model_extra", None) or {})


def _raw_item_status(item: BatchItemsResponseListItem) -> str | None:
    """Best-effort per-item status, if the API provides one."""
    extra = _raw_item_extra(item)
    for key in ("status", "state", "item_status"):
        value = extra.get(key)
        if isinstance(value, str) and value:
            return value.lower()
    return None


def _raw_item_failure_reason(item: BatchItemsResponseListItem) -> str | None:
    """Best-effort human-readable failure reason attached to a batch item."""
    extra = _raw_item_extra(item)
    for key in _BATCH_ITEM_ERROR_FIELDS:
        value = extra.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for nested_key in ("message", "reason", "detail"):
                nested = value.get(nested_key)
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    return None


def _classify_fetched_item(
    item: BatchItemsResponseListItem,
) -> tuple[bool, str | None]:
    """Decide whether a fetched batch item succeeded, and why it did not.

    The API does not always expose a per-item status, so failure detection is
    conservative: an item is successful only when it has a ``retrieve_id`` and
    no failure status/reason. This means failed items are never silently dropped.
    """
    status = _raw_item_status(item)
    reason = _raw_item_failure_reason(item)

    if status in _BATCH_ITEM_FAILED_STATUSES:
        return False, reason or f"the item status is '{status}'"
    if reason:
        return False, reason
    if not item.retrieve_id:
        if status:
            return False, f"the item status is '{status}' and it has no retrieve_id"
        return False, "the item has no retrieve_id, so it has no retrievable content"
    return True, None


def _url_alias_candidates(url: str | None) -> set[str]:
    """Normalized URL forms so HttpUrl trailing-slash changes still match."""
    if not url:
        return set()
    candidates = {url, url.rstrip("/")}
    if url.endswith("/"):
        candidates.add(url[:-1])
    else:
        candidates.add(f"{url}/")
    return candidates


def _build_summary_items(
    caller: EndpointCaller | None,
    fetched: list[BatchItemsResponseListItem],
    requested_items: list[dict[str, Any]] | None = None,
    local_failures: dict[int, str] | None = None,
) -> list[BatchSummaryItem]:
    """Pair fetched API items with the original request and classify them.

    Every requested item appears exactly once. Requested items the API never
    reported are included as failures instead of being dropped.

    ``local_failures`` maps an index in ``requested_items`` to a readable reason
    for items that were rejected client-side and never sent to the API.
    """
    requested = list(requested_items or [])
    local_failures = dict(local_failures or {})

    if not requested:
        # Nothing is known about the original request: summarize whatever the
        # API returned, in API order.
        entries: list[BatchSummaryItem] = []
        for item in fetched:
            succeeded, reason = _classify_fetched_item(item)
            entries.append(
                BatchSummaryItem(
                    caller,
                    url=item.url,
                    custom_id=item.custom_id,
                    retrieve_id=item.retrieve_id,
                    succeeded=succeeded,
                    reason=reason,
                )
            )
        return entries

    # Match fetched items to requested entries. custom_id is the primary key (the
    # API round-trips it verbatim); URL matching and positional matching are
    # fallbacks for items created without a custom id.
    matched_entries: dict[int, BatchSummaryItem] = {}
    extra_entries: list[BatchSummaryItem] = []

    remaining = list(range(len(requested)))
    for item in fetched:
        request_index = _match_requested_index(item, requested, remaining)
        succeeded, reason = _classify_fetched_item(item)

        if request_index is None:
            # The API reported an item we never asked for; keep it visible.
            extra_entries.append(
                BatchSummaryItem(
                    caller,
                    url=item.url,
                    custom_id=item.custom_id,
                    retrieve_id=item.retrieve_id,
                    succeeded=succeeded,
                    reason=reason,
                )
            )
            continue

        remaining.remove(request_index)
        request = requested[request_index]
        matched_entries[request_index] = BatchSummaryItem(
            caller,
            url=request.get("url") or item.url,
            custom_id=request.get("custom_id") or item.custom_id,
            retrieve_id=item.retrieve_id,
            succeeded=succeeded,
            reason=reason,
        )

    # Items the API never reported: still part of the summary, marked failed.
    # This covers terminal states where the API dropped a URL (e.g. a batch that
    # finished with fewer items than were submitted).
    for index, request in enumerate(requested):
        if index in matched_entries:
            continue
        matched_entries[index] = BatchSummaryItem(
            caller,
            url=request.get("url"),
            custom_id=request.get("custom_id"),
            retrieve_id=None,
            succeeded=False,
            reason=local_failures.get(index, "the batch item was not reported by the API"),
        )

    # Preserve input order for matched items, then append API-only extras.
    return [matched_entries[index] for index in range(len(requested))] + extra_entries


def _match_requested_index(
    item: BatchItemsResponseListItem,
    requested: list[dict[str, Any]],
    remaining: list[int],
) -> int | None:
    """Find the requested entry a fetched item belongs to, if any."""
    if item.custom_id:
        for index in remaining:
            if requested[index].get("custom_id") == item.custom_id:
                return index
        # The API returned an id we did not send: fall back to URL matching so
        # the item is not double-counted as an extra entry.

    aliases = _url_alias_candidates(item.url)
    for index in remaining:
        if requested[index].get("url") in aliases:
            return index

    # Last resort for items without custom id: take the next unmatched request
    # that also had no custom id, so positional pairing stays stable.
    for index in remaining:
        if not requested[index].get("custom_id"):
            return index
    return None


class BatchSummaryItem:
    """A single entry in a :class:`BatchSummary`.

    Unlike :class:`BatchItemResult` (which mirrors one item returned by the API),
    a summary item may also represent a URL that the API never returned at all.
    Every entry keeps the original ``url`` and ``custom_id`` (when one was supplied
    or auto-generated) so callers can reconcile the summary with their input.

    Attributes:
        url: The original URL requested for this item.
        custom_id: Custom identifier supplied with the batch, if any.
        retrieve_id: Identifier usable with the retrieve endpoint (success items only).
        succeeded: Whether the item was processed successfully.
        reason: Human-readable failure reason (``None`` for successful items).
    """

    def __init__(
        self,
        caller: EndpointCaller | None,
        *,
        url: str,
        custom_id: str | None = None,
        retrieve_id: str | None = None,
        succeeded: bool = False,
        reason: str | None = None,
    ) -> None:
        self._caller = caller
        self.url = url
        self.custom_id = custom_id
        self.retrieve_id = retrieve_id
        self.succeeded = succeeded
        self.reason = reason

    @property
    def success(self) -> bool:
        """Alias for :attr:`succeeded`."""
        return self.succeeded

    @property
    def failed(self) -> bool:
        """Whether this item failed and therefore has no content to retrieve."""
        return not self.succeeded

    @property
    def failure_reason(self) -> str | None:
        """Alias for :attr:`reason`."""
        return self.reason

    @property
    def error(self) -> str | None:
        """Alias for :attr:`reason`."""
        return self.reason

    def __repr__(self) -> str:
        return (
            f"BatchSummaryItem(url={self.url!r}, custom_id={self.custom_id!r}, "
            f"succeeded={self.succeeded!r}, reason={self.reason!r})"
        )

    def __str__(self) -> str:
        label = self.custom_id or "-"
        if self.succeeded:
            return f"BatchSummaryItem {label} -> {self.url} (ok)"
        return f"BatchSummaryItem {label} -> {self.url} (failed: {self.reason})"

    async def retrieve(self, formats: list[str] | None = None) -> ScrapeResult:
        """Retrieve the scraped content for this item.

        Args:
            formats: List of content formats to retrieve (e.g., ["html", "markdown"]).
                If None, returns all available formats.

        Returns:
            ScrapeResult: The scraped content in the requested formats.

        Raises:
            OlostepClientError_BatchItemFailed: If this item failed processing, or
                if the API returns no content at all. Failure is signalled explicitly
                instead of returning an empty result the caller could mistake for
                a successful scrape.
            Exception: If the API request fails for a successful item.
        """
        if not self.succeeded or not self.retrieve_id:
            raise OlostepClientError_BatchItemFailed(
                url=self.url,
                custom_id=self.custom_id,
                reason=self.reason or "the item has no retrievable content",
            )

        result = await _retrieve_content(self._caller, self.retrieve_id, formats)
        if not _scrape_result_has_content(result):
            raise OlostepClientError_BatchItemFailed(
                url=self.url,
                custom_id=self.custom_id,
                reason=(
                    "the API returned no content for this item"
                    f" (retrieve_id={self.retrieve_id!r})"
                ),
            )
        return result


class BatchSummary:
    """Aggregated outcome of a batch: successful and failed items side by side.

    Typically returned by ``BatchMenu.create_summary()`` (or ``Batch.summary()``)
    after the batch has finished. Every requested URL is represented exactly once,
    so partial failures never disappear from the summary.

    Attributes:
        batch: The underlying :class:`Batch` (``None`` for an empty input summary).
        items: All entries in input order, each a :class:`BatchSummaryItem`.
    """

    def __init__(
        self,
        batch: "Batch | None",
        items: list[BatchSummaryItem] | None = None,
    ) -> None:
        self.batch = batch
        self.items: list[BatchSummaryItem] = list(items or [])

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------
    @property
    def total_count(self) -> int:
        """Total number of entries in the summary."""
        return len(self.items)

    @property
    def total(self) -> int:
        """Alias for :attr:`total_count`."""
        return self.total_count

    @property
    def success_count(self) -> int:
        """Number of successfully processed entries."""
        return sum(1 for item in self.items if item.succeeded)

    @property
    def failed_count(self) -> int:
        """Number of failed entries."""
        return self.total_count - self.success_count

    @property
    def successful_count(self) -> int:
        """Alias for :attr:`success_count`."""
        return self.success_count

    @property
    def successful_items(self) -> list[BatchSummaryItem]:
        """All successful entries."""
        return [item for item in self.items if item.succeeded]

    @property
    def failed_items(self) -> list[BatchSummaryItem]:
        """All failed entries."""
        return [item for item in self.items if not item.succeeded]

    @property
    def successes(self) -> list[BatchSummaryItem]:
        """Alias for :attr:`successful_items`."""
        return self.successful_items

    @property
    def failures(self) -> list[BatchSummaryItem]:
        """Alias for :attr:`failed_items`."""
        return self.failed_items

    def __len__(self) -> int:
        return self.total_count

    def __iter__(self):
        return iter(self.items)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    def get_all_by_custom_id(self, custom_id: str) -> list[BatchSummaryItem]:
        """Return every entry carrying ``custom_id`` (may be empty).

        Duplicate custom ids are preserved in input order; use this method when
        duplicates are possible, otherwise prefer :meth:`get_by_custom_id`.
        """
        return [item for item in self.items if item.custom_id == custom_id]

    def get_by_custom_id(self, custom_id: str) -> BatchSummaryItem:
        """Return the first entry carrying ``custom_id``.

        Raises:
            KeyError: If no entry has that custom id.
        """
        matches = self.get_all_by_custom_id(custom_id)
        if not matches:
            raise KeyError(f"No batch summary item with custom_id={custom_id!r}")
        return matches[0]

    def find_by_custom_id(self, custom_id: str) -> BatchSummaryItem | None:
        """Return the first entry carrying ``custom_id`` or ``None`` if absent."""
        matches = self.get_all_by_custom_id(custom_id)
        return matches[0] if matches else None

    def __getitem__(self, key: str) -> BatchSummaryItem:
        """Look an entry up by custom id (raises ``KeyError`` when absent)."""
        return self.get_by_custom_id(key)

    def __repr__(self) -> str:
        batch_id = self.batch.id if self.batch is not None else None
        return (
            f"BatchSummary(batch_id={batch_id!r}, total={self.total_count}, "
            f"success={self.success_count}, failed={self.failed_count})"
        )

    def __str__(self) -> str:
        batch_id = self.batch.id if self.batch is not None else "-"
        return (
            f"BatchSummary {batch_id}: {self.success_count}/{self.total_count} succeeded, "
            f"{self.failed_count} failed"
        )


class BatchInfo:
    """Represents information about a batch processing operation.

    This class provides access to batch metadata including status, progress,
    and timing information. It's typically obtained from the Batch.info() method
    or the BatchMenu.info() method.

    Attributes:
        id: Unique identifier for the batch.
        status: Current status of the batch (e.g., "in_progress", "completed", "failed").
        created: Unix timestamp when the batch was created.
        total_urls: Total number of URLs in the batch.
        completed_urls: Number of URLs that have been processed.
        country: Country code used for the batch (if specified).
    """

    def __init__(self, response: BatchInfoResponse) -> None:
        """Initialize BatchInfo from API response.

        Args:
            response: Batch info response from API.
        """
        # Copy fields from response to reduce dependency
        self.id = response.id
        self.status = response.status
        self.created = response.created
        self.total_urls = response.total_urls
        self.completed_urls = response.completed_urls
        self.country = response.country

    def __repr__(self) -> str:
        """Return a string representation of the BatchInfo.

        Returns:
            str: String representation showing id, status, progress, and age.
        """
        age_str = f", age={self.age}" if self.created else ""
        return f"BatchInfo(id={self.id!r}, status={self.status!r}, completed={self.completed_urls}/{self.total_urls}{age_str})"

    def __str__(self) -> str:
        """Return a human-readable string representation of the BatchInfo.

        Returns:
            str: Human-readable string showing status and progress.
        """
        return f"BatchInfo: status={self.status}, progress={self.completed_urls}/{self.total_urls}"

    @property
    def age(self) -> str:
        """Get human-readable age of this batch.

        Returns:
            str: Human-readable time delta (e.g., "2h ago", "3d ago").
        """
        return _format_time_delta(self.created)

    @property
    def time_since_start(self) -> float:
        """Get time since batch started in seconds.

        Returns:
            float: Number of seconds since the batch was created.
        """
        now = datetime.now(timezone.utc)
        created_time = datetime.fromtimestamp(self.created / 1000, tz=timezone.utc)
        elapsed = now - created_time
        return elapsed.total_seconds()


class Batch:
    """Represents a batch processing operation for multiple URLs.

    This class provides access to batch operations including status monitoring,
    item iteration, and completion waiting. It supports pagination and filtering
    of batch items. Typically created by the BatchMenu.create() method.

    Attributes:
        id: Unique identifier for the batch.
        status: Current status of the batch (e.g., "in_progress", "completed").
        created: Unix timestamp when the batch was created.
        total_urls: Total number of URLs in the batch.
        completed_urls: Number of URLs that have been processed.
        parser: Parser configuration used for the batch (if any).
        country: Country setting used for the batch (if any).
        start_date: Human-readable start date of the batch.
    """

    def __init__(
        self,
        caller: EndpointCaller,
        response: BatchCreateResponse,
        requested_items: list[dict[str, Any]] | None = None,
    ) -> None:
        """Initialize Batch from API response.

        Args:
            caller: EndpointCaller for making API requests.
            response: Batch creation response from API.
            requested_items: Coerced batch items as they were sent to the API.
                Used to reconcile the summary with the original input.
        """
        self._caller = caller
        self._requested_items = list(requested_items or [])
        # Copy fields from response to reduce dependency
        self.id = response.id
        self.status = str(response.status)
        self.created = response.created
        self.total_urls = response.total_urls
        self.completed_urls = response.completed_urls
        self.parser = response.batch_parser if response.batch_parser else None
        self.country = response.batch_country.value if response.batch_country else None
        self.start_date = response.start_date

    def __repr__(self) -> str:
        """Return a string representation of the Batch.

        Returns:
            str: String representation showing id and total URLs.
        """
        return f"Batch(id={self.id!r}, urls={self.total_urls})"

    def __str__(self) -> str:
        """Return a human-readable string representation of the Batch.

        Returns:
            str: Human-readable string showing id, status, and progress.
        """
        return (
            f"Batch {self.id} [{self.status}] {self.completed_urls}/{self.total_urls}"
        )

    @property
    def requested_items(self) -> list[dict[str, Any]]:
        """The coerced batch items that were sent to the API, in input order."""
        return list(self._requested_items)

    @classmethod
    async def _info(cls, caller: EndpointCaller, batch_id: str) -> BatchInfo:
        """Private class method to get batch information.

        Args:
            caller: EndpointCaller for making API requests.
            batch_id: The ID of the batch to get information for.

        Returns:
            BatchInfo: Current batch status, progress, and metadata.
        """
        c = CONTRACTS[("batch", "info")]
        data: BatchInfoResponse = await caller.invoke(
            c, path_params={"batch_id": batch_id}
        )
        return BatchInfo(data)

    async def info(self) -> BatchInfo:
        """Get current information about the batch.

        Retrieves the latest status, progress, and metadata for this batch.
        Useful for monitoring batch progress and checking completion status.

        Returns:
            BatchInfo: Current batch status, progress, and metadata.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Get current batch information
            info = await batch.info()
            print(f"Status: {info.status}")
            print(f"Progress: {info.completed_urls}/{info.total_urls}")
        """
        return await self._info(self._caller, self.id)

    def items(
        self,
        *,
        batch_size: int = 50,
        status: str | None = None,
        wait_for_completion: bool = True,
    ) -> AsyncIterator[BatchItemResult]:
        """Return an async iterator for elegant pagination over all batch items.

        Returns an async iterator that yields BatchItemResult objects for all items
        in this batch. Handles pagination automatically and can filter by status.
        Optionally waits for batch completion before starting iteration.

        Args:
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
            async for item in batch.items(status="completed"):
                result = await item.retrieve()
                print(f"Retrieved: {item.url}")

            # Get items without waiting for completion
            async for item in batch.items(wait_for_completion=False):
                print(f"Item: {item.url} - {item.retrieve_id}")
        """
        return self._items_async_iterator(
            self._caller,
            self.id,
            batch_size=batch_size,
            status=status,
            wait_for_completion=wait_for_completion,
        )

    @classmethod
    async def _wait_till_done_(
        cls,
        caller: EndpointCaller,
        batch_id: str,
        *,
        check_every_n_secs: int = 10,
        timeout_seconds: int = 600,
    ) -> None:
        """Private static method to wait for batch completion."""
        start_time = datetime.now(timezone.utc)

        # Get initial info for logging
        info = await cls._info(caller, batch_id)
        batch_elapsed = info.time_since_start

        logger.info(
            f"Starting wait_till_done for batch {batch_id}: batch started {batch_elapsed:.2f}s ago, "
            f"monitoring for up to {timeout_seconds}s"
        )

        while True:
            info = await cls._info(caller, batch_id)
            wait_elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

            logger.info(
                f"[BatchInfo] update: id={batch_id} wait={wait_elapsed:.2f}s status={info.status} completed={info.completed_urls}/{info.total_urls}"
            )

            if info.status in ("completed", "failed"):
                logger.info(
                    f"[BatchInfo] finish: id={batch_id} wait={wait_elapsed:.2f}s status={info.status} completed={info.completed_urls}/{info.total_urls}"
                )
                break

            if wait_elapsed >= timeout_seconds:
                logger.error(
                    f"[BatchInfo] id={batch_id} aborted after {wait_elapsed:.2f}s (timeout: {timeout_seconds}s)"
                )
                raise OlostepClientError_Timeout("wait_till_done", timeout_seconds)

            await asyncio.sleep(check_every_n_secs)

    @classmethod
    async def _items_async_iterator(
        cls,
        caller: EndpointCaller,
        batch_id: str,
        *,
        batch_size: int = 50,
        status: str | None = None,
        wait_for_completion: bool = True,
    ) -> AsyncIterator[BatchItemResult]:
        """Internal async iterator that handles pagination automatically."""
        if wait_for_completion:
            await cls._wait_till_done_(caller, batch_id)

        current_cursor = None
        while True:
            c = CONTRACTS[("batch", "items")]
            args: dict[str, Any] = {}
            if current_cursor is None:
                # First request: send only limit
                args["limit"] = batch_size
            else:
                # Subsequent requests: send only cursor (API remembers limit)
                args["cursor"] = current_cursor
            if status is not None:
                args["status"] = status

            data: BatchItemsResponse = await caller.invoke(
                c, path_params={"batch_id": batch_id}, query_params=args
            )

            if not data.items:
                break

            for item_data in data.items:
                yield BatchItemResult(caller, item_data)

            if data.cursor is None:
                logger.debug(
                    f"Pagination for batch {batch_id!r} complete: no more items"
                )
                break
            logger.debug(
                f"Pagination for batch {batch_id!r}: next cursor={data.cursor}"
            )
            current_cursor = data.cursor

    async def wait_till_done(self, *, check_every_n_secs: int = 10) -> None:
        """Wait until the batch is completed or failed.

        Polls the batch status at regular intervals until the batch reaches a
        terminal state (completed or failed). Useful for ensuring all items
        are processed before proceeding.

        Args:
            check_every_n_secs: How often to check batch status in seconds (default: 10).
                More frequent checking uses more API calls but provides faster updates.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Wait for batch completion with default settings
            await batch.wait_till_done()

            # Wait with more frequent status checks
            await batch.wait_till_done(check_every_n_secs=5)
        """
        await self._wait_till_done_(
            self._caller, self.id, check_every_n_secs=check_every_n_secs
        )

    async def summary(
        self,
        *,
        batch_size: int = 50,
        wait_for_completion: bool = True,
        check_every_n_secs: int = 10,
    ) -> BatchSummary:
        """Wait for the batch and return a successful/failed item summary.

        Collects every batch item exactly once and classifies each as successful
        or failed. Failed items keep their URL and custom id and carry a readable
        reason; their ``retrieve()`` raises instead of returning empty content.
        Items the API never reports are still included as failed, so partial
        failures never disappear from the result.

        Args:
            batch_size: Number of items to fetch per API request (default: 50).
            wait_for_completion: Wait for the batch to finish before collecting
                items (default: True).
            check_every_n_secs: Polling interval while waiting for completion.

        Returns:
            BatchSummary: Successful and failed entries plus totals and lookup helpers.

        Examples:
            summary = await batch.summary()
            print(summary.total_count, summary.success_count, summary.failed_count)
            item = summary.get_by_custom_id("news_1")
            content = await item.retrieve(["markdown"])
        """
        items = await self._collect_summary_items(
            self._caller,
            self.id,
            requested_items=self._requested_items,
            batch_size=batch_size,
            wait_for_completion=wait_for_completion,
            check_every_n_secs=check_every_n_secs,
        )
        return BatchSummary(self, items)

    @classmethod
    async def _collect_summary_items(
        cls,
        caller: EndpointCaller,
        batch_id: str,
        *,
        requested_items: list[dict[str, Any]] | None = None,
        local_failures: dict[int, str] | None = None,
        batch_size: int = 50,
        wait_for_completion: bool = True,
        check_every_n_secs: int = 10,
    ) -> list[BatchSummaryItem]:
        """Fetch every batch item and build summary entries, preserving input order."""
        if wait_for_completion:
            await cls._wait_till_done_(
                caller, batch_id, check_every_n_secs=check_every_n_secs
            )

        fetched: list[BatchItemsResponseListItem] = []
        current_cursor = None
        while True:
            c = CONTRACTS[("batch", "items")]
            args: dict[str, Any] = {}
            if current_cursor is None:
                args["limit"] = batch_size
            else:
                args["cursor"] = current_cursor

            data: BatchItemsResponse = await caller.invoke(
                c, path_params={"batch_id": batch_id}, query_params=args
            )
            fetched.extend(data.items)

            if data.cursor is None:
                break
            current_cursor = data.cursor

        return _build_summary_items(
            caller, fetched, requested_items, local_failures=local_failures
        )


class CrawlPage:
    """Represents a single page discovered during a crawl operation.

    Each CrawlPage corresponds to one URL that was discovered and processed
    during a crawl. It provides access to the URL, retrieve ID, and allows
    retrieving the scraped content for that specific page.

    Attributes:
        url: The URL that was crawled.
        retrieve_id: Unique identifier for retrieving the scraped content.
        is_external: Whether this page is external to the crawl domain.
    """

    def __init__(
        self, caller: EndpointCaller, item: CrawlPagesResponseListItem
    ) -> None:
        """Initialize CrawlPage from API response.

        Args:
            caller: EndpointCaller for making API requests.
            item: Crawl page data from API response.
        """
        self._caller = caller
        # Copy fields from item to reduce dependency
        self.url = item.url
        self.retrieve_id = item.retrieve_id
        self.is_external = item.is_external

    def __repr__(self) -> str:
        """Return a string representation of the CrawlPage.

        Returns:
            str: String representation showing url, retrieve_id, and external status.
        """
        return f"CrawlPage(url={self.url!r}, retrieve_id={self.retrieve_id!r}, external={self.is_external})"

    def __str__(self) -> str:
        """Return a human-readable string representation of the CrawlPage.

        Returns:
            str: Human-readable string showing url and external/internal status.
        """
        return (
            f"CrawlPage {self.url} ({'external' if self.is_external else 'internal'})"
        )

    async def retrieve(self, formats: list[str] | None = None) -> ScrapeResult:
        """Retrieve the scraped content for this crawl page.

        Fetches the scraped content for this specific crawl page using its
        retrieve_id. Supports filtering by content formats.

        Args:
            formats: List of content formats to retrieve (e.g., ["html", "markdown"]).
                If None, returns all available formats.

        Returns:
            ScrapeResult: The scraped content in the requested formats.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Retrieve all available formats
            result = await crawl_page.retrieve()

            # Retrieve specific formats
            result = await crawl_page.retrieve(["html", "markdown"])
        """
        c = CONTRACTS[("retrieve", "get")]
        query_params: dict[str, Any] = {"retrieve_id": self.retrieve_id}
        if formats is not None:
            query_params["formats"] = formats
        data: RetrieveResponse = await self._caller.invoke(c, query_params=query_params)
        return ScrapeResult(data)


class CrawlInfo:
    """Represents information about a crawl operation.

    This class provides access to crawl metadata including status, progress,
    and timing information. It's typically obtained from the Crawl.info() method
    or the CrawlMenu.info() method.

    Attributes:
        id: Unique identifier for the crawl.
        status: Current status of the crawl (e.g., "in_progress", "completed", "failed").
        created: Unix timestamp when the crawl was created.
        pages_count: Total number of pages discovered in the crawl.
        current_depth: Current depth of the crawl from the starting URL.
    """

    def __init__(self, response: CrawlInfoResponse) -> None:
        """Initialize CrawlInfo from API response.

        Args:
            response: Crawl info response from API.
        """
        # Copy fields from response to reduce dependency
        self.id = response.id
        self.status = str(response.status)
        self.created = response.created  # start of crawl
        self.pages_count = response.pages_count
        self.current_depth = response.current_depth
        self._last_updated = datetime.now(timezone.utc)

    def __repr__(self) -> str:
        """Return a string representation of the CrawlInfo.

        Returns:
            str: String representation showing id, status, pages count, and depth.
        """
        return f"CrawlInfo(id={self.id!r}, created={self.created}, status={self.status!r}, pages_count={self.pages_count}, current_depth={self.current_depth})"

    def __str__(self) -> str:
        """Return a human-readable string representation of the CrawlInfo.

        Returns:
            str: Human-readable string showing id, age, status, pages count, and depth.
        """
        age_str = f", age={self.age}" if self.created else ""
        return f"CrawlInfo: (id: {self.id!r}{age_str}, status={self.status}, pages_count={self.pages_count}, current_depth={self.current_depth})"

    @property
    def time_since_start(self) -> int:
        """Get time since crawl started in seconds.

        Returns:
            int: Number of seconds since the crawl was created.
        """
        now = datetime.now(timezone.utc)
        created_time = datetime.fromtimestamp(self.created / 1000, tz=timezone.utc)
        elapsed = now - created_time
        return int(elapsed.total_seconds())

    @property
    def time_since_info_update(self) -> int:
        """Get time since last info update in seconds.

        Returns:
            int: Number of seconds since this CrawlInfo object was last updated.
        """
        now = datetime.now(timezone.utc)
        elapsed = now - self._last_updated
        return int(elapsed.total_seconds())

    @property
    def age(self) -> str:
        """Get human-readable age of this crawl.

        Returns:
            str: Human-readable time delta (e.g., "2h ago", "3d ago").
        """
        return _format_time_delta(self.created)


class Crawl:
    """Represents a crawl operation for discovering and processing multiple pages.

    This class provides access to crawl operations including status monitoring,
    page iteration, and completion waiting. It supports pagination and filtering
    of discovered pages. Typically created by the CrawlMenu.create() method.

    Attributes:
        id: Unique identifier for the crawl.
        object: Object type identifier.
        status: Current status of the crawl (e.g., "in_progress", "completed").
        created: Unix timestamp when the crawl was created.
        start_date: Human-readable start date of the crawl.
        start_url: The URL where the crawl started.
        max_pages: Maximum number of pages to crawl (if set).
        max_depth: Maximum crawl depth from start URL (if set).
        exclude_urls: URL patterns to exclude from crawling (if set).
        include_urls: URL patterns to include in crawling (if set).
        include_external: Whether external links are included.
        search_query: Search query used to filter pages (if set).
        top_n: Maximum number of results to return (if set).
        current_depth: Current depth of the crawl from start URL.
        pages_count: Total number of pages discovered so far.
        webhook_url: Webhook URL for notifications (if set).
    """

    def __init__(self, caller: EndpointCaller, response: CreateCrawlResponse) -> None:
        """Initialize Crawl from API response.

        Args:
            caller: EndpointCaller for making API requests.
            response: Crawl creation response from API.
        """
        self._caller = caller
        # Explicitly set all fields from response
        self.id: str = response.id
        self.object: str = response.object
        self.status: CrawlResponseStatus = response.status
        self.created: int = response.created
        self.start_date: str = response.start_date
        self.start_url: str = response.start_url
        self.max_pages: int | None = response.max_pages
        self.max_depth: int | None = response.max_depth
        self.exclude_urls: list[str] | None = response.exclude_urls
        self.include_urls: list[str] | None = response.include_urls
        self.include_external: bool = response.include_external
        self.search_query: str | None = response.search_query
        self.top_n: int | None = response.top_n
        self.current_depth: int | None = response.current_depth
        self.pages_count: int = response.pages_count
        self.webhook_url: str | None = response.webhook_url

    def __repr__(self) -> str:
        """Return a string representation of the Crawl.

        Returns:
            str: String representation showing key crawl parameters.
        """
        return (
            f"Crawl(id={self.id!r}, start_url={self.start_url!r}, "
            f"max_pages={self.max_pages!r}, include_urls={self.include_urls!r}, "
            f"exclude_urls={self.exclude_urls!r}, max_depth={self.max_depth!r}, "
            f"include_external={self.include_external!r}, include_subdomain=None, "
            f"search_query={self.search_query!r}, top_n={self.top_n!r}, "
            f"webhook_url={self.webhook_url!r})"
        )

    def __str__(self) -> str:
        """Return a human-readable string representation of the Crawl.

        Returns:
            str: Human-readable string showing key crawl information.
        """
        return f"Crawl (start_url: {self.start_url!r}, id: {self.id!r}, status: {self.status}, pages_count={self.pages_count}, max_pages: {self.max_pages!r}, max_depth: {self.max_depth!r}, webhook_url: {self.webhook_url!r})"

    @classmethod
    async def _info(cls, caller: EndpointCaller, crawl_id: str) -> CrawlInfo:
        """Private class method to get crawl information.

        Args:
            caller: EndpointCaller for making API requests.
            crawl_id: The ID of the crawl to get information for.

        Returns:
            CrawlInfo: Current crawl status, progress, and metadata.
        """
        c = CONTRACTS[("crawl", "info")]
        data: CrawlInfoResponse = await caller.invoke(
            c, path_params={"crawl_id": crawl_id}
        )
        return CrawlInfo(data)

    async def info(self) -> CrawlInfo:
        """Get current information about the crawl.

        Retrieves the latest status, progress, and metadata for this crawl.
        Useful for monitoring crawl progress and checking completion status.

        Returns:
            CrawlInfo: Current crawl status, progress, and metadata.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Get current crawl information
            info = await crawl.info()
            print(f"Status: {info.status}")
            print(f"Pages discovered: {info.pages_count}")
        """
        return await self._info(self._caller, self.id)

    def pages(
        self,
        *,
        batch_size: int = 50,
        search_query: str | None = None,
        wait_for_completion: bool = True,
    ) -> AsyncIterator[CrawlPage]:
        """Return an async iterator for elegant pagination over all crawl pages.

        Returns an async iterator that yields CrawlPage objects for all pages
        discovered during this crawl. Handles pagination automatically and can filter
        by search query. Optionally waits for crawl completion before starting iteration.

        Args:
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
            async for page in crawl.pages():
                result = await page.retrieve()
                print(f"Retrieved: {page.url}")

            # Get pages matching a search query
            async for page in crawl.pages(search_query="news"):
                print(f"News page: {page.url}")
        """
        return self._pages_async_iterator(
            self._caller,
            self.id,
            batch_size=batch_size,
            search_query=search_query,
            wait_for_completion=wait_for_completion,
        )

    @classmethod
    async def _wait_till_done_(
        cls,
        caller: EndpointCaller,
        crawl_id: str,
        *,
        check_every_n_secs: int = 10,
        timeout_seconds: int = 600,
    ) -> None:
        """Private static method to wait for crawl completion."""
        start_time = datetime.now(timezone.utc)

        # Get initial info for logging
        info = await cls._info(caller, crawl_id)
        crawl_elapsed = info.time_since_start

        logger.info(
            f"Starting wait_till_done for crawl {crawl_id}: crawl started {crawl_elapsed:.2f}s ago, "
            f"monitoring for up to {timeout_seconds}s"
        )

        while True:
            info = await cls._info(caller, crawl_id)
            wait_elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

            logger.info(
                f"[CrawlInfo] update: id={crawl_id} wait={wait_elapsed:.2f}s status={info.status} depth={info.current_depth} pages={info.pages_count}"
            )

            if info.status in ["completed", "failed"]:
                logger.info(
                    f"[CrawlInfo] finish: id={crawl_id} wait={wait_elapsed:.2f}s status={info.status} depth={info.current_depth} pages={info.pages_count}"
                )
                break

            if wait_elapsed >= timeout_seconds:
                logger.error(
                    f"[CrawlInfo] id={crawl_id} aborted after {wait_elapsed:.2f}s (timeout: {timeout_seconds}s)"
                )
                raise OlostepClientError_Timeout("wait_till_done", timeout_seconds)

            await asyncio.sleep(check_every_n_secs)

    @classmethod
    async def _pages_async_iterator(
        cls,
        caller: EndpointCaller,
        crawl_id: str,
        *,
        batch_size: int = 50,
        search_query: str | None = None,
        wait_for_completion: bool = True,
    ) -> AsyncIterator[CrawlPage]:
        """Internal async iterator that handles pagination automatically."""
        if wait_for_completion:
            await cls._wait_till_done_(caller, crawl_id)

        current_cursor = None
        while True:
            c = CONTRACTS[("crawl", "pages")]
            args: dict[str, Any] = {}
            if current_cursor is None:
                # First request: send only limit
                args["limit"] = batch_size
            else:
                # Subsequent requests: send only cursor (API remembers limit)
                args["cursor"] = current_cursor
            if search_query is not None:
                args["search_query"] = search_query
            data: CrawlPagesResponse = await caller.invoke(
                c, path_params={"crawl_id": crawl_id}, query_params=args
            )

            if not data.pages:
                break

            for page_data in data.pages:
                yield CrawlPage(caller, page_data)

            if data.cursor is None:
                logger.debug(
                    f"Pagination for crawl {crawl_id!r} complete: no more pages"
                )
                break
            logger.debug(
                f"Pagination for crawl {crawl_id!r}: next cursor={data.cursor}"
            )
            current_cursor = data.cursor

    async def wait_till_done(
        self, *, check_every_n_secs: int = 10, timeout_seconds: int = 600
    ) -> None:
        """Wait until the crawl is completed or failed.

        Polls the crawl status at regular intervals until the crawl reaches a
        terminal state (completed or failed). Useful for ensuring all pages
        are discovered before proceeding.

        Args:
            check_every_n_secs: How often to check crawl status in seconds (default: 10).
                More frequent checking uses more API calls but provides faster updates.
            timeout_seconds: Maximum time to wait in seconds (default: 600 seconds / 10 minutes).
                If the crawl doesn't complete within this time, a timeout error is raised.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Wait for crawl completion with default settings
            await crawl.wait_till_done()

            # Wait with more frequent status checks and longer timeout
            await crawl.wait_till_done(check_every_n_secs=5, timeout_seconds=1200)
        """
        await self._wait_till_done_(
            self._caller,
            self.id,
            check_every_n_secs=check_every_n_secs,
            timeout_seconds=timeout_seconds,
        )


class Sitemap:
    """Represents a sitemap operation for extracting links from a website.

    This class provides access to sitemap operations including link extraction,
    pagination, and filtering. It supports pagination for large sitemaps and
    provides methods for iterating over discovered URLs. Typically created by
    the SitemapMenu.__call__() method.

    Attributes:
        id: Unique identifier for the sitemap (if available).
        initial_urls_count: Total number of URLs discovered in the initial response.
        cursor: Pagination cursor for retrieving more URLs (if available).
    """

    def __init__(self, caller: EndpointCaller, response: MapResponse, url: str) -> None:
        """Initialize Sitemap from API response.

        Args:
            caller: EndpointCaller for making API requests.
            response: Map response from API.
            url: Original URL used to create the sitemap (required for pagination).

        Note:
            The original URL is required for pagination because the API needs it
            when fetching subsequent pages with cursor-based pagination. Without
            the URL, pagination requests fail with validation errors.
        """
        self._caller = caller
        # Copy fields from response to reduce dependency
        self.id = response.id or ""
        self._initial_urls = response.urls
        self.initial_urls_count = response.urls_count
        self.cursor = response.cursor or ""
        self._original_url = url  # Store original URL for pagination

    def __repr__(self) -> str:
        """Return a string representation of the Sitemap.

        Returns:
            str: String representation showing id, initial URLs count, and cursor.
        """
        return f"Sitemap(id={self.id!r}, initial_urls_count={self.initial_urls_count}, cursor={self.cursor!r})"

    def __str__(self) -> str:
        """Return a human-readable string representation of the Sitemap.

        Returns:
            str: Human-readable string showing id, initial URLs count, and cursor status.
        """
        return f"Sitemap {self.id or '-'} initial_urls_count={self.initial_urls_count} (cursor={'set' if self.cursor else 'none'})"

    async def urls(self) -> AsyncIterator[str]:
        """Return an async iterator for all sitemap URLs.

        This method automatically handles pagination, yielding each URL
        individually for seamless iteration over large sitemaps.

        Yields:
            str: Individual URLs from the sitemap.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Get all URLs from the sitemap
            async for url in sitemap.urls():
                print(f"Found URL: {url}")
        """
        async for url in self._urls_async_iterator(self._caller, self):
            yield url

    @classmethod
    async def _urls_async_iterator(
        cls, caller: EndpointCaller, sitemap: "Sitemap"
    ) -> AsyncIterator[str]:
        """Internal async iterator that handles pagination automatically."""
        current_sitemap = sitemap

        while True:
            # Yield all URLs from current sitemap
            for url in current_sitemap._initial_urls:
                yield url

            # Check if there are more URLs to fetch
            if not current_sitemap.cursor:
                logger.debug("Pagination for sitemap complete: no more URLs")
                break

            # Fetch next batch using cursor and original URL
            logger.debug(
                f"Pagination for sitemap: next cursor={current_sitemap.cursor}"
            )
            c = CONTRACTS[("map", "create")]
            req = {
                "cursor": current_sitemap.cursor,
                "url": current_sitemap._original_url,
            }
            data: MapResponse = await caller.invoke(c, body_params=req)
            current_sitemap = Sitemap(caller, data, current_sitemap._original_url)


class MonitorResult:
    """Result object for a single monitor (create, get, update, pause, resume, delete).

    Attributes:
        id: Monitor identifier (starts with ``monitor_``).
        object: Always ``"monitor"``.
        query: Natural-language query describing what to watch.
        status: One of ``provisioning``, ``active``, ``paused``, ``failed``, ``deleted``.
        schedule: Schedule config including frequency, cron, and next_run_at.
        notification: Notification channels and event triggers.
        webhook: Webhook configuration (if set).
        output_schema: JSON Schema for structured extraction (if set).
        metadata: User-defined key/value labels.
        last_run: Most recent run summary (GET only; None on create/update).
        total_count: Total snapshot events (GET only; None on create/update).
        created: Unix-second creation timestamp.
        updated: Unix-second last-updated timestamp.
        error_message: Set when status is ``failed``.
    """

    def __init__(self, response: MonitorResponse) -> None:
        self.id = response.id
        self.object = response.object
        self.query = response.query
        self.status = response.status
        self.tracked = response.tracked
        self.source_policy = response.source_policy
        self.schedule = response.schedule
        self.notification = response.notification
        self.webhook = response.webhook
        self.output_schema = response.output_schema
        self.metadata = response.metadata or {}
        self.agent = response.agent
        self.last_run = response.last_run
        self.total_count = response.total_count
        self.mermaid_diagram = response.mermaid_diagram
        self.error_message = response.error_message
        self.created = response.created
        self.updated = response.updated

    def __repr__(self) -> str:
        return (
            f"MonitorResult(id={self.id!r}, status={self.status!r}, "
            f"query={self.query[:50]!r}{'...' if len(self.query) > 50 else ''})"
        )

    def __str__(self) -> str:
        freq = ""
        if self.schedule and self.schedule.frequency:
            freq = f", frequency={self.schedule.frequency!r}"
        return f"Monitor {self.id} [{self.status}]{freq}: {self.query[:60]}"


class MonitorDeleteResult:
    """Result object for DELETE /monitors/{id}.

    Delete returns a confirmation, not the monitor itself.

    Attributes:
        monitor_id: The deleted monitor's identifier.
        message: Human-readable confirmation message from the API.
    """

    def __init__(self, response: MonitorDeleteResponse) -> None:
        self.monitor_id = response.monitor_id
        self.message = response.message

    def __repr__(self) -> str:
        return f"MonitorDeleteResult(monitor_id={self.monitor_id!r})"

    def __str__(self) -> str:
        return f"Monitor {self.monitor_id} deleted: {self.message}"


class MonitorListResult:
    """Result object for GET /monitors (list).

    Attributes:
        monitors: List of MonitorResult objects.
        count: Total number of monitors returned.
    """

    def __init__(self, response: MonitorListResponse) -> None:
        self.monitors = [MonitorResult(m) for m in response.monitors]
        self.count = response.count

    def __repr__(self) -> str:
        return f"MonitorListResult(count={self.count})"

    def __iter__(self):
        return iter(self.monitors)

    def __len__(self) -> int:
        return len(self.monitors)


class MonitorEventResult:
    """Result object for GET /monitors/{id}/events.

    Attributes:
        data: List of event dicts with id, run_id, created, changed, summary, snapshot_url.
        has_more: True when more events exist beyond this page.
        next_cursor: Cursor for the next page (pass as ``cursor=`` in the next call).
        total_count: Total snapshot count; only present on the first page or count_only=True.
    """

    def __init__(self, response: MonitorEventsResponse) -> None:
        self.data = [e.model_dump(exclude_none=True) for e in response.data]
        self.has_more = response.has_more
        self.next_cursor = response.next_cursor
        self.total_count = response.total_count

    def __repr__(self) -> str:
        more = ", has_more=True" if self.has_more else ""
        return f"MonitorEventResult(events={len(self.data)}{more})"

    def __iter__(self):
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)


def _format_time_delta(timestamp: int) -> str:
    """Format a Unix timestamp as a human-readable time delta."""
    if not timestamp:
        return "unknown"

    try:
        created_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        delta = now - created_time

        if delta.days > 0:
            return f"{delta.days}d ago"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours}h ago"
        elif delta.seconds > 60:
            minutes = delta.seconds // 60
            return f"{minutes}m ago"
        else:
            return f"{delta.seconds}s ago"
    except (ValueError, OSError):
        return "invalid"
