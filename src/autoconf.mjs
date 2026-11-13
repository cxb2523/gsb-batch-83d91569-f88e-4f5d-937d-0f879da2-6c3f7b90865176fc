// 자동 세팅 규칙표(레인 L1~L10): 실행 환경에서 무엇을 확인해 어떤 값을 정하는지 한 곳에 모은다(PRD2/01_PRD.md).
//
// 레인은 순수 함수다 — 입력(facts: 플랫폼·환경변수·파일 존재·프로브 결과)만 보고 [{ lane, key, value, reason }]을 돌려준다.
// value가 undefined면 "자동 값 없음"(그 항목은 기본값으로 떨어진다). 감지하지 못한 것은 추측하지 않는다.
// 실제 환경에서 facts를 모으는 일은 detect() 하나가 한다(scripts/doctor.mjs diagnose·herdr detectTerminal·core를 그대로 쓴다).
//
// 자동 값은 설정의 맨 아래 층이다: 설정 패널(DB) > 환경변수(.env 포함) > 자동 > 기본값(src/settings.mjs).
// 여기서는 .env·DB를 쓰지 않는다. 결과는 상태 폴더의 auto.json에 남는다(scripts/autoconf.mjs).
import { execFile } from 'node:child_process'
import { existsSync, readFileSync, renameSync, writeFileSync, mkdirSync } from 'node:fs'
import { createServer } from 'node:net'
import { homedir, release } from 'node:os'
import { join } from 'node:path'
import { desktopSession, diagnose, which, winSessionNo } from '../scripts/doctor.mjs'
import * as herdr from './runtime/herdr.mjs'
import { platform } from './platform.mjs'

export const AUTO_FILE = 'auto.json'
export const OVIS_PORTS = Array.from({ length: 14 }, (_, i) => 7317 + i)   // 7317~7330
// 맥에서 새 창을 열 줄 아는 앱이 먼저(herdr.mjs openerFor), 그다음 창 올리기만 되는 앱.
export const MAC_TERMINALS = ['Ghostty', 'Terminal', 'iTerm', 'WezTerm', 'kitty']
const NODE_MIN = [22, 13]

const item = (lane, key, value, reason) => ({ lane, key, value, reason })
// 원격이면 그 이유, 데스크톱이면 null. 윈도우 판정(세션 0·SESSIONNAME)은 doctor의 desktopSession을 그대로 쓴다.
// macOS·리눅스는 주입한 platform만 보도록 여기서 본다(desktopSession의 리눅스 판정은 지금 도는 OS를 봐서 주입 시험에 맞지 않는다).
const remoteWhy = (f) => {
  const env = f.env || {}
  if (f.platform === 'win32') { const d = desktopSession(env, true, f.winSession ?? null); return d.ok ? null : d.why }   // winSession: detect()가 읽은 세션 번호
  if (env.SSH_CONNECTION || env.SSH_TTY) return 'ssh'
  if (f.platform === 'linux' && !env.DISPLAY && !env.WAYLAND_DISPLAY) return 'no DISPLAY/WAYLAND_DISPLAY'
  return null
}

// L1 OS: 실행기(sh / node launch.mjs)는 herdr-plugin.toml이 고른다. 여기서는 그 사실과 OS 알림 항목 노출만 정한다.
export function laneOS(f) {
  const p = f.platform
  if (!['darwin', 'linux', 'win32'].includes(p)) return [item('L1', 'os', undefined, `unsupported platform ${p}`)]
  return [
    item('L1', 'os', p, `process.platform=${p}${f.release ? ` release=${f.release}` : ''}`),
    item('L1', 'launcher', p === 'win32' ? 'node' : 'sh', p === 'win32' ? 'herdr-plugin.toml windows entries run node scripts/launch.mjs' : 'herdr-plugin.toml linux·macos entries run sh scripts/plugin.sh'),
    item('L1', 'os_notify_available', p !== 'win32', p === 'win32' ? 'OS alerts are not offered on Windows' : 'OS alerts can be turned on in settings'),
  ]
}

