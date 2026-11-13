from __future__ import annotations

import ast
import json
import sqlite3
from contextlib import closing
from datetime import datetime

from ehentai_crawler.db import Database, crawl_time
from ehentai_crawler.parse import GalleryInfo, ListEntry

#: The CREATE statements of the 2019 version, verbatim.
SCHEMA_2019 = [
    """CREATE TABLE IF NOT EXISTS "hentai_list" (
	                            "id"	INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
	                            "big_tag"	TEXT NOT NULL,
	                            "title"	TEXT NOT NULL,
	                            "timestamp"	INTEGER NOT NULL,
	                            "gallery_id"	INTEGER NOT NULL UNIQUE,
	                            "uploader"	TEXT NOT NULL,
	                            "pages"	INTEGER NOT NULL,
                                "url_hash"	TEXT NOT NULL,
                                "removed"	INTEGER NOT NULL
                            );""",
    """CREATE TABLE IF NOT EXISTS "page_information" (
	                            "id"	INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT UNIQUE,
	                            "gallery_id"	INTEGER NOT NULL UNIQUE,
                                "tags"	TEXT,
                                "favorited_time"	INTEGER NOT NULL,
                                "rating_count"	INTEGER NOT NULL,
                                "average_score"	REAL NOT NULL,
                                "last_update_time"	TEXT NOT NULL,
                                "all_downloaded_check" INTEGER NOT NULL
                            );""",
]

ENTRY = ListEntry(1005, "0a1b2c3d4e", "Misc", "Sample Gallery One", "2026-01-03 10:00", "uploader-a", 3)
INFO = GalleryInfo({"sample": ["alpha", "beta two"]}, 12, 7, 4.25)


def columns(path, table):
    with closing(sqlite3.connect(path)) as conn, conn:
        return [(row[1], row[2], row[3], row[5]) for row in conn.execute(f'PRAGMA table_info("{table}")')]


def old_database(path, list_rows=(), page_rows=()):
    with closing(sqlite3.connect(path)) as conn, conn:
        for statement in SCHEMA_2019:
            conn.execute(statement)
        conn.executemany('INSERT INTO "hentai_list" VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?)', list_rows)
        conn.executemany('INSERT INTO "page_information" VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)', page_rows)
    return path


def test_schema_is_the_2019_schema(tmp_path):
    Database(tmp_path / "new.db").close()
    old_database(tmp_path / "old.db")
    for table in ("hentai_list", "page_information"):
        assert columns(tmp_path / "new.db", table) == columns(tmp_path / "old.db", table)


def test_opens_a_2019_database_as_is(tmp_path):
    old_tags = str({"sample": ["alpha"]})  # the 2019 version stored str(dict)
    path = old_database(
        tmp_path / "old.db",
        [("Misc", "Sample", "2019-08-04 03:18", 7, "uploader-a", 5, "abcdef0123", 0)],
        [(7, old_tags, 1, 2, 3.5, "2019-08-15 21:31:00", 1)],  # seconds came from the old merge
    )
    with Database(path) as db:
        assert db.gallery_ids() == {7}
        assert db.newest_list_time() == datetime(2019, 8, 4, 3, 18)
        page = db.page_rows()[7]
        assert ast.literal_eval(page.tags) == {"sample": ["alpha"]}


def test_list_insert_update_and_newest_time(tmp_path):
    with Database(tmp_path / "list.db") as db:
        assert db.newest_list_time() is None
        with db.transaction():
            db.insert_list_entry(ENTRY)
            db.insert_list_entry(ListEntry(1004, "5f6a7b8c9d", "Misc", "Two", "2026-01-02 09:30", "b", 1))
        assert db.newest_list_time() == datetime(2026, 1, 3, 10, 0)

        with db.transaction():
            db.mark_removed(1005)
        assert db.list_rows()[1005].removed == 1
        with db.transaction():  # showing up in the list again clears the mark, as in 2019
            db.update_list_entry(ListEntry(1005, "ffffffffff", "Misc", "x", "2026-02-01 00:00", "a", 4))
        stored = db.list_rows()[1005]
        assert (stored.removed, stored.entry.url_hash, stored.entry.pages) == (0, "ffffffffff", 4)


