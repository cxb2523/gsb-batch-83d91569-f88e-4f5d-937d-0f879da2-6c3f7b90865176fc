// 사람마다 바꾸는 수치. 우선순위: DB meta(설정 패널) > 환경변수(.env 포함) > 자동 감지(auto.json) > 기본값. 범위 밖 값은 거절한다.
// 사람이 정한 값(패널·환경변수)은 자동 값이 절대 이기지 못한다. 자동 층은 setAutoValues로 넣는다(서버 시작 때 auto.json).
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { getMeta, setMeta } from './db.mjs'
import { isWindows } from './platform.mjs'

const RESET = Symbol('reset')

export const SETTINGS = {
  seen_snooze_min: { def: 30, min: 1, max: 1440, env: 'WHOSUP_SEEN_SNOOZE_MIN' },
  renotify_min: { def: 15, min: 1, max: 240, env: 'WHOSUP_RENOTIFY_MIN' },
  renotify_max: { def: 4, min: 0, max: 20, env: 'WHOSUP_RENOTIFY_MAX' },
  gone_misses: { def: 3, min: 1, max: 20, env: 'WHOSUP_GONE_MISSES' },
  stale_collect_sec: { def: 30, min: 5, max: 600, env: 'WHOSUP_STALE_COLLECT_SEC' },
  closed_keep_days: { def: 7, min: 1, max: 90, env: 'WHOSUP_CLOSED_KEEP_DAYS' },
  stale_days: { def: 3, min: 1, max: 60, env: ['WHOSUP_STALE_DAYS', 'STALE_DAYS'] },
  os_notify: { def: 0, min: 0, max: 1, env: 'WHOSUP_OS_NOTIFY' },
  unreachable_ttl_h: { def: 24, min: 1, max: 168, env: 'WHOSUP_UNREACHABLE_TTL_H' },
  // 화면 나눠 쓰기: 칸을 누르면 보드 창을 화면 왼쪽 N%에, 터미널 창을 나머지 오른쪽에 붙인다. 0이면 끈다(작은 노트북 화면용).
  split_pct: { def: 0, min: 0, max: 60, env: 'WHOSUP_SPLIT_PCT' },
}

// 글자 설정: 새 세션·이어서 열기에 쓸 명령. 한 줄, 200자 이하.
// front_app: 칸을 누르면 앞으로 올릴(없으면 새 창을 열) 터미널 앱 이름. 비어 있으면 자동(떠 있는 앱 > 기본 터미널).
// 앱 이름은 명령줄과 AppleScript에 들어가므로 macOS·리눅스에서는 글자를 좁게 받는다.
// 윈도우에서는 이 값이 명령줄에 들어가지 않는다(창 올리기 켬/끔과 어느 터미널로 새 창을 열지만 정한다 — herdr.mjs winTerminal).
// 그래서 'C:\…\wt.exe'·'Windows Terminal (Preview)' 같은 값도 받는다. e82b667 이후 이런 값이 패턴에 걸려 조용히
// 꺼지던 것이 9b4bc0f(비어 있지 않은 아무 값이면 켜짐) 대비 회귀였다(REVIEW2 (b)).
export const TEXT_SETTINGS = {
  agent_cmd: { def: 'claude', env: 'AGENT_CMD', max: 200 },
  front_app: { def: '', env: 'FRONT_APP', max: 60, pattern: /^[A-Za-z0-9 ._-]+$/, windows: { max: 260, pattern: null } },
  // 칸을 누르면 열 곳: terminal(서버 화면의 터미널 창, 기본) | web(세션별 웹 주소, ovis 등) | both. 자동 층이 없다 — ovis가 있어도
  // 기본은 터미널이고(오너 결정 11-11), 첫 실행 확인 카드나 설정에서 사람이 고른 값만 바꾼다. 브라우저에 저장한 값이 있으면 그게 먼저다.
  click_target: { def: 'terminal', env: 'WHOSUP_CLICK_TARGET', max: 8, pattern: /^(terminal|web|both)$/, choices: ['terminal', 'web', 'both'] },
}
const specFor = (spec) => (spec.windows && isWindows() ? { ...spec, ...spec.windows } : spec)
const validText = (spec0, v) => { const spec = specFor(spec0); return typeof v === 'string' && v.trim().length > 0 && v.length <= spec.max && !/[\r\n\0]/.test(v) && (!spec.pattern || spec.pattern.test(v.trim())) }

