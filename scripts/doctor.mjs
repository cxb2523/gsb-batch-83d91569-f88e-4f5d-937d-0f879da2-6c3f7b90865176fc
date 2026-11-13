#!/usr/bin/env node
// whosup doctor — 이 기계에서 whosup이 쓰는 것들을 읽기만 해서 한 번에 보여 준다(특히 윈도우 실기기 확인용).
//
//   node scripts/doctor.mjs            사람이 읽는 표 + 상태 폴더에 doctor.json 스냅숏
//   node scripts/doctor.mjs --json     같은 내용을 JSON으로
//   node scripts/doctor.mjs --probe    herdr 세션 소켓(윈도우는 named pipe)에 실제로 접속이 되는지도 본다(접속만 하고 아무것도 보내지 않음)
//   node scripts/doctor.mjs --no-save  스냅숏을 남기지 않는다
//
// 스냅숏은 진단 기록일 뿐이다: whosup은 이 파일을 읽어 동작을 정하지 않는다(OS 판단은 언제나 process.platform).
// 아무것도 고치거나 띄우지 않는다. herdr에는 --version과 session list만 묻는다. 토큰·키 값은 읽지도 찍지도 않는다.
import { execFile, spawnSync } from 'node:child_process'
import { existsSync, lstatSync, mkdirSync, writeFileSync } from 'node:fs'
import { createConnection } from 'node:net'
import { arch, homedir, release } from 'node:os'
import { delimiter, join } from 'node:path'
import { bin, herdrCommand, parseSessionJson, parseSessionTable } from '../src/runtime/herdr.mjs'
import * as core from '../src/runtime/core.mjs'
import { connectTarget, isWindows, platform } from '../src/platform.mjs'

const argv = process.argv.slice(2)
const STATE = process.env.WHOSUP_STATE_DIR || process.env.HERDR_PLUGIN_STATE_DIR || join(homedir(), '.config', 'whosup')

const run = (file, args, timeout = 5000) => new Promise((resolve) => {
  execFile(file, args, { encoding: 'utf8', timeout, killSignal: 'SIGKILL', windowsHide: true }, (err, stdout, stderr) =>
    resolve(err ? { ok: false, code: err.code ?? null, out: String(stdout || ''), err: String(stderr || err.message || '').trim().split('\n')[0].slice(0, 200) } : { ok: true, out: String(stdout) }))
})
// PATH에서 실행 파일 찾기(실행하지 않고 파일만 본다). 윈도우는 PATHEXT(.EXE 등)를 붙여 본다.
// 윈도우 스토어 앱의 실행 별칭(…\WindowsApps\wt.exe)은 0바이트 재분석 지점이라 existsSync가 false(stat EACCES)를 낸다
// — 링크 자체가 있으면(lstat) 있는 것으로 본다(윈도우 실기기 실측 2026-11-11).
const present = (p, win) => { if (existsSync(p)) return true; if (!win) return false; try { lstatSync(p); return true } catch { return false } }
export function which(name, env = process.env, win = isWindows()) {
  const exts = win ? ['', ...String(env.PATHEXT || '.EXE;.CMD;.BAT;.COM').split(';').filter(Boolean)] : ['']
  for (const dir of String(env.PATH || env.Path || '').split(win ? ';' : delimiter).filter(Boolean)) {
    for (const ext of exts) { const p = join(dir, name + ext); if (present(p, win)) return p }
  }
  return null
}
const probe = (target, timeoutMs = 1500) => new Promise((resolve) => {
  const sock = createConnection(target)
  const done = (r) => { clearTimeout(t); sock.destroy(); resolve(r) }
  const t = setTimeout(() => done('timeout'), timeoutMs)
  sock.once('connect', () => done('ok'))
  sock.once('error', (e) => done(e.code || 'error'))
})

