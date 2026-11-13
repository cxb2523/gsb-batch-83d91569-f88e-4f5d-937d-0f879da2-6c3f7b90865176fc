"""
page_manifest.py
----------------
The per-page manifest of a search run: `<out>.pages.json`, written beside the
output on EVERY search run, whatever the exit code.

Why it exists
-------------
This site's API does not validate what it is given (a page past the end is
answered with page 1 again), so a run plans its pages from the page count the
site states on page 1 and then works through them. A run stopped halfway — a
refusal, a transport timeout — used to leave no record of WHICH pages it
holds and which it never got, so the next run could only start over. The
manifest is that record: one entry per page with the page's status, how many
rows it yielded, and why it failed when it did. `--resume` reads it and
fetches only the pages that are not already `success`.

The file
--------
    {
      "version": 1,
      "mode": "search",
      "query": {...},            # page_flow.query_summary
      "currency": "BRL",         # null until a run read it
      "total_results": 1844,     # the site's own counts, from page 1
      "pages_available": 40,
      "pages": [
        {"page": 1, "status": "success", "rows": 100, "error": null,
         "items": [...]},        # the rows themselves, as the JSON output
                                # holds them, so a resume needs nothing else
        {"page": 2, "status": "failed", "rows": 0,
         "error": "refused: cloudfront"},
        {"page": 3, "status": "pending", "rows": 0, "error": null}
      ]
    }

Statuses are `success`, `failed` and `pending` (planned but never attempted —
the run stopped before reaching the page). A failed entry's `error` names the
kind of failure: `refused: ...` (CloudFront / PerimeterX), `transport: ...`
(a timeout, a dead exit) or `site-error: ...` (the gateway's 403, a throttle,
a payload the parser could not read).

`items` is what makes a resume self-contained: the rows of a completed page
are recovered from the manifest itself, so the resumed run's output is the
union of the manifest's completed pages and what it fetches, in page order,
and `--format csv` runs resume exactly like JSON ones.

Reading is deliberately suspicious. A missing, unparseable or truncated
manifest is not an error — the run treats it as absent and starts fresh. A
page number that appears twice (a hand edit, two runs racing one prefix) is
resolved LAST-WINS, and a `success` entry that holds no `items` is not
believed, because skipping the page would silently drop its rows from the
union; it is fetched again instead.

Nothing here imports a browser or page_flow (page_flow imports THIS), so the
manifest can be read and written in processes that never open one.
"""

import json
import logging
from dataclasses import asdict, fields
from typing import Any, Dict, List, Optional

from output_writer import ROW_CLASS_BY_MODE, Listing, _atomic

log = logging.getLogger("page_manifest")

SUCCESS = "success"
FAILED = "failed"
PENDING = "pending"
STATUSES = (SUCCESS, FAILED, PENDING)

MANIFEST_VERSION = 1


def manifest_path(out_prefix: str) -> str:
    """The manifest belonging to an output prefix: `<out>.pages.json`."""
    return f"{out_prefix}.pages.json"


def entry(page: int, status: str, rows: int = 0,
          error: Optional[str] = None,
          items: Optional[List[dict]] = None) -> dict:
    """One page's record. `items` is kept only for a success."""
    e = {"page": int(page), "status": status, "rows": int(rows),
         "error": error}
    if status == SUCCESS:
        e["items"] = list(items or [])
    return e


class Manifest:
    """A parsed `<out>.pages.json`: the run-level counts plus one entry per
    page (duplicates already resolved, last win)."""

    def __init__(self, currency=None, total_results=None, pages_available=None,
                 query=None, entries=None):
        self.currency = currency
        self.total_results = total_results
        self.pages_available = pages_available
        self.query = query or {}
        self.entries: Dict[int, dict] = entries or {}

    def successful_pages(self) -> List[int]:
        return sorted(n for n, e in self.entries.items()
                      if e["status"] == SUCCESS)


