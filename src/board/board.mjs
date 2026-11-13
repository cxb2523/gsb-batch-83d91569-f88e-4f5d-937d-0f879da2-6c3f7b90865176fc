import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { branchOf, coreContext, lastApiError, lastPrompt, paneContext, resumeTarget, warmContext } from './context.mjs'
import { capsOf, deskLabelOf, deskOf } from '../runtime/index.mjs'
import { getMeta } from '../db.mjs'
import { getSettings } from '../settings.mjs'

// 다른 칸에서 지금 살아 있는 대화 id(#9) — 이어서 열기가 그 대화를 두 번째 칸에서 열지 않게.
const LIVE = ['working', 'blocked', 'done', 'idle']
export function otherLiveSids(rows, exceptId) {
  return new Set(rows.filter((r) => r.id !== exceptId && !r.archived && LIVE.includes(r.status) && r.provider_session).map((r) => r.provider_session))
}
export const resumeFor = (rows, s, cmd) => resumeTarget(s, { exclude: otherLiveSids(rows, s.id), cmd })

export function startOfDay(now) {
  const d = new Date(now)
  d.setHours(0, 0, 0, 0)
  return d
}


// 손 든 칸 = 입력 필요(blocked)·답변 도착(done) 중 보관하지 않았고, 확인하지 않았거나 확인 뒤 미루기 시간이 지난 칸.
// 날짜와 무관하다(약속 1 — 자정을 넘겨도 사라지지 않는다).
// ttlMs: 확인 불가(unreachable=1)가 이보다 오래된 칸은 손 든 칸에서 내린다(#14). 칸은 판에 남는다.
export function attentionState(s, now, snoozeMs, ttlMs = Infinity) {
  // 서버가 꺼진 세션(unreachable=2)의 칸은 답할 에이전트가 없으니 손 든 칸으로 세지 않는다.
  if (!['blocked', 'done'].includes(s.status) || s.stashed_at || s.archived || s.unreachable === 2) return null
  if (s.unreachable === 1 && now.getTime() - new Date(s.updated_at).getTime() > ttlMs) return null
  if (!s.seen_at || (s.attention_since && s.seen_at < s.attention_since)) return 'raised'
  if (now.getTime() - new Date(s.seen_at).getTime() >= snoozeMs) return 'raised'
  return 'snoozed'
}

// 순번 하나: 실패 → 입력 필요 → 답변 도착, 각 무리 안에서 오래 기다린 순. 다음 1건·Enter·숫자키·알림이 모두 이것을 쓴다(약속 2).
export function orderAttention(cards) {
  const rank = (c) => (c.status === 'blocked' ? (c.failed ? 0 : 1) : 2)
  return [...cards].sort((a, b) => rank(a) - rank(b) || (a.attention_since || '').localeCompare(b.attention_since || '') || a.id - b.id)
}

export function collectHealth(db, now, cfg) {
  const okAt = getMeta(db, 'collect_ok_at')
  const errAt = getMeta(db, 'collect_err_at')
  const age = okAt ? Math.round((now.getTime() - new Date(okAt).getTime()) / 1000) : null
  const unreachable = (getMeta(db, 'collect_unreachable') || '').split(',').filter(Boolean)
  return {
    ok_at: okAt,
    age_sec: age,
    stale: age === null || age > cfg.stale_collect_sec,
    error: errAt && (!okAt || errAt > okAt) ? getMeta(db, 'collect_err') : null,
    error_at: errAt,
    error_kind: errAt && (!okAt || errAt > okAt) ? (getMeta(db, 'collect_err_kind') || 'failed') : null,
    unreachable,
    stopped: (getMeta(db, 'collect_stopped') || '').split(',').filter(Boolean),
  }
}

// 서버가 쓰는 판 계산: 칸 화면·git을 비동기로 먼저 읽어 두고(서버가 멈추지 않는다) 같은 규칙으로 계산한다.
export async function computeBoardAsync(db, opts = {}) {
  const now = opts.now || new Date()
  await warmContext(db.prepare('SELECT id, runtime, runtime_ref, status, unreachable, cwd, fields_json FROM session WHERE archived = 0').all(), now.getTime(), opts.onLate)
  return computeBoard(db, { ...opts, now })
}

