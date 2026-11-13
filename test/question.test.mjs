// 2026-11-08 3대 실기기 QA 회귀: 선택 커서(❯ 1. …, ❯ No, exit)를 입력줄로 오인해 질문을 못 읽던 결함
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { extractQuestion, extractLastSay } from '../src/board/context.mjs'
const fx = (n) => readFileSync(new URL(`./fixtures/${n}`, import.meta.url), 'utf8')

test('객관식 질문 화면에서 질문 문장을 읽는다 (탭 줄 제외)', () => {
  assert.equal(extractQuestion(fx('choice-question.txt')), 'Which color do you prefer?')
})
test('폴더 신뢰 화면을 신뢰 질문으로 읽는다', () => {
  assert.match(extractQuestion(fx('trust-prompt.txt')), /신뢰할까요/)
})
test('윈도우 Claude Code의 ● 응답 머리도 마지막 말로 읽는다', () => {
  const rule = '─'.repeat(40)
  assert.equal(extractLastSay(`❯ hi\n● ok\n${rule}\n❯ \n${rule}`), 'ok')
})