def _coerce_entry(raw: Any) -> Optional[dict]:
    """One entry from the file, normalised, or None if it names no page.

    A `success` without its `items` is downgraded to a failure that names the
    problem, so the page is fetched again rather than its rows silently
    dropped from the resumed output.
    """
    if not isinstance(raw, dict):
        return None
    try:
        page = int(raw.get("page"))
    except (TypeError, ValueError):
        return None
    if page < 1:
        return None
    status = raw.get("status")
    if status not in STATUSES:
        status = PENDING
    items = raw.get("items")
    error = raw.get("error") if isinstance(raw.get("error"), str) else None
    if status == SUCCESS:
        if isinstance(items, list):
            return entry(page, SUCCESS, len(items), None, items)
        return entry(page, FAILED, 0,
                     "manifest: success entry held no rows; refetching")
    try:
        rows = int(raw.get("rows") or 0)
    except (TypeError, ValueError):
        rows = 0
    return entry(page, status, rows, error)


def load(path: str) -> Optional[Manifest]:
    """Read a manifest, or return None when there is none worth trusting.

    None — a fresh run — on: no file, unreadable file, invalid JSON, a top
    level that is not an object, or a `pages` that is not a list. Never
    raises: a corrupt manifest must not crash a run that could simply start
    over.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        log.info("No usable page manifest at %s (%s).", path, e)
        return None
    if not isinstance(data, dict) or not isinstance(data.get("pages"), list):
        log.info("No usable page manifest at %s (not a manifest's shape).", path)
        return None
    entries: Dict[int, dict] = {}
    for raw in data["pages"]:
        e = _coerce_entry(raw)
        if e is None:
            continue
        # A page recorded twice: the LAST record is the truth.
        entries[e["page"]] = e
    return Manifest(currency=data.get("currency"),
                    total_results=data.get("total_results"),
                    pages_available=data.get("pages_available"),
                    query=data.get("query") if isinstance(data.get("query"), dict) else {},
                    entries=entries)


def write(path: str, *, query: dict, currency, total_results,
          pages_available, entries: List[dict]) -> str:
    """Write the manifest atomically; return its path.

    One entry per page, in page order — the writer never emits duplicates, so
    the reader's last-wins rule only ever fires on a file someone else
    touched.
    """
    by_page: Dict[int, dict] = {}
    for e in entries:
        by_page[e["page"]] = e  # last wins here too, on principle
    payload = {
        "version": MANIFEST_VERSION,
        "mode": "search",
        "query": query or {},
        "currency": currency,
        "total_results": total_results,
        "pages_available": pages_available,
        "pages": [by_page[n] for n in sorted(by_page)],
    }
    with _atomic(path) as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("Wrote the page manifest -> %s (%d page(s): %d ok, %d failed, "
             "%d not attempted).", path, len(payload["pages"]),
             sum(1 for e in payload["pages"] if e["status"] == SUCCESS),
             sum(1 for e in payload["pages"] if e["status"] == FAILED),
             sum(1 for e in payload["pages"] if e["status"] == PENDING))
    return path


# ---------------------------------------------------------------------------
# PageOutcome <-> entry. Duck-typed on purpose: page_flow imports this
# module, so the outcome's class cannot be named here.
# ---------------------------------------------------------------------------

def failure_reason(outcome) -> str:
    """The `error` string for a failed page: what kind of failure it was."""
    if getattr(outcome, "blocked_by", None):
        return "refused: %s" % outcome.blocked_by
    if getattr(outcome, "rejected", None):
        return "site-error: %s" % outcome.rejected
    if getattr(outcome, "unread", False):
        return "site-error: payload shape not recognised"
    state = getattr(outcome, "state", None) or ""
    if state == "throttled":
        return "site-error: throttled (HTTP 429)"
    return "transport: %s" % (state or "the request never completed")


def entry_from_outcome(outcome) -> dict:
    """The manifest entry for one fetched page, rows included on success."""
    if outcome.ok:
        items = [asdict(r) for r in outcome.products]
        return entry(outcome.page_num, SUCCESS, len(items), None, items)
    return entry(outcome.page_num, FAILED, 0, failure_reason(outcome))


def rows_from_entry(e: dict, mode: str = "search") -> List:
    """The rows a success entry holds, as row objects of the mode's class.

    Keys the current row class no longer knows are dropped rather than
    failing: a manifest written by a newer version must still resume.
    """
    row_cls = ROW_CLASS_BY_MODE.get(mode, Listing)
    known = {f.name for f in fields(row_cls)}
    rows = []
    for d in e.get("items") or []:
        if not isinstance(d, dict):
            continue
        rows.append(row_cls(**{k: v for k, v in d.items() if k in known}))
    return rows
