from __future__ import annotations

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

# Support "python -I" execution: ensure sibling modules are importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_category_pages import CATEGORIES


ROOT = Path(__file__).resolve().parents[1]
CATEGORY_SLUGS = {name: slug for name, slug, _emoji, _summary, _anchor in CATEGORIES}

REQUIRED_FIELDS = {
    "title",
    "path",
    "url",
    "category",
    "source",
    "platform",
    "author",
    "description",
}
AFFILIATE_URL = re.compile(
    r"^https://www\.coreclaw\.com/[^/?]+/[^/?]+\?fpr=chris69$"
)


def _display(path: Path, root: Path) -> str:
    """Render a path relative to root when possible, for readable errors."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def collect_validation_errors(
    root: Path | None = None,
    csv_path: Path | None = None,
    readme_path: Path | None = None,
    banner_path: Path | None = None,
    category_root: Path | None = None,
) -> list[str]:
    """Return every catalog problem found, one message per problem.

    An empty list means the catalog is valid. Paths in messages are kept
    relative to ``root`` so the same code serves the real repo and temp trees.
    """
    root = root or ROOT
    csv_path = csv_path or root / "data" / "workers.csv"
    readme_path = readme_path or root / "README.md"
    banner_path = banner_path or root / "assets" / "coreclaw-api-directory-banner.svg"
    category_root = category_root or root

    errors: list[str] = []

    if not csv_path.is_file():
        return [f"missing {_display(csv_path, root)}"]
    if not readme_path.is_file():
        errors.append("missing README.md")
    if not banner_path.is_file():
        errors.append(f"missing {_display(banner_path, root)}")

    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing_fields = REQUIRED_FIELDS - fields
        if missing_fields:
            return [f"CSV is missing fields: {', '.join(sorted(missing_fields))}"]
        rows = list(reader)

    if not rows:
        return ["catalog is empty"]

    paths = [row["path"].strip() for row in rows]
    duplicate_paths = sorted(path for path, count in Counter(paths).items() if count > 1)
    if duplicate_paths:
        errors.append(f"duplicate Worker paths: {', '.join(duplicate_paths)}")

    for index, row in enumerate(rows, start=2):
        worker_path = row["path"].strip() or f"<row {index}>"
        empty = sorted(field for field in REQUIRED_FIELDS if not row[field].strip())
        if empty:
            errors.append(
                f"CSV row {index} (path {worker_path}) has empty fields: "
                f"{', '.join(empty)}"
            )
        if not AFFILIATE_URL.fullmatch(row["url"].strip()):
            errors.append(
                f"CSV row {index} (path {worker_path}) has an invalid affiliate URL: "
                f"{row['url']}"
            )

    if readme_path.is_file():
        readme = readme_path.read_text(encoding="utf-8")
        missing_from_readme = [path for path in paths if path not in readme]
        if missing_from_readme:
            errors.append(
                f"README ({_display(readme_path, root)}) is missing {len(missing_from_readme)} "
                f"Worker paths: {', '.join(missing_from_readme)}"
            )

    for row in rows:
        category_slug = CATEGORY_SLUGS.get(row["category"])
        if category_slug is None:
            errors.append(
                f"unknown category {row['category']!r} for path {row['path'].strip()}"
            )
            continue
        category_page = category_root / category_slug / "README.md"
        if not category_page.is_file():
            errors.append(f"missing category page: {_display(category_page, root)}")
        elif row["path"].strip() not in category_page.read_text(encoding="utf-8"):
            errors.append(
                f"{_display(category_page, root)} is missing Worker path: "
                f"{row['path'].strip()}"
            )

    if banner_path.is_file():
        try:
            document = ET.parse(banner_path).getroot()
        except ET.ParseError as error:
            errors.append(f"banner SVG is invalid: {error}")
        else:
            if not document.tag.endswith("svg"):
                errors.append("banner asset is not an SVG document")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate the Worker CSV, README directory and category pages."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root containing data/workers.csv (default: repo root)",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    errors = collect_validation_errors(root=root)
    if errors:
        for message in errors:
            print(f"ERROR: {message}", file=sys.stderr)
        raise SystemExit(1)

    with (root / "data" / "workers.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    category_counts = Counter(row["category"].strip() for row in rows)
    source_count = len({row["source"].strip() for row in rows})
    print(
        f"Catalog valid: {len(rows)} Workers, "
        f"{len(category_counts)} categories, {source_count} sources."
    )
    for category, count in sorted(category_counts.items()):
        print(f"  {count:>3}  {category}")


if __name__ == "__main__":
    main()
