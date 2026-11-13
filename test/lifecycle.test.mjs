// #8 확인 불가 칸의 마지막 확인 시각, #13 핀 칸은 보관 후보 아님, I-2 보관 칸이 다시 손 들면 복귀·보관 칸은 기한 없이, #14 확인 불가 수명.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { openDb } from '../src/db.mjs'
import { collectOnce } from '../src/collector.mjs'
import { computeBoard, setPinned, setStashed } from '../src/board/board.mjs'
import { setSettings } from '../src/settings.mjs'

const T0 = new Date('2026-11-08T10:00:00Z')
const at = (min) => new Date(T0.getTime() + min * 60000)
const pane = (ref, status, ps = `ps-${ref}`) => ({
  runtime: 'herdr', runtime_ref: ref, provider_session: ps, cwd: `/tmp/${ref}`, project: ref.split('/')[1], title: ref,
  pane_label: null, provider: status === 'shell' ? null : 'claude', status, attentionTimestamp: null, archived: false,
  fields: { lastStatus: status, requiresAttention: status === 'blocked' || status === 'done', attentionReason: null, lastUserMessageAt: null, title: ref },
})
const rt = (panes) => ({ name: 'herdr', TRACKS_GONE: true, FIELDS: ['lastStatus', 'requiresAttention', 'attentionReason', 'lastUserMessageAt', 'title'],
  state: { panes, unreachable: [] }, listSnapshot() { return { sessions: this.state.panes, unreachable: this.state.unreachable } } })
const tick = (db, r, min) => collectOnce(db, r, { now: at(min) })
const board = (db, min) => computeBoard(db, { now: at(min), withContext: false })
const find = (b, ref) => Object.values(b.columns).flat().find((c) => c.ref === ref)

test('#8: 확인 불가가 이어져도 마지막으로 확인한 시각은 그대로 남는다', () => {
  const db = openDb(':memory:')
  const r = rt([pane('main/w1:p1', 'blocked')])
  tick(db, r, 0)
  r.state.panes = []; r.state.unreachable = ['main']
  for (let s = 1; s <= 20; s++) tick(db, r, s * 0.05)
  const c = find(board(db, 1), 'main/w1:p1')
  assert.equal(c.unreachable, true)
  assert.equal(c.last_ok_at, at(0).toISOString())
})

test('#13: 핀 고정 칸은 오래 멈춰도 보관 후보 표시가 붙지 않는다', () => {
  const db = openDb(':memory:')
  const r = rt([pane('main/w1:p1', 'idle'), pane('main/w1:p2', 'idle')])
  tick(db, r, 0)
  const later = 10 * 86400 / 60
  setPinned(db, find(board(db, 1), 'main/w1:p1').id, true, at(1))
  const b = computeBoard(db, { now: at(later), withContext: true })
  assert.equal(find(b, 'main/w1:p1').stale, false)
  assert.equal(find(b, 'main/w1:p2').stale, true)
})

test('I-2: 보관한 빈 칸에 에이전트가 붙어 손 들면 보관이 풀리고 판에 돌아온다', () => {
  const db = openDb(':memory:')
  const r = rt([pane('main/w1:p1', 'shell', null)])
  tick(db, r, 0)
  const id = find(board(db, 0.1), 'main/w1:p1').id
  setStashed(db, id, true, at(0.1))
  r.state.panes = [pane('main/w1:p1', 'blocked', 'new-conv')]
  tick(db, r, 0.15)
  const b = board(db, 0.2)
  assert.equal(b.next?.ref, 'main/w1:p1')
  assert.equal(b.closed.length, 0)
  assert.ok(db.prepare("SELECT 1 FROM event WHERE field = 'unstash' AND source = 'collector'").get())
})

test('I-2: 보관한 칸은 기한이 지나도 최근 닫힘에 남아 되돌릴 수 있다(사라진 칸만 기한)', () => {
  const db = openDb(':memory:')
  const r = rt([pane('main/w1:p1', 'idle')])
  tick(db, r, 0)
  setStashed(db, find(board(db, 0.1), 'main/w1:p1').id, true, at(0.1))
  const b = board(db, 8 * 1440)
  assert.deepEqual(b.closed.map((c) => [c.ref, c.reason]), [['main/w1:p1', 'stashed']])
})

test('#14: 확인 불가가 unreachable_ttl_h를 넘긴 칸은 손 든 칸에서 내려온다', () => {
  const db = openDb(':memory:')
  const r = rt([pane('main/w1:p1', 'blocked')])
  tick(db, r, 0)
  r.state.panes = []; r.state.unreachable = ['main']
  tick(db, r, 0.05)
  assert.equal(board(db, 60).next?.ref, 'main/w1:p1')
  assert.equal(setSettings(db, { unreachable_ttl_h: 2 }).ok, true)
  tick(db, r, 179)
  const b = board(db, 180)
  assert.equal(b.next, null)
  assert.ok(find(b, 'main/w1:p1'), '칸은 판에 남는다(숫자·순번에서만 빠짐)')
})
