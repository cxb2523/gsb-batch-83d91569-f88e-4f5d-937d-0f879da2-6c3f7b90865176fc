import { transaction, getMeta, setMeta } from './db.mjs'
import { getSettings } from './settings.mjs'

const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null)

// 런타임 조회. listSnapshot이 있으면 확인 불가 세션 목록까지 받는다.
function snapshot(runtime) {
  if (typeof runtime.listSnapshot === 'function') return runtime.listSnapshot()
  return { sessions: runtime.listSessions(), unreachable: [] }
}

// 수집 실패 세 갈래(#15): 실행 파일 없음 · 응답 없음(시간 초과·강제 종료) · 그 밖.
export function errKind(err) {
  if (err?.code === 'ENOENT') return 'no_herdr'
  if (err?.code === 'ETIMEDOUT' || ['SIGTERM', 'SIGKILL'].includes(err?.signal)) return 'no_reply'
  return 'failed'
}

// health=false: 수집 상태(성공 시각·실패·확인 불가 목록)를 적지 않는다 — 런타임이 둘일 때 덧붙는 쪽이 앞쪽 기록을 덮지 않게.
// 후즈업이 다시 뜰 때 부른다: "런타임에 닿지 않기 시작한 때"는 이 프로세스가 지켜본 동안만 뜻이 있다.
// 꺼지기 직전에 적힌 값이 남아 있으면, 오래 꺼 두었다 켠 첫 수집에서 닿지 않은 지 하루가 넘은 것으로 읽힌다.
export function forgetDownSince(db) { db.prepare("DELETE FROM meta WHERE key LIKE 'collect_down_since:%'").run() }