def test_changes_outside_a_transaction_are_not_committed(tmp_path):
    db = Database(tmp_path / "list.db")
    db.insert_list_entry(ENTRY)
    db.close()
    with Database(tmp_path / "list.db") as reopened:
        assert reopened.gallery_ids() == set()


def test_page_info_is_json_and_keeps_the_download_flag(tmp_path):
    with Database(tmp_path / "list.db") as db:
        with db.transaction():
            db.save_page_info(1005, INFO, "2026-01-04 00:00")
            db.set_downloaded(1005, True)
        with db.transaction():
            db.save_page_info(1005, GalleryInfo({}, 13, 8, 4.5), "2026-01-05 00:00")
        page = db.page_rows()[1005]
    assert (page.favorited_time, page.all_downloaded_check, page.last_update_time) == (13, 1, "2026-01-05 00:00")
    assert json.loads(page.tags) == {}


def test_tags_keep_non_ascii_text_readable(tmp_path):
    with Database(tmp_path / "list.db") as db:
        with db.transaction():
            db.save_page_info(1, GalleryInfo({"language": ["日本語"]}, 0, 0, 0.0))
        tags = db.page_rows()[1].tags
    assert "日本語" in tags and json.loads(tags) == ast.literal_eval(tags)


def test_crawl_time_is_one_hour_early():
    assert crawl_time(datetime(2026, 1, 4, 12, 30)) == "2026-01-04 11:30"


def test_merge_adds_new_rows_and_takes_newer_ones(tmp_path):
    with Database(tmp_path / "mine.db") as mine, Database(tmp_path / "theirs.db") as theirs:
        with mine.transaction():
            mine.insert_list_entry(ENTRY)
            mine.save_page_info(1005, INFO, "2026-01-04 00:00")
            mine.set_downloaded(1005, True)
        with theirs.transaction():
            theirs.insert_list_entry(ListEntry(1005, "0a1b2c3d4e", "Misc", "x", "2026-01-09 00:00", "a", 9))
            theirs.insert_list_entry(ListEntry(1001, "c1d2e3f4a5", "Misc", "y", "2025-12-30 12:00", "c", 1))
            theirs.save_page_info(1005, GalleryInfo({}, 99, 9, 5.0), "2026-01-08 00:00")
            theirs.save_page_info(1001, INFO, "2026-01-01 00:00")
            theirs.set_downloaded(1001, True)

        stats = mine.merge_from(theirs)

        assert (stats.list_added, stats.list_updated, stats.page_added, stats.page_updated) == (1, 1, 1, 1)
        assert mine.list_rows()[1005].entry.pages == 9
        pages = mine.page_rows()
        assert (pages[1005].favorited_time, pages[1005].all_downloaded_check) == (99, 1)  # flag stays local
        assert pages[1001].all_downloaded_check == 0  # their files are not on this machine


def test_merge_keeps_a_removed_mark_from_the_other_side(tmp_path):
    """Regression: the 2019 merge meant to keep "removed" but the line had no effect."""
    with Database(tmp_path / "mine.db") as mine, Database(tmp_path / "theirs.db") as theirs:
        with mine.transaction():
            mine.insert_list_entry(ENTRY)
        with theirs.transaction():
            theirs.insert_list_entry(ENTRY, removed=1)
        mine.merge_from(theirs)
        assert mine.list_rows()[1005].removed == 1


def test_merge_ignores_older_rows_and_reads_old_times_with_seconds(tmp_path):
    other = old_database(
        tmp_path / "old.db",
        [("Misc", "Sample", "2026-01-01 00:00", 1005, "a", 3, "0a1b2c3d4e", 0)],
        [(1005, "{}", 1, 1, 1.0, "2026-01-01 00:00:59", 0), (7, "{}", 1, 1, 1.0, "not a time", 0)],
    )
    with Database(tmp_path / "mine.db") as mine, Database(other) as theirs:
        with mine.transaction():
            mine.insert_list_entry(ENTRY)
            mine.save_page_info(1005, INFO, "2026-01-04 00:00")
        stats = mine.merge_from(theirs)
        assert (stats.list_updated, stats.page_updated, stats.page_added) == (0, 0, 0)
        assert mine.page_rows()[1005].favorited_time == 12
