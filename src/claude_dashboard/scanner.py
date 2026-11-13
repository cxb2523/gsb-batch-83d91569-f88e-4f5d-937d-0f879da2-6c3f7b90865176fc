from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from claude_dashboard.parser import merge_stats, parse_file
from claude_dashboard.pricing import estimate_cost, rate_revision
from claude_dashboard.store import Store

_CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
_RATE_REVISION_KEY = "pricing_rate_revision"

# Per-file outcome categories. Every transcript discovered during a refresh
# (main session files and their subagent files) gets exactly one of these,
# so the report accounts for every file the scan touched.
ADDED = "added"
UPDATED = "updated"
SKIPPED = "skipped"
PARSE_FAILED = "parse_failed"
VANISHED = "vanished"
PRUNED = "pruned"

# Non-error outcomes: a file vanishing mid-scan is normal (Claude Code runs
# its own cleanup concurrently) and pruning is an explicit user action, so
# neither counts toward report.errors.
_NON_ERROR_OUTCOMES = frozenset({ADDED, UPDATED, SKIPPED, VANISHED, PRUNED})


@dataclass
class FileOutcome:
    """What happened to one discovered transcript file during a refresh.

    One row per file (main session transcript or subagent transcript), so a
    caller can reconstruct why every file on disk did — or did not — reach the
    cache. ``reason`` is a human-readable explanation; ``is_subagent`` tells
    the two file kinds apart and ``session_id`` groups a subagent with the
    session it belongs to.
    """

    path: str
    session_id: str
    outcome: str
    reason: str
    is_subagent: bool = False

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "session_id": self.session_id,
            "outcome": self.outcome,
            "reason": self.reason,
            "is_subagent": self.is_subagent,
        }


@dataclass
class RefreshReport:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    pruned: int = 0
    errors: list[str] = field(default_factory=list)
    # One entry per discovered file, in scan order. Holds the full story the
    # four counters above can't tell: which file, which session, why.
    outcomes: list[FileOutcome] = field(default_factory=list)

    def record(self, outcome: FileOutcome) -> None:
        self.outcomes.append(outcome)
        if outcome.outcome not in _NON_ERROR_OUTCOMES:
            # The error string keeps its historical "{path}: {detail}" shape
            # so existing log/consumers of report.errors are unaffected.
            self.errors.append(f"{outcome.path}: {outcome.reason}")

    def outcome_counts(self) -> dict[str, int]:
        """Tally of outcomes by category — safe to expose over an API that
        must not leak filesystem paths or exception text."""
        counts: dict[str, int] = {}
        for o in self.outcomes:
            counts[o.outcome] = counts.get(o.outcome, 0) + 1
        return counts


def refresh(store: Store, prune: bool = False) -> RefreshReport:
    """Scan ~/.claude/projects and update the cache.

    With prune=True, sessions whose transcript file no longer exists on disk
    are removed from the DB. Default is to keep them: Claude Code deletes old
    transcripts after `cleanupPeriodDays`, and the cache deliberately preserves
    that history.

    Every discovered file (including subagent transcripts) gets a FileOutcome
    on the returned report. A single file failing never aborts the scan, never
    removes that session's cached stats, and never marks the pricing revision
    as processed — so the next refresh retries the failed file.
    """
    report = RefreshReport()

    if not _CLAUDE_PROJECTS.exists():
        return report

    # Stored cost_usd was computed with whatever rates were in effect at parse time.
    # If the rate table has changed since, the mtime/size cache would keep serving
    # those stale numbers forever — so re-parse everything once after a rate edit.
    revision = rate_revision()
    reprice_all = store.get_meta(_RATE_REVISION_KEY) != revision

    for project_dir in sorted(_CLAUDE_PROJECTS.iterdir()):
        if not project_dir.is_dir():
            continue

        project_path = _decode_project_path(project_dir.name)

        # Collect top-level session jsonl files (not subagent files)
        session_files: dict[str, Path] = {}  # session_id -> path
        for f in project_dir.iterdir():
            if f.suffix == ".jsonl" and f.is_file():
                # UUID based name
                session_id = f.stem
                session_files[session_id] = f

        for session_id, jsonl_path in session_files.items():
            _refresh_session(store, report, session_id, jsonl_path,
                             project_path, project_dir.name, reprice_all)

    if prune:
        report.pruned = _prune_missing(store, report)

    # Only once the whole scan is clean. If a session errored out it kept its old
    # cost, so leaving the revision unrecorded makes the next refresh try again.
    if not report.errors:
        store.set_meta(_RATE_REVISION_KEY, revision)

    return report


