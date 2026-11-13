// I-5 실패 여부·종류는 Claude 기록의 구조 표식(isApiErrorMessage·error)으로 먼저 판정한다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { apiErrorIn } from '../src/board/context.mjs'

const L = (o) => JSON.stringify(o)
const user = L({ type: 'user', timestamp: 't1', message: { content: 'hi' } })
const err = (kind) => L({ type: 'assistant', timestamp: 't2', isApiErrorMessage: true, error: kind, message: { model: '<synthetic>', content: [{ type: 'text', text: 'API Error' }] } })
const ok = L({ type: 'assistant', timestamp: 't3', message: { content: [{ type: 'text', text: 'done' }] } })

test('I-5: 마지막 대화 줄이 오류 합성 줄이면 그 종류를 돌려준다', () => {
  assert.deepEqual(apiErrorIn([user, err('rate_limit')].join('\n')), { kind: 'rate_limit', at: 't2' })
})
test('I-5: 오류 뒤에 사람이 다시 말했거나 정상 답이 왔으면 실패가 아니다', () => {
  assert.equal(apiErrorIn([user, err('rate_limit'), user].join('\n')), null)
  assert.equal(apiErrorIn([user, err('rate_limit'), ok].join('\n')), null)
})
test('I-5: 플래그 없는 <synthetic> 줄은 실패로 세지 않는다', () => {
  assert.equal(apiErrorIn([user, L({ type: 'assistant', message: { model: '<synthetic>', stop_reason: 'stop_sequence' } })].join('\n')), null)
})
