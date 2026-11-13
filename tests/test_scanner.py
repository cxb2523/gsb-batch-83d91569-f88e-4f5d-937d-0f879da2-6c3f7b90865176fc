"""Scanner tests against a fake ~/.claude/projects tree in tmp_path.

Covers the incremental-scan contract (add → skip → update), resilience to
files vanishing mid-scan, and the opt-in prune of sessions whose transcript
is gone from disk.

The refresh also produces a per-file outcome trail (one FileOutcome per
discovered transcript, subagent files included): those tests pin the
outcome categories, the human-readable reasons, and the failure contract
(old stats retained, pricing revision unrecorded, retry on the next run).
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from claude_dashboard import scanner
from claude_dashboard.scanner import (
    ADDED,
    PARSE_FAILED,
    PRUNED,
    SKIPPED,
    UPDATED,
    VANISHED,
    FileOutcome,
)
from claude_dashboard.store import Store

_FIXTURE = Path(__file__).parent / "fixtures" / "tiny_session.jsonl"


@pytest.fixture
def projects_dir(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(scanner, "_CLAUDE_PROJECTS", root)
    return root


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "usage.db")
    yield s
    s.close()


def _add_session(projects_dir: Path, project: str = "-Users-test-myproject",
                 name: str = "test-session-001.jsonl") -> Path:
    proj = projects_dir / project
    proj.mkdir(exist_ok=True)
    dest = proj / name
    shutil.copy(_FIXTURE, dest)
    return dest


def _add_subagent(projects_dir: Path, session_name: str = "test-session-001.jsonl",
                  agent_name: str = "agent-01.jsonl") -> Path:
    """Create the <session_id>/subagents/agent-*.jsonl tree next to a session."""
    session_id = Path(session_name).stem
    proj = next(p for p in projects_dir.iterdir() if p.is_dir())
    sub_dir = proj / session_id / "subagents"
    sub_dir.mkdir(parents=True, exist_ok=True)
    dest = sub_dir / agent_name
    shutil.copy(_FIXTURE, dest)
    return dest


def _outcomes_by_path(report) -> dict[str, FileOutcome]:
    return {o.path: o for o in report.outcomes}


def _outcome_for(report, name: str) -> FileOutcome:
    matches = [o for o in report.outcomes if Path(o.path).name == name]
    assert matches, f"no outcome recorded for {name}"
    assert len(matches) == 1
    return matches[0]


def test_refresh_adds_then_skips(projects_dir, store):
    _add_session(projects_dir)

    report = scanner.refresh(store)
    assert report.added == 1
    assert report.errors == []
    assert store.get_session("test-session-001")["cwd"] == "/Users/test/myproject"

    # Unchanged file → skipped on the next scan.
    report = scanner.refresh(store)
    assert (report.added, report.updated, report.skipped) == (0, 0, 1)


def test_refresh_updates_changed_file(projects_dir, store):
    path = _add_session(projects_dir)
    scanner.refresh(store)

    with open(path, "a") as fh:
        fh.write("\n")
    report = scanner.refresh(store)
    assert report.updated == 1


def test_file_vanishing_mid_scan_does_not_kill_refresh(projects_dir, store, monkeypatch):
    _add_session(projects_dir)

    # Simulate the transcript disappearing between iterdir() and parsing
    # (e.g. Claude Code's own cleanup running concurrently).
    def _gone(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(scanner, "parse_file", _gone)
    report = scanner.refresh(store)  # must not raise
    assert report.added == 0
    assert report.errors == []  # a vanished file is not an error


def test_prune_removes_sessions_with_deleted_transcripts(projects_dir, store):
    path = _add_session(projects_dir)
    scanner.refresh(store)
    assert store.get_session("test-session-001")

    path.unlink()

    # Default: deleted transcripts stay in the cache (history survives cleanup).
    report = scanner.refresh(store)
    assert report.pruned == 0
    assert store.get_session("test-session-001")

    # Opt-in prune drops the session and its file-tracking row.
    report = scanner.refresh(store, prune=True)
    assert report.pruned == 1
    assert store.get_session("test-session-001") is None
    assert store.get_file(str(path)) is None


def test_rate_change_reprices_unchanged_sessions(projects_dir, store, monkeypatch):
    """An edit to the pricing table must re-price sessions already in the DB. The
    mtime/size cache would otherwise skip them and keep serving the old cost_usd."""
    _add_session(projects_dir)
    scanner.refresh(store)
    before = store.get_session("test-session-001")["cost_usd"]

    # Same file on disk, but the rate table now fingerprints differently.
    monkeypatch.setattr(scanner, "rate_revision", lambda: "deadbeefdeadbeef")
    monkeypatch.setattr(
        scanner, "estimate_cost", lambda tokens: {"by_model": {}, "total": 99.0, "unknown_models": []}
    )

    report = scanner.refresh(store)
    assert (report.updated, report.skipped) == (1, 0)
    assert store.get_session("test-session-001")["cost_usd"] == 99.0
    assert before != 99.0

    # The revision is recorded, so the next scan goes back to skipping.
    report = scanner.refresh(store)
    assert (report.updated, report.skipped) == (0, 1)


def test_rate_revision_not_recorded_when_scan_errors(projects_dir, store, monkeypatch):
    """A scan that hit an error left some sessions on their old cost, so the revision
    must stay unrecorded and the re-price must be retried on the next refresh."""
    _add_session(projects_dir)
    scanner.refresh(store)

    monkeypatch.setattr(scanner, "rate_revision", lambda: "deadbeefdeadbeef")
    _add_session(projects_dir, name="test-session-002.jsonl")

    real_parse = scanner.parse_file

    def parse_file(path):
        if Path(path).name == "test-session-002.jsonl":
            raise ValueError("unreadable")
        return real_parse(path)

    monkeypatch.setattr(scanner, "parse_file", parse_file)

    report = scanner.refresh(store)
    assert report.errors  # the bad transcript was reported, not fatal
    monkeypatch.setattr(scanner, "parse_file", real_parse)

    # Revision unrecorded → everything is re-parsed again rather than skipped.
    report = scanner.refresh(store)
    assert report.skipped == 0


# ── Per-file outcome trail ──────────────────────────────────────────────────

def test_every_discovered_file_gets_an_outcome(projects_dir, store):
    """One FileOutcome per discovered transcript — main file and each subagent."""
    _add_session(projects_dir)
    sub_path = _add_subagent(projects_dir)

    report = scanner.refresh(store)
    assert report.errors == []
    names = {Path(o.path).name for o in report.outcomes}
    assert names == {"test-session-001.jsonl", sub_path.name}

    main_outcome = _outcome_for(report, "test-session-001.jsonl")
    assert main_outcome.outcome == ADDED
    assert main_outcome.session_id == "test-session-001"
    assert main_outcome.is_subagent is False
    assert main_outcome.reason  # always a human-readable explanation

    sub_outcome = _outcome_for(report, sub_path.name)
    assert sub_outcome.outcome == UPDATED
    assert sub_outcome.is_subagent is True
    assert sub_outcome.session_id == "test-session-001"

    # outcome_counts mirrors the trail and is safe to hand to an API.
    assert report.outcome_counts() == {ADDED: 1, UPDATED: 1}
    # Every row serializes with the documented field set.
    for row in report.outcomes:
        assert set(row.as_dict()) == {
            "path", "session_id", "outcome", "reason", "is_subagent",
        }


def test_skip_outcomes_distinguish_main_and_subagent(projects_dir, store):
    """Skipped rows must say whether the main transcript or a subagent was
    unchanged — the four counters alone can't tell them apart."""
    _add_session(projects_dir)
    sub_path = _add_subagent(projects_dir)
    scanner.refresh(store)

    report = scanner.refresh(store)
    assert (report.added, report.updated, report.skipped) == (0, 0, 1)

    main_outcome = _outcome_for(report, "test-session-001.jsonl")
    assert main_outcome.outcome == SKIPPED
    assert "main transcript unchanged" in main_outcome.reason

    sub_outcome = _outcome_for(report, sub_path.name)
    assert sub_outcome.outcome == SKIPPED
    assert sub_outcome.is_subagent is True
    assert "subagent transcript unchanged" in sub_outcome.reason