const envName = (spec) => [].concat(spec.env).find((k) => process.env[k] !== undefined && process.env[k] !== '') ?? null
const fromEnv = (spec) => { const k = envName(spec); return k ? Number(process.env[k]) : undefined }
const valid = (spec, v) => Number.isFinite(v) && Number.isInteger(v) && v >= spec.min && v <= spec.max

// 자동 층: { values: { key: 값 }, reasons: { key: '근거' } } — src/autoconf.mjs evaluate()의 결과(auto.json) 그대로.
let auto = { values: {}, reasons: {}, result: null }
export function setAutoValues(result) { auto = { values: { ...(result?.values || {}) }, reasons: { ...(result?.reasons || {}) }, result: result || null } }
export const autoValues = () => auto
const autoNum = (key, spec) => { const v = auto.values[key]; return typeof v === 'number' && valid(spec, v) ? v : undefined }
const autoText = (key, spec) => { const v = auto.values[key]; return typeof v === 'string' && validText(spec, v) ? v : undefined }

export function getSettings(db) {
  const out = {}
  for (const [key, spec] of Object.entries(SETTINGS)) {
    const saved = db ? getMeta(db, `setting.${key}`) : null
    const cands = [saved == null ? undefined : Number(saved), fromEnv(spec), autoNum(key, spec), spec.def]
    out[key] = cands.find((v) => v !== undefined && valid(spec, v)) ?? spec.def
  }
  for (const [key, spec] of Object.entries(TEXT_SETTINGS)) {
    const cands = [db ? getMeta(db, `setting.${key}`) : null, process.env[spec.env], autoText(key, spec), spec.def]
    out[key] = (cands.find((v) => v != null && validText(spec, v)) ?? spec.def).trim()
  }
  return out
}

// patch의 키·값을 검사해 저장한다. 하나라도 틀리면 아무것도 저장하지 않고 이유를 돌려준다.
export function setSettings(db, patch) {
  const errors = []
  const clean = {}
  for (const [key, raw] of Object.entries(patch || {})) {
    if (raw === null || raw === '') { if (SETTINGS[key] || TEXT_SETTINGS[key]) clean[key] = RESET; else errors.push(`unknown setting ${key}`); continue } // 비우면 기본값(환경변수 > 코드 기본값)으로 되돌린다
    if (TEXT_SETTINGS[key]) {
      if (!validText(TEXT_SETTINGS[key], raw)) { const sp = specFor(TEXT_SETTINGS[key]); errors.push(sp.choices ? `${key} must be one of ${sp.choices.join(', ')}` : sp.pattern ? `${key} must be an app name: letters, digits, spaces, . _ - (up to ${sp.max})` : `${key} must be one line of 1–${sp.max} characters`); continue }
      clean[key] = raw.trim(); continue
    }
    const spec = SETTINGS[key]
    if (!spec) { errors.push(`unknown setting ${key}`); continue }
    const v = typeof raw === 'boolean' ? Number(raw) : Number(raw)
    if (!valid(spec, v)) { errors.push(`${key} must be an integer ${spec.min}–${spec.max}`); continue }
    clean[key] = v
  }
  if (errors.length) return { ok: false, errors }
  for (const [k, v] of Object.entries(clean)) {
    if (v === RESET) db.prepare('DELETE FROM meta WHERE key = ?').run(`setting.${k}`)
    else setMeta(db, `setting.${k}`, v)
  }
  return { ok: true, settings: getSettings(db) }
}

// 키마다 지금 값이 어디서 왔는지(옛 모양): saved(설정 패널) | env(환경변수) | auto(자동 감지) | default(코드 기본값). 패널이 '(환경변수)'처럼 보인다(I-11).
const OLD = { panel: 'saved', env: 'env', auto: 'auto', default: 'default' }
export function settingSources(db) {
  return Object.fromEntries(Object.entries(settingOrigins(db)).map(([k, o]) => [k, OLD[o.source]]))
}

