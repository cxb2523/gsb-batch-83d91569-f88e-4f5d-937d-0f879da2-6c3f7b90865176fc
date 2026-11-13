// 수집이 끊겼을 때 이미 아는 것을 잃지도, 아무 일 없는 척하지도 않는지 고정한다(약속 1·5).
//   · 한 번 안 보인 칸은 닫지 않는다 — miss_count만 올리고 마지막 상태·시각을 지킨다.
//   · 정말 사라진 칸은 gone_misses번 연속 안 보여야 닫고, 그때 사건을 적는다.
//   · 런타임 전체가 unreachable_ttl_h 넘게 닿지 않을 때만 닫는다(그 전에는 확인 불가로 유지).
//   · 수집 실패는 세 갈래(no_herdr·no_reply·failed)로, 300자로 줄여 시각과 함께 남긴다.
//   · 다시 닿으면 확인 불가 표시와 "닿지 않기 시작한 때"를 지우고, 마지막 성공 시각은 런타임마다 따로 센다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { getMeta, openDb } from '../src/db.mjs'
import { collectOnce, errKind, forgetDownSince } from '../src/collector.mjs'
import { setSettings } from '../src/settings.mjs'

const T0 = new Date('2026-11-12T09:00:00Z')
const at = (min) => new Date(T0.getTime() + min * 60000)
const hours = (h) => h * 60
const FIELDS = ['lastStatus', 'requiresAttention', 'attentionReason', 'lastUserMessageAt', 'title']
const pane = (runtime, ref, status = 'blocked') => ({
  runtime, runtime_ref: ref, provider_session: `ps-${ref}`, cwd: `/tmp/${ref}`, project: ref.split('/')[1], title: ref,
  pane_label: null, provider: 'claude', status, attentionTimestamp: null, archived: false,
  fields: { lastStatus: status, requiresAttention: status === 'blocked', attentionReason: null, lastUserMessageAt: null, title: ref },
})
// 상태를 바꿔 가며 쓰는 가짜 런타임: sessions·unreachable·stopped·holdAll·fail을 그때그때 바꾼다.
// 실제 런타임처럼, 읽지 못한 세션(unreachable)의 칸은 sessions에 들어 있지 않다 — 목록에는 있는데 못 읽은 것이다.
const deskOfRef = (p) => p.runtime_ref.split('/')[0]
function runtime(name, panes) {
  return {
    name, TRACKS_GONE: true, FIELDS,
    state: { panes, unreachable: [], stopped: [], holdAll: false, fail: null },
    listSnapshot() {
      if (this.state.fail) throw this.state.fail
      const { unreachable, stopped, holdAll } = this.state
      const sessions = holdAll ? [] : this.state.panes.filter((p) => !unreachable.includes(deskOfRef(p)))
      return { sessions, unreachable, stopped, holdAll }
    },
  }
}
const tick = (db, rt, min, opts) => collectOnce(db, rt, { now: at(min), ...opts })
const row = (db, ref) => db.prepare('SELECT * FROM session WHERE runtime_ref = ?').get(ref)
const goneEvents = (db) => db.prepare("SELECT * FROM event WHERE field = 'gone' ORDER BY id").all()

test('한 번 안 보인 칸은 닫지 않는다: 마지막 상태·updated_at을 지키고 miss_count만 올린다', () => {
  const db = openDb(':memory:')
  const rt = runtime('herdr', [pane('herdr', 'main/w1:p1'), pane('herdr', 'main/w1:p2', 'idle')])
  tick(db, rt, 0)
  rt.state.panes = [pane('herdr', 'main/w1:p2', 'idle')]
  tick(db, rt, 0.05) // 3초짜리 한 번의 흔들림
  const gone = row(db, 'main/w1:p1')
  assert.equal(gone.archived, 0)
  assert.equal(gone.status, 'blocked', '마지막으로 알던 상태 그대로')
  assert.equal(gone.updated_at, at(0).toISOString(), '마지막으로 확인한 시각 그대로')
  assert.equal(gone.miss_count, 1)
  assert.equal(goneEvents(db).length, 0, '닫힘 사건을 적지 않는다')
  // 다시 보이면 miss_count가 0으로 돌아간다(흔들림이 쌓이지 않는다)
  rt.state.panes = [pane('herdr', 'main/w1:p1'), pane('herdr', 'main/w1:p2', 'idle')]
  tick(db, rt, 0.1)
  assert.deepEqual([row(db, 'main/w1:p1').miss_count, row(db, 'main/w1:p1').archived], [0, 0])
})

