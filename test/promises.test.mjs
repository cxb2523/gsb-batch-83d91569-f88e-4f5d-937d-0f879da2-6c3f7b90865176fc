// 약속 5개(놓치지 않는다·하나를 가리킨다·버리지 않는다·닿는다·모르면 모른다) 회귀 테스트. 실사용 DB는 쓰지 않는다(:memory:).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { openDb, getMeta } from '../src/db.mjs'
import { computeBoard, markSeen, markUnseen, setPinned, setStashed, orderAttention, markReopened } from '../src/board/board.mjs'
import { collectOnce } from '../src/collector.mjs'
import { setSettings, getSettings } from '../src/settings.mjs'

const T0 = new Date('2026-11-07T14:40:00Z') // KST 23:40 — 자정 직전
const at = (min) => new Date(T0.getTime() + min * 60000)
const pane = (ref, status, extra = {}) => ({
  runtime: 'herdr', runtime_ref: ref, provider_session: extra.ps ?? `ps-${ref}`, cwd: `/tmp/${ref}`, project: ref.split('/')[1], title: ref,
  pane_label: null, provider: status === 'shell' ? null : 'claude', status, attentionTimestamp: null, archived: false,
  fields: { lastStatus: status, requiresAttention: status === 'blocked' || status === 'done', attentionReason: null, lastUserMessageAt: null, title: ref },
})
// 상태를 바꿔 가며 쓰는 가짜 herdr 런타임
function fakeRuntime(panes) {
  return {
    name: 'herdr', TRACKS_GONE: true, FIELDS: ['lastStatus', 'requiresAttention', 'attentionReason', 'lastUserMessageAt', 'title'],
    state: { panes, unreachable: [], fail: null },
    listSnapshot() { if (this.state.fail) throw new Error(this.state.fail); return { sessions: this.state.panes, unreachable: this.state.unreachable } },
  }
}
const board = (db, min) => computeBoard(db, { now: at(min), withContext: false })
const ids = (cards) => cards.map((c) => c.ref)
const tick = (db, rt, min) => collectOnce(db, rt, { now: at(min) })

test('promise1: 자정 전에 손 든 미확인 칸은 다음 날에도 입력 필요로 남는다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('main/w1:p3', 'blocked'), pane('main/w1:p1', 'working')])
  tick(db, rt, 0)
  for (let m = 1; m <= 6; m++) tick(db, rt, m * 0.05) // 3초 간격 수집
  const b = board(db, 14 * 60) // 다음 날 오후
  assert.deepEqual(ids(b.columns.red), ['main/w1:p3'])
  assert.equal(b.next.ref, 'main/w1:p3')
})

test('promise1: 확인함은 30분 미루기 — 지나면 다시 올라오고, 취소하면 바로 올라온다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('main/w1:p1', 'blocked')])
  tick(db, rt, 0)
  const id = board(db, 1).next.id
  markSeen(db, id, at(1))
  let b = board(db, 10)
  assert.equal(b.columns.red.length, 0)
  assert.deepEqual(ids(b.columns.snoozed), ['main/w1:p1'])
  assert.ok(b.columns.snoozed[0].snoozed_until)
  assert.equal(b.next, null)
  assert.deepEqual(ids(board(db, 32).columns.red), ['main/w1:p1'], '30분 뒤 다시 손 든 칸')
  markUnseen(db, id, at(11))
  assert.deepEqual(ids(board(db, 12).columns.red), ['main/w1:p1'], '확인 취소 즉시 복귀')
})

test('promise1: 미루기 시간은 설정에서 바꾼 값을 따른다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('main/w1:p1', 'done')])
  tick(db, rt, 0)
  markSeen(db, board(db, 1).next.id, at(1))
  assert.equal(setSettings(db, { seen_snooze_min: 5 }).ok, true)
  assert.equal(board(db, 4).columns.yellow.length, 0)
  assert.equal(board(db, 7).columns.yellow.length, 1)
})

