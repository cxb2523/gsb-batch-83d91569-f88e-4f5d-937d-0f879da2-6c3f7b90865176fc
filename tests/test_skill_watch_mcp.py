"""Tests for the read-only batch tool in tools/skill_watch_mcp.py.

The MCP server pins the 2.x SDK (see its inline script metadata). The CI unit-test
job may only have an older ``mcp`` installed, so these tests skip until the pinned
SDK import surface is available; the stdio integration check under
examples/skill-watch/check_mcp.py still exercises the server end to end there.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import skill_watch as sw  # noqa: E402
import watch_fetch as wf  # noqa: E402

MCP_AVAILABLE = importlib.util.find_spec("mcp.server.mcpserver") is not None
if MCP_AVAILABLE:
    import skill_watch_mcp as mcp_watch  # noqa: E402
    from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402


@unittest.skipUnless(MCP_AVAILABLE, "requires the pinned MCP SDK 2.x import surface")
class SkillWatchBatchTests(unittest.TestCase):
    SOURCE_IDS = ["alpha", "beta", "gamma"]

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self._prepare_project(self.root)
        self.watch = sw.Watch(self.root)
        self.server = mcp_watch.create_server(
            self.root, "skill-watch.toml", ".skill-watch/baseline.json"
        )
        self.tools = {tool.name: tool.fn for tool in self.server._tool_manager.list_tools()}
        self.baseline_bytes = self._snapshot_baseline()

    def _prepare_project(self, root: Path) -> None:
        (root / "skills/demo").mkdir(parents=True)
        (root / "agents").mkdir()
        (root / "agents/demo-reviewer.toml").write_text('skills = ["demo"]\n')
        config = ["version = 1\n"]
        for index, source_id in enumerate(self.SOURCE_IDS):
            owner = root / f"skills/demo/{source_id}.md"
            owner.write_text(f"Reference notes for {source_id}. https://docs.example.org/{index}\n")
            (root / f"{source_id}.txt").write_text(f"{source_id} baseline text\n")
            config.append(
                f'\n[[sources]]\nid = "{source_id}"\nfile = "{source_id}.txt"\n'
                f'owners = ["skills/demo/{source_id}.md"]\n'
            )
        (root / "skill-watch.toml").write_text("".join(config))

    def _snapshot_baseline(self) -> bytes:
        self.watch.snapshot()
        return self.watch.state.read_bytes()

    def check_one(self, source_id: str, max_chars: int = sw.DEFAULT_MCP_DIFF_CHARS):
        return self.tools["skill_watch_check"](source_id, max_chars=max_chars)

    def check_batch(self, source_ids, max_chars: int = sw.DEFAULT_MCP_DIFF_CHARS):
        return self.tools["skill_watch_check_batch"](source_ids, max_chars=max_chars)

    def entries_by_id(self, report):
        return {entry["id"]: entry for entry in report["sources"]}

    def assert_baseline_untouched(self):
        self.assertTrue(self.watch.state.exists())
        self.assertEqual(self.watch.state.read_bytes(), self.baseline_bytes)

    def test_all_sources_unchanged_reports_no_review_and_no_truncation(self):
        report = self.check_batch(self.SOURCE_IDS)
        self.assertEqual(report["status"], "unchanged")
        self.assertEqual([entry["id"] for entry in report["sources"]], self.SOURCE_IDS)
        for entry in report["sources"]:
            self.assertEqual(entry["status"], "unchanged")
            self.assertEqual(entry["sha256"], self.watch.capture(entry["id"])["sha256"])
            self.assertEqual(entry["affected_files"], 2)
            self.assertFalse(entry["diff_truncated"])
            self.assertEqual(entry["omitted_hunks"], 0)
            self.assertIsNone(entry["error"])
        summary = report["summary"]
        self.assertEqual(summary["requested"], 3)
        self.assertEqual(summary["review_needed"], 0)
        self.assertEqual(summary["review_needed_ids"], [])
        self.assertEqual(summary["truncated"], 0)
        self.assertEqual(summary["error_ids"], [])
        self.assert_baseline_untouched()

    def test_partial_change_with_pruned_diff_is_summarized_and_matches_single_tool(self):
        # alpha: one oversized hunk that cannot fit even the minimum budget.
        (self.root / "alpha.txt").write_text("alpha baseline text\n" + "x" * 600 + "\n")
        # beta: several separated change hunks so pruning drops only some of them.
        beta_lines = ["beta baseline text"]
        beta_lines += [f"context line {number}" for number in range(28)]
        for number in (2, 10, 18, 26):
            beta_lines[number] = f"changed line {number}"
        (self.root / "beta.txt").write_text("\n".join(beta_lines) + "\n")
        max_chars = 400

        report = self.check_batch(self.SOURCE_IDS, max_chars=max_chars)
        entries = self.entries_by_id(report)
        self.assertEqual(report["status"], "review-needed")

        self.assertEqual(entries["alpha"]["status"], "changed")
        self.assertTrue(entries["alpha"]["diff_truncated"])
        self.assertGreaterEqual(entries["alpha"]["omitted_hunks"], 1)
        self.assertEqual(entries["alpha"]["sha256"], self.watch.capture("alpha")["sha256"])

        self.assertEqual(entries["beta"]["status"], "changed")
        self.assertTrue(entries["beta"]["diff_truncated"])
        self.assertGreaterEqual(entries["beta"]["omitted_hunks"], 1)

        self.assertEqual(entries["gamma"]["status"], "unchanged")
        self.assertFalse(entries["gamma"]["diff_truncated"])
        self.assertEqual(entries["gamma"]["omitted_hunks"], 0)

        summary = report["summary"]
        self.assertEqual(summary["requested"], 3)
        self.assertEqual(summary["review_needed"], 2)
        self.assertEqual(sorted(summary["review_needed_ids"]), ["alpha", "beta"])
        self.assertEqual(summary["truncated"], 2)
        self.assertEqual(sorted(summary["truncated_ids"]), ["alpha", "beta"])
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["error_ids"], [])

        # The batch view must agree with calling the single-source tool per source.
        for source_id in self.SOURCE_IDS:
            single = self.check_one(source_id, max_chars=max_chars)["sources"][0]
            entry = entries[source_id]
            self.assertEqual(entry["status"], single["status"])
            self.assertEqual(entry["diff_truncated"], single["diff_truncated"])
            self.assertEqual(
                entry["omitted_hunks"],
                mcp_watch._count_omitted_hunks(
                    self.watch.check(source_id)["sources"][0]["diff"],
                    single["diff"],
                    single["diff_truncated"],
                ),
            )
            self.assertEqual(
                entry["sha256"],
                single["current"].get("sha256") if single.get("current") else None,
            )
            self.assertEqual(
                entry["affected_files"],
                len(set(single["owners"]) | set(single["agents"]) | set(single["generated_files"])),
            )
        self.assert_baseline_untouched()

    def test_one_failing_source_is_an_error_entry_without_aborting_the_batch(self):
        (self.root / "beta.txt").unlink()
        (self.root / "gamma.txt").write_text("gamma has moved\n")

        report = self.check_batch(self.SOURCE_IDS)
        entries = self.entries_by_id(report)
        self.assertEqual(report["status"], "error")

        self.assertEqual(entries["alpha"]["status"], "unchanged")
        self.assertIsNotNone(entries["alpha"]["sha256"])
        self.assertIsNone(entries["alpha"]["error"])

        self.assertEqual(entries["beta"]["status"], "error")
        self.assertIsNone(entries["beta"]["sha256"])
        self.assertIsInstance(entries["beta"]["error"], str)
        self.assertTrue(entries["beta"]["error"])
        self.assertFalse(entries["beta"]["diff_truncated"])
        self.assertEqual(entries["beta"]["omitted_hunks"], 0)
        self.assertEqual(entries["beta"]["affected_files"], 2)

        self.assertEqual(entries["gamma"]["status"], "changed")

        summary = report["summary"]
        self.assertEqual(summary["requested"], 3)
        self.assertEqual(summary["review_needed"], 1)
        self.assertEqual(summary["review_needed_ids"], ["gamma"])
        self.assertEqual(summary["truncated"], 0)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["error_ids"], ["beta"])

        # Errors classify identically through the single-source tool.
        single = self.check_one("beta")["sources"][0]
        self.assertEqual(single["status"], "error")
        self.assertEqual(entries["beta"]["error"], single["error"])
        self.assert_baseline_untouched()

    def test_unknown_id_rejects_the_whole_batch_before_any_fetch(self):
        with (
            patch.object(sw, "fetch", side_effect=AssertionError("must not fetch")),
            patch.object(wf, "fetch", side_effect=AssertionError("must not fetch")),
        ):
            with self.assertRaises(ToolError) as context:
                self.check_batch(["alpha", "not-configured", "gamma"])
        self.assertIn("not-configured", str(context.exception))

        # A rejected batch leaves no partial state and other tools keep working.
        self.assert_baseline_untouched()
        self.assertEqual(self.check_batch(["alpha"])["status"], "unchanged")

    def test_invalid_arguments_are_rejected_before_any_source_is_checked(self):
        def assert_rejected(arguments):
            with (
                patch.object(self.watch, "check", side_effect=AssertionError("must not check")),
                patch.object(sw, "fetch", side_effect=AssertionError("must not fetch")),
                patch.object(wf, "fetch", side_effect=AssertionError("must not fetch")),
            ):
                with self.assertRaises(ToolError):
                    self.check_batch(**arguments)

        assert_rejected({"source_ids": []})
        assert_rejected({"source_ids": ["alpha"], "max_chars": 127})
        assert_rejected({"source_ids": ["alpha"], "max_chars": sw.MAX_MCP_DIFF_CHARS + 1})
        assert_rejected({"source_ids": ["alpha", "alpha"]})
        self.assert_baseline_untouched()

    def test_batch_counts_match_iterated_single_tool_calls(self):
        # Mix every non-error outcome: unchanged, changed, new-source.
        (self.root / "beta.txt").write_text("beta changed content\n")
        (self.root / "gamma.txt").unlink()
        (self.root / "gamma.txt").write_text("gamma replacement content\n")
        new_owner = self.root / "skills/demo/delta.md"
        new_owner.write_text("delta owner notes\n")
        (self.root / "delta.txt").write_text("delta has no baseline yet\n")
        config_path = self.root / "skill-watch.toml"
        with config_path.open("a") as config:
            config.write(
                '\n[[sources]]\nid = "delta"\nfile = "delta.txt"\n'
                'owners = ["skills/demo/delta.md"]\n'
            )
        # Rebuild the watch so the added source is configured; state file stays as-is.
        self.watch = sw.Watch(self.root)
        self.server = mcp_watch.create_server(
            self.root, "skill-watch.toml", ".skill-watch/baseline.json"
        )
        self.tools = {tool.name: tool.fn for tool in self.server._tool_manager.list_tools()}
        requested = ["alpha", "beta", "gamma", "delta"]

        batch = self.check_batch(requested)
        singles = {source_id: self.check_one(source_id)["sources"][0] for source_id in requested}
        entries = self.entries_by_id(batch)

        expected_statuses = {
            "alpha": "unchanged",
            "beta": "changed",
            "gamma": "changed",
            "delta": "new-source",
        }
        for source_id in requested:
            self.assertEqual(entries[source_id]["status"], expected_statuses[source_id])
            self.assertEqual(entries[source_id]["status"], singles[source_id]["status"])
            self.assertEqual(
                entries[source_id]["diff_truncated"],
                singles[source_id]["diff_truncated"],
            )
            expected_hash = (
                singles[source_id]["current"].get("sha256")
                if singles[source_id].get("current")
                else None
            )
            self.assertEqual(entries[source_id]["sha256"], expected_hash)
            self.assertEqual(
                entries[source_id]["affected_files"],
                len(
                    set(singles[source_id]["owners"])
                    | set(singles[source_id]["agents"])
                    | set(singles[source_id]["generated_files"])
                ),
            )

        review_from_singles = sum(
            1 for source in singles.values() if source["status"] != "unchanged"
        )
        truncated_from_singles = sum(1 for source in singles.values() if source["diff_truncated"])
        self.assertEqual(batch["summary"]["requested"], len(requested))
        self.assertEqual(batch["summary"]["review_needed"], review_from_singles)
        self.assertEqual(batch["summary"]["truncated"], truncated_from_singles)
        self.assertEqual(batch["summary"]["errors"], 0)
        self.assertEqual(
            batch["summary"]["review_needed_ids"],
            [source_id for source_id in requested if expected_statuses[source_id] != "unchanged"],
        )
        self.assert_baseline_untouched()

    def test_tools_are_registered_read_only_and_single_tool_shape_is_unchanged(self):
        names = set(self.tools)
        self.assertEqual(
            names,
            {
                "skill_watch_discover",
                "skill_watch_sources",
                "skill_watch_check",
                "skill_watch_check_batch",
            },
        )
        for tool in self.server._tool_manager.list_tools():
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertFalse(tool.annotations.destructive_hint)

        single = self.check_one("alpha")
        self.assertEqual(set(single), {"status", "meaning", "unconfigured_baselines", "sources"})
        source = single["sources"][0]
        # The single-source tool keeps its original fields, including the pruned diff.
        self.assertEqual(
            set(source),
            {
                "id",
                "owners",
                "agents",
                "generated_files",
                "status",
                "current",
                "baseline",
                "diff",
                "diff_truncated",
            },
        )
        # Text bodies stay stripped from the evidence hashes in both tools.
        self.assertNotIn("text", source["current"])
        self.assertNotIn("text", source["baseline"])
        batch_entry = self.entries_by_id(self.check_batch(["alpha"]))["alpha"]
        self.assertNotIn("diff", batch_entry)
        self.assertNotIn("text", batch_entry)


if __name__ == "__main__":
    unittest.main()