test('정말 사라진 칸은 gone_misses번 연속 안 보여야 닫고, 그때 gone 사건을 한 번 적는다', () => {
  const db = openDb(':memory:')
  assert.equal(setSettings(db, { gone_misses: 3 }).ok, true)
  const rt = runtime('herdr', [pane('herdr', 'main/w1:p1')])
  tick(db, rt, 0)
  rt.state.panes = []
  tick(db, rt, 0.05)
  tick(db, rt, 0.1)
  assert.equal(row(db, 'main/w1:p1').archived, 0, '2회까지는 유지')
  assert.equal(row(db, 'main/w1:p1').miss_count, 2)
  tick(db, rt, 0.15)
  const gone = row(db, 'main/w1:p1')
  assert.deepEqual([gone.archived, gone.status], [1, 'gone'])
  assert.deepEqual(goneEvents(db).map((e) => [e.field, e.before, e.after, e.source, e.at]), [['gone', 'false', 'true', 'collector', at(0.15).toISOString()]])
})

test('런타임 전체가 닿지 않으면: 그 전에는 확인 불가로 유지하고, TTL이 지나야만 닫는다', () => {
  const db = openDb(':memory:')
  assert.equal(setSettings(db, { unreachable_ttl_h: 2 }).ok, true)
  const rt = runtime('herdr', [pane('herdr', 'main/w1:p1')])
  tick(db, rt, 0)
  rt.state.holdAll = true // 창구가 통째로 닿지 않는다: 아는 칸이 하나도 없다
  tick(db, rt, 1)
  const held = row(db, 'main/w1:p1')
  assert.deepEqual([held.archived, held.unreachable, held.status], [0, 1, 'blocked'], '확인 불가로 표시하되 닫지는 않는다')
  assert.equal(held.updated_at, at(0).toISOString(), '마지막으로 확인한 시각 유지')
  assert.equal(getMeta(db, 'collect_down_since:herdr'), at(1).toISOString(), '닿지 않기 시작한 때를 적는다')
  tick(db, rt, 121) // 1분에 닿지 않기 시작해 꼭 2시간 — 아직 넘지 않았다
  assert.deepEqual([row(db, 'main/w1:p1').archived, row(db, 'main/w1:p1').unreachable], [0, 1])
  assert.equal(goneEvents(db).length, 0)
  tick(db, rt, 125) // 2시간을 넘겼다
  const gone = row(db, 'main/w1:p1')
  assert.deepEqual([gone.archived, gone.status, gone.unreachable], [1, 'gone', 0])
  assert.deepEqual(goneEvents(db).map((e) => [e.field, e.before, e.after, e.at]), [['gone', 'false', 'true', at(125).toISOString()]])
})

test('확인하지 못한 세션의 칸은 여러 번 이어져도 miss_count가 쌓이지 않고, 닫히지도 않는다', () => {
  const db = openDb(':memory:')
  assert.equal(setSettings(db, { gone_misses: 3 }).ok, true)
  const rt = runtime('herdr', [pane('herdr', 'main/w1:p1'), pane('herdr', 'side/w1:p1')])
  tick(db, rt, 0)
  rt.state.unreachable = ['side']
  for (let i = 1; i <= 10; i++) tick(db, rt, i * 0.05) // gone_misses(3)를 훌쩍 넘게 이어진다
  const side = row(db, 'side/w1:p1')
  assert.deepEqual([side.archived, side.unreachable, side.status, side.miss_count], [0, 1, 'blocked', 0], '모르는 것과 없어진 것은 다르다')
  assert.equal(side.updated_at, at(0).toISOString())
  assert.equal(goneEvents(db).length, 0)
  rt.state.unreachable = []
  tick(db, rt, 0.6)
  assert.deepEqual([row(db, 'side/w1:p1').unreachable, row(db, 'side/w1:p1').status], [0, 'blocked'])
})

