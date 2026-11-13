// 런타임 모음: herdr 세션(herdr.mjs)과 herdr-core 터미널(core.mjs). 있는 쪽만 수집하고,
// 카드가 어느 쪽 것인지에 따라 조작(이동·닫기·새 세션·줄 켜고 끄기)을 그쪽 구현으로 보낸다.
import * as herdr from './herdr.mjs'
import * as core from './core.mjs'
import { collectOnce } from '../collector.mjs'
import { getMeta, setMeta } from '../db.mjs'

const ALL = { [herdr.name]: herdr, [core.name]: core }
// WHOSUP_RUNTIMES: 'auto'(기본 — 있는 것 전부) 또는 쉼표로 고른 이름(herdr, herdr-core).
export function wanted() {
  const v = (process.env.WHOSUP_RUNTIMES || 'auto').trim()
  if (!v || v === 'auto') return Object.keys(ALL)
  return v.split(',').map((x) => x.trim()).filter((n) => ALL[n])
}
export const runtimeOf = (name) => ALL[name] || null
// 줄 열쇠(herdr 세션 이름 또는 core:<공간>)가 어느 런타임 것인지.
export const runtimeForDesk = (desk) => (core.isDesk(desk) ? core : herdr)
export const deskOf = (row) => (row.runtime === core.name ? core.deskOf(row) : row.runtime_ref.split('/')[0])
export const deskLabelOf = (row) => (row.runtime === core.name ? core.deskLabelOf(row) : row.runtime_ref.split('/')[0])
// 카드에서 할 수 있는 일. 화면은 런타임 이름이 아니라 이것으로 버튼을 정한다. 모르는 런타임의 행은 null(판에 올리지 않는다).
// toggle = 줄 켜고 끄기. 공간 밖 터미널을 모은 줄(core:)에는 닫을 공간이 없어서 뺀다.
const FULL = ['focus', 'close', 'resume', 'new', 'toggle', 'web']
export function capsOf(row) {
  if (row.runtime === herdr.name) return FULL
  if (row.runtime === core.name) return core.deskOf(row) === core.DESK_PREFIX ? FULL.filter((c) => c !== 'toggle') : FULL
  return null
}

// 한 번의 수집. 런타임마다 미리 읽은 결과를 수집기에 넘긴다. 없는 런타임(실행 파일·코어 없음)은 그 런타임의 칸이
// DB에 없을 때만 조용히 건너뛴다 — 칸이 있었다면 "확인 불가"로 남겨야 한다(모르면 모른다고 한다).
// 보드에서 칸을 닫는 등 판을 직접 바꾼 일이 있으면 알린다. 그보다 먼저 읽기 시작한 목록은 버리고 다시 읽는다 —
// 닫기 전에 읽은 목록이 닫은 뒤에 적용되면 닫은 카드가 되살아난다(한쪽 런타임 조회가 느릴 때).
let changes = 0
export const noteChange = () => { changes++ }
export async function collectAll(db, opts = {}) {
  const names = wanted()
  let rts, clean = false
  for (let i = 0; i < 3 && !clean; i++) {
    const seen = changes
    rts = Object.fromEntries(await Promise.all(names.map(async (n) => [n, await ALL[n].snapshotRuntime()])))
    clean = seen === changes
  }
  // 세 번을 읽는 동안에도 판이 계속 바뀌었다: 낡은 목록을 적용하지 않고 이번 수집을 건너뛴다(다음 수집이 곧 온다).
  if (!clean) return { runs: [], runtimes: rts, failure: null, notes: [], skipped: true }
  const rows = (n) => db.prepare('SELECT COUNT(*) AS n FROM session WHERE runtime = ? AND archived = 0').get(n).n
  const h = rts[herdr.name]
  const c = rts[core.name]
  const coreHere = Boolean(c) && !c.absent
  const useCore = Boolean(c) && (coreHere || rows(core.name) > 0 || !h)
  // herdr가 설치되지 않았는데 herdr-core는 있고 herdr 칸도 없으면: herdr-core만 쓰는 기계다.
  const useHerdr = Boolean(h) && !(h.absent && useCore && rows(herdr.name) === 0)
  const runs = []
  let failure = null
  if (useHerdr) { try { runs.push({ name: herdr.name, ...collectOnce(db, h, opts) }) } catch (err) { failure = err } }
  if (useCore) { try { runs.push({ name: core.name, ...collectOnce(db, c, { ...opts, health: !useHerdr }) }) } catch (err) { failure ||= err } }
  // herdr가 판의 건강 상태를 적는 기계에서 herdr-core에 닿지 못하면: 그 사실을 건강 상태의 "확인 불가" 목록에 보태고
  // 호출자에게 알린다(카드에는 이미 확인 불가가 붙는다 — 왜 그런지가 어디에도 남지 않던 것을 메운다).
  const notes = []
  if (useCore && (c.absent || c.err)) {
    notes.push(`${core.name}: ${c.err ? String(c.err.message || c.err).slice(0, 200) : 'not running'}`)
    if (useHerdr && !failure) setMeta(db, 'collect_unreachable', [...new Set([...(getMeta(db, 'collect_unreachable') || '').split(',').filter(Boolean), core.LOOSE_LABEL])].join(','))
  }
  return { runs, runtimes: rts, failure, notes }
}

// 변화 알림 구독(있으면 주기를 기다리지 않고 바로 수집). 수집 결과를 받아 런타임별로 건다.
export function watchAll(runtimes, kick) {
  const h = runtimes[herdr.name]
  if (h?.snap) herdr.watchEvents(h.snap.sessions, h.snap.table, kick)
  if (runtimes[core.name]) core.watchEvents(kick)
}
export function stopWatching() { herdr.stopWatching(); core.stopWatching() }
