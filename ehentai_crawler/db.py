"""SQLite storage. The schema is the one the 2019 version created, so old
``list.db`` files work as they are.

Tags are stored as JSON (``{"namespace": ["tag", ...]}``). Rows written by the
2019 version hold the same structure as a Python literal; ``ast.literal_eval``
reads both forms.

Methods that change rows never commit on their own: wrap them in
:meth:`Database.transaction`, so a crash never leaves half a page written.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType

from .errors import CrawlerError
from .parse import TIME_FORMAT, GalleryInfo, ListEntry

log = logging.getLogger(__name__)

LIST_TABLE = "hentai_list"
PAGE_TABLE = "page_information"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS "{LIST_TABLE}" (
    "id"         INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
    "big_tag"    TEXT NOT NULL,
    "title"      TEXT NOT NULL,
    "timestamp"  INTEGER NOT NULL,
    "gallery_id" INTEGER NOT NULL UNIQUE,
    "uploader"   TEXT NOT NULL,
    "pages"      INTEGER NOT NULL,
    "url_hash"   TEXT NOT NULL,
    "removed"    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS "{PAGE_TABLE}" (
    "id"                   INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
    "gallery_id"           INTEGER NOT NULL UNIQUE,
    "tags"                 TEXT,
    "favorited_time"       INTEGER NOT NULL,
    "rating_count"         INTEGER NOT NULL,
    "average_score"        REAL NOT NULL,
    "last_update_time"     TEXT NOT NULL,
    "all_downloaded_check" INTEGER NOT NULL
);
"""

#: The crawl time is stored one hour early. The 2019 code did this (its comment
#: says "ehentai timezone UTC-1"); since the list shows UTC times it acts as a
#: safety margin, so a gallery changed shortly before a crawl is crawled again.
#: Kept so new rows compare the same way as rows from older databases.
CRAWL_TIME_MARGIN = timedelta(hours=1)


def parse_time(text: str) -> datetime:
    """Read a stored time; merges in the 2019 version also wrote seconds, which are ignored."""
    return datetime.strptime(str(text)[:16], TIME_FORMAT)


def format_time(moment: datetime) -> str:
    return moment.strftime(TIME_FORMAT)


