// /api/health는 herdr에 닿지 못해도 200(프로세스가 답하는가만 말한다), /api/new는 세션 이름을 검사한다,
// 다른 출처의 POST는 막는다. plugin.sh start는 herdr가 없어도 성공으로 끝나고 pid 파일이 맞게 남는다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, existsSync } from 'node:fs'
import { tmpdir, homedir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const BIN = join(ROOT, 'bin/whosup.mjs')
const NO_HERDR = '/nonexistent/whosup-test/herdr'
const port = () => 4900 + Math.floor(Math.random() * 21)

function start(env) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [BIN], { env: { ...process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] })
    let out = ''
    child.once('error', reject)
    child.stdout.on('data', (d) => { out += d; const m = out.match(/listening at (http:\S+)/); if (m) resolve({ child, url: m[1] }) })
    child.stderr.on('data', (d) => { out += d })
    child.on('exit', (code) => reject(new Error(`exited ${code}: ${out}`)))
  })
}

test('herdr에 닿지 못해도 /api/health는 200, /api/new는 이상한 세션 이름을 400으로 막고, 다른 출처 POST는 403', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'whosup-api-'))
  const { child, url } = await start({ WHOSUP_STATE_DIR: dir, HERDR_BIN: NO_HERDR, HERDR_BIN_PATH: NO_HERDR, PORT: String(port()), WHOSUP_INTERVAL: '60' })
  try {
    const h = await fetch(`${url}/api/health`)
    assert.equal(h.status, 200)
    const hb = await h.json()
    assert.equal(hb.ok, true)
    assert.equal(hb.herdr, null)
    assert.match(hb.herdr_error, /ENOENT/)

    const post = (path, body, headers = {}) => fetch(`${url}${path}`, { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: JSON.stringify(body) })
    for (const session of ['--help', '-x', 'a b', 'a;b', '', 42]) {
      const r = await post('/api/new', { session, cwd: homedir() })
      assert.equal(r.status, 400, `session ${JSON.stringify(session)}`)
      assert.equal((await r.json()).code, 'bad_request')
    }
    const d = await post('/api/desk', { session: '--help' })
    assert.equal(d.status, 400)

    const evil = await post('/api/seen', { id: 1 }, { origin: 'http://evil.example' })
    assert.equal(evil.status, 403)
    const evilLocalOtherPort = await post('/api/seen', { id: 1 }, { origin: 'http://127.0.0.1:1' })
    assert.equal(evilLocalOtherPort.status, 403)
  } finally { child.kill('SIGTERM') }
})

test('plugin.sh start: herdr가 없어도 성공으로 끝나고 pid 파일이 실제 프로세스를 가리키며, stop이 그 프로세스를 끈다', { skip: process.platform === 'win32' }, () => {
  const state = mkdtempSync(join(tmpdir(), 'whosup-plug-'))
  const conf = mkdtempSync(join(tmpdir(), 'whosup-conf-'))
  const env = { ...process.env, PATH: `${join(process.execPath, '..')}:${process.env.PATH}`, HERDR_PLUGIN_STATE_DIR: state, HERDR_PLUGIN_CONFIG_DIR: conf, PORT: String(port()), OPEN_BROWSER: '0', HERDR_BIN: NO_HERDR, HERDR_BIN_PATH: NO_HERDR, WHOSUP_INTERVAL: '60' }
  const sh = (cmd) => spawnSync('sh', [join(ROOT, 'scripts/plugin.sh'), cmd], { env, encoding: 'utf8', timeout: 20000 })
  let pid
  try {
    const s = sh('start')
    assert.equal(s.status, 0, s.stdout + s.stderr)
    assert.match(s.stdout, /listening/)
    pid = Number(readFileSync(join(state, 'server.pid'), 'utf8'))
    assert.doesNotThrow(() => process.kill(pid, 0))
    const st = sh('status')
    assert.equal(st.status, 0, st.stdout + st.stderr)
    const again = sh('start')
    assert.match(again.stdout, /already listening/)
    assert.equal(Number(readFileSync(join(state, 'server.pid'), 'utf8')), pid)
    const stop = sh('stop')
    assert.equal(stop.status, 0, stop.stdout + stop.stderr)
    assert.equal(existsSync(join(state, 'server.pid')), false)
    assert.throws(() => process.kill(pid, 0))
    pid = null
  } finally {
    // 실패해도 띄운 서버를 남기지 않는다.
    if (pid) try { process.kill(pid, 'SIGTERM') } catch {}
    if (existsSync(join(state, 'server.pid'))) sh('stop')
  }
})
