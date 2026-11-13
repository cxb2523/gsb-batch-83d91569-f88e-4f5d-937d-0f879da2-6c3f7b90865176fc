// 윈도우 분기를 맥·리눅스에서도 시험한다: process.platform 대신 platform.mjs의 _setPlatform('win32')로 바꿔 넣는다.
// 실제 PowerShell·herdr·창은 띄우지 않는다(가짜 도우미·가짜 창 조작만). 임시 폴더는 os.tmpdir() 아래.
import { test, afterEach } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const dir = mkdtempSync(join(tmpdir(), 'whosup-win-'))
process.env.WHOSUP_STATE_DIR = dir
process.env.XDG_STATE_HOME = join(dir, 'xdg-state')
delete process.env.HC_SOCKET
delete process.env.HC_SESSION
// 실제 herdr·Herdr 앱에 닿지 않게: 없는 실행 파일을 가리킨다.
process.env.HERDR_APP_BIN = join(dir, 'no-herdr-app')
process.env.HERDR_BIN = join(dir, 'no-herdr')
delete process.env.HERDR_BIN_PATH

const { _setPlatform, pipeName, connectTarget, commandFor, psQuote } = await import('../src/platform.mjs')
const herdr = await import('../src/runtime/herdr.mjs')
const core = await import('../src/runtime/core.mjs')
const { getSettings, setSettings } = await import('../src/settings.mjs')
const { openDb } = await import('../src/db.mjs')
const { cdLine } = await import('../scripts/desks.mjs')
const doctor = await import('../scripts/doctor.mjs')

afterEach(() => { _setPlatform(null); herdr.setFrontApp(''); delete process.env.FRONT_APP })

// ── A2: e82b667 FRONT_APP 회귀 ──────────────────────────────────────
test('윈도우: FRONT_APP에 경로·괄호가 든 값도 그대로 켜진다(9b4bc0f 대비 회귀 고정)', () => {
  _setPlatform('win32')
  for (const v of ['on', 'wt.exe', 'C:\\Program Files\\PowerShell\\7\\pwsh.exe', 'Windows Terminal (Preview)', 'C:\\Users\\me\\AppData\\Local\\Microsoft\\WindowsApps\\wt.exe']) {
    process.env.FRONT_APP = v
    assert.equal(getSettings(null).front_app, v, v)
    assert.notEqual(herdr.winTerminal(getSettings(null).front_app), null, v)
  }
})
test('macOS·리눅스: FRONT_APP 앱 이름 검사는 그대로(명령줄·AppleScript에 들어가므로)', () => {
  for (const pl of ['darwin', 'linux']) {
    _setPlatform(pl)
    process.env.FRONT_APP = 'Windows Terminal (Preview)'
    assert.equal(getSettings(null).front_app, '')
    process.env.FRONT_APP = 'Ghostty'
    assert.equal(getSettings(null).front_app, 'Ghostty')
  }
})
test('윈도우: 설정 패널에서 경로 값을 저장할 수 있고, 줄바꿈은 여전히 거절한다', () => {
  _setPlatform('win32')
  const db = openDb(':memory:')
  assert.equal(setSettings(db, { front_app: 'C:\\Tools\\wt.exe' }).ok, true)
  assert.equal(getSettings(db).front_app, 'C:\\Tools\\wt.exe')
  assert.equal(setSettings(db, { front_app: 'a\nb' }).ok, false)
  _setPlatform('darwin')
  assert.equal(setSettings(db, { front_app: 'C:\\Tools\\wt.exe' }).ok, false)
})

