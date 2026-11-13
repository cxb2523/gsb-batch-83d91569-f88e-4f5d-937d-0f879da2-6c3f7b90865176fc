#!/usr/bin/env node
// whosup autoconf — 실행 환경을 확인해 자동 값을 정하고(src/autoconf.mjs 레인 L1~L10) 상태 폴더의 auto.json에 쓴다.
//
//   node scripts/autoconf.mjs              감지 표(레인·자동 값·근거) + 설정 출처 표, auto.json 쓰기
//   node scripts/autoconf.mjs --json       같은 내용을 JSON으로
//   node scripts/autoconf.mjs --no-save    auto.json을 쓰지 않는다
//   node scripts/autoconf.mjs --value KEY  감지·저장한 뒤 그 키의 자동 값만 한 줄(없으면 빈 줄). 시작 스크립트용
//   node scripts/autoconf.mjs --read KEY   감지하지 않고 지금 auto.json의 값만 한 줄
//
// 설치(build 훅: preflight 뒤)와 시작(plugin.sh·launch.mjs start, 서버를 띄우기 전)에 돈다. 아무것도 고치거나 띄우지 않는다.
// 사용자 설정 파일(<설정 폴더>/.env)은 읽기만 하고 만들거나 고치지 않는다. 설정 패널(DB)도 건드리지 않는다.
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { detect, evaluate, readAuto, writeAuto } from '../src/autoconf.mjs'
import { loadEnv } from './launch.mjs'

const STATE = process.env.WHOSUP_STATE_DIR || process.env.HERDR_PLUGIN_STATE_DIR || join(homedir(), '.config', 'whosup')
const show = (v) => (v === undefined ? '-' : Array.isArray(v) ? v.join(',') : String(v))

// 사람이 정한 값이 auto를 이기는지 미리 보여 준다(환경변수·.env만 — 패널 값은 서버 DB에 있어 여기서 열지 않는다).
const HUMAN_ENV = { front_app: 'FRONT_APP', agent_cmd: 'AGENT_CMD', open_browser: 'OPEN_BROWSER', port: 'PORT' }
export function render(r, env = process.env) {
  const L = [`whosup autoconf  ${r.at}  (${r.platform})`, 'lane key                         auto value                         why']
  for (const l of r.lanes) {
    const human = HUMAN_ENV[l.key] && env[HUMAN_ENV[l.key]] !== undefined && env[HUMAN_ENV[l.key]] !== '' ? `  [${HUMAN_ENV[l.key]} set: env wins]` : ''
    L.push(`${l.lane.padEnd(4)} ${l.key.padEnd(28)} ${show(l.value).padEnd(34)} ${l.reason}${human}`)
  }
  L.push('order: settings panel > environment (.env) > auto > default. Values you set are never changed by auto.')
  return L.join('\n')
}

export async function run(argv = process.argv.slice(2), log = console.log) {
  const at = (f) => { const i = argv.indexOf(f); return i >= 0 ? argv[i + 1] : undefined }
  if (argv.includes('--read')) { const v = readAuto(STATE)?.values?.[at('--read')]; log(v === undefined ? '' : show(v)); return 0 }
  const env = loadEnv(process.env)   // .env를 읽기만(scripts/launch.mjs와 같은 규칙)
  const r = evaluate(await detect({ env }))
  let file = null
  if (!argv.includes('--no-save')) { try { file = writeAuto(STATE, r) } catch (e) { console.error(`whosup autoconf: could not write auto.json: ${e.message}`) } }
  if (argv.includes('--value')) { const v = r.values[at('--value')]; log(v === undefined ? '' : show(v)); return 0 }
  if (argv.includes('--json')) log(JSON.stringify(r, null, 2))
  else { log(render(r, env)); if (file) log(`saved: ${file}`) }
  return 0
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = await run()