// runtimes: 보여 줄 런타임 목록(null이면 전부). 세션판 서버는 기본 herdr만 보인다(Paseo는 기록으로만 남김).
export function computeBoard(db, { now = new Date(), withContext = true } = {}) {
  const today = startOfDay(now).toISOString()
  const cfg = getSettings(db)
  const snoozeMs = cfg.seen_snooze_min * 60000
  const ttlMs = cfg.unreachable_ttl_h * 3600000
  const sessions = db.prepare('SELECT * FROM session WHERE archived = 0').all()
  const STALE_MS = cfg.stale_days * 86400000
  // 칸 문맥(라벨·브랜치·질문 원문·마지막 요청)은 아는 런타임(herdr, herdr-core)의 칸에만 읽는다. 못 읽으면 null.
  const contextOf = (s) => {
    if (!withContext || !capsOf(s)) return {}
    const [desk, pane] = s.runtime_ref.split('/')
    const live = !['stopped', 'gone', 'shell'].includes(s.status) && !s.unreachable
    const ctx = live && ['blocked', 'done'].includes(s.status) ? (s.runtime === 'herdr' ? paneContext(desk, pane, s.status, now.getTime()) : coreContext(s)) : null
    const prompt = lastPrompt(s.provider_session, now.getTime())
    // 실패는 기록의 구조 표식이 먼저(I-5). 화면 정규식은 표식이 없는 공급자용으로 질문을 읽지 못한 blocked 칸에만 남는다(I-1).
    const apiErr = ['blocked', 'done'].includes(s.status) ? lastApiError(s.provider_session, now.getTime()) : null
    const lastAt = prompt?.at || s.last_user_msg_at || s.attention_since || null
    const activityAt = lastAt || s.first_seen
    return {
      label: s.pane_label || null,
      branch: branchOf(s.cwd, now.getTime()),
      question: ctx?.question ?? null,
      ask_kind: ctx?.ask_kind ?? null, // approval | question (#17)
      last_say: ctx?.last_say ?? null,
      failed: Boolean(ctx?.failed) || Boolean(apiErr && !ctx?.question),
      fail_kind: apiErr?.kind ?? null,
      last_prompt: prompt?.text ?? null,
      resume: s.status === 'shell' ? resumeFor(sessions, s, cfg.agent_cmd) : null,
      recent_prompt: s.status === 'shell' ? (resumeFor(sessions, s, cfg.agent_cmd)?.prompt ?? null) : null,
      last_prompt_at: lastAt,
      // 핀 고정 칸은 보관 후보로 표시하지 않는다(#13).
      stale: !s.pinned_at && ['idle', 'stopped', 'unknown', 'shell'].includes(s.status) && now.getTime() - new Date(activityAt).getTime() > STALE_MS,
    }
  }
  const base = (s) => {
    const pane = s.runtime_ref.split('/')[1]
    return {
      id: s.id,
      ref: s.runtime_ref,
      // desk = 줄 열쇠(herdr 세션 이름 또는 core:<공간>), desk_label = 줄에 보일 이름, caps = 이 카드에서 할 수 있는 일
      desk: deskOf(s), desk_label: deskLabelOf(s), pane,
      caps: capsOf(s),
      project: s.project,
      title: s.title || '(제목 없음)',
      runtime: s.runtime,
      cwd: s.cwd,
      status: s.status,
      provider: s.provider,
      attention_since: s.attention_since,
      last_user_msg_at: s.last_user_msg_at,
      seen_at: s.seen_at,
      pinned_at: s.pinned_at || null,
      stashed_at: s.stashed_at || null,
      unreachable: s.unreachable === 1,
      off: s.unreachable === 2,
      last_ok_at: s.unreachable ? s.updated_at : null, // 확인 불가·꺼짐 칸을 마지막으로 확인한 시각(#8)
    }
  }
  const card = (s) => {
    const c = { ...base(s), ...contextOf(s) }
    const st = attentionState(s, now, snoozeMs, ttlMs)
    if (st === 'snoozed') c.snoozed_until = new Date(new Date(s.seen_at).getTime() + snoozeMs).toISOString()
    return c
  }

  const live = sessions.filter((s) => !s.stashed_at)
  const raised = live.filter((s) => attentionState(s, now, snoozeMs, ttlMs) === 'raised')
  const snoozed = live.filter((s) => attentionState(s, now, snoozeMs, ttlMs) === 'snoozed')
  const raisedCards = orderAttention(raised.map(card))
  const red = raisedCards.filter((c) => c.status === 'blocked')
  const yellow = raisedCards.filter((c) => c.status === 'done')
  const green = live.filter((s) => s.status === 'working').sort((a, b) => (b.last_user_msg_at || '').localeCompare(a.last_user_msg_at || ''))
  const shown = new Set([...raised, ...snoozed, ...green].map((s) => s.id))
  const seenToday = live.filter((s) => !shown.has(s.id) && s.seen_at && s.seen_at >= today)
  const carryAll = live.filter((s) => !shown.has(s.id) && !(s.seen_at && s.seen_at >= today))
    .sort((a, b) => a.runtime_ref.localeCompare(b.runtime_ref, 'en', { numeric: true }))

  // 최근 닫힘: 사라진 칸은 closed_keep_days 안의 것만, 사용자가 보관한 칸은 기한 없이 — 들어간 문에서 나오는 문이
  // 7일 뒤 잠기면 안 된다(약속 3, I-2).
  const keepFrom = new Date(now.getTime() - cfg.closed_keep_days * 86400000).toISOString()
  const closed = db.prepare(`SELECT * FROM session WHERE (archived = 1 AND status = 'gone' AND updated_at >= ?) OR (archived = 0 AND stashed_at IS NOT NULL)
    ORDER BY COALESCE(stashed_at, updated_at) DESC`).all(keepFrom)
    .map((s) => ({ ...base(s), closed_at: s.stashed_at || s.updated_at, reason: s.stashed_at && !s.archived ? 'stashed' : 'gone',
      resume: withContext && s.archived ? resumeFor(sessions, s, cfg.agent_cmd) : null }))

  return {
    stats: todayStats(db, now),
    now: now.toISOString(),
    today,
    next: raisedCards[0] || null,
    order: raisedCards.map((c) => c.id),
    columns: {
      red,
      yellow,
      snoozed: snoozed.map(card),
      green: green.map(card),
      grey: seenToday.map((s) => ({ kind: 'seen', ...card(s) })),
      carry: carryAll.map(card),
    },
    closed,
    carry_total: carryAll.length,
    health: collectHealth(db, now, cfg),
    settings: cfg,
  }
}

