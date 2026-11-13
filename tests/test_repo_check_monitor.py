"""Offline tests for the private APT repository freshness collector.

These tests never run apt, never touch the network, and never read the host's
real APT configuration. Every external dependency of RepoCheckMonitor is
injected: the command runner, the architecture list, and the source
configuration signature. The cache root is always a fresh temporary directory.
"""

import fcntl
import importlib.util
import json
import os
import sys
import threading
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if importlib.util.find_spec("psutil") is None:  # pragma: no cover
    # systempi imports psutil at module scope for unrelated dashboard metrics.
    # The repository collector under test never calls it, so a stub keeps these
    # tests runnable on a bare interpreter.
    sys.modules["psutil"] = types.ModuleType("psutil")

import systempi  # noqa: E402


ARCHITECTURES = ["arm64"]
SIGNATURE = "signature-a"


def upgradable_output(names):
    return "".join(f"{name}/stable 1.0 arm64 [upgradable from: 0.9]\n" for name in names)


def result_payload(generation_path):
    with open(generation_path / "result.json", "r", encoding="utf-8") as fh:
        return json.load(fh)


class FakeCommandRunner:
    """Records every invocation and replays scripted outcomes.

    Each scripted step is a dict with optional keys:
      returncode, stdout, stderr, timed_out, cancelled, before (callable).
    Once the script is exhausted the last step repeats, which keeps the
    background loop tests from spinning without a defined answer.
    """

    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    def __call__(self, args, stop_event, timeout):
        self.calls.append(list(args))
        index = min(len(self.calls) - 1, len(self.steps) - 1)
        step = self.steps[index]
        hook = step.get("before")
        if hook is not None:
            hook()
        return (
            step.get("returncode", 0),
            step.get("stdout", ""),
            step.get("stderr", ""),
            step.get("timed_out", False),
            step.get("cancelled", False),
        )


def ok_step(names):
    return {"returncode": 0, "stdout": upgradable_output(names)}


def make_monitor(cache_root, runner, signature=SIGNATURE, architectures=None):
    architectures = list(architectures or ARCHITECTURES)
    return systempi.RepoCheckMonitor(
        cache_root=cache_root,
        interval=3600,
        retry_interval=60,
        timeout=5,
        command_runner=runner,
        architecture_provider=lambda: list(architectures),
        signature_provider=lambda _arches, sig=signature: sig,
        command_probe=lambda _name: "/usr/bin/fake",
    )


def current_target(cache_root):
    return os.readlink(cache_root / "current")


def generation_entries(cache_root):
    generations = cache_root / "generations"
    if not generations.is_dir():
        return []
    return sorted(path.name for path in generations.iterdir() if path.is_dir())


