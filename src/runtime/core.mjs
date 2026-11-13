// herdr-core runtime: every live terminal of the herdr-core server on this machine — the terminals the Herdr app shows.
// Reads and writes go to the core's own socket (JSON-RPC, one line per message); a core that is not running is never
// started from here. Window control (jump to a pane, new tab, close a space) goes through the `herdr-app` command.
// Nothing here assumes a space name, a folder, or an agent wrapper.
import { execFile } from 'node:child_process'
import { createConnection } from 'node:net'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { basename, dirname, join } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'
import { STATE_DIR } from '../db.mjs'
import { commandFor, connectTarget, isWindows } from '../platform.mjs'
import * as herdr from './herdr.mjs'
// A cycle on purpose (context.mjs reads screens through this module): only used inside functions, never while loading.
import { isTrustScreen } from '../board/context.mjs'

export const name = 'herdr-core'
export const FIELDS = ['lastStatus', 'requiresAttention', 'attentionReason', 'lastUserMessageAt', 'title']
export const TRACKS_GONE = true
export const IDLE_AFTER_WORK_IS_DONE = false   // the core reports `done` itself
export const AGENT_CHANGE_IS_NEW = true        // the core names the program in a terminal: another agent there is a new card
// Row key on the board. A space of the Herdr app is one row; terminals outside any space share the row `core:`.
// herdr session names cannot contain ':', so these keys never collide with a herdr session.
export const DESK_PREFIX = 'core:'
export const LOOSE_LABEL = 'herdr-core'
export const isDesk = (s) => typeof s === 'string' && /^core:[A-Za-z0-9._-]*$/.test(s)
const spaceOf = (desk) => desk.slice(DESK_PREFIX.length)

// ── where the core listens ──────────────────────────────────────────
// HC_SOCKET wins. Otherwise the core writes its socket path into <state>/herdr-core/<session>/core.lock.
// Windows (assumption, not checked on a Windows machine: herdr-core's Windows build is unknown): the state folder may be
// %LOCALAPPDATA% instead of ~/.local/state, so both are looked at, and the socket is reached as a named pipe by the same
// rule herdr uses (\\.\pipe\<socket path>, see platform.mjs connectTarget). The socket file itself is what tells
// "running" (available), as with herdr where that file holds pid:nonce.
const coreSession = () => process.env.HC_SESSION || 'default'
export const stateDirs = () => (process.env.XDG_STATE_HOME ? [process.env.XDG_STATE_HOME]
  : [...(isWindows() && process.env.LOCALAPPDATA ? [process.env.LOCALAPPDATA] : []), join(homedir(), '.local', 'state')])
export function socketPath() {
  if (process.env.HC_SOCKET) return process.env.HC_SOCKET
  for (const state of stateDirs()) {
    try { const p = readFileSync(join(state, 'herdr-core', coreSession(), 'core.lock'), 'utf8').trim(); if (p) return p } catch {}
  }
  return null
}
// Running = the socket is there. No core, or a stopped one, is simply "not here" (no error, no cards).
export const available = () => { const p = socketPath(); return Boolean(p) && existsSync(p) }

const MAX_FRAME = 64 * 1024 * 1024   // one line from the core; anything longer is not a terminal list
function notRunning() { return Object.assign(new Error('herdr-core is not running'), { code: 'ENOENT' }) }
export function rpc(method, params = {}, { timeoutMs = 5000 } = {}) {
  return new Promise((resolve, reject) => {
    const path = socketPath()
    if (!path) return reject(notRunning())
    const sock = createConnection(connectTarget(path))
    let buf = ''
    let settled = false
    // Every way out goes through here once: a reply, an error reply, a timeout, a socket error, the core hanging up.
    const finish = (err, value) => { if (settled) return; settled = true; clearTimeout(timer); sock.destroy(); err ? reject(err) : resolve(value) }
    const timer = setTimeout(() => finish(Object.assign(new Error(`herdr-core ${method}: no reply`), { code: 'ETIMEDOUT' })), timeoutMs)
    sock.setEncoding('utf8')
    sock.on('connect', () => sock.write(`${JSON.stringify({ jsonrpc: '2.0', id: 1, method, params })}\n`))
    sock.on('data', (chunk) => {
      buf += chunk
      let nl
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl); buf = buf.slice(nl + 1)
        let res
        try { res = JSON.parse(line) } catch { continue }
        if (!res || typeof res !== 'object' || Array.isArray(res)) return finish(Object.assign(new Error(`herdr-core ${method}: not a JSON-RPC reply`), { code: 'EPROTO' }))
        if (res.id !== 1) continue
        if (!res.error) return finish(null, res.result)
        const kind = res.error?.data?.kind
        // "not found" wording is what the board server looks for to move a card to Recently closed.
        return finish(Object.assign(new Error(kind === 'not_found' ? `terminal not found: ${params.terminal ?? ''}` : `herdr-core ${method}: ${res.error?.message}`), { kind }))
      }
      if (buf.length > MAX_FRAME) finish(Object.assign(new Error(`herdr-core ${method}: reply too large`), { code: 'EMSGSIZE' }))
    })
    sock.on('error', (err) => finish(err))
    // The core hung up before answering: say so now instead of waiting for the timeout (everything else collected in the
    // same round waits for this call).
    sock.on('close', () => finish(Object.assign(new Error(`herdr-core ${method}: connection closed before the reply`), { code: 'ECONNRESET' })))
  })
}

