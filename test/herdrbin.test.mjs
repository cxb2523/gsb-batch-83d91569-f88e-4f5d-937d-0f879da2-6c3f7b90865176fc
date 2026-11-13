// I-4 herdr 실행 파일 찾기는 한 곳: HERDR_BIN_PATH만 있는 환경에서도 칸 화면 읽기가 같은 파일을 쓴다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
const FAKE = fileURLToPath(new URL('../test-support/fake-herdr.mjs', import.meta.url))
delete process.env.HERDR_BIN
process.env.HERDR_BIN_PATH = FAKE
const { readPane } = await import('../src/board/context.mjs')
const { bin } = await import('../src/runtime/herdr.mjs')

test('readPane은 수집기와 같은 herdr 실행 파일을 쓴다', () => {
  assert.equal(bin(), FAKE)
  assert.match(readPane('main', 'w1:p1'), /FAKE PANE SCREEN/)
})
