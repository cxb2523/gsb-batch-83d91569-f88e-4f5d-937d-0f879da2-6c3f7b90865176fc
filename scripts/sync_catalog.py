#!/usr/bin/env python3
"""Synchronize the main README directory and category pages with workers.csv.

Pipeline (all steps run from this single entry point):

    data/workers.csv
        -> validate every record (categories, affiliate URLs, unique paths, ...)
        -> regenerate the README.md directory region (add/update/remove entries)
        -> regenerate every category page
        -> run the full catalog validation

The command is idempotent: running it a second time against an unchanged CSV
writes nothing and leaves every file byte-for-byte identical, including line
endings and the trailing newline. Any failure exits non-zero and reports the
offending Worker path, file and check; data problems are collected in full
before any file is written.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Allow sibling-module imports even under "python -I" (isolated mode), where
# the script directory is not automatically placed on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_category_pages import (
    CATEGORIES,
    expected_pages,
    group_by_category,
    load_workers,
)
from validate_catalog import AFFILIATE_URL, REQUIRED_FIELDS, collect_validation_errors


ROOT = Path(__file__).resolve().parents[1]

# Optional explicit markers. When present they delimit the managed region;
# otherwise the script falls back to the stable landmarks already used by the
# real README (the "#directory" anchor and the "Machine-readable catalog" heading).
DIRECTORY_START_MARKER = "<!-- CATALOG-DIRECTORY:START -->"
DIRECTORY_END_MARKER = "<!-- CATALOG-DIRECTORY:END -->"
DIRECTORY_ANCHOR = '<a id="directory"></a>'
NEXT_SECTION_HEADING = "## Machine-readable catalog"


class SyncError(Exception):
    """Raised when synchronization cannot complete; the message lists every cause."""


def _display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def preflight(
    csv_path: Path, root: Path
) -> tuple[list[dict[str, str]], list[str]]:
    """Validate raw CSV content without touching any output file.

    Returns the parsed rows and a list of human-readable problems. Every
    problem is reported (the function never stops at the first one). Each
    message names the Worker path and the failing check so a maintainer can
    fix the CSV directly.
    """
    if not csv_path.is_file():
        return [], [f"missing data file: {_display(csv_path, root)}"]

    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing_fields = REQUIRED_FIELDS - fieldnames
        if missing_fields:
            return [], [
                f"{_display(csv_path, root)} is missing required CSV fields: "
                f"{', '.join(sorted(missing_fields))}"
            ]
        rows = list(reader)

    errors: list[str] = []
    if not rows:
        return [], ["catalog is empty: data/workers.csv contains no Worker rows"]

    seen = Counter(row["path"].strip() for row in rows)
    duplicate_paths = sorted(path for path, count in seen.items() if count > 1)
    for path in duplicate_paths:
        line_numbers = [
            str(index)
            for index, row in enumerate(rows, start=2)
            if row["path"].strip() == path
        ]
        errors.append(
            f"duplicate path {path!r} appears {seen[path]} times "
            f"({_display(csv_path, root)} rows {', '.join(line_numbers)})"
        )

    known_categories = {name for name, *_rest in CATEGORIES}
    for index, row in enumerate(rows, start=2):
        path = row["path"].strip() or f"<row {index}>"
        empty = sorted(field for field in REQUIRED_FIELDS if not row[field].strip())
        if empty:
            errors.append(
                f"path {path!r}: {_display(csv_path, root)} row {index} has empty "
                f"required fields: {', '.join(empty)}"
            )
        category = row["category"].strip()
        if category and category not in known_categories:
            errors.append(
                f"path {path!r}: unknown category {category!r} "
                f"(not one of the {len(CATEGORIES)} CATEGORIES entries)"
            )
        url = row["url"].strip()
        if url and not AFFILIATE_URL.fullmatch(url):
            errors.append(
                f"path {path!r}: invalid affiliate URL {url!r}; expected "
                "https://www.coreclaw.com/<author>/<slug>?fpr=chris69"
            )

    return rows, errors


def render_worker_entry(worker: dict[str, str]) -> list[str]:
    suffix = f' _— by {worker["author"].strip()}_' if worker["author"].strip() != "CoreClaw" else ""
    return [
        f'- [**{worker["title"]}**]({worker["url"].strip()}) '
        f'— `{worker["path"].strip()}`<br>',
        f'  {worker["description"]}{suffix}',
    ]


def render_readme_directory(workers: list[dict[str, str]]) -> str:
    """Render the managed README directory region (no trailing newline)."""
    grouped = group_by_category(workers)
    lines = [
        DIRECTORY_ANCHOR,
        "## Directory",
        "",
        "The directory is organized first by **use case**, then by **source**. "
        "Expand a section to browse every Worker. Each title opens the exact "
        "Worker page with affiliate attribution preserved.",
        "",
    ]

    for name, slug, emoji, summary, readme_anchor in CATEGORIES:
        category_workers = grouped.get(name, [])
        sources: dict[str, list[dict[str, str]]] = defaultdict(list)
        for worker in category_workers:
            sources[worker["source"]].append(worker)
        source_word = "source" if len(sources) == 1 else "sources"

        lines.extend(
            [
                f'<a id="{readme_anchor}"></a>',
                "<details>",
                f"<summary><strong>{emoji} {name}</strong> · "
                f"{len(category_workers)} APIs across {len(sources)} {source_word}</summary>",
                "",
                "<br>",
                "",
            ]
        )

        for source in sorted(sources, key=str.casefold):
            source_workers = sorted(
                sources[source], key=lambda row: row["title"].casefold()
            )
            lines.extend([f"### {source} <sup>{len(source_workers)}</sup>", ""])
            for worker in source_workers:
                lines.extend(render_worker_entry(worker))
            lines.append("")

        lines.extend(["</details>", ""])

    return "\n".join(lines)


def _minimal_readme(region: str) -> str:
    # Mirrors the landmark splice: region already ends in one blank line, so
    # only a single separating newline precedes the next heading.
    return (
        "# CoreClaw API Directory\n\n"
        f"{region}\n"
        f"{NEXT_SECTION_HEADING}\n"
    )


def splice_readme(original: str | None, region: str, readme_path: Path, root: Path) -> str:
    """Return README content with its managed directory region replaced.

    Two layouts are supported. Explicit ``CATALOG-DIRECTORY`` markers delimit
    the region and are preserved around the new content; otherwise the shipped
    landmark layout (the ``#directory`` anchor up to the
    ``Machine-readable catalog`` heading) is used. A missing README gets a
    minimal skeleton.
    """
    region = region.replace("\r\n", "\n")
    if original is None:
        return _minimal_readme(region)

    original = original.replace("\r\n", "\n")
    if DIRECTORY_START_MARKER in original and DIRECTORY_END_MARKER in original:
        start = original.index(DIRECTORY_START_MARKER)
        end = original.index(DIRECTORY_END_MARKER) + len(DIRECTORY_END_MARKER)
        managed = f"{DIRECTORY_START_MARKER}\n{region}\n{DIRECTORY_END_MARKER}"
        return original[:start] + managed + original[end:]

    if DIRECTORY_ANCHOR in original and NEXT_SECTION_HEADING in original:
        start = original.index(DIRECTORY_ANCHOR)
        end = original.index(NEXT_SECTION_HEADING)
        return original[:start] + region + "\n" + original[end:]

    raise SyncError(
        f"cannot locate the managed directory region in {_display(readme_path, root)}: "
        f"add {DIRECTORY_START_MARKER}/{DIRECTORY_END_MARKER} markers or the "
        f"{DIRECTORY_ANCHOR!r} landmark"
    )


def update_readme(readme_path: Path, region: str, root: Path) -> bool:
    """Write README.md only when the spliced content actually changes."""
    original = (
        readme_path.read_text(encoding="utf-8") if readme_path.is_file() else None
    )
    updated = splice_readme(original, region, readme_path, root)
    if original is not None and original.replace("\r\n", "\n") == updated:
        return False
    readme_path.parent.mkdir(parents=True, exist_ok=True)
    readme_path.write_text(updated, encoding="utf-8", newline="\n")
    return True


def write_if_changed(path: Path, content: str) -> bool:
    """Write ``content`` with LF endings only when the bytes actually change."""
    content = content.replace("\r\n", "\n")
    if path.is_file() and path.read_text(encoding="utf-8").replace("\r\n", "\n") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return True


def sync_catalog(
    root: Path,
    csv_path: Path | None = None,
    readme_path: Path | None = None,
    category_root: Path | None = None,
    banner_path: Path | None = None,
    check: bool = False,
) -> list[str]:
    """Run the full synchronization pipeline.

    Returns the list of files (display paths) whose content changed. Raises
    SyncError with the complete list of problems on any failure.
    """
    root = root.resolve()
    csv_path = (csv_path or root / "data" / "workers.csv").resolve()
    readme_path = (readme_path or root / "README.md").resolve()
    category_root = (category_root or root).resolve()
    banner_path = (
        banner_path or root / "assets" / "coreclaw-api-directory-banner.svg"
    ).resolve()

    # 1) Validate the CSV fully before writing anything.
    rows, problems = preflight(csv_path, root)
    if problems:
        raise SyncError(
            "aborted before writing any file; the CSV has "
            f"{len(problems)} problem(s):\n" + "\n".join(f"  - {item}" for item in problems)
        )

    workers = load_workers(csv_path)

    # 2) Build every output in memory first, so a rendering error also leaves
    #    the working tree untouched.
    region = render_readme_directory(workers)
    pages = expected_pages(
        workers=workers, category_root=category_root, csv_path=csv_path
    )

    if check:
        stale: list[str] = []
        current_readme = (
            readme_path.read_text(encoding="utf-8") if readme_path.is_file() else None
        )
        expected_readme = splice_readme(
            current_readme, region, readme_path, root
        )
        if (
            current_readme is None
            or current_readme.replace("\r\n", "\n") != expected_readme
        ):
            stale.append(_display(readme_path, root))
        for page_path, content in pages.items():
            if (
                not page_path.is_file()
                or page_path.read_text(encoding="utf-8").replace("\r\n", "\n")
                != content.replace("\r\n", "\n")
            ):
                stale.append(_display(page_path, root))
        if stale:
            raise SyncError(
                "generated files are stale, run without --check to sync:\n"
                + "\n".join(f"  - {item}" for item in stale)
            )
        return []

    # 3) Apply changes.
    changed: list[str] = []
    if update_readme(readme_path, region, root):
        changed.append(_display(readme_path, root))
    for page_path, content in pages.items():
        if write_if_changed(page_path, content):
            changed.append(_display(page_path, root))

    # 4) Run the full validator over the freshly written tree.
    validation_errors = collect_validation_errors(
        root=root,
        csv_path=csv_path,
        readme_path=readme_path,
        banner_path=banner_path,
        category_root=category_root,
    )
    if validation_errors:
        raise SyncError(
            "post-sync validation failed:\n"
            + "\n".join(f"  - {item}" for item in validation_errors)
        )

    return changed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync README.md and category pages with data/workers.csv."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root containing data/workers.csv (default: repo root)",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="override the workers.csv path (default: <root>/data/workers.csv)",
    )
    parser.add_argument(
        "--readme",
        type=Path,
        default=None,
        help="override the main README path (default: <root>/README.md)",
    )
    parser.add_argument(
        "--category-root",
        type=Path,
        default=None,
        help="directory holding the category folders (default: <root>)",
    )
    parser.add_argument(
        "--banner",
        type=Path,
        default=None,
        help="override the banner SVG path used by validation",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when README or category pages would change",
    )
    args = parser.parse_args()

    try:
        changed = sync_catalog(
            root=args.root,
            csv_path=args.csv,
            readme_path=args.readme,
            category_root=args.category_root,
            banner_path=args.banner,
            check=args.check,
        )
    except SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from None

    if args.check:
        print("Catalog in sync: README.md and all category pages match workers.csv.")
    elif not changed:
        print("Catalog already in sync: no files changed.")
    else:
        print(f"Synced {len(changed)} file(s):")
        for path in changed:
            print(f"  updated {path}")


if __name__ == "__main__":
    main()
