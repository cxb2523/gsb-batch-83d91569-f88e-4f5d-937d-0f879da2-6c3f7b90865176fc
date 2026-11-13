"""Persistent sampled connection history. Byte deltas are assigned to observation time.

Initial counters and counters after collection gaps are baselines, never backfilled
into a later time window. Only whitelisted network metadata is stored.
"""
from __future__ import annotations

import hashlib
import math
import sqlite3
from datetime import datetime
from pathlib import Path

INTERVAL = 2
RETENTION_DAYS = 30
MAX_BYTES = 256 * 1024 * 1024
GROUPS = {"category": "category", "domain": "host", "source": "source", "node": "node", "route": "route", "inbound": "inbound"}
# These describe destination domains, not the identity of the calling service.
CATEGORY_DOMAINS = {
    'AI 应用': ('chatgpt.com', 'openai.com', 'anthropic.com', 'claude.ai', 'deepseek.com', 'typesafe.ai'),
    '社交内容': ('x.com', 'twitter.com', 'twimg.com', 'reddit.com', 'bilibili.com', 'youtube.com', 'googlevideo.com'),
    '金融行情': ('xueqiu.com', 'snowball.finance', 'eastmoney.com'),
    '电商交易': ('goofish.com', 'taobao.com', 'tmall.com', 'jd.com'),
    '开发资源': ('github.com', 'githubusercontent.com', 'githubassets.com', 'npmjs.org', 'npmjs.com', 'pypi.org', 'pythonhosted.org'),
}
CATEGORY_SQL = 'CASE ' + ' '.join(
    'WHEN (' + ' OR '.join(f"(LOWER(c.host)='{domain}' OR LOWER(c.host) LIKE '%.{domain}')" for domain in domains)
    + f") THEN '{label}'" for label, domains in CATEGORY_DOMAINS.items()
) + " ELSE '其他 / 未分类' END"


def connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5) if readonly else sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=5000")
    return db


def timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        return 0


def count(value) -> int:
    try:
        return min(2**62, max(0, int(value)))
    except (ValueError, TypeError, OverflowError):
        return 0


