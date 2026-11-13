"""Authoritative, serialized MCP health checks with a shared durable history."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from pathlib import Path

from . import health
from .checks import CHECK_TOOL, MESSAGES, PLATFORMS, PROBES, SCHEMA_VERSION, classify, configuration_revision


class HealthChecks:
    cooldown = 60
    timeout = 40
    probe_gap = 1

    def __init__(self, platforms, path=None, config=None):
        self.platforms = platforms
        self.path = Path(path) if path else Path.home() / '.webmirage/health-checks.sqlite3'
        self.config = config
        self.lock = asyncio.Lock()
        self.initialized = False

    def _db(self):
        if not self.initialized:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        if not self.initialized:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS checks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL,
                    platform TEXT NOT NULL, tool TEXT NOT NULL, category TEXT NOT NULL,
                    elapsed_ms INTEGER, revision TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS checks_tool ON checks(tool,id);
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
            ''')
            if 'backend' not in {r[1] for r in db.execute('PRAGMA table_info(checks)')}:
                db.execute("ALTER TABLE checks ADD COLUMN backend TEXT NOT NULL DEFAULT ''")
                db.execute("UPDATE checks SET backend='http' WHERE platform='reddit'")
            db.execute('INSERT OR IGNORE INTO state VALUES (?,?)', ('store_id', uuid.uuid4().hex))
            db.commit()
            self.path.chmod(0o600)
            self.initialized = True
        return db

    def _config(self):
        if self.config is None:
            from .config import get_config
            return get_config()
        return self.config()

    def _revision(self, platform):
        return configuration_revision(self._config(), platform)

    def _public(self, row, store_id, cached=False):
        result = {key: row[key] for key in ('timestamp', 'platform', 'tool', 'category', 'elapsed_ms')}
        result['backend'] = row['backend']
        result.update(id=f'{store_id}:{row["id"]}', sequence=row['id'], cached=cached,
                      checker=CHECK_TOOL, credential_current=row['revision'] == self._revision(row['platform']),
                      message=MESSAGES[row['category']][0], advice=MESSAGES[row['category']][1])
        return result

    def _latest(self, name):
        db = self._db()
        try:
            store_id = db.execute("SELECT value FROM state WHERE key='store_id'").fetchone()[0]
            row = db.execute('SELECT * FROM checks WHERE tool=? AND revision=? ORDER BY id DESC LIMIT 1',
                             (name, self._revision(name.split('_', 1)[0]))).fetchone()
            return self._public(row, store_id, True) if row else None
        finally:
            db.close()

    async def _one(self, name):
        last = self._latest(name)
        if last and time.time() - last['timestamp'] < self.cooldown:
            return last
        if self.lock.locked():
            return {**last, 'pending': True} if last else {'tool': name, 'pending': True}
        async with self.lock:
            # Repeat after acquiring the shared lock to coalesce callers.
            last = self._latest(name)
            if last and time.time() - last['timestamp'] < self.cooldown:
                return last
            platform = name.split('_', 1)[0]
            providers = {p.name: p for p in self.platforms()}
            provider = providers.get(platform)
            revision = self._revision(platform)
            backend = self._config().get('reddit_backend', 'http') if platform == 'reddit' else ''
            start = time.monotonic()
            category = 'unregistered'
            if provider is not None:
                if not provider.is_available():
                    category = 'missing'
                elif name in {t['name'] for t in provider.get_tool_definitions()}:
                    try:
                        text = await asyncio.wait_for(provider.handle_call(name, dict(PROBES[name][1])), self.timeout)
                        category = classify(text) if isinstance(text, str) and text.strip() else 'interface'
                    except asyncio.TimeoutError:
                        category = 'network'
                    except Exception:
                        category = 'interface'
                    health.record(platform, category == 'ok', MESSAGES[category][0])
            elapsed = round((time.monotonic() - start) * 1000)
            db = self._db()
            try:
                with db:
                    cursor = db.execute('INSERT INTO checks(timestamp,platform,tool,category,elapsed_ms,revision,backend) VALUES (?,?,?,?,?,?,?)',
                                        (time.time(), platform, name, category, elapsed, revision, backend))
                    row = db.execute('SELECT * FROM checks WHERE id=?', (cursor.lastrowid,)).fetchone()
                    store_id = db.execute("SELECT value FROM state WHERE key='store_id'").fetchone()[0]
                    db.execute('DELETE FROM checks WHERE timestamp<?', (time.time() - 30 * 86400,))
                    db.execute('DELETE FROM checks WHERE id NOT IN (SELECT id FROM checks ORDER BY id DESC LIMIT 10000)')
                return self._public(row, store_id)
            finally:
                db.close()

    async def run(self, arguments):
        if set(arguments) - {'mode', 'platform', 'tool', 'after_id'}:
            raise ValueError('unsupported health check parameter')
        mode = arguments.get('mode', 'check')
        platform = arguments.get('platform', 'all')
        tool = arguments.get('tool')
        after = arguments.get('after_id', 0)
        if mode not in ('status', 'check') or platform not in ('all', *PLATFORMS):
            raise ValueError('invalid health check mode or platform')
        if type(after) is not int or after < 0:
            raise ValueError('invalid health history cursor')
        if tool is not None and (tool not in PROBES or (platform != 'all' and not tool.startswith(platform + '_'))):
            raise ValueError('tool is not a safe health probe')
        names = [n for n in PROBES if (platform == 'all' or n.startswith(platform + '_')) and (not tool or n == tool)]
        checks = []
        for index, name in enumerate(names):
            result = await self._one(name) if mode == 'check' else self._latest(name)
            if result:
                checks.append(result)
            if mode == 'check' and index + 1 < len(names) and result and not result.get('cached'):
                await asyncio.sleep(self.probe_gap)
        db = self._db()
        try:
            store_id = db.execute("SELECT value FROM state WHERE key='store_id'").fetchone()[0]
            history = db.execute('SELECT * FROM checks WHERE id>? ORDER BY id LIMIT 200', (after,)).fetchall()
            return {'schema_version': SCHEMA_VERSION, 'checker': CHECK_TOOL, 'store_id': store_id,
                    'timestamp': time.time(), 'checks': checks,
                    'history': [self._public(row, store_id, True) for row in history],
                    'cursor': history[-1]['id'] if history else after, 'busy': self.lock.locked()}
        finally:
            db.close()
