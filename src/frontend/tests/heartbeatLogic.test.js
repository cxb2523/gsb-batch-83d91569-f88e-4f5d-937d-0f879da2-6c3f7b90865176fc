// Tests for the check-heartbeat detail helpers. Run with `node --test` in this folder (Node 20 or newer, no packages needed).
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { NO_DETAILS, describeAttempt, errorLabel, heartbeatView, slotHeartbeats } from '../src/availability/heartbeatLogic.js'

test('a successful attempt shows its index, latency and the basis it was judged on', () => {
  const line = describeAttempt({ attempt: 1, ok: true, response_ms: 42, basis: 'HTTP 200 accepted' })
  assert.equal(line, '1 · OK · 42 ms · HTTP 200 accepted')
  assert.equal(describeAttempt({ attempt: 2, ok: true, basis: 'keyword found' }), '2 · OK · keyword found')
})

test('a failed attempt shows the fixed failure category and the short reason, never a fabricated latency', () => {
  const line = describeAttempt({ attempt: 2, ok: false, response_ms: null, error_category: 'timeout', detail: 'Timed out after 5 s' })
  assert.equal(line, '2 · Timeout · Timed out after 5 s')
  assert.equal(errorLabel('dns_error'), 'DNS resolution failed')
  assert.equal(errorLabel('something-new'), 'something-new')
  assert.equal(describeAttempt({ attempt: 1, ok: false, error_category: 'certificate_error', detail: 'expired' }), '1 · Certificate problem · expired')
})

test('a heartbeat without detail is explicitly "no details", not an empty success', () => {
  assert.deepEqual(heartbeatView({ has_details: false, attempts: null }), { hasDetails: false, label: NO_DETAILS, attempts: [] })
  assert.deepEqual(heartbeatView({ has_details: true, attempts: [] }), { hasDetails: false, label: NO_DETAILS, attempts: [] })
  assert.equal(heartbeatView(undefined).label, NO_DETAILS)
})

test('a heartbeat with detail keeps every attempt in order, retries included', () => {
  const view = heartbeatView({
    has_details: true,
    attempts: [
      { attempt: 1, ok: false, error_category: 'connection_refused', detail: 'Connection refused' },
      { attempt: 2, ok: false, error_category: 'timeout', detail: 'Timed out after 5 s' },
      { attempt: 3, ok: true, response_ms: 31, basis: 'TCP connection opened' },
    ],
  })
  assert.equal(view.hasDetails, true)
  assert.equal(view.label, '3 attempts')
  assert.equal(view.attempts.length, 3)
  assert.match(view.attempts[0].line, /Connection refused/)
  assert.match(view.attempts[2].line, /3 · OK · 31 ms/)
})

test('slot heartbeats list each server and mark the ones without detail honestly', () => {
  const rows = slotHeartbeats({
    heartbeats: [
      { server_id: 1, hostname: 'alpha', has_details: true, attempts: [{ attempt: 1, ok: true, response_ms: 12, basis: 'HTTP 200 accepted' }] },
      { server_id: 2, hostname: 'bravo', has_details: false, attempts: null },
    ],
  })
  assert.deepEqual(rows.map((row) => [row.server, row.hasDetails, row.label]), [['alpha', true, '1 attempt'], ['bravo', false, NO_DETAILS]])
  assert.deepEqual(slotHeartbeats(undefined), [])
})
