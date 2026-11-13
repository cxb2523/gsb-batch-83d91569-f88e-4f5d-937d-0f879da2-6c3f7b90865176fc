import { test } from 'node:test'
import assert from 'node:assert/strict'
import { openDb } from '../src/db.mjs'
import { computeBoard, markSeen } from '../src/board/board.mjs'
import { collectOnce } from '../src/collector.mjs'
const now = new Date()
const iso = (m) => new Date(now.getTime() - m * 60000).toISOString()
const fake = { name: 'herdr', FIELDS: ['lastStatus', 'requiresAttention', 'attentionReason', 'lastUserMessageAt', 'title'], TRACKS_GONE: true, listSessions: () => [
  { runtime: 'herdr', runtime_ref: 'main/w1:p1', provider_session: 'x', cwd: '/work/a', project: 'a', title: 'a', pane_label: 'alpha', provider: 'claude', status: 'blocked', attentionTimestamp: iso(5), archived: false, fields: { lastStatus: 'error', requiresAttention: true, attentionReason: 'blocked', lastUserMessageAt: null, title: 'a' } },
  { runtime: 'herdr', runtime_ref: 'main/w1:p2', provider_session: null, cwd: '/work/b', project: 'b', title: 'b', pane_label: null, provider: null, status: 'shell', attentionTimestamp: null, archived: false, fields: { lastStatus: 'shell', requiresAttention: false, attentionReason: null, lastUserMessageAt: null, title: 'b' } },
  { runtime: 'herdr', runtime_ref: 'side/w1:p1', provider_session: 'y', cwd: '/work/c', project: 'c', title: 'c', pane_label: 'gamma', provider: 'codex', status: 'working', attentionTimestamp: null, archived: false, fields: { lastStatus: 'running', requiresAttention: false, attentionReason: null, lastUserMessageAt: null, title: 'c' } },
] }
test('collect → board: blocked is red/next, shell is carry, working is green, labels kept', () => {
  const db = openDb(':memory:')
  collectOnce(db, fake, { emit: false })
  const b = computeBoard(db, { withContext: false })
  assert.equal(b.next.ref, 'main/w1:p1')
  assert.deepEqual(b.columns.green.map((c) => c.ref), ['side/w1:p1'])
  assert.deepEqual(b.columns.carry.map((c) => [c.ref, c.status]), [['main/w1:p2', 'shell']])
  assert.equal(db.prepare("SELECT pane_label FROM session WHERE runtime_ref='side/w1:p1'").get().pane_label, 'gamma')
  markSeen(db, b.next.id)
  assert.equal(computeBoard(db, { withContext: false }).columns.red.length, 0)
})
