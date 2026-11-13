#!/usr/bin/env node
// preflight | start | stop | status | open — plugin.sh를 Node로 옮긴 것. 윈도우의 herdr가 셸 없이
// ["node", "scripts/launch.mjs", "<명령>"]로 부른다(herdr-plugin.toml의 windows 항목). macOS·리눅스는 지금처럼 plugin.sh를 쓴다
// (herdr가 최소 PATH로 부를 때 node를 찾아 주는 node-path.sh가 sh 쪽에 있어서다). 손으로 돌려도 된다: node scripts/launch.mjs status
//
// 상태(pid·db·port·로그)는 herdr가 부를 때 HERDR_PLUGIN_STATE_DIR, 아니면 ~/.config/whosup.
// 사용자 설정은 <설정 폴더>/.env의 KEY=VALUE 줄을 읽는다 — 셸로 실행하지 않는다(따옴표 한 겹만 벗기고 $ 펼치기·명령 실행 없음).
import { spawn, spawnSync } from 'node:child_process'
import { closeSync, openSync, readFileSync, statSync, unlinkSync, writeFileSync, mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as sleep } from 'node:timers/promises'

const ROOT = fileURLToPath(new URL('..', import.meta.url))

// .env 한 줄 = KEY=VALUE. 빈 줄·# 주석·앞의 export 는 넘긴다. 값 양끝의 같은 따옴표 한 겹만 벗긴다. 이름이 이상한 줄은 버린다.
export function parseEnvFile(text) {
  const out = {}
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const m = /^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/.exec(line)
    if (!m) continue
    let v = m[2]
    const q = v[0]
    if ((q === '"' || q === "'") && v.length >= 2 && v.endsWith(q)) v = v.slice(1, -1)
    else v = v.replace(/\s+#.*$/, '').trim()   // 따옴표 없는 값 뒤의 " # 주석"
    out[m[1]] = v
  }
  return out
}

export function paths(env = process.env) {
  const STATE = env.HERDR_PLUGIN_STATE_DIR || join(homedir(), '.config', 'whosup')
  const CONF = env.HERDR_PLUGIN_CONFIG_DIR || join(homedir(), '.config', 'whosup')
  return { STATE, CONF, PID: join(STATE, 'server.pid'), LOG: join(STATE, 'server.log'), PORTF: join(STATE, 'port') }
}
// .env가 환경을 덮는다(plugin.sh의 set -a; . .env 와 같은 순서).
export function loadEnv(env = process.env) {
  const { CONF } = paths(env)
  let file = {}
  try { file = parseEnvFile(readFileSync(join(CONF, '.env'), 'utf8')) } catch {}
  return { ...env, ...file }
}

const readText = (f) => { try { return readFileSync(f, 'utf8').trim() } catch { return '' } }
export function pidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false
  try { process.kill(pid, 0); return true } catch (e) { return e.code === 'EPERM' }
}
const sqliteOk = async () => { try { await import('node:sqlite'); return true } catch { return false } }
const NEED_NODE = () => `whosup needs Node 22.13 or newer (found ${process.version}): node:sqlite is not available without flags.`
const recent = (file, ms = 15000) => { try { return Date.now() - statSync(file).mtimeMs < ms } catch { return false } }
// 실행 환경 확인(scripts/autoconf.mjs): 자동 값을 상태 폴더 auto.json에 쓴다. 따로 띄운 node로 돌려 .env를 합친 환경을 그대로 넘긴다.
// 실패해도 설치·시작은 막지 않는다(기본값으로 뜬다). .env·설정 패널은 건드리지 않는다.
export function runAutoconf(env, STATE, log = console.log) {
  const r = spawnSync(process.execPath, [join(ROOT, 'scripts', 'autoconf.mjs')], { cwd: ROOT, env: { ...env, WHOSUP_STATE_DIR: STATE }, encoding: 'utf8', timeout: 60000, windowsHide: true })
  if (r.status !== 0) { log(`whosup autoconf failed: starting with defaults${r.error ? ` (${r.error.message})` : ''}`); return false }
  log(String(r.stdout || '').trimEnd()); return true
}
// auto.json의 자동 값 하나(없으면 undefined).
const autoValue = (STATE, key) => { try { return JSON.parse(readFileSync(join(STATE, 'auto.json'), 'utf8')).values?.[key] } catch { return undefined } }
async function answers(url) {
  try { const r = await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(2000) }); return r.ok } catch { return false }
}

