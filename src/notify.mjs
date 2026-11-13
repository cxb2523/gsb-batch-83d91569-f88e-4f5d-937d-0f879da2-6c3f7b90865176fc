// 탭이 닫혀 있어도 닿는 macOS 알림(선택 옵션, 기본 끔 — 설정 os_notify). 약속 4.
// 손 든 칸마다 처음 1회 + renotify_min 간격으로 최대 renotify_max회 다시 보낸다. 확인함으로 미룬 칸은 보내지 않는다.
import { execFile } from 'node:child_process'
import { attentionState, collectHealth, orderAttention } from './board/board.mjs'
import { getMeta, setMeta } from './db.mjs'
import { getSettings } from './settings.mjs'

const esc = (t) => String(t ?? '').replace(/["\\]/g, '\\$&').replace(/\s+/g, ' ').slice(0, 160)
export function osNotify({ title, subtitle, body }, run = execFile) {
  if (process.platform !== 'darwin') return false
  run('/usr/bin/osascript', ['-e', `display notification "${esc(body)}" with title "${esc(title)}" subtitle "${esc(subtitle)}"`], { timeout: 10000 }, (err) => { if (err) console.error(`whosup: macOS notification failed: ${String(err.message || err).slice(0, 200)}`) })
  return true
}

const KIND = { blocked: { ko: '입력 필요', en: 'needs input' }, done: { ko: '답변 도착', en: 'finished' } }
const TEXT = {
  blind: { ko: ['herdr를 읽지 못하고 있습니다', '그동안 손 든 칸 알림이 멈춥니다'], en: ['cannot read herdr', 'pane alerts are paused until it reconnects'] },
  many: { ko: (n) => `칸 ${n}개가 기다립니다`, en: (n) => `${n} panes are waiting` },
}
const lang = () => (process.env.LANG || '').startsWith('ko') ? 'ko' : 'en'

// prime=true(프로세스 첫 수집)면 이미 손 든 칸은 보낸 것으로만 표시한다 — 재시작마다 알림이 쏟아지지 않게.
export function notifyPass(db, { now = new Date(), prime = false, send = osNotify } = {}) {
  const cfg = getSettings(db)
  if (!cfg.os_notify) return 0
  const L = lang()
  // 수집이 끊긴 동안은 판이 낡았으니 재알림하지 않는다(#7). 대신 끊김 자체를 에피소드(마지막 성공 시각)당 한 통 알린다(I-7).
  // 나이만으로 판정하면 잠에서 깬 직후 거짓 경보가 나므로 수집 오류가 함께 있을 때만.
  const health = collectHealth(db, now, cfg)
  if (health.stale) {
    const episode = health.ok_at || 'never'
    if (!prime && health.error && getMeta(db, 'blind_notified_ok_at') !== episode) {
      send({ title: 'whosup', subtitle: TEXT.blind[L][0], body: TEXT.blind[L][1] })
      setMeta(db, 'blind_notified_ok_at', episode)
      return 1
    }
    return 0
  }
  const snoozeMs = cfg.seen_snooze_min * 60000
  const rows = db.prepare("SELECT * FROM session WHERE archived = 0 AND status IN ('blocked', 'done')").all()
    .filter((s) => attentionState(s, now, snoozeMs, cfg.unreachable_ttl_h * 3600000) === 'raised')
  const mark = db.prepare('UPDATE session SET last_alert_at = ?, alert_count = ? WHERE id = ?')
  const due = orderAttention(rows).filter((s) => !s.last_alert_at || (s.alert_count <= cfg.renotify_max && now.getTime() - new Date(s.last_alert_at).getTime() >= cfg.renotify_min * 60000))
  const name = (s) => s.pane_label || s.project
  let sent = 0
  if (!prime && due.length >= 2) {
    // 동시에 여러 칸이면 한 통으로 묶는다(#16). 순번대로 이름을 늘어놓는다.
    send({ title: 'whosup', subtitle: TEXT.many[L](due.length), body: due.map((s) => `${name(s)} · ${KIND[s.status][L]}`).join(', ') })
    sent = 1
  } else if (!prime && due.length === 1) {
    const s = due[0]
    send({ title: 'whosup', subtitle: `${name(s)} · ${KIND[s.status][L]}${s.alert_count ? (L === 'ko' ? ' · 다시' : ' · again') : ''}`, body: s.title || s.cwd })
    sent = 1
  }
  for (const s of due) mark.run(now.toISOString(), s.alert_count + 1, s.id)
  return sent
}