// ── 창 올리기 기본값·터미널 감지 ─────────────────────────────────────
test('윈도우 창 올리기: 기본은 켬(PowerShell), off로 끄고, Windows Terminal·pwsh를 알아본다', () => {
  assert.equal(herdr.winTerminal(''), 'powershell')
  assert.equal(herdr.winTerminal(undefined), 'powershell')
  for (const v of ['off', 'OFF', 'none', '0', 'false', '끔']) assert.equal(herdr.winTerminal(v), null, v)
  for (const v of ['Windows Terminal', 'Windows Terminal (Preview)', 'wt', 'wt.exe', 'C:\\x\\wt.exe']) assert.equal(herdr.winTerminal(v), 'wt', v)
  assert.equal(herdr.winTerminal('C:\\Program Files\\PowerShell\\7\\pwsh.exe'), 'pwsh')
  assert.equal(herdr.winTerminal('on'), 'powershell')
})
// 2회차 회차 2: 자동 값이 Windows Terminal이어도 사람이 PowerShell을 고를 수 있어야 한다(전에는 PowerShell 프리셋 값이 ''라 자동으로 되돌아갔다).
test('윈도우 설정: 자동 Windows Terminal 위에 PowerShell을 고르면 그 값이 이기고, 자동을 고르면 자동으로 돌아간다', async () => {
  _setPlatform('win32')
  const { frontAppChoice, setAutoValues } = await import('../src/settings.mjs')
  const db = openDb(':memory:')
  setAutoValues({ values: { front_app: 'Windows Terminal' }, reasons: { front_app: 'L4: wt.exe found' } })
  try {
    const term = () => { const [human, auto] = frontAppChoice(db); return herdr.winTerminal(human || auto) }   // herdr.mjs effectiveApp과 같은 순서
    assert.equal(term(), 'wt', '아무것도 고르지 않으면 자동(Windows Terminal)')
    assert.equal(setSettings(db, { front_app: 'PowerShell' }).ok, true)
    assert.deepEqual(frontAppChoice(db), ['PowerShell', 'Windows Terminal'])
    assert.equal(term(), 'powershell', 'PowerShell을 고르면 자동 Windows Terminal을 이긴다')
    for (const v of ['PowerShell', 'powershell', 'powershell.exe']) assert.equal(herdr.winTerminal(v), 'powershell', v)
    assert.equal(setSettings(db, { front_app: null }).ok, true)   // 화면의 '자동' = 빈 값 저장 = 사람 값 지우기
    assert.deepEqual(frontAppChoice(db), ['', 'Windows Terminal'])
    assert.equal(term(), 'wt')
    const w = herdr.WIN_CHOICES
    assert.deepEqual(w.find(([, v]) => v === 'PowerShell'), ['PowerShell', 'PowerShell'], 'PowerShell 프리셋은 빈 값이 아니다')
    assert.deepEqual(w.filter(([, v]) => v === ''), [['auto', '']], "빈 값은 '자동' 하나뿐")
  } finally { setAutoValues(null) }
})
test('설정 패널 화면: 윈도우도 자동 값은 \'자동\' 단추로 보이고(빈 값), 자동 선택지 이름은 T.appAuto', async () => {
  const { readFileSync } = await import('node:fs')
  const html = readFileSync(new URL('../src/board/index.html', import.meta.url), 'utf8')
  assert.match(html, /const frontVal = data\.origins\?\.front_app\?\.source === 'auto' \? '' :/)
  assert.match(html, /a === 'off' \? T\.appOff : a === '' \? T\.appAuto : n/)
})
test('detectTerminal: win32에서 supported:true와 윈도우 선택지, 리눅스는 그대로 supported:false', async () => {
  _setPlatform('win32')
  const d = await herdr.detectTerminal()
  assert.equal(d.supported, true)
  assert.equal(d.platform, 'win32')
  assert.deepEqual(d.choices.map(([, v]) => v), ['', 'PowerShell', 'Windows Terminal', 'off'])
  _setPlatform('linux')
  assert.equal((await herdr.detectTerminal()).supported, false)
})

// ── pipe 이름 ────────────────────────────────────────────────────────
test('named pipe 이름: \\\\.\\pipe\\<소켓 경로>, 이미 pipe면 그대로, 윈도우에서만 pipe로 접속', () => {
  const sock = 'C:\\Users\\Hong Gildong\\.config\\herdr\\sessions\\main\\herdr.sock'
  assert.equal(pipeName(sock), `\\\\.\\pipe\\${sock}`)
  assert.equal(pipeName(pipeName(sock)), pipeName(sock))
  _setPlatform('win32'); assert.equal(connectTarget(sock), pipeName(sock))
  _setPlatform('darwin'); assert.equal(connectTarget('/work/x.sock'), '/work/x.sock')
})
test('herdr-core: 윈도우는 LOCALAPPDATA도 상태 폴더 후보로 보고, 거기 적힌 소켓을 pipe로 연다(가정)', async () => {
  const saved = { xdg: process.env.XDG_STATE_HOME, lad: process.env.LOCALAPPDATA }
  try {
    delete process.env.XDG_STATE_HOME
    process.env.LOCALAPPDATA = join(dir, 'Local App Data')
    const lock = join(process.env.LOCALAPPDATA, 'herdr-core', 'default')
    mkdirSync(lock, { recursive: true })
    writeFileSync(join(lock, 'core.lock'), 'C:\\Users\\Hong Gildong\\AppData\\Local\\herdr-core\\default\\default.sock\n')
    _setPlatform('win32')
    assert.equal(core.stateDirs()[0], process.env.LOCALAPPDATA)
    assert.equal(core.socketPath(), 'C:\\Users\\Hong Gildong\\AppData\\Local\\herdr-core\\default\\default.sock')
    _setPlatform('darwin')
    assert.ok(!core.stateDirs().includes(process.env.LOCALAPPDATA))
  } finally { process.env.XDG_STATE_HOME = saved.xdg; if (saved.lad === undefined) delete process.env.LOCALAPPDATA; else process.env.LOCALAPPDATA = saved.lad }
})

