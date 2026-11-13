// 2회차 자동 세팅: 레인 L1~L10 순수 함수(darwin·linux·win32 주입), 감지 실패 → 값 없음, 사람 값(DB·env) > auto, auto.json·.env 미생성.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  evaluate, envFromProc, envFromPs, laneAccessibility, laneAgent, laneCore, laneDesktop, laneHerdr, laneNode, laneOS, laneOvis,
  lanePort, laneTerminal, ovisSignature, probeOvis, ovisUrl, readAuto, sessionOfSocket, writeAuto,
} from '../src/autoconf.mjs'
import { openDb } from '../src/db.mjs'
import { clientDefaults, getSettings, setAutoValues, setSettings, settingOrigins, settingSources } from '../src/settings.mjs'
import { autoconfView, createBoardServer, firstRunDone } from '../src/board/server.mjs'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const FAKE_HERDR = join(ROOT, 'test-support', 'fake-herdr.mjs')
const OSES = ['darwin', 'linux', 'win32']
const val = (items, key) => items.find((i) => i.key === key)?.value
const has = (items, key) => items.some((i) => i.key === key)
const local = { darwin: {}, linux: { DISPLAY: ':0' }, win32: { SESSIONNAME: 'Console' } }

test('L1 OS: darwin·linux·win32 각각 실행기와 OS 알림 노출을 정하고, 모르는 OS는 값 없음', () => {
  for (const p of OSES) {
    const r = laneOS({ platform: p, release: '1.0' })
    assert.equal(val(r, 'os'), p)
    assert.equal(val(r, 'launcher'), p === 'win32' ? 'node' : 'sh')
    assert.equal(val(r, 'os_notify_available'), p !== 'win32')
  }
  assert.equal(val(laneOS({ platform: 'aix' }), 'os'), undefined)
})

test('L2 Node·sqlite: 22.13 이상 + node:sqlite만 통과(세 OS 같은 규칙), 버전 모르면 값 없음', () => {
  for (const p of OSES) {
    assert.equal(val(laneNode({ platform: p, node: { version: 'v22.13.0', sqlite: true } }), 'node_ok'), true)
    assert.equal(val(laneNode({ platform: p, node: { version: 'v22.12.9', sqlite: true } }), 'node_ok'), false)
    assert.equal(val(laneNode({ platform: p, node: { version: 'v24.1.0', sqlite: false } }), 'node_ok'), false)
    assert.equal(val(laneNode({ platform: p }), 'node_ok'), undefined)
  }
})

test('L3 데스크톱 세션: 원격(SSH·윈도우 세션 0·리눅스 화면 없음)이면 open_browser=0, 데스크톱이면 자동 값 없음', () => {
  for (const p of OSES) {
    const here = laneDesktop({ platform: p, env: local[p] })
    assert.equal(val(here, 'desktop'), true, p)
    assert.equal(val(here, 'open_browser'), undefined, p)
    const ssh = laneDesktop({ platform: p, env: { ...local[p], SSH_CONNECTION: '1 2 3 4' } })
    assert.equal(val(ssh, 'desktop'), false, p)
    assert.equal(val(ssh, 'open_browser'), 0, p)
  }
  assert.equal(val(laneDesktop({ platform: 'win32', env: {} }), 'open_browser'), 0, '윈도우 SESSIONNAME 없음 = 세션 0')
  assert.equal(val(laneDesktop({ platform: 'win32', env: {}, winSession: 3 }), 'desktop'), true, '윈도우 로그온 예약 작업: SESSIONNAME 없어도 세션 3이면 데스크톱')
  assert.equal(val(laneDesktop({ platform: 'win32', env: {}, winSession: 0 }), 'open_browser'), 0, '윈도우 세션 0')
  assert.equal(val(laneDesktop({ platform: 'win32', env: { SSH_CONNECTION: '1 2 3 4' }, winSession: 3 }), 'open_browser'), 0, 'SSH면 세션 번호와 상관없이 원격')
  assert.equal(val(laneDesktop({ platform: 'linux', env: {} }), 'open_browser'), 0, '리눅스 DISPLAY 없음')
  assert.equal(val(laneDesktop({ platform: 'darwin', env: { SSH_TTY: '/dev/ttys001' } }), 'open_browser'), 0)
})