test('수집 실패 세 갈래: 실행 파일 없음 no_herdr, 응답 없음 no_reply, 그 밖 failed — 300자로 줄여 시각과 함께 남긴다', () => {
  const cases = [
    [{ code: 'ENOENT', message: 'spawnSync herdr ENOENT' }, 'no_herdr'],
    [{ code: 'ETIMEDOUT', message: 'spawnSync herdr ETIMEDOUT' }, 'no_reply'],
    [{ signal: 'SIGTERM', message: 'killed' }, 'no_reply'],
    [{ signal: 'SIGKILL', message: 'killed' }, 'no_reply'],
    [{ message: 'Unexpected token < in JSON' }, 'failed'],
  ]
  for (const [props, kind] of cases) {
    assert.equal(errKind(props), kind)
    const db = openDb(':memory:')
    const rt = { name: 'herdr', TRACKS_GONE: true, FIELDS, listSnapshot() { throw Object.assign(new Error(props.message), props) } }
    assert.throws(() => tick(db, rt, 0), '실패는 그대로 알린다(수집이 조용히 넘어가지 않는다)')
    assert.deepEqual([getMeta(db, 'collect_err_kind'), getMeta(db, 'collect_err'), getMeta(db, 'collect_err_at')],
      [kind, props.message.slice(0, 300), at(0).toISOString()])
  }
  // 긴 오류 문구는 300자에서 자른다
  const db = openDb(':memory:')
  const rt = { name: 'herdr', TRACKS_GONE: true, FIELDS, listSnapshot() { throw new Error('x'.repeat(900)) } }
  assert.throws(() => tick(db, rt, 0))
  assert.equal(getMeta(db, 'collect_err').length, 300)
  assert.equal(getMeta(db, 'collect_err_kind'), 'failed')
})

test('다시 닿으면 확인 불가 표시와 "닿지 않기 시작한 때"를 지우고, 마지막 성공 시각을 새로 적는다', () => {
  const db = openDb(':memory:')
  // 이 시험은 수집 간격이 1분이다. 기본 stale_collect_sec(30초)로 두면 정상 수집조차 "수집 공백"이 되어
  // 손 든 칸이 새 사건으로 열린다(그 동작 자체는 맞고 promises.test.mjs가 본다) — 여기서 보려는 것만 남긴다.
  assert.equal(setSettings(db, { stale_collect_sec: 600 }).ok, true)
  const rt = runtime('herdr', [pane('herdr', 'main/w1:p1')])
  tick(db, rt, 0)
  rt.state.unreachable = ['main'] // 이 세션만 읽지 못한다
  tick(db, rt, 1)
  assert.deepEqual([row(db, 'main/w1:p1').unreachable, row(db, 'main/w1:p1').archived], [1, 0])
  rt.state.unreachable = []
  tick(db, rt, 2)
  const back = row(db, 'main/w1:p1')
  assert.deepEqual([back.unreachable, back.archived, back.status], [0, 0, 'blocked'], '확인 불가 표시가 사라진다')
  assert.equal(back.updated_at, at(2).toISOString(), '마지막으로 확인한 시각이 새로 잡힌다')
  assert.equal(back.attention_since, at(0).toISOString(), '확인하지 못한 동안에도 대기 시작 시각은 그대로였다')
  assert.equal(getMeta(db, 'collect_ok_at:herdr'), at(2).toISOString())

  // 전체가 닿지 않던 경우: 닿자마자 "닿지 않기 시작한 때"를 지운다 — 다음에 켤 때 옛 실패를 새 실패로 세지 않게.
  rt.state.holdAll = true
  tick(db, rt, 3)
  assert.equal(getMeta(db, 'collect_down_since:herdr'), at(3).toISOString())
  rt.state.holdAll = false
  tick(db, rt, 4)
  assert.equal(getMeta(db, 'collect_down_since:herdr'), null)
  assert.equal(row(db, 'main/w1:p1').unreachable, 0)
})

