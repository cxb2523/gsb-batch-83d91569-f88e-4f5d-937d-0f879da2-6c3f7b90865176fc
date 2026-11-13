#!/usr/bin/env python3
"""verify.py — refresh data/verified.json from current GitHub state.

Reads data/tools.yaml (the source of truth) and re-queries every repo via the
gh CLI. Updates these fields per entry: stars, last_push, license, language,
description, status, archived. Preserves human-curated fields (name, slug,
when_to_use, category, notes, why_added, renamed_from, install).

Status thresholds, in months since last push:
    < 6   active
    6-18  stale
    > 18  dead
    404   missing  (and clears live fields)

Failure handling — a lookup has three outcomes:
    ok        GitHub returned metadata; live fields are overwritten.
    not_found gh explicitly reported HTTP 404; the entry is marked `missing`
              and all GitHub-sourced fields are cleared.
    error     transient failure (rate limit, timeout, 5xx, auth, network,
              unparsable output). The entry keeps ALL of its previous fields,
              is excluded from this round's status_counts, and is listed in
              the end-of-run incomplete summary (and in verified.json under
              "incomplete") so the round can be audited and retried.

Rename tracking: when GitHub's full_name differs from the entry's repo, the
entry records renamed_from and repo/url are updated to the canonical
coordinates. Renames are independent of lifecycle status — a renamed repo is
still classified active/stale/dead from its pushed_at.

Usage:
    python scripts/verify.py
        # rewrites data/tools.yaml in place AND regenerates data/verified.json

    python scripts/verify.py --json-only
        # just rebuild data/verified.json from current tools.yaml (no API calls)

    python scripts/verify.py --data-dir PATH
        # read/write tools.yaml + verified.json under PATH (used by tests)

Requires: gh CLI authenticated, PyYAML.
The gh binary can be overridden via the VERIFY_GH_BIN env var (test hook).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml  (or: pip install -r requirements.txt)")

# Console output includes emoji/unicode; force UTF-8 on redirected Windows streams.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = REPO_ROOT / "data"
NOW = dt.datetime.now(dt.timezone.utc)

# Fields the verifier OVERWRITES from GitHub. Everything else is preserved.
LIVE_FIELDS = {"stars", "last_push", "license", "language", "description", "status", "archived"}

GH_TIMEOUT = 60  # seconds per `gh api` call

# Lookup outcomes
OK = "ok"
NOT_FOUND = "not_found"
ERROR = "error"

_HTTP_STATUS_RE = re.compile(r"HTTP\s+(\d{3})", re.IGNORECASE)


def _gh_command() -> list[str]:
    """Base command for invoking the GitHub CLI.

    Defaults to ["gh"]; VERIFY_GH_BIN may override it (e.g. pointing at a
    fake gh for tests). The value is split like a shell command line.
    """
    return shlex.split(os.environ.get("VERIFY_GH_BIN", "gh"))


def gh_api_repo(slug: str) -> tuple[str, object]:
    """Query `gh api repos/{slug}` and classify the outcome.

    Returns (outcome, payload):
        (OK, dict)        — repo metadata
        (NOT_FOUND, None) — gh explicitly reported HTTP 404
        (ERROR, str)      — transient failure; payload is a human-readable
                            reason (rate limit, 5xx, auth, timeout, network,
                            invalid JSON). The caller must NOT treat this as
                            "repo is gone".
    """
    try:
        proc = subprocess.run(
            [*_gh_command(), "api", f"repos/{slug}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=GH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return ERROR, f"gh api repos/{slug} timed out after {GH_TIMEOUT}s"
    except OSError as exc:
        return ERROR, f"failed to execute gh: {exc}"

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        m = _HTTP_STATUS_RE.search(stderr)
        code = int(m.group(1)) if m else None
        if code == 404 or (code is None and "Not Found" in stderr):
            return NOT_FOUND, None
        first_line = stderr.splitlines()[0][:200] if stderr else f"gh exited {proc.returncode} with no stderr"
        reason = f"HTTP {code}: {first_line}" if code is not None else first_line
        return ERROR, reason

    try:
        return OK, json.loads(proc.stdout)
    except json.JSONDecodeError:
        return ERROR, "gh returned invalid JSON"


def classify(last_push_iso: str) -> str:
    last = dt.datetime.fromisoformat(last_push_iso.replace("Z", "+00:00"))
    months = (NOW - last).days / 30.4375
    if months < 6:
        return "active"
    if months < 18:
        return "stale"
    return "dead"


def refresh_entry(entry: dict) -> str | None:
    """Refresh one entry in place from GitHub.

    Returns None when the entry reached a definite status this round
    (active/stale/dead/missing, or no-repo passthrough). Returns a failure
    reason string when the lookup failed transiently — in that case the
    entry is left completely untouched.
    """
    slug_label = entry.get("name") or entry.get("slug") or "?"
    repo = entry.get("repo")
    if not repo:
        # missing/no-repo entries pass through unchanged
        entry.setdefault("status", "missing")
        return None

    outcome, payload = gh_api_repo(repo)

    if outcome == ERROR:
        print(f"  ⚠️  {slug_label} ({repo}): incomplete — {payload}")
        return str(payload)

    if outcome == NOT_FOUND:
        print(f"  ⚫ {slug_label} ({repo}): confirmed 404 — marking missing")
        for f in LIVE_FIELDS:
            entry.pop(f, None)
        entry["status"] = "missing"
        return None

    meta = payload
    pushed = meta.get("pushed_at")
    if not pushed:
        reason = "GitHub response had no pushed_at"
        print(f"  ⚠️  {slug_label} ({repo}): incomplete — {reason}")
        return reason

    new_status = classify(pushed)
    entry["stars"] = meta["stargazers_count"]
    entry["last_push"] = pushed[:10]
    entry["license"] = (meta.get("license") or {}).get("spdx_id") or "None"
    entry["language"] = meta.get("language")
    entry["description"] = meta.get("description")
    entry["status"] = new_status
    if meta.get("archived"):
        entry["archived"] = True
    else:
        entry.pop("archived", None)

    # Surface canonical name if the repo was transferred. This is independent
    # of the lifecycle status computed above.
    canonical = meta.get("full_name")
    if canonical and canonical != repo:
        entry["renamed_from"] = repo
        entry["repo"] = canonical
        entry["url"] = meta.get("html_url") or entry.get("url")

    marker = {"active": "🟢", "stale": "🟡", "dead": "🔴"}.get(new_status, "?")
    print(f"  {marker} {slug_label} ({entry['repo']}): {new_status}, ⭐{entry['stars']}, push {entry['last_push']}")
    return None


def stringify(obj):
    if isinstance(obj, dict):
        return {k: stringify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [stringify(v) for v in obj]
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    return obj


def render_json(tools: list[dict], out_path: Path, incomplete: list[tuple[dict, str]]) -> None:
    """Write verified.json.

    status_counts only covers entries that reached a definite status this
    round; transiently-failed entries are reported separately under
    "incomplete" and excluded from the counts.
    """
    skipped = {id(e) for e, _ in incomplete}
    counts: dict[str, int] = {}
    for t in tools:
        if id(t) in skipped:
            continue
        counts[t.get("status", "?")] = counts.get(t.get("status", "?"), 0) + 1
    payload = {
        "$schema": "./schema.json",
        "generated_at": NOW.isoformat(),
        "tool_count": len(tools),
        "verified_count": len(tools) - len(incomplete),
        "status_counts": counts,
        "incomplete": [
            {
                "name": e.get("name") or e.get("slug") or "?",
                "repo": e.get("repo"),
                "reason": reason,
            }
            for e, reason in incomplete
        ],
        "tools": stringify(tools),
    }
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nWrote {out_path} ({len(tools)} tools, {payload['verified_count']} verified this round)")
    for k in ("active", "stale", "dead", "missing"):
        if k in counts:
            print(f"  {k:>8s}: {counts[k]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json-only", action="store_true", help="Skip GitHub API calls; just rebuild verified.json from tools.yaml.")
    ap.add_argument("--data-dir", type=Path, default=DATA, help="Directory holding tools.yaml/verified.json (default: repo data/).")
    args = ap.parse_args(argv)

    tools_yaml = args.data_dir / "tools.yaml"
    verified_json = args.data_dir / "verified.json"

    with tools_yaml.open(encoding="utf-8") as f:
        tools = yaml.safe_load(f) or []

    if args.json_only:
        print(f"Rebuilding {verified_json} from {tools_yaml} (no API calls)")
        render_json(tools, verified_json, incomplete=[])
        return 0

    print(f"Verifying {len(tools)} tools against GitHub API…")
    incomplete: list[tuple[dict, str]] = []
    for t in tools:
        reason = refresh_entry(t)
        if reason is not None:
            incomplete.append((t, reason))

    # Re-sort: category asc, stars desc
    tools.sort(key=lambda e: (e.get("category", "zzz"), -(e.get("stars") or 0)))

    with tools_yaml.open("w", encoding="utf-8") as f:
        yaml.safe_dump(stringify(tools), f, allow_unicode=True, sort_keys=False, width=200)
    print(f"\nUpdated {tools_yaml}")

    render_json(tools, verified_json, incomplete)

    if incomplete:
        print(f"\n⚠️  {len(incomplete)} entr{'y was' if len(incomplete) == 1 else 'ies were'} NOT verified this round "
              f"(transient failures — previous values kept, excluded from status_counts):")
        for e, reason in incomplete:
            print(f"  - {e.get('name') or e.get('slug') or '?'} ({e.get('repo')}): {reason}")
        print("Re-run the script to retry these entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