// ── terminal → board session ───────────────────────────────────────
const SHELLS = new Set(['zsh', 'bash', 'sh', 'fish', 'nu', 'dash', 'ksh', 'tcsh', 'csh', 'pwsh', 'powershell', 'cmd', 'elvish', 'xonsh'])
const progName = (t) => basename(String(t.foreground?.name || t.foreground?.argv?.[0] || t.argv?.[0] || '')).replace(/^-/, '').replace(/\.exe$/i, '').toLowerCase()
export const isShell = (t) => !t.status?.state && SHELLS.has(progName(t))
// The board's resume logic knows Claude Code as 'claude'.
const PROVIDER = { 'claude-code': 'claude' }
const DONE_FADES_TO_IDLE = new Set(['codex'])   // agents whose `done` turns into `idle` by itself (see toSession)
// `where` is "<space name> / <tab name>" (written by the app). The space name is everything before the last " / ".
const spaceName = (where) => { const i = String(where || '').lastIndexOf(' / '); return i > 0 ? where.slice(0, i) : null }

export function refOf(address) { return `${coreSession()}/${address}` }
export function splitRef(ref) {
  const i = ref.indexOf('/')
  if (i <= 0) throw new Error(`bad herdr-core ref: ${ref}`)
  return { core: ref.slice(0, i), terminal: ref.slice(i + 1) }
}

// screenAsk: what the screen of a terminal without a reported status is waiting for ('trust' = the agent's folder-trust
// prompt, shown before the agent is up and so before it can report anything). See trustWaiting.
export function toSession(t, { sid = null, screenAsk = null } = {}) {
  const st = t.status?.state
  let status = st ? (st === 'error' ? 'blocked' : ['working', 'blocked', 'done', 'idle'].includes(st) ? st : 'unknown') : isShell(t) ? 'shell' : 'unknown'
  if (status === 'unknown' && !st && screenAsk === 'trust') status = 'blocked'
  // The app records the last turn the person has looked at (label herdr.seen); whosup records its own when a card is
  // opened from the board (label whosup.seen — see focus). A finished turn already seen is not waiting any more, the
  // same way a herdr pane goes from finished to idle once it has been looked at.
  const turn = Number.isSafeInteger(t.turn) && t.turn > 0 ? t.turn : 0
  // A seen turn ahead of the current one was written for a program that is no longer there (its count started over):
  // such a label is left out by itself, so it cannot cancel the other label when that one is good.
  const seenTurn = Math.max(...['herdr.seen', 'whosup.seen'].map((k) => Number(t.labels?.[k])).filter((n) => Number.isSafeInteger(n) && n <= turn), -1)
  if (status === 'done' && turn > 0 && seenTurn >= turn) status = 'idle'
  // Some agents report `done` only for a moment and are `idle` again right after (Codex, measured: 2 s). The turn they
  // finished is still one nobody has looked at, so the card keeps saying so until it is seen — the same rule as above,
  // read from the other side. Only for agents seen to do that: an agent that keeps `done` until it is looked at
  // (Claude Code) is `idle` with a new turn when the person stopped it halfway, and that is not an answer.
  else if (status === 'idle' && turn > 0 && seenTurn < turn && DONE_FADES_TO_IDLE.has(t.status?.app)) status = 'done'
  const cwd = t.foreground?.cwd || t.cwd || ''
  const space = t.labels?.['herdr.space'] || ''
  const title = t.title && !['Claude Code', ''].includes(t.title) && st ? t.title : t.name || basename(cwd.replace(/\/+$/, '')) || t.address
  const waiting = status === 'done' || status === 'blocked'
  return {
    runtime: name,
    runtime_ref: refOf(t.address),
    provider_session: sid,
    cwd,
    project: basename(cwd.replace(/\/+$/, '')) || '-',
    title,
    pane_label: t.name || null,
    provider: st ? (PROVIDER[t.status.app] || t.status.app || null) : null,
    status,
    attentionTimestamp: waiting && t.status_ms ? new Date(t.status_ms).toISOString() : null,
    archived: false,
    fields: {
      lastStatus: { working: 'running', blocked: 'error', done: 'idle', idle: 'idle', shell: 'shell' }[status] || 'unknown',
      requiresAttention: waiting,
      attentionReason: status === 'done' ? 'finished' : status === 'blocked' ? 'blocked' : null,
      lastUserMessageAt: null,
      title,
      desk: `${DESK_PREFIX}${space}`,
      deskLabel: (space && spaceName(t.labels?.where)) || (space ? space : LOOSE_LABEL),
      tab: t.labels?.['herdr.tab'] || null,
      statusKind: t.status?.kind || (!st && status === 'blocked' ? 'trust' : null),   // 'trust' = read from the screen, not reported
      statusMsg: t.status?.msg || null,
      failed: st === 'error',
      turn,
      // The same finished turn is one event however the core words it (done, then idle): the collector keeps its
      // waiting-since time while this stays the same.
      // Without a turn count there is nothing to tell two finished turns apart by: no key, the time decides as before.
      attentionKey: status === 'done' && turn > 0 ? `done:${turn}` : null,
      // The same address can be handed to a new terminal later; this tells the two apart.
      incarnation: t.created_ms != null ? String(t.created_ms) : null,
    },
  }
}
// Row key of a stored row (the collector and the board ask this instead of cutting the ref).
export function deskOf(row) {
  try { return JSON.parse(row.fields_json || '{}').desk || DESK_PREFIX } catch { return DESK_PREFIX }
}
export function deskLabelOf(row) {
  try { return JSON.parse(row.fields_json || '{}').deskLabel || LOOSE_LABEL } catch { return LOOSE_LABEL }
}