// tasklist /FO CSV /NH 한 줄("이미지","PID","세션 이름","세션#","메모리")에서 세션 번호. 못 읽으면 null.
export function sessionFromTasklist(text) { const m = /^"[^"]*","\d+","[^"]*","(\d+)"/m.exec(String(text || '')); return m ? Number(m[1]) : null }
// 이 프로세스의 윈도우 세션 번호(0 = 서비스·SSH, 1 이상 = 로그온한 사용자의 바탕화면). 읽기만 한다.
export function winSessionNo(pid = process.pid) {
  try { return sessionFromTasklist(spawnSync('tasklist', ['/FI', `PID eq ${pid}`, '/FO', 'CSV', '/NH'], { encoding: 'utf8', timeout: 5000, windowsHide: true }).stdout) } catch { return null }
}
// 바탕화면 세션 여부. 윈도우: 서비스·SSH로 띄운 프로세스는 세션 0이라 창을 올려도 보이지 않는다(Windows 실기기 실측).
// SESSIONNAME은 바탕화면 로그온에 'Console'(원격 데스크톱이면 RDP-Tcp#N)으로 들어오고, 서비스·SSH에는 없다.
// 로그온 예약 작업(At logon, 대화형)으로 띄운 프로세스는 바탕화면 세션(1 이상)에 있어도 SESSIONNAME이 없다(윈도우 실기기 실측 2026-11-11)
// — 그래서 SESSIONNAME이 없으면 세션 번호를 직접 본다(sessionNo: 주입값, undefined면 tasklist로 읽음, null이면 모름).
export function desktopSession(env = process.env, win = isWindows(), sessionNo) {
  if (win) {
    if (env.SSH_CONNECTION || env.SSH_CLIENT) return { ok: false, why: 'ssh (session 0: windows will not show)' }
    // 'Services'는 세션 0(서비스)의 이름이다 — 바탕화면으로 보지 않는다(codex 리뷰 M5-T4).
    if (/^services$/i.test(env.SESSIONNAME || '')) return { ok: false, why: 'SESSIONNAME=Services (session 0: windows will not show)' }
    if (env.SESSIONNAME) return { ok: true, why: `SESSIONNAME=${env.SESSIONNAME}` }
    const n = sessionNo === undefined ? winSessionNo() : sessionNo
    if (Number.isInteger(n) && n > 0) return { ok: true, why: `session ${n} (no SESSIONNAME: started by a logon task)` }
    if (n === 0) return { ok: false, why: 'session 0: windows will not show' }
    return { ok: false, why: 'no SESSIONNAME: likely a service or session 0' }
  }
  if (env.SSH_CONNECTION) return { ok: false, why: 'ssh' }
  if (platform() === 'linux' && !env.DISPLAY && !env.WAYLAND_DISPLAY) return { ok: false, why: 'no DISPLAY/WAYLAND_DISPLAY' }
  return { ok: true, why: 'local' }
}

export async function diagnose({ probeSockets = false } = {}) {
  const r = { at: new Date().toISOString(), os: { platform: platform(), release: release(), arch: arch() } }
  let sqlite = true
  try { await import('node:sqlite') } catch { sqlite = false }
  r.node = { version: process.version, execPath: process.execPath, sqlite }
  r.desktop = desktopSession()
  // herdr
  const herdrBin = bin()
  const h = { bin: herdrBin, from: process.env.HERDR_BIN_PATH ? 'HERDR_BIN_PATH' : process.env.HERDR_BIN ? 'HERDR_BIN' : 'search' }
  const ver = await run(...herdrCommand(['--version']))
  h.found = ver.ok || ver.code !== 'ENOENT'
  h.version = ver.ok ? ver.out.trim() : null
  if (!ver.ok) h.error = ver.err
  let rows = null
  if (h.found) {
    const js = await run(...herdrCommand(['session', 'list', '--json']), 15000)
    try { rows = parseSessionJson(js.out); h.sessionListJson = true } catch {
      h.sessionListJson = false
      const tx = await run(...herdrCommand(['session', 'list']), 15000)
      if (tx.ok) rows = parseSessionTable(tx.out); else h.sessionListError = tx.err
    }
  }
  h.sessions = []
  for (const s of rows || []) {
    const target = connectTarget(s.socket)
    const row = { name: s.name, status: s.status, socket: s.socket, connect: target, socketFile: s.socket ? existsSync(s.socket) : false }
    if (probeSockets && s.status === 'running') row.probe = await probe(target)
    h.sessions.push(row)
  }
  r.herdr = h
  // herdr-core (Herdr 앱)
  const sp = core.socketPath()
  r.herdrCore = { stateDirs: core.stateDirs(), socket: sp, connect: sp ? connectTarget(sp) : null, running: core.available(), assumption: isWindows() ? 'named pipe like herdr (unverified)' : null }
  if (probeSockets && r.herdrCore.running) r.herdrCore.probe = await probe(r.herdrCore.connect)
  r.herdrApp = { bin: core.appBin(), found: Boolean(which(core.appBin())) || existsSync(core.appBin()) }
  // 그 밖의 도구
  r.tools = { git: which('git') }
  if (isWindows()) Object.assign(r.tools, { powershell: which('powershell.exe'), pwsh: which('pwsh.exe'), wt: which('wt.exe') })
  else if (platform() === 'darwin') Object.assign(r.tools, { osascript: existsSync('/usr/bin/osascript') ? '/usr/bin/osascript' : null })
  // 실기기에서만 확인할 수 있는 것(자동으로 판정하지 않는다)
  r.manual = isWindows() ? [
    'herdr startup hook: after herdr restarts, is whosup still running once the hook has returned? (node scripts/launch.mjs status)',
    'click a pane: does the terminal window come forward (desktop session needed)?',
    'click twice quickly while no window is open: only one new window?',
  ] : []
  return r
}