test('L4 터미널 앱: 맥 = 보여 주는 앱 > 설치 앱, 윈도우 = wt.exe면 Windows Terminal·원격이면 off, 리눅스 = 값 없음', () => {
  assert.equal(val(laneTerminal({ platform: 'darwin', env: {}, terminal: { showing: 'iTerm2', installed: ['Ghostty'] } }), 'front_app'), 'iTerm2')
  assert.equal(val(laneTerminal({ platform: 'darwin', env: {}, terminal: { showing: null, installed: ['Terminal', 'Ghostty'] } }), 'front_app'), 'Ghostty')
  assert.equal(val(laneTerminal({ platform: 'darwin', env: {}, terminal: { showing: null, installed: ['Terminal'] } }), 'front_app'), undefined, 'Terminal만 있으면 기본값(자동)과 같다')
  assert.equal(val(laneTerminal({ platform: 'darwin', env: {}, terminal: null }), 'front_app'), undefined, '감지 실패 → 값 없음')
  assert.equal(val(laneTerminal({ platform: 'win32', env: local.win32, tools: { wt: 'C:\\x\\wt.exe' } }), 'front_app'), 'Windows Terminal')
  assert.equal(val(laneTerminal({ platform: 'win32', env: local.win32, tools: { wt: null } }), 'front_app'), undefined, 'wt 없음 = 기본 PowerShell')
  assert.equal(val(laneTerminal({ platform: 'win32', env: { SSH_CONNECTION: 'x' }, tools: { wt: 'wt.exe' } }), 'front_app'), 'off')
  assert.equal(val(laneTerminal({ platform: 'linux', env: local.linux }), 'front_app'), undefined)
  assert.equal(val(laneTerminal({ platform: 'darwin', env: { SSH_CONNECTION: 'x' }, terminal: { showing: 'iTerm2', installed: ['Ghostty'] } }), 'front_app'), 'off', '맥도 원격이면 창 올리기 끔(L3)')
})

test('L5 herdr: 찾으면 읽기 대상 true, 못 찾으면 false, 확인 못 했으면 값 없음(세 OS)', () => {
  for (const p of OSES) {
    const r = laneHerdr({ platform: p, herdr: { found: true, version: 'herdr 0.9.3', sessions: [{ name: 'main', status: 'running' }, { name: 'x', status: 'stopped' }] } })
    assert.equal(val(r, 'runtime_herdr'), true)
    assert.match(r[0].reason, /running sessions: main$/)
    assert.equal(val(laneHerdr({ platform: p, herdr: { found: false, bin: 'herdr' } }), 'runtime_herdr'), false)
    assert.equal(val(laneHerdr({ platform: p }), 'runtime_herdr'), undefined)
  }
})

test('L6 Herdr 데스크톱 앱: core 소켓이 살아 있으면 읽기 대상, herdr-app 있으면 앱 이름(세 OS)', () => {
  for (const p of OSES) {
    const on = laneCore({ platform: p, herdrCore: { running: true, socket: '/s/core.sock' }, herdrApp: { found: true, bin: 'herdr-app' } })
    assert.equal(val(on, 'runtime_herdr_core'), true)
    assert.equal(val(on, 'herdr_app'), 'herdr-app')
    const off = laneCore({ platform: p, herdrCore: { running: false, socket: null }, herdrApp: { found: false, bin: 'herdr-app' } })
    assert.equal(val(off, 'runtime_herdr_core'), false)
    assert.equal(val(off, 'herdr_app'), undefined)
    assert.equal(val(laneCore({ platform: p }), 'runtime_herdr_core'), undefined)
  }
})

