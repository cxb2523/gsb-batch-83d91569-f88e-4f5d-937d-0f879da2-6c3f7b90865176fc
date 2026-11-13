"""Refresh pipeline: download from the sources, validate, and write to SQLite.

Steps (each logged in refresh_log, each isolated so one failure doesn't stop the rest):
  1. universe     - check every scheme code against AMFI's scheme master
  2. nav          - full NAV history for every verified fund
  3. market_cap   - AMFI's large / mid / small cap list
  4. holdings     - month-end portfolios from each AMC connector

Sources are injected (see `Sources`) so tests can run the whole pipeline offline.
"""
from __future__ import annotations

import calendar
import hashlib
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from smt import settings, store, universe
from smt.holdings.connectors import Connector, DisclosureFile, default_connectors
from smt.sources import amfi, mfapi

log = logging.getLogger("smt.pipeline")


@dataclass
class Sources:
    scheme_master: Callable[[], pd.DataFrame] = amfi.fetch_scheme_master
    nav_history: Callable[[str], tuple[str, pd.DataFrame]] = mfapi.fetch_history
    market_cap: Callable[[], tuple[str, pd.DataFrame]] = amfi.fetch_market_cap
    connectors: dict[str, Connector] = field(default_factory=default_connectors)
    raw_dir: Path = settings.RAW_DIR      # downloaded disclosure files are kept here
    # The holdings window is computed from this. Tests pin it so a refresh does not
    # depend on the wall clock.
    today: Callable[[], date] = date.today


def cached_download(connector: Connector, f: DisclosureFile, raw_dir: Path) -> bytes:
    """Download a disclosure file once and keep it, so re-parsing never re-downloads.

    Month-end files don't change after publication, and keeping the originals
    means every number in the database can be traced back to its source file.
    """
    name = f.url.split("?")[0].rsplit("/", 1)[-1]
    path = raw_dir / connector.name / f"{hashlib.sha1(f.url.encode()).hexdigest()[:10]}_{name}"
    if path.exists():
        return path.read_bytes()
    content = connector.download(f)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


@dataclass
class Report:
    verified: int = 0
    mismatched: list[str] = field(default_factory=list)
    nav_rows: int = 0
    holdings_rows: int = 0
    files: int = 0
    errors: list[str] = field(default_factory=list)
    # One entry per (connector, month-end) with its status: ok | missing |
    # download_failed | parse_failed | no_schemes | discover_failed. The same
    # outcomes are stored in disclosure_files.
    holdings_outcomes: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Steps
# --------------------------------------------------------------------------- #
def refresh_universe(con: sqlite3.Connection, src: Sources, report: Report) -> None:
    with store.job(con, "universe") as info:
        master = src.scheme_master().set_index("scheme_code")
        rows = []
        for f in universe.FUNDS:
            amfi_row = master.loc[f.scheme_code] if f.scheme_code in master.index else None
            if isinstance(amfi_row, pd.DataFrame):
                amfi_row = amfi_row.iloc[0]
            published = "" if amfi_row is None else str(amfi_row["scheme_name"])
            ok = universe.normalise(published) == universe.normalise(f.expected_name)
            if not ok:
                report.mismatched.append(
                    f"{f.scheme_code}: expected '{f.expected_name}', AMFI says '{published or 'not found'}'")
            rows.append({
                "scheme_code": f.scheme_code, "scheme_name": published or f.expected_name,
                "expected_name": f.expected_name, "amc": f.amc,
                "category": None if amfi_row is None else amfi_row["category"],
                "holdings_source": f.holdings, "is_benchmark": int(f.is_benchmark),
                "verified": int(ok), "verified_at": store.now(),
            })
        with con:
            store.upsert_funds(con, rows)
        report.verified = sum(r["verified"] for r in rows)
        info["rows"] = report.verified
        if report.mismatched:
            info["status"] = "warning"
            info["message"] = "; ".join(report.mismatched)


def refresh_nav(con: sqlite3.Connection, src: Sources, report: Report) -> None:
    codes = store.funds(con)["scheme_code"].tolist()
    with store.job(con, "nav") as info:
        failed = []
        for code in codes:
            try:
                _, df = src.nav_history(code)
                if df.empty:
                    raise ValueError("no NAV rows")
                report.nav_rows += store.replace_nav(con, code, df)
            except Exception as e:  # noqa: BLE001 - one fund failing must not stop the rest
                failed.append(f"{code}: {e}")
                log.warning("NAV %s failed: %s", code, e)
        info["rows"] = report.nav_rows
        if failed:
            report.errors += failed
            info["status"], info["message"] = "warning", "; ".join(failed)


def refresh_market_cap(con: sqlite3.Connection, src: Sources, report: Report) -> None:
    with store.job(con, "market_cap") as info:
        try:
            label, df = src.market_cap()
            info["rows"] = store.replace_market_cap(con, df, label)
            info["message"] = f"AMFI list for six months ended {label}"
        except Exception as e:  # noqa: BLE001
            report.errors.append(f"market_cap: {e}")
            info["status"], info["message"] = "warning", str(e)


# --------------------------------------------------------------------------- #
# Holdings
# --------------------------------------------------------------------------- #
def month_ends(today: date, months: int) -> list[date]:
    """The `months` most recent month-ends at or before `today`, newest first.

    A month still in progress has not had its disclosure published yet, so the
    window starts from the previous month when `today` is mid-month. Otherwise
    every refresh early in a month would report the running month as missing.
    """
    last = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    if last > today:
        last = date(today.year, today.month, 1) - timedelta(days=1)
    out = []
    for _ in range(max(months, 0)):
        out.append(last)
        last = date(last.year, last.month, 1) - timedelta(days=1)
    return out


