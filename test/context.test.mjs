import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { extractQuestion, extractLastSay, looksFailed, lastPromptIn } from '../src/board/context.mjs'
const screens = JSON.parse(readFileSync(new URL('./pane_screens.json', import.meta.url), 'utf8'))
test('permission box → "cmd — 승인할까요?", question paragraph joined', () => {
  assert.equal(extractQuestion(screens.permission), 'npm run build — 승인할까요?')
  assert.equal(extractQuestion(screens.question), '파일 3개를 덮어쓰게 됩니다. 기존 index.html은 백업이 없는데 그대로 진행할까요?')
  assert.match(extractQuestion(screens.trust), /신뢰할까요/)
})
test('last say + failure signal', () => {
  assert.match(extractLastSay(screens.done), /테스트 24건/)
  assert.equal(looksFailed(screens.failed), true)
  assert.equal(looksFailed(screens.done), false)
})
test('last user prompt from jsonl', () => {
  const lines = [{ type: 'user', timestamp: 't1', message: { content: 'a' } }, { type: 'user', isMeta: true, message: { content: 'm' } }, { type: 'user', timestamp: 't2', message: { content: [{ type: 'text', text: ' b ' }] } }].map((o) => JSON.stringify(o)).join('\n')
  assert.deepEqual(lastPromptIn(lines), { at: 't2', text: 'b' })
})
