import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { failedFor, extractQuestion } from '../src/board/context.mjs'

const box = '\n' + '─'.repeat(40) + '\n❯ \n' + '─'.repeat(40)

test('failedFor: 질문을 기다리는 칸은 바로 위에 도구 오류 줄이 있어도 실패가 아니다', () => {
  const screen = readFileSync(new URL('./pane_screens.json', import.meta.url), 'utf8')
  const q = JSON.parse(screen).question
  const withErr = '⏺ AskUserQuestion\n  ⎿  Error: PreToolUse:AskUserQuestion hook error: 회상부터\n' + q
  const question = extractQuestion(withErr)
  assert.ok(question)
  assert.equal(failedFor(withErr, 'blocked', question), false)
})

test('failedFor: 답을 마친 칸의 API 오류는 그대로 실패다', () => {
  const t = '❯ test\n⏺ API Error: 529 Provider connect timeout after 200000ms' + box
  assert.equal(failedFor(t, 'done', null), true)
  assert.equal(failedFor(t, 'idle', null), true)
})