@pytest.fixture()
def cache_root(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    return root


def test_successful_refresh_writes_result_and_switches_current(cache_root):
    runner = FakeCommandRunner([
        ok_step([]),                      # apt-get update
        ok_step(["curl", "wget", "git"]),  # apt list --upgradable
    ])
    monitor = make_monitor(cache_root, runner)

    outcome = monitor._refresh_once()

    assert outcome == systempi.REPO_REFRESH_SUCCESS
    assert monitor.get_last_outcome() == systempi.REPO_REFRESH_SUCCESS
    assert monitor.get_status() == "3 available"

    generation = systempi.current_generation_path(cache_root)
    assert generation is not None
    payload = result_payload(generation)
    assert payload["schema"] == 1
    assert payload["update_count"] == 3
    assert payload["source_signature"] == SIGNATURE
    assert payload["architectures"] == ARCHITECTURES
    assert systempi.parse_utc_timestamp(payload["success_utc"]) is not None
    assert payload["success_utc"].endswith("Z")

    # The new generation is the only one left behind; older ones are pruned.
    assert generation_entries(cache_root) == [generation.name]
    assert current_target(cache_root) == os.path.join("generations", generation.name)


def test_successful_refresh_replaces_previous_generation(cache_root):
    runner = FakeCommandRunner([ok_step([]), ok_step(["a"])])
    monitor = make_monitor(cache_root, runner)
    assert monitor._refresh_once() == systempi.REPO_REFRESH_SUCCESS
    first = systempi.current_generation_path(cache_root)

    # A stray generation from an interrupted run must not survive the refresh.
    stray = cache_root / "generations" / "19990101T000000Z-stray"
    systempi.ensure_generation_layout(stray)

    monitor = make_monitor(cache_root, FakeCommandRunner([ok_step([]), ok_step(["a", "b"])]))
    assert monitor._refresh_once() == systempi.REPO_REFRESH_SUCCESS
    second = systempi.current_generation_path(cache_root)

    assert second != first
    assert result_payload(second)["update_count"] == 2
    # The current generation plus the one it was seeded from are the only ones
    # kept; everything else (including the stray) is pruned.
    assert generation_entries(cache_root) == sorted([first.name, second.name])
    assert "19990101T000000Z-stray" not in generation_entries(cache_root)
    assert current_target(cache_root) == os.path.join("generations", second.name)


def test_failure_keeps_previous_count_and_marks_it_stale(cache_root):
    runner = FakeCommandRunner([
        ok_step([]),
        ok_step(["curl", "wget"]),
        {"returncode": 100, "stderr": "temporary failure resolving archive"},
    ])
    monitor = make_monitor(cache_root, runner)
    assert monitor._refresh_once() == systempi.REPO_REFRESH_SUCCESS
    assert monitor.get_status() == "2 available"

    # Age the successful timestamp so the stale label carries a visible age.
    with monitor._lock:
        monitor._success_utc = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat().replace("+00:00", "Z")

    outcome = monitor._refresh_once()
    assert outcome == systempi.REPO_REFRESH_FAILURE
    assert monitor.get_last_outcome() == systempi.REPO_REFRESH_FAILURE

    status = monitor.get_status()
    assert "2 cached" in status
    assert "old" in status
    assert "failed" in status

    # The last good result stays on disk untouched by the failure.
    generation = systempi.current_generation_path(cache_root)
    assert result_payload(generation)["update_count"] == 2


def test_failure_without_any_previous_success_reports_failure(cache_root):
    runner = FakeCommandRunner([{"returncode": 1, "stderr": "no network"}])
    monitor = make_monitor(cache_root, runner)

    assert monitor._refresh_once() == systempi.REPO_REFRESH_FAILURE
    assert monitor.get_status() == systempi.REPO_STATUS_FAILED
    assert systempi.current_generation_path(cache_root) is None
    assert generation_entries(cache_root) == []


def test_busy_when_lock_is_held_does_not_touch_current_generation(cache_root):
    runner = FakeCommandRunner([ok_step([]), ok_step(["curl", "wget"])])
    monitor = make_monitor(cache_root, runner)
    assert monitor._refresh_once() == systempi.REPO_REFRESH_SUCCESS

    generation = systempi.current_generation_path(cache_root)
    target_before = current_target(cache_root)
    result_before = (generation / "result.json").read_bytes()
    calls_before = len(runner.calls)

    holder = open(cache_root / "repo-check.lock", "a", encoding="utf-8")
    try:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        outcome = monitor._refresh_once()
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()

    assert outcome == systempi.REPO_REFRESH_BUSY
    assert monitor.get_last_outcome() == systempi.REPO_REFRESH_BUSY
    # No collection command ran while another process held the lock.
    assert len(runner.calls) == calls_before
    assert current_target(cache_root) == target_before
    assert (generation / "result.json").read_bytes() == result_before

    status = monitor.get_status()
    assert "2 cached" in status and "busy" in status
    assert generation_entries(cache_root) == [generation.name]


def test_busy_without_previous_success_reports_busy(cache_root):
    monitor = make_monitor(cache_root, FakeCommandRunner([ok_step([])]))
    holder = open(cache_root / "repo-check.lock", "a", encoding="utf-8")
    try:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert monitor._refresh_once() == systempi.REPO_REFRESH_BUSY
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()

    assert monitor.get_status() == systempi.REPO_STATUS_BUSY


def test_recount_with_changed_signature_requests_full_refresh_and_clears_count(cache_root):
    runner = FakeCommandRunner([ok_step([]), ok_step(["curl"]), ok_step([]), ok_step(["curl", "wget"])])
    monitor = make_monitor(cache_root, runner)
    assert monitor._refresh_once() == systempi.REPO_REFRESH_SUCCESS
    assert monitor._count == 1

    # The APT source configuration changed under us.
    monitor._signature_provider = lambda _arches: "signature-b"
    outcome = monitor._recount_current_generation()

    assert outcome == systempi.REPO_REFRESH_NEEDED
    assert monitor.get_last_outcome() == systempi.REPO_REFRESH_NEEDED
    # The old count may no longer pose as the current result.
    assert monitor._count is None
    assert monitor._success_utc is None
    assert monitor.get_status() == "Checking..."

    # A follow-up full refresh collects from scratch with the new signature.
    assert monitor._refresh_once() == systempi.REPO_REFRESH_SUCCESS
    generation = systempi.current_generation_path(cache_root)
    payload = result_payload(generation)
    assert payload["source_signature"] == "signature-b"
    assert payload["update_count"] == 2
    assert monitor.get_status() == "2 available"


def test_recount_with_changed_architectures_also_requests_refresh(cache_root):
    runner = FakeCommandRunner([ok_step([]), ok_step(["curl"])])
    monitor = make_monitor(cache_root, runner)
    assert monitor._refresh_once() == systempi.REPO_REFRESH_SUCCESS

    monitor._architecture_provider = lambda: ["arm64", "i386"]
    assert monitor._recount_current_generation() == systempi.REPO_REFRESH_NEEDED
    assert monitor._count is None
    assert monitor.get_status() == "Checking..."


def test_config_change_during_refresh_does_not_reuse_stale_count(cache_root):
    """A failed full refresh after a config change must not fall back to A's count."""
    runner = FakeCommandRunner([
        ok_step([]),
        ok_step(["curl", "wget"]),
        {"returncode": 1},  # apt-get update fails for the new configuration
    ])
    monitor = make_monitor(cache_root, runner)
    assert monitor._refresh_once() == systempi.REPO_REFRESH_SUCCESS
    assert monitor.get_status() == "2 available"

    monitor._signature_provider = lambda _arches: "signature-b"
    assert monitor._refresh_once() == systempi.REPO_REFRESH_FAILURE

    assert monitor._count is None
    assert monitor.get_status() == systempi.REPO_STATUS_FAILED


def test_failed_refresh_removes_unfinished_generation(cache_root):
    runner = FakeCommandRunner([
        {"returncode": 0},                          # apt-get update succeeds
        {"returncode": 100, "stderr": "boom"},      # apt list --upgradable fails
    ])
    monitor = make_monitor(cache_root, runner)

    assert monitor._refresh_once() == systempi.REPO_REFRESH_FAILURE
    assert generation_entries(cache_root) == []
    assert systempi.current_generation_path(cache_root) is None


def test_cancelled_refresh_removes_unfinished_generation(cache_root):
    monitor = make_monitor(cache_root, FakeCommandRunner([{"returncode": 0}]))

    def cancelling_runner(args, stop_event, timeout):
        # Simulates run_repo_process noticing stop_event mid-command.
        monitor._stop.set()
        return 0, "", "", False, True

    monitor.command_runner = cancelling_runner
    try:
        assert monitor._refresh_once() == systempi.REPO_REFRESH_FAILURE
        assert monitor.get_status() == systempi.REPO_STATUS_FAILED
        assert generation_entries(cache_root) == []
        assert systempi.current_generation_path(cache_root) is None
    finally:
        monitor._stop.clear()


def test_cancel_during_recount_keeps_current_generation(cache_root):
    runner = FakeCommandRunner([ok_step([]), ok_step(["curl"])])
    monitor = make_monitor(cache_root, runner)
    assert monitor._refresh_once() == systempi.REPO_REFRESH_SUCCESS
    generation = systempi.current_generation_path(cache_root)

    def cancelling_runner(args, stop_event, timeout):
        monitor._stop.set()
        return 0, "", "", False, True

    monitor.command_runner = cancelling_runner
    try:
        assert monitor._recount_current_generation() == systempi.REPO_REFRESH_FAILURE
        assert systempi.current_generation_path(cache_root) == generation
        assert result_payload(generation)["update_count"] == 1
    finally:
        monitor._stop.clear()


def test_every_attempt_reports_one_of_four_outcomes(cache_root):
    """The four documented outcomes are all reachable through the monitor."""
    seen = set()

    runner = FakeCommandRunner([ok_step([]), ok_step(["curl"])])
    monitor = make_monitor(cache_root, runner)
    seen.add(monitor._refresh_once())

    runner.steps.append({"returncode": 1})
    seen.add(monitor._refresh_once())

    holder = open(cache_root / "repo-check.lock", "a", encoding="utf-8")
    try:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        seen.add(monitor._refresh_once())
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()

    monitor._signature_provider = lambda _arches: "signature-b"
    seen.add(monitor._recount_current_generation())

    assert seen == {
        systempi.REPO_REFRESH_SUCCESS,
        systempi.REPO_REFRESH_FAILURE,
        systempi.REPO_REFRESH_BUSY,
        systempi.REPO_REFRESH_NEEDED,
    }


def test_run_loop_turns_refresh_needed_into_an_immediate_full_refresh(cache_root):
    """The scheduling loop must not wait out the interval after a recount
    discovers that the cached generation no longer matches the configuration."""

    class LoopProbe(systempi.RepoCheckMonitor):
        def __init__(self, *args, **kwargs):
            self.events = []
            super().__init__(*args, **kwargs)

        def _refresh_once(self):
            self.events.append("refresh")
            return self._finish_attempt(systempi.REPO_REFRESH_SUCCESS)

        def _recount_current_generation(self):
            self.events.append("recount")
            return self._finish_attempt(systempi.REPO_REFRESH_NEEDED)

    monitor = LoopProbe(
        cache_root=cache_root,
        interval=3600,
        retry_interval=60,
        timeout=5,
        command_runner=lambda *a: (0, "", "", False, False),
        architecture_provider=lambda: list(ARCHITECTURES),
        signature_provider=lambda _arches: SIGNATURE,
        command_probe=lambda _name: "/usr/bin/fake",
    )
    monitor._thread = threading.Thread(target=monitor._run, daemon=True)
    monitor._thread.start()
    try:
        deadline = time.monotonic() + 5
        while "refresh" not in monitor.events and time.monotonic() < deadline:
            time.sleep(0.01)
        assert monitor.events[0] == "refresh"  # the on-start refresh

        monitor.request_local_recount()
        while monitor.events[-2:] != ["recount", "refresh"] and time.monotonic() < deadline:
            time.sleep(0.01)

        # recount reported NEEDED and the loop immediately refreshed again
        # instead of sleeping for the full interval.
        assert monitor.events[-2:] == ["recount", "refresh"]
    finally:
        monitor.stop()
