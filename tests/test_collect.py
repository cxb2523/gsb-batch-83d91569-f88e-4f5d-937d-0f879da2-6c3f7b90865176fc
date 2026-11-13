#!/usr/bin/env python3
"""Tests for the recall-window and old-day write decisions in scripts/collect.py.

Every test builds a throwaway mini-repo: a copy of collect.py, a config.json, a
data/<host>/ tree, and a real git repo, plus an `npx` stand-in on PATH whose
`ccusage` output is a fixed JSON payload. That pins down exactly what the
collector read, wrote, skipped and stamped into _meta.json — no network, no
shared state between tests.

Run: python3 -m unittest discover -s tests -v
Targets Python 3.9. Standard library only.
"""

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECT_SRC = os.path.join(REPO_ROOT, "scripts", "collect.py")
HOST = "test-host"
FINAL_AFTER = 7

STUB_PY = r'''import json
import os
import sys

log_path = os.environ.get("STUB_CCUSAGE_LOG")
if log_path:
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(sys.argv[1:]) + "\n")

argv = sys.argv[1:]
if "--version" in argv:
    print("ccusage 20.0.50")
    sys.exit(0)

payload = json.load(open(os.environ["STUB_CCUSAGE"], encoding="utf-8"))
source = argv[argv.index("daily") - 1] if "daily" in argv else "claude"
print(json.dumps({"daily": payload.get(source, [])}))
'''


def utc_today():
    return dt.datetime.now(dt.timezone.utc).date()


def day(days_ago):
    return utc_today() - dt.timedelta(days=days_ago)


def iso(days_ago):
    return day(days_ago).isoformat()


def claude_row(date_str, input_tokens):
    """A minimal ccusage `claude daily` record the normalizer understands."""
    return {
        "date": date_str,
        "inputTokens": input_tokens,
        "outputTokens": 1,
        "cacheCreationTokens": 0,
        "cacheReadTokens": 0,
        "totalTokens": input_tokens + 1,
        "totalCost": 0.001,
    }


def claude_source(input_tokens):
    """The normalized payload a stored data file should hold for the row above."""
    return {
        "input": input_tokens,
        "output": 1,
        "cacheCreation": 0,
        "cacheRead": 0,
        "total": input_tokens + 1,
        "costUSD": 0.001,
        "models": {},
    }


def data_record(date_str, input_tokens, status="final", collected_at="2026-01-01T00:00:00Z"):
    return {
        "date": date_str,
        "host": HOST,
        "timezone": "UTC",
        "status": status,
        "collectedAt": collected_at,
        "ccusageVersion": "20.0.50",
        "sources": {"claude": claude_source(input_tokens)},
    }