def _ingest_file(con: sqlite3.Connection, connector: Connector, f: DisclosureFile,
                 targets: dict[str, str], report: Report, raw_dir: Path) -> tuple[str, int, int, str | None]:
    """Download, parse and store one disclosure file.

    Returns (status, schemes matched, bytes, detail) where status is one of
    download_failed, parse_failed, no_schemes or ok. A failure here is one file's
    outcome, never an exception that escapes the month or AMC loop.
    """
    name = f.url.rsplit("/", 1)[-1]
    try:
        content = cached_download(connector, f, raw_dir)
    except Exception as e:  # noqa: BLE001 - classified as a download failure
        return "download_failed", 0, 0, f"{name}: {e}"
    try:
        portfolios = connector.parse(content)
        matched = 0
        for p in portfolios:
            code = targets.get(universe.normalise(p.scheme_title))
            if code is None:
                continue
            as_of = (p.as_of or f.as_of).isoformat()
            report.holdings_rows += store.replace_holdings(con, code, as_of, p.holdings)
            matched += 1
    except Exception as e:  # noqa: BLE001 - a bad workbook must not stop other months
        return "parse_failed", 0, len(content), f"{name}: {e}"
    report.files += 1
    if not matched:
        return "no_schemes", 0, len(content), f"{name}: parsed but matched no tracked scheme"
    return "ok", matched, len(content), None


def _save_outcome(con: sqlite3.Connection, report: Report, connector: str, month: date,
                  status: str, *, url: str | None = None, size: int | None = None,
                  matched: int = 0, detail: str | None = None) -> None:
    """Store one AMC-month outcome and add it to the report."""
    as_of = month.isoformat()
    store.record_file(con, connector, as_of, url=url, size=size, matched=matched,
                      status=status, detail=detail)
    report.holdings_outcomes.append({
        "connector": connector, "as_of": as_of, "status": status,
        "url": url, "schemes_matched": matched, "detail": detail,
    })


# Worse outcomes win when one month has several files (PPFAS publishes one per scheme).
_WORST_FIRST = ("parse_failed", "download_failed")


def refresh_holdings(con: sqlite3.Connection, src: Sources, report: Report,
                     months: int = settings.HOLDINGS_MONTHS) -> None:
    """Give every tracked AMC-month in the window an explicit outcome.

    A month never disappears just because no file was found for it: each month gets
    a disclosure_files row (status missing / download_failed / parse_failed /
    no_schemes / ok) and a line in the job message. One bad month or AMC does not
    stop the others; it only turns the job into a warning.
    """
    window = month_ends(src.today(), months)
    funds = store.funds(con)
    for name, connector in src.connectors.items():
        targets = {
            universe.normalise(r.expected_name): r.scheme_code
            for r in funds.itertuples() if r.holdings_source == name
        }
        if not targets:
            continue
        with store.job(con, f"holdings:{name}") as info:
            try:
                files = connector.discover()
            except Exception as e:  # noqa: BLE001 - the other AMCs still run
                reason = f"could not list files: {e}"
                report.errors.append(f"{name}: {reason}")
                # Without a listing no month can be judged, so every month in the
                # window is recorded as unknown rather than silently omitted.
                for month in window:
                    _save_outcome(con, report, name, month, "discover_failed", detail=reason)
                info["message"] = reason
                info["status"] = "warning"
                continue

            by_month: dict[date, list[DisclosureFile]] = {}
            for f in files:
                by_month.setdefault(f.as_of, []).append(f)

            problems: list[str] = []
            for month in window:
                month_files = by_month.get(month, [])
                if not month_files:
                    _save_outcome(con, report, name, month, "missing", detail="no file found on the page")
                    problems.append(f"{month.isoformat()}: no file found on the page")
                    continue
                results = [_ingest_file(con, connector, f, targets, report, src.raw_dir)
                           for f in month_files]
                matched = sum(r[1] for r in results)
                size = sum(r[2] for r in results)
                failures = [(r[0], r[3]) for r in results if r[0] in ("download_failed", "parse_failed")]
                if failures:
                    # Other files for the same month may still have loaded; the month
                    # is flagged because part of it is missing.
                    status = next(s for s in _WORST_FIRST if s in [f[0] for f in failures])
                    detail = "; ".join(d for _, d in failures if d)
                    problems.append(f"{month.isoformat()}: {status.replace('_', ' ')}: {detail}")
                elif matched:
                    status, detail = "ok", None
                else:
                    status = "no_schemes"
                    detail = "no file for this month matched a tracked scheme"
                    problems.append(f"{month.isoformat()}: {detail}")
                _save_outcome(con, report, name, month, status, url="; ".join(f.url for f in month_files),
                              size=size or None, matched=matched, detail=detail)
                info["rows"] += matched
            if problems:
                report.errors += [f"{name} {p}" for p in problems]
                info["status"], info["message"] = "warning", "; ".join(problems)


def refresh(db_path=None, months: int = settings.HOLDINGS_MONTHS, holdings: bool = True,
            src: Sources | None = None) -> Report:
    src = src or Sources()
    report = Report()
    con = store.connect(db_path)
    try:
        refresh_universe(con, src, report)
        refresh_nav(con, src, report)
        refresh_market_cap(con, src, report)
        if holdings:
            refresh_holdings(con, src, report, months)
    finally:
        con.close()
    return report