// ── 세션 목록 파싱 ───────────────────────────────────────────────────
test('세션 목록 표: 홈에 공백이 있어도 폴더·소켓 칸이 밀리지 않는다', () => {
  const text = [
    'name                 status   directory                                        socket',
    'main                 running  C:\\Users\\Hong Gildong\\.config\\herdr\\sessions\\main  C:\\Users\\Hong Gildong\\.config\\herdr\\sessions\\main\\herdr.sock',
    'default              stopped  /Users/me/.config/herdr                         /Users/me/.config/herdr/herdr.sock',
    'whosuptest-x         running  /tmp/a                                           /tmp/a/herdr.sock',
    'odd                  running  /a b/c                                           /elsewhere/s.sock',
    '',
  ].join('\r\n')
  assert.deepEqual(herdr.parseSessionTable(text), [
    { name: 'main', status: 'running', dir: 'C:\\Users\\Hong Gildong\\.config\\herdr\\sessions\\main', socket: 'C:\\Users\\Hong Gildong\\.config\\herdr\\sessions\\main\\herdr.sock' },
    { name: 'default', status: 'stopped', dir: '/Users/me/.config/herdr', socket: '/Users/me/.config/herdr/herdr.sock' },
    // 소켓이 폴더 밖이면 끝 열부터 자른다
    { name: 'odd', status: 'running', dir: '/a b/c', socket: '/elsewhere/s.sock' },
  ])
})
test('세션 목록 --json: herdr 0.9.3 모양을 읽고 시험 세션은 뺀다', () => {
  const rows = herdr.parseSessionJson(JSON.stringify({ sessions: [
    { default: true, name: 'default', running: false, session_dir: 'C:\\Users\\Hong Gildong\\.config\\herdr', socket_path: 'C:\\Users\\Hong Gildong\\.config\\herdr\\herdr.sock' },
    { name: 'main', running: true, session_dir: '/s/main', socket_path: '/s/main/herdr.sock' },
    { name: 'whosuptest-1', running: true, session_dir: '/t', socket_path: '/t/s' },
  ] }))
  assert.deepEqual(rows, [
    { name: 'default', status: 'stopped', dir: 'C:\\Users\\Hong Gildong\\.config\\herdr', socket: 'C:\\Users\\Hong Gildong\\.config\\herdr\\herdr.sock' },
    { name: 'main', status: 'running', dir: '/s/main', socket: '/s/main/herdr.sock' },
  ])
  assert.throws(() => herdr.parseSessionJson('{"result":{}}'))
})

// ── PowerShell 인자 이스케이프 ───────────────────────────────────────
test('PowerShell 명령: 작은따옴표가 든 경로·값이 깨지지 않는다(REPORT 18번)', () => {
  assert.equal(psQuote("it's"), "'it''s'")
  assert.equal(herdr.winAttachCommand("C:\\Users\\O'Brien\\herdr.exe", 'main'), "& 'C:\\Users\\O''Brien\\herdr.exe' '--session' 'main'")
  assert.equal(herdr.winAttachCommand('C:\\herdr.exe', 'default'), "& 'C:\\herdr.exe'")
  // 세션 이름에 PowerShell 구분자가 들어도 인자 하나로 남는다(M5-T4 codex 리뷰)
  assert.equal(herdr.winAttachCommand('C:\\herdr.exe', "x; Start-Process calc"), "& 'C:\\herdr.exe' '--session' 'x; Start-Process calc'")
  assert.equal(herdr.winRunCommand(['C:\\bin\\hc.exe', 'attach', 't4'], { HC_SESSION: 'default', HC_SOCKET: "C:\\a b\\it's.sock" }),
    "$env:HC_SESSION='default'; $env:HC_SOCKET='C:\\a b\\it''s.sock'; & 'C:\\bin\\hc.exe' 'attach' 't4'")
  // Windows Terminal은 ; 를 탭 구분으로 읽는다 → \; 로 넘긴다
  assert.deepEqual(herdr.winOpener('wt', "$env:A='1'; & 'hc'"), { file: 'wt.exe', args: ['powershell.exe', '-NoProfile', '-Command', "$env:A='1'\\; & 'hc'"] })
  assert.deepEqual(herdr.winOpener('pwsh', 'x'), { file: 'pwsh.exe', args: ['-NoProfile', '-Command', 'x'] })
  assert.equal(cdLine("C:\\Users\\O'Brien\\proj", true), "Set-Location -LiteralPath 'C:\\Users\\O''Brien\\proj'; Clear-Host")
  assert.equal(cdLine('/a b', false), 'cd "/a b"; clear')
})