test('promise1: 확인 뒤 대기 종류가 바뀌면(blocked→done) 새 사건으로 다시 올라온다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('main/w1:p1', 'blocked')])
  tick(db, rt, 0)
  markSeen(db, board(db, 1).next.id, at(1))
  rt.state.panes = [pane('main/w1:p1', 'done')] // working 구간을 수집이 못 봄
  tick(db, rt, 2)
  const b = board(db, 3)
  assert.deepEqual(ids(b.columns.yellow), ['main/w1:p1'])
})

test('promise1: 수집 공백 뒤 첫 수집은 손 든 칸을 새 사건으로 연다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('main/w1:p1', 'done')])
  tick(db, rt, 0)
  markSeen(db, board(db, 0.02).next.id, at(0.02))
  tick(db, rt, 0.05) // 3초 뒤 정상 수집 — 같은 사건이라 확인함이 유지된다
  assert.equal(board(db, 0.06).columns.yellow.length, 0)
  tick(db, rt, 20) // whosup가 꺼져 있던 동안(>30초) 새 답변이 왔을 수 있다
  assert.equal(board(db, 20.1).columns.yellow.length, 1)
})

test('promise5: 조회하지 못한 herdr 세션의 칸은 사라지지 않고 확인 불가로 남는다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('side/w1:p1', 'blocked'), pane('main/w1:p1', 'working')])
  tick(db, rt, 0)
  rt.state.panes = [pane('main/w1:p1', 'working')]
  rt.state.unreachable = ['side']
  for (let i = 1; i <= 5; i++) tick(db, rt, i * 0.05)
  const b = board(db, 0.5)
  assert.deepEqual(ids(b.columns.red), ['side/w1:p1'])
  assert.equal(b.columns.red[0].unreachable, true)
  assert.deepEqual(b.health.unreachable, ['side'])
  assert.equal(b.closed.length, 0)
})

test('promise5: 정말 없어진 칸은 연속 3회 안 보일 때만 닫힘으로 옮긴다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('main/w1:p1', 'blocked'), pane('main/w1:p2', 'working')])
  tick(db, rt, 0)
  rt.state.panes = [pane('main/w1:p2', 'working')]
  tick(db, rt, 0.05); tick(db, rt, 0.1)
  assert.deepEqual(ids(board(db, 0.11).columns.red), ['main/w1:p1'], '2회까지는 유지')
  rt.state.panes = [pane('main/w1:p1', 'blocked'), pane('main/w1:p2', 'working')]
  tick(db, rt, 0.15) // 다시 보이면 카운트 초기화
  rt.state.panes = [pane('main/w1:p2', 'working')]
  tick(db, rt, 0.2); tick(db, rt, 0.25); tick(db, rt, 0.3)
  const b = board(db, 0.31)
  assert.equal(b.columns.red.length, 0)
  assert.deepEqual(b.closed.map((c) => [c.ref, c.reason]), [['main/w1:p1', 'gone']])
})

test('promise5: herdr에 아예 닿지 않으면 칸을 건드리지 않고 끊김을 알린다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('main/w1:p1', 'blocked')])
  tick(db, rt, 0)
  rt.state.fail = 'connect ENOENT herdr.sock'
  for (let i = 1; i <= 4; i++) assert.throws(() => tick(db, rt, i * 0.05))
  let b = board(db, 0.25)
  assert.deepEqual(ids(b.columns.red), ['main/w1:p1'])
  assert.match(b.health.error, /ENOENT/)
  assert.equal(b.health.stale, false)
  b = board(db, 1) // 마지막 성공 수집 60초 전 > 30초
  assert.equal(b.health.stale, true)
  assert.equal(b.health.age_sec, 60)
})