test('마지막 성공 시각은 런타임마다 따로 센다: 한쪽이 끊겨도 다른 쪽 칸의 대기 시작이 새로 잡히지 않는다', () => {
  const db = openDb(':memory:')
  const h = runtime('herdr', [pane('herdr', 'main/w1:p1')])
  const c = runtime('herdr-core', [pane('herdr-core', 'core:a/w1:p1')])
  tick(db, h, 0)
  tick(db, c, 0, { health: false }) // 판의 건강 상태는 herdr 쪽이 적는다
  const coreSince = row(db, 'core:a/w1:p1').attention_since
  const coreOk = getMeta(db, 'collect_ok_at:herdr-core')
  assert.ok(coreOk)
  h.state.fail = new Error('herdr is gone')
  for (let i = 1; i <= 4; i++) {
    assert.throws(() => tick(db, h, i * 0.05))
    tick(db, c, i * 0.05, { health: false })
  }
  assert.equal(row(db, 'core:a/w1:p1').attention_since, coreSince, 'herdr가 끊긴 것이 herdr-core 칸의 대기 시작을 흔들지 않는다')
  assert.equal(row(db, 'core:a/w1:p1').unreachable, 0)
  assert.notEqual(getMeta(db, 'collect_ok_at:herdr-core'), coreOk, 'herdr-core는 계속 성공 시각을 적는다')
  assert.equal(getMeta(db, 'collect_ok_at'), at(0).toISOString(), '공용 건강 기록은 herdr가 끊긴 뒤로 낡은 채 남는다')
})

test('오래 꺼 두었다 켠 첫 수집: 꺼지기 직전에 적힌 "닿지 않기 시작한 때"로 칸을 닫지 않는다', () => {
  const run = (restart) => {
    const db = openDb(':memory:')
    const rt = runtime('herdr', [pane('herdr', 'main/w1:p1')])
    tick(db, rt, 0)
    rt.state.holdAll = true
    tick(db, rt, 0.05) // 닿지 않기 시작했고, 곧 후즈업도 꺼졌다
    if (restart) forgetDownSince(db) // 30시간 뒤 후즈업이 다시 뜬다
    tick(db, rt, hours(30))
    return row(db, 'main/w1:p1')
  }
  const fresh = run(true)
  assert.deepEqual([fresh.archived, fresh.status, fresh.unreachable], [0, 'blocked', 1], '닿지 않은 것은 방금부터다')
  const sameProcess = run(false)
  assert.deepEqual([sameProcess.archived, sameProcess.status], [1, 'gone'], '같은 프로세스가 30시간 내내 닿지 못했다면 닫는다')
})

test('아무것도 모르는 첫 수집에서도 실패는 남기되, 칸이 없으면 닫을 것도 없다', () => {
  const db = openDb(':memory:')
  const rt = runtime('herdr', [])
  rt.state.fail = Object.assign(new Error('spawnSync herdr ENOENT'), { code: 'ENOENT' })
  assert.throws(() => tick(db, rt, 0))
  assert.deepEqual([getMeta(db, 'collect_err_kind'), getMeta(db, 'collect_ok_at:herdr')], ['no_herdr', null])
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM session').get().n, 0)
  // 성공한 뒤 실패하면 마지막 성공 시각은 그대로 남는다(판이 "끊김"을 알아챈다). 다시 성공하면 새로 잡힌다.
  const ok = runtime('herdr', [pane('herdr', 'main/w1:p1')])
  tick(db, ok, 1)
  assert.equal(getMeta(db, 'collect_ok_at:herdr'), at(1).toISOString())
  ok.state.fail = Object.assign(new Error('spawnSync herdr ETIMEDOUT'), { code: 'ETIMEDOUT' })
  assert.throws(() => tick(db, ok, 2))
  assert.deepEqual([getMeta(db, 'collect_ok_at:herdr'), getMeta(db, 'collect_err_kind'), getMeta(db, 'collect_err_at')],
    [at(1).toISOString(), 'no_reply', at(2).toISOString()])
  ok.state.fail = null
  tick(db, ok, 3)
  assert.equal(getMeta(db, 'collect_ok_at:herdr'), at(3).toISOString())
})