test('L7 ovis: 서명 확인된 서버만, 붙은 세션을 herdr가 알 때만 세션별 주소, 모르면 확인 필요 후보(세 OS)', () => {
  const sessions = [{ name: 'main', status: 'running', socket: '/h/sessions/main/herdr.sock' }, { name: 'side', status: 'running', socket: '/h/sessions/side/herdr.sock' }]
  for (const p of OSES) {
    const r = laneOvis({ platform: p, herdr: { sessions }, ovis: [
      { port: 7317, signed: true, socket: '/h/sessions/main/herdr.sock' },
      { port: 7318, signed: true, sessionEnv: 'side' },
      { port: 7319, signed: false },                                        // 서명 없는 HTTP 서버는 ovis로 보지 않는다
      { port: 7320, signed: true, socket: '/h/sessions/gone/herdr.sock' },   // herdr가 모르는 세션
      { port: 7321, signed: true, why: 'Windows: the listening process environment is not readable' },
    ] })
    assert.deepEqual(val(r, 'ovis'), [7317, 7318, 7320, 7321])
    assert.equal(val(r, 'open_url:main'), 'http://127.0.0.1:7317/?pane={pane}')
    assert.equal(val(r, 'open_url:side'), ovisUrl(7318))
    assert.equal(has(r, 'open_url:gone'), false)
    assert.ok(has(r, 'ovis_candidate:7320') && val(r, 'ovis_candidate:7320') === undefined)
    assert.match(r.find((i) => i.key === 'ovis_candidate:7321').reason, /check$/)
    assert.equal(r.some((i) => /7319/.test(i.key)), false)
  }
  assert.equal(val(laneOvis({ platform: 'darwin', ovis: [] }), 'ovis'), undefined, 'ovis 없음 → 값 없음')
  assert.equal(val(laneOvis({ platform: 'darwin', ovis: [{ port: 7317, answered: true, signed: false }] }), 'ovis'), undefined)
})

test('L7 ovis 보조: 서명·ps eww·/proc environ·소켓→세션', () => {
  assert.equal(ovisSignature({ ok: true, bridge_protocol: 1, web_ui: { boot_id: 'b' } }), true)
  assert.equal(ovisSignature({ ok: true }), false)
  assert.equal(ovisSignature({ error: { code: 'connect_failed' } }), false)
  assert.equal(ovisSignature(null), false)
  assert.deepEqual(envFromPs('bun server.ts PORT=7318 HERDR_SOCKET=/h/sessions/side/herdr.sock OTHER=1'), { socket: '/h/sessions/side/herdr.sock', sessionEnv: null })
  assert.deepEqual(envFromProc('A=1\0HERDR_SESSION=main\0HERDR_SOCKET=/s/main.sock\0'), { socket: '/s/main.sock', sessionEnv: 'main' })
  assert.equal(sessionOfSocket('/x/sessions/side/herdr.sock', []), 'side')
  assert.equal(sessionOfSocket('/odd/path.sock', [{ name: 'main', socket: '/odd/path.sock' }]), 'main')
  assert.equal(sessionOfSocket('/odd/path.sock', []), null)
})

test('L8 에이전트: claude > codex, 둘 다 없으면 값 없음(세 OS)', () => {
  for (const p of OSES) {
    assert.equal(val(laneAgent({ platform: p, agents: { claude: '/b/claude', codex: '/b/codex', projectsDir: '/p' } }), 'agent_cmd'), 'claude')
    assert.equal(val(laneAgent({ platform: p, agents: { claude: null, codex: '/b/codex', projectsDir: null } }), 'agent_cmd'), 'codex')
    const none = laneAgent({ platform: p, agents: { claude: null, codex: null, projectsDir: null } })
    assert.equal(val(none, 'agent_cmd'), undefined)
    assert.equal(val(none, 'resume_available'), false)
    assert.equal(val(laneAgent({ platform: p }), 'resume_available'), undefined)
  }
})

test('L9 맥 손쉬운 사용 권한: 맥에서 권한 없음이 확인됐을 때만 split_available=false, 그 밖은 값 없음', () => {
  assert.equal(val(laneAccessibility({ platform: 'darwin', raiseWarning: 'mac_accessibility' }), 'split_available'), false)
  assert.equal(val(laneAccessibility({ platform: 'darwin', raiseWarning: undefined }), 'split_available'), undefined)
  assert.equal(val(laneAccessibility({ platform: 'linux', raiseWarning: 'mac_accessibility' }), 'split_available'), undefined)
  assert.equal(val(laneAccessibility({ platform: 'win32' }), 'split_available'), undefined)
})