// ── 윈도우 도우미: 보내는 줄과 20초 새 창 중복 방지 ───────────────────
function fakeHelper(reply = 'opened') {
  const lines = []
  return { lines, start() {}, stop() {}, send(line) { lines.push(line); return Promise.resolve(typeof reply === 'function' ? reply(line) : reply) } }
}
test('윈도우 칸 클릭: 도우미에 세션·터미널·새 창 명령을 보내고, 20초 안의 두 번째 클릭은 새 창을 열지 말라고 보낸다', async () => {
  _setPlatform('win32')
  process.env.HERDR_BIN_PATH = "C:\\it's\\herdr.exe"
  try {
    const h = fakeHelper('opened'); herdr._setWinHelper(h)
    herdr.setFrontApp('')
    assert.equal(await herdr.activateTerminal('w20a', 0), 'raised')
    assert.equal(await herdr.activateTerminal('w20a', 33), 'raised')
    await new Promise((r) => setImmediate(r))
    assert.deepEqual(h.lines, ["w20a|0|0|powershell|& 'C:\\it''s\\herdr.exe' '--session' 'w20a'", "w20a|33|1|powershell|& 'C:\\it''s\\herdr.exe' '--session' 'w20a'"])
    // 터미널을 바꾸면 따로 센다
    herdr.setFrontApp('Windows Terminal')
    await herdr.activateTerminal('w20a', 0)
    assert.match(h.lines.at(-1), /^w20a\|0\|0\|wt\|/)
  } finally { delete process.env.HERDR_BIN_PATH; herdr._setWinHelper(null) }
})
test('윈도우 칸 클릭: 이미 떠 있던 창을 올렸다는 답이면 표시를 지워 다음 클릭이 새 창을 열 수 있다', async () => {
  _setPlatform('win32')
  const h = fakeHelper('raised:console:42'); herdr._setWinHelper(h)
  try {
    herdr.setFrontApp('')
    await herdr.activateTerminal('w20b', 0)
    await new Promise((r) => setImmediate(r))
    await herdr.activateTerminal('w20b', 0)
    assert.deepEqual(h.lines.map((l) => l.split('|')[2]), ['0', '0'])
  } finally { herdr._setWinHelper(null) }
})
test('윈도우 칸 클릭: herdr 세션 이름 규칙에 맞지 않는 이름은 도우미에 보내지 않는다(M5-T4 codex 리뷰)', async () => {
  _setPlatform('win32')
  const h = fakeHelper(); herdr._setWinHelper(h)
  try {
    herdr.setFrontApp('')
    assert.equal(await herdr.activateTerminal('x; Start-Process calc', 0), 'off')
    assert.equal(await herdr.activateTerminal('a|b', 0), 'off')
    assert.deepEqual(h.lines, [])
  } finally { herdr._setWinHelper(null) }
})
test('윈도우 창 올리기 끔(off): 도우미에 아무것도 보내지 않는다', async () => {
  _setPlatform('win32')
  const h = fakeHelper(); herdr._setWinHelper(h)
  try {
    herdr.setFrontApp('off')
    assert.equal(await herdr.activateTerminal('w20c', 0), 'off')
    assert.equal(await herdr.raiseApp('Herdr'), 'off')
    assert.equal(await herdr.openWindowRunning(['hc', 'attach', 't1'], 'core-t1', { HC_SESSION: 'default' }), 'off')
    assert.deepEqual(h.lines, [])
  } finally { herdr._setWinHelper(null) }
})
test('윈도우 Herdr 앱 올리기: 도우미에 앱 이름만(글자 거름) 보낸다', async () => {
  _setPlatform('win32')
  const h = fakeHelper('raised:app:7'); herdr._setWinHelper(h)
  try {
    herdr.setFrontApp('')
    assert.equal(await herdr.raiseApp('Her"dr;', 33), 'raised')
    assert.deepEqual(h.lines, ['!app|Herdr|33'])
  } finally { herdr._setWinHelper(null) }
})

