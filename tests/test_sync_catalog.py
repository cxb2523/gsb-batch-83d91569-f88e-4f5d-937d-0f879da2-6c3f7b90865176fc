#!/usr/bin/env python3
"""Offline end-to-end tests for scripts/sync_catalog.py.

The suite builds throwaway catalog trees under the system temp directory and
drives the real sync entry point as a subprocess (``python -I``), so it never
touches the repository's data or depends on the network or coreclaw.com.

Scenarios covered:
  1. add    -> a newly added path lands in both README.md and its category page
  2. delete -> a removed path disappears from README.md and the category page
  3. illegal category + malformed URL -> non-zero exit, every problem reported
  4. duplicate path -> non-zero exit, every duplicated path reported
  5. idempotency -> a second run changes not a single byte (incl. line endings)
"""

from __future__ import annotations

import csv
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
SYNC = SCRIPTS_DIR / "sync_catalog.py"
VALIDATE = SCRIPTS_DIR / "validate_catalog.py"

FIELDS = [
    "title",
    "path",
    "url",
    "category",
    "source",
    "platform",
    "author",
    "description",
]


def worker(path: str, **overrides: str) -> dict[str, str]:
    author, slug = path.split("/", 1)
    row = {
        "title": slug.replace("-", " ").title(),
        "path": path,
        "url": f"https://www.coreclaw.com/{path}?fpr=chris69",
        "category": "AI & Research",
        "source": "Acme",
        "platform": "Other",
        "author": author,
        "description": f"Synthetic Worker for {path}.",
    }
    row.update(overrides)
    return row


