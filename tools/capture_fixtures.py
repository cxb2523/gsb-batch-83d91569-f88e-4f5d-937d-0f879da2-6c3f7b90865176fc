#!/usr/bin/env python3
"""Capture PSX HTML/JSON fixtures from AJAX endpoints for unit tests.

All captures use plain requests — no Playwright needed.
Run when PSX changes a page structure or on demand to refresh fixtures.

Usage:
    python tools/capture_fixtures.py                             # capture all
    python tools/capture_fixtures.py --fixture screener          # capture one
    python tools/capture_fixtures.py --list                      # list available
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import requests

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"

BASE_URL = "https://dps.psx.com.pk"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://dps.psx.com.pk/",
    "X-Requested-With": "XMLHttpRequest",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _stamp_html(url: str, html: str) -> str:
    today = date.today()
    return (
        f"<!-- Captured: {today} | Source: {url} -->\n"
        "<!-- Re-capture: python tools/capture_fixtures.py -->\n"
        + html
    )


def _stamp_json(url: str, data: object) -> str:
    today = date.today()
    return json.dumps(
        {"_meta": {"captured": str(today), "source": url}, "data": data},
        indent=2,
    )


def _capture_get_html(endpoint: str, filename: str) -> tuple[Path, int]:
    url = f"{BASE_URL}{endpoint}"
    resp = _session().get(url, timeout=30)
    resp.raise_for_status()
    content = _stamp_html(url, resp.text)
    out = FIXTURES_DIR / filename
    out.write_text(content, encoding="utf-8")
    return out, len(content.encode())


def _capture_post_html(
    endpoint: str, data: dict, filename: str
) -> tuple[Path, int]:
    url = f"{BASE_URL}{endpoint}"
    resp = _session().post(url, data=data, timeout=30)
    resp.raise_for_status()
    content = _stamp_html(url, resp.text)
    out = FIXTURES_DIR / filename
    out.write_text(content, encoding="utf-8")
    return out, len(content.encode())


def _capture_get_json(endpoint: str, filename: str) -> tuple[Path, int]:
    url = f"{BASE_URL}{endpoint}"
    resp = _session().get(url, timeout=30)
    resp.raise_for_status()
    content = _stamp_json(url, resp.json())
    out = FIXTURES_DIR / filename
    out.write_text(content, encoding="utf-8")
    return out, len(content.encode())


FIXTURES = {
    "historical_engro": {
        "description": "POST /historical {symbol: ENGRO}",
        "fn": lambda: _capture_post_html(
            "/historical", {"symbol": "ENGRO"}, "historical_engro.html"
        ),
    },
    "trading_board_reg_main": {
        "description": "GET /trading-board/REG/main",
        "fn": lambda: _capture_get_html(
            "/trading-board/REG/main", "trading_board_reg_main.html"
        ),
    },
    "trading_board_reg_gem": {
        "description": "GET /trading-board/REG/gem",
        "fn": lambda: _capture_get_html(
            "/trading-board/REG/gem", "trading_board_reg_gem.html"
        ),
    },
    "trading_board_bnb_bnb": {
        "description": "GET /trading-board/BNB/bnb",
        "fn": lambda: _capture_get_html(
            "/trading-board/BNB/bnb", "trading_board_bnb_bnb.html"
        ),
    },
    "symbols": {
        "description": "GET /symbols (JSON)",
        "fn": lambda: _capture_get_json("/symbols", "symbols.json"),
    },
    "sector_summary": {
        "description": "GET /sector-summary/sectorwise",
        "fn": lambda: _capture_get_html(
            "/sector-summary/sectorwise", "sector_summary.html"
        ),
    },
    "financial_reports": {
        "description": "GET /financial-reports-list",
        "fn": lambda: _capture_get_html(
            "/financial-reports-list", "financial_reports.html"
        ),
    },
    "indices_kse100": {
        "description": "GET /indices/KSE100",
        "fn": lambda: _capture_get_html(
            "/indices/KSE100", "indices_kse100.html"
        ),
    },
    "screener": {
        "description": "GET /screener",
        "fn": lambda: _capture_get_html("/screener", "screener.html"),
    },
    "debt_market": {
        "description": "GET /debt-market",
        "fn": lambda: _capture_get_html("/debt-market", "debt_market.html"),
    },
    "eligible_scrips": {
        "description": "GET /eligible-scrips",
        "fn": lambda: _capture_get_html(
            "/eligible-scrips", "eligible_scrips.html"
        ),
    },
    "trading_panel": {
        "description": "GET /trading-panel (index summary tables)",
        "fn": lambda: _capture_get_html(
            "/trading-panel", "trading_panel.html"
        ),
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture PSX HTML/JSON fixtures for unit tests"
    )
    parser.add_argument(
        "--fixture",
        choices=list(FIXTURES.keys()),
        help="Capture only this fixture",
    )
    parser.add_argument(
        "--list", action="store_true", help="List available fixtures"
    )
    args = parser.parse_args()

    if args.list:
        for name, spec in FIXTURES.items():
            print(f"  {name:<30} {spec['description']}")
        return

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    targets = (
        {args.fixture: FIXTURES[args.fixture]} if args.fixture else FIXTURES
    )
    failed = False

    for name, spec in targets.items():
        print(
            f"  Capturing {name} ({spec['description']}) ...",
            end=" ",
            flush=True,
        )
        try:
            path, size = spec["fn"]()
            print(f"done — {path} ({size:,} bytes)")
        except Exception as exc:
            print(f"FAILED: {exc}")
            failed = True

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
