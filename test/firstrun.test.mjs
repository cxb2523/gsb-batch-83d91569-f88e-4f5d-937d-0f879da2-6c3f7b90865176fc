// M3 화면: 설정 값의 출처 표시, "감지한 환경" 요약, 첫 실행 확인 카드.
// 화면(index.html)의 /*origin*/ 덩어리(순수 함수)와 I18N을 그대로 읽어 시험하고, 화면 배선은 문지기 패턴(readonly.test.mjs)으로 본다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { openDb } from '../src/db.mjs'
import { setAutoValues, getSettings } from '../src/settings.mjs'
import { createBoardServer } from '../src/board/server.mjs'

const html = readFileSync(new URL('../src/board/index.html', import.meta.url), 'utf8')
const I18N = new Function(`${html.match(/const I18N = \{[\s\S]*?\n\}\n/)[0]}; return I18N`)()
const block = html.match(/\/\*origin\*\/([\s\S]*?)\/\*\/origin\*\//)
assert.ok(block, 'index.html에 /*origin*/ … /*/origin*/ 덩어리가 있어야 한다')
const { originText, envSummaryParts, firstRunPlan, firstRunHintKey } = new Function(`${block[1]}; return { originText, envSummaryParts, firstRunPlan, firstRunHintKey }`)()

test('출처 한 줄: 패널 / 환경변수(파일 경로·stop 뒤 start) / 자동 감지(근거) / 기본값 — ko·en', () => {
  for (const lang of ['ko', 'en']) {
    const T = I18N[lang]
    const panel = originText({ source: 'panel' }, T)
    const envFile = originText({ source: 'env', name: 'AGENT_CMD', file: '/tmp/cfg/.env' }, T)
    const envShell = originText({ source: 'env', name: 'FRONT_APP', file: null }, T)
    const auto = originText({ source: 'auto', reason: 'L4: Ghostty.app is installed' }, T)
    const def = originText({ source: 'default' }, T)
    assert.ok(panel && def && panel !== def, lang)
    assert.match(envFile, /AGENT_CMD/); assert.match(envFile, /\/tmp\/cfg\/\.env/); assert.match(envFile, /stop/); assert.match(envFile, /start/)
    assert.match(envShell, /FRONT_APP/); assert.match(envShell, /stop/); assert.doesNotMatch(envShell, /null/)
    assert.match(auto, /L4: Ghostty\.app is installed/)
    assert.equal(originText(undefined, T), '', '옛 서버(origins 없음)면 아무것도 쓰지 않는다')
    assert.ok(originText({ source: 'browser' }, T), lang)
    assert.ok(originText({ source: 'card' }, T) && originText({ source: 'card' }, T) !== panel, '칸 열기 방식의 사람 값은 칸 비우기 안내가 없는 문구')
  }
  assert.match(originText({ source: 'panel' }, I18N.ko), /설정 패널에서 정함/)
  assert.match(originText({ source: 'auto', reason: 'x' }, I18N.ko), /자동 감지/)
  assert.match(originText({ source: 'default' }, I18N.ko), /기본값/)
})

test('어디인지 모르는 "지금 값은 환경변수" 문구를 없앴다', () => {
  assert.doesNotMatch(html, /fromEnv/)
  assert.doesNotMatch(html, /지금 값은 환경변수/)
  assert.doesNotMatch(html, /current value from environment/)
})

test('감지한 환경 요약: OS·터미널 앱·herdr 세션·Herdr 앱·ovis 포트↔세션·원격 여부, 감지 못 한 항목은 "확인 못 함"', () => {
  const T = I18N.ko
  const none = envSummaryParts(null, T)
  assert.equal(none.length, 6)
  assert.ok(none.every(([, v]) => v === '확인 못 함'), 'auto.json이 없으면 전부 확인 못 함')
  const full = Object.fromEntries(envSummaryParts({
    os: 'darwin', desktop: true, terminal: 'Ghostty',
    herdr: { found: true, version: '0.9.3', sessions: ['main', 'side'] }, herdr_core: { running: true }, herdr_app: { found: true },
    ovis: [{ port: 7318, session: 'side', url: 'http://127.0.0.1:7318/?pane={pane}', confirmed: true }, { port: 7317, session: null, confirmed: false }],
  }, T))
  assert.equal(full.OS, 'macOS')
  assert.equal(full['터미널 앱'], 'Ghostty')
  assert.match(full['herdr 세션'], /2개 \(main, side\)/)
  assert.match(full['Herdr 앱'], /있음 · 코어 실행 중/)
  assert.equal(full.ovis, '7318 ↔ side, 7317 ↔ 세션 확인 필요')
  assert.equal(full['실행 위치'], '이 컴퓨터의 데스크톱')
  const part = Object.fromEntries(envSummaryParts({ os: 'win32', desktop: null, terminal: 'off', herdr: null, herdr_core: null, herdr_app: null, ovis: [] }, T))
  assert.equal(part.OS, 'Windows')
  assert.equal(part['터미널 앱'], '끔')
  assert.equal(part['herdr 세션'], '확인 못 함')
  assert.equal(part['Herdr 앱'], '확인 못 함')
  assert.equal(part.ovis, '없음')
  assert.equal(part['실행 위치'], '확인 못 함')
  const remote = Object.fromEntries(envSummaryParts({ os: 'linux', desktop: false, terminal: null, herdr: { found: false }, ovis: [] }, I18N.en))
  assert.match(remote['running on'], /remote/)
  assert.equal(remote['herdr sessions'], 'none')
  assert.equal(remote['terminal app'], 'no window raising')
})

test('첫 실행 카드: ovis 있음=세 선택+이대로 쓰기, 없음=이대로 쓰기만, 읽기 전용=닫기만(저장 없음), 다시 보기', () => {
  const view = (show, ask) => ({ first_run: { show, ask_click: ask } })
  assert.deepEqual(firstRunPlan(view(true, true)), { show: true, ask: true, actions: ['terminal', 'web', 'both', 'ok'] })
  assert.deepEqual(firstRunPlan(view(true, false)), { show: true, ask: false, actions: ['ok'] })
  assert.equal(firstRunPlan(view(false, true)).show, false, '한 번 닫은 뒤에는 다시 뜨지 않는다')
  assert.equal(firstRunPlan(view(true, true), { readonly: true }).show, false, '읽기 전용은 저절로 띄우지 않는다')
  assert.deepEqual(firstRunPlan(view(false, true), { readonly: true, force: true }), { show: true, ask: false, actions: ['close'] })
  assert.deepEqual(firstRunPlan(view(false, true), { force: true }).actions, ['terminal', 'web', 'both', 'ok'], '설정 패널에서 다시 볼 수 있다')
  assert.equal(firstRunPlan(null).show, false)
})

test('첫 실행 카드 안내: ovis가 없어 고를 것이 없으면 \'고른 값은 사람이 정한 설정으로 저장…\' 문장을 내지 않는다 — ko·en', () => {
  const view = (ask) => ({ first_run: { show: true, ask_click: ask } })
  assert.equal(firstRunHintKey(firstRunPlan(view(true))), 'frHint')
  assert.equal(firstRunHintKey(firstRunPlan(view(false))), 'frHintNoAsk')
  assert.equal(firstRunHintKey(firstRunPlan(view(false), { readonly: true, force: true })), 'frRo')
  for (const lang of ['ko', 'en']) {
    const T = I18N[lang]
    const noAsk = T[firstRunHintKey(firstRunPlan(view(false)))]
    assert.ok(noAsk, `${lang}.frHintNoAsk`)
    assert.notEqual(noAsk, T.frHint)
    assert.doesNotMatch(noAsk, lang === 'ko' ? /고른 값|사람이 정한/ : /what you pick|your own setting/i, lang)
    assert.match(T.frHint, lang === 'ko' ? /고른 값은 사람이 정한 설정/ : /What you pick is saved/)
  }
  assert.match(html, /<div class="hint">\$\{T\[firstRunHintKey\(plan\)\]\}<\/div>/, '카드가 이 함수로 문장을 고른다')
})

test('화면 배선: 카드 저장은 문지기(can) 뒤 POST /api/first-run, 패널 항목마다 출처, 위에 감지 요약, 다시 보기 단추', () => {
  assert.match(html, /async function firstRunChoose\(choice\) \{\n\s+if \(!can\(\)\) return denied\(\)/)
  assert.match(html, /post\('\/api\/first-run', choice \? \{ choice \} : \{\}\)/)
  const fn = html.match(/async function showSettings\(\) \{[\s\S]*?\n\}\n/)[0]
  for (const k of ["orig('front_app')", "orig('agent_cmd')", 'orig(k)', 'data-origin="click_target"', 'envSummaryHtml(data.autoconf, true)']) assert.ok(fn.includes(k), k)
  assert.ok(fn.indexOf('envSummaryHtml(data.autoconf, true)') < fn.indexOf('${langRow}\n  <div class="setrow cmdrow">'), '요약은 설정 항목보다 위')
  assert.match(html, /data-firstrun-open/)
  assert.match(html, /<div class="firstrun" id="firstrun" hidden><\/div>/)
  // 서버 기본값(client_defaults)은 브라우저에 옮겨 적지 않는다 — 자동 값을 사람 값으로 굳히지 않는다.
  assert.doesNotMatch(html, /localStorage\.setItem\([^)]*srvDefaults/)
  // 다른 설정만 저장해도 칸 열기 방식을 브라우저 값으로 굳히지 않는다.
  assert.match(html, /if \(pendingMode !== loadedMode\) setClickMode\(pendingMode\)/)
  for (const lang of ['ko', 'en']) for (const k of ['oPanel', 'oEnv', 'oEnvShell', 'oAuto', 'oDefault', 'oCard', 'oBrowser', 'envTitle', 'envUnknown', 'frQ', 'frTerminal', 'frOvis', 'frBoth', 'frOk', 'frClose', 'frRo', 'frReopen']) assert.ok(I18N[lang][k], `${lang}.${k}`)
})

test('서버: 읽기 전용이면 카드를 띄우지 않고 POST /api/first-run은 read_only, 아니면 선택이 패널 값으로 저장되고 다시 뜨지 않는다', async () => {
  setAutoValues({ values: { 'open_url:side': 'http://127.0.0.1:7318/?pane={pane}' }, reasons: {}, summary: { os: 'darwin', ovis: [{ port: 7318, session: 'side', confirmed: true }] } })
  const db = openDb(':memory:')
  const srv = createBoardServer(db)
  await new Promise((r) => srv.listen(0, '127.0.0.1', r))
  const base = `http://127.0.0.1:${srv.address().port}`
  const postFR = (body) => fetch(`${base}/api/first-run`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) })
  try {
    process.env.WHOSUP_READONLY = '1'
    assert.equal((await (await fetch(`${base}/api/autoconf`)).json()).first_run.show, false)
    const ro = await postFR({ choice: 'web' })
    assert.equal(ro.status, 403); assert.equal((await ro.json()).code, 'read_only')
    assert.equal(getSettings(db).click_target, 'terminal', '읽기 전용에서는 저장하지 않는다')
    delete process.env.WHOSUP_READONLY
    const v = await (await fetch(`${base}/api/autoconf`)).json()
    assert.equal(v.first_run.show, true); assert.equal(v.first_run.ask_click, true)
    assert.equal(v.client_defaults['whosup-open-url-on'], 'off', 'ovis가 있어도 기본은 터미널')
    assert.equal(v.client_defaults['whosup-open-url:side'], 'http://127.0.0.1:7318/?pane={pane}')
    const r = await (await postFR({ choice: 'web' })).json()
    assert.equal(r.ok, true)
    assert.equal(r.client_defaults['whosup-open-url-on'], 'on'); assert.equal(r.client_defaults['whosup-raise'], 'off')
    const s = await (await fetch(`${base}/api/settings`)).json()
    assert.equal(s.settings.click_target, 'web'); assert.deepEqual(s.origins.click_target, { source: 'panel' })
    assert.equal((await (await fetch(`${base}/api/autoconf`)).json()).first_run.show, false, '다시 뜨지 않는다')
  } finally { srv.close(); delete process.env.WHOSUP_READONLY; setAutoValues(null) }
})
