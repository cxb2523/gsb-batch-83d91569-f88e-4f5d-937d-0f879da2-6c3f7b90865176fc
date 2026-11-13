"""
Monitor operations for scheduled page watching and change detection.
"""

from __future__ import annotations

from typing import Any

from .._log import get_logger
from ..backend.api_endpoints import (
    MONITOR_CREATE,
    MONITOR_DELETE,
    MONITOR_EVENTS,
    MONITOR_GET,
    MONITOR_LIST,
    MONITOR_PAUSE,
    MONITOR_RESUME,
    MONITOR_UPDATE,
)
from ..backend.caller import EndpointCaller
from ..frontend.client_state import (
    MonitorDeleteResult,
    MonitorEventResult,
    MonitorListResult,
    MonitorResult,
)

logger = get_logger("frontend.monitor_menu")


class MonitorMenu:
    """Monitor operations for scheduled web watching and change alerts.

    Set up a monitor from a natural-language query. Olostep visits the target on
    a schedule, detects changes, and can notify you by email, Slack, SMS, or
    webhook. The monitor starts as ``status: provisioning`` and transitions to
    ``active`` once the backing schedule is ready (usually within a minute).
    """

    def __init__(self, caller: EndpointCaller) -> None:
        self._caller = caller

    async def create(
        self,
        query: str,
        *,
        frequency: str | None = None,
        source_policy: dict[str, Any] | None = None,
        notification: dict[str, Any] | None = None,
        webhook: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> MonitorResult:
        """Create a recurring web monitor.

        Provisions a shadow agent, generates a workflow spec, queues DAG planning,
        and schedules recurring runs. Returns immediately with ``status: provisioning``;
        the monitor becomes ``active`` once setup completes (usually within a minute).

        Args:
            query: Natural-language description of what to watch. Required.
                Example: ``"Alert me when the price of this product drops below $50"``
            frequency: How often to run. Accepts natural language such as
                ``"every hour"``, ``"every day at 9am"``, or ``"every 30 minutes"``.
                Minimum interval is 10 minutes. Defaults to ``"every hour"``.
            source_policy: Controls which URLs are fetched on each run. Supports
                ``include_urls``, ``exclude_urls``, ``include_domains``,
                ``exclude_domains`` (all optional string lists).
            notification: Where to send alerts. Supports ``events`` (list of
                ``"changed"`` and/or ``"first_snapshot"``) and ``channels``
                (list of ``{"type": "email"|"slack"|"sms", "target": "..."}``).
            webhook: HTTPS endpoint that receives a POST on each run.
                Pass ``{"url": "https://your-endpoint.example.com/hook"}``.
                Payloads are not signed.
            output_schema: Optional JSON Schema for structured extraction from
                the monitored page.
            metadata: Key/value labels for tagging this monitor.

        Returns:
            MonitorResult: The newly created monitor (status will be ``provisioning``).

        Examples:
            # Minimal — just a query
            monitor = await client.monitors.create(
                "Watch the Stripe status page for incidents"
            )

            # With notification and schedule
            monitor = await client.monitors.create(
                "Has the pricing on stripe.com changed?",
                frequency="every day at 8am",
                source_policy={"include_urls": ["https://stripe.com/pricing"]},
                notification={
                    "channels": [{"type": "email", "target": "you@example.com"}]
                },
            )
        """
        body: dict[str, Any] = {"query": query}
        if frequency is not None:
            body["frequency"] = frequency
        if source_policy is not None:
            body["source_policy"] = source_policy
        if notification is not None:
            body["notification"] = notification
        if webhook is not None:
            body["webhook"] = webhook
        if output_schema is not None:
            body["output_schema"] = output_schema
        if metadata is not None:
            body["metadata"] = metadata

        from ..models.response import MonitorResponse

        data: MonitorResponse = await self._caller.invoke(
            MONITOR_CREATE, body_params=body
        )
        return MonitorResult(data)

    async def list(
        self,
        *,
        include_deleted: bool = False,
    ) -> MonitorListResult:
        """List all monitors for this API key.

        Args:
            include_deleted: When True, soft-deleted monitors are included.

        Returns:
            MonitorListResult: Wrapper with ``.monitors`` list and ``.count``.
        """
        query: dict[str, Any] = {}
        if include_deleted:
            query["include_deleted"] = "true"

        from ..models.response import MonitorListResponse

        data: MonitorListResponse = await self._caller.invoke(
            MONITOR_LIST, query_params=query
        )
        return MonitorListResult(data)

    async def get(
        self,
        monitor_id: str,
        *,
        include_total_count: bool = True,
        include_diagram: bool = False,
    ) -> MonitorResult:
        """Retrieve a single monitor by ID.

        Args:
            monitor_id: The monitor ID (starts with ``"monitor_"``).
            include_total_count: Whether to include the total snapshot count
                in the response. Defaults to True.
            include_diagram: When True, the response includes a ``mermaid_diagram``
                string for the monitor's workflow DAG.

        Returns:
            MonitorResult: The monitor with ``last_run`` and optionally ``total_count``.
        """
        query: dict[str, Any] = {}
        if not include_total_count:
            query["include_total_count"] = "false"
        if include_diagram:
            query["include-diagram"] = "true"

        from ..models.response import MonitorResponse

        data: MonitorResponse = await self._caller.invoke(
            MONITOR_GET,
            path_params={"monitor_id": monitor_id},
            query_params=query or None,
        )
        return MonitorResult(data)

    _UNSET = object()  # sentinel for "not provided" vs explicit None

    async def update(
        self,
        monitor_id: str,
        *,
        frequency: str | None = None,
        notification: dict[str, Any] | None = None,
        webhook: dict[str, Any] | None = _UNSET,  # type: ignore[assignment]
        metadata: dict[str, str] | None = None,
    ) -> MonitorResult:
        """Update a monitor's settings.

        Only the four mutable fields are accepted: ``frequency``, ``notification``,
        ``webhook``, and ``metadata``. Any other keys are silently ignored by the API.
        Changing ``frequency`` recreates the underlying EventBridge schedule.
        Pass ``webhook=None`` explicitly to remove a previously configured webhook.

        Args:
            monitor_id: The monitor ID to update.
            frequency: New schedule in natural language (e.g., ``"every 4 hours"``).
            notification: Replacement notification config.
            webhook: Replacement webhook config. Pass ``None`` explicitly to remove
                an existing webhook. Omit entirely to leave the webhook unchanged.
            metadata: Metadata patch — empty-string values delete individual keys.

        Returns:
            MonitorResult: The updated monitor.
        """
        body: dict[str, Any] = {}
        if frequency is not None:
            body["frequency"] = frequency
        if notification is not None:
            body["notification"] = notification
        if webhook is not MonitorMenu._UNSET:
            # Include webhook whether it is a dict (set/replace) or None (remove).
            body["webhook"] = webhook
        if metadata is not None:
            body["metadata"] = metadata

        from ..models.response import MonitorResponse

        data: MonitorResponse = await self._caller.invoke(
            MONITOR_UPDATE,
            path_params={"monitor_id": monitor_id},
            body_params=body,
        )
        return MonitorResult(data)

    async def pause(
        self,
        monitor_id: str,
    ) -> MonitorResult:
        """Pause a monitor, disabling future scheduled runs.

        Args:
            monitor_id: The monitor ID to pause.

        Returns:
            MonitorResult: The monitor with ``status: paused``.
        """
        from ..models.response import MonitorResponse

        data: MonitorResponse = await self._caller.invoke(
            MONITOR_PAUSE,
            path_params={"monitor_id": monitor_id},
        )
        return MonitorResult(data)

    async def resume(
        self,
        monitor_id: str,
    ) -> MonitorResult:
        """Resume a paused monitor, re-enabling scheduled runs.

        Args:
            monitor_id: The monitor ID to resume.

        Returns:
            MonitorResult: The monitor with ``status: active``.
        """
        from ..models.response import MonitorResponse

        data: MonitorResponse = await self._caller.invoke(
            MONITOR_RESUME,
            path_params={"monitor_id": monitor_id},
        )
        return MonitorResult(data)

    async def delete(
        self,
        monitor_id: str,
    ) -> MonitorDeleteResult:
        """Soft-delete a monitor and remove its schedule and shadow agent.

        The monitor is excluded from list results unless ``include_deleted=True``
        is passed. The API returns a confirmation, not the monitor object.

        Args:
            monitor_id: The monitor ID to delete.

        Returns:
            MonitorDeleteResult: The deleted monitor's ID and a confirmation message.
        """
        from ..models.response import MonitorDeleteResponse

        data: MonitorDeleteResponse = await self._caller.invoke(
            MONITOR_DELETE,
            path_params={"monitor_id": monitor_id},
        )
        return MonitorDeleteResult(data)

    async def events(
        self,
        monitor_id: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        count_only: bool = False,
    ) -> MonitorEventResult:
        """List snapshot events for a monitor, newest first.

        Each event records whether a change was detected on that run, along
        with a summary and a pre-signed URL to the snapshot content.

        Args:
            monitor_id: The monitor ID to fetch events for.
            limit: Number of events to return (1–100). Default: 25.
            cursor: Pagination cursor from a previous response's ``next_cursor`` field.
            count_only: When True, returns only ``total_count`` without event data.

        Returns:
            MonitorEventResult: Wrapper with ``.data`` list, ``.has_more``,
                ``.next_cursor``, and ``.total_count``.
        """
        query: dict[str, Any] = {}
        if limit is not None:
            query["limit"] = limit
        if cursor is not None:
            query["cursor"] = cursor
        if count_only:
            query["count_only"] = "true"

        from ..models.response import MonitorEventsResponse

        data: MonitorEventsResponse = await self._caller.invoke(
            MONITOR_EVENTS,
            path_params={"monitor_id": monitor_id},
            query_params=query or None,
        )
        return MonitorEventResult(data)
