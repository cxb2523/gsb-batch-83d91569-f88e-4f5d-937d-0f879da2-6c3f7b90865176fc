import { createServer } from 'node:http'
import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { isWindows } from '../platform.mjs'
import { basename, dirname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import { computeBoardAsync, markSeen, markUnseen, resumeFor, setPinned, setStashed, markReopened } from './board.mjs'
import { autoValues, clientDefaults, frontAppChoice, getSettings, setSettings, settingOrigins, settingSources, SETTING_RANGES, TEXT_SETTINGS } from '../settings.mjs'
import { getMeta, setMeta } from '../db.mjs'
import * as herdr from '../runtime/herdr.mjs'
import * as core from '../runtime/core.mjs'
import { collectAll, deskLabelOf, deskOf, noteChange, runtimeForDesk, runtimeOf } from '../runtime/index.mjs'
// 자동 세팅(auto.json) 요약 + 첫 실행 확인 카드. 화면은 이것으로 "감지한 환경" 단락과 카드를 그린다.
// first_run.show: 아직 카드를 닫은 적 없음(DB meta firstrun.done 없음, 읽기 전용 보기는 늘 false).
// first_run.ask_click: 세션과 맞춘 ovis가 있을 때만 "칸을 누르면 어디로 열까요?"를 묻는다(없으면 요약과 "이대로 쓰기"만).
export function autoconfView(db) {
  const r = autoValues().result
  const summary = r?.summary ? { ...r.summary } : null
  const raise = herdr.raiseWarning()
  if (summary) summary.split_available = raise === 'mac_accessibility' ? false : r.values?.split_available ?? null
  const askClick = Boolean(summary?.ovis?.some((o) => o.confirmed))
  return {
    at: r?.at ?? null,
    platform: r?.platform ?? null,
    summary,
    lanes: r?.lanes ?? [],
    raise_warning: raise,
    client_defaults: clientDefaults(db),
    first_run: { show: !readonly() && !getMeta(db, 'firstrun.done'), ask_click: askClick, choices: TEXT_SETTINGS.click_target.choices, done_at: getMeta(db, 'firstrun.done') || null },
  }
}
// 카드에서 고른 것을 사람이 정한 값으로 저장한다(click_target → 설정 패널 값). 고르지 않고 "이대로 쓰기"면 표시만 남긴다.
export function firstRunDone(db, choice) {
  if (choice !== undefined && choice !== null) {
    const r = setSettings(db, { click_target: choice })
    if (!r.ok) return r
  }
  setMeta(db, 'firstrun.done', new Date().toISOString())
  return { ok: true, settings: getSettings(db), client_defaults: clientDefaults(db) }
}

// 보드에서 상태를 바꾼 직후 한 번 바로 수집한다 — 다음 수집 주기(3초)를 기다리지 않고 판이 따라오게.
const collectNow = async (db) => { try { await collectAll(db, { source: 'board' }) } catch {} }

const HTML_PATH = fileURLToPath(new URL('./index.html', import.meta.url))
// 화면 판본: 보드 HTML이 바뀐 채로 서버가 다시 뜨면 열려 있던 탭이 스스로 새로고침한다.
const BUILD = String(statSync(HTML_PATH).mtimeMs | 0)
const LOCAL_HOST = /^(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$/
const readonly = () => process.env.WHOSUP_READONLY === '1'

// 칸이 닫혔음을 아는 즉시 최근 닫힘으로(수집이 연속 미검출을 세기 전에) — 보드가 바로 따라오게.
export function markGoneNow(db, id, at = new Date().toISOString()) {
  noteChange()   // 이보다 먼저 읽기 시작한 수집이 이 칸을 되살리지 않게
  db.prepare("UPDATE session SET archived = 1, status = 'gone', unreachable = 0, miss_count = 0, updated_at = ? WHERE id = ? AND archived = 0").run(at, id)
  db.prepare('INSERT INTO event (session_id, at, field, before, after, source) VALUES (?, ?, ?, ?, ?, ?)').run(id, at, 'gone', 'false', 'true', 'board')
}

// 그 카드를 만들 때의 터미널(런타임이 알려 준 incarnation). 조작할 때 함께 넘겨, 같은 주소를 물려받은 다른 터미널을
// 옛 카드로 열거나 닫지 않게 한다(herdr 카드에는 값이 없고, herdr 런타임은 이 값을 쓰지 않는다).
const incarnationOf = (s) => { try { return JSON.parse(s.fields_json || '{}').incarnation ?? null } catch { return null } }
// 마지막 클릭만 이긴다 — 런타임이 달라도. 런타임마다 자기 클릭만 세므로, 판 전체의 순번은 여기서 본다.
let latestSeq = 0
export async function openSession(db, id, seq, { raise = true } = {}) {
  const s = db.prepare('SELECT * FROM session WHERE id = ?').get(id)
  if (!s) return { ok: false, code: 'no_session', message: `no session ${id}` }
  if (s.archived) return { ok: false, code: 'closed', message: 'that pane is closed — use resume' }
  const rt = runtimeOf(s.runtime)
  if (!rt) return { ok: false, code: 'no_session', message: `no session ${id}` }
  const older = () => Number.isFinite(seq) && seq < latestSeq
  if (older()) return { ok: true, code: 'superseded', window: 'superseded', message: `skipped ${s.runtime_ref} (a newer click won)` }
  if (Number.isFinite(seq)) latestSeq = seq
  let r
  try { r = await rt.focus(s.runtime_ref, { cwd: s.cwd || undefined, seq, split: getSettings(db).split_pct, raise, incarnation: incarnationOf(s), superseded: older }) } catch (err) {
    // 터미널에서 이미 닫은 칸(수집이 아직 못 따라온 3~9초): 오류 대신 바로 최근 닫힘으로 옮긴다.
    if (/pane_not_found|not found/i.test(String(err.message))) { markGoneNow(db, s.id); return { ok: true, code: 'pane_gone', message: `${s.runtime_ref} was already closed` } }
    throw err
  }
  if (r.window === 'superseded') return { ok: true, code: 'superseded', window: r.window, message: `skipped ${r.session} ${r.pane} (a newer click won)` }
  const code = r.client === 'started' ? 'focused_started' : r.window === 'opened' ? 'focused_opened' : 'focused'
  return { ok: true, code, window: r.window, message: `focused ${r.session} ${r.pane}${r.client === 'started' ? ' (session started)' : ''}${r.window === 'opened' ? ' (opened a terminal window)' : ''}` }
}

// Empty pane (shell) after a restart: resume the newest conversation for that folder, or start fresh.
// A closed (gone) pane: open a new tab in the same herdr session and resume its conversation there.
// 같은 칸에 대한 요청이 진행 중이면 두 번째는 무시한다(연타 방지 — 재개 명령이 에이전트 입력으로 두 번 들어가지 않게).
const inflight = new Set()
// 같은 대화를 서로 다른 두 칸에서 동시에 이어 열지 않는다: 이어 열기 시작한 대화는 잠시 잡아 둔다(수집이 그 대화가
// 어느 칸에서 살아났는지 알게 될 때까지 — 그 뒤로는 재개 후보 규칙이 다른 칸에서 그 대화를 빼 준다).
// 같은 칸에서 다시 누르는 것은 막지 않는다(그 칸의 연타는 위 inflight가 본다). 풀어 주는 시간은 명령을 넣는 일이 끝난
// 때부터 센다 — 만들기가 줄을 서서 오래 걸려도 그 사이에 풀리지 않게.
const resuming = new Map()   // 대화 id → { id: 잡은 칸, timer }
const RESUME_HOLD_MS = 10000
const heldByOther = (sid, id) => Boolean(sid) && resuming.has(sid) && resuming.get(sid).id !== id
const holdSid = (sid, id) => { clearTimeout(resuming.get(sid)?.timer); resuming.set(sid, { id, timer: null }) }
const releaseLater = (sid) => { const h = resuming.get(sid); if (!h) return; clearTimeout(h.timer); h.timer = setTimeout(() => { if (resuming.get(sid) === h) resuming.delete(sid) }, RESUME_HOLD_MS); h.timer.unref?.() }
const dropSid = (sid) => { clearTimeout(resuming.get(sid)?.timer); resuming.delete(sid) }
export const _clearResumeHolds = () => { for (const sid of [...resuming.keys()]) dropSid(sid) }   // 시험
// shownSid: 판이 보여 준 재개 대상(undefined면 옛 탭 — 비교하지 않는다). 다시 계산한 값과 다르면 실행하지 않는다(I-3).
export async function resumeSession(db, id, shownSid, { raise = true } = {}) {
  if (inflight.has(id)) return { ok: false, code: 'busy', message: 'already resuming that pane' }
  inflight.add(id)
  try {
    const s = db.prepare('SELECT * FROM session WHERE id = ?').get(id)
    if (!s) return { ok: false, code: 'no_session', message: `no session ${id}` }
    const cmd = getSettings(db).agent_cmd
    const rows = db.prepare('SELECT id, status, archived, provider_session FROM session WHERE archived = 0').all()
    const sid = resumeFor(rows, s, cmd)?.sid ?? null
    if (shownSid !== undefined && (shownSid || null) !== sid) return { ok: false, code: 'resume_changed', message: 'the conversation to resume changed — check the board and try again' }
    const run = sid ? `${cmd} --resume ${sid}` : cmd
    const rt = runtimeOf(s.runtime)
    if (!rt) return { ok: false, code: 'no_session', message: `no session ${id}` }
    if (s.archived && s.status === 'gone') {
      if (heldByOther(sid, id)) return { ok: false, code: 'busy', message: 'that conversation is already being resumed in another pane' }
      if (sid) holdSid(sid, id)
      let r
      try { r = await rt.newSession({ session: deskOf(s), cwd: s.cwd || homedir(), command: run, raise }) } catch (err) { if (sid) dropSid(sid); throw err }
      if (sid) releaseLater(sid)
      markReopened(db, s.id)
      return { ok: true, code: sid ? 'resumed' : 'started', message: sid ? `resuming ${sid.slice(0, 8)} in a new tab (${r.pane})` : `started ${cmd} in a new tab (${r.pane})`, resumed: Boolean(sid) }
    }
    if (s.status !== 'shell' && s.status !== 'idle' && s.status !== 'unknown') return { ok: false, code: 'has_agent', message: 'that pane already has an agent' }
    if (heldByOther(sid, id)) return { ok: false, code: 'busy', message: 'that conversation is already being resumed in another pane' }
    if (sid) holdSid(sid, id)
    let r
    try { r = await rt.focus(s.runtime_ref, { cwd: s.cwd || undefined, run, raise, incarnation: incarnationOf(s) }) } catch (err) { if (sid) dropSid(sid); throw err }
    if (sid) releaseLater(sid)
    return { ok: true, code: sid ? 'resumed' : 'started', message: sid ? `resuming ${sid.slice(0, 8)} in ${r.pane}` : `started ${cmd} in ${r.pane}`, resumed: Boolean(sid) }
  } finally {
    setTimeout(() => inflight.delete(id), 3000)
  }
}

// 꺼 둔 Herdr 앱 줄을 다시 켠다: 같은 이름·폴더로 공간을 만들고, 끌 때 열려 있던 대화를 이어서 연다.
// 옛 칸(끝난 터미널)은 'reopened'로 접는다 — 새 터미널은 수집이 새 칸으로 잡는다.
export async function startCoreDesk(db, desk, { raise = true } = {}) {
  const cmd = getSettings(db).agent_cmd
  const all = db.prepare('SELECT * FROM session WHERE archived = 0').all()
  const off = all.filter((r) => r.runtime === core.name && r.unreachable === 2 && deskOf(r) === desk)
  const others = all.filter((r) => !off.includes(r))
  const commands = []
  for (const r of off) {
    if (!r.provider_session) continue
    const t = resumeFor(others, r, cmd)
    if (t?.from === 'pane') commands.push({ id: r.id, cwd: r.cwd, command: `${cmd} --resume ${t.sid}` })   // 그 칸의 대화만 — 폴더의 다른 대화로 대신하지 않는다
  }
  const r = await core.startSession(desk, undefined, { raise, commands })
  // 이어 열지 못한 대화의 옛 칸은 접지 않는다: 다음 수집이 닫힌 칸으로 옮기고, 거기서 하나씩 이어 열 수 있다.
  const failed = new Set(r.failed || [])
  const at = new Date().toISOString()
  const fold = db.prepare("UPDATE session SET archived = 1, status = 'reopened', unreachable = 0, updated_at = ? WHERE id = ?")
  for (const row of off) if (!failed.has(row.id)) fold.run(at, row.id)
  return r
}
// 한 줄을 끄거나 켜는 요청은 그 뒤의 수집까지 끝나야 다음 것을 받는다: 끄자마자 켜면 판(DB)이 아직 꺼진 줄을 모르고,
// 이어 열 대화를 하나도 찾지 못한 채 빈 공간만 만든다.
const deskBusy = new Set()

// POST는 이 보드 페이지(같은 주소·같은 포트)만 받는다 — 공개판의 신뢰 모델 그대로. remote-click의 '포트가 달라도 루프백이면 허용'은
// 신뢰 범위를 넓히는 결정이라 여기서는 들이지 않았다(오너 결정 대기). Origin이 없으면(curl 등 브라우저 밖) 통과.
export function sameOrigin(req) {
  const origin = req.headers.origin
  const port = req.socket.localPort
  return !origin || origin === `http://127.0.0.1:${port}` || origin === `http://localhost:${port}`
}
function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = ''
    req.on('data', (c) => { data += c; if (data.length > 4096) reject(new Error('body too large')) })
    req.on('end', () => resolve(data))
    req.on('error', reject)
  })
}