// L2 Node·sqlite: 22.13 미만이거나 node:sqlite가 없으면 설치가 멈춘다(preflight). 규칙표에는 판정만 싣는다.
export function laneNode(f) {
  const v = f.node?.version
  if (!v) return [item('L2', 'node_ok', undefined, 'node version not known')]
  const [maj, min] = String(v).replace(/^v/, '').split('.').map(Number)
  const newEnough = maj > NODE_MIN[0] || (maj === NODE_MIN[0] && min >= NODE_MIN[1])
  if (f.node.sqlite === false) return [item('L2', 'node_ok', false, `node ${v}: node:sqlite missing, need Node 22.13+`)]
  if (!newEnough) return [item('L2', 'node_ok', false, `node ${v} is older than 22.13`)]
  return [item('L2', 'node_ok', true, `node ${v} with node:sqlite`)]
}

// L3 데스크톱 세션: 원격(SSH·윈도우 세션 0·리눅스 화면 없음)이면 브라우저를 열지 않는다. 창 올리기도 끈다(L4 front_app 'off').
export function laneDesktop(f) {
  const why = remoteWhy(f)
  if (why) {
    return [
      item('L3', 'desktop', false, `remote: ${why}`),
      item('L3', 'open_browser', 0, `remote (${why}): no browser to open on this screen`),
    ]
  }
  return [item('L3', 'desktop', true, 'local desktop session'), item('L3', 'open_browser', undefined, 'local: default (open once)')]
}

// L4 터미널 앱(front_app). 맥: 지금 herdr를 보여 주는 앱 > 설치된 앱(Ghostty·Terminal·iTerm·WezTerm·kitty 순).
// 윈도우: wt.exe가 있으면 Windows Terminal, 없으면 기본(PowerShell). 맥·윈도우 모두 원격이면 'off'. 리눅스: 창 올리기 없음.
export function laneTerminal(f) {
  const p = f.platform
  if (p === 'win32') {
    const why = remoteWhy(f)
    if (why) return [item('L4', 'front_app', 'off', `remote (${why}): windows would not show, raising is off`)]
    if (f.tools?.wt) return [item('L4', 'front_app', 'Windows Terminal', `wt.exe found at ${f.tools.wt}`)]
    return [item('L4', 'front_app', undefined, 'wt.exe not on PATH: default PowerShell window')]
  }
  if (p === 'darwin') {
    const why = remoteWhy(f)
    if (why) return [item('L4', 'front_app', 'off', `remote (${why}): windows on this Mac's screen are not seen, raising is off`)]
    if (f.terminal?.showing) return [item('L4', 'front_app', f.terminal.showing, `${f.terminal.showing} is showing a herdr client now`)]
    const inst = MAC_TERMINALS.find((a) => (f.terminal?.installed || []).includes(a) && a !== 'Terminal')
    if (inst) return [item('L4', 'front_app', inst, `${inst}.app is installed`)]
    return [item('L4', 'front_app', undefined, 'no herdr window and no extra terminal app: default (Terminal)')]
  }
  return [item('L4', 'front_app', undefined, `${p}: whosup does not raise windows here`)]
}

// L5 herdr: 실행 파일·버전·세션 목록. 읽을 수 있으면 읽기 대상에 herdr를 넣는다(WHOSUP_RUNTIMES 'auto'가 그대로 쓴다).
export function laneHerdr(f) {
  const h = f.herdr
  if (!h) return [item('L5', 'runtime_herdr', undefined, 'herdr not checked')]
  if (!h.found) return [item('L5', 'runtime_herdr', false, `herdr not found (${h.bin || 'herdr'})`)]
  const running = (h.sessions || []).filter((s) => s.status === 'running').map((s) => s.name)
  return [item('L5', 'runtime_herdr', true, `${h.version || 'herdr'}; running sessions: ${running.length ? running.join(', ') : 'none'}`)]
}