def _refresh_session(store: Store, report: RefreshReport, session_id: str,
                     jsonl_path: Path, project_path: str,
                     project_dir_name: str, reprice_all: bool) -> None:
    """Process one main session transcript and its subagent transcripts.

    Everything here can hit files deleted between iterdir() and the actual
    read (e.g. Claude Code's own cleanup); one vanished or unparseable session
    must not kill the whole scan — especially the silent startup thread.
    """
    path_str = str(jsonl_path)
    try:
        stat = os.stat(jsonl_path)
        mtime = stat.st_mtime
        size = stat.st_size

        # Subagent files decide the skip/update call below.
        subagent_paths = _find_subagents(jsonl_path)

        cached = store.get_file(path_str)
        if not reprice_all and cached and cached["mtime"] == mtime and cached["size"] == size:
            # Check if subagents changed
            changed_sub = _first_changed_subagent(store, subagent_paths)
            if changed_sub is None:
                report.skipped += 1
                report.record(FileOutcome(
                    path=path_str, session_id=session_id, outcome=SKIPPED,
                    reason="main transcript unchanged (mtime/size match cache)",
                ))
                for sub_path in subagent_paths:
                    report.record(FileOutcome(
                        path=str(sub_path), session_id=session_id, outcome=SKIPPED,
                        reason="subagent transcript unchanged (mtime/size match cache)",
                        is_subagent=True,
                    ))
                return
            is_update = True
            change_reason = f"subagent changed: {changed_sub}"
        else:
            is_update = bool(cached)
            if reprice_all:
                change_reason = "pricing rate table updated; re-parsing for re-price"
            elif cached:
                change_reason = "main transcript changed (mtime/size differ from cache)"
            else:
                change_reason = "new transcript, not yet in cache"

        stats = parse_file(jsonl_path)
        stats["session_id"] = stats["session_id"] or session_id
        # Use cwd from the file itself — it's the authoritative path.
        # The folder-name encoding is lossy (dashes = slashes), so names
        # like "server-management" would decode incorrectly if we relied on it.
        cwd = stats.get("cwd") or project_path
        stats["project_path"] = cwd
        stats["project_name"] = cwd.rstrip("/").split("/")[-1] if cwd else project_dir_name

        # Merge subagent stats. Each subagent is its own per-file error
        # boundary and gets its own outcome row.
        subagent_failures: list[FileOutcome] = []
        for sub_path in subagent_paths:
            sub_outcome, sub_stats = _refresh_subagent(session_id, sub_path)
            report.record(sub_outcome)
            if sub_outcome.outcome == PARSE_FAILED:
                # Do not merge anything for this subagent; remember the failure
                # so the parent session keeps its previously cached stats.
                subagent_failures.append(sub_outcome)
                continue
            if sub_outcome.outcome == VANISHED:
                # Gone between listing and reading. Its stats must not be
                # counted; the orphaned cache row is handled by prune.
                continue
            merge_stats(stats, sub_stats)
            try:
                sub_stat = os.stat(sub_path)
            except FileNotFoundError as e:
                # Parsed fine, then deleted before its tracking row could be
                # written. Correct the earlier optimistic outcome to the
                # non-error disappearance; the stale row (if any) is reclaimed
                # by prune on a later refresh.
                sub_outcome.outcome = VANISHED
                sub_outcome.reason = f"subagent transcript disappeared during scan: {e}"
                continue
            store.upsert_file(
                str(sub_path), session_id,
                sub_stat.st_mtime, sub_stat.st_size
            )

        if subagent_failures:
            # A merged session cost would silently drop the failed subagent's
            # contribution (or keep a partial one). Refuse to overwrite the
            # cached session and leave the main file's tracking row untouched,
            # so its old cost survives and the unchanged-mtime fast path cannot
            # swallow the retry on the next refresh.
            detail = "; ".join(Path(o.path).name for o in subagent_failures)
            report.record(FileOutcome(
                path=path_str, session_id=session_id, outcome=PARSE_FAILED,
                reason=(f"main transcript parsed, but {len(subagent_failures)} "
                        f"subagent transcript(s) failed; cached stats retained: {detail}"),
            ))
            return

        # Equivalent API cost. Runs below what `/cost` reports, because the
        # CLI bills side requests it never writes to the transcript — see the
        # module docstring in pricing.py.
        stats["cost_usd"] = estimate_cost(stats.get("tokens_by_model", {}))["total"]

        store.upsert_session(stats)
        store.upsert_file(path_str, stats["session_id"], mtime, size)

        if is_update:
            report.updated += 1
            report.record(FileOutcome(
                path=path_str, session_id=session_id, outcome=UPDATED,
                reason=change_reason,
            ))
        else:
            report.added += 1
            report.record(FileOutcome(
                path=path_str, session_id=session_id, outcome=ADDED,
                reason=change_reason,
            ))

    except FileNotFoundError as e:
        # Deleted mid-scan; a vanished file is an expected, non-error outcome.
        # The stale DB entry is handled by prune.
        report.record(FileOutcome(
            path=path_str, session_id=session_id, outcome=VANISHED,
            reason=f"transcript disappeared during scan: {e}",
        ))
    # Blind catch is deliberate: this is a per-file error boundary. One bad
    # transcript is recorded and skipped, not fatal to the scan, and the
    # session's cached stats are left intact for the next refresh to retry.
    except Exception as e:  # noqa: BLE001
        report.record(FileOutcome(
            path=path_str, session_id=session_id, outcome=PARSE_FAILED,
            reason=str(e),
        ))