def test_outcome_counters_match_the_four_report_totals(projects_dir, store):
    """The legacy added/updated/skipped/pruned counters keep their semantics:
    they count main-session outcomes only, and stay consistent with the trail."""
    _add_session(projects_dir)
    _add_session(projects_dir, name="test-session-002.jsonl")

    report = scanner.refresh(store)
    main_outcomes = [o for o in report.outcomes if not o.is_subagent]
    assert len(main_outcomes) == 2
    assert report.added == sum(o.outcome == ADDED for o in main_outcomes)
    assert report.outcome_counts()[ADDED] == 2


def test_parse_failure_keeps_old_stats_and_retries_next_run(projects_dir, store, monkeypatch):
    """A broken transcript must not (1) abort the scan, (2) wipe the session's
    cached cost, or (3) mark the pricing revision handled — the next refresh
    retries the file."""
    path = _add_session(projects_dir)
    scanner.refresh(store)
    cached_before = store.get_session("test-session-001")
    cost_before = cached_before["cost_usd"]
    assert cost_before > 0
    revision_before = store.get_meta(scanner._RATE_REVISION_KEY)
    assert revision_before is not None

    # New pricing table makes this a re-price run; the transcript now fails.
    monkeypatch.setattr(scanner, "rate_revision", lambda: "deadbeefdeadbeef")

    real_parse = scanner.parse_file

    def parse_file(path):
        if Path(path).name == "test-session-001.jsonl":
            raise ValueError("unreadable transcript")
        return real_parse(path)

    monkeypatch.setattr(scanner, "parse_file", parse_file)
    report = scanner.refresh(store)  # must not raise

    # Failure is a per-file parse_failed outcome, recorded in errors.
    outcome = _outcome_for(report, "test-session-001.jsonl")
    assert outcome.outcome == PARSE_FAILED
    assert "unreadable transcript" in outcome.reason
    assert report.errors and report.outcome_counts()[PARSE_FAILED] == 1

    # Old cost and the whole cached row survive.
    assert store.get_session("test-session-001")["cost_usd"] == cost_before
    # The file-tracking row is untouched too, so nothing pretends the parse
    # succeeded.
    assert store.get_file(str(path)) is not None
    # Revision NOT advanced → the re-price (and the failed file) get retried.
    assert store.get_meta(scanner._RATE_REVISION_KEY) == revision_before

    # Repair the file: the next refresh retries and succeeds.
    monkeypatch.setattr(scanner, "parse_file", real_parse)
    report = scanner.refresh(store)
    assert report.errors == []
    assert _outcome_for(report, "test-session-001.jsonl").outcome in (ADDED, UPDATED)
    # Now the revision can finally be recorded.
    assert store.get_meta(scanner._RATE_REVISION_KEY) == "deadbeefdeadbeef"


