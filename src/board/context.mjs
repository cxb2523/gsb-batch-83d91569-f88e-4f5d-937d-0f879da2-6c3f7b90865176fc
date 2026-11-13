// 칸마다 화면에 쓸 문맥: 기다리는 질문 원문(herdr 칸 화면), 마지막 요청(Claude 세션 기록), git 브랜치, 데스크 라벨.
// 전부 읽기 전용이고 짧게 캐시한다. 못 읽으면 null을 돌려주고 판은 그대로 뜬다.
import { execFile, execFileSync } from 'node:child_process'
import { closeSync, existsSync, fstatSync, openSync, readFileSync, readSync, readdirSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { herdrCommand } from '../runtime/herdr.mjs'
import * as core from '../runtime/core.mjs'

const cache = new Map()
// 뒤에서 새로 읽는 중인 키. 그동안은 옛 값을 그대로 준다(동기 실행으로 서버를 멈추지 않게).
const inflight = new Map()
function memo(key, ttlMs, fn, now = Date.now()) {
  const hit = cache.get(key)
  // 뒤에서 읽는 중이면 기다리지 않는다: 옛 값이 있으면 그것을, 없으면 아직 모름(null)을 준다.
  if (inflight.has(key)) return hit ? hit.value : null
  if (hit && now - hit.at < ttlMs) return hit.value
  let value = null
  try { value = fn() } catch { value = null }
  cache.set(key, { at: now, value })
  return value
}
export const clearContextCache = () => { cache.clear(); fileCache.clear() }
export const _cacheKeys = () => [...cache.keys()]   // 시험
// 비동기로 캐시를 채운다. 값이 신선하면 null, 아니면 읽고 있는 약속을 돌려준다(기다릴지는 부르는 쪽이 정한다).
function refresh(key, ttlMs, fn, now) {
  const hit = cache.get(key)
  if (hit && now - hit.at < ttlMs) return null
  let p = inflight.get(key)
  if (!p) {
    p = (async () => { let value = null; try { value = await fn() } catch { value = null } cache.set(key, { at: Math.max(now, Date.now()), value }) })().finally(() => inflight.delete(key))
    inflight.set(key, p)
  }
  return p
}
const run = (file, args, opts) => new Promise((resolve, reject) => execFile(file, args, { encoding: 'utf8', killSignal: 'SIGKILL', timeout: 5000, ...opts }, (err, out) => (err ? reject(err) : resolve(out))))
// 한 번에 도는 git 수를 묶는다(폴더가 많아도 프로세스를 한꺼번에 쏟지 않게).
let gitBusy = 0; const gitWait = []
async function gitSlot(fn) {
  if (gitBusy >= 6) await new Promise((r) => gitWait.push(r))
  gitBusy += 1
  try { return await fn() } finally { gitBusy -= 1; gitWait.shift()?.() }
}
// 파일이 그대로면(크기·수정 시각) 다시 읽지 않는다. 쉬는 칸의 대화 기록을 15초마다 4MB씩 다시 읽던 것을 없앤다.
const fileCache = new Map()
function byFile(kind, path, fn) {
  const st = statSync(path)
  const sig = `${st.size}:${st.mtimeMs}`
  const k = `${kind}:${path}`
  const hit = fileCache.get(k)
  if (hit && hit.sig === sig) return hit.value
  const value = fn()
  if (fileCache.size > 2000) fileCache.clear()
  fileCache.set(k, { sig, value })
  return value
}


// ── 칸 화면 글 ───────────────────────────────────────────────
export function readPane(session, pane, lines = 60) {
  const [file, argv] = herdrCommand(['pane', 'read', pane, '--source', 'detection', '--lines', String(lines)], session)
  return execFileSync(file, argv, { encoding: 'utf8', timeout: 4000, killSignal: 'SIGKILL' })
}

const RULE = /^[\s]*[─—-]{10,}\s*$/
const NOISE = /^\s*(❯|◆|📁|⏵⏵|⎿|✻|✽|✶|✳|✢|·\s*(Thinking|Working)|\?\s*for shortcuts|View Observations|✨ 30 Day|Get up to|https?:\/\/cmem\.ai)/
const ANSWER_OPTION = /^\s*(❯\s*)?\d+\.\s/

// Claude Code 화면의 아래쪽 입력줄·상태줄을 떼고 본문 줄만 남긴다.
export function bodyLines(text) {
  const lines = text.replace(/\r/g, '').split('\n')
  // 입력줄(❯)을 찾고 그 위의 괘선에서 자른다. 입력줄이 없으면 마지막 괘선, 그것도 없으면 전부.
  let end = lines.length
  let input = -1
  // 입력줄 = 괘선 바로 아래의 ❯ 줄. 객관식·폴더 신뢰 화면의 선택 커서(❯ 1. …, ❯ No, exit)는 입력줄이 아니다
  // (2026-11-08 3대 QA: 커서를 입력줄로 오인해 질문 상자 머리에서 잘라 question이 늘 비었다).
  for (let i = lines.length - 1; i >= 1; i--) if (/^\s*❯/.test(lines[i]) && RULE.test(lines[i - 1])) { input = i; break }
  // 입력줄이 없으면(질문·신뢰·승인 선택 화면) 자르지 않는다 — 질문은 마지막 괘선 아래에 있다.
  if (input >= 0) for (let i = input - 1; i >= 0; i--) {
    if (RULE.test(lines[i])) { end = i; break }
  }
  return lines.slice(0, end).map((l) => l.replace(/\s+$/, ''))
}

// 승인·질문 대기 칸: 화면 아래쪽에서 질문 문장을 찾는다. 선택지 번호줄은 질문이 아니다.
// 권한 상자(╭ │ ╰)는 "명령 — 승인?" 꼴로 줄인다.
const BOX = /^[\s│╭╰╮╯]+|[\s│]+$/g
const unbox = (l) => l.replace(BOX, '').replace(/^[⏺●]\s*/, '')
// 폴더 신뢰 화면의 고정 문구. 에이전트가 아직 뜨기 전이라 런타임이 상태를 알리지 못하는 대기다 —
// herdr-core 런타임은 상태 없는 터미널의 화면이 이 질문으로 읽힐 때만 '입력 필요'로 올린다(isTrustScreen).
export const TRUST_QUESTION = Object.freeze({ text: '이 폴더를 신뢰할까요? (Yes, I trust this folder)', kind: 'approval' })
// 폴더 신뢰 대화상자인가: 질문 줄(…trust…?) + 신뢰를 고르는 선택지 + 맨 아래의 Enter 안내가 함께 있을 때만.
// 선택 커서(❯ › >)와 번호는 떼고 본다 — 커서가 어느 선택지에 있어도 같은 화면이다. 낱말 하나가 아니라 구조를 보는
// 이유: 문서를 보여 주는 프로그램의 화면에 같은 문장이 있다고 걸리면 안 된다(herdr-core 카드는 이 판정으로 상태를 올린다).
// 확인한 화면: Claude Code 2.1("Yes, I trust this folder" / "Enter to confirm"), Codex 0.167("Trust and continue" / "enter continue").
const CURSOR = /^[\s❯›>▶]*(\d+\.\s*)?/
export function trustDialogOf(text) {
  const lines = String(text || '').replace(/\r/g, '').split('\n').map((l) => l.replace(/^[\s│╭╰╮╯]+|[\s│]+$/g, '')).filter(Boolean)
  const tail = lines.slice(-16)
  let hint = -1
  for (let i = tail.length - 1; i >= Math.max(0, tail.length - 3); i--) if (/^enter\b.{0,12}\b(confirm|continue)\b/i.test(tail[i])) { hint = i; break }
  if (hint < 0) return null
  const above = tail.slice(0, hint)
  const option = above.slice(-8).some((l) => /^(yes,?\s+)?(i\s+)?trust\b.{0,30}$/i.test(l.replace(CURSOR, '')))
  const asks = above.some((l) => /\btrust\b[^?]{0,80}\?/i.test(l)) && above.some((l) => /\b(folder|project|workspace|directory)\b/i.test(l))
  return option && asks ? TRUST_QUESTION : null
}
export const isTrustScreen = (text) => trustDialogOf(text) === TRUST_QUESTION
// #17 질문 문장과 종류: approval(권한 상자·폴더 신뢰) | question(그 밖의 물음).
export function questionOf(text) {
  const trust = trustDialogOf(text)   // 커서가 신뢰 선택지에 있으면 아래 줄 단위 규칙은 그 줄을 잡음으로 버린다
  if (trust) return trust
  const raw = bodyLines(text)
  const body = raw.map(unbox).filter((l) => l.trim() && !NOISE.test(l) && !/^[─╭╰╮╯]+$/.test(l))
  for (let i = body.length - 1; i >= 0; i--) {
    const l = body[i].trim()
    if (ANSWER_OPTION.test(l) || /^(Esc|Enter|Tab) /.test(l)) continue
    if (/Do you want to (proceed|make this edit|allow)/i.test(l)) {
      // 상자 안 명령: 상자 제목줄(Bash command / Edit file …) 다음 첫 비어 있지 않은 줄
      const head = body.slice(Math.max(0, i - 12), i)
      const titleIdx = head.findIndex((h) => /^(Bash command|Edit file|Write file|Create file|Read file|Tool use|Run)/i.test(h.trim()))
      const cmd = (titleIdx >= 0 ? head.slice(titleIdx + 1) : head).map((h) => h.trim()).find((h) => h && !/^(Bash command|Edit file|Write file)/i.test(h))
      return { text: cmd ? `${cmd.slice(0, 120)} — 승인할까요?` : '승인할까요?', kind: 'approval' }
    }
    if (/trust this folder/i.test(l)) return TRUST_QUESTION
    if (/^Enter to confirm/i.test(l)) {
      for (let k = i - 1; k >= Math.max(0, i - 12); k--) if (/[?？]/.test(body[k])) return { text: joinWrapped(body, k), kind: 'question' }
    }
    if (/[?？]$/.test(l) || /승인|진행할까|허용/i.test(l)) return { text: joinWrapped(body, i), kind: 'question' }
  }
  return null
}
export const extractQuestion = (text) => questionOf(text)?.text ?? null

// 끝난 칸: 마지막 ⏺ 문단(에이전트의 마지막 말)
export function extractLastSay(text) {
  const body = bodyLines(text)
  let start = -1
  for (let i = body.length - 1; i >= 0; i--) if (/^\s*[⏺●]\s/.test(body[i]) && !/^\s*[⏺●]\s+\S+\(/.test(body[i])) { start = i; break }
  // ⏺ 문단이 화면에 없으면(세션 시작 배너·긴 출력 뒤) 지어내지 않고 null — 판은 마지막 요청·제목으로 대신한다.
  if (start < 0) return null
  const out = [body[start].replace(/^\s*[⏺●]\s*/, '')]
  for (let i = start + 1; i < body.length && out.join(' ').length < 200; i++) {
    const l = body[i]
    if (!l.trim() || /^\s*[⏺●]/.test(l) || NOISE.test(l)) break
    out.push(l.trim())
  }
  return out.join(' ').replace(/\s+/g, ' ').trim().slice(0, 200) || null
}

// 화면 폭 때문에 줄바꿈된 문장을 위로 올라가며 한 문장으로 잇는다.
function joinWrapped(body, i) {
  const parts = [body[i].trim()]
  const indent = body[i].match(/^\s*/)[0].length
  for (let k = i - 1; k >= 0 && parts.length < 4; k--) {
    const l = body[k]
    // 객관식 질문 위의 탭 줄(☐ Color, ✔ Submit, ← → 화살표)은 질문 문장이 아니다
    if (!l.trim() || ANSWER_OPTION.test(l) || /[.!?。]$/.test(l.trim()) || /^\s*(←|[☐✔☒]\s)/.test(l)) break
    const own = l.match(/^\s*/)[0].length
    const starts = /^\s*[⏺●]/.test(l)
    if (own !== indent && !starts) break
    parts.unshift(l.replace(/^\s*[⏺●]\s*/, '').trim())
    if (starts) break
  }
  return parts.join(' ').replace(/\s+/g, ' ').slice(0, 200)
}

// 실패로 볼 신호(화면 아래쪽 20줄 안)
export function looksFailed(text) {
  const tail = bodyLines(text).slice(-20).join('\n')
  return /API Error|rate.?limit|429|overloaded|exit code [1-9]|command not found|Traceback|FAILED|✘|Error:/i.test(tail)
}

// 질문·승인을 기다리는 칸은 실패로 보지 않는다 — 기다리는 건 사람의 답이다.
// (2026-11-08 실측: 질문 바로 위 `⎿  Error: PreToolUse:AskUserQuestion hook error` 줄 때문에 입력 필요 칸이 실패로 떴다)
export function failedFor(text, status, question) {
  if (status === 'blocked' && question) return false
  return looksFailed(text)
}

function parsePane(text, status) {
  const asked = status === 'blocked' ? questionOf(text) : null
  const question = asked?.text ?? null
  return {
    question,
    ask_kind: asked?.kind ?? null,
    last_say: status === 'done' ? extractLastSay(text) : null,
    failed: failedFor(text, status, question),
  }
}
export function paneContext(session, pane, status, now = Date.now()) {
  return memo(`pane:${session}/${pane}:${status}`, 10000, () => parsePane(readPane(session, pane), status), now)
}

// herdr-core 칸: 코어가 질문·승인 문구를 직접 알려 준다(status.msg). 그것을 먼저 쓰고, 없을 때만 화면에서 찾는다.
// 문구 머리의 "answer: "·"approve "는 코어가 붙인 꼬리표라 뗀다. 승인은 herdr 칸과 같은 꼴("… — 승인할까요?")로 맞춘다.
export function coreQuestion(fields) {
  // 화면에서 읽어 올린 폴더 신뢰 대기: 이미 그 질문으로 확인한 것이라 화면을 다시 읽지 않고 같은 문구를 쓴다.
  if (fields?.statusKind === 'trust') return TRUST_QUESTION
  const msg = String(fields?.statusMsg || '').replace(/\s+/g, ' ').trim()
  if (!msg) return null
  if (fields.statusKind === 'permission') return { text: `${msg.replace(/^approve\s+/i, '').slice(0, 120)} — 승인할까요?`, kind: 'approval' }
  return { text: msg.replace(/^answer:\s*/i, '').slice(0, 200), kind: 'question' }
}
// 화면 캐시의 열쇠: 카드(행 id)와 턴까지 넣는다. 같은 주소를 새 터미널이 물려받거나 같은 터미널의 다음 턴이
// 같은 상태로 보일 때 앞 화면의 질문·답변이 새 카드에 붙지 않게.
const coreKey = (s) => {
  let turn = ''
  try { turn = JSON.parse(s.fields_json || '{}').turn ?? '' } catch {}
  return `pane:core:${s.id ?? s.runtime_ref}:${s.status}:${turn}`
}
// 화면 글(마지막 말·실패 신호)은 warmContext가 비동기로 읽어 둔 것만 본다 — 소켓 읽기라 동기로 읽을 길이 없다.
export function coreContext(s) {
  let f = {}
  try { f = JSON.parse(s.fields_json || '{}') } catch {}
  const screen = cache.get(coreKey(s))?.value || null
  const asked = s.status === 'blocked' ? coreQuestion(f) : null
  return {
    question: asked?.text ?? screen?.question ?? null,
    ask_kind: asked?.kind ?? screen?.ask_kind ?? null,
    last_say: screen?.last_say ?? null,
    // 실패는 코어가 오류라고 알린 칸뿐이다. 화면의 오류 낱말로 실패를 추측하지 않는다(답변에 "Fixed API Error"가 있다고 실패가 아니다).
    failed: Boolean(f.failed),
  }
}

// 판을 계산하기 전에 칸 화면·git 브랜치를 비동기로 미리 읽어 캐시에 넣는다. 그 뒤의 computeBoard는 캐시만 본다.
// 칸 화면(질문 원문)은 새 값을 기다린다. 브랜치는 기다리지 않는다 — 판은 바로 내주고(첫 화면이 git을 기다리지 않는다),
// 읽고 나서 값이 달라졌으면 onLate를 한 번 불러 화면이 다시 읽게 한다.
export async function warmContext(rows, now = Date.now(), onLate = null) {
  const jobs = []
  const late = []
  const cwds = new Set()
  // 코어 카드의 화면 캐시는 열쇠에 턴이 들어 있어 턴마다 새로 생긴다: 지금 판의 카드가 쓰지 않는 것은 버린다.
  const keep = new Set(rows.filter((s) => s.runtime === core.name).map(coreKey))
  for (const k of cache.keys()) if (k.startsWith('pane:core:') && !keep.has(k) && !inflight.has(k)) cache.delete(k)
  for (const s of rows) {
    if (s.runtime !== 'herdr' && s.runtime !== core.name) continue
    const live = !['stopped', 'gone', 'shell'].includes(s.status) && !s.unreachable
    if (live && ['blocked', 'done'].includes(s.status)) {
      if (s.runtime === core.name) jobs.push(refresh(coreKey(s), 10000, async () => parsePane(await core.readScreen(s.runtime_ref), s.status), now))
      else {
        const [session, pane] = s.runtime_ref.split('/')
        jobs.push(refresh(`pane:${session}/${pane}:${s.status}`, 10000, async () =>
          parsePane(await run(...herdrCommand(['pane', 'read', pane, '--source', 'detection', '--lines', '60'], session), { timeout: 4000 }), s.status), now))
      }
    }
    if (s.cwd && !cwds.has(s.cwd) && existsSync(s.cwd)) {
      cwds.add(s.cwd)
      const key = `branch:${s.cwd}`
      const known = cache.has(key)
      const before = cache.get(key)?.value
      const p = refresh(key, 60000, () => gitSlot(async () => {
        const quiet = { timeout: 5000 }
        const b = (await run('git', ['-C', s.cwd, 'branch', '--show-current'], quiet)).trim()
        if (!b) return null
        const dirty = (await run('git', ['-C', s.cwd, 'status', '--porcelain', '--untracked-files=no'], quiet)).trim() !== ''
        return dirty ? `${b}*` : b
      }), now)
      if (p) late.push(p.then(() => !known || cache.get(key)?.value !== before))
    }
  }
  if (late.length && onLate) Promise.all(late).then((changed) => { if (changed.some(Boolean)) onLate() }).catch(() => {})
  await Promise.all(jobs.filter(Boolean))
}

// ── Claude 세션 기록(jsonl)의 마지막 요청 ────────────────────
const projectsDir = () => process.env.CLAUDE_PROJECTS_DIR || join(homedir(), '.claude', 'projects')

export function findSessionFile(sessionId) {
  if (!sessionId || !/^[0-9a-f-]{36}$/i.test(sessionId)) return null
  const key = `file:${sessionId}`
  const file = memo(key, 300000, () => {
    const root = projectsDir()
    for (const dir of readdirSync(root)) {
      const p = join(root, dir, `${sessionId}.jsonl`)
      if (existsSync(p)) return p
    }
    return null
  })
  // 아직 없는 기록은 5분 동안 "없음"으로 굳히지 않는다 — 대화 id가 기록 파일보다 먼저 알려지는 경우(막 시작한 대화)
  // 마지막 요청이 5분 뒤에야 보였다. 10초 뒤 다시 찾는다.
  if (!file) { const hit = cache.get(key); if (hit && Date.now() - hit.at < 290000) hit.at -= 290000 }
  return file
}

function tailText(path, bytes) {
  const fd = openSync(path, 'r')
  try {
    const size = fstatSync(fd).size
    const len = Math.min(bytes, size)
    const buf = Buffer.alloc(len)
    readSync(fd, buf, 0, len, size - len)
    return buf.toString('utf8')
  } finally {
    closeSync(fd)
  }
}

export function lastPromptIn(text) {
  let last = null
  for (const line of text.split('\n')) {
    if (!line.startsWith('{') || !line.includes('"user"')) continue
    let o
    try { o = JSON.parse(line) } catch { continue }
    if (o.type !== 'user' || o.isMeta) continue
    const c = o.message?.content
    const t = (typeof c === 'string' ? c : Array.isArray(c) ? c.filter((x) => x?.type === 'text').map((x) => x.text).join(' ') : '').trim()
    if (!t || t.startsWith('<') || /^This session is being continued/.test(t) || /^claude --resume/.test(t)) continue
    last = { at: o.timestamp || null, text: t.replace(/\s+/g, ' ').slice(0, 200) }
  }
  return last
}

const promptOfFile = (file) => byFile('prompt', file, () => {
  for (const bytes of [262144, 4194304]) {
    const hit = lastPromptIn(tailText(file, bytes))
    if (hit) return hit
  }
  return null
})
export function lastPrompt(sessionId, now = Date.now()) {
  return memo(`prompt:${sessionId}`, 15000, () => {
    const file = findSessionFile(sessionId)
    return file ? promptOfFile(file) : null
  }, now)
}

// I-5 기록의 구조 표식: Claude는 재시도를 다 쓴 뒤 isApiErrorMessage 합성 줄을 남긴다. 마지막 대화 줄이 그것이면 실패다.
// 꼬리 끝에서 거꾸로 첫 대화 줄(user·assistant)만 본다. 그 뒤에 사람이 말했거나 정상 답이 왔으면 실패가 아니다.
export function apiErrorIn(text) {
  const lines = text.split('\n')
  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i]
    if (!l.startsWith('{')) continue
    let o
    try { o = JSON.parse(l) } catch { continue }
    if (o.type !== 'user' && o.type !== 'assistant') continue
    if (o.type === 'user' && (o.isMeta || o.toolUseResult)) continue
    return o.type === 'assistant' && o.isApiErrorMessage === true ? { kind: o.error || 'unknown', at: o.timestamp || null } : null
  }
  return null
}
export function lastApiError(sessionId, now = Date.now()) {
  return memo(`apierr:${sessionId}`, 15000, () => {
    const file = findSessionFile(sessionId)
    return file ? byFile('apierr', file, () => apiErrorIn(tailText(file, 65536))) : null
  }, now)
}