test('order: 실패 → 입력 필요 → 답변 도착, 각 무리 안은 오래 기다린 순', () => {
  const c = (id, status, since, failed = false) => ({ id, status, attention_since: since, failed })
  const out = orderAttention([c(1, 'done', '2026-11-07T01:00:00Z'), c(2, 'blocked', '2026-11-07T03:00:00Z'), c(3, 'blocked', '2026-11-07T02:00:00Z'), c(4, 'blocked', '2026-11-07T05:00:00Z', true)])
  assert.deepEqual(out.map((x) => x.id), [4, 3, 2, 1])
})

test('order: 보드 응답의 order 첫 칸이 곧 다음 1건이다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('main/w1:p1', 'done'), pane('main/w1:p2', 'blocked')])
  tick(db, rt, 0)
  const b = board(db, 1)
  assert.equal(b.order[0], b.next.id)
  assert.equal(b.next.ref, 'main/w1:p2')
  assert.deepEqual(b.order, [...b.columns.red, ...b.columns.yellow].map((c) => c.id))
})

test('promise3: 이어서 할 것은 개수 제한 없이 모두 실린다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime(Array.from({ length: 60 }, (_, i) => pane(`main/w1:p${i + 1}`, 'idle')))
  tick(db, rt, 0)
  const b = board(db, 1)
  assert.equal(b.columns.carry.length, 60)
  assert.equal(b.carry_total, 60)
})

test('promise3: 보관한 칸은 최근 닫힘으로 가고 되돌릴 수 있다, 핀은 유지된다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('main/w1:p1', 'idle'), pane('main/w1:p2', 'blocked')])
  tick(db, rt, 0)
  const idle = board(db, 1).columns.carry[0]
  setStashed(db, idle.id, true, at(2))
  let b = board(db, 3)
  assert.equal(b.columns.carry.length, 0)
  assert.deepEqual(b.closed.map((c) => [c.ref, c.reason]), [['main/w1:p1', 'stashed']])
  setStashed(db, idle.id, false, at(4))
  b = board(db, 5)
  assert.equal(b.columns.carry.length, 1)
  setPinned(db, b.next.id, true, at(6))
  tick(db, rt, 6.05)
  assert.ok(board(db, 7).next.pinned_at)
  const bb = board(db, 8 + 8 * 24 * 60) // 보관 기간(7일)이 지나면 닫힘 줄에서 빠진다
  assert.equal(bb.closed.length, 0)
})

test('settings: 범위 밖 값은 저장하지 않고, 기본값은 PRD 수치다', () => {
  const db = openDb(':memory:')
  assert.deepEqual(getSettings(db), { seen_snooze_min: 30, renotify_min: 15, renotify_max: 4, gone_misses: 3, stale_collect_sec: 30, closed_keep_days: 7, stale_days: 3, os_notify: 0, unreachable_ttl_h: 24, split_pct: 0, agent_cmd: process.env.AGENT_CMD || 'claude', front_app: process.env.FRONT_APP || '', click_target: 'terminal' })   // click_target: 2회차 첫 실행 카드 선택(기본 터미널)
  const r = setSettings(db, { renotify_min: 5, gone_misses: 0 })
  assert.equal(r.ok, false)
  assert.equal(getSettings(db).renotify_min, 15, '하나라도 틀리면 아무것도 저장하지 않는다')
  assert.equal(getMeta(db, 'setting.renotify_min'), null)
})

test('settings: 실행 명령은 한 줄 글자로 저장하고, 비우면 기본값으로 돌아간다', () => {
  const db = openDb(':memory:')
  assert.equal(setSettings(db, { agent_cmd: 'claude --dangerously-skip-permissions' }).ok, true)
  assert.equal(getSettings(db).agent_cmd, 'claude --dangerously-skip-permissions')
  assert.equal(setSettings(db, { agent_cmd: 'claude\nrm -rf ~' }).ok, false, '여러 줄은 거절')
  assert.equal(setSettings(db, { agent_cmd: 'x'.repeat(201) }).ok, false, '200자 초과는 거절')
  assert.equal(getSettings(db).agent_cmd, 'claude --dangerously-skip-permissions')
  setSettings(db, { agent_cmd: null })
  assert.equal(getSettings(db).agent_cmd, process.env.AGENT_CMD || 'claude')
})

