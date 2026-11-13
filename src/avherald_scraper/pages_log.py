"""One JSON file describing the listing pages a run requested.

The crawl writes this file once, after the walk, so a run that ends normally
always leaves a complete file that can be parsed. Each entry says whether the
page came back, was blocked, or failed outright, and how many requests it took
across proxy retries.

`crawl_state` still holds the bookmark. The `resume_url` in this file is the
same value, repeated here so the next position can be checked without opening
SQLite.
"""

#  @name:           The Aviation Herald (avherald)
#  @description     Unofficial CLI tool to scrape data from avherald.com and store it in a .sqlite database.
#  @author          Kolja Nolte <kolja.nolte@gmail.com>
#  @copyright       2025-2026 (C) Kolja Nolte
#  @see             https://docs.kolja-nolte.com/av-herald
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  Released under the GNU General Public License v2 or later.
#  See: https://www.gnu.org/licenses/gpl-2.0.html
#
#  @package AVH
#  @license GPL-2.0-or-later

# Annotations can mention types defined further down.
from __future__ import annotations

# The file is JSON, so the standard library encoder is enough.
import json

# Replace is atomic on the same filesystem, which keeps the log complete.
import os

# One frozen record per requested page.
from dataclasses import dataclass

# The timestamp is UTC and written as ISO 8601.
from datetime import UTC, datetime

# Callers pass either a string path or a pathlib path.
from pathlib import Path

# Only the three outcomes the crawl can report.
OK = "ok"

# Every configured proxy returned the IP-block page.
BLOCKED = "blocked"

# An HTTP or network error survived every proxy attempt.
FAILED = "failed"

# The legal values for PageRecord.status.
PAGE_STATUSES = (OK, BLOCKED, FAILED)


# Frozen so a finished run cannot change what it wrote.
@dataclass(frozen=True)
class PageRecord:
    """What happened to one listing URL in one run."""

    # The URL that was requested. A proxy retry does not get its own record.
    url: str

    # One of ok, blocked, or failed.
    status: str

    # Real requests sent for this URL, across all proxies.
    attempts: int

    # Short reason when the page did not come back. None on success.
    error: str | None = None

    def as_dict(self) -> dict[str, str | int | None]:
        """Return the shape this record has inside the JSON `pages` array."""

        # Key order matches the documented format.
        return {
            "url": self.url,
            "status": self.status,
            "attempts": self.attempts,
            "error": self.error,
        }


def _iso_utc(moment: datetime) -> str:
    """Render a timestamp as a UTC ISO 8601 string."""

    # A naive value is treated as UTC, not as the machine's local time.
    if moment.tzinfo is None:
        # Pin it before converting.
        moment = moment.replace(tzinfo=UTC)

    # Drop microseconds so the value is stable and readable.
    return moment.astimezone(UTC).replace(microsecond=0).isoformat()


def build_payload(
        *,
        run_started_at: datetime,
        pages: list[PageRecord] | tuple[PageRecord, ...],
        resume_url: str | None,
) -> dict[str, object]:
    """Assemble the document written to disk."""

    # `pages` keeps the order the crawl requested them in.
    return {
        "run_started_at": _iso_utc(run_started_at),
        "pages": [page.as_dict() for page in pages],
        "resume_url": resume_url,
    }


def write_pages_log(
        path: str | Path,
        *,
        run_started_at: datetime,
        pages: list[PageRecord] | tuple[PageRecord, ...],
        resume_url: str | None,
) -> Path:
    """Write the page log and return the path that was written.

    The JSON is fully built before anything touches the disk. It goes to a
    temporary sibling first and is then replaced into place, so a reader never
    sees half a file. Any filesystem error is raised as OSError.
    """

    # Accept a string from a caller that did not convert it.
    target = Path(path)

    # The default path sits beside the database, and that folder may be new.
    target.parent.mkdir(parents=True, exist_ok=True)

    # One complete document. The trailing newline keeps text tools happy.
    text = json.dumps(
        build_payload(run_started_at=run_started_at, pages=pages, resume_url=resume_url),
        indent=2,
        ensure_ascii=False,
    ) + "\n"

    # Same directory, so the final replace stays atomic.
    temp = target.with_name(target.name + ".tmp")

    try:
        # UTF-8 is what the rest of the project writes.
        temp.write_text(text, encoding="utf-8")

        # Another process sees either the old file or this complete one.
        os.replace(temp, target)

    # A read-only folder, a full disk, or a directory in the way.
    except OSError:
        # Do not leave a half-written sibling behind.
        try:
            # Best effort. The original error is the one worth reporting.
            temp.unlink()

        # The temp file may never have been created.
        except OSError:
            # Nothing else to clean up.
            pass

        # main() turns this into exit code 1.
        raise

    # Callers put this on the result and in `--show-config`.
    return target
