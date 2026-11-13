"""Explicit transactional schema migrations. Never reset an unknown database."""
from __future__ import annotations

import sqlite3

from ..review.models import ReviewError

SCHEMA_VERSION = 1
MIGRATIONS = {1: (
    """CREATE TABLE runs (
        run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('success','partial','failed')),
        metadata TEXT NOT NULL)""",
    """CREATE TABLE events (
        event_id TEXT PRIMARY KEY, latest_run TEXT NOT NULL REFERENCES runs(run_id),
        payload TEXT NOT NULL)""",
    """CREATE TABLE event_identity_map (
        event_id TEXT PRIMARY KEY REFERENCES events(event_id), anchor_raw_item_id TEXT NOT NULL,
        anchor_slot TEXT NOT NULL, first_run TEXT NOT NULL REFERENCES runs(run_id),
        last_run TEXT NOT NULL REFERENCES runs(run_id))""",
    """CREATE TABLE event_snapshots (
        run_id TEXT NOT NULL REFERENCES runs(run_id), event_id TEXT NOT NULL REFERENCES events(event_id),
        ordinal INTEGER NOT NULL, visible INTEGER NOT NULL CHECK(visible IN (0,1)), payload TEXT NOT NULL,
        PRIMARY KEY(run_id,event_id))""",
    """CREATE TABLE event_review (
        event_id TEXT PRIMARY KEY REFERENCES events(event_id), decision TEXT NOT NULL,
        notes TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    """CREATE TABLE place_snapshots (
        run_id TEXT NOT NULL REFERENCES runs(run_id), candidate_id TEXT NOT NULL,
        payload TEXT NOT NULL, PRIMARY KEY(run_id,candidate_id))""",
    """CREATE TABLE place_review (
        run_id TEXT NOT NULL, candidate_id TEXT NOT NULL, decision TEXT NOT NULL,
        notes TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(run_id,candidate_id),
        FOREIGN KEY(run_id,candidate_id) REFERENCES place_snapshots(run_id,candidate_id))""",
    """CREATE TABLE duplicate_review (
        pair_key TEXT PRIMARY KEY, event_id_a TEXT NOT NULL REFERENCES events(event_id),
        event_id_b TEXT NOT NULL REFERENCES events(event_id), decision TEXT NOT NULL,
        notes TEXT NOT NULL, updated_at TEXT NOT NULL,
        first_seen_run TEXT NOT NULL REFERENCES runs(run_id), last_seen_run TEXT NOT NULL REFERENCES runs(run_id),
        CHECK(event_id_a < event_id_b), UNIQUE(event_id_a,event_id_b))""",
    """CREATE TABLE duplicate_snapshots (
        run_id TEXT NOT NULL REFERENCES runs(run_id), pair_key TEXT NOT NULL REFERENCES duplicate_review(pair_key),
        payload TEXT NOT NULL, PRIMARY KEY(run_id,pair_key))""",
    """CREATE TABLE review_exports (
        token TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('event','place','duplicate')),
        identity TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES runs(run_id),
        decision TEXT NOT NULL, notes TEXT NOT NULL)""",
)}


def migrate(connection: sqlite3.Connection) -> None:
    connection.execute('BEGIN IMMEDIATE')
    try:
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise ReviewError('Database schema is newer than this application; no state was changed.')
        if version == 0 and connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone():
            raise ReviewError('Unversioned database contains tables; refusing to replace existing state.')
        for next_version in range(version + 1, SCHEMA_VERSION + 1):
            for statement in MIGRATIONS[next_version]:
                connection.execute(statement)
            connection.execute(f'PRAGMA user_version = {next_version}')
        connection.commit()
    except Exception:
        connection.rollback()
        raise