test('folders: 홈 아래 폴더만 보이고, 숨김 폴더는 뺀다', async () => {
  const { listDirs } = await import('../src/board/server.mjs')
  const { homedir } = await import('node:os')
  const r = listDirs(homedir())
  assert.equal(r.ok, true)
  assert.equal(r.parent, null)
  assert.ok(r.dirs.every((n) => !n.startsWith('.')))
  assert.equal(listDirs('/etc').ok, false)
  assert.equal(listDirs(homedir() + '/../..').ok, false, '.. 로 홈 밖으로 못 나간다')
})

test('promise4: macOS 알림은 기본 끔, 켜면 처음 1회 + 15분 간격 최대 4회, 미룬 칸·첫 수집은 보내지 않는다', async () => {
  const { notifyPass } = await import('../src/notify.mjs')
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('main/w1:p1', 'blocked'), pane('main/w1:p2', 'done')])
  tick(db, rt, 0)
  const sent = []
  const send = (m) => sent.push(m)
  assert.equal(notifyPass(db, { now: at(0), send }), 0, '기본 끔')
  setSettings(db, { os_notify: 1, stale_collect_sec: 600 }) // 1분 간격 수집을 공백으로 보지 않게
  notifyPass(db, { now: at(0), prime: true, send })
  assert.equal(sent.length, 0, '첫 수집은 표시만')
  markSeen(db, board(db, 0.1).columns.yellow[0].id, at(0.1))
  for (let m = 1; m <= 120; m++) { tick(db, rt, m); notifyPass(db, { now: at(m), send }) }
  const p1 = sent.filter((x) => x.subtitle.includes('p1'))
  assert.equal(p1.length, 4, '처음 알림은 prime으로 소비, 이후 15분 간격 재알림 4회')
  assert.ok(sent.every((x) => !x.subtitle.includes('p2')) || sent.filter((x) => x.subtitle.includes('p2')).length <= 4)
})

test('promise4: 새 사건이 생기면 알림 횟수가 처음부터 다시 센다', async () => {
  const { notifyPass } = await import('../src/notify.mjs')
  const db = openDb(':memory:')
  setSettings(db, { os_notify: 1 })
  const rt = fakeRuntime([pane('main/w1:p1', 'blocked')])
  tick(db, rt, 0)
  const sent = []
  notifyPass(db, { now: at(0.01), send: (m) => sent.push(m) })
  assert.equal(sent.length, 1)
  rt.state.panes = [pane('main/w1:p1', 'done')]
  tick(db, rt, 0.05)
  notifyPass(db, { now: at(0.06), send: (m) => sent.push(m) })
  assert.equal(sent.length, 2, 'blocked→done 새 사건은 바로 알린다')
})

test('settings: 비운 값은 기본값으로 되돌린다', () => {
  const db = openDb(':memory:')
  setSettings(db, { renotify_min: 5 })
  assert.equal(getSettings(db).renotify_min, 5)
  assert.equal(setSettings(db, { renotify_min: null }).ok, true)
  assert.equal(getSettings(db).renotify_min, 15)
})

test('promise1: 개편 전 DB(대기 종류 비어 있음)를 올려도 원래 대기 시작 시각을 지킨다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('main/w1:p3', 'blocked')])
  tick(db, rt, 0)
  db.prepare('UPDATE session SET attention_kind = NULL').run() // 마이그레이션 직후 상태
  tick(db, rt, 0.05)
  assert.equal(board(db, 1).columns.red[0].attention_since, at(0).toISOString())
})

