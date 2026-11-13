// Local-only integration fixtures: never contact Reddit or use real cookies.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import http from 'node:http'
import net from 'node:net'
import { once } from 'node:events'
const browserPath = process.env.CHROMIUM_PATH || '/home/lcarus/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome'
function request(socketPath, body) {
  return new Promise((resolve, reject) => {
    const req = http.request({ socketPath, method: 'POST', path: '/', timeout: 12000 }, res => {
      let text = ''; res.on('data', x => { text += x }); res.on('end', () => { try { resolve(JSON.parse(text)) } catch (e) { reject(e) } })
    }); req.on('error', reject); req.on('timeout', () => req.destroy(new Error('fixture timeout'))); req.end(JSON.stringify(body))
  })
}
async function start(folder, proxy) {
  const socketPath = join(folder, 'worker.sock')
  const child = spawn(process.execPath, ['worker.mjs'], { cwd: new URL('.', import.meta.url),
    env: { ...process.env, REDDIT_BROWSER_SOCKET: socketPath, REDDIT_BROWSER_PROFILE: join(folder, 'state/profile'),
      REDDIT_BROWSER_EXECUTABLE: browserPath, REDDIT_BROWSER_PROXY: proxy, REDDIT_BROWSER_OPERATION_TIMEOUT_MS: '3000' }, stdio: 'ignore' })
  for (let i = 0; i < 100; i++) {
    try { await request(socketPath, { action: 'status' }); return { child, socketPath } } catch {}
    if (child.exitCode !== null) throw new Error('Fixture worker exited')
    await new Promise(resolve => setTimeout(resolve, 50))
  }
  child.kill(); throw new Error('Fixture worker did not start')
}
async function stop(child) { const ended = once(child, 'exit'); child.kill('SIGTERM'); await ended }

test('bounded timeout closes in-page work and the worker can start again', { skip: !existsSync(browserPath) }, async () => {
  const folder = await mkdtemp(join(tmpdir(), 'mirage-browser-test-'))
  const sockets = new Set()
  // A proxy that deliberately never completes CONNECT; it never forwards traffic.
  const proxy = net.createServer(socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)) })
  proxy.listen(0, '127.0.0.1'); await once(proxy, 'listening')
  let worker
  try {
    worker = await start(folder, `http://127.0.0.1:${proxy.address().port}`)
    const result = await request(worker.socketPath, { action: 'query', tool: 'reddit_search', cookie: 'reddit_session=TEST-ONLY', args: { query: 'test', limit: 1 } })
    assert.equal(result.ok, false)
    assert.equal(result.category, 'network')
    const status = await request(worker.socketPath, { action: 'status' })
    assert.equal(status.status.running, false)
    assert.equal(status.status.busy, false)
    const again = await request(worker.socketPath, { action: 'start', cookie: 'reddit_session=TEST-ONLY' })
    assert.equal(again.ok, true)
    assert.equal(again.status.running, true)
    assert.equal((await request(worker.socketPath, { action: 'stop' })).status.running, false)
  } finally {
    if (worker) await stop(worker.child)
    for (const socket of sockets) socket.destroy()
    proxy.close()
    await rm(folder, { recursive: true, force: true })
  }
})

test('rate-limit cooldown survives worker restart without launching a browser', async () => {
  const folder = await mkdtemp(join(tmpdir(), 'mirage-cooldown-test-'))
  let worker
  try {
    await mkdir(join(folder, 'state'))
    const until = Date.now() / 1000 + 1000
    await writeFile(join(folder, 'state/worker-state.json'), JSON.stringify({ cooldown_until: until, last_failure: 'rate_limit' }))
    for (let i = 0; i < 2; i++) {
      worker = await start(folder, 'http://127.0.0.1:1')
      const result = await request(worker.socketPath, { action: 'start', cookie: 'reddit_session=TEST-ONLY' })
      assert.equal(result.category, 'rate_limit')
      const status = await request(worker.socketPath, { action: 'status' })
      assert.equal(status.status.cooldown_until, until)
      assert.equal(status.status.running, false)
      await stop(worker.child); worker = undefined
    }
  } finally {
    if (worker) await stop(worker.child)
    await rm(folder, { recursive: true, force: true })
  }
})
