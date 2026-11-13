import test from 'node:test'
import assert from 'node:assert/strict'
import { STOP_WAIT_STEPS } from '../src/runtime/herdr.mjs'

// 데스크 끄기는 서버가 실제로 내려갈 때까지 기다린 뒤 수집한다. 에이전트 5개 데스크는 3.17초 걸렸다(실측).
test('desk stop: 서버 종료를 3초보다 넉넉히(8초) 기다린다', () => {
  assert.ok(STOP_WAIT_STEPS * 100 >= 8000, `wait cap ${STOP_WAIT_STEPS * 100}ms`)
})