test('L10 포트: 빈 포트를 자동 값으로, 못 찾으면 값 없음(세 OS)', () => {
  for (const p of OSES) {
    assert.equal(val(lanePort({ platform: p, port: { start: 4790, free: 4790 } }), 'port'), 4790)
    assert.match(lanePort({ platform: p, port: { start: 4790, free: 4792 } })[0].reason, /4790-4791 busy/)
    assert.equal(val(lanePort({ platform: p, port: { start: 4790, free: null } }), 'port'), undefined)
    assert.equal(val(lanePort({ platform: p }), 'port'), undefined)
  }
})

test('감지 실패: 빈 입력이면 OS 말고는 자동 값이 하나도 없다(추측 금지)', () => {
  for (const p of OSES) {
    const r = evaluate({ platform: p, env: local[p] })
    const keys = Object.keys(r.values).filter((k) => !['os', 'launcher', 'os_notify_available', 'desktop'].includes(k))
    assert.deepEqual(keys, [], `${p}: ${keys}`)
    assert.equal(r.lanes.filter((l) => /^L\d+$/.test(l.lane)).length, r.lanes.length)
    for (const n of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) assert.ok(r.lanes.some((l) => l.lane === `L${n}`), `L${n} 없음`)
  }
})

test('우선순위: 설정 패널(DB) > 환경변수 > auto > 기본값, 사람이 정한 값은 auto가 못 이긴다', () => {
  const db = openDb(':memory:')
  const keep = { FRONT_APP: process.env.FRONT_APP, AGENT_CMD: process.env.AGENT_CMD, WHOSUP_SPLIT_PCT: process.env.WHOSUP_SPLIT_PCT }
  for (const k of Object.keys(keep)) delete process.env[k]
  try {
    setAutoValues({ values: { front_app: 'Ghostty', agent_cmd: 'codex', split_pct: 33 }, reasons: { front_app: 'L4: Ghostty.app is installed' } })
    assert.equal(getSettings(db).front_app, 'Ghostty')
    assert.deepEqual(settingOrigins(db).front_app, { source: 'auto', reason: 'L4: Ghostty.app is installed' })
    assert.equal(settingSources(db).front_app, 'auto')
    process.env.FRONT_APP = 'Terminal'
    assert.equal(getSettings(db).front_app, 'Terminal', '환경변수가 auto를 이긴다')
    assert.equal(settingOrigins(db).front_app.source, 'env')
    assert.equal(settingOrigins(db).front_app.name, 'FRONT_APP')
    setSettings(db, { front_app: 'iTerm', agent_cmd: 'claude', split_pct: 0 })
    assert.equal(getSettings(db).front_app, 'iTerm', '패널 값이 환경변수·auto를 이긴다')
    assert.equal(getSettings(db).agent_cmd, 'claude')
    assert.equal(getSettings(db).split_pct, 0, '패널 0도 사람 값이다(auto 33을 못 이김)')
    assert.deepEqual(settingOrigins(db).front_app, { source: 'panel' })
    setAutoValues({ values: { front_app: 'WezTerm', agent_cmd: 'codex' } })   // 다음 시작의 새 감지
    assert.equal(getSettings(db).front_app, 'iTerm', '다시 감지해도 사람 값은 그대로')
    setSettings(db, { front_app: '' }); delete process.env.FRONT_APP
    assert.equal(getSettings(db).front_app, 'WezTerm', '패널을 비우고 환경변수도 없으면 auto')
    setAutoValues({ values: { front_app: 'bad\nname' } })
    assert.equal(getSettings(db).front_app, '', '규칙에 안 맞는 auto 값은 버리고 기본값')
    assert.equal(settingOrigins(db).front_app.source, 'default')
  } finally {
    setAutoValues(null)
    for (const [k, v] of Object.entries(keep)) if (v === undefined) delete process.env[k]; else process.env[k] = v
  }
})

