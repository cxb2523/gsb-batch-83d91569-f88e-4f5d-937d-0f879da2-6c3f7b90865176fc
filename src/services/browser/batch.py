"""Batch text extraction over the page-control channel of a running profile.

For each target the service reuses the existing control actions of the running
browser (no new browser process): open a fresh tab, navigate, wait for a
selector, read its text, close the tab. Every target gets its own tab so no
page state leaks from one target to the next, and one failing target never
stops the batch.

Results of recent batches are kept in memory (per profile, bounded) so callers
can fetch them later and so a re-run with ``skip_succeeded`` can mark targets
that already succeeded instead of fetching them again.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ...core.logging import get_logger
from .launcher import BrowserControlError

if TYPE_CHECKING:
    from ...interfaces import IBrowserLauncher

logger = get_logger("browser.batch")

# Failure classifications reported per target.
PROXY_OR_NETWORK_UNREACHABLE = "proxy_or_network_unreachable"
WAIT_TIMEOUT = "wait_timeout"
SCRIPT_ERROR = "script_error"
INVALID_PARAMS = "invalid_params"

# Per-target result statuses.
SUCCESS = "success"
FAILED = "failed"
SKIPPED = "skipped"

# How many batch records are kept per profile for later retrieval / skipping.
MAX_BATCHES_PER_PROFILE = 20

# Extra seconds the control channel is given beyond the element wait itself.
_CONTROL_TIMEOUT_SLACK = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _classify(phase: str, error: BrowserControlError) -> str:
    """Map a control-channel failure to one of the reported error kinds."""
    message = str(error)
    if error.status == 400:
        # The control server rejects bad URLs and bad parameters with 400.
        return INVALID_PARAMS
    if phase == "navigate":
        # goto() only fails on network-level problems: dead proxy, DNS,
        # refused connection, navigation timeout.
        return PROXY_OR_NETWORK_UNREACHABLE
    if phase == "wait":
        if message.startswith("TimeoutError"):
            return WAIT_TIMEOUT
        if "selector" in message.lower():
            return INVALID_PARAMS
    return SCRIPT_ERROR


class BatchExtractService:
    """Runs batch extractions on running profiles and remembers the results."""

    def __init__(self, launcher: IBrowserLauncher) -> None:
        self._launcher = launcher
        self._lock = threading.Lock()
        self._batches: dict[str, list[dict[str, Any]]] = {}
        self._running: dict[str, threading.Lock] = {}

    # --- public API ---------------------------------------------------------

    def run(self, profile_name: str, request: dict[str, Any]) -> dict[str, Any]:
        """Run a whole batch and return its record. Raises BrowserControlError
        before anything starts when the batch cannot run at all."""
        targets = request["targets"]
        if not targets:
            raise BrowserControlError("Target list is empty", status=400)
        ids = [t["id"] for t in targets]
        if len(set(ids)) != len(ids):
            raise BrowserControlError("Target ids must be unique", status=400)
        if not self._launcher.is_running(profile_name):
            raise BrowserControlError("Browser is not running", status=409)

        with self._lock:
            lock = self._running.setdefault(profile_name, threading.Lock())
        if not lock.acquire(blocking=False):
            raise BrowserControlError("A batch is already running for this profile", status=409)
        try:
            return self._run_locked(profile_name, request)
        finally:
            lock.release()

    def latest(self, profile_name: str) -> dict[str, Any] | None:
        with self._lock:
            batches = self._batches.get(profile_name) or []
            return batches[-1] if batches else None

    def get(self, profile_name: str, batch_id: str) -> dict[str, Any] | None:
        with self._lock:
            for batch in self._batches.get(profile_name) or []:
                if batch["batch_id"] == batch_id:
                    return batch
        return None

    # --- internals ----------------------------------------------------------

    def _run_locked(self, profile_name: str, request: dict[str, Any]) -> dict[str, Any]:
        record: dict[str, Any] = {
            "batch_id": uuid.uuid4().hex[:12],
            "profile": profile_name,
            "started_at": _now(),
            "finished_at": None,
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "results": [],
        }
        succeeded_before = self._succeeded_ids(profile_name) if request["skip_succeeded"] else {}
        for target in request["targets"]:
            previous = succeeded_before.get(target["id"])
            if previous is not None:
                result = self._result_shell(target, request)
                result["status"] = SKIPPED
                result["reason"] = f"already succeeded in batch {previous}"
            else:
                result = self._extract_one(profile_name, target, request)
            record["results"].append(result)
        record["total"] = len(record["results"])
        record["succeeded"] = sum(r["status"] == SUCCESS for r in record["results"])
        record["failed"] = sum(r["status"] == FAILED for r in record["results"])
        record["skipped"] = sum(r["status"] == SKIPPED for r in record["results"])
        record["finished_at"] = _now()
        with self._lock:
            batches = self._batches.setdefault(profile_name, [])
            batches.append(record)
            del batches[:-MAX_BATCHES_PER_PROFILE]
        logger.info(
            "Batch %s for %s: %d ok, %d failed, %d skipped",
            record["batch_id"],
            profile_name,
            record["succeeded"],
            record["failed"],
            record["skipped"],
        )
        return record

    def _succeeded_ids(self, profile_name: str) -> dict[str, str]:
        """Target id -> batch id for every target that ever succeeded here."""
        succeeded: dict[str, str] = {}
        with self._lock:
            batches = list(self._batches.get(profile_name) or [])
        for batch in batches:
            for result in batch["results"]:
                if result["status"] == SUCCESS:
                    succeeded[result["id"]] = batch["batch_id"]
        return succeeded

    @staticmethod
    def _result_shell(target: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": target["id"],
            "url": target["url"],
            "selector": target.get("selector") or request["selector"],
            "status": None,
            "error_kind": None,
            "error": None,
            "reason": None,
            "text": None,
            "truncated": False,
        }

    def _extract_one(
        self,
        profile_name: str,
        target: dict[str, Any],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._result_shell(target, request)
        selector = result["selector"]
        wait_ms = target.get("timeout") or request["timeout"]
        max_chars = target.get("max_chars") or request["max_chars"]
        tab_index: int | None = None
        phase = "open_tab"
        try:
            tabs = self._launcher.control(profile_name, "tab_new")
            tab_index = next(t["index"] for t in tabs["tabs"] if t["active"])
            phase = "navigate"
            self._launcher.control(profile_name, "navigate", {"url": target["url"]})
            phase = "wait"
            self._launcher.control(
                profile_name,
                "wait_for",
                {"selector": selector, "timeout": wait_ms},
                timeout=wait_ms / 1000 + _CONTROL_TIMEOUT_SLACK,
            )
            phase = "extract"
            extracted = self._launcher.control(
                profile_name, "text", {"selector": selector, "max_chars": max_chars}
            )
            result["status"] = SUCCESS
            result["text"] = extracted["text"]
            result["truncated"] = extracted["truncated"]
        except BrowserControlError as e:
            result["status"] = FAILED
            result["error_kind"] = _classify(phase, e)
            result["error"] = str(e)
        finally:
            if tab_index is not None:
                try:
                    self._launcher.control(profile_name, "tab_close", {"index": tab_index})
                except BrowserControlError:
                    logger.warning("Could not close batch tab %s for %s", tab_index, profile_name)
        return result