// ── git 브랜치 ───────────────────────────────────────────────
export function branchOf(cwd, now = Date.now()) {
  if (!cwd || !existsSync(cwd)) return null
  return memo(`branch:${cwd}`, 60000, () => {
    const quiet = { encoding: 'utf8', timeout: 5000, killSignal: 'SIGKILL', stdio: ['ignore', 'pipe', 'ignore'] }
    const b = execFileSync('git', ['-C', cwd, 'branch', '--show-current'], quiet).trim() // guard-ok: quiet에 timeout
    if (!b) return null
    const dirty = execFileSync('git', ['-C', cwd, 'status', '--porcelain', '--untracked-files=no'], quiet).trim() !== '' // guard-ok: quiet에 timeout
    return dirty ? `${b}*` : b
  }, now)
}


// ── 이어서 열기 대상 ─────────────────────────────────────────
// 판에 보인 대상과 버튼이 여는 대상은 이 함수 하나로 정한다(I-3). 서버도 누를 때 같은 함수로 다시 계산해 비교한다.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const KNOWN_AGENTS = ['claude', 'codex', 'gemini', 'opencode', 'cursor-agent', 'amp', 'aider', 'goose', 'qwen', 'pi', 'grok', 'droid']
// 실행 명령의 첫 단어가 알려진 에이전트면 그 이름, 래퍼(cco 등)처럼 모르는 명령이면 null.
export const cmdAgent = (cmd) => { const b = String(cmd || '').trim().split(/\s+/)[0].split('/').pop(); return KNOWN_AGENTS.includes(b) ? b : null }