test('출처: 환경변수가 .env 파일에서 왔으면 그 경로를 알려 준다(.env는 읽기만)', () => {
  const conf = mkdtempSync(join(tmpdir(), 'whosup-aconf-'))
  writeFileSync(join(conf, '.env'), '# x\nexport WHOSUP_RENOTIFY_MIN=20\n')
  const before = readFileSync(join(conf, '.env'), 'utf8')
  const keep = { c: process.env.HERDR_PLUGIN_CONFIG_DIR, r: process.env.WHOSUP_RENOTIFY_MIN, s: process.env.WHOSUP_SEEN_SNOOZE_MIN }
  process.env.HERDR_PLUGIN_CONFIG_DIR = conf; process.env.WHOSUP_RENOTIFY_MIN = '20'; process.env.WHOSUP_SEEN_SNOOZE_MIN = '10'
  try {
    const o = settingOrigins(openDb(':memory:'))
    assert.deepEqual(o.renotify_min, { source: 'env', name: 'WHOSUP_RENOTIFY_MIN', file: join(conf, '.env') })
    assert.deepEqual(o.seen_snooze_min, { source: 'env', name: 'WHOSUP_SEEN_SNOOZE_MIN', file: null })
    assert.deepEqual(o.gone_misses, { source: 'default' })
    assert.equal(readFileSync(join(conf, '.env'), 'utf8'), before)
  } finally {
    for (const [k, n] of [['c', 'HERDR_PLUGIN_CONFIG_DIR'], ['r', 'WHOSUP_RENOTIFY_MIN'], ['s', 'WHOSUP_SEEN_SNOOZE_MIN']]) if (keep[k] === undefined) delete process.env[n]; else process.env[n] = keep[k]
  }
})

test('L7 브라우저 기본값: ovis 주소를 내려 주되 클릭은 기본 터미널, 첫 실행 카드 선택이 사람 값으로 저장되고 다시 안 뜬다', () => {
  const db = openDb(':memory:')
  try {
    setAutoValues(evaluate({ platform: 'darwin', env: {}, herdr: { found: true, sessions: [{ name: 'side', status: 'running', socket: '/h/sessions/side/herdr.sock' }] }, ovis: [{ port: 7318, signed: true, socket: '/h/sessions/side/herdr.sock' }] }))
    const d = clientDefaults(db)
    assert.equal(d['whosup-open-url:side'], ovisUrl(7318))
    assert.equal(d['whosup-open-url-on'], 'off', 'ovis가 있어도 기본은 터미널')
    const v = autoconfView(db)
    assert.deepEqual(v.first_run.show, true)
    assert.equal(v.first_run.ask_click, true)
    assert.deepEqual(v.summary.ovis.map((o) => [o.port, o.session, o.confirmed]), [[7318, 'side', true]])
    assert.equal(firstRunDone(db, 'nope').ok, false)
    assert.equal(autoconfView(db).first_run.show, true, '틀린 선택은 저장하지 않는다')
    const r = firstRunDone(db, 'both')
    assert.equal(r.ok, true)
    assert.equal(r.settings.click_target, 'both')
    assert.equal(settingOrigins(db).click_target.source, 'panel')
    assert.equal(r.client_defaults['whosup-open-url-on'], 'on')
    assert.equal(autoconfView(db).first_run.show, false)
    setAutoValues(evaluate({ platform: 'darwin', env: {} }))
    assert.equal(autoconfView(db).first_run.ask_click, false, 'ovis 없으면 묻지 않는다')
  } finally { setAutoValues(null) }
})

test('서버 API: GET /api/autoconf, POST /api/first-run, GET /api/settings의 origins', async () => {
  const db = openDb(':memory:')
  setAutoValues(evaluate({ platform: 'darwin', env: {}, agents: { claude: null, codex: '/b/codex' } }))
  const server = createBoardServer(db)
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  const base = `http://127.0.0.1:${server.address().port}`
  try {
    const a = await (await fetch(`${base}/api/autoconf`)).json()
    for (const k of ['at', 'platform', 'summary', 'lanes', 'raise_warning', 'client_defaults', 'first_run']) assert.ok(k in a, k)
    assert.equal(a.first_run.show, true)
    const post = await fetch(`${base}/api/first-run`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({}) })
    assert.equal(post.status, 200)
    assert.equal((await (await fetch(`${base}/api/autoconf`)).json()).first_run.show, false)
    const bad = await fetch(`${base}/api/first-run`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ choice: 'x' }) })
    assert.equal(bad.status, 400)
  } finally { server.close(); setAutoValues(null) }
})