class HistoryStore:
    def __init__(self, path: Path, now: float):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = connect(path)
        self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS connections (
                key TEXT PRIMARY KEY, connection_id TEXT, host TEXT, port TEXT,
                source TEXT, process TEXT, network TEXT, inbound TEXT, node TEXT, route TEXT,
                started REAL, first_seen REAL, last_seen REAL, last_activity REAL,
                upload_total INTEGER, download_total INTEGER, preexisting INTEGER,
                present INTEGER, observed_end REAL
            );
            CREATE INDEX IF NOT EXISTS connections_seen ON connections(last_seen);
            CREATE TABLE IF NOT EXISTS traffic (
                at REAL, connection_key TEXT, upload INTEGER, download INTEGER,
                PRIMARY KEY(at, connection_key)
            );
            CREATE INDEX IF NOT EXISTS traffic_connection ON traffic(connection_key, at);
            CREATE TABLE IF NOT EXISTS collector (
                id INTEGER PRIMARY KEY CHECK(id=1), started REAL, last_success REAL,
                last_attempt REAL, error TEXT, retained_from REAL
            );
            CREATE TABLE IF NOT EXISTS gaps (
                id INTEGER PRIMARY KEY, started REAL, ended REAL, reason TEXT
            );
        """)
        with self.db:
            state = self.db.execute("SELECT * FROM collector WHERE id=1").fetchone()
            if state and state['last_success'] is not None:
                self._gap(state['last_success'], 'collector_restart')
            self.db.execute("INSERT OR IGNORE INTO collector VALUES (1,?,NULL,?,NULL,?)", (now, now, now))
            self.db.execute("UPDATE connections SET present=-1 WHERE present=1")
        self.previous: dict[str, tuple[int, int]] | None = None
        self.last_time: float | None = None
        self.last_prune = 0.0

    def _gap(self, start: float, reason: str):
        if not self.db.execute("SELECT 1 FROM gaps WHERE ended IS NULL").fetchone():
            self.db.execute("INSERT INTO gaps(started,ended,reason) VALUES (?,NULL,?)", (start, reason))

    def failed(self, now: float):
        with self.db:
            state = self.db.execute("SELECT last_success FROM collector WHERE id=1").fetchone()
            self._gap(state[0] if state and state[0] is not None else now, 'controller_unavailable')
            self.db.execute("UPDATE collector SET last_attempt=?, error='controller_unavailable' WHERE id=1", (now,))
            self.db.execute("UPDATE connections SET present=-1 WHERE present=1")
        self.previous = None

    def ingest(self, payload: dict, now: float):
        if not isinstance(payload, dict) or not isinstance(payload.get('connections'), list):
            raise ValueError('Unexpected connections response')
        continuous = self.previous is not None and self.last_time is not None and 0 < now - self.last_time <= INTERVAL * 3
        current = {}
        with self.db:
            if self.last_time is not None and now - self.last_time > INTERVAL * 3:
                self._gap(self.last_time, 'collection_delay')
            self.db.execute("UPDATE gaps SET ended=? WHERE ended IS NULL", (now,))
            self.db.execute("UPDATE connections SET present=0, observed_end=? WHERE present!=0", (now,))
            for raw in payload['connections']:
                if not isinstance(raw, dict) or not raw.get('id'):
                    continue
                meta = raw.get('metadata') or {}
                started = timestamp(raw.get('start', ''))
                key = hashlib.sha256((str(raw['id']) + '\0' + str(raw.get('start', ''))).encode()).hexdigest()
                if key in current:
                    continue
                up, down = count(raw.get('upload')), count(raw.get('download'))
                previous = (self.previous or {}).get(key) if continuous else None
                # A newly observed connection beginning inside continuous coverage can
                # contribute its first counters. Older connections are baseline only.
                fresh = continuous and self.last_time is not None and self.last_time <= started <= now
                baseline = previous or ((0, 0) if fresh else (up, down))
                if up < baseline[0] or down < baseline[1]:
                    du, dd = 0, 0
                    self.db.execute("INSERT INTO gaps(started,ended,reason) VALUES (?,?,?)", (self.last_time, now, 'counter_reset'))
                else:
                    du, dd = up - baseline[0], down - baseline[1]
                chains = raw.get('chains') or []
                node = str(chains[0]) if chains else '未知'
                route = 'direct' if node == 'DIRECT' else 'reject' if node in ('REJECT', 'REJECT-DROP') else 'unknown' if not chains else 'proxy'
                values = (key, str(raw['id']), str(meta.get('host') or meta.get('destinationIP') or '未知'),
                          str(meta.get('destinationPort') or ''), str(meta.get('sourceIP') or '未知'),
                          str(meta.get('process') or ''), str(meta.get('network') or ''),
                          str(meta.get('inboundName') or '未命名入口'), node, route, started or now,
                          now, now, now if du or dd else None, up, down, int(not fresh), 1, None)
                self.db.execute("""INSERT INTO connections VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(key) DO UPDATE SET last_seen=excluded.last_seen,
                    last_activity=COALESCE(excluded.last_activity,connections.last_activity),
                    upload_total=excluded.upload_total,download_total=excluded.download_total,
                    present=1,observed_end=NULL""", values)
                if du or dd:
                    self.db.execute("INSERT INTO traffic VALUES (?,?,?,?)", (now, key, du, dd))
                current[key] = (up, down)
            self.db.execute("UPDATE collector SET last_success=?,last_attempt=?,error=NULL WHERE id=1", (now, now))
        self.previous = current
        self.last_time = now
        if now - self.last_prune > 3600:
            self.prune(now)

    def prune(self, now: float):
        cutoff = now - RETENTION_DAYS * 86400
        with self.db:
            self.db.execute("DELETE FROM traffic WHERE at<?", (cutoff,))
            self.db.execute("DELETE FROM connections WHERE last_seen<? AND present=0", (cutoff,))
            self.db.execute("DELETE FROM gaps WHERE ended<?", (cutoff,))
            # Reclaim the oldest day if the live DB exceeds the storage budget.
            used = (self.db.execute('PRAGMA page_count').fetchone()[0] - self.db.execute('PRAGMA freelist_count').fetchone()[0]) * self.db.execute('PRAGMA page_size').fetchone()[0]
            if used > MAX_BYTES:
                oldest = self.db.execute('SELECT MIN(at) FROM traffic').fetchone()[0]
                if oldest is not None:
                    cutoff = max(cutoff, min(now, oldest + 86400))
                    self.db.execute('DELETE FROM traffic WHERE at<?', (cutoff,))
                    self.db.execute('DELETE FROM connections WHERE last_seen<? AND present=0', (cutoff,))
            self.db.execute('UPDATE collector SET retained_from=MAX(retained_from,?) WHERE id=1', (cutoff,))
        self.db.execute('PRAGMA incremental_vacuum(2048)')
        self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        self.last_prune = now

    def close(self):
        self.db.close()


def query_history(path: Path, *, start: float, end: float, now: float,
                  group_by: str = 'domain', search: str = '', group_value: str | None = None,
                  route: str = 'all', page: int = 1, group_page: int = 1, page_size: int = 20) -> dict:
    if group_by not in GROUPS or not math.isfinite(start) or not math.isfinite(end) or start >= end or end - start > 31 * 86400:
        raise ValueError('请选择有效的时间范围，单次最多查询 31 天')
    if route not in ('all', 'direct', 'proxy', 'reject', 'unknown') or page < 1 or group_page < 1 or not 1 <= page_size <= 100:
        raise ValueError('查询参数无效')
    db = connect(path, readonly=True)
    try:
        db.execute('BEGIN')  # All lists and totals share one consistent read snapshot.
        state = dict(db.execute('SELECT * FROM collector WHERE id=1').fetchone())
        fresh = state['last_success'] is not None and now - state['last_success'] <= INTERVAL * 3 and not state['error']
        column = GROUPS[group_by]  # SQL identifiers are selected only from this allowlist.
        where = ['c.first_seen < ?', 'c.last_seen >= ?']
        params: list = [end, start]
        if search:
            escaped = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            where.append("(c.host LIKE ? ESCAPE '\\' OR c.source LIKE ? ESCAPE '\\' OR c.node LIKE ? ESCAPE '\\' OR c.process LIKE ? ESCAPE '\\')")
            params.extend(['%' + escaped + '%'] * 4)
        if group_value is not None:
            where.append(f'{CATEGORY_SQL if column == "category" else "c." + column}=?')
            params.append(group_value)
        if route != 'all':
            where.append('c.route=?')
            params.append(route)
        condition = ' AND '.join(where)
        cte = f"""WITH deltas AS (
            SELECT connection_key,SUM(upload) upload,SUM(download) download FROM traffic
            WHERE at>=? AND at<? GROUP BY connection_key
        ), selected AS (
            SELECT c.*,{CATEGORY_SQL} category,COALESCE(d.upload,0) period_upload,COALESCE(d.download,0) period_download
            FROM connections c LEFT JOIN deltas d ON d.connection_key=c.key WHERE {condition}
        ) """
        args = [start, end, *params]
        totals = dict(db.execute(cte + 'SELECT COUNT(*) connections,COALESCE(SUM(period_upload),0) upload,COALESCE(SUM(period_download),0) download FROM selected', args).fetchone())
        group_total = db.execute(cte + f'SELECT COUNT(DISTINCT {column}) FROM selected', args).fetchone()[0]
        groups = [dict(row) for row in db.execute(cte + f'''SELECT {column} label,COUNT(*) connections,
            SUM(period_upload) upload,SUM(period_download) download FROM selected GROUP BY {column}
            ORDER BY (SUM(period_upload)+SUM(period_download)) DESC,label LIMIT ? OFFSET ?''', [*args, page_size, (group_page - 1) * page_size])]
        records = []
        for row in db.execute(cte + 'SELECT * FROM selected ORDER BY last_seen DESC,key LIMIT ? OFFSET ?', [*args, page_size, (page - 1) * page_size]):
            record = dict(row)
            record['state'] = 'unknown' if not fresh or record['present'] == -1 else 'observed' if record['present'] else 'not_seen'
            record['activity'] = 'recent' if record['last_activity'] is not None and now - record['last_activity'] <= 10 else 'idle'
            records.append(record)
        step = max(60, math.ceil((end - start) / 120 / 60) * 60)
        series = [dict(row) for row in db.execute(f'''SELECT CAST((t.at-?)/? AS INTEGER) bucket,
            SUM(t.upload) upload,SUM(t.download) download FROM traffic t JOIN connections c ON c.key=t.connection_key
            WHERE t.at>=? AND t.at<? AND {condition} GROUP BY bucket ORDER BY bucket''', [start, step, start, end, *params])]
        indexed = {int(row['bucket']): row for row in series}
        points = [{'at': start + i * step, 'upload': indexed.get(i, {}).get('upload', 0),
                   'download': indexed.get(i, {}).get('download', 0)} for i in range(math.ceil((end - start) / step))]
        gap_count = db.execute('SELECT COUNT(*) FROM gaps WHERE started<? AND (ended IS NULL OR ended>?)', (end, start)).fetchone()[0]
        gaps = [dict(row) for row in db.execute('SELECT started,ended,reason FROM gaps WHERE started<? AND (ended IS NULL OR ended>?) ORDER BY started DESC LIMIT 50', (end, start))]
        # Chart coverage uses every gap even when the expanded list is paged down.
        all_gaps = db.execute('SELECT started,ended FROM gaps WHERE started<? AND (ended IS NULL OR ended>?) ORDER BY started', (end, start)).fetchall()
        merged = []
        for gap in all_gaps:
            until = gap['ended'] if gap['ended'] is not None else end
            if merged and gap['started'] <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], until)
            else:
                merged.append([gap['started'], until])
        cursor = 0
        for point in points:
            while cursor < len(merged) and merged[cursor][1] <= point['at']:
                cursor += 1
            point['incomplete'] = point['at'] < state['retained_from'] or point['at'] < state['started'] or (
                cursor < len(merged) and merged[cursor][0] < point['at'] + step)
        return {'range': {'start': start, 'end': end}, 'totals': totals,
                'groups': {'rows': groups, 'total': group_total, 'page': group_page, 'page_size': page_size},
                'records': {'rows': records, 'total': totals['connections'], 'page': page, 'page_size': page_size},
                'series': points, 'bucket_seconds': step, 'gaps': gaps, 'gap_count': gap_count,
                'collector': {**state, 'healthy': bool(fresh), 'interval_seconds': INTERVAL, 'retention_days': RETENTION_DAYS},
                'estimated': True}
    finally:
        db.close()