// ── herdr-core 새 창: 윈도우는 /usr/bin/env 대신 환경변수를 따로 넘긴다 ──
test('herdr-core 카드(앱 창 없음): 윈도우는 [hc, attach, 터미널]과 환경변수 묶음으로 새 창을 연다', async () => {
  const saved = process.env.HC_SOCKET
  const savedRun = process.env.XDG_RUNTIME_DIR
  process.env.HC_SOCKET = 'C:\\Users\\Hong Gildong\\core.sock'
  // 리눅스 CI·데스크톱에 흔한 값. 윈도우 새 창에는 넘기지 않는다(POSIX 로그인 세션 폴더), 맥·리눅스 새 창에는 넘긴다.
  process.env.XDG_RUNTIME_DIR = '/run/user/1001'
  const seen = []
  core._setWindowOps({ openWindowRunning: async (...a) => { seen.push(a); return 'opened' } })
  try {
    _setPlatform('win32')
    const r = await core.__showForTest('t9')
    assert.equal(r, 'opened')
    assert.deepEqual(seen[0], [[process.env.HC_BIN || 'hc', 'attach', 't9'], 'core-t9', { HC_SESSION: 'default', HC_SOCKET: 'C:\\Users\\Hong Gildong\\core.sock', XDG_STATE_HOME: process.env.XDG_STATE_HOME }])
    _setPlatform('darwin')
    await core.__showForTest('t9')
    assert.equal(seen[1][0][0], '/usr/bin/env')
    assert.ok(seen[1][0].includes('XDG_RUNTIME_DIR=/run/user/1001'), seen[1][0].join(' '))
    assert.equal(seen[1].length, 2)
  } finally {
    if (saved === undefined) delete process.env.HC_SOCKET; else process.env.HC_SOCKET = saved
    if (savedRun === undefined) delete process.env.XDG_RUNTIME_DIR; else process.env.XDG_RUNTIME_DIR = savedRun
    core._setWindowOps({ openWindowRunning: herdr.openWindowRunning })
  }
})

// ── node 스크립트 실행 ───────────────────────────────────────────────
test('실행 파일이 .mjs면 지금 도는 node로 돌린다(윈도우는 shebang을 읽지 않는다)', () => {
  assert.deepEqual(commandFor('C:\\x\\fake-herdr.mjs', ['--version']), [process.execPath, ['C:\\x\\fake-herdr.mjs', '--version']])
  assert.deepEqual(commandFor('herdr', ['--version']), ['herdr', ['--version']])
})

// ── doctor: 바탕화면 세션·PATH 찾기 ───────────────────────────────────
test('doctor: 윈도우 바탕화면 세션 판정(SSH·세션 0이면 경고)', () => {
  assert.equal(doctor.desktopSession({ SESSIONNAME: 'Console' }, true).ok, true)
  assert.equal(doctor.desktopSession({ SESSIONNAME: 'Console', SSH_CONNECTION: '1 2 3 4' }, true).ok, false)
  assert.equal(doctor.desktopSession({}, true, null).ok, false)
  assert.equal(doctor.desktopSession({}, true, 3).ok, true, '로그온 예약 작업: SESSIONNAME 없음 + 세션 3')
  assert.equal(doctor.desktopSession({}, true, 0).ok, false)
  assert.equal(doctor.desktopSession({ SESSIONNAME: 'Services' }, true, 0).ok, false, "SESSIONNAME=Services는 세션 0(M5-T4 codex 리뷰)")
  assert.equal(doctor.sessionFromTasklist('"herdr.exe","14608","Console","3","26,384 K"\r\n'), 3)
  assert.equal(doctor.sessionFromTasklist('"powershell.exe","26132","Services","0","67,164 K"'), 0)
  assert.equal(doctor.sessionFromTasklist('INFO: No tasks are running which match the specified criteria.'), null)
})
test('doctor: PATH에서 PATHEXT를 붙여 실행 파일을 찾는다(실행하지 않음)', () => {
  const bin = join(dir, 'Program Files', 'bin')
  mkdirSync(bin, { recursive: true })
  writeFileSync(join(bin, 'wt.EXE'), '')
  assert.equal(doctor.which('wt', { PATH: `C:\\nowhere;${bin}`, PATHEXT: '.COM;.EXE' }, true), join(bin, 'wt.EXE'))
  assert.equal(doctor.which('nope', { PATH: bin }, false), null)
})
test('doctor: 윈도우 앱 실행 별칭(stat이 실패하는 링크, WindowsApps\\wt.exe)도 찾는다', () => {
  const apps = join(dir, 'WindowsApps')
  mkdirSync(apps, { recursive: true })
  symlinkSync(join(apps, 'missing-target'), join(apps, 'wt.exe'))   // existsSync는 false, lstat은 된다 — 별칭과 같은 모양
  assert.equal(doctor.which('wt', { PATH: apps, PATHEXT: '.exe' }, true), join(apps, 'wt.exe'))
  assert.equal(doctor.which('wt', { PATH: apps }, false), null)   // 윈도우가 아니면 끊긴 링크는 없는 것
})