test('promise5: 서버를 끈 세션의 칸은 꺼짐으로 남고 손 든 칸·순번에서 빠진다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('side/w1:p1', 'blocked'), pane('main/w1:p1', 'blocked')])
  tick(db, rt, 0)
  rt.state.panes = [pane('main/w1:p1', 'blocked')]
  rt.listSnapshot = function () { return { sessions: this.state.panes, unreachable: [], stopped: ['side'] } }
  for (let i = 1; i <= 4; i++) tick(db, rt, i * 0.05)
  const b = board(db, 0.3)
  assert.deepEqual(ids(b.columns.red), ['main/w1:p1'])
  const side = b.columns.carry.find((c) => c.ref === 'side/w1:p1')
  assert.ok(side && side.off && !side.unreachable, '꺼짐 표시로 판에 남음')
  assert.deepEqual(b.health.stopped, ['side'])
  assert.equal(b.closed.length, 0)
})

test('D1: 최근 닫힘에서 이어서 연 칸은 목록에서 빠진다(새 칸으로 다시 잡힌다)', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('main/w1:p1', 'idle'), pane('main/w1:p2', 'working')])
  tick(db, rt, 0)
  rt.state.panes = [pane('main/w1:p2', 'working')]
  tick(db, rt, 0.05); tick(db, rt, 0.1); tick(db, rt, 0.15)
  const closed = board(db, 0.16).closed
  assert.deepEqual(closed.map((c) => c.ref), ['main/w1:p1'])
  markReopened(db, closed[0].id, at(0.2))
  assert.equal(board(db, 0.21).closed.length, 0, '이어서 연 뒤에는 최근 닫힘에 남지 않는다')
})

test('D3: 끝난 칸을 유휴로만 알리는 런타임에서 진행 중 → 유휴는 답변 도착으로 올라오고, 새 요청 전까지 유지된다', () => {
  const db = openDb(':memory:')
  const rt = { ...fakeRuntime([pane('w/w1:p1', 'working', { }), pane('w/w1:p2', 'idle')]), IDLE_AFTER_WORK_IS_DONE: true }
  rt.state = { panes: [pane('w/w1:p1', 'working'), pane('w/w1:p2', 'idle')], unreachable: [], fail: null }
  tick(db, rt, 0)
  rt.state.panes = [pane('w/w1:p1', 'idle'), pane('w/w1:p2', 'idle')]
  tick(db, rt, 0.05)
  assert.deepEqual(ids(board(db, 0.06).columns.yellow), ['w/w1:p1'], '진행 중이던 칸만 답변 도착')
  tick(db, rt, 0.1); tick(db, rt, 0.15)
  assert.deepEqual(ids(board(db, 0.16).columns.yellow), ['w/w1:p1'], '다음 수집에서도 유지')
})
test('D3: 답변 도착을 직접 주는 런타임(맥)에서는 진행 중 → 유휴를 그대로 유휴로 둔다', () => {
  const db = openDb(':memory:')
  const rt = fakeRuntime([pane('m/w1:p1', 'working')])
  tick(db, rt, 0)
  rt.state.panes = [pane('m/w1:p1', 'idle')]
  tick(db, rt, 0.05)
  assert.equal(board(db, 0.06).columns.yellow.length, 0)
})
test('D2: 수집 사이에 시작해 끝난 짧은 작업도 답변 도착으로 올라온다(유휴만 알리는 런타임)', () => {
  const db = openDb(':memory:')
  const p = (msg) => { const x = pane('w/w1:p1', 'idle'); x.fields.lastUserMessageAt = msg; return x }
  const rt = { ...fakeRuntime([p('2026-11-07T14:39:00Z')]), IDLE_AFTER_WORK_IS_DONE: true }
  rt.state = { panes: [p('2026-11-07T14:39:00Z')], unreachable: [], fail: null }
  tick(db, rt, 0); tick(db, rt, 0.05)
  assert.equal(board(db, 0.06).columns.yellow.length, 0, '새 요청이 없으면 유휴')
  rt.state.panes = [p('2026-11-07T14:40:04Z')]
  tick(db, rt, 0.1)
  assert.deepEqual(ids(board(db, 0.11).columns.yellow), ['w/w1:p1'])
})