// L6 Herdr 데스크톱 앱: herdr-core 소켓(core.lock)이 살아 있으면 읽기 대상에 넣는다. herdr-app이 있으면 앱 창을 올릴 수 있다.
export function laneCore(f) {
  const c = f.herdrCore
  const out = []
  if (!c) out.push(item('L6', 'runtime_herdr_core', undefined, 'herdr-core not checked'))
  else if (c.running) out.push(item('L6', 'runtime_herdr_core', true, `herdr-core socket ${c.socket}`))
  else out.push(item('L6', 'runtime_herdr_core', false, c.socket ? `herdr-core socket missing (${c.socket})` : 'no herdr-core core.lock'))
  if (f.herdrApp) out.push(item('L6', 'herdr_app', f.herdrApp.found ? f.herdrApp.bin : undefined, f.herdrApp.found ? `${f.herdrApp.bin} found: Herdr app windows can be raised` : `${f.herdrApp.bin} not found`))
  return out
}

// L7 ovis: 서명이 확인된 서버만(GET /api/health?scope=bridge 의 bridge_protocol 숫자 + web_ui.boot_id 문자열).
// 붙은 herdr 세션은 리슨 프로세스의 HERDR_SOCKET(없으면 HERDR_SESSION)으로 안다. herdr가 그 세션을 실제로 보여 줄 때만
// 세션별 웹 주소를 자동 값으로 둔다. 모르면 값 없이 '확인 필요' 후보로만 남긴다. 클릭 기본 동작은 바꾸지 않는다(오너 결정).
export const ovisUrl = (port) => `http://127.0.0.1:${port}/?pane={pane}`
export function sessionOfSocket(socket, sessions = []) {
  if (!socket) return null
  const hit = sessions.find((s) => s.socket && s.socket === socket)
  if (hit) return hit.name
  return /[\\/]sessions[\\/]([^\\/]+)[\\/]herdr\.sock$/.exec(socket)?.[1] ?? null
}
export function laneOvis(f) {
  const servers = (f.ovis || []).filter((o) => o.signed)
  if (!servers.length) return [item('L7', 'ovis', undefined, (f.ovis || []).length ? 'ports answered but none is an ovis server' : 'no ovis server on 127.0.0.1:7317-7330')]
  const known = new Set((f.herdr?.sessions || []).map((s) => s.name))
  const taken = new Set()
  const out = [item('L7', 'ovis', servers.map((o) => o.port), `ovis on port ${servers.map((o) => o.port).join(', ')}`)]
  for (const o of servers) {
    const session = sessionOfSocket(o.socket, f.herdr?.sessions) || o.sessionEnv || null
    const how = o.socket ? 'HERDR_SOCKET of the listening process' : o.sessionEnv ? 'HERDR_SESSION of the listening process' : null
    if (!session) { out.push(item('L7', `ovis_candidate:${o.port}`, undefined, `ovis on ${o.port}: herdr session not found (${o.why || 'process environment not readable'}) — check`)); continue }
    if (!known.has(session)) { out.push(item('L7', `ovis_candidate:${o.port}`, undefined, `ovis on ${o.port} is attached to herdr session "${session}" (${how}), which herdr does not list — check`)); continue }
    if (taken.has(session)) { out.push(item('L7', `ovis_candidate:${o.port}`, undefined, `ovis on ${o.port} also serves "${session}"; the lower port is used — check`)); continue }
    taken.add(session)
    out.push(item('L7', `open_url:${session}`, ovisUrl(o.port), `ovis on ${o.port} serves herdr session "${session}" (${how})`))
  }
  return out
}

// L8 에이전트: PATH의 claude > codex. 이어서 열기는 ~/.claude/projects(CLAUDE_PROJECTS_DIR)가 있어야 대화를 찾는다.
export function laneAgent(f) {
  const a = f.agents || {}
  const out = []
  if (a.claude) out.push(item('L8', 'agent_cmd', 'claude', `claude found at ${a.claude}`))
  else if (a.codex) out.push(item('L8', 'agent_cmd', 'codex', `claude not on PATH, codex found at ${a.codex}`))
  else out.push(item('L8', 'agent_cmd', undefined, 'neither claude nor codex on PATH: default (claude)'))
  out.push(item('L8', 'resume_available', a.projectsDir === undefined ? undefined : Boolean(a.projectsDir), a.projectsDir ? `conversation folder ${a.projectsDir}` : 'no Claude conversation folder: resume starts fresh'))
  return out
}

