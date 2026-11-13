#!/usr/bin/env python3
"""End-to-end tests for scripts/verify.py, driven by a fake `gh` binary.

Every test runs verify.py as a subprocess against a *temporary* data dir
(--data-dir) with VERIFY_GH_BIN pointing at tests/fake_gh.py. No real GitHub
traffic happens and no repo data files are touched.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFY = REPO_ROOT / "scripts" / "verify.py"
FAKE_GH = REPO_ROOT / "tests" / "fake_gh.py"

NOW = dt.datetime.now(dt.timezone.utc)


def iso(days_ago: float) -> str:
    return (NOW - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def repo_payload(slug: str, *, days_ago: float, stars: int, **extra) -> dict:
    payload = {
        "full_name": slug,
        "html_url": f"https://github.com/{slug}",
        "stargazers_count": stars,
        "pushed_at": iso(days_ago),
        "license": {"spdx_id": "MIT"},
        "language": "Python",
        "description": f"description of {slug}",
        "archived": False,
    }
    payload.update(extra)
    return payload


def make_entry(name: str, repo: str | None, **extra) -> dict:
    entry = {
        "name": name,
        "slug": name,
        "category": "z-cat",
        "when_to_use": f"curated note for {name}",
    }
    if repo is not None:
        entry["repo"] = repo
        entry["url"] = f"https://github.com/{repo}"
        entry.setdefault("stars", 1)
        entry.setdefault("last_push", "2020-01-01")
        entry.setdefault("license", "Apache-2.0")
        entry.setdefault("language", "JavaScript")
        entry.setdefault("description", "old description")
        entry.setdefault("status", "dead")
    entry.update(extra)
    return entry


@pytest.fixture()
def harness(tmp_path):
    """Set up a temp data dir + fake-gh scenario; return a runner."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    scenario_path = tmp_path / "scenario.json"
    log_path = tmp_path / "gh_calls.log"

    def run_verify(entries, scenario, *extra_args):
        (data_dir / "tools.yaml").write_text(
            yaml.safe_dump(entries, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        scenario_path.write_text(json.dumps(scenario), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["VERIFY_GH_BIN"] = f'"{Path(sys.executable).as_posix()}" "{FAKE_GH.as_posix()}"'
        env["FAKE_GH_SCENARIO"] = str(scenario_path)
        env["FAKE_GH_LOG"] = str(log_path)
        proc = subprocess.run(
            [sys.executable, str(VERIFY), "--data-dir", str(data_dir), *extra_args],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )
        assert proc.returncode == 0, f"verify.py failed:\n{proc.stdout}\n{proc.stderr}"
        tools = yaml.safe_load((data_dir / "tools.yaml").read_text(encoding="utf-8"))
        verified = json.loads((data_dir / "verified.json").read_text(encoding="utf-8"))
        calls = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
        return proc, tools, verified, calls

    return run_verify


def by_name(tools):
    return {t["name"]: t for t in tools}


# ---------------------------------------------------------------- normal run

def full_scenario():
    return {
        "repos/acme/active-tool": {"payload": repo_payload("acme/active-tool", days_ago=10, stars=500)},
        "repos/acme/stale-tool": {"payload": repo_payload("acme/stale-tool", days_ago=270, stars=300)},
        "repos/acme/dead-tool": {"payload": repo_payload("acme/dead-tool", days_ago=900, stars=100, archived=True)},
        "repos/acme/old-name": {"payload": repo_payload("acme/new-name", days_ago=5, stars=42)},
        "repos/acme/gone-tool": {"exit": 1, "stderr": "gh: Not Found (HTTP 404)\nhttps://api.github.com/repos/acme/gone-tool"},
        "repos/acme/limited-tool": {"exit": 1, "stderr": "gh: API rate limit exceeded for user ID 1. (HTTP 403)"},
        "repos/acme/broken-tool": {"exit": 1, "stderr": "gh: Bad Gateway (HTTP 502)"},
    }


def full_entries():
    return [
        make_entry("active-tool", "acme/active-tool"),
        make_entry("stale-tool", "acme/stale-tool"),
        make_entry("dead-tool", "acme/dead-tool"),
        make_entry("renamed-tool", "acme/old-name"),
        make_entry("gone-tool", "acme/gone-tool", stars=999, status="active"),
        make_entry("limited-tool", "acme/limited-tool", stars=777, status="active",
                   last_push="2026-01-01", description="keep me"),
        make_entry("broken-tool", "acme/broken-tool", stars=555, status="stale"),
        make_entry("no-repo-tool", None, status="missing", notes="curated, no repo"),
    ]


def test_statuses_and_fields_written(harness):
    _, tools, verified, _ = harness(full_entries(), full_scenario())
    t = by_name(tools)

    active = t["active-tool"]
    assert active["status"] == "active"
    assert active["stars"] == 500
    assert active["last_push"] == iso(10)[:10]
    assert active["license"] == "MIT"
    assert active["language"] == "Python"
    assert active["description"] == "description of acme/active-tool"
    assert "archived" not in active
    assert active["when_to_use"] == "curated note for active-tool"  # curated field kept

    assert t["stale-tool"]["status"] == "stale"
    assert t["dead-tool"]["status"] == "dead"
    assert t["dead-tool"]["archived"] is True


def test_rename_tracked_independently_of_status(harness):
    _, tools, _, _ = harness(full_entries(), full_scenario())
    renamed = by_name(tools)["renamed-tool"]
    assert renamed["renamed_from"] == "acme/old-name"
    assert renamed["repo"] == "acme/new-name"
    assert renamed["url"] == "https://github.com/acme/new-name"
    assert renamed["status"] == "active"  # lifecycle still derived from pushed_at
    assert renamed["stars"] == 42


def test_confirmed_404_clears_live_fields(harness):
    _, tools, verified, _ = harness(full_entries(), full_scenario())
    gone = by_name(tools)["gone-tool"]
    assert gone["status"] == "missing"
    for field in ("stars", "last_push", "license", "language", "description", "archived"):
        assert field not in gone, f"{field} should have been cleared"
    assert gone["when_to_use"] == "curated note for gone-tool"  # curated field kept
    assert verified["status_counts"]["missing"] == 2  # gone-tool + no-repo-tool


def test_transient_failures_keep_fields_and_are_summarised(harness):
    proc, tools, verified, _ = harness(full_entries(), full_scenario())
    t = by_name(tools)

    limited = t["limited-tool"]
    assert limited["stars"] == 777            # previous values preserved
    assert limited["status"] == "active"
    assert limited["description"] == "keep me"
    assert t["broken-tool"]["stars"] == 555
    assert t["broken-tool"]["status"] == "stale"

    # Incomplete summary in verified.json, with reasons
    incomplete = {i["name"]: i for i in verified["incomplete"]}
    assert set(incomplete) == {"limited-tool", "broken-tool"}
    assert "rate limit" in incomplete["limited-tool"]["reason"].lower()
    assert "502" in incomplete["broken-tool"]["reason"]
    assert incomplete["limited-tool"]["repo"] == "acme/limited-tool"

    # status_counts only covers entries that reached a status this round
    # (active-tool + renamed-tool are active; limited-tool is incomplete and excluded)
    assert verified["status_counts"] == {"active": 2, "stale": 1, "dead": 1, "missing": 2}
    assert verified["verified_count"] == 6
    assert verified["tool_count"] == 8

    # End-of-run summary printed for the operator
    assert "NOT verified this round" in proc.stdout
    assert "limited-tool" in proc.stdout and "broken-tool" in proc.stdout


def test_no_repo_entry_passes_through(harness):
    _, tools, _, _ = harness(full_entries(), full_scenario())
    no_repo = by_name(tools)["no-repo-tool"]
    assert no_repo["status"] == "missing"
    assert no_repo["notes"] == "curated, no repo"
    assert "repo" not in no_repo


def test_sorted_by_category_then_stars_desc(harness):
    entries = full_entries()
    for e in entries:
        if e["name"] == "active-tool":
            e["category"] = "a-cat"
    _, tools, _, _ = harness(entries, full_scenario())
    cats = [t["category"] for t in tools]
    assert cats == sorted(cats)
    z = [t for t in tools if t["category"] == "z-cat"]
    stars = [t.get("stars") or 0 for t in z]
    assert stars == sorted(stars, reverse=True)


# ------------------------------------------------------------------ json-only

def test_json_only_makes_no_api_calls(harness):
    entries = full_entries()
    proc, tools, verified, calls = harness(entries, {}, "--json-only")
    assert calls == [], f"--json-only must not call gh, got: {calls}"
    assert verified["tool_count"] == len(entries)
    # statuses taken straight from tools.yaml, nothing reclassified
    assert verified["status_counts"]["active"] == 2  # gone-tool + limited-tool (as authored)
    assert verified["incomplete"] == []
    assert "no API calls" in proc.stdout


# -------------------------------------------------------------- edge failures

def test_auth_failure_is_transient_not_missing(harness):
    entries = [make_entry("private-tool", "acme/private-tool", stars=42, status="active")]
    scenario = {"repos/acme/private-tool": {"exit": 1, "stderr": "gh: Bad credentials (HTTP 401)"}}
    _, tools, verified, _ = harness(entries, scenario)
    tool = tools[0]
    assert tool["stars"] == 42 and tool["status"] == "active"
    assert verified["status_counts"] == {}
    assert verified["incomplete"][0]["name"] == "private-tool"


def test_404_without_http_marker_still_detected(harness):
    entries = [make_entry("gone", "acme/gone")]
    scenario = {"repos/acme/gone": {"exit": 1, "stderr": "gh: Not Found"}}
    _, tools, verified, _ = harness(entries, scenario)
    assert tools[0]["status"] == "missing"
    assert "stars" not in tools[0]
    assert verified["status_counts"] == {"missing": 1}