const logEvent = (db, id, at, field, before, after) =>
  db.prepare("INSERT INTO event (session_id, at, field, before, after, source) VALUES (?, ?, ?, ?, ?, 'board')").run(id, at, field, JSON.stringify(before ?? null), JSON.stringify(after ?? null))
const rowOf = (db, id) => {
  const row = db.prepare('SELECT * FROM session WHERE id = ?').get(id)
  if (!row) throw new Error(`no session ${id}`)
  return row
}

// 확인함 = 알림을 seen_snooze_min 동안 미룬다. 그 뒤에도 손 든 상태면 다시 올라온다.
export function markSeen(db, sessionId, now = new Date()) {
  const at = now.toISOString()
  const row = rowOf(db, sessionId)
  db.prepare('UPDATE session SET seen_at = ? WHERE id = ?').run(at, sessionId)
  logEvent(db, sessionId, at, 'seen', row.seen_at, at)
  return at
}

export function markUnseen(db, sessionId, now = new Date()) {
  const row = rowOf(db, sessionId)
  db.prepare('UPDATE session SET seen_at = NULL WHERE id = ?').run(sessionId)
  logEvent(db, sessionId, now.toISOString(), 'unseen', row.seen_at, null)
}

export function setPinned(db, sessionId, on, now = new Date()) {
  const at = now.toISOString()
  const row = rowOf(db, sessionId)
  db.prepare('UPDATE session SET pinned_at = ? WHERE id = ?').run(on ? at : null, sessionId)
  logEvent(db, sessionId, at, on ? 'pin' : 'unpin', row.pinned_at, on ? at : null)
  return on ? at : null
}

// 보관 = 사용자가 직접 접는다. 판에서는 최근 닫힘 줄로 옮겨 가고 되돌릴 수 있다.
export function setStashed(db, sessionId, on, now = new Date()) {
  const at = now.toISOString()
  const row = rowOf(db, sessionId)
  db.prepare('UPDATE session SET stashed_at = ? WHERE id = ?').run(on ? at : null, sessionId)
  logEvent(db, sessionId, at, on ? 'stash' : 'unstash', row.stashed_at, on ? at : null)
  return on ? at : null
}

// 오늘의 주의 사건: 시간대별 발생 수(스파크라인)와 3분 안에 응답한 비율.
// 응답 = 같은 세션에서 requiresAttention이 true→false로 바뀐 시각.
export function todayStats(db, now = new Date()) {
  const today = startOfDay(now).toISOString()
  const rows = db.prepare(`SELECT e.session_id, e.at, e.after FROM event e JOIN session s ON s.id = e.session_id
    WHERE e.field = 'requiresAttention' AND e.at >= ? AND s.runtime IN ('herdr', 'herdr-core') ORDER BY e.at`).all(today)
  const hourly = Array.from({ length: 24 }, () => 0)
  const open = new Map()
  let raised = 0
  let within = 0
  let answered = 0
  for (const r of rows) {
    const t = new Date(r.at)
    if (r.after === 'true') {
      raised += 1
      hourly[t.getHours()] += 1
      open.set(r.session_id, t.getTime())
    } else if (open.has(r.session_id)) {
      answered += 1
      if (t.getTime() - open.get(r.session_id) <= 180000) within += 1
      open.delete(r.session_id)
    }
  }
  return { raised, answered, within_3min: within, within_3min_rate: answered ? within / answered : null, hourly: hourly.slice(0, now.getHours() + 1) }
}
// 최근 닫힘에서 '이어서 열기'로 새 탭에 다시 띄운 칸: 옛 행은 'reopened'로 바꿔 최근 닫힘에서 뺀다.
// 새 칸은 수집이 새 행으로 잡는다(D1, 2026-11-09 — 이어서 연 뒤에도 같은 칸이 최근 닫힘에 남아 있었다).
export function markReopened(db, id, now = new Date()) {
  const at = now.toISOString()
  const r = db.prepare("UPDATE session SET status = 'reopened', updated_at = ? WHERE id = ? AND archived = 1 AND status = 'gone'").run(at, id)
  if (r.changes) db.prepare('INSERT INTO event (session_id, at, field, before, after, source) VALUES (?, ?, ?, ?, ?, ?)').run(id, at, 'status', 'gone', 'reopened', 'board')
  return r.changes > 0
}