test('auto.json: 원자적으로 쓰고 읽는다', () => {
  const dir = mkdtempSync(join(tmpdir(), 'whosup-auto-'))
  const r = evaluate({ platform: 'linux', env: local.linux })
  writeAuto(dir, r)
  assert.deepEqual(readAuto(dir).values, r.values)
  assert.deepEqual(readdirSync(dir), ['auto.json'], '임시 파일이 남지 않는다')
  assert.equal(readAuto(mkdtempSync(join(tmpdir(), 'whosup-auto-'))), null)
})

const isolatedEnv = (state, conf) => ({ ...process.env, WHOSUP_STATE_DIR: state, HERDR_PLUGIN_STATE_DIR: state, HERDR_PLUGIN_CONFIG_DIR: conf, HERDR_BIN: FAKE_HERDR, HERDR_BIN_PATH: FAKE_HERDR, PORT: '4850' })

test('scripts/autoconf.mjs: 임시 상태 폴더에 auto.json을 만들고 설정 폴더에 .env를 만들지 않는다(--json·--value·--read)', () => {
  const state = mkdtempSync(join(tmpdir(), 'whosup-astate-'))
  const conf = mkdtempSync(join(tmpdir(), 'whosup-aconf-'))
  const env = isolatedEnv(state, conf)
  const j = spawnSync(process.execPath, [join(ROOT, 'scripts/autoconf.mjs'), '--json'], { env, encoding: 'utf8', timeout: 60000 })
  assert.equal(j.status, 0, j.stderr)
  const out = JSON.parse(j.stdout)
  assert.equal(out.values.os, process.platform)
  assert.ok(existsSync(join(state, 'auto.json')))
  assert.deepEqual(readdirSync(conf), [], '.env를 만들지 않는다')
  const v = spawnSync(process.execPath, [join(ROOT, 'scripts/autoconf.mjs'), '--value', 'os'], { env, encoding: 'utf8', timeout: 60000 })
  assert.equal(v.stdout.trim(), process.platform)
  const rd = spawnSync(process.execPath, [join(ROOT, 'scripts/autoconf.mjs'), '--read', 'nothing_here'], { env, encoding: 'utf8', timeout: 60000 })
  assert.equal(rd.stdout, '\n')
  const t = spawnSync(process.execPath, [join(ROOT, 'scripts/autoconf.mjs')], { env, encoding: 'utf8', timeout: 60000 })
  for (let n = 1; n <= 10; n++) assert.match(t.stdout, new RegExp(`^L${n} `, 'm'), `표에 L${n}`)
  assert.deepEqual(readdirSync(conf), [])
})

test('설치·시작 연결: launch.mjs preflight(윈도우 build 훅)와 preflight.sh(sh build 훅)가 auto.json을 쓰고 .env는 0건', () => {
  const state = mkdtempSync(join(tmpdir(), 'whosup-astate-'))
  const conf = mkdtempSync(join(tmpdir(), 'whosup-aconf-'))
  const env = isolatedEnv(state, conf)
  delete env.WHOSUP_STATE_DIR   // herdr가 부를 때처럼 HERDR_PLUGIN_STATE_DIR만
  const r = spawnSync(process.execPath, [join(ROOT, 'scripts/launch.mjs'), 'preflight'], { env, encoding: 'utf8', timeout: 60000 })
  assert.equal(r.status, 0, r.stdout + r.stderr)
  assert.match(r.stdout, /whosup autoconf/)
  assert.ok(readAuto(state))
  assert.deepEqual(readdirSync(conf), [])
  if (process.platform === 'win32') return
  const state2 = mkdtempSync(join(tmpdir(), 'whosup-astate-'))
  const env2 = { ...isolatedEnv(state2, conf) }
  delete env2.WHOSUP_STATE_DIR
  const s = spawnSync('sh', [join(ROOT, 'scripts/preflight.sh')], { cwd: ROOT, env: env2, encoding: 'utf8', timeout: 60000 })
  assert.equal(s.status, 0, s.stdout + s.stderr)
  assert.ok(readAuto(state2))
  assert.deepEqual(readdirSync(conf), [])
})