function headText(path, bytes) {
  const fd = openSync(path, 'r')
  try { const buf = Buffer.alloc(Math.min(bytes, fstatSync(fd).size)); readSync(fd, buf, 0, buf.length, 0); return buf.toString('utf8') } finally { closeSync(fd) }
}
// 대화 줄(user·assistant)이 하나라도 있는 기록인가(#20). 요약·스냅숏만 있는 파일은 --resume으로 열어도 빈 대화다.
export function hasConversationLine(file) {
  const isConv = (text) => text.split('\n').some((l) => { if (!l.startsWith('{')) return false; try { const t = JSON.parse(l).type; return t === 'user' || t === 'assistant' } catch { return false } })
  try { return byFile('conv', file, () => isConv(headText(file, 65536)) || isConv(tailText(file, 65536))) } catch { return false }
}
function describe(file, sid, from) {
  const prompt = promptOfFile(file)
  return { sid, from, at: new Date(statSync(file).mtimeMs).toISOString(), prompt: prompt?.text ?? null }
}

// s: 세션 행(provider, provider_session, cwd). exclude: 다른 칸에서 지금 살아 있는 대화 id(#9). cmd: 실행 명령.
// 돌려주는 값 {sid, from:'pane'|'folder', at, prompt} 또는 null(새 대화로 시작).
export function resumeTarget(s, { exclude = new Set(), cmd = 'claude' } = {}) {
  // 재개 후보는 Claude 기록뿐이다. 실행 명령이나 칸의 공급자가 다른 에이전트면 그 id로 열지 않는다(#18).
  const agent = cmdAgent(cmd)
  if (agent && agent !== 'claude') return null
  if (s.provider && s.provider !== 'claude') return null
  const key = `resume:${s.provider_session || ''}:${s.cwd || ''}:${[...exclude].sort().join(',')}`
  return memo(key, 15000, () => {
    const own = s.provider_session
    if (UUID.test(own || '') && !exclude.has(own)) {
      const file = findSessionFile(own)
      if (file && hasConversationLine(file)) return describe(file, own, 'pane')
    }
    if (!s.cwd) return null
    const dir = join(projectsDir(), s.cwd.replace(/[^A-Za-z0-9]/g, '-'))
    if (!existsSync(dir)) return null
    const cands = readdirSync(dir).filter((f) => f.endsWith('.jsonl') && UUID.test(f.slice(0, -6)) && !exclude.has(f.slice(0, -6)))
      .map((f) => ({ sid: f.slice(0, -6), file: join(dir, f), mtime: statSync(join(dir, f)).mtimeMs }))
      .sort((a, b) => b.mtime - a.mtime)
    const hit = cands.find((c) => hasConversationLine(c.file))
    return hit ? describe(hit.file, hit.sid, 'folder') : null
  })
}