// L9 맥 손쉬운 사용 권한: 창 올리기에서 권한이 빠졌다고 확인됐을 때만 '화면 나눠 쓰기 불가'. 확인 전에는 값 없음.
export function laneAccessibility(f) {
  if (f.platform !== 'darwin') return [item('L9', 'split_available', undefined, `${f.platform}: no macOS accessibility check`)]
  if (f.raiseWarning === 'mac_accessibility') return [item('L9', 'split_available', false, 'Accessibility permission missing: split screen and restoring minimized windows do not work')]
  return [item('L9', 'split_available', undefined, f.raiseWarning === null ? 'no permission problem seen so far (checked when a pane is clicked)' : 'not checked yet (checked when a pane is clicked)')]
}

// L10 포트: PORT(또는 4790)부터 빈 포트. whosup은 막혀 있으면 스스로 다음 포트로 간다 — 규칙표에는 그 판정만.
export function lanePort(f) {
  const p = f.port
  if (!p || !p.free) return [item('L10', 'port', undefined, p ? `no free port in ${p.start}-${p.start + 9}` : 'port not checked')]
  return [item('L10', 'port', p.free, p.free === p.start ? `${p.start} is free` : `${p.start}-${p.free - 1} busy, ${p.free} is free`)]
}

export const LANES = [laneOS, laneNode, laneDesktop, laneTerminal, laneHerdr, laneCore, laneOvis, laneAgent, laneAccessibility, lanePort]

// 레인 전체 → auto.json 본문. values는 자동 값이 있는 키만.
export function evaluate(facts) {
  const lanes = LANES.flatMap((fn) => fn(facts))
  const values = {}
  for (const l of lanes) if (l.value !== undefined && !(l.key in values)) values[l.key] = l.value
  const reasons = Object.fromEntries(lanes.filter((l) => l.value !== undefined).map((l) => [l.key, `${l.lane}: ${l.reason}`]))
  return { version: AUTO_VERSION, at: new Date().toISOString(), platform: facts.platform, values, reasons, lanes, summary: summarize(facts, lanes) }
}
export const AUTO_VERSION = 1