// M5-T4 codex 리뷰: ovis 확인은 리디렉트를 따라가지 않고, 2xx 답의 본문만 서명으로 본다.
test('L7 ovis 확인: 리디렉트·오류 답은 서명이 아니다', async () => {
  const { createServer } = await import('node:http')
  const signed = JSON.stringify({ bridge_protocol: 1, web_ui: { boot_id: 'b' } })
  let hitTarget = 0
  const target = createServer((req, res) => { hitTarget++; res.writeHead(200, { 'content-type': 'application/json' }); res.end(signed) })
  await new Promise((r) => target.listen(0, '127.0.0.1', r))
  const mk = (handler) => new Promise((r) => { const s = createServer(handler); s.listen(0, '127.0.0.1', () => r(s)) })
  const redirect = await mk((req, res) => { res.writeHead(302, { location: `http://127.0.0.1:${target.address().port}/api/health?scope=bridge` }); res.end() })
  const err500 = await mk((req, res) => { res.writeHead(500, { 'content-type': 'application/json' }); res.end(signed) })
  try {
    assert.equal((await probeOvis(target.address().port, 2000))?.signed, true)
    const before = hitTarget
    const r = await probeOvis(redirect.address().port, 2000)
    assert.notEqual(r?.signed, true)
    assert.equal(hitTarget, before, '리디렉트 대상에 요청이 가지 않는다')
    assert.equal((await probeOvis(err500.address().port, 2000))?.signed, false)
  } finally { for (const s of [target, redirect, err500]) s.close() }
})

// ── 2회차 회차 2: 직접 실행(bin/whosup.mjs) 때 오래된 auto.json을 믿지 않는다 ──
test('autoIsFresh: 같은 판본·플랫폼이고 2분 안에 쓴 것만 믿는다(오래됨·다른 플랫폼·다른 판본·시각 없음·실패 결과는 낡음)', async () => {
  const { autoIsFresh, AUTO_FRESH_MS, AUTO_VERSION } = await import('../src/autoconf.mjs')
  const now = Date.parse('2026-11-11T12:00:00Z')
  const r = (over = {}) => ({ version: AUTO_VERSION, at: new Date(now - 10_000).toISOString(), platform: 'darwin', values: {}, ...over })
  const o = { now, platform: 'darwin' }
  assert.equal(autoIsFresh(r(), o), true)
  assert.equal(autoIsFresh(r({ at: new Date(now - AUTO_FRESH_MS - 1).toISOString() }), o), false, '2분 넘음')
  assert.equal(autoIsFresh(r({ at: new Date(now - 3 * 86400_000).toISOString() }), o), false, '며칠 전')
  assert.equal(autoIsFresh(r({ platform: 'win32' }), o), false, '다른 플랫폼')
  assert.equal(autoIsFresh(r({ version: AUTO_VERSION + 1 }), o), false, '다른 판본')
  assert.equal(autoIsFresh(r({ at: null }), o), false, '시각 없음')
  assert.equal(autoIsFresh(r({ at: new Date(now + 60_000).toISOString() }), o), false, '앞날 시각')
  assert.equal(autoIsFresh(r({ error: 'boom' }), o), false, '감지 실패 결과')
  assert.equal(autoIsFresh(null, o), false)
})

test('refreshAuto: 다시 감지해 auto.json을 새로 쓰고, 감지가 실패하면 옛 값을 남기지 않는다(값 없음 + error)', async () => {
  const { refreshAuto } = await import('../src/autoconf.mjs')
  const dir = mkdtempSync(join(tmpdir(), 'whosup-refresh-'))
  writeAuto(dir, { version: 1, at: '2026-01-01T00:00:00.000Z', platform: 'darwin', values: { front_app: 'Ghostty', stale_sentinel: 1 }, reasons: {} })
  const ok = await refreshAuto(dir, { detectFn: async () => ({ platform: 'win32', env: local.win32, tools: { wt: 'C:\\wt.exe' } }) })
  assert.equal(ok.values.front_app, 'Windows Terminal')
  assert.equal(readAuto(dir).values.stale_sentinel, undefined)
  assert.equal(readAuto(dir).platform, 'win32')
  const bad = await refreshAuto(dir, { detectFn: async () => { throw new Error('detect broke') } })
  assert.deepEqual(bad.values, {})
  assert.match(bad.error, /detect broke/)
  assert.deepEqual(readAuto(dir).values, {}, '실패해도 이전 값(Windows Terminal)을 유지하지 않는다')
  assert.match(readAuto(dir).error, /detect broke/)
})