// 새 세션 창의 폴더 고르기: 홈 아래만, 숨김 폴더는 빼고, 이름순. 경로를 손으로 칠 필요가 없게 한다.
const HOME = homedir()
// Windows 경로(C:\\Users\\…)도 받도록 구분자 대신 relative로 판정 (Windows 실기기 QA: 폴더 탐색이 400)
// 윈도우 경로는 대소문자를 가리지 않는다: c:\users\me 도 홈 자체로 본다(REPORT 14번).
const sameDir = (a, b) => (isWindows() ? a.toLowerCase() === b.toLowerCase() : a === b)
const underHome = (p) => { const r = relative(HOME, p); return sameDir(p, HOME) || (!!r && !r.startsWith('..') && !isAbsolute(r)) }
export function listDirs(path) {
  const p = resolve(path)
  if (!underHome(p)) return { ok: false, message: 'only folders under home' }
  let names = []
  try { names = readdirSync(p, { withFileTypes: true }).filter((d) => !d.name.startsWith('.') && (d.isDirectory() || (d.isSymbolicLink() && !isWindows() && isDir(join(p, d.name))))).map((d) => d.name) }
  catch (err) { return { ok: false, message: String(err.code || err.message) } }
  names.sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }))
  return { ok: true, path: p, parent: sameDir(p, HOME) ? null : dirname(p), home: HOME, sep, dirs: names.slice(0, 500), more: Math.max(0, names.length - 500) }
}
const isDir = (p) => { try { return statSync(p).isDirectory() } catch { return false } }
// 최근에 칸이 열렸던 폴더(지금도 있는 것만), 최근 활동 순.
export function recentFolders(db, limit = 12) {
  const rows = db.prepare(`SELECT cwd, MAX(COALESCE(last_user_msg_at, '')) AS t, MAX(updated_at) AS u FROM session WHERE cwd != '' GROUP BY cwd ORDER BY t DESC, u DESC LIMIT 60`).all()
  return rows.map((r) => r.cwd).filter((c) => underHome(c) && !sameDir(c, HOME) && existsSync(c)).slice(0, limit)
}