// 화면이 쓸 "감지한 환경" 요약(경로는 넣지 않는다).
export function summarize(f, lanes) {
  const get = (k) => lanes.find((l) => l.key === k)
  return {
    os: f.platform,
    desktop: get('desktop')?.value ?? null,
    terminal: get('front_app')?.value ?? null,
    herdr: f.herdr ? { found: Boolean(f.herdr.found), version: f.herdr.version || null, sessions: (f.herdr.sessions || []).filter((s) => s.status === 'running').map((s) => s.name) } : null,
    herdr_core: f.herdrCore ? { running: Boolean(f.herdrCore.running) } : null,
    herdr_app: f.herdrApp ? { found: Boolean(f.herdrApp.found) } : null,
    ovis: lanes.filter((l) => l.lane === 'L7' && (l.key.startsWith('open_url:') || l.key.startsWith('ovis_candidate:'))).map((l) => {
      const port = Number(/:(\d+)\//.exec(l.value || '')?.[1] || l.key.split(':')[1])
      return l.value ? { port, session: l.key.slice('open_url:'.length), url: l.value, confirmed: true, reason: l.reason } : { port, session: null, url: null, confirmed: false, reason: l.reason }
    }),
    agent: get('agent_cmd')?.value ?? null,
  }
}

// ── 실제 환경에서 입력 모으기 ──
const runText = (file, args, timeout = 3000) => new Promise((resolve) => {
  execFile(file, args, { encoding: 'utf8', timeout, killSignal: 'SIGKILL', windowsHide: true, maxBuffer: 4 * 1024 * 1024 }, (err, out) => resolve(err ? '' : String(out)))
})
// 서명 확인: ovis의 열린 /api/health?scope=bridge(인증 없이 답하는 경로, herdr가 죽어 있어도 답한다).
export function ovisSignature(body) {
  return Boolean(body) && typeof body === 'object' && typeof body.bridge_protocol === 'number' && typeof body.web_ui?.boot_id === 'string'
}
export async function probeOvis(port, timeoutMs = 800) {
  try {
    // 리디렉트는 따라가지 않는다(다른 주소로 요청이 나가지 않게), 2xx가 아닌 답은 서명으로 보지 않는다(codex 리뷰 M5-T4).
    const r = await fetch(`http://127.0.0.1:${port}/api/health?scope=bridge`, { signal: AbortSignal.timeout(timeoutMs), redirect: 'error' })
    let body = null
    if (r.ok) { try { body = await r.json() } catch {} }
    return { port, answered: true, signed: ovisSignature(body) }
  } catch { return null }
}
// 리슨 프로세스의 환경변수 두 개만 읽는다(값 전체를 남기거나 찍지 않는다). 맥: ps eww, 리눅스: /proc/<pid>/environ. 윈도우: 방법 없음.
export function envFromPs(text) {
  const pick = (k) => new RegExp(`(?:^|\\s)${k}=(\\S+)`).exec(text)?.[1] ?? null
  return { socket: pick('HERDR_SOCKET'), sessionEnv: pick('HERDR_SESSION') }
}
export function envFromProc(buf) {
  const kv = Object.fromEntries(String(buf).split('\0').map((s) => { const i = s.indexOf('='); return i > 0 ? [s.slice(0, i), s.slice(i + 1)] : null }).filter(Boolean))
  return { socket: kv.HERDR_SOCKET || null, sessionEnv: kv.HERDR_SESSION || null }
}
async function listenerEnv(port, p = platform()) {
  if (p === 'win32') return { why: 'Windows: the listening process environment is not readable' }
  const pid = Number((await runText('lsof', ['-nP', '-t', `-iTCP:${port}`, '-sTCP:LISTEN'])).trim().split('\n')[0])
  if (!pid) return { why: 'listening process not found (lsof)' }
  if (p === 'linux') { try { return envFromProc(readFileSync(`/proc/${pid}/environ`)) } catch { return { why: 'process environment not readable' } } }
  const e = envFromPs(await runText('/bin/ps', ['eww', '-o', 'command=', '-p', String(pid)]))
  return e.socket || e.sessionEnv ? e : { why: 'HERDR_SOCKET not in the listening process environment' }
}
async function findOvis(p) {
  const hits = (await Promise.all(OVIS_PORTS.map((port) => probeOvis(port)))).filter(Boolean)
  return Promise.all(hits.map(async (h) => (h.signed ? { ...h, ...(await listenerEnv(h.port, p)) } : h)))
}
const portFree = (port) => new Promise((resolve) => {
  const s = createServer()
  s.once('error', () => resolve(false))
  s.listen(port, '127.0.0.1', () => s.close(() => resolve(true)))
})
async function freePort(start) {
  for (let p = start; p < start + 10; p++) if (await portFree(p)) return p
  return null
}
const macApps = () => MAC_TERMINALS.filter((a) => [join('/Applications', `${a}.app`), join('/System/Applications/Utilities', `${a}.app`), join(homedir(), 'Applications', `${a}.app`)].some(existsSync))

export async function detect({ env = process.env } = {}) {
  const p = platform()
  const [d, term, ovis, free] = await Promise.all([
    diagnose(),
    p === 'darwin' ? herdr.detectTerminal().catch(() => null) : null,
    findOvis(p),
    freePort(Number(env.PORT) || 4790),
  ])
  const projectsDir = env.CLAUDE_PROJECTS_DIR || join(homedir(), '.claude', 'projects')
  return {
    platform: p, release: release(), env,
    node: d.node, herdr: d.herdr, herdrCore: d.herdrCore, herdrApp: d.herdrApp, tools: d.tools,
    terminal: p === 'darwin' ? { showing: term?.front_app ?? null, installed: macApps() } : null,
    ovis,
    agents: { claude: which('claude', env), codex: which('codex', env), projectsDir: existsSync(projectsDir) ? projectsDir : null },
    raiseWarning: undefined,   // L9는 칸을 눌러 창을 올려 봐야 안다 — 서버가 실시간 값(raise_warning)을 함께 내려 준다
    port: { start: Number(env.PORT) || 4790, free },
    winSession: p === 'win32' && !env.SESSIONNAME && !env.SSH_CONNECTION && !env.SSH_CLIENT ? winSessionNo() : null,
  }
}

// ── auto.json ──
export const autoPath = (stateDir) => join(stateDir, AUTO_FILE)
export function writeAuto(stateDir, result) {
  mkdirSync(stateDir, { recursive: true })
  const file = autoPath(stateDir)
  const tmp = `${file}.${process.pid}.tmp`
  writeFileSync(tmp, `${JSON.stringify(result, null, 2)}\n`)
  renameRetry(tmp, file)   // 같은 폴더 안 이름 바꾸기: 읽는 쪽은 옛 파일이나 새 파일 하나를 통째로 본다
  return file
}
// 윈도우는 다른 프로세스가 대상 파일을 열고 있는 짧은 순간(판 서버·시작 스크립트·백신이 읽는 중)에 덮어쓰는 이름 바꾸기를
// EPERM·EACCES·EBUSY로 거절한다(GitHub Actions windows-latest 실측). 잠깐 기다렸다 몇 번 다시 한다. 그 밖의 오류는 그대로 던진다.
const RETRY_CODES = new Set(['EPERM', 'EACCES', 'EBUSY'])
export function renameRetry(from, to, { rename = renameSync, tries = 20, waitMs = 25 } = {}) {
  for (let i = 1; ; i++) {
    try { return rename(from, to) } catch (err) {
      if (!RETRY_CODES.has(err?.code) || i >= tries) throw err
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, waitMs)
    }
  }
}
export function readAuto(stateDir) {
  try { const r = JSON.parse(readFileSync(autoPath(stateDir), 'utf8')); return r && typeof r === 'object' && r.values ? r : null } catch { return null }
}

