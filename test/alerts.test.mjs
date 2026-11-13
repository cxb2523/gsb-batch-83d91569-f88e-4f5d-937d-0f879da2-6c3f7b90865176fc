// 브라우저 알림 판단(index.html의 순수 함수 블록)을 꺼내 시험한다. #3·I-1 사건 키, #21 첫 실발송 라벨, #7 끊김 중 재알림 정지, I-7 끊김 알림.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const html = readFileSync(new URL('../src/board/index.html', import.meta.url), 'utf8')
const block = html.match(/\/\*pure:begin\*\/([\s\S]*?)\/\*pure:end\*\//)
assert.ok(block, 'index.html에 /*pure:begin*/ … /*pure:end*/ 블록이 있어야 한다')
const { attnKey, planAlerts, planBlind, orderDesks } = new Function(`${block[1]}; return { attnKey, planAlerts, planBlind, orderDesks }`)()

const cfg = { renotify_min: 15, renotify_max: 4 }
const MIN = 60000
const card = (id, status, since = '2026-11-08T10:00:00Z') => ({ id, status, attention_since: since })
const keys = (...cs) => new Map(cs.map((c) => [c.id, attnKey(c)]))

test('#3·I-1: 화면 판독이 wait↔fail로 흔들려도 herdr 상태·시작 시각이 같으면 같은 사건이다', () => {
  // 키는 화면 판독 결과(fail/wait)가 아니라 herdr 상태로만 만든다
  assert.equal(attnKey(card(1, 'blocked')), attnKey({ ...card(1, 'blocked'), failed: true }))
  const a1 = keys(card(1, 'blocked'))
  let r = planAlerts(null, a1, new Map(), { now: 0, away: true, on: true, off: false, cfg })
  r = planAlerts(a1, a1, r.alerts, { now: 3000, away: true, on: true, off: false, cfg })
  assert.deepEqual(r.send, [])
})

test('#3: attention_since가 바뀌면(새 사건) 다시 알린다', () => {
  const a1 = keys(card(1, 'blocked', 't1'))
  const a2 = keys(card(1, 'blocked', 't2'))
  let r = planAlerts(null, a1, new Map(), { now: 0, away: true, on: true, off: false, cfg })
  r = planAlerts(a1, a2, r.alerts, { now: 3000, away: true, on: true, off: false, cfg })
  assert.deepEqual(r.send, [{ id: 1, again: false }])
})

test('#21: 손 들 때 탭을 보고 있어 못 보낸 칸의 첫 실발송에는 "다시"가 붙지 않는다', () => {
  const a = keys(card(1, 'done'))
  let r = planAlerts(new Map(), a, new Map(), { now: 0, away: false, on: true, off: false, cfg })
  assert.deepEqual(r.send, [])
  r = planAlerts(a, a, r.alerts, { now: 16 * MIN, away: true, on: true, off: false, cfg })
  assert.deepEqual(r.send, [{ id: 1, again: false }])
  r = planAlerts(a, a, r.alerts, { now: 32 * MIN, away: true, on: true, off: false, cfg })
  assert.deepEqual(r.send, [{ id: 1, again: true }])
})

test('#7: 수집이 끊긴 동안에는 재알림하지 않는다', () => {
  const a = keys(card(1, 'blocked'))
  let r = planAlerts(new Map(), a, new Map(), { now: 0, away: true, on: true, off: false, cfg })
  assert.equal(r.send.length, 1)
  r = planAlerts(a, a, r.alerts, { now: 20 * MIN, away: true, on: true, off: true, cfg })
  assert.deepEqual(r.send, [])
  r = planAlerts(a, a, r.alerts, { now: 21 * MIN, away: true, on: true, off: false, cfg })
  assert.deepEqual(r.send, [{ id: 1, again: true }])
})

test('재알림은 처음 1회 + renotify_max회까지, 풀린 칸은 걷는다', () => {
  const a = keys(card(1, 'blocked'))
  let r = planAlerts(new Map(), a, new Map(), { now: 0, away: true, on: true, off: false, cfg })
  let sent = r.send.length
  for (let i = 1; i <= 10; i++) { r = planAlerts(a, a, r.alerts, { now: i * 15 * MIN, away: true, on: true, off: false, cfg }); sent += r.send.length }
  assert.equal(sent, 1 + cfg.renotify_max)
  r = planAlerts(a, new Map(), r.alerts, { now: 999 * MIN, away: true, on: true, off: false, cfg })
  assert.deepEqual(r.drop, [1])
})

test('I-7: 끊김은 연속 2회 관측(또는 수집 오류)일 때 에피소드당 한 번, 풀리면 닫는다', () => {
  let b = planBlind({}, 'herdr:t1', { errored: false })
  assert.equal(b.due, false, '한 번 늦은 응답(잠에서 깬 직후)으로는 알리지 않는다')
  b = planBlind(b, 'herdr:t1', { errored: false })
  assert.equal(b.due, true)
  b = { ...b, sent: true }
  b = planBlind(b, 'herdr:t1', { errored: false })
  assert.equal(b.due, false, '같은 에피소드는 한 번만')
  b = planBlind(b, null, {})
  assert.equal(b.close, true)
  b = planBlind(b, 'herdr:t2', { errored: true })
  assert.equal(b.due, true, '수집 오류가 함께 있으면 바로')
})

test('#4: 데스크 순서는 처음 본 순서로 고정되고, 새 데스크는 끝에 붙는다', () => {
  const seen = []
  const g = (desk, n) => ({ desk, cards: Array(n).fill(0) })
  assert.deepEqual(orderDesks([g('b', 1), g('a', 3)], seen).map((x) => x.desk), ['a', 'b'])
  assert.deepEqual(orderDesks([g('b', 5), g('a', 1)], seen).map((x) => x.desk), ['a', 'b'], '칸 수가 바뀌어도 자리가 그대로')
  assert.deepEqual(orderDesks([g('c', 9), g('b', 1), g('a', 1)], seen).map((x) => x.desk), ['a', 'b', 'c'])
})
