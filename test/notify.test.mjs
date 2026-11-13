// 서버 쪽 macOS 알림: #7 끊긴 동안 재알림 정지, I-7 끊김 에피소드당 한 통, #16 동시 2건 이상이면 한 통.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { openDb } from '../src/db.mjs'
import { collectOnce } from '../src/collector.mjs'
import { setSettings } from '../src/settings.mjs'
import { notifyPass } from '../src/notify.mjs'

const T0 = new Date('2026-11-08T10:00:00Z')
const at = (min) => new Date(T0.getTime() + min * 60000)
const pane = (ref, status) => ({
  runtime: 'herdr', runtime_ref: ref, provider_session: `ps-${ref}`, cwd: `/tmp/${ref}`, project: ref.split('/')[1], title: ref,
  pane_label: null, provider: 'claude', status, attentionTimestamp: null, archived: false,
  fields: { lastStatus: status, requiresAttention: status === 'blocked' || status === 'done', attentionReason: null, lastUserMessageAt: null, title: ref },
})
const rt = (panes) => ({ name: 'herdr', TRACKS_GONE: true, FIELDS: ['lastStatus', 'requiresAttention', 'attentionReason', 'lastUserMessageAt', 'title'],
  state: { panes, fail: null }, listSnapshot() { if (this.state.fail) throw new Error(this.state.fail); return { sessions: this.state.panes, unreachable: [] } } })
const tick = (db, r, min) => { try { collectOnce(db, r, { now: at(min) }) } catch {} }
function setup(panes) {
  const db = openDb(':memory:')
  const r = rt(panes)
  setSettings(db, { os_notify: 1, stale_collect_sec: 120 })
  tick(db, r, 0)
  notifyPass(db, { now: at(0), prime: true, send: () => {} })
  return { db, r }
}

test('#7·I-7: herdr를 못 읽는 동안 재알림은 멈추고, 끊김은 에피소드당 한 통만 간다', () => {
  const { db, r } = setup([pane('main/w1:p1', 'blocked')])
  const sent = []
  r.state.fail = 'spawnSync herdr ETIMEDOUT'
  for (let m = 1; m <= 60; m++) { tick(db, r, m); notifyPass(db, { now: at(m), send: (x) => sent.push(x) }) }
  assert.equal(sent.length, 1, sent.map((x) => x.subtitle).join(' / '))
  assert.match(sent[0].body + sent[0].subtitle, /herdr/)
  r.state.fail = null
  tick(db, r, 61); notifyPass(db, { now: at(61), send: (x) => sent.push(x) })
  r.state.fail = 'again'
  for (let m = 62; m <= 70; m++) { tick(db, r, m); notifyPass(db, { now: at(m), send: (x) => sent.push(x) }) }
  assert.equal(sent.filter((x) => /herdr/.test(x.body + x.subtitle)).length, 2, '새 에피소드는 다시 한 통')
})

test('#16: 같은 패스에 보낼 칸이 둘 이상이면 한 통으로 묶고, 각 칸의 횟수는 따로 센다', () => {
  const db = openDb(':memory:')
  const r = rt([pane('main/w1:p1', 'blocked')])
  setSettings(db, { os_notify: 1, stale_collect_sec: 120 })
  tick(db, r, 0)
  notifyPass(db, { now: at(0), prime: true, send: () => {} })
  r.state.panes = [pane('main/w1:p1', 'blocked'), pane('main/w1:p2', 'done'), pane('main/w1:p3', 'blocked')]
  tick(db, r, 1)
  const sent = []
  notifyPass(db, { now: at(1), send: (x) => sent.push(x) })
  assert.equal(sent.length, 1)
  assert.match(sent[0].subtitle, /2/)
  assert.match(sent[0].body, /p2/); assert.match(sent[0].body, /p3/)
  const counts = db.prepare('SELECT runtime_ref, alert_count FROM session ORDER BY runtime_ref').all().map((x) => x.alert_count)
  assert.deepEqual(counts, [1, 1, 1])
})