// ── which conversation runs in a terminal ───────────────────────────
// Claude Code keeps one small file per running process: <config>/sessions/<pid>.json with its current conversation id.
// A terminal's agent is the terminal's program or one of its children (wrappers start it as a child), so the id is found
// by pid. Nothing is guessed from the folder: with several agents in one folder that picked the wrong conversation.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const claudeSessionsDir = () => join(dirname(process.env.CLAUDE_PROJECTS_DIR || join(homedir(), '.claude', 'projects')), 'sessions')
function sidOfPid(pid) {
  try { const o = JSON.parse(readFileSync(join(claudeSessionsDir(), `${pid}.json`), 'utf8')); return UUID.test(o.sessionId || '') ? o.sessionId : null } catch { return null }
}
// Only real options count: `--resume <id>`, `-r <id>`, `--session-id <id>` (or `=<id>`) as arguments of their own.
// A shell line (zsh -ic "claude --resume <id>") is read too, but only the part before any quote — a quoted prompt that
// happens to mention "--resume <id>" is text, not an option.
const SID_FLAGS = ['--resume', '-r', '--session-id']
function sidFromWords(words) {
  for (let i = 0; i < words.length; i++) {
    if (SID_FLAGS.includes(words[i]) && UUID.test(words[i + 1] || '')) return words[i + 1]
    const m = /^(?:--resume|--session-id)=(.+)$/.exec(words[i])
    if (m && UUID.test(m[1])) return m[1]
  }
  return null
}
export function sidFromArgv(argv = []) {
  const direct = sidFromWords(argv)
  if (direct) return direct
  const c = argv.findIndex((a, i) => i > 0 && /^-[a-z]*c$/.test(a))
  if (c < 0 || typeof argv[c + 1] !== 'string' || !SHELLS.has(basename(String(argv[0])).replace(/^-/, ''))) return null
  return sidFromWords(argv[c + 1].split(/['"\\`$]/)[0].trim().split(/\s+/))
}
let psCache = { at: 0, kids: null }   // kids: a promise, so terminals looked up at the same moment share one ps run
function childMap() {
  // Windows: no ps. Not looked up there (REPORT 15): the id is read from the argv below instead.
  if (isWindows()) return Promise.resolve(new Map())
  if (psCache.kids && Date.now() - psCache.at < 5000) return psCache.kids
  const kids = new Promise((resolve) => execFile('/bin/ps', ['-axo', 'pid=,ppid='], { encoding: 'utf8', timeout: 4000, killSignal: 'SIGKILL' }, (err, out) => {
    const map = new Map()
    for (const line of (err ? '' : out).split('\n')) { const m = line.trim().match(/^(\d+)\s+(\d+)$/); if (!m) continue; const p = Number(m[2]); if (!map.has(p)) map.set(p, []); map.get(p).push(Number(m[1])) }
    resolve(map)
  }))
  psCache = { at: Date.now(), kids }
  return kids
}
// Looked up from the terminal's current processes every time: a pid remembered from before would keep answering with
// the old conversation after another program took the terminal. Only for Claude Code — the registry is Claude's.
async function sidOf(t) {
  if (!t.status?.state || PROVIDER[t.status.app] !== 'claude') return null
  const roots = [t.foreground?.pid, t.pid].filter((p) => Number.isInteger(p))
  for (const pid of roots) { const sid = sidOfPid(pid); if (sid) return sid }
  const kids = await childMap()
  const seen = new Set(roots)
  for (let layer = roots, depth = 0; layer.length && depth < 6; depth++) {
    const next = []
    for (const p of layer) for (const c of kids.get(p) || []) { if (seen.has(c)) continue; seen.add(c); next.push(c); const sid = sidOfPid(c); if (sid) return sid }
    layer = next
  }
  return sidFromArgv(t.foreground?.argv) || sidFromArgv(t.argv)
}

// ── rows the person switched off ────────────────────────────────────
// Turning a row off closes its space and ends its terminals. The row is remembered here (name and folder) so the board
// can offer to turn it back on, the same way a stopped herdr session stays on the list.
const OFF_PATH = () => join(STATE_DIR, 'core-off.json')
export function offDesks() { try { return JSON.parse(readFileSync(OFF_PATH(), 'utf8')) || {} } catch { return {} } }
function saveOff(o) { mkdirSync(dirname(OFF_PATH()), { recursive: true }); writeFileSync(OFF_PATH(), JSON.stringify(o)) }

// ── a wait the core cannot report ───────────────────────────────────
// An agent asks "do you trust this folder?" before it is up, so the core has no status for that terminal and the card
// would sit there as "unknown" while the agent waits. Only for such terminals (a program that is not a shell and reports
// nothing) the screen is read, and only that one prompt counts — judged by the same rule the herdr cards use.
// Nothing else is guessed from the screen. Read at most every few seconds per terminal; a failed read means "no".
const trustSeen = new Map()   // "<address>:<created_ms>" → { at, waiting, pending }
const TRUST_TTL_MS = 4000
export const _resetScreenCache = () => trustSeen.clear()   // tests
async function trustWaiting(t) {
  if (t.status?.state || isShell(t)) return false
  const key = `${t.address}:${t.created_ms}`
  const hit = trustSeen.get(key)
  if (hit?.pending) return hit.pending   // a read is on its way: collections that overlap share it
  if (hit && Date.now() - hit.at < TRUST_TTL_MS) return hit.waiting
  const entry = { at: 0, waiting: false, pending: null }
  entry.pending = (async () => {
    let waiting = false
    try { waiting = isTrustScreen((await rpc('terminal.read', { terminal: t.address, lines: 0 }, { timeoutMs: 1500 })).text || '') } catch {}
    // Only if this is still the entry in use (the terminal may have gone, or the cache been cleared, meanwhile).
    if (trustSeen.get(key) === entry) Object.assign(entry, { at: Date.now(), waiting, pending: null })
    return waiting
  })()
  trustSeen.set(key, entry)
  return entry.pending
}

// ── listing ─────────────────────────────────────────────────────────
export async function listTerminals() { return (await rpc('terminal.list', {})).terminals || [] }
export async function listSnapshotAsync() {
  const terminals = (await listTerminals()).filter((t) => t.state === 'live' && !String(t.address).includes('/'))   // this machine only
  const busy = new Set(switching)   // rows being switched when this list was read (not when it is worked through, below)
  const keys = new Set(terminals.map((t) => `${t.address}:${t.created_ms}`))
  for (const k of trustSeen.keys()) if (!keys.has(k)) trustSeen.delete(k)
  const sessions = await Promise.all(terminals.map(async (t) => toSession(t, { sid: await sidOf(t), screenAsk: (await trustWaiting(t)) ? 'trust' : null })))
  // A row that was switched off is on again only when a terminal created after the switch-off shows up in it.
  // A list read just before the switch-off still holds the old terminals and must not undo it (seen with the real app:
  // the regular collection raced the switch-off and the row was forgotten).
  const off = offDesks()
  let changed = false
  for (const d of Object.keys(off)) {
    if (busy.has(d) || switching.has(d)) continue   // was (or is) being switched: a terminal that turned up meanwhile is ended with the rest
    const since = Date.parse(off[d].at) || 0
    if (terminals.some((t) => `${DESK_PREFIX}${t.labels?.['herdr.space'] || ''}` === d && Number(t.created_ms) > since)) { delete off[d]; changed = true }
  }
  if (changed) saveOff(off)
  return { sessions, unreachable: [], stopped: Object.keys(off) }
}
// What the collector gets. null = no core here (skip quietly). A core that is there but did not answer keeps every
// card as it was ("can't check"), the same promise the herdr runtime makes for a session it could not read.
export async function snapshotRuntime() {
  const base = { name, FIELDS, TRACKS_GONE, IDLE_AFTER_WORK_IS_DONE, AGENT_CHANGE_IS_NEW, deskOf }
  // Which rows the person switched off is written on this machine, not asked from the core: it holds while the core is away.
  const heldAll = () => ({ sessions: [], unreachable: [LOOSE_LABEL], stopped: Object.keys(offDesks()), holdAll: true })
  if (!available()) return { ...base, absent: true, listSnapshot: heldAll }
  let snap, err
  try { snap = await listSnapshotAsync() } catch (e) { err = e }
  return { ...base, snap, err, listSnapshot: () => snap || heldAll() }
}

// ── change events ───────────────────────────────────────────────────
// One subscription on the core socket; any event means "collect now". Without it the regular collection still runs.
let watch = null
export function watchEvents(onChange) {
  if (process.env.WHOSUP_NO_EVENTS === '1') return
  const path = socketPath()
  if (!path || !existsSync(path)) { stopWatching(); return }
  if (watch && watch.path === path && !watch.sock.destroyed) return
  stopWatching()
  const sock = createConnection(connectTarget(path))
  const w = { sock, path }
  watch = w
  let buf = ''
  sock.setEncoding('utf8')
  sock.on('connect', () => sock.write(`${JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'events.subscribe', params: {} })}\n`))
  sock.on('data', (chunk) => {
    buf += chunk
    let i; let hit = false
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i); buf = buf.slice(i + 1)
      let msg
      try { msg = JSON.parse(line) } catch { continue }
      if (msg?.method === 'event') hit = true
      // The core refused the subscription: let go, the next collection asks again.
      else if (msg?.id === 1 && msg.error) { sock.destroy(); return }
    }
    if (buf.length > MAX_FRAME) { sock.destroy(); return }
    if (hit) onChange(name)
  })
  const drop = () => { if (watch === w) watch = null }
  sock.on('error', drop); sock.on('close', drop)
}
export function stopWatching() { watch?.sock.destroy(); watch = null }

// ── screen text ─────────────────────────────────────────────────────
export async function readScreen(ref, lines = 60) {
  return (await rpc('terminal.read', { terminal: splitRef(ref).terminal, lines }, { timeoutMs: 4000 })).text || ''
}

// ── the Herdr app window ────────────────────────────────────────────
export const appBin = () => process.env.HERDR_APP_BIN || 'herdr-app'
export const appName = () => process.env.HERDR_APP_NAME || 'Herdr'
// Resolves { ok, out }. ok=false with code 'no_app' (command not installed) | 'no_window' (the app is not open) | 'failed'.
function app(args, { timeout = 5000 } = {}) {
  return new Promise((resolve) => {
    const [file, argv] = commandFor(appBin(), args)
    execFile(file, argv, { encoding: 'utf8', timeout, killSignal: 'SIGKILL', maxBuffer: 8 * 1024 * 1024 }, (err, stdout, stderr) => {
      if (!err) return resolve({ ok: true, out: stdout })
      const text = `${stderr || ''}${err.message || ''}`
      resolve({ ok: false, code: err.code === 'ENOENT' ? 'no_app' : /no Herdr window/i.test(text) ? 'no_window' : 'failed', message: text.trim().split('\n')[0].slice(0, 300) })
    })
  })
}
const appDo = (command, args = {}) => app(['do', command, JSON.stringify(args)])
// Spaces of the open window: [{ id, name, folder, terminals: [{ terminal, pane, tab }] }], or null when there is no window.
export async function appSpaces() {
  const r = await app(['ls'])
  if (!r.ok) return null
  try {
    return (JSON.parse(r.out).spaces || []).map((s) => ({ id: s.id, name: s.name, folder: s.folder || null,
      terminals: (s.tabs || []).flatMap((t) => (t.terminals || []).map((x) => ({ terminal: x.terminal, pane: x.pane, tab: t.id }))) }))
  } catch { return null }
}

// ── jump ────────────────────────────────────────────────────────────
// Bringing an app forward and opening a terminal window are borrowed from the herdr runtime (same rules, same settings).
// Kept in one place so tests can swap them out instead of touching real windows.
const windows = { raiseApp: herdr.raiseApp, openWindowRunning: herdr.openWindowRunning }
export const _setWindowOps = (ops) => Object.assign(windows, ops)
let latestClick = 0
// expect = the terminal the card was made for (its created_ms). The core hands an address to a new terminal once the old
// one is gone: a card that has not caught up must not open, type into or end whatever lives at that address now.
// ("not found" is the wording the board server looks for to move the card to Recently closed.)
const live = async (terminal, expect = null) => {
  const t = await rpc('terminal.get', { terminal })
  if (!t || t.state !== 'live') throw new Error(`terminal not found: ${terminal} (finished)`)
  if (expect != null && String(t.created_ms) !== String(expect)) throw new Error(`terminal not found: ${terminal} (that address belongs to another terminal now)`)
  return t
}
// The terminal a card points at — only for cards of the core this whosup is talking to.
const terminalOf = (ref) => {
  const r = splitRef(ref)
  if (r.core !== coreSession()) throw new Error(`terminal not found: ${ref} (a card of another core)`)
  return r.terminal
}
// Type a command into a terminal that is at a shell prompt (resume, start an agent).
async function typeInto(t, text) {
  if (!isShell(t)) throw new Error(`${t.address} is not at a shell prompt`)
  await rpc('terminal.send', { terminal: t.address, text })
}
// Show the terminal in the app (any space, any tab) and bring the app forward. If no pane shows it yet the app is asked
// to give it one. Without an open app window the terminal is opened in a terminal window instead (`hc attach`).
// raise:false = the click came from a browser that is not in front of this screen: move the pane, leave windows alone.
async function show(terminal, { raise = true, split = 0 } = {}) {
  let r = await appDo('pane.focus', { terminal })
  if (!r.ok && r.code === 'failed') { const kept = await appDo('terminal.keep', { terminal }); if (kept.ok) r = await appDo('pane.focus', { terminal }) }
  if (r.ok) {
    if (raise === false) return 'skipped'
    return windows.raiseApp(appName(), split)
  }
  if (raise === false) return 'skipped'
  const hc = process.env.HC_BIN || 'hc'
  // The new window starts with the person's own environment, not this server's. Whatever tells `hc` where this core is
  // goes along, so it attaches to the core the card came from (and does not start another one somewhere else).
  // The session name and the socket this click talked to are always spelled out (the window's own shell may point `hc`
  // at another core); the state folders only when this server was given them. XDG_STATE_HOME is where this file looks for
  // core.lock on every system (stateDirs), so it goes along everywhere. XDG_RUNTIME_DIR is a POSIX login-session folder:
  // on Windows it is not this server's to hand on (a stray value inherited from some tool would point `hc` at a path
  // that means nothing there), and the socket is already spelled out.
  const sock = socketPath()
  const xdg = isWindows() ? ['XDG_STATE_HOME'] : ['XDG_STATE_HOME', 'XDG_RUNTIME_DIR']
  const env = { HC_SESSION: coreSession(), ...(sock ? { HC_SOCKET: sock } : {}),
    ...Object.fromEntries(xdg.filter((k) => process.env[k]).map((k) => [k, process.env[k]])) }
  // Windows has no /usr/bin/env: the variables go to the window as PowerShell $env: lines (herdr.openWindowRunning).
  if (isWindows()) return windows.openWindowRunning([hc, 'attach', terminal], `core-${terminal}`, env)
  const argv = ['/usr/bin/env', ...Object.entries(env).map(([k, v]) => `${k}=${v}`), hc, 'attach', terminal]
  return windows.openWindowRunning(argv, `core-${terminal}`)
}
export const __showForTest = (terminal, opts) => show(terminal, opts)   // tests: the window step alone
export async function focus(ref, opts = {}) {
  const terminal = terminalOf(ref)
  const { run = null, seq } = opts
  // superseded(): the board server's own word on it — it sees the clicks of every runtime, this file only its own.
  const lost = () => !run && Number.isFinite(seq) && (seq < latestClick || opts.superseded?.() === true)
  const skipped = { session: LOOSE_LABEL, pane: terminal, client: 'running', window: 'superseded' }
  if (lost()) return skipped
  if (Number.isFinite(seq)) latestClick = Math.max(latestClick, seq)
  const t = await live(terminal, opts.incarnation)
  // A newer click arrived while this one was looking the terminal up: it wins, this one moves nothing.
  if (lost()) return skipped
  if (run) await typeInto(t, run)
  const window = await show(terminal, opts)
  // Opening a finished card from the board counts as having looked at it (whosup's own label; the app's is left alone).
  // "Finished" is whatever the card showed as finished: toSession decides (an agent can be idle again and still have
  // a turn nobody looked at). seen: true = written, false = could not be written (the card stays "finished"), null = nothing to write.
  let seen = null
  if (!run && toSession(t).status === 'done') { try { seen = await markSeen(terminal, t.created_ms) } catch { seen = false } }
  return { session: (t.labels?.['herdr.space'] && spaceName(t.labels?.where)) || LOOSE_LABEL, pane: terminal, client: 'running', window, seen }
}
// Writes for one terminal go one after another, and each reads the terminal again just before writing: the turn may have
// moved on while the window was being shown, and a click that finishes late must not put an older turn back.
const seenWrites = new Map()   // "<address>:<created_ms>" → the write in progress
function markSeen(terminal, created) {
  const key = `${terminal}:${created}`
  const write = async () => {
    const t = await rpc('terminal.get', { terminal })
    if (!t || t.state !== 'live' || t.created_ms !== created || toSession(t).status !== 'done') return false
    await rpc('terminal.label', { terminal, labels: { 'whosup.seen': String(t.turn) } })
    return true
  }
  const mine = (seenWrites.get(key) || Promise.resolve()).then(write, write)
  const tail = mine.catch(() => {})
  seenWrites.set(key, tail)
  tail.then(() => { if (seenWrites.get(key) === tail) seenWrites.delete(key) })
  return mine
}
export const warmClick = () => {}

// ── close one terminal ──────────────────────────────────────────────
// With the app open, close its pane (the app ends the terminal and tidies the tab). Otherwise end the terminal directly.
export async function closePane(ref, { incarnation = null } = {}) {
  const terminal = terminalOf(ref)
  await live(terminal, incarnation)   // the card's own terminal, still there — not a newer one at the same address
  const pane = (await appSpaces())?.flatMap((s) => s.terminals).find((x) => x.terminal === terminal)?.pane
  if (pane && (await appDo('pane.close', { pane })).ok) return { pane: terminal }
  await rpc('terminal.kill', { terminal })
  return { pane: terminal }
}

// ── new terminal with a command typed in ────────────────────────────
// Wait for a live terminal that was not there before (the app's replies are not relied on).
// "Was not there" is told by address and creation time together (an address can be handed out again).
const keyOf = (t) => `${t.address}:${t.created_ms}`
async function newTerminal(before, match = () => true, tries = 24) {
  for (let i = 0; i < tries; i++) {
    const t = (await listTerminals()).find((x) => x.state === 'live' && !before.keys.has(keyOf(x)) && match(x))
    if (t) return t
    await sleep(125)
  }
  return null
}
const existing = async () => {
  const all = await listTerminals()
  return { keys: new Set(all.map(keyOf)), spaces: new Set(all.map((t) => t.labels?.['herdr.space']).filter(Boolean)) }
}
// Creating goes one at a time: the new terminal is recognised as "the one that was not there before", which only holds
// while nothing else of ours is being created (two rows switched on together took each other's terminal). A terminal the
// person opens in the app in that same moment can still be taken for it — the match narrows that to the same space.
let creating = Promise.resolve()
const oneAtATime = (fn) => { const run = creating.then(() => fn()); creating = run.catch(() => {}); return run }
// desk: a `core:<space id>` row. With the app open the terminal is a new tab of that space; without it (or for the row
// of terminals outside any space) it is started straight on the core.
export const newSession = (o) => oneAtATime(() => openTerminal(o))
async function openTerminal({ session: desk, cwd, command, raise = true }) {
  if (!isDesk(desk)) throw Object.assign(new Error(`invalid herdr-core row: ${String(desk).slice(0, 60)}`), { code: 'bad_session' })
  if (!cwd || !existsSync(cwd)) throw herdr.cwdMissing(cwd)
  const space = spaceOf(desk)
  const before = await existing()
  let t = null
  if (space && (await appDo('tab.new', { space, folder: cwd })).ok) t = await newTerminal(before, (x) => x.labels?.['herdr.space'] === space)
  if (!t) t = await rpc('terminal.run', { cwd })
  if (command) await rpc('terminal.send', { terminal: t.address, text: command })
  const window = await show(t.address, { raise })
  return { session: desk, pane: t.address, client: 'running', window }
}

// ── turn a row off and on ───────────────────────────────────────────
export const validSessionName = isDesk
const switching = new Set()   // rows being turned off or on right now
export async function stopSession(desk) {
  if (!isDesk(desk)) throw Object.assign(new Error('invalid herdr-core row'), { code: 'bad_session' })
  const space = spaceOf(desk)
  // The row of terminals outside any space is not a space: there is nothing to close as a whole.
  if (!space) throw Object.assign(new Error('that row cannot be switched off'), { code: 'bad_session' })
  if (switching.has(desk)) throw Object.assign(new Error('that row is already being switched'), { code: 'busy' })
  switching.add(desk)
  let at = null
  const alive = async () => (await listTerminals()).filter((x) => x.state === 'live' && (x.labels?.['herdr.space'] || '') === space)
  try {
    const mine = await alive()
    const info = (await appSpaces())?.find((s) => s.id === space)
    const label = info?.name || spaceName(mine[0]?.labels?.where) || LOOSE_LABEL
    const folder = info?.folder || mine[0]?.cwd || null
    if (!mine.length && !info) return { session: desk, already: true }
    // The row is written down as off before anything ends: terminals ending make the board collect right away, and a
    // collection that does not know the row is off counts them as closed instead of keeping them for turning back on.
    at = new Date().toISOString()
    saveOff({ ...offDesks(), [desk]: { label, folder, at } })
    // The app closes the space and ends its terminals in one step; anything still alive (or no app) is ended on the core.
    if (info) await appDo('space.close', { id: space, confirmed: true })
    for (const t of await alive()) { try { await rpc('terminal.kill', { terminal: t.address }) } catch {} }
    let left = await alive()
    for (let i = 0; left.length && i < 10; i++) { await new Promise((r) => setTimeout(r, 200)); left = await alive() }
    if (left.length) throw Object.assign(new Error(`${left.length} terminal(s) did not stop`), { code: 'stop_failed' })
    return { session: desk }
  } catch (e) {
    const off = offDesks()
    // The row is not off after all. Terminals that did end before the failure are counted as closed by the next
    // collection: each one can still be resumed from Recently closed.
    if (at && off[desk]?.at === at) { delete off[desk]; saveOff(off) }
    throw e
  } finally { switching.delete(desk) }
}
// commands: what to type into the new terminals, one each ([{ id, cwd, command }]) — the conversations that were open
// when the row was turned off. The first goes into the space's first terminal when that is its folder, the rest into
// new tabs. Returns which of them were opened (done) and which could not be (failed), by the caller's id.
export async function startSession(desk, _cwd, { raise = true, commands = [] } = {}) {
  if (!isDesk(desk)) throw Object.assign(new Error('invalid herdr-core row'), { code: 'bad_session' })
  if (switching.has(desk)) throw Object.assign(new Error('that row is already being switched'), { code: 'busy' })   // a double click must not make two spaces
  const was = offDesks()[desk]
  if (!was) throw Object.assign(new Error('that row is not switched off'), { code: 'bad_session' })
  switching.add(desk)
  try { return await oneAtATime(() => bringBack(desk, was, { raise, commands })) } finally { switching.delete(desk) }
}
async function bringBack(desk, was, { raise, commands }) {
  const folder = [was.folder, commands[0]?.cwd, homedir()].find((d) => d && existsSync(d))
  const before = await existing()
  let first = null
  const made = await appDo('space.new', { ...(was.label && was.label !== LOOSE_LABEL ? { name: was.label } : {}), folder })
  // The space's first terminal: one that was not there, in a space that was not there.
  if (made.ok) first = await newTerminal(before, (x) => Boolean(x.labels?.['herdr.space']) && !before.spaces.has(x.labels['herdr.space']))
  if (!first) first = await rpc('terminal.run', { cwd: folder })
  // From here on the row is on again (its space exists): whatever goes wrong with one conversation is reported for that
  // conversation, and the switched-off record goes — a second try must not make a second space.
  const newDesk = `${DESK_PREFIX}${first.labels?.['herdr.space'] || ''}`
  const opened = [], done = [], failed = []
  for (const [i, c] of commands.entries()) {
    try {
      // A conversation is resumed in the folder it ran in. The first terminal is used only when that is its folder.
      const cwd = c.cwd && existsSync(c.cwd) ? c.cwd : null
      if (i === 0 && (!cwd || cwd === first.cwd)) { if (c.command) await rpc('terminal.send', { terminal: first.address, text: c.command }); opened.push(first.address) }
      else opened.push((await openTerminal({ session: newDesk, cwd: cwd || folder, command: c.command, raise: false })).pane)
      if (c.id != null) done.push(c.id)
    } catch { if (c.id != null) failed.push(c.id) }
  }
  // Read the list again: other rows may have been switched while this one was starting.
  const off = offDesks()
  if (off[desk]) { delete off[desk]; saveOff(off) }
  const window = await show(first.address, { raise })
  return { session: newDesk, client: 'started', window, opened, done, failed }
}

// Rows a new session can go to: every space of the open app window plus rows already on the board.
export async function targets(known = []) {
  const out = new Map(known.map((k) => [k.key, k]))
  for (const s of (await appSpaces()) || []) out.set(`${DESK_PREFIX}${s.id}`, { key: `${DESK_PREFIX}${s.id}`, label: s.name || s.id })
  return [...out.values()]
}