export function collectOnce(db, runtime, { now = new Date(), emit = true, source = 'collector', health = true } = {}) {
  const at = now.toISOString()
  const FIELDS = runtime.FIELDS
  const cfg = getSettings(db)
  let snap
  try {
    snap = snapshot(runtime)
  } catch (err) {
    // herdr에 아예 닿지 않음: 칸을 하나도 건드리지 않고 실패만 남긴다(약속 5 — 모르면 모른다고 한다).
    if (health) {
      setMeta(db, 'collect_err', String(err.message || err).slice(0, 300))
      setMeta(db, 'collect_err_kind', errKind(err))
      setMeta(db, 'collect_err_at', at)
    }
    throw err
  }
  const { sessions, unreachable = [], stopped = [], holdAll = false } = snap
  // 줄(데스크) 이름: herdr는 ref의 앞 마디, 그 밖의 런타임은 스스로 알려 준다.
  const deskOf = (row) => (runtime.deskOf ? runtime.deskOf(row) : row.runtime_ref.split('/')[0])
  // 수집 공백은 런타임마다 따로 잰다: 한쪽(herdr)이 한동안 읽히지 않았다고 멀쩡히 읽히는 다른 쪽(herdr-core) 칸의
  // 대기 시작 시각을 수집 때마다 새로 잡으면 안 된다. 예전 DB에는 런타임별 값이 없어 공용 값으로 이어받는다.
  const okKey = `collect_ok_at:${runtime.name}`
  const lastOk = getMeta(db, okKey) || getMeta(db, 'collect_ok_at')
  // 수집 공백 뒤 첫 수집: 그동안 일어난 일을 모르므로 손 든 칸은 새 사건으로 연다.
  const resumedAfterGap = lastOk && now.getTime() - new Date(lastOk).getTime() > cfg.stale_collect_sec * 1000
  const primed = db.prepare('SELECT COUNT(*) AS n FROM session WHERE runtime = ?').get(runtime.name).n > 0
  emit = emit && primed
  const get = db.prepare('SELECT * FROM session WHERE runtime = ? AND runtime_ref = ?')
  const insert = db.prepare(`INSERT INTO session
    (runtime, runtime_ref, provider_session, project, cwd, title, pane_label, provider, status, fields_json,
     attention_since, attention_kind, last_user_msg_at, archived, first_seen, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
  const update = db.prepare(`UPDATE session SET provider_session = ?, project = ?, cwd = ?, title = ?, pane_label = ?,
    provider = ?, status = ?, fields_json = ?, attention_since = ?, attention_kind = ?, last_user_msg_at = ?, archived = ?,
    miss_count = 0, unreachable = 0, updated_at = ? WHERE id = ?`)
  const resetAlerts = db.prepare('UPDATE session SET last_alert_at = NULL, alert_count = 0 WHERE id = ?')
  const addEvent = db.prepare('INSERT INTO event (session_id, at, field, before, after, source) VALUES (?, ?, ?, ?, ?, ?)')
  const unstash = db.prepare('UPDATE session SET stashed_at = NULL WHERE id = ?')
  const detach = db.prepare("UPDATE session SET runtime_ref = ?, archived = 1, status = 'gone', updated_at = ? WHERE id = ?")
  let added = 0
  let events = 0
  let gone = 0
  let held = 0

  transaction(db, () => {
    for (let s of sessions) {
      let row = get.get(s.runtime, s.runtime_ref)
      // a different conversation moved into the same pane: archive the old row, start a new one
      if (runtime.TRACKS_GONE && row?.provider_session && s.provider_session && row.provider_session !== s.provider_session) {
        detach.run(`${row.runtime_ref}#${row.id}`, at, row.id)
        row = null
      }
      // 다른 에이전트 프로그램이 그 터미널을 차지했다(런타임이 프로그램을 알려 줄 때만): 옛 카드의 대화 id·확인·핀·보관을
      // 새 프로그램의 카드에 물려주지 않는다 — 옛 행은 닫힘으로 보내고 새 행으로 시작한다. 대화 id가 있고 없고와 무관하다.
      if (runtime.AGENT_CHANGE_IS_NEW && row?.provider && s.provider && s.provider !== row.provider) {
        detach.run(`${row.runtime_ref}#${row.id}`, at, row.id)
        row = null
      }
      let hasState = row && row.fields_json !== '{}'
      let prev = hasState ? JSON.parse(row.fields_json) : null
      // 같은 주소를 새 터미널이 물려받았다(런타임이 incarnation으로 알려 준다): 옛 행은 닫힘으로 보내고 새 행으로 시작한다.
      if (runtime.TRACKS_GONE && prev?.incarnation && s.fields.incarnation && prev.incarnation !== s.fields.incarnation) {
        detach.run(`${row.runtime_ref}#${row.id}`, at, row.id)
        row = null; hasState = false; prev = null
      }
      s = inferDone(runtime, s, row, prev)
      let attentionSince = null
      let attentionKind = null
      if (s.fields.requiresAttention) {
        attentionKind = s.status
        // 같은 사건이 이어질 때만 시작 시각을 유지한다. 대기 종류가 바뀌었거나(blocked↔done) 수집 공백 뒤면 새 사건.
        // attention_kind가 비어 있으면 개편 전 행이다 — 같은 사건으로 이어 받아 원래 대기 시작 시각을 지킨다.
        const continuing = prev?.requiresAttention && row?.attention_since && (row.attention_kind == null || row.attention_kind === s.status) && !resumedAfterGap
        // 런타임이 "같은 사건"이라고 알려 주면(attentionKey: 같은 끝난 턴) 런타임이 준 시각이 달라져도 시작 시각을 지킨다.
        const sameEvent = continuing && prev?.attentionKey && prev.attentionKey === s.fields.attentionKey
        attentionSince = sameEvent ? row.attention_since : (s.attentionTimestamp || (continuing ? row.attention_since : at))
      }
      const values = [s.provider_session ?? row?.provider_session ?? null, s.project, s.cwd, s.title, s.pane_label ?? null,
        s.provider ?? row?.provider ?? null, s.status, JSON.stringify(s.fields), attentionSince, attentionKind, s.fields.lastUserMessageAt, s.archived ? 1 : 0]
      let sessionId
      if (!row) {
        sessionId = Number(insert.run(s.runtime, s.runtime_ref, ...values, at, at).lastInsertRowid)
        added += 1
      } else {
        sessionId = row.id
        update.run(...values, at, row.id)
        // 보관은 주의를 가리지 않는다(I-2): 보관한 칸이 다시 움직이면(작업 중·입력 필요·답변 도착) 판으로 돌려놓는다.
        if (row.stashed_at && s.status !== row.status && ['working', 'blocked', 'done'].includes(s.status)) {
          unstash.run(row.id)
          addEvent.run(row.id, at, 'unstash', JSON.stringify(row.stashed_at), 'null', source)
        }
        if (attentionSince !== row.attention_since) resetAlerts.run(row.id)
      }
      if (!emit || (row && !hasState)) continue
      for (const field of FIELDS) {
        const before = prev ? prev[field] : null
        if (prev && same(before, s.fields[field])) continue
        addEvent.run(sessionId, at, field, JSON.stringify(before ?? null), JSON.stringify(s.fields[field] ?? null), source)
        events += 1
      }
    }
    if (runtime.TRACKS_GONE) {
      const present = new Set(sessions.map((s) => s.runtime_ref))
      const cut = new Set(unreachable)
      const off = new Set(stopped)
      // unreachable: 1 = 조회 실패(확인 불가, 마지막 상태 유지), 2 = 서버 꺼짐(손 든 칸에서 뺌)
      // updated_at은 건드리지 않는다 — 확인 불가 동안 그 값이 곧 "마지막으로 확인한 시각"이다(#8).
      const hold = db.prepare('UPDATE session SET unreachable = ? WHERE id = ?')
      const miss = db.prepare('UPDATE session SET miss_count = miss_count + 1 WHERE id = ?')
      const markGone = db.prepare("UPDATE session SET archived = 1, status = 'gone', unreachable = 0, updated_at = ? WHERE id = ?")
      // 런타임 전체에 닿지 않기 시작한 때(holdAll). 닿으면 지운다. "오래 닿지 않았다"는 이 시각부터 잰다 —
      // 후즈업을 오래 꺼 두었다가 켠 직후 한 번 닿지 않았다고 칸을 닫지 않는다.
      const downKey = `collect_down_since:${runtime.name}`
      let downSince = getMeta(db, downKey)
      if (holdAll && !downSince) { downSince = at; setMeta(db, downKey, at) }
      if (!holdAll && downSince) setMeta(db, downKey, null)
      const downFor = holdAll ? now.getTime() - new Date(downSince).getTime() : 0
      for (const row of db.prepare('SELECT id, runtime_ref, miss_count, fields_json, updated_at FROM session WHERE runtime = ? AND archived = 0').all(runtime.name)) {
        if (present.has(row.runtime_ref)) continue
        // 조회하지 못한 세션의 칸: 마지막 상태를 그대로 두고 "확인 불가"로 표시한다.
        const desk = deskOf(row)
        // 런타임 전체에 닿지 않는 채로(holdAll) unreachable_ttl_h가 지난 칸은 닫힘으로 보낸다 — 지운 프로그램의 칸이 판에 영영 남지 않게.
        if (holdAll && !off.has(desk) && downFor > cfg.unreachable_ttl_h * 3600000 && now.getTime() - new Date(row.updated_at).getTime() > cfg.unreachable_ttl_h * 3600000) {
          markGone.run(at, row.id); addEvent.run(row.id, at, 'gone', 'false', 'true', source); gone += 1; continue
        }
        if (holdAll || cut.has(desk) || off.has(desk)) { hold.run(off.has(desk) ? 2 : 1, row.id); held += 1; continue }
        // 정말 없어진 칸: 연속 gone_misses번 안 보여야 닫힘으로 옮긴다(일시 오류에 흔들리지 않게).
        if (row.miss_count + 1 >= cfg.gone_misses) {
          markGone.run(at, row.id)
          addEvent.run(row.id, at, 'gone', 'false', 'true', source)
          gone += 1
        } else miss.run(row.id)
      }
    }
    if (!holdAll) setMeta(db, okKey, at)
    if (health) {
      setMeta(db, 'collect_ok_at', at)
      setMeta(db, 'collect_unreachable', unreachable.join(','))
      setMeta(db, 'collect_stopped', stopped.join(','))
    }
  })
  return { at, sessions: sessions.length, added, events, gone, held, unreachable, stopped }
}

// 끝난 칸을 '유휴'로만 알려 주는 런타임(윈도우 herdr — '답변 도착'을 내지 않는다)에서, 아직 안 본 끝난 칸을 답변 도착으로 해석한다.
// D3: 진행 중 → 유휴. D2: 수집 사이(3초)에 새 요청이 들어왔다가 이미 끝나 유휴로만 보이는 짧은 작업.
// 그렇게 만든 답변 도착은 같은 대화에 새 요청이 없는 동안 유지된다(확인함·열기는 보드의 확인 처리로 내린다). 2026-11-09 QA
function inferDone(runtime, s, row, prev) {
  if (!runtime.IDLE_AFTER_WORK_IS_DONE || s.status !== 'idle' || !row || !prev) return s
  const msgSame = same(prev.lastUserMessageAt, s.fields.lastUserMessageAt)
  const wasWorking = row.status === 'working'
  const keep = prev.inferredDone && row.status === 'done' && msgSame
  const shortTurn = !msgSame && s.fields.lastUserMessageAt != null
  if (!(wasWorking || keep || shortTurn)) return s
  return { ...s, status: 'done', fields: { ...s.fields, requiresAttention: true, inferredDone: true } }
}