export async function main(cmd = 'status', env0 = process.env, log = console.log) {
  const env = loadEnv(env0)
  const { STATE, PID, LOG, PORTF } = paths(env)
  mkdirSync(STATE, { recursive: true })
  const PORT = env.PORT || '4790'
  let URL_ = `http://127.0.0.1:${PORT}`
  const alive = () => pidAlive(Number(readText(PID)))
  // 4790이 차 있으면 whosup은 다음 포트로 뜨고 $STATE/port에 적는다 — 그 포트를 먼저 본다.
  const healthy = async () => {
    const p = readText(PORTF)
    if (p && await answers(`http://127.0.0.1:${p}`)) { URL_ = `http://127.0.0.1:${p}`; return true }
    return answers(URL_)
  }
  const openBrowser = (force = false) => {
    // 환경변수·.env > 자동 감지(원격이면 0) > 1
    if (String(env.OPEN_BROWSER ?? autoValue(STATE, 'open_browser') ?? '1') !== '1') return
    if (recent(join(STATE, 'board-heartbeat'))) return            // 이 보드를 보는 탭이 15초 안에 신호를 보냈다
    if (!force && recent(join(STATE, 'board-connected'))) return  // herdr 시작 때: 가려진 탭이라도 붙어 있으면 새로 열지 않는다
    let how = null
    if (process.platform === 'win32') how = ['explorer.exe', [URL_]]
    else if (process.platform === 'darwin') { if (!env.SSH_CONNECTION) how = ['/usr/bin/open', [URL_]] }
    else if (env.DISPLAY || env.WAYLAND_DISPLAY) how = ['xdg-open', [URL_]]
    if (!how) return
    const child = spawn(how[0], how[1], { detached: true, stdio: 'ignore', windowsHide: true })
    child.once('error', (err) => console.error(`whosup: could not open the browser: ${err.message}`))
    child.unref()
  }

  switch (cmd) {
    case 'preflight': {
      if (!(await sqliteOk())) { log(NEED_NODE()); return 1 }
      log(`node ${process.version} ok`)
      runAutoconf(env, STATE, log)   // 설치(build 훅) 때 감지 결과를 herdr 로그에 남긴다
      return 0
    }
    case 'start': {
      if (await healthy()) { log(`whosup already listening at ${URL_}`); openBrowser(); return 0 }
      // 기록된 whosup이 살아 있는데 답하지 않으면 새로 띄우지 않는다 — pid 파일을 덮어쓰면 그 프로세스가 고아가 된다.
      if (alive()) { log(`whosup pid ${readText(PID)} is running but not answering — run stop first, see ${LOG}`); return 1 }
      if (!(await sqliteOk())) { log(NEED_NODE()); return 1 }
      runAutoconf(env, STATE, () => {})   // 서버를 띄우기 전에 auto.json을 새로 쓴다(서버가 시작할 때 읽는다)
      const fd = openSync(LOG, 'a')
      // startup 훅은 한 번 실행되고 끝나는 명령이다: whosup은 떼어 내서(detached + unref) 훅이 끝나도 살아 있게 한다.
      // 윈도우에서 herdr가 훅이 끝날 때 자식까지 끝내는지는 실기기에서 확인할 것(doctor의 손 확인 항목).
      const child = spawn(process.execPath, [join(ROOT, 'bin', 'whosup.mjs')], { cwd: ROOT, env: { ...env, WHOSUP_STATE_DIR: STATE, PORT }, detached: true, stdio: ['ignore', fd, fd], windowsHide: true })
      let spawnErr = null
      child.once('error', (err) => { spawnErr = err })
      child.unref()
      closeSync(fd)
      for (let i = 0; i < 40 && !spawnErr; i++) { if (await healthy()) break; if (!pidAlive(child.pid)) break; await sleep(250) }
      if (!spawnErr && await healthy()) {
        // 같은 상태 폴더의 다른 whosup이 이미 답하고 있으면 방금 띄운 것은 스스로 끝난다 — 그때는 pid 파일을 건드리지 않는다.
        if (pidAlive(child.pid)) writeFileSync(PID, String(child.pid))
        log(`whosup listening at ${URL_}`); openBrowser(); return 0
      }
      // 실패로 끝낼 때는 방금 띄운 프로세스를 남기지 않는다.
      try { if (child.pid) process.kill(child.pid) } catch {}
      log(`whosup failed to start — see ${LOG}${spawnErr ? ` (${spawnErr.message})` : ''}`)
      log(readText(LOG).split('\n').slice(-5).join('\n'))
      return 1
    }
    case 'stop': {
      if (!alive()) { log('whosup not running'); return 0 }
      // 윈도우에서 process.kill은 곧바로 끝낸다(TerminateProcess) — whosup의 exit 처리는 돌지 않지만, 창 도우미(PowerShell)는
      // 표준 입력이 닫히면 스스로 끝나고 SQLite 잠금은 OS가 푼다(REPORT 20번).
      const pid = Number(readText(PID))
      try { process.kill(pid, 'SIGTERM') } catch {}
      for (let i = 0; i < 20 && alive(); i++) await sleep(250)
      if (alive()) { log(`still running pid=${pid}`); return 1 }
      try { unlinkSync(PID) } catch {}
      log('whosup stopped'); return 0
    }
    case 'status': {
      if (await healthy()) { log(`whosup listening at ${URL_} (pid ${readText(PID) || '?'})`); return 0 }
      log('whosup not running'); return 1
    }
    case 'open': {
      if (!(await healthy())) { log('whosup not running — start it first'); return 1 }
      env.OPEN_BROWSER = '1'
      openBrowser(true); log(`opened ${URL_}`); return 0
    }
    default: log('usage: launch.mjs preflight|start|stop|status|open'); return 2
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = await main(process.argv[2] || 'status')
