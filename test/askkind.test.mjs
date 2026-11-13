// #17 권한 상자·폴더 신뢰는 승인(approval), 그 밖의 물음은 질문(question). 화면 대체 문구는 승인일 때만 "승인 대기".
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { questionOf } from '../src/board/context.mjs'

const rule = '─'.repeat(40)
test('#17: 권한 상자는 approval', () => {
  const t = ['╭' + rule, '│ Bash command', '│   npm run build', '│ Do you want to proceed?', '│ ❯ 1. Yes', '│   2. No', '╰' + rule].join('\n')
  assert.equal(questionOf(t)?.kind, 'approval')
})
test('#17: 폴더 신뢰는 approval', () => assert.equal(questionOf('Do you trust this folder?\n Yes, I trust this folder')?.kind, 'approval'))
test('#17: 에이전트가 묻는 말은 question', () => assert.equal(questionOf('⏺ 어느 쪽으로 진행할까요?\n')?.kind, 'question'))
test('#17: 화면 대체 문구는 승인일 때만 승인 대기', () => {
  const html = readFileSync(new URL('../src/board/index.html', import.meta.url), 'utf8')
  assert.match(html, /ask_kind === 'approval' \? T\.waiting : T\.needsInput/)
})
