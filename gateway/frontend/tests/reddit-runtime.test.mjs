// Pure unit tests for the Reddit runtime presentation rules. No DOM, no gateway.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { BROWSER_FAILURE_TEXT, createRedditRuntime, failureText, formatDuration } from '../src/redditRuntime.ts'

function model(runtime, now = 1000, flags = { redditBusy: () => false, checking: () => false }) {
  let current = runtime
  const api = createRedditRuntime(() => current, () => now, flags)
  return { api, setRuntime: next => { current = next } }
}

const healthy = {
  backend: 'opencli', available: true, running: true, session_imported: true,
  session_current: true, busy: false, last_failure: null, cooldown_until: 0, idle_seconds: 600,
}

test('cooldown remaining is derived from cooldown_until and blocks start with a reason', () => {
  const { api } = model({ ...healthy, running: false, last_failure: 'rate_limit', cooldown_until: 3600 }, 1000)
  assert.equal(api.cooldownRemaining(), 2600)
  assert.equal(api.inCooldown(), true)
  assert.equal(api.startDisabled(), true)
  const reason = api.startBlockedReason()
  assert.match(reason, /冷却/)
  assert.ok(reason.includes(formatDuration(2600)), 'reason shows the remaining time')
})

test('start becomes allowed again once the cooldown deadline passes', () => {
  let clock = 3600
  const api = createRedditRuntime(
    () => ({ ...healthy, cooldown_until: 3600 }),
    () => clock,
    { redditBusy: () => false, checking: () => false },
  )
  assert.equal(api.inCooldown(), false)
  assert.equal(api.startDisabled(), false)
  assert.equal(api.startBlockedReason(), '')
  clock = 3599
  assert.equal(api.inCooldown(), true)
  assert.equal(api.startDisabled(), true)
})

test('session mismatch is reported only when an imported session disagrees with config', () => {
  assert.equal(model({ ...healthy, session_current: false }).api.sessionMismatch(), true)
  assert.equal(model(healthy).api.sessionMismatch(), false)
  assert.equal(model({ ...healthy, session_imported: false, session_current: false }).api.sessionMismatch(), false)
})

test('known failures render Chinese explanations; unknown values fall back instead of leaking', () => {
  assert.equal(failureText('rate_limit'), BROWSER_FAILURE_TEXT.rate_limit)
  assert.match(failureText('rate_limit'), /429/)
  for (const value of ['mystery_blob_9f3a', '', null, undefined]) {
    assert.equal(failureText(value), BROWSER_FAILURE_TEXT.unknown)
  }
})

test('start disable reasons follow cooldown, operation, check, availability, busy precedence', () => {
  const base = { ...healthy, available: true, busy: false }
  const flags = { redditBusy: () => false, checking: () => false }
  assert.equal(model(base, 1000, flags).api.startBlockedReason(), '')
  assert.match(model({ ...base, available: false }, 1000, flags).api.startBlockedReason(), /未连接/)
  assert.match(model({ ...base, busy: true }, 1000, flags).api.startBlockedReason(), /正在处理/)
  assert.match(model(base, 1000, { redditBusy: () => true, checking: () => false }).api.startBlockedReason(), /操作进行中/)
  assert.match(model(base, 1000, { redditBusy: () => false, checking: () => true }).api.startBlockedReason(), /检测进行中/)
  const cooldown = model({ ...base, cooldown_until: 2000 }, 1000, { redditBusy: () => true, checking: () => true })
  assert.match(cooldown.api.startBlockedReason(), /冷却/, 'cooldown outranks every other reason')
})

test('duration formatter uses Chinese units and never emits NaN', () => {
  assert.equal(formatDuration(0), '0 分钟')
  assert.equal(formatDuration(45), '45 秒')
  assert.equal(formatDuration(120), '2 分钟')
  assert.equal(formatDuration(150), '2 分 30 秒')
  assert.equal(formatDuration(3600), '1 小时')
  assert.equal(formatDuration(3900), '1 小时 5 分钟')
  assert.equal(formatDuration(Number.NaN), '0 分钟')
})