// 사용자 설정 파일(.env)의 위치와 그 안의 키: 환경변수 출처가 그 파일인지 알려 주려고 읽기만 한다(만들거나 고치지 않는다).
// 형식은 scripts/launch.mjs parseEnvFile과 같다(KEY=VALUE, # 주석, export 접두, 따옴표 한 겹).
export const envFilePath = (env = process.env) => join(env.HERDR_PLUGIN_CONFIG_DIR || join(homedir(), '.config', 'whosup'), '.env')
function envFileKeys(file) {
  try {
    return new Set(readFileSync(file, 'utf8').split(/\r?\n/).map((l) => /^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=/.exec(l)?.[1]).filter(Boolean))
  } catch { return new Set() }
}

// 키마다 출처를 자세히: { source: 'panel' } | { source: 'env', name, file|null } | { source: 'auto', reason } | { source: 'default' }.
// 순서는 getSettings와 같다(패널 > 환경변수 > 자동 > 기본) — 화면이 보여 주는 출처가 실제 값과 어긋나지 않는다.
export function settingOrigins(db) {
  const file = envFilePath()
  const inFile = envFileKeys(file)
  const envOrigin = (name) => ({ source: 'env', name, file: inFile.has(name) ? file : null })
  const autoOrigin = (key) => ({ source: 'auto', reason: auto.reasons[key] || 'detected' })
  const out = {}
  for (const [key, spec] of Object.entries(SETTINGS)) {
    const saved = db ? getMeta(db, `setting.${key}`) : null
    const env = fromEnv(spec)
    out[key] = saved != null && valid(spec, Number(saved)) ? { source: 'panel' }
      : env !== undefined && valid(spec, env) ? envOrigin(envName(spec))
      : autoNum(key, spec) !== undefined ? autoOrigin(key) : { source: 'default' }
  }
  for (const [key, spec] of Object.entries(TEXT_SETTINGS)) {
    const saved = db ? getMeta(db, `setting.${key}`) : null
    out[key] = saved != null && validText(spec, saved) ? { source: 'panel' }
      : process.env[spec.env] != null && validText(spec, process.env[spec.env]) ? envOrigin(spec.env)
      : autoText(key, spec) !== undefined ? autoOrigin(key) : { source: 'default' }
  }
  return out
}

// 창 올리기에 넘길 [사람이 정한 앱(패널·FRONT_APP, 없으면 ''), 자동 세팅 앱(L4, 없으면 '')] — herdr.setFrontApp(...)에 그대로 펼친다.
// 자동 값을 '사람이 고른 앱'으로 넘기지 않는다: 맥에서 자동 앱은 떠 있는 창이 없을 때 새 창을 열 앱일 뿐이다(herdr.mjs setFrontApp).
export function frontAppChoice(db) {
  const v = getSettings(db).front_app
  const a = autoText('front_app', TEXT_SETTINGS.front_app) ?? ''
  return settingOrigins(db).front_app.source === 'auto' ? ['', a.trim()] : [v, a.trim()]
}

// 브라우저 쪽(localStorage) 설정의 서버 기본값. 브라우저에 사람이 저장한 값이 있으면 그게 먼저다 — 화면은 저장값이 없을 때만 이것을 쓴다.
// whosup-open-url:<세션> = 자동 감지한 ovis 주소. 클릭 동작(whosup-open-url-on·whosup-raise)은 click_target(기본 터미널)에서만 나온다.
export function clientDefaults(db) {
  const s = getSettings(db)
  const out = { 'whosup-open-url-on': s.click_target === 'terminal' ? 'off' : 'on', 'whosup-raise': s.click_target === 'web' ? 'off' : 'on' }
  for (const [k, v] of Object.entries(auto.values)) if (k.startsWith('open_url:') && typeof v === 'string') out[`whosup-open-url:${k.slice('open_url:'.length)}`] = v
  return out
}

export const SETTING_RANGES = Object.fromEntries([
  ...Object.entries(SETTINGS).map(([k, s]) => [k, { def: s.def, min: s.min, max: s.max }]),
  ...Object.entries(TEXT_SETTINGS).map(([k, s]) => [k, { def: s.def, text: true, max: s.max, ...(s.choices ? { choices: s.choices } : {}) }]),   // max는 macOS 기준(윈도우 front_app은 260)
])
