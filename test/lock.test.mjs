// #1 상태 폴더당 후즈업 하나: 같은 상태 폴더로 두 번째 후즈업을 띄우면 수집기를 돌리지 않고 바로 나간다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { acquireLock } from '../src/db.mjs'
import { fileURLToPath } from 'node:url'

const BIN = fileURLToPath(new URL('../bin/whosup.mjs', import.meta.url))
const FAKE = fileURLToPath(new URL('../test-support/fake-herdr.mjs', import.meta.url))

test('acquireLock: 같은 폴더의 두 번째 잠금은 실패하고, 첫 잠금을 놓으면 다시 잡힌다', () => {
  const dir = mkdtempSync(join(tmpdir(), 'whosup-lock-'))
  const a = acquireLock(dir)
  assert.ok(a)
  assert.equal(acquireLock(dir), null)
  a.close()
  const b = acquireLock(dir)
  assert.ok(b)
  b.close()
})

function run(env, nodeArgs = []) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [...nodeArgs, BIN], { env: { ...process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] })
    let out = ''
    child.stdout.on('data', (d) => { out += d; if (/listening/.test(out)) resolve({ child, out, code: null }) })
    child.stderr.on('data', (d) => { out += d })
    child.on('exit', (code) => resolve({ child, out, code }))
  })
}

test('whosup 두 번 기동: 두 번째는 기존 포트를 알리고 exit 0', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'whosup-dup-'))
  const env = { WHOSUP_STATE_DIR: dir, HERDR_BIN: FAKE, HERDR_BIN_PATH: FAKE, PORT: String(47900 + Math.floor(Math.random() * 90)), WHOSUP_INTERVAL: '60' }
  const first = await run(env)
  try {
    assert.equal(first.code, null, first.out)
    const port = readFileSync(join(dir, 'port'), 'utf8')
    const second = await run(env)
    assert.equal(second.code, 0, second.out)
    assert.match(second.out, new RegExp(`already running.*${port}`))
  } finally { first.child.kill('SIGTERM') }
})

// 잠금 핸들을 아무도 참조하지 않으면 GC가 거둬 잠금이 풀린다(요청 수백 번 뒤 두 번째 후즈업이 함께 떴다).
// 첫 후즈업에서 gc()를 여러 번 돌린 뒤에도 두 번째 기동이 거절되는지 본다.
test('whosup 잠금은 GC 뒤에도 유지된다: gc() 뒤 두 번째 기동도 거절', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'whosup-gc-'))
  const env = { WHOSUP_STATE_DIR: dir, HERDR_BIN: FAKE, HERDR_BIN_PATH: FAKE, PORT: String(47900 + Math.floor(Math.random() * 90)), WHOSUP_INTERVAL: '60' }
  const gcLoop = 'data:text/javascript,setInterval(()=>globalThis.gc(),20).unref()'
  const first = await run(env, ['--expose-gc', '--import', gcLoop])
  try {
    assert.equal(first.code, null, first.out)
    await new Promise((r) => setTimeout(r, 500))
    const second = await run(env)
    if (second.code === null) second.child.kill('SIGTERM')
    assert.equal(second.code, 0, `second whosup started alongside the first:\n${second.out}`)
    assert.match(second.out, /already running/)
  } finally { first.child.kill('SIGTERM') }
})