def crawl_time(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return format_time(now - CRAWL_TIME_MARGIN)


def encode_tags(tags: dict[str, list[str]]) -> str:
    return json.dumps(tags, ensure_ascii=False)


@dataclass(frozen=True)
class StoredGallery:
    entry: ListEntry
    removed: int


@dataclass(frozen=True)
class StoredPage:
    gallery_id: int
    tags: str | None
    favorited_time: int
    rating_count: int
    average_score: float
    last_update_time: str
    all_downloaded_check: int


@dataclass
class MergeStats:
    list_added: int = 0
    list_updated: int = 0
    page_added: int = 0
    page_updated: int = 0


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        try:
            self.conn = sqlite3.connect(self.path)
            self.conn.executescript(SCHEMA)
        except sqlite3.Error as exc:
            raise CrawlerError(f"cannot open database {self.path}: {exc}") from exc

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Commit everything inside the block at once, or nothing on error."""
        with self.conn:
            yield

    # --- gallery list ------------------------------------------------------------

    def gallery_ids(self) -> set[int]:
        return {row[0] for row in self.conn.execute(f'SELECT gallery_id FROM "{LIST_TABLE}"')}

    def newest_list_time(self) -> datetime | None:
        row = self.conn.execute(f'SELECT timestamp FROM "{LIST_TABLE}" ORDER BY timestamp DESC LIMIT 1').fetchone()
        return parse_time(row[0]) if row else None

    def insert_list_entry(self, entry: ListEntry, removed: int = 0) -> None:
        self.conn.execute(
            f'INSERT INTO "{LIST_TABLE}" (big_tag, title, timestamp, gallery_id, uploader, pages, url_hash, removed) '
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.big_tag,
                entry.title,
                entry.timestamp,
                entry.gallery_id,
                entry.uploader,
                entry.pages,
                entry.url_hash,
                removed,
            ),
        )

    def update_list_entry(self, entry: ListEntry, removed: int = 0) -> None:
        """Refresh the columns the 2019 version refreshed when a gallery showed up again."""
        self.conn.execute(
            f'UPDATE "{LIST_TABLE}" SET timestamp = ?, pages = ?, url_hash = ?, removed = ? WHERE gallery_id = ?',
            (entry.timestamp, entry.pages, entry.url_hash, removed, entry.gallery_id),
        )

    def mark_removed(self, gallery_id: int, removed: int = 1) -> None:
        self.conn.execute(f'UPDATE "{LIST_TABLE}" SET removed = ? WHERE gallery_id = ?', (removed, gallery_id))

    def list_rows(self) -> dict[int, StoredGallery]:
        query = f'SELECT gallery_id, url_hash, big_tag, title, timestamp, uploader, pages, removed FROM "{LIST_TABLE}"'
        rows: dict[int, StoredGallery] = {}
        for gid, url_hash, big_tag, title, timestamp, uploader, pages, removed in self.conn.execute(query):
            entry = ListEntry(gid, url_hash, big_tag, title, str(timestamp), uploader, int(pages))
            rows[gid] = StoredGallery(entry, int(removed))
        return rows

    # --- gallery metadata --------------------------------------------------------

    def page_rows(self) -> dict[int, StoredPage]:
        query = (
            "SELECT gallery_id, tags, favorited_time, rating_count, average_score, last_update_time, "
            f'all_downloaded_check FROM "{PAGE_TABLE}"'
        )
        return {row[0]: StoredPage(*row) for row in self.conn.execute(query)}

    def save_page_info(self, gallery_id: int, info: GalleryInfo, last_update_time: str | None = None) -> None:
        """Insert or refresh a gallery's metadata; an existing download flag is left alone."""
        self._upsert_page(
            StoredPage(
                gallery_id,
                encode_tags(info.tags),
                info.favorited_time,
                info.rating_count,
                info.average_score,
                last_update_time or crawl_time(),
                0,
            )
        )

    def set_downloaded(self, gallery_id: int, complete: bool) -> None:
        self.conn.execute(
            f'UPDATE "{PAGE_TABLE}" SET all_downloaded_check = ? WHERE gallery_id = ?', (int(complete), gallery_id)
        )

    def _upsert_page(self, page: StoredPage) -> bool:
        """Update the row for ``page.gallery_id`` or insert it; return True when inserted."""
        cursor = self.conn.execute(
            f'UPDATE "{PAGE_TABLE}" SET tags = ?, favorited_time = ?, rating_count = ?, average_score = ?, '
            "last_update_time = ? WHERE gallery_id = ?",
            (
                page.tags,
                page.favorited_time,
                page.rating_count,
                page.average_score,
                page.last_update_time,
                page.gallery_id,
            ),
        )
        if cursor.rowcount:
            return False
        self.conn.execute(
            f'INSERT INTO "{PAGE_TABLE}" (gallery_id, tags, favorited_time, rating_count, average_score, '
            "last_update_time, all_downloaded_check) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                page.gallery_id,
                page.tags,
                page.favorited_time,
                page.rating_count,
                page.average_score,
                page.last_update_time,
                page.all_downloaded_check,
            ),
        )
        return True

    # --- merging another crawler's database (-ds) ---------------------------------

    def merge_from(self, other: Database) -> MergeStats:
        """Combine by gallery id: newer rows win, a "removed" mark from either side is
        kept, and the download flag stays local (the other machine's files are not here)."""
        stats = MergeStats()
        with self.transaction():
            mine = self.list_rows()
            for gid, theirs in other.list_rows().items():
                local = mine.get(gid)
                if local is None:
                    self.insert_list_entry(theirs.entry, theirs.removed)
                    stats.list_added += 1
                    continue
                removed = max(local.removed, theirs.removed)
                if parse_time(theirs.entry.timestamp) > parse_time(local.entry.timestamp):
                    self.update_list_entry(theirs.entry, removed)
                    stats.list_updated += 1
                elif removed != local.removed:
                    self.mark_removed(gid, removed)
                    stats.list_updated += 1

            my_pages = self.page_rows()
            for gid, page in other.page_rows().items():
                try:
                    theirs_time = parse_time(page.last_update_time)
                    local_page = my_pages.get(gid)
                    if local_page is not None and parse_time(local_page.last_update_time) >= theirs_time:
                        continue
                except ValueError:
                    log.warning("gallery %s: unreadable last_update_time in %s, skipped", gid, other.path)
                    continue
                incoming = StoredPage(
                    gid,
                    page.tags,
                    page.favorited_time,
                    page.rating_count,
                    page.average_score,
                    format_time(theirs_time),
                    0,
                )
                if self._upsert_page(incoming):
                    stats.page_added += 1
                else:
                    stats.page_updated += 1
        return stats