// 서버(bin/whosup.mjs)가 시작할 때 auto.json을 그대로 써도 되는지: 시작 스크립트(plugin.sh·launch.mjs)가 방금 쓴 것만 믿는다.
// 형식 판본·플랫폼이 다르거나, 쓴 지 AUTO_FRESH_MS가 지났거나, 시각을 읽을 수 없으면 낡은 것으로 보고 다시 감지한다
// (직접 실행하면 몇 날 전 다른 환경에서 쓴 값이 그대로 쓰였다 — LOOP 2회차 회차 1 후보).
export const AUTO_FRESH_MS = 2 * 60 * 1000
export function autoIsFresh(r, { now = Date.now(), platform: p = platform(), maxAgeMs = AUTO_FRESH_MS } = {}) {
  if (!r || typeof r !== 'object' || r.version !== AUTO_VERSION || r.platform !== p || !r.values || r.error) return false
  const age = now - Date.parse(r.at)
  return Number.isFinite(age) && age >= -5000 && age <= maxAgeMs
}
// 지금 다시 감지해 auto.json에 쓰고 결과를 돌려준다. 감지가 실패하면 이전 값을 남기지 않는다 — 값 없는 결과(error 포함)를 쓴다.
export async function refreshAuto(stateDir, { detectFn = detect, onWriteError } = {}) {
  let r
  try { r = evaluate(await detectFn()) } catch (err) {
    r = { version: AUTO_VERSION, at: new Date().toISOString(), platform: platform(), values: {}, reasons: {}, lanes: [], summary: null, error: String(err?.message || err).slice(0, 200) }
  }
  try { writeAuto(stateDir, r) } catch (err) { onWriteError?.(err) }
  return r
}