// ── 설정 패널: 윈도우 서버면 터미널 칸이 보이고 OS 알림 칸은 숨는다 ─────
test('윈도우 서버의 /api/settings: 터미널 칸을 그릴 감지 결과(supported·선택지)를 준다', async () => {
  _setPlatform('win32')
  const { startBoard } = await import('../src/board/server.mjs')
  const db = openDb(':memory:')
  const server = await startBoard(db, { port: 48100 + Math.floor(Math.random() * 90), heartbeatPath: join(dir, 'hb') })
  try {
    const r = await (await fetch(`http://127.0.0.1:${server.address().port}/api/settings`)).json()
    assert.equal(r.detected.supported, true)
    assert.equal(r.detected.platform, 'win32')
    assert.deepEqual(r.detected.choices.map(([n]) => n), ['auto', 'PowerShell', 'Windows Terminal', 'off'])
  } finally { await new Promise((res) => server.close(res)); server.closeAllConnections?.() }
})
test('설정 패널 화면: 윈도우 서버면 윈도우 선택지·안내를 쓰고 macOS 알림(os_notify) 칸을 뺀다', async () => {
  const { readFileSync } = await import('node:fs')
  const html = readFileSync(new URL('../src/board/index.html', import.meta.url), 'utf8')
  const I18N = new Function(`${html.match(/const I18N = \{[\s\S]*?\n\}\n/)[0]}; return I18N`)()
  for (const l of ['ko', 'en']) for (const k of ['appHintWin', 'appOff', 'appPhWin']) assert.ok(I18N[l][k], `${l}.${k}`)
  assert.match(html, /const winSrv = data\.detected\?\.platform === 'win32'/)
  assert.match(html, /\$\{data\.detected\?\.supported \? `<div class="setrow cmdrow" id="front-app-row"/)
  assert.match(html, /winSrv \? \(data\.detected\.choices \|\| \[\]\)/)
  assert.match(html, /filter\(\(\[k, r\]\) => !r\.text && !\(winSrv && k === 'os_notify'\)\)/)
})

// 도우미 PowerShell 본문은 JS 템플릿 문자열 안에 있다: 역슬래시가 JS에서 한 번 먹히므로 실제로 PowerShell이 받는 글자를 본다.
test('윈도우 도우미 본문: 줄 형식·새 창 금지·wt의 세미콜론 바꾸기·작은따옴표 겹치기가 PowerShell에 그대로 간다', async () => {
  const { readFileSync } = await import('node:fs')
  const src = readFileSync(new URL('../src/runtime/herdr.mjs', import.meta.url), 'utf8')
  const body = src.match(/const WIN_HELPER_PS = `([\s\S]*?)`\nclass Helper/)[1]
  const ps = new Function(`return \`${body}\``)()
  assert.match(ps, /\$ses, \$split, \$noopen, \$term, \$cmd = \$line\.Split\('\|', 5\)/)
  assert.match(ps, /if \(-not \$done -and \$noopen -eq '1'\) \{ \$res = 'opened:waiting' \}/)
  assert.ok(ps.includes(String.raw`($cmd -replace ';', '\;')`), 'wt.exe에는 ; 대신 \\; 가 가야 한다')
  assert.ok(ps.includes(`($bin -replace "'", "''")`))
  assert.doesNotMatch(ps, /WIN_RAISE_PS|"& '\$bin' \$want"/)
})
