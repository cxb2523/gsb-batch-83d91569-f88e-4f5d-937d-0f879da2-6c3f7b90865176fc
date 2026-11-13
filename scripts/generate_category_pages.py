#!/usr/bin/env python3
"""Generate browsable category pages from the canonical Worker CSV."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "workers.csv"
CATEGORY_ROOT = ROOT

# (display name, directory slug, emoji, summary, main-README anchor)
CATEGORIES = (
    (
        "E-Commerce & Marketplaces",
        "e-commerce-marketplaces",
        "🛍️",
        "Products, pricing, reviews, stores, suppliers and marketplace intelligence.",
        "commerce",
    ),
    (
        "Social & Creator Data",
        "social-creator-data",
        "🌐",
        "Profiles, posts, comments, creators, events and audience signals.",
        "social",
    ),
    (
        "Search, Maps & SEO",
        "search-maps-seo",
        "🔎",
        "SERPs, maps, local business data, keywords and SEO intelligence.",
        "search",
    ),
    (
        "Jobs & Recruiting",
        "jobs-recruiting",
        "💼",
        "Job listings, candidate discovery, employers, salaries and recruiting data.",
        "jobs",
    ),
    (
        "Lead Generation & Company Intelligence",
        "lead-generation-company-intelligence",
        "🎯",
        "Companies, decision-makers, suppliers, business emails and sales prospects.",
        "leads",
    ),
    (
        "AI & Research",
        "ai-research",
        "✨",
        "AI answers, cited sources and structured research workflows.",
        "ai",
    ),
    (
        "Developer & Web Utilities",
        "developer-web-utilities",
        "🧰",
        "Browser automation, extraction, screenshots, parsing and data utilities.",
        "developer-tools",
    ),
    (
        "Finance & Markets",
        "finance-markets",
        "📈",
        "Public-market, company and financial time-series data.",
        "finance",
    ),
    (
        "Real Estate",
        "real-estate",
        "🏠",
        "Property listings, valuations, history and location data.",
        "real-estate",
    ),
    (
        "Education & Knowledge",
        "education-knowledge",
        "📚",
        "Courses, books, metadata and learning catalog intelligence.",
        "knowledge",
    ),
    (
        "News & Media",
        "news-media",
        "📰",
        "News articles, media pages and publication monitoring.",
        "news",
    ),
)


def table_text(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")


def link_text(value: str) -> str:
    return table_text(value).replace("[", "\\[").replace("]", "\\]")


def anchor_slug(value: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def load_workers(csv_path: Path | None = None) -> list[dict[str, str]]:
    """Read and order every Worker row from the canonical CSV."""
    path = csv_path or CSV_PATH
    with path.open(encoding="utf-8", newline="") as handle:
        workers = list(csv.DictReader(handle))
    workers.sort(key=lambda row: (row["category"], row["source"], row["title"].casefold()))
    return workers


def group_by_category(
    workers: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for worker in workers:
        grouped[worker["category"]].append(worker)
    return grouped


def unknown_categories(workers: list[dict[str, str]]) -> list[str]:
    known = {name for name, *_rest in CATEGORIES}
    return sorted({row["category"].strip() for row in workers} - known)


def render_category(
    name: str,
    emoji: str,
    summary: str,
    workers: list[dict[str, str]],
) -> str:
    sources: dict[str, list[dict[str, str]]] = defaultdict(list)
    for worker in workers:
        sources[worker["source"]].append(worker)

    lines = [
        '<p align="center"><a href="../README.md#categories">← All categories</a> · '
        '<a href="../README.md">Main directory</a></p>',
        "",
        f"# {emoji} {name}",
        "",
        summary,
        "",
        f"**{len(workers)} APIs** across **{len(sources)} data sources**",
        "",
        "## Sources",
        "",
        " · ".join(
            f"[{source}](#{anchor_slug(source)})"
            for source in sorted(sources, key=str.casefold)
        ),
        "",
    ]

    for source in sorted(sources, key=str.casefold):
        source_workers = sorted(sources[source], key=lambda row: row["title"].casefold())
        lines.extend(
            [
                f'<a id="{anchor_slug(source)}"></a>',
                f"## {source} ({len(source_workers)})",
                "",
                "| API | Worker ID | What it does |",
                "|---|---|---|",
            ]
        )
        for worker in source_workers:
            lines.append(
                f'| [**{link_text(worker["title"])}**]({worker["url"]}) '
                f'| `{table_text(worker["path"])}` '
                f'| {table_text(worker["description"])} |'
            )
        lines.append("")

    lines.extend(
        [
            "> [!NOTE]",
            "> Links open the exact CoreClaw Worker page and include the maintainer’s "
            "affiliate attribution. See the main README for the full disclosure.",
            "",
            '<p align="center"><a href="../README.md#categories">← Browse all categories</a> · '
            '<a href="../README.md#directory">Complete API directory</a></p>',
            "",
        ]
    )
    return "\n".join(lines)


def expected_pages(
    workers: list[dict[str, str]] | None = None,
    category_root: Path | None = None,
    csv_path: Path | None = None,
) -> dict[Path, str]:
    """Map every category page path to its rendered content."""
    if workers is None:
        workers = load_workers(csv_path)
    root = category_root or CATEGORY_ROOT
    grouped = group_by_category(workers)

    unknown = unknown_categories(workers)
    if unknown:
        raise ValueError(f"Unknown categories in CSV: {', '.join(unknown)}")

    pages = {}
    for name, slug, emoji, summary, _readme_anchor in CATEGORIES:
        pages[root / slug / "README.md"] = render_category(
            name, emoji, summary, grouped[name]
        )
    return pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when generated category pages are missing or stale",
    )
    args = parser.parse_args()

    pages = expected_pages()
    stale = []
    for path, content in pages.items():
        content = content.replace("\r\n", "\n")
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8").replace("\r\n", "\n") != content:
                stale.append(path.relative_to(ROOT))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    if stale:
        print("Generated category pages are stale:", file=sys.stderr)
        for path in stale:
            print(f"  {path}", file=sys.stderr)
        print("Run: python scripts/generate_category_pages.py", file=sys.stderr)
        raise SystemExit(1)

    action = "Verified" if args.check else "Generated"
    print(f"{action} {len(pages)} category pages.")


if __name__ == "__main__":
    main()