const mark = (ok) => (ok ? 'ok ' : '-- ')
export function render(r) {
  const L = []
  L.push(`whosup doctor  ${r.at}`)
  L.push(`${mark(true)}os        ${r.os.platform} ${r.os.release} ${r.os.arch}`)
  L.push(`${mark(r.node.sqlite)}node      ${r.node.version} ${r.node.execPath}${r.node.sqlite ? '' : '  (node:sqlite missing: need Node 22.13+)'}`)
  L.push(`${mark(r.desktop.ok)}desktop   ${r.desktop.why}`)
  L.push(`${mark(r.herdr.found)}herdr     ${r.herdr.bin} (${r.herdr.from})${r.herdr.version ? `  ${r.herdr.version}` : r.herdr.error ? `  ${r.herdr.error}` : ''}`)
  if (r.herdr.found) L.push(`${mark(r.herdr.sessionListJson)}  --json  session list --json ${r.herdr.sessionListJson ? 'supported' : 'not supported (table parser used)'}`)
  for (const s of r.herdr.sessions) L.push(`    session ${s.name} ${s.status}  ${s.connect}${s.probe ? `  connect=${s.probe}` : ''}`)
  L.push(`${mark(r.herdrCore.running)}core      ${r.herdrCore.running ? r.herdrCore.connect : 'not running'}${r.herdrCore.assumption ? `  (${r.herdrCore.assumption})` : ''}${r.herdrCore.probe ? `  connect=${r.herdrCore.probe}` : ''}`)
  L.push(`    state   ${r.herdrCore.stateDirs.join(' | ')}`)
  L.push(`${mark(r.herdrApp.found)}herdr-app ${r.herdrApp.bin}${r.herdrApp.found ? '' : ' (not found: Herdr app cards can still be read, window control needs it)'}`)
  for (const [k, v] of Object.entries(r.tools)) L.push(`${mark(Boolean(v))}${k.padEnd(9)} ${v || 'not found'}`)
  for (const m of r.manual) L.push(`??  check by hand: ${m}`)
  return L.join('\n')
}

if (process.argv[1] && /doctor\.mjs$/.test(process.argv[1])) {
  const r = await diagnose({ probeSockets: argv.includes('--probe') })
  console.log(argv.includes('--json') ? JSON.stringify(r, null, 2) : render(r))
  if (!argv.includes('--no-save')) {
    try { mkdirSync(STATE, { recursive: true }); writeFileSync(join(STATE, 'doctor.json'), `${JSON.stringify(r, null, 2)}\n`); if (!argv.includes('--json')) console.log(`snapshot: ${join(STATE, 'doctor.json')}`) } catch (e) { console.error(`could not write the snapshot: ${e.message}`) }
  }
}
