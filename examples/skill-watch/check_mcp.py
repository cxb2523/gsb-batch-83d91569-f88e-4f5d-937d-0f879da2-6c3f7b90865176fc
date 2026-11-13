# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp==2.2.0"]
# ///
"""Check actual stdio discovery, tool calls, and errors without an LLM or network."""

import asyncio
import importlib.metadata
import json
import shutil
import sys
import tempfile
from pathlib import Path

from mcp import Client, StdioServerParameters
from run import HERE, ROOT, Watch, prepare


async def exercise(project, mode):
    prepare(project)
    watch = Watch(project)
    watch.snapshot()
    baseline = watch.state.read_bytes()
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "tools/skill_watch_mcp.py"), "--project", str(project)],
    )
    async with Client(params, read_timeout_seconds=20, mode=mode) as client:
        tools = (await client.list_tools()).tools
        assert {tool.name for tool in tools} == {
            "skill_watch_discover",
            "skill_watch_sources",
            "skill_watch_check",
            "skill_watch_check_batch",
        }
        assert all(tool.annotations.read_only_hint for tool in tools)
        sources = await client.call_tool("skill_watch_sources", {})
        assert sources.structured_content["sources"][0]["id"] == "training"
        links = await client.call_tool("skill_watch_discover", {})
        assert (
            links.structured_content["references"][0]["url"] == "https://docs.example.org/training"
        )
        first = await client.call_tool("skill_watch_check", {"source_id": "training"})
        assert first.structured_content["status"] == "unchanged"
        shutil.copyfile(HERE / "after.html", project / "training.html")
        changed = await client.call_tool("skill_watch_check", {"source_id": "training"})
        report = changed.structured_content
        assert report["status"] == "review-needed"
        assert report["sources"][0]["agents"] == ["agents/mkl-demo-investigator.toml"]
        assert "Checkpoints are disabled" in report["sources"][0]["diff"]
        unknown = await client.call_tool("skill_watch_check", {"source_id": "not-configured"})
        assert unknown.is_error
        missing = await client.call_tool("skill_watch_check", {})
        assert missing.is_error

        # The batch tool reports the whole set in one call and stays read-only.
        batch_ok = await client.call_tool("skill_watch_check_batch", {"source_ids": ["training"]})
        batch_report = batch_ok.structured_content
        assert batch_report["status"] == "review-needed"
        entry = batch_report["sources"][0]
        assert entry["id"] == "training"
        assert entry["status"] == "changed"
        assert len(entry["sha256"]) == 64
        assert entry["affected_files"] == 2
        assert batch_report["summary"]["requested"] == 1
        assert batch_report["summary"]["review_needed"] == 1
        assert batch_report["summary"]["error_ids"] == []

        batch_unknown = await client.call_tool(
            "skill_watch_check_batch", {"source_ids": ["training", "not-configured"]}
        )
        assert batch_unknown.is_error
        batch_budget = await client.call_tool(
            "skill_watch_check_batch", {"source_ids": ["training"], "max_chars": 127}
        )
        assert batch_budget.is_error
        batch_empty = await client.call_tool("skill_watch_check_batch", {"source_ids": []})
        assert batch_empty.is_error

        # A failing source becomes an error entry, not a rejected batch; the null hash
        # and error string must survive structured output over the wire.
        (project / "training.html").write_text("unrelated page without the markers")
        batch_failed = await client.call_tool(
            "skill_watch_check_batch", {"source_ids": ["training"]}
        )
        assert not batch_failed.is_error
        failed_report = batch_failed.structured_content
        assert failed_report["status"] == "error"
        failed_entry = failed_report["sources"][0]
        assert failed_entry["id"] == "training"
        assert failed_entry["status"] == "error"
        assert failed_entry["sha256"] is None
        assert failed_entry["error"]
        assert failed_entry["diff_truncated"] is False
        assert failed_entry["omitted_hunks"] == 0
        assert failed_report["summary"]["error_ids"] == ["training"]
    assert watch.state.read_bytes() == baseline
    return {"mode": mode, "tools": len(tools), "verified": True}


async def main():
    runs = []
    for mode in ("auto", "legacy"):
        with tempfile.TemporaryDirectory(prefix="mkl-watch-mcp-") as directory:
            runs.append(await exercise(Path(directory), mode))
    print(
        json.dumps(
            {
                "transport": "stdio",
                "mcp_sdk": importlib.metadata.version("mcp"),
                "python": sys.version.split()[0],
                "runs": runs,
                "model_invoked": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run this check without Python -O; its assertions must be enabled")
    asyncio.run(main())