export function createBoardServer(db, { heartbeatPath } = {}) {
  // 열려 있는 보드 탭(SSE). 판이 바뀌면 notifyChange()가 한 줄 밀어 주고, 탭은 그때 바로 새로 읽는다.
  const clients = new Set()
  const notify = () => { for (const c of clients) c.write(`data: ${Date.now()}\n\n`) }
  // 가려진 탭이라도 붙어 있으면 그 사실을 적어 둔다 — herdr가 켜질 때 탭을 또 열지 않게(plugin.sh).
  const connectedPath = heartbeatPath ? join(dirname(heartbeatPath), 'board-connected') : null
  const touchConnected = () => { if (connectedPath && clients.size) { try { writeFileSync(connectedPath, new Date().toISOString()) } catch {} } }
  herdr.setFrontApp(...frontAppChoice(db))   // 설정 패널 값 > FRONT_APP > ''(자동, 자동 세팅 앱은 따로)
  const beat = setInterval(() => { touchConnected(); for (const c of clients) c.write(': ping\n\n') }, 5000)
  beat.unref()
  const server = createServer(async (req, res) => {
    const send = (code, body, type = 'application/json; charset=utf-8') => { res.writeHead(code, { 'content-type': type, 'cache-control': 'no-store' }); res.end(body) }
    try {
      if (!LOCAL_HOST.test(req.headers.host || '')) return send(403, JSON.stringify({ error: 'local only' }))
      const url = new URL(req.url, 'http://127.0.0.1')
      if (req.method === 'GET' && url.pathname === '/') return send(200, readFileSync(HTML_PATH), 'text/html; charset=utf-8')
      // health는 '후즈업 프로세스가 답하는가'만 말한다. herdr에 닿지 못해도 200이고, 그 사정은 herdr_error에 싣는다.
      if (req.method === 'GET' && url.pathname === '/api/health') {
        let sessions = null, herdrError
        try { sessions = await herdr.runningSessionsAsync() } catch (err) { herdrError = String(err.message || err).slice(0, 300) }
        // targets = 새 세션을 열 수 있는 줄(herdr 세션 + Herdr 앱 공간). 화면은 이 목록을 쓰고, herdr는 옛 화면·점검용으로 남긴다.
        let targets = (sessions || []).map((n) => ({ key: n, label: n }))
        if (core.available()) {
          const known = db.prepare('SELECT * FROM session WHERE runtime = ? AND archived = 0 AND unreachable = 0').all(core.name).map((r) => ({ key: deskOf(r), label: deskLabelOf(r) }))
          try { targets = targets.concat(await core.targets(known)) } catch {}
        }
        return send(200, JSON.stringify({ ok: true, readonly: readonly(), herdr: sessions, targets, ...(herdrError ? { herdr_error: herdrError } : {}) }))
      }
      if (req.method === 'GET' && url.pathname === '/api/events') {
        // 브라우저는 한 주소에 연결을 6개까지만 연다. 탭을 여러 개 띄워도 일반 요청이 막히지 않게 4개까지만 받고,
        // 그 뒤 탭은 204로 돌려보낸다(EventSource가 다시 붙지 않고, 그 탭은 3초 주기로만 읽는다).
        if (clients.size >= 4) { res.writeHead(204, { 'cache-control': 'no-store' }); return res.end() }
        res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store', connection: 'keep-alive' })
        res.write(': ok\n\n')
        clients.add(res); touchConnected()
        req.on('close', () => clients.delete(res))
        return
      }
      if (req.method === 'GET' && url.pathname === '/api/warm') { if (!readonly()) herdr.warmClick(); return send(200, '{"ok":true}') }
      if (req.method === 'GET' && url.pathname === '/api/settings') return send(200, JSON.stringify({ settings: getSettings(db), ranges: SETTING_RANGES, sources: settingSources(db), origins: settingOrigins(db), detected: await herdr.detectTerminal(), autoconf: autoconfView(db) }))
      if (req.method === 'GET' && url.pathname === '/api/autoconf') return send(200, JSON.stringify(autoconfView(db)))
      // 읽기 전용이면 새 세션 열기가 막혀 있으므로 홈 아래 폴더 목록도 내주지 않는다.
      if (req.method === 'GET' && (url.pathname === '/api/folders' || url.pathname === '/api/dirs') && readonly()) return send(403, JSON.stringify({ error: 'read-only', code: 'read_only' }))
      if (req.method === 'GET' && url.pathname === '/api/folders') return send(200, JSON.stringify({ home: homedir(), recent: recentFolders(db) }))
      if (req.method === 'GET' && url.pathname === '/api/dirs') { const r = listDirs(url.searchParams.get('path') || homedir()); return send(r.ok ? 200 : 400, JSON.stringify(r)) }
      if (req.method === 'GET' && url.pathname === '/api/board') {
        if (heartbeatPath && url.searchParams.get('view') === '1') writeFileSync(heartbeatPath, new Date().toISOString())
        return send(200, JSON.stringify({ ...(await computeBoardAsync(db, { onLate: notify })), readonly: readonly(), raise_warning: herdr.raiseWarning(), build: BUILD }))
      }
      if (req.method === 'POST') {
        if (!sameOrigin(req)) return send(403, JSON.stringify({ error: 'local page only' }))
        // JSON만 받는다: 다른 출처의 페이지는 application/json POST를 보내려면 사전 확인(preflight)을 거쳐야 하고,
        // whosup은 CORS를 허락하지 않으므로 거기서 막힌다. text/plain·form 같은 단순 요청으로 JSON을 흉내 내는
        // CSRF(같은 컴퓨터 다른 포트의 페이지가 agent_cmd를 바꾸는 등)를 이것으로 끊는다(2026-11-09 격리 E2E 재현).
        if (readonly()) return send(403, JSON.stringify({ error: 'read-only', code: 'read_only' }))
        if (!/^application\/json\s*(;|$)/i.test(req.headers['content-type'] || '')) return send(415, JSON.stringify({ error: 'json only' }))
        res.on('finish', notify)   // 한 탭에서 바꾼 것(확인함·고정·보관·닫기)을 다른 탭도 바로 본다
        const body = JSON.parse((await readBody(req)) || '{}')
        const id = body.id
        if (['/api/open', '/api/seen', '/api/unseen', '/api/pin', '/api/stash', '/api/resume', '/api/close'].includes(url.pathname) && !Number.isInteger(id)) return send(400, JSON.stringify({ error: 'id required', code: 'bad_request' }))
        try {
          const raise = body.raise !== false   // 이 클릭을 한 브라우저가 서버 화면의 창을 올려도 되는지(기기별 설정)
          if (url.pathname === '/api/open') { const r = await openSession(db, id, Number(body.seq), { raise }); return send(r.ok ? 200 : 409, JSON.stringify(r)) }
          if (url.pathname === '/api/close') {
            const s = db.prepare('SELECT * FROM session WHERE id = ?').get(id)
            if (!s || s.archived) return send(409, JSON.stringify({ ok: false, code: 'no_session' }))
            try { await runtimeOf(s.runtime)?.closePane(s.runtime_ref, { incarnation: incarnationOf(s) }) } catch (err) { if (!/pane_not_found|not found/i.test(String(err.message))) throw err }
            markGoneNow(db, s.id); await collectNow(db)
            return send(200, JSON.stringify({ ok: true, code: 'pane_closed' }))
          }
          if (url.pathname === '/api/resume') { const r = await resumeSession(db, id, body.sid, { raise }); await collectNow(db); return send(r.ok ? 200 : 409, JSON.stringify(r)) }
          if (url.pathname === '/api/seen') return send(200, JSON.stringify({ ok: true, seen_at: markSeen(db, id) }))
          if (url.pathname === '/api/unseen') { markUnseen(db, id); return send(200, JSON.stringify({ ok: true })) }
          if (url.pathname === '/api/pin') return send(200, JSON.stringify({ ok: true, pinned_at: setPinned(db, id, body.on !== false) }))
          if (url.pathname === '/api/stash') return send(200, JSON.stringify({ ok: true, stashed_at: setStashed(db, id, body.on !== false) }))
          if (url.pathname === '/api/desk') {
            const session = String(body.session || '')
            const rt = runtimeForDesk(session)
            if (!rt.validSessionName(session)) return send(400, JSON.stringify({ ok: false, code: 'bad_request' }))
            if (deskBusy.has(session)) return send(409, JSON.stringify({ ok: false, code: 'busy', message: 'that row is already being switched' }))
            deskBusy.add(session)
            try {
              if (body.on === false) { await rt.stopSession(session); await collectNow(db); return send(200, JSON.stringify({ ok: true, code: 'desk_stopped' })) }
              const r = rt === core ? await startCoreDesk(db, session, { raise }) : await rt.startSession(session, undefined, { raise })
              await collectNow(db); return send(200, JSON.stringify({ ok: true, code: 'desk_started', window: r.window, ...(r.failed?.length ? { not_resumed: r.failed.length } : {}) }))
            } finally { deskBusy.delete(session) }
          }
          // 터미널 앱은 저장하는 즉시 다음 클릭부터 쓴다(재시작 없음).
          if (url.pathname === '/api/settings') { const r = setSettings(db, body.settings); if (r.ok) herdr.setFrontApp(...frontAppChoice(db)); return send(r.ok ? 200 : 400, JSON.stringify(r)) }
          if (url.pathname === '/api/first-run') { const r = firstRunDone(db, body.choice); return send(r.ok ? 200 : 400, JSON.stringify(r)) }
          if (url.pathname === '/api/new') {
            const { session, cwd } = body
            const rt = runtimeForDesk(session)
            if (!rt.validSessionName(session)) return send(400, JSON.stringify({ ok: false, code: 'bad_request' }))
            if ( typeof cwd !== 'string' || !underHome(resolve(cwd))) return send(400, JSON.stringify({ ok: false, code: 'bad_folder', message: 'session and a folder under home are required' }))
            if (!isDir(cwd)) return send(400, JSON.stringify({ ok: false, code: 'no_folder', message: `no such folder: ${cwd}` }))
            const r = await rt.newSession({ session, cwd, command: getSettings(db).agent_cmd, raise }); await collectNow(db)
            return send(200, JSON.stringify({ ok: true, code: 'opened_new', message: `opened ${basename(cwd)} in ${session} (${r.pane})` }))
          }
        } catch (err) {
          if (err.code === 'cwd_missing') return send(409, JSON.stringify({ ok: false, code: 'cwd_missing', message: err.message.slice(0, 300) }))
          return send(500, JSON.stringify({ ok: false, code: 'herdr_error', message: err.message.slice(0, 300) }))
        }
      }
      return send(404, JSON.stringify({ error: 'not found' }))
    } catch (err) { return send(500, JSON.stringify({ error: String(err.message).slice(0, 300) })) }
  })
  server.notifyChange = notify
  server.on('close', () => { clearInterval(beat); for (const c of clients) c.end() })
  return server
}

export function startBoard(db, { port = Number(process.env.PORT || 4790), heartbeatPath } = {}) {
  const server = createBoardServer(db, { heartbeatPath })
  return new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(port, '127.0.0.1', () => resolve(server))
  })
}
