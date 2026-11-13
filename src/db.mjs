import { DatabaseSync } from 'node:sqlite'
import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { homedir } from 'node:os'

export const STATE_DIR = process.env.WHOSUP_STATE_DIR || join(homedir(), '.config', 'whosup')
export const DEFAULT_DB = join(STATE_DIR, 'whosup.db')

const SCHEMA = `
CREATE TABLE IF NOT EXISTS session (
  id INTEGER PRIMARY KEY,
  runtime TEXT NOT NULL,
  runtime_ref TEXT NOT NULL,
  provider_session TEXT,
  project TEXT NOT NULL DEFAULT '-',
  cwd TEXT NOT NULL DEFAULT '',
  title TEXT,
  pane_label TEXT,
  provider TEXT,
  status TEXT NOT NULL DEFAULT 'unknown',
  fields_json TEXT NOT NULL DEFAULT '{}',
  attention_since TEXT,
  last_user_msg_at TEXT,
  seen_at TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  first_seen TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (runtime, runtime_ref)
);
CREATE TABLE IF NOT EXISTS event (
  id INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES session(id),
  at TEXT NOT NULL,
  field TEXT NOT NULL,
  before TEXT,
  after TEXT,
  source TEXT NOT NULL DEFAULT 'collector'
);
CREATE INDEX IF NOT EXISTS event_at ON event(at);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
`

// 개편(2026-11-08) 추가 열. 기존 DB를 보존하려고 없을 때만 ALTER로 붙인다.
const ADDED_COLUMNS = [
  ['attention_kind', 'TEXT'],
  ['pinned_at', 'TEXT'],
  ['stashed_at', 'TEXT'],
  ['miss_count', 'INTEGER NOT NULL DEFAULT 0'],
  ['unreachable', 'INTEGER NOT NULL DEFAULT 0'],
  ['last_alert_at', 'TEXT'],
  ['alert_count', 'INTEGER NOT NULL DEFAULT 0'],
]

function migrate(db) {
  const have = new Set(db.prepare('PRAGMA table_info(session)').all().map((c) => c.name))
  for (const [name, type] of ADDED_COLUMNS) if (!have.has(name)) db.exec(`ALTER TABLE session ADD COLUMN ${name} ${type}`)
}

export const getMeta = (db, key) => db.prepare('SELECT value FROM meta WHERE key = ?').get(key)?.value ?? null
export const setMeta = (db, key, value) => db.prepare('INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value').run(key, value == null ? null : String(value))

export function openDb(path = process.env.WHOSUP_DB || DEFAULT_DB) {
  if (path !== ':memory:') mkdirSync(dirname(path), { recursive: true })
  const db = new DatabaseSync(path)
  db.exec('PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 5000;')
  db.exec(SCHEMA)
  migrate(db)
  return db
}

// #1 상태 폴더당 후즈업 하나. 같은 DB에 수집기가 둘이면 알림이 두 번 나간다.
// 잠금 파일에 SQLite 배타 잠금을 잡고 프로세스가 끝날 때까지 쥔다(OS가 풀어 주므로 죽어도 남지 않는다).
// 다른 프로세스가 쥐고 있으면 null.
export function acquireLock(dir = STATE_DIR) {
  mkdirSync(dir, { recursive: true })
  const lock = new DatabaseSync(join(dir, 'whosup.lock'))
  try {
    lock.exec('PRAGMA busy_timeout = 0; PRAGMA locking_mode = EXCLUSIVE;')
    lock.exec('CREATE TABLE IF NOT EXISTS owner (pid INTEGER); DELETE FROM owner;')
    lock.prepare('INSERT INTO owner (pid) VALUES (?)').run(process.pid)
    return lock
  } catch (err) {
    lock.close()
    if (/locked|busy/i.test(String(err.message))) return null
    throw err
  }
}

export function transaction(db, fn) {
  db.exec('BEGIN')
  try {
    const result = fn()
    db.exec('COMMIT')
    return result
  } catch (err) {
    db.exec('ROLLBACK')
    throw err
  }
}
