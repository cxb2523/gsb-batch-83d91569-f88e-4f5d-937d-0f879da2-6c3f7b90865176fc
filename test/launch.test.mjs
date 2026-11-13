// 윈도우 진입점 scripts/launch.mjs(plugin.sh를 Node로 옮긴 것)와 herdr-plugin.toml의 플랫폼 분기.
// 실제 herdr·브라우저에는 닿지 않는다: 없는 herdr 경로, OPEN_BROWSER=0, 임시 상태 폴더, 무작위 포트(48000~48089).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseEnvFile, loadEnv, pidAlive } from '../scripts/launch.mjs'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const NO_HERDR = join(tmpdir(), 'whosup-test-no-herdr', 'herdr')
const port = () => 48000 + Math.floor(Math.random() * 90)

test('.env는 실행하지 않고 KEY=VALUE로만 읽는다(따옴표 한 겹, 주석, export, $ 그대로)', () => {
  const env = parseEnvFile([
    '# 주석',
    'PORT=4811',
    'export OPEN_BROWSER=0',
    "FRONT_APP='Windows Terminal (Preview)'",
    'AGENT_CMD="claude --dangerously-skip-permissions"',
    'HERDR_BIN=C:\\Program Files\\herdr\\herdr.exe   # 설치 위치',
    'X=$(rm -rf ~)',
    'bad line',
    '1BAD=x',
    '',
  ].join('\r\n'))
  assert.deepEqual(env, {
    PORT: '4811', OPEN_BROWSER: '0', FRONT_APP: 'Windows Terminal (Preview)', AGENT_CMD: 'claude --dangerously-skip-permissions',
    HERDR_BIN: 'C:\\Program Files\\herdr\\herdr.exe', X: '$(rm -rf ~)',
  })
})
test('.env 값이 환경을 덮는다(plugin.sh의 set -a 순서와 같다)', () => {
  const conf = mkdtempSync(join(tmpdir(), 'whosup-lconf-'))
  writeFileSync(join(conf, '.env'), 'PORT=4999\n')
  assert.equal(loadEnv({ HERDR_PLUGIN_CONFIG_DIR: conf, PORT: '1' }).PORT, '4999')
  assert.equal(loadEnv({ HERDR_PLUGIN_CONFIG_DIR: join(conf, 'none'), PORT: '1' }).PORT, '1')
})

test('launch.mjs start·status·stop: herdr가 없어도 뜨고, pid 파일이 실제 프로세스를 가리키며, stop이 끈다', () => {
  const state = mkdtempSync(join(tmpdir(), 'whosup-lstate-'))
  const conf = mkdtempSync(join(tmpdir(), 'whosup-lconf-'))
  const env = { ...process.env, HERDR_PLUGIN_STATE_DIR: state, HERDR_PLUGIN_CONFIG_DIR: conf, PORT: String(port()), OPEN_BROWSER: '0', HERDR_BIN: NO_HERDR, HERDR_BIN_PATH: NO_HERDR, WHOSUP_INTERVAL: '60', WHOSUP_NO_EVENTS: '1' }
  const L = (cmd) => spawnSync(process.execPath, [join(ROOT, 'scripts/launch.mjs'), cmd], { env, encoding: 'utf8', timeout: 30000 })
  let pid
  try {
    const pre = L('preflight')
    assert.equal(pre.status, 0, pre.stdout + pre.stderr)
    assert.equal(L('status').status, 1)
    const s = L('start')
    assert.equal(s.status, 0, s.stdout + s.stderr)
    assert.match(s.stdout, /listening at http:\/\/127\.0\.0\.1:\d+/)
    pid = Number(readFileSync(join(state, 'server.pid'), 'utf8'))
    assert.equal(pidAlive(pid), true)
    const st = L('status')
    assert.equal(st.status, 0, st.stdout + st.stderr)
    assert.match(st.stdout, new RegExp(`pid ${pid}`))
    const again = L('start')
    assert.match(again.stdout, /already listening/)
    assert.equal(Number(readFileSync(join(state, 'server.pid'), 'utf8')), pid)
    const stop = L('stop')
    assert.equal(stop.status, 0, stop.stdout + stop.stderr)
    assert.equal(existsSync(join(state, 'server.pid')), false)
    assert.equal(pidAlive(pid), false)
    pid = null
    assert.match(L('stop').stdout, /not running/)
  } finally {
    if (pid) try { process.kill(pid, 'SIGTERM') } catch {}
  }
})

test('herdr-plugin.toml: windows 항목은 node로, linux·macos 항목의 sh 명령은 그대로', () => {
  const toml = readFileSync(join(ROOT, 'herdr-plugin.toml'), 'utf8')
  assert.match(toml, /^platforms = \["linux", "macos", "windows"\]$/m)
  // 원래(aa1a671) 있던 sh 명령 줄 8개가 글자 그대로 남아 있다
  const shLines = [
    'command = ["sh", "scripts/preflight.sh"]', 'command = ["sh", "scripts/plugin.sh", "start"]', 'command = ["sh", "scripts/plugin.sh", "start"]',
    'command = ["sh", "scripts/plugin.sh", "stop"]', 'command = ["sh", "scripts/plugin.sh", "status"]',
    'command = ["sh", "-c", ". scripts/node-path.sh && exec node scripts/desks.mjs apply"]', 'command = ["sh", "-c", ". scripts/node-path.sh && exec node scripts/desks.mjs status"]',
    'command = ["sh", "scripts/plugin.sh", "open"]',
    // 2회차: 자동 세팅 액션(설치·시작 때는 preflight가 부른다)
    'command = ["sh", "-c", ". scripts/node-path.sh && exec node scripts/autoconf.mjs"]',
  ]
  const have = toml.split('\n').filter((l) => l.startsWith('command = ["sh"'))
  assert.deepEqual(have, shLines)
  // 항목마다 platforms를 갖고, sh 항목은 windows에서 돌지 않는다
  const items = toml.split(/^\[\[/m).slice(1)
  for (const it of items) {
    const pl = /^platforms = (\[.*\])$/m.exec(it)?.[1]
    assert.ok(pl, `platforms missing: ${it.slice(0, 60)}`)
    if (/command = \["sh"/.test(it)) assert.equal(pl, '["linux", "macos"]')
    else assert.equal(pl, '["windows"]')
    if (pl === '["windows"]') assert.match(it, /command = \["node", "scripts\/(launch|desks|doctor|autoconf)\.mjs"/)
  }
  // action id는 플러그인 안에서 유일해야 한다(herdr 문서)
  const ids = [...toml.matchAll(/^id = "([^"]+)"$/gm)].map((m) => m[1]).filter((x) => x !== 'fivetaku.whosup')
  assert.equal(new Set(ids).size, ids.length)
  // build·startup·액션 모두 윈도우 짝이 있다
  for (const k of ['build', 'startup']) assert.equal((toml.match(new RegExp(`^\\[\\[${k}\\]\\]$`, 'gm')) || []).length, 2, k)
  for (const a of ['start', 'stop', 'status', 'desks-apply', 'desks-status', 'open', 'autoconf']) assert.ok(ids.includes(`win-${a}`), a)
})
