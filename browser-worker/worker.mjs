// A private Unix socket bridges the existing config volume. No public listener.
import http from 'node:http'
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFile, writeFile, mkdir, chmod, unlink, stat } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'
import { VERSION, TOOLS, input, argv, rows, restoreState } from './contract.mjs'

process.umask(0o077)
const root = dirname(fileURLToPath(import.meta.url))
const socketPath = process.env.REDDIT_BROWSER_SOCKET || resolve(root, '../webmirage-config/reddit-browser.sock')
const profile = process.env.REDDIT_BROWSER_PROFILE || resolve(root, '../gateway/data/reddit-browser/profile')
const proxy = process.env.REDDIT_BROWSER_PROXY || 'http://127.0.0.1:7890'
const executable = process.env.REDDIT_BROWSER_EXECUTABLE
const cli = resolve(root, 'node_modules/@jackwener/opencli/dist/src/main.js')
const sourceLock = JSON.parse(await readFile(resolve(root, 'reddit-source-lock.json'), 'utf8'))
const packageInfo = JSON.parse(await readFile(resolve(root, 'node_modules/@jackwener/opencli/package.json'), 'utf8'))
if (packageInfo.version !== VERSION) throw new Error('OpenCLI version mismatch')
for (const [name, expected] of Object.entries(sourceLock.files)) {
  const data = await readFile(resolve(root, 'node_modules/@jackwener/opencli/clis/reddit', name))
  if (createHash('sha256').update(data).digest('hex') !== expected) throw new Error('Run prepare_runtime.py to restore reviewed adapters')
}
const idleSeconds = Number(process.env.REDDIT_BROWSER_IDLE_SECONDS || 600)
const operationMs = Math.max(1000, Math.min(32000, Number(process.env.REDDIT_BROWSER_OPERATION_TIMEOUT_MS) || 32000))
let context, page, endpoint, cookieRevision, activeChild, busy = false, lastActivity = 0, lastFailure = null, cooldownUntil = 0
const stateFile = resolve(dirname(profile), 'worker-state.json')
await mkdir(dirname(stateFile), { recursive: true, mode: 0o700 })
// Corrupt or tampered state must never take the worker down or surface raw text.
let savedState = {}
try { savedState = JSON.parse(await readFile(stateFile, 'utf8')) }
catch (error) { if (error.code !== 'ENOENT') savedState = {} }
const restored = restoreState(savedState)
cooldownUntil = restored.cooldownUntil
lastFailure = restored.lastFailure
const digest = s => createHash('sha256').update(s).digest('hex')
function status() {
  return { available: true, version: VERSION, running: !!context, session_imported: !!cookieRevision,
    busy, last_activity: lastActivity || null, last_failure: lastFailure, cooldown_until: cooldownUntil,
    idle_seconds: idleSeconds, supported_tools: TOOLS }
}
async function close() {
  const current = context
  context = page = endpoint = cookieRevision = undefined
  if (current) await current.close().catch(() => {})
}
async function prepare(cookie, force = false) {
  const pairs = cookie.split(';').map(p => p.trim()).filter(p => p.includes('='))
    .map(p => { const i = p.indexOf('='); return { name: p.slice(0, i).trim(), value: p.slice(i + 1).trim(), domain: '.reddit.com', path: '/', secure: true } })
    .filter(p => /^[A-Za-z0-9_-]+$/.test(p.name) && p.value)
  if (!pairs.some(p => p.name === 'reddit_session')) throw new Error('missing')
  if (!context) {
    await mkdir(profile, { recursive: true, mode: 0o700 })
    await chmod(profile, 0o700)
    context = await chromium.launchPersistentContext(profile, {
      executablePath: executable, headless: true, proxy: { server: proxy, bypass: 'localhost,127.0.0.1' },
      args: ['--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0'],
      timeout: 15000, viewport: { width: 1280, height: 900 },
    })
    context.on('close', () => { context = page = endpoint = cookieRevision = undefined })
    page = context.pages()[0] || await context.newPage()
    for (const extra of context.pages().slice(1)) await extra.close()
    // Bind OpenCLI to this exact page, never another user's browser tab.
    const cdp = await context.newCDPSession(page)
    const target = await cdp.send('Target.getTargetInfo')
    await cdp.detach()
    const port = (await readFile(resolve(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]
    if (!/^\d+$/.test(port)) throw new Error('browser')
    endpoint = `ws://127.0.0.1:${port}/devtools/page/${target.targetInfo.targetId}`
    // Keep browser-refreshed cookies when the imported config has not changed.
    const saved = await readFile(resolve(profile, 'webmirage-cookie-revision'), 'utf8').catch(() => '')
    const stored = await context.cookies('https://www.reddit.com')
    if (saved === digest(cookie) && stored.some(c => c.name === 'reddit_session' && c.value)) cookieRevision = saved
  }
  const revision = digest(cookie)
  if (force || revision !== cookieRevision) {
    await context.clearCookies()
    await context.addCookies(pairs)
    cookieRevision = revision
    await writeFile(resolve(profile, 'webmirage-cookie-revision'), revision, { mode: 0o600 })
  }
  lastActivity = Date.now() / 1000
}
async function execute(body, deadline) {
  const environment = { ...process.env, OPENCLI_CDP_ENDPOINT: endpoint, OPENCLI_SITE_SESSION: 'persistent',
    OPENCLI_BROWSER_CONNECT_TIMEOUT: '5', OPENCLI_BROWSER_COMMAND_TIMEOUT: '20' }
  for (const k of ['OPENCLI_PROFILE','OPENCLI_CDP_TARGET','OPENCLI_SITE_SLOTS','OPENCLI_VERBOSE','DEBUG_SNAPSHOT','OPENCLI_CDP_INIT_SCRIPT']) delete environment[k]
  return await new Promise((resolvePromise, reject) => {
    const child = spawn(process.execPath, [cli, ...argv(body)], { env: environment, stdio: ['ignore','pipe','pipe'] })
    activeChild = child
    let output = '', size = 0, exceeded = false, timedOut = false
    const timer = setTimeout(() => { timedOut = true; child.kill('SIGKILL') }, Math.max(1000, deadline - Date.now()))
    child.stdout.on('data', data => { size += data.length; if (size > 2_000_000) { exceeded = true; child.kill('SIGKILL') } else output += data })
    child.stderr.on('data', () => {}) // CLI diagnostics can contain request contents; discard.
    child.on('error', () => { clearTimeout(timer); reject(new Error('browser')) })
    child.on('close', code => {
      if (activeChild === child) activeChild = undefined
      clearTimeout(timer)
      if (timedOut) return reject(new Error('network'))
      if (exceeded) return reject(new Error('interface'))
      try { resolvePromise(rows(JSON.parse(output), code)) } catch (error) {
        reject(new Error(['rate_limit','forbidden','risk','auth','network'].includes(error.message) ? error.message : 'interface'))
      }
    })
  })
}
const server = http.createServer(async (req, res) => {
  const send = (code, data) => { res.writeHead(code, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(data)) }
  if (req.method !== 'POST' || req.url !== '/') return send(404, { ok: false, category: 'bad_input' })
  let raw = '', size = 0, owned = false
  try {
    for await (const chunk of req) {
      size += chunk.length
      if (size > 40000) return send(413, { ok: false, category: 'bad_input' })
      raw += chunk
    }
    const body = input(JSON.parse(raw))
    if (body.action === 'status') return send(200, { ok: true, status: { ...status(), session_current: !!cookieRevision && cookieRevision === body.revision } })
    if (busy) return send(409, { ok: false, category: 'busy' })
    if (body.action !== 'stop' && Date.now() / 1000 < cooldownUntil) return send(409, { ok: false, category: 'rate_limit' })
    busy = true
    owned = true
    const deadline = Date.now() + operationMs
    let deadlineTimer
    try {
      const operation = async () => {
        if (body.action === 'stop') await close()
        else {
          await prepare(body.cookie, body.action === 'start')
          if (Date.now() >= deadline) throw new Error('network')
          if (body.action === 'query') return await execute(body, deadline)
        }
      }
      const result = await Promise.race([operation(), new Promise((_, reject) => {
        deadlineTimer = setTimeout(() => reject(new Error('network')), operationMs)
      })])
      lastActivity = Date.now() / 1000
      lastFailure = null
      await writeFile(stateFile, JSON.stringify({ cooldown_until: cooldownUntil, last_failure: null }), { mode: 0o600 }).catch(() => {})
      return send(200, { ok: true, ...(body.action === 'query' ? { rows: result } : {}), status: { ...status(), busy: false } })
    } finally { clearTimeout(deadlineTimer) }
  } catch (error) {
    const safe = ['bad_input','unsupported','missing','rate_limit','forbidden','risk','auth','network','interface','browser'].includes(error.message) ? error.message : 'browser'
    lastFailure = safe
    if (safe === 'rate_limit') cooldownUntil = Date.now() / 1000 + 3600
    await writeFile(stateFile, JSON.stringify({ cooldown_until: cooldownUntil, last_failure: safe }), { mode: 0o600 }).catch(() => {})
    // Kill outstanding in-page work before the next request after a timeout/failure.
    if (owned && !['bad_input','unsupported','missing'].includes(safe)) {
      if (activeChild) activeChild.kill('SIGKILL')
      await close()
    }
    send(200, { ok: false, category: safe, status: { ...status(), busy: false } })
  } finally { if (owned) busy = false }
})
server.requestTimeout = 45000
await mkdir(dirname(socketPath), { recursive: true })
try {
  const info = await stat(socketPath)
  if (!info.isSocket()) throw new Error('Socket path is occupied by a regular file')
  // systemd owns this sole worker; refuse to replace an active listener.
  const active = await new Promise(resolvePromise => {
    const check = http.request({ socketPath, method: 'POST', path: '/', timeout: 1000 }, res => { res.resume(); resolvePromise(true) })
    check.on('error', () => resolvePromise(false)); check.on('timeout', () => { check.destroy(); resolvePromise(true) }); check.end('{}')
  })
  if (active) throw new Error('A browser worker is already running')
  await unlink(socketPath)
} catch (error) { if (error.code !== 'ENOENT') throw error }
await new Promise((resolvePromise, reject) => { server.once('error', reject); server.listen(socketPath, resolvePromise) })
await chmod(socketPath, 0o600)
setInterval(() => {
  if (!busy && context && Date.now() / 1000 - lastActivity > idleSeconds) { busy = true; close().finally(() => { busy = false }) }
}, 10000).unref()
let shuttingDown = false
async function shutdown() {
  if (shuttingDown) return
  shuttingDown = true
  server.close()
  await close()
  await unlink(socketPath).catch(() => {})
  process.exit(0)
}
process.on('SIGTERM', shutdown); process.on('SIGINT', shutdown)
console.log('Reddit browser worker ready (private Unix socket)')