class CollectorEnv(object):
    """A disposable repo + PATH stub + payload the collector runs against."""

    def __init__(self, tmpdir, recall=None, meta=None, sources=("claude",)):
        self.root = os.path.join(tmpdir, "repo")
        self.host_dir = os.path.join(self.root, "data", HOST)
        self.meta_path = os.path.join(self.host_dir, "_meta.json")
        self.payload_path = os.path.join(tmpdir, "payload.json")
        self.stub_log = os.path.join(tmpdir, "stub.log")
        self.bin_dir = os.path.join(tmpdir, "bin")

        os.makedirs(os.path.join(self.root, "scripts"))
        os.makedirs(self.host_dir)
        os.makedirs(self.bin_dir)
        # Copy so REPO_ROOT resolves to the temp repo, not the real one.
        shutil.copy2(COLLECT_SRC, os.path.join(self.root, "scripts", "collect.py"))

        self.script = os.path.join(self.root, "scripts", "collect.py")
        self.config_path = os.path.join(self.root, "config.json")
        cfg = {
            "host": HOST,
            "timezone": "UTC",
            "sources": list(sources),
            "recall": dict({"min_days": 3, "max_days": 21, "slack_days": 2,
                            "final_after_days": FINAL_AFTER}, **(recall or {})),
            "git": {"enabled": True, "remote": "origin", "branch": "main",
                    "push_retries": 1},
            "ccusage": {"spec": "ccusage@latest"},
        }
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)

        if meta is not None:
            self.write_meta(meta)
        self.write_payload({})
        self._install_stub()
        self._init_git()

    # -- fixtures ---------------------------------------------------------

    def write_payload(self, payload):
        with open(self.payload_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def write_meta(self, meta):
        with open(self.meta_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, sort_keys=True)

    def read_meta(self):
        if not os.path.exists(self.meta_path):
            return None
        with open(self.meta_path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def write_day(self, date_str, input_tokens, status="final",
                  collected_at="2026-01-01T00:00:00Z"):
        record = data_record(date_str, input_tokens, status, collected_at)
        with open(os.path.join(self.host_dir, date_str + ".json"), "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, sort_keys=True)
        return record

    def read_day(self, date_str):
        path = os.path.join(self.host_dir, date_str + ".json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def day_files(self):
        return sorted(n for n in os.listdir(self.host_dir)
                      if n.endswith(".json") and n != "_meta.json")

    def _install_stub(self):
        stub = os.path.join(self.bin_dir, "stub.py")
        with open(stub, "w", encoding="utf-8") as fh:
            fh.write(STUB_PY)
        py = sys.executable
        # One launcher per platform; both are harmless, `shutil.which("npx")`
        # picks the one this OS understands.
        with open(os.path.join(self.bin_dir, "npx"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write('#!/bin/sh\nexec "{}" "{}" "$@"\n'.format(py, stub))
        os.chmod(os.path.join(self.bin_dir, "npx"), 0o755)
        with open(os.path.join(self.bin_dir, "npx.bat"), "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write('@echo off\n"{}" "{}" %*\n'.format(py, stub))

    def _init_git(self):
        self.git("init", "-q")
        self.git("config", "user.name", "Test Bot")
        self.git("config", "user.email", "test@example.com")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "initial snapshot")

    # -- execution --------------------------------------------------------

    def git(self, *args):
        proc = subprocess.run(["git", "-C", self.root] + list(args),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = proc.stdout.decode(errors="replace")
        if proc.returncode != 0:
            raise AssertionError("git {} failed:\n{}".format(args, out))
        return out

    def commit_count(self):
        return int(self.git("rev-list", "--count", "HEAD").strip())

    def stub_calls(self):
        """Every argv the collector asked the ccusage stand-in to run."""
        if not os.path.exists(self.stub_log):
            return []
        with open(self.stub_log, "r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def requested_since(self):
        """The --since value of the first `daily` fetch, as YYYY-MM-DD."""
        for argv in self.stub_calls():
            if "daily" in argv and "--since" in argv:
                raw = argv[argv.index("--since") + 1]
                return dt.date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])).isoformat()
        return None

    def run(self, *args):
        if os.path.exists(self.stub_log):
            os.remove(self.stub_log)
        env = dict(os.environ)
        env["PATH"] = self.bin_dir + os.pathsep + env.get("PATH", "")
        env["STUB_CCUSAGE"] = self.payload_path
        env["STUB_CCUSAGE_LOG"] = self.stub_log
        proc = subprocess.run([sys.executable, self.script, "--config", self.config_path]
                              + list(args), cwd=self.root, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = (proc.stdout + proc.stderr).decode(errors="replace")
        if proc.returncode != 0:
            raise AssertionError("collect.py failed ({}):\n{}".format(proc.returncode, out))
        return out


def stats_line(output):
    """(written, skipped) parsed from the collector's summary line."""
    match = re.search(r"\b(\d+) day\(s\) (?:written|would be written), "
                      r"(\d+) unchanged old day\(s\) (?:skipped|would be skipped)", output)
    if not match:
        raise AssertionError("no written/skipped summary in output:\n{}".format(output))
    return int(match.group(1)), int(match.group(2))


class RecallWindowTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="collect-test-")
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def make(self, **kwargs):
        return CollectorEnv(self._tmp, **kwargs)

    def test_missing_watermark_floors_window_at_earliest_on_disk(self):
        env = self.make()  # no _meta.json at all
        env.write_day(iso(40), 100)
        env.write_day(iso(30), 100)
        env.write_day(iso(12), 100)
        payload = {"claude": [claude_row(iso(n), 10) for n in range(45, -1, -1)]}
        env.write_payload(payload)

        out = env.run()

        # The watermark is gone, so without the floor this would fetch from
        # 2000-01-01. It must start at our oldest recorded day instead.
        self.assertEqual(env.requested_since(), iso(40))
        self.assertIn("window={}..{}".format(iso(40), utc_today().isoformat()), out)
        # Days ccusage offered but that predate our data are not resurrected.
        self.assertIsNone(env.read_day(iso(45)))
        self.assertIsNone(env.read_day(iso(41)))
        # And the gap between our newest old day and today is backfilled.
        self.assertIsNotNone(env.read_day(iso(11)))
        self.assertIsNotNone(env.read_day(iso(0)))
        meta = env.read_meta()
        self.assertEqual(meta["last_success_date"], utc_today().isoformat())
        self.assertEqual(meta["earliest_date"], iso(40))

    def test_no_data_on_disk_keeps_all_time_window(self):
        env = self.make()
        env.write_payload({"claude": [claude_row(iso(90), 10), claude_row(iso(0), 10)]})

        out = env.run()

        self.assertEqual(env.requested_since(), "2000-01-01")
        self.assertIn("window=(all)..", out)
        self.assertIsNotNone(env.read_day(iso(90)))
        self.assertIsNotNone(env.read_day(iso(0)))

    def test_backdated_watermark_clamped_to_earliest_on_disk(self):
        env = self.make(recall={"max_days": 60})
        env.write_day(iso(30), 100)
        env.write_meta({"host": HOST, "timezone": "UTC",
                        "last_success_date": iso(300)})
        env.write_payload({"claude": [claude_row(iso(n), 10) for n in range(70, -1, -1)]})

        out = env.run()

        # clamp(gap + slack, 3, 60) = 60 -> start would be today-59, but on-disk
        # data starts at today-30, so the window is clamped forward.
        self.assertEqual(env.requested_since(), iso(30))
        self.assertIn("clamped", out)
        self.assertIsNone(env.read_day(iso(35)))

    def test_window_within_bounds_is_not_clamped(self):
        env = self.make()
        env.write_day(iso(40), 100)
        env.write_meta({"host": HOST, "timezone": "UTC",
                        "last_success_date": iso(10)})
        env.write_payload({"claude": [claude_row(iso(n), 10) for n in range(14, -1, -1)]})

        env.run()

        # clamp(10 + 2, 3, 21) = 12 -> today-11, later than the floor of -40.
        self.assertEqual(env.requested_since(), iso(11))

    def test_all_flag_is_an_explicit_full_backfill(self):
        env = self.make()
        env.write_day(iso(5), 100)  # floor would be today-5
        env.write_payload({"claude": [claude_row(iso(60), 10), claude_row(iso(5), 10)]})

        out = env.run("--all")

        self.assertEqual(env.requested_since(), "2000-01-01")
        self.assertIn("window=(all)..", out)
        self.assertIsNotNone(env.read_day(iso(60)))


class OldDayWriteTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="collect-test-")
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def make(self, **kwargs):
        return CollectorEnv(self._tmp, **kwargs)

    def test_old_day_smaller_reread_is_skipped_and_not_written(self):
        env = self.make()
        env.write_day(iso(10), 500)
        env.write_meta({"host": HOST, "timezone": "UTC",
                        "last_success_date": iso(10)})
        env.write_payload({"claude": [claude_row(iso(10), 400),
                                      claude_row(iso(3), 100)]})

        out = env.run()

        self.assertEqual(stats_line(out), (1, 1))
        record = env.read_day(iso(10))
        self.assertEqual(record["sources"]["claude"]["input"], 500)  # merge_max held
        self.assertEqual(record["collectedAt"], "2026-01-01T00:00:00Z")  # untouched
        self.assertEqual(env.read_day(iso(3))["sources"]["claude"]["input"], 100)
        # The run did write a day, so the watermark advances.
        self.assertEqual(env.read_meta()["last_success_date"], utc_today().isoformat())

    def test_old_day_larger_reread_is_merged_and_written(self):
        env = self.make()
        env.write_day(iso(10), 500)
        env.write_meta({"host": HOST, "timezone": "UTC",
                        "last_success_date": iso(10)})
        env.write_payload({"claude": [claude_row(iso(10), 800)]})

        out = env.run()

        self.assertEqual(stats_line(out), (1, 0))
        record = env.read_day(iso(10))
        self.assertEqual(record["sources"]["claude"]["input"], 800)
        self.assertEqual(record["sources"]["claude"]["total"], 801)
        self.assertNotEqual(record["collectedAt"], "2026-01-01T00:00:00Z")

    def test_all_unchanged_writes_nothing_and_makes_no_commit(self):
        env = self.make()
        env.write_day(iso(20), 500)
        env.write_day(iso(15), 600)
        env.write_meta({"host": HOST, "timezone": "UTC",
                        "last_success_date": iso(20), "earliest_date": iso(20)})
        env.write_payload({"claude": [claude_row(iso(20), 500),
                                      claude_row(iso(15), 600)]})
        meta_before = env.read_meta()
        commits_before = env.commit_count()

        out = env.run()

        self.assertEqual(stats_line(out), (0, 2))
        self.assertIn("nothing to write", out)
        self.assertEqual(env.read_meta(), meta_before)  # watermark not advanced
        self.assertEqual(env.commit_count(), commits_before)  # no empty commit
        self.assertEqual(env.read_day(iso(20))["collectedAt"], "2026-01-01T00:00:00Z")
        self.assertEqual(env.read_day(iso(15))["collectedAt"], "2026-01-01T00:00:00Z")

    def test_earliest_date_never_moves_forward(self):
        env = self.make()
        env.write_day(iso(50), 500)  # outside the recall window
        env.write_day(iso(10), 500)
        env.write_meta({"host": HOST, "timezone": "UTC",
                        "last_success_date": iso(10), "earliest_date": iso(50)})
        env.write_payload({"claude": [claude_row(iso(10), 500),
                                      claude_row(iso(3), 100)]})

        out = env.run()

        self.assertEqual(stats_line(out), (1, 1))
        meta = env.read_meta()
        self.assertEqual(meta["earliest_date"], iso(50))
        self.assertEqual(meta["latest_date"], iso(3))

    def test_dry_run_reports_both_sets_without_side_effects(self):
        env = self.make()
        env.write_day(iso(10), 500)
        env.write_meta({"host": HOST, "timezone": "UTC",
                        "last_success_date": iso(10)})
        env.write_payload({"claude": [claude_row(iso(10), 400),
                                      claude_row(iso(3), 100)]})
        meta_before = env.read_meta()
        day_before = env.read_day(iso(10))
        commits_before = env.commit_count()

        out = env.run("--dry-run")

        self.assertEqual(stats_line(out), (1, 1))
        self.assertIn("would write {}".format(os.path.join("data", HOST, iso(3) + ".json")), out)
        self.assertIn("would skip {}".format(iso(10)), out)
        self.assertIn("no files written, _meta.json unchanged, git untouched", out)
        self.assertEqual(env.read_meta(), meta_before)
        self.assertEqual(env.read_day(iso(10)), day_before)  # untouched
        self.assertIsNone(env.read_day(iso(3)))  # not created
        self.assertEqual(env.commit_count(), commits_before)

    def test_dry_run_all_skipped_reports_it(self):
        env = self.make()
        env.write_day(iso(20), 500)
        env.write_meta({"host": HOST, "timezone": "UTC",
                        "last_success_date": iso(20)})
        env.write_payload({"claude": [claude_row(iso(20), 500)]})
        commits_before = env.commit_count()

        out = env.run("--dry-run")

        self.assertEqual(stats_line(out), (0, 1))
        self.assertIn("nothing to write", out)
        self.assertEqual(env.commit_count(), commits_before)

    def test_empty_window_says_so_and_makes_no_commit(self):
        env = self.make()
        env.write_meta({"host": HOST, "timezone": "UTC",
                        "last_success_date": iso(1)})
        env.write_payload({"claude": []})
        meta_before = env.read_meta()
        commits_before = env.commit_count()

        out = env.run()

        self.assertIn("empty", out)
        self.assertIn("no files written, _meta.json unchanged, no commit", out)
        self.assertEqual(env.read_meta(), meta_before)
        self.assertEqual(env.commit_count(), commits_before)


if __name__ == "__main__":
    unittest.main()