test('auto.json 이름 바꾸기: 윈도우가 잠깐 거절하면(EPERM·EACCES·EBUSY) 다시 하고, 다른 오류나 끝내 거절은 그대로 던진다', async () => {
  const { renameRetry } = await import('../src/autoconf.mjs')
  const failing = (codes) => { const calls = []; return { calls, rename: (a, b) => { calls.push([a, b]); const c = codes.shift(); if (c) throw Object.assign(new Error(c), { code: c }) } } }
  const f = failing(['EPERM', 'EBUSY', 'EACCES'])
  renameRetry('x.tmp', 'x', { rename: f.rename, waitMs: 1 })
  assert.equal(f.calls.length, 4)
  const g = failing(['ENOENT'])
  assert.throws(() => renameRetry('x.tmp', 'x', { rename: g.rename, waitMs: 1 }), { code: 'ENOENT' })
  assert.equal(g.calls.length, 1)
  const h = failing(Array(10).fill('EPERM'))
  assert.throws(() => renameRetry('x.tmp', 'x', { rename: h.rename, tries: 3, waitMs: 1 }), { code: 'EPERM' })
  assert.equal(h.calls.length, 3)
})

// 실제 bin/whosup.mjs를 임시 상태 폴더·시험 포트(4800~4899)로 띄운다.
function runBin(env) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [join(ROOT, 'bin', 'whosup.mjs')], { env: { ...process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] })
    let out = ''
    const done = (code) => resolve({ child, code, get out() { return out } })
    child.stdout.on('data', (d) => { out += d; if (/listening/.test(out)) done(null) })
    child.stderr.on('data', (d) => { out += d })
    child.on('exit', done)
  })
}
const waitFor = async (fn, ms = 20000) => { const end = Date.now() + ms; while (Date.now() < end) { const v = fn(); if (v) return v; await new Promise((r) => setTimeout(r, 100)) } return fn() }
const binEnv = (dir) => ({ WHOSUP_STATE_DIR: dir, HERDR_BIN: FAKE_HERDR, HERDR_BIN_PATH: FAKE_HERDR, CLAUDE_PROJECTS_DIR: join(dir, 'projects'), PORT: String(4800 + Math.floor(Math.random() * 100)), WHOSUP_INTERVAL: '60', WHOSUP_OPEN_BROWSER: '0', OPEN_BROWSER: '0', FRONT_APP: '' })

test('bin/whosup.mjs 직접 실행: 오래된 auto.json(며칠 전·다른 플랫폼)은 쓰지 않고 시작할 때 다시 감지해 새로 쓴다', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'whosup-stale-'))
  writeAuto(dir, { version: 1, at: '2026-01-01T00:00:00.000Z', platform: process.platform === 'win32' ? 'darwin' : 'win32', values: { stale_sentinel: 'old' }, reasons: {} })
  const r = await runBin(binEnv(dir))
  try {
    assert.equal(r.code, null, r.out)
    const a = await waitFor(() => { const x = readAuto(dir); return x && !x.values.stale_sentinel && x })
    assert.ok(a, `auto.json이 새로 쓰이지 않았다:\n${r.out}`)
    assert.equal(a.platform, process.platform)
    assert.ok(Date.now() - Date.parse(a.at) < 60_000, a.at)
    await waitFor(() => /autoconf/.test(r.out))
    assert.match(r.out, /autoconf: \d+ detected values \(auto\.json was stale\)/)
  } finally { r.child.kill('SIGTERM') }
})

test('bin/whosup.mjs: 시작 스크립트가 방금 쓴 auto.json(2분 안·같은 플랫폼)은 다시 감지하지 않고 그대로 쓴다', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'whosup-fresh-'))
  const at = new Date().toISOString()
  writeAuto(dir, { version: 1, at, platform: process.platform, values: { fresh_sentinel: 'kept' }, reasons: {} })
  const r = await runBin(binEnv(dir))
  try {
    assert.equal(r.code, null, r.out)
    await new Promise((res) => setTimeout(res, 1500))
    const a = readAuto(dir)
    assert.equal(a.at, at, '파일을 다시 쓰지 않았다')
    assert.equal(a.values.fresh_sentinel, 'kept')
    assert.doesNotMatch(r.out, /autoconf/)
  } finally { r.child.kill('SIGTERM') }
})