def test_one_bad_file_does_not_block_sibling_sessions(projects_dir, store, monkeypatch):
    """The failing file's neighbour must still be collected in the same run."""
    _add_session(projects_dir)
    _add_session(projects_dir, name="test-session-002.jsonl")

    real_parse = scanner.parse_file

    def parse_file(path):
        if Path(path).name == "test-session-002.jsonl":
            raise ValueError("unreadable transcript")
        return real_parse(path)

    monkeypatch.setattr(scanner, "parse_file", parse_file)
    report = scanner.refresh(store)

    assert _outcome_for(report, "test-session-001.jsonl").outcome == ADDED
    assert _outcome_for(report, "test-session-002.jsonl").outcome == PARSE_FAILED
    assert store.get_session("test-session-001") is not None
    assert store.get_session("test-session-002") is None


def test_vanished_file_is_non_error_outcome(projects_dir, store, monkeypatch):
    """A transcript deleted between listing and parsing is recorded as
    ``vanished`` — not an error, not counted in report.errors."""
    _add_session(projects_dir)

    def _gone(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(scanner, "parse_file", _gone)
    report = scanner.refresh(store)  # must not raise

    outcome = _outcome_for(report, "test-session-001.jsonl")
    assert outcome.outcome == VANISHED
    assert report.errors == []
    assert PARSE_FAILED not in report.outcome_counts()
    assert report.outcome_counts()[VANISHED] == 1
    # A clean (error-free) run still records the pricing revision.
    assert store.get_meta(scanner._RATE_REVISION_KEY) is not None


def test_vanished_subagent_is_non_error_and_keeps_session(projects_dir, store, monkeypatch):
    _add_session(projects_dir)
    sub_path = _add_subagent(projects_dir)
    scanner.refresh(store)

    # Force a re-parse (otherwise the unchanged fast path never opens the
    # subagent), then make the subagent disappear during that re-parse.
    monkeypatch.setattr(scanner, "rate_revision", lambda: "deadbeefdeadbeef")
    real_parse = scanner.parse_file

    def parse_file(path):
        if Path(path).name == sub_path.name:
            raise FileNotFoundError(path)
        return real_parse(path)

    monkeypatch.setattr(scanner, "parse_file", parse_file)
    report = scanner.refresh(store)

    sub_outcome = _outcome_for(report, sub_path.name)
    assert sub_outcome.outcome == VANISHED
    assert sub_outcome.is_subagent is True
    assert report.errors == []
    # Parent session is still refreshed around the missing subagent.
    assert store.get_session("test-session-001") is not None


def test_failed_subagent_keeps_cached_session_stats(projects_dir, store, monkeypatch):
    """A subagent parse failure must not overwrite the parent session with
    stats missing that subagent's contribution."""
    _add_session(projects_dir)
    sub_path = _add_subagent(projects_dir)
    scanner.refresh(store)
    cost_before = store.get_session("test-session-001")["cost_usd"]
    rounds_before = store.get_session("test-session-001")["user_rounds"]
    # The subagent's tracking row exists after the first clean scan.
    assert store.get_file(str(sub_path)) is not None

    # Force a re-parse so the broken subagent is actually opened.
    monkeypatch.setattr(scanner, "rate_revision", lambda: "deadbeefdeadbeef")
    real_parse = scanner.parse_file

    def parse_file(path):
        if Path(path).name == sub_path.name:
            raise ValueError("bad subagent jsonl")
        return real_parse(path)

    monkeypatch.setattr(scanner, "parse_file", parse_file)
    report = scanner.refresh(store)

    sub_outcome = _outcome_for(report, sub_path.name)
    assert sub_outcome.outcome == PARSE_FAILED
    assert report.errors

    cached = store.get_session("test-session-001")
    assert cached["cost_usd"] == cost_before
    assert cached["user_rounds"] == rounds_before

    # Subagent tracking row untouched → next run retries instead of skipping.
    monkeypatch.setattr(scanner, "parse_file", real_parse)
    report = scanner.refresh(store)
    assert report.errors == []
    assert _outcome_for(report, sub_path.name).outcome == UPDATED


def test_prune_records_outcomes_for_main_and_subagent_rows(projects_dir, store):
    path = _add_session(projects_dir)
    sub_path = _add_subagent(projects_dir)
    scanner.refresh(store)

    path.unlink()
    shutil.rmtree(sub_path.parents[1])  # remove <session_id>/ tree incl. subagent

    report = scanner.refresh(store, prune=True)
    assert report.pruned == 1

    main_outcome = _outcome_for(report, "test-session-001.jsonl")
    assert main_outcome.outcome == PRUNED
    assert "session removed" in main_outcome.reason
    sub_outcome = _outcome_for(report, sub_path.name)
    assert sub_outcome.outcome == PRUNED
    assert sub_outcome.is_subagent is True
    # Pruning is an explicit action, never an error.
    assert report.errors == []
    assert store.get_session("test-session-001") is None


def test_update_outcome_explains_what_changed(projects_dir, store):
    path = _add_session(projects_dir)
    scanner.refresh(store)

    with open(path, "a") as fh:
        fh.write("\n")
    report = scanner.refresh(store)
    outcome = _outcome_for(report, "test-session-001.jsonl")
    assert outcome.outcome == UPDATED
    assert "changed" in outcome.reason