def _refresh_subagent(
    session_id: str, sub_path: Path
) -> tuple[FileOutcome, dict | None]:
    """Read one subagent transcript, returning (outcome, parsed stats).

    The stats merge and file-row upsert happen in the caller, which owns the
    parent session. On a failure or disappearance stats is None and the
    outcome carries the human-readable reason; parsing here keeps the failure
    attributed to this subagent instead of bubbling into the parent session's
    error boundary.
    """
    path_str = str(sub_path)

    def _fail(outcome: str, reason: str) -> tuple[FileOutcome, dict | None]:
        return (
            FileOutcome(path=path_str, session_id=session_id,
                        outcome=outcome, reason=reason, is_subagent=True),
            None,
        )

    try:
        sub_stats = parse_file(sub_path)
    except FileNotFoundError as e:
        return _fail(VANISHED, f"subagent transcript disappeared during scan: {e}")
    except Exception as e:  # noqa: BLE001
        return _fail(PARSE_FAILED, str(e))
    return (
        FileOutcome(
            path=path_str, session_id=session_id, outcome=UPDATED,
            reason="subagent transcript parsed and merged into parent session",
            is_subagent=True,
        ),
        sub_stats,
    )


def _decode_project_path(encoded: str) -> str:
    """Convert `-Users-alice-projects-MyApp` → `/Users/alice/projects/MyApp`."""
    # Strip a single leading dash, then replace remaining dashes with slashes.
    # This is a heuristic — consecutive dashes in real path segments would break it,
    # but Claude Code itself uses the same encoding scheme.
    encoded = encoded.removeprefix("-")
    return "/" + encoded.replace("-", "/")


def _find_subagents(session_jsonl: Path) -> list[Path]:
    """Look for subagents/<session_id>/subagents/agent-*.jsonl patterns."""
    results = []
    # Pattern: ~/.claude/projects/<project>/<session_id>/subagents/agent-*.jsonl
    session_dir = session_jsonl.parent / session_jsonl.stem
    if session_dir.is_dir():
        sub_dir = session_dir / "subagents"
        if sub_dir.is_dir():
            for f in sorted(sub_dir.glob("agent-*.jsonl")):
                if f.is_file():
                    results.append(f)
    return results


def _first_changed_subagent(store: Store, paths: list[Path]) -> str | None:
    """Return a human-readable description of the first subagent that changed,
    or None when every subagent is unchanged (including the no-subagents case)."""
    for p in paths:
        try:
            stat = os.stat(p)
        except FileNotFoundError:
            # Vanished since listing — reparse to drop its stats.
            return f"{p.name} vanished since listing"
        cached = store.get_file(str(p))
        if not cached:
            return f"{p.name} not yet in cache"
        if cached["mtime"] != stat.st_mtime or cached["size"] != stat.st_size:
            return f"{p.name} changed (mtime/size differ from cache)"
    return None


def _prune_missing(store: Store, report: RefreshReport | None = None) -> int:
    """Delete DB entries whose backing files are gone. Returns sessions removed.

    A session row is removed only when its main transcript
    (<session_id>.jsonl) is missing; orphaned subagent file rows are cleaned
    up without touching their parent session. Every removed row is recorded
    as a PRUNED outcome when a report is supplied.
    """
    removed = 0
    for row in store.list_files():
        path = row["path"]
        if os.path.exists(path):
            continue
        is_main = path.endswith(f"{row['session_id']}.jsonl")
        store.delete_file(path)
        if is_main:
            store.delete_session(row["session_id"])
            removed += 1
        if report is not None:
            report.record(FileOutcome(
                path=path, session_id=row["session_id"], outcome=PRUNED,
                reason=("main transcript missing on disk; session removed"
                        if is_main
                        else "subagent transcript missing on disk; file row removed"),
                is_subagent=not is_main,
            ))
    return removed