def write_csv(csv_path: Path, rows: list[dict[str, str]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_banner(assets_dir: Path) -> None:
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "coreclaw-api-directory-banner.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n',
        encoding="utf-8",
        newline="\n",
    )


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def run_sync(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SYNC), "--root", str(root), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def run_validate(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(VALIDATE), "--root", str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


class SyncCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="sync-catalog-test-")
        self.root = Path(self._tmp)
        write_banner(self.root / "assets")
        self.csv_path = self.root / "data" / "workers.csv"
        self.readme = self.root / "README.md"
        self.category_page = self.root / "ai-research" / "README.md"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _base_rows(self) -> list[dict[str, str]]:
        return [
            worker("alice/alpha-worker"),
            worker("bob/beta-worker", category="News & Media", source="Daily Planet"),
        ]

    def test_add_scenario_populates_readme_and_category_page(self) -> None:
        write_csv(self.csv_path, self._base_rows())
        first = run_sync(self.root)
        self.assertEqual(first.returncode, 0, first.stderr)

        # A third, brand-new Worker is appended to the CSV, then re-synced.
        added = worker("carol/gamma-worker", source="Acme")
        write_csv(self.csv_path, [*self._base_rows(), added])
        second = run_sync(self.root)
        self.assertEqual(second.returncode, 0, second.stderr)

        readme_text = self.readme.read_text(encoding="utf-8")
        page_text = self.category_page.read_text(encoding="utf-8")
        self.assertIn("carol/gamma-worker", readme_text)
        self.assertIn("carol/gamma-worker", page_text)
        # The new entry carries the affiliate URL and an author attribution line.
        self.assertIn(
            "https://www.coreclaw.com/carol/gamma-worker?fpr=chris69", readme_text
        )
        self.assertIn("_— by carol_", readme_text)
        # Pre-existing paths are retained.
        for existing in ("alice/alpha-worker", "bob/beta-worker"):
            self.assertIn(existing, readme_text)

        # The standalone validator must accept the synchronized tree.
        self.assertEqual(run_validate(self.root).returncode, 0)

    def test_delete_scenario_removes_stale_links(self) -> None:
        rows = self._base_rows()
        write_csv(self.csv_path, rows)
        self.assertEqual(run_sync(self.root).returncode, 0)
        self.assertIn("alice/alpha-worker", self.readme.read_text(encoding="utf-8"))

        # Drop one row entirely and re-sync; no stale link may survive.
        write_csv(self.csv_path, [row for row in rows if row["path"] != "alice/alpha-worker"])
        result = run_sync(self.root)
        self.assertEqual(result.returncode, 0, result.stderr)

        readme_text = self.readme.read_text(encoding="utf-8")
        page_text = self.category_page.read_text(encoding="utf-8")
        self.assertNotIn("alice/alpha-worker", readme_text)
        self.assertNotIn("alice/alpha-worker", page_text)
        self.assertNotIn(
            "https://www.coreclaw.com/alice/alpha-worker?fpr=chris69", readme_text
        )
        # The surviving Worker is still listed.
        self.assertIn("bob/beta-worker", readme_text)
        self.assertEqual(run_validate(self.root).returncode, 0)

    def test_illegal_category_and_bad_url_report_every_problem_before_writing(self) -> None:
        bad_rows = [
            worker(
                "dan/bad-category",
                category="Made Up Category",
            ),
            worker(
                "eve/bad-url",
                url="https://example.com/no-affiliate-params",
            ),
            # A valid control row that must not rescue the run.
            worker("frank/valid-row"),
        ]
        write_csv(self.csv_path, bad_rows)
        before = snapshot(self.root)

        result = run_sync(self.root)
        self.assertNotEqual(result.returncode, 0)
        output = result.stderr

        # Both offending paths are named, not just the first one.
        self.assertIn("dan/bad-category", output)
        self.assertIn("eve/bad-url", output)
        # And each failing check is identified.
        self.assertIn("unknown category", output)
        self.assertIn("invalid affiliate URL", output)
        self.assertIn("Made Up Category", output)
        self.assertIn("https://example.com/no-affiliate-params", output)

        # No output file may have been created or modified on failure.
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.readme.exists())
        self.assertFalse(self.category_page.exists())

    def test_duplicate_paths_report_all_occurrences_and_abort(self) -> None:
        dup_rows = [
            worker("gina/duplicate-thing", title="First copy"),
            worker("henry/single-ok"),
            worker("gina/duplicate-thing", title="Second copy"),
        ]
        write_csv(self.csv_path, dup_rows)
        before = snapshot(self.root)

        result = run_sync(self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gina/duplicate-thing", result.stderr)
        self.assertIn("duplicate path", result.stderr)
        # Both CSV line numbers (header is line 1, data starts at 2) are shown.
        self.assertIn("rows 2, 4", result.stderr)
        self.assertEqual(snapshot(self.root), before)

    def test_second_run_is_byte_for_byte_idempotent(self) -> None:
        write_csv(self.csv_path, self._base_rows())
        first = run_sync(self.root)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("Synced", first.stdout)

        snapshot_after_first = snapshot(self.root)

        second = run_sync(self.root)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("already in sync", second.stdout)

        # Not a single byte may differ: content, line endings and final newline.
        self.assertEqual(snapshot(self.root), snapshot_after_first)
        for relative, content in snapshot_after_first.items():
            if relative.endswith(".md"):
                self.assertTrue(
                    content.endswith(b"\n"), f"{relative} must end with a newline"
                )
                self.assertNotIn(b"\r", content)

    def test_crlf_input_is_normalized_then_stable(self) -> None:
        write_csv(self.csv_path, self._base_rows())
        # Seed a README using Windows CRLF line endings.
        self.assertEqual(run_sync(self.root).returncode, 0)
        crlf_readme = self.readme.read_bytes().replace(b"\n", b"\r\n")
        self.readme.write_bytes(crlf_readme)

        first = run_sync(self.root)
        self.assertEqual(first.returncode, 0, first.stderr)
        after_first = snapshot(self.root)

        # The managed directory region is rewritten with LF endings, even when
        # the surrounding README originally used CRLF.
        text = self.readme.read_text(encoding="utf-8")
        start = text.index('<a id="directory"></a>')
        end = text.index("## Machine-readable catalog")
        managed = text[start:end]
        self.assertNotIn("\r", managed)

        second = run_sync(self.root)
        self.assertEqual(second.returncode, 0, second.stderr)
        # Second run must not touch a single byte.
        self.assertEqual(snapshot(self.root), after_first)

    def test_check_mode_fails_when_tree_is_stale_then_passes_after_sync(self) -> None:
        write_csv(self.csv_path, self._base_rows())
        stale = run_sync(self.root, "--check")
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("stale", stale.stderr)

        self.assertEqual(run_sync(self.root).returncode, 0)
        fresh = run_sync(self.root, "--check")
        self.assertEqual(fresh.returncode, 0, fresh.stderr)

    def test_explicit_marker_layout_is_supported_and_idempotent(self) -> None:
        # A README that opts into explicit managed-region markers. The markers
        # wrap the whole managed region, which itself begins at the #directory
        # anchor produced by the renderer.
        self.readme.write_text(
            "# Header\n\n"
            "<!-- CATALOG-DIRECTORY:START -->\n"
            '<a id="directory"></a>\nold region\n'
            "<!-- CATALOG-DIRECTORY:END -->\n\n"
            "## Machine-readable catalog\n",
            encoding="utf-8",
            newline="\n",
        )
        write_csv(self.csv_path, self._base_rows())
        self.assertEqual(run_sync(self.root).returncode, 0)
        once = self.readme.read_bytes()
        self.assertIn(b"alice/alpha-worker", once)
        self.assertIn(b"<!-- CATALOG-DIRECTORY:START -->", once)
        self.assertIn(b"<!-- CATALOG-DIRECTORY:END -->", once)
        self.assertEqual(run_sync(self.root).returncode, 0)
        self.assertEqual(self.readme.read_bytes(), once)


if __name__ == "__main__":
    unittest.main(verbosity=2)
