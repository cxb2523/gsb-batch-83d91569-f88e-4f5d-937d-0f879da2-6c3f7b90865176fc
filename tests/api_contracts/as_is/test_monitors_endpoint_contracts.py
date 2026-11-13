"""
Monitor endpoint contract tests.

Validates that the monitors API responses parse cleanly into the SDK models.
These are contract tests (shape/type checks) using fixtures, not live API calls.
"""

from __future__ import annotations

import pytest

from olostep.backend.api_endpoints import (
    MONITOR_CREATE,
    MONITOR_DELETE,
    MONITOR_EVENTS,
    MONITOR_GET,
    MONITOR_LIST,
    MONITOR_PAUSE,
    MONITOR_RESUME,
    MONITOR_UPDATE,
)
from olostep.frontend.client_state import (
    MonitorEventResult,
    MonitorListResult,
    MonitorResult,
)
from olostep.models.response import (
    MonitorEventsResponse,
    MonitorListResponse,
    MonitorResponse,
)
from tests.fixtures.api.responses.monitors import (
    MONITOR_CREATE_RESPONSE,
    MONITOR_EVENTS_RESPONSE,
    MONITOR_GET_RESPONSE,
    MONITOR_LIST_RESPONSE,
)


class TestMonitorResponseParsing:
    """Validate that fixture data parses into the SDK models without errors."""

    def test_create_response_parses(self):
        r = MonitorResponse.model_validate(MONITOR_CREATE_RESPONSE)
        assert r.id == "monitor_abc1234567"
        assert r.status == "provisioning"
        assert r.query == "Watch the Stripe status page for incidents"
        assert r.last_run is None
        assert r.total_count is None

    def test_get_response_parses(self):
        r = MonitorResponse.model_validate(MONITOR_GET_RESPONSE)
        assert r.status == "active"
        assert r.last_run is not None
        assert r.last_run.change_detected is False
        assert r.last_run.status == "completed"
        assert r.total_count == 5

    def test_list_response_parses(self):
        r = MonitorListResponse.model_validate(MONITOR_LIST_RESPONSE)
        assert r.count == 1
        assert len(r.monitors) == 1
        assert r.monitors[0].id == "monitor_abc1234567"

    def test_events_response_parses(self):
        r = MonitorEventsResponse.model_validate(MONITOR_EVENTS_RESPONSE)
        assert len(r.data) == 1
        assert r.data[0].id == "run_xyz789"
        assert r.data[0].changed is False
        assert r.total_count == 5
        assert r.has_more is False
        assert r.next_cursor is None


class TestMonitorResultWrappers:
    """Validate MonitorResult, MonitorListResult, MonitorEventResult convenience classes."""

    def test_monitor_result_from_create(self):
        r = MonitorResponse.model_validate(MONITOR_CREATE_RESPONSE)
        result = MonitorResult(r)
        assert result.id == "monitor_abc1234567"
        assert result.status == "provisioning"
        assert result.metadata == {}
        assert "monitor_abc1234567" in repr(result)

    def test_monitor_result_from_get(self):
        r = MonitorResponse.model_validate(MONITOR_GET_RESPONSE)
        result = MonitorResult(r)
        assert result.status == "active"
        assert result.last_run is not None
        assert result.total_count == 5

    def test_monitor_list_result(self):
        r = MonitorListResponse.model_validate(MONITOR_LIST_RESPONSE)
        result = MonitorListResult(r)
        assert result.count == 1
        assert len(result) == 1
        monitors = list(result)
        assert monitors[0].id == "monitor_abc1234567"

    def test_monitor_event_result(self):
        r = MonitorEventsResponse.model_validate(MONITOR_EVENTS_RESPONSE)
        result = MonitorEventResult(r)
        assert len(result) == 1
        assert result.has_more is False
        assert result.next_cursor is None
        assert result.total_count == 5
        events = list(result)
        assert events[0]["id"] == "run_xyz789"
        assert events[0]["changed"] is False


class TestMonitorEndpointContracts:
    """Smoke-test endpoint contract definitions."""

    def test_all_monitor_contracts_have_keys(self):
        contracts = [
            MONITOR_CREATE,
            MONITOR_LIST,
            MONITOR_GET,
            MONITOR_UPDATE,
            MONITOR_DELETE,
            MONITOR_PAUSE,
            MONITOR_RESUME,
            MONITOR_EVENTS,
        ]
        for c in contracts:
            assert c.key[0] == "monitor"
            assert c.method in ("GET", "POST", "DELETE")
            assert "/monitors" in c.path
            assert c.response_model is not None

    def test_monitor_id_path_param(self):
        for c in [MONITOR_GET, MONITOR_UPDATE, MONITOR_DELETE, MONITOR_PAUSE, MONITOR_RESUME, MONITOR_EVENTS]:
            assert "monitor_id" in c.path_parameters, f"{c.key} missing monitor_id in path"

    def test_create_and_list_have_no_path_params(self):
        assert MONITOR_CREATE.path_parameters == []
        assert MONITOR_LIST.path_parameters == []
