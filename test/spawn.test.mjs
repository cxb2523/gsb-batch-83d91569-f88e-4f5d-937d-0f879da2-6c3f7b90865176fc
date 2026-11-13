// #2 없는 폴더로 열기가 프로세스를 죽이지 않는다. HERDR_BIN을 가짜로 고정해 실제 herdr를 띄우지 않는다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
process.env.HERDR_BIN = fileURLToPath(new URL('../test-support/fake-herdr.mjs', import.meta.url))
delete process.env.HERDR_BIN_PATH
const herdr = await import('../src/runtime/herdr.mjs')

test('focus: 꺼진 세션을 없는 폴더로 띄우면 cwd_missing으로 거절하고 프로세스는 산다', async () => {
  await assert.rejects(herdr.focus('ghost/w1:p1', { cwd: '/nonexistent/whosup-test-dir' }), (err) => err.code === 'cwd_missing')
  await new Promise((r) => setTimeout(r, 200)) // 비동기 spawn 'error'가 터질 틈
})

test('newSession: 없는 폴더면 cwd_missing', async () => {
  await assert.rejects(herdr.newSession({ session: 'ghost', cwd: '/nonexistent/whosup-test-dir' }), (err) => err.code === 'cwd_missing')
})
