// 칸을 누르면 열 웹 주소(웹 터미널) — 화면(index.html)의 /*weburl*/ 덩어리를 그대로 읽어 시험한다.
// 이 기능에는 시험이 하나도 없었다. 주소 만들기·줄별 주소 고르기·누름 방식 판정·읽기 전용 동작을 여기서 고정한다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const html = readFileSync(new URL('../src/board/index.html', import.meta.url), 'utf8')
// 덩어리는 표식 한 쌍 사이의 글이다. 표식이 하나씩이고 순서가 맞아야 화면이 쓰는 그 코드를 시험하는 것이다.
const block = (name) => {
  const [a, b] = [`/*${name}*/`, `/*/${name}*/`]
  assert.equal(html.split(a).length, 2, `${a} 하나`); assert.equal(html.split(b).length, 2, `${b} 하나`)
  assert.ok(html.indexOf(a) < html.indexOf(b))
  return html.slice(html.indexOf(a), html.indexOf(b))
}
const chunk = block('weburl')
const { validOpenUrl, openUrlTemplateFor, buildOpenUrl, openUrlOf, clickModeOf, clickPlanOf } =
  new Function(`${chunk}; return { validOpenUrl, openUrlTemplateFor, buildOpenUrl, openUrlOf, clickModeOf, clickPlanOf }`)()
// 탭 열기: 화면의 openTab을 가짜 창으로 돌린다
const tabs = (window) => new Function('window', `${block('webtab')}; return { openTab, openedTabs }`)(window)
const store = (o) => (k) => (k in o ? o[k] : null)
const WEB = ['focus', 'close', 'resume', 'new', 'toggle', 'web']
const herdrCard = (desk, pane) => ({ runtime: 'herdr', ref: `${desk}/${pane}`, desk, desk_label: desk, pane, caps: WEB })
const coreCard = (space, label, t) => ({ runtime: 'herdr-core', ref: `default/${t}`, desk: `core:${space}`, desk_label: label, pane: t, caps: WEB })
const OVIS = 'http://127.0.0.1:7317/?pane={pane}'

test('주소 꼴: http(s)로 시작하고 {pane}이 들어가야 한다', () => {
  assert.equal(validOpenUrl(OVIS), true)
  assert.equal(validOpenUrl('https://term.example.com/{session}/{pane}'), true)
  for (const bad of ['', null, undefined, 'http://127.0.0.1:7317/', 'ftp://x/{pane}', 'javascript:alert(1)//{pane}', 'http://a b/{pane}']) assert.equal(validOpenUrl(bad), false, String(bad))
  // 꼴은 맞아 보여도 주소로 읽히지 않는 것(포트에 글자, 호스트 없음, 깨진 호스트)
  for (const bad of ['http://127.0.0.1:731x/?pane={pane}', 'http:///?pane={pane}', 'http://[bad]/{pane}']) assert.equal(validOpenUrl(bad), false, bad)
  assert.equal(validOpenUrl('http://{session}.term.example.com/{pane}'), true)
  assert.equal(buildOpenUrl(herdrCard('a b', 'w1:p3'), 'http://{session}.term.example.com/{pane}'), '')   // 자리를 채운 결과가 주소가 아니면 열지 않는다
})

test('주소 만들기: {pane}·{session}을 채우고 칸 id의 특수 문자를 인코딩한다', () => {
  assert.equal(buildOpenUrl(herdrCard('alpha', 'w1:p3'), OVIS), 'http://127.0.0.1:7317/?pane=w1%3Ap3')
  assert.equal(buildOpenUrl(herdrCard('beta', 'w2:p1'), 'https://t.example.com/{session}?pane={pane}&s={session}'), 'https://t.example.com/beta?pane=w2%3Ap1&s=beta')
  // 칸 id에 '/'가 들어 있어도 전체가 칸 id다
  assert.equal(buildOpenUrl(herdrCard('alpha', 'w1/p3'), OVIS), 'http://127.0.0.1:7317/?pane=w1%2Fp3')
  // Herdr 앱 카드: {session}은 공간 이름, {pane}은 터미널 주소
  assert.equal(buildOpenUrl(coreCard('spA', 'my project', 't4'), 'http://h/{session}/{pane}'), 'http://h/my%20project/t4')
  // 주소로 열 수 없는 카드(caps에 web 없음)·틀린 주소·카드 없음 → ''
  assert.equal(buildOpenUrl({ ...herdrCard('alpha', 'w1:p3'), caps: ['focus'] }, OVIS), '')
  assert.equal(buildOpenUrl(herdrCard('alpha', 'w1:p3'), 'http://127.0.0.1:7317/'), '')
  assert.equal(buildOpenUrl(null, OVIS), '')
})

test('줄별 주소: herdr 세션은 자기 주소가 먼저, 없으면 기본 주소 (세션마다 웹 터미널 포트가 다른 경우)', () => {
  const get = store({ 'whosup-open-url': OVIS, 'whosup-open-url:beta': 'http://127.0.0.1:7400/?pane={pane}' })
  assert.equal(openUrlOf(herdrCard('alpha', 'w1:p3'), get), 'http://127.0.0.1:7317/?pane=w1%3Ap3')
  assert.equal(openUrlOf(herdrCard('beta', 'w1:p2'), get), 'http://127.0.0.1:7400/?pane=w1%3Ap2')
  // 기본 주소 없이 줄별 주소만 있어도 그 줄은 열린다. 주소가 없는 줄은 열지 않는다(터미널 이동만)
  const only = store({ 'whosup-open-url:beta': 'http://127.0.0.1:7400/?pane={pane}' })
  assert.equal(openUrlOf(herdrCard('beta', 'w1:p2'), only), 'http://127.0.0.1:7400/?pane=w1%3Ap2')
  assert.equal(openUrlOf(herdrCard('alpha', 'w1:p3'), only), '')
  // 줄에 적어 둔 주소의 꼴이 틀렸으면 그 줄은 웹으로 열지 않는다 — 기본 주소(다른 세션의 웹 터미널)로 넘어가지 않는다
  const broken = store({ 'whosup-open-url': OVIS, 'whosup-open-url:beta': 'not a url' })
  assert.equal(openUrlOf(herdrCard('beta', 'w1:p2'), broken), '')
  assert.equal(openUrlOf(herdrCard('alpha', 'w1:p3'), broken), 'http://127.0.0.1:7317/?pane=w1%3Ap3')   // 다른 줄은 그대로
  assert.equal(openUrlOf(herdrCard('beta', 'w1:p2'), store({ 'whosup-open-url': OVIS, 'whosup-open-url:beta': '' })), 'http://127.0.0.1:7317/?pane=w1%3Ap2')   // 비워 둔 줄은 기본 주소
})

test('Herdr 앱 줄: 그 줄에 적은 주소가 있을 때만 웹으로 연다. 기본 주소(herdr용)는 쓰지 않는다', () => {
  const get = store({ 'whosup-open-url': OVIS, 'whosup-open-url:core:spB': 'http://10.0.0.5:9000/t/{pane}' })
  assert.equal(openUrlOf(coreCard('spA', 'my project', 't4'), get), '')                     // → Herdr 앱 이동
  assert.equal(openUrlOf(coreCard('spB', 'other', 't7'), get), 'http://10.0.0.5:9000/t/t7')
  assert.equal(openUrlTemplateFor(coreCard('spA', 'my project', 't4'), get), '')
})

test('웹 주소를 꺼 두었으면 주소가 있어도 열지 않는다', () => {
  const get = store({ 'whosup-open-url': OVIS, 'whosup-open-url-on': 'off' })
  assert.equal(openUrlOf(herdrCard('alpha', 'w1:p3'), get), '')
})

test('누름 방식: 맞는 주소가 하나라도 있고 켜져 있으면 web(창 올리기 끔) 또는 both, 아니면 terminal', () => {
  const mode = (o) => clickModeOf(store(o), Object.keys(o))
  assert.equal(mode({}), 'terminal')
  assert.equal(mode({ 'whosup-open-url': OVIS }), 'both')
  assert.equal(mode({ 'whosup-open-url': OVIS, 'whosup-raise': 'off' }), 'web')
  assert.equal(mode({ 'whosup-open-url': OVIS, 'whosup-open-url-on': 'off' }), 'terminal')
  assert.equal(mode({ 'whosup-open-url': 'broken' }), 'terminal')
  assert.equal(mode({ 'whosup-open-url:core:spB': 'http://h/{pane}' }), 'both')            // 줄별 주소만 있어도 웹 방식이 된다
})

test('한 번의 클릭이 할 일: 설정 패널이 보여 주는 방식과 실제 요청(창 올리기)이 같은 판정을 쓴다', () => {
  const plan = (c, o) => clickPlanOf(c, store(o), Object.keys(o))
  const A = herdrCard('alpha', 'w1:p3'), CORE = coreCard('spA', 'my project', 't4')
  const url = 'http://127.0.0.1:7317/?pane=w1%3Ap3'
  assert.deepEqual(plan(A, {}), { url: '', raise: true })                                                   // 터미널 창
  assert.deepEqual(plan(A, { 'whosup-open-url': OVIS }), { url, raise: true })                              // 둘 다
  assert.deepEqual(plan(A, { 'whosup-open-url': OVIS, 'whosup-raise': 'off' }), { url, raise: false })      // 웹 주소만
  // 패널이 '터미널 창'으로 보이는 저장 상태에서는 창을 올린다(예전 값 whosup-raise=off가 남아 있어도)
  assert.deepEqual(plan(A, { 'whosup-raise': 'off' }), { url: '', raise: true })
  assert.deepEqual(plan(A, { 'whosup-open-url': OVIS, 'whosup-open-url-on': 'off', 'whosup-raise': 'off' }), { url: '', raise: true })
  // 웹 주소만 고른 브라우저에서 주소가 없는 Herdr 앱 카드: 설정 안내대로 Herdr 앱으로 간다(창을 올린다)
  assert.deepEqual(plan(CORE, { 'whosup-open-url': OVIS, 'whosup-raise': 'off' }), { url: '', raise: true })
  assert.deepEqual(plan(CORE, { 'whosup-open-url:core:spA': 'http://h/{pane}', 'whosup-raise': 'off' }), { url: 'http://h/t4', raise: false })
  // 화면은 이 계획대로 요청한다: 카드 클릭은 plan.raise를 싣고, 요청에 적은 값이 기본값을 이긴다
  // 열쇠는 이 브라우저 저장값 + 서버 기본값(client_defaults). 브라우저 저장값이 먼저다(lsGet).
  assert.match(html, /const clickPlan = \(c\) => clickPlanOf\(c, lsGet, lsKeys\(\)\)/)
  assert.match(html, /const lsKeys = \(\) => \[\.\.\.new Set\(\[\.\.\.Object\.keys\(localStorage\), \.\.\.Object\.keys\(srvDefaults\)\]\)\]/)
  assert.match(html, /const lsGet = \(k\) => localStorage\.getItem\(k\) \?\? /)
  assert.match(html, /post\('\/api\/open', \{ id, seq, raise: plan\.raise \}\)/)
  assert.match(html, /JSON\.stringify\(\{ raise: raiseOn\(\), \.\.\.body \}\)/)
})

test('탭 열기: 줄마다 이름 붙인 탭 하나. 누를 때마다 그 주소로 보낸다(같은 주소여도). 막히면 그렇다고 돌려준다', () => {
  // 가짜 브라우저: 이름이 같은 탭이 살아 있으면 그 탭을 그 주소로 보내고 돌려준다(브라우저의 이름 붙인 창 규칙)
  const named = new Map()
  const opens = []
  const browser = { open: (url, name) => {
    opens.push([url, name])
    let w = named.get(name)
    if (!w || w.closed) { w = { closed: false, focused: 0, href: null, focus() { this.focused += 1 } }; named.set(name, w) }
    w.href = url
    return w
  } }
  const { openTab } = tabs(browser)
  const a = openTab('alpha', 'http://h/?pane=t1')
  assert.deepEqual([a.ok, a.fresh, a.win.href, a.win.focused], [true, true, 'http://h/?pane=t1', 1])
  assert.deepEqual(opens[0], ['http://h/?pane=t1', 'whosup-alpha'])
  // 그 탭 안에서 다른 칸으로 옮겨 간 뒤 같은 카드를 다시 누른다: 같은 탭을 그 주소로 다시 보낸다(건너뛰지 않는다)
  a.win.href = 'http://h/?pane=t2'
  const b = openTab('alpha', 'http://h/?pane=t1')
  assert.deepEqual([b.ok, b.fresh, b.win === a.win, b.win.href, b.win.focused, opens.length], [true, false, true, 'http://h/?pane=t1', 2, 2])
  openTab('alpha', 'http://h/?pane=t1')                                                                     // 탭이 이미 그 주소에 있어 보여도 다시 보낸다
  assert.equal(opens.length, 3)
  // 다른 줄은 다른 탭, 닫은 탭은 새로 연 것으로 센다
  const c = openTab('beta', 'http://h2/?pane=t1')
  assert.deepEqual([c.fresh, c.win === a.win, opens[3][1]], [true, false, 'whosup-beta'])
  a.win.closed = true
  assert.equal(openTab('alpha', 'http://h/?pane=t3').fresh, true)
  // 브라우저가 막았다
  const blocked = tabs({ open: () => null })
  assert.deepEqual(blocked.openTab('alpha', 'http://h/?pane=t1'), { ok: false })
  const throws = tabs({ open: () => { throw new Error('blocked') } })
  assert.deepEqual(throws.openTab('alpha', 'http://h/?pane=t1'), { ok: false })
  // 화면은 막힌 탭을 서버 쪽 성공 문구로 덮지 않는다
  assert.match(html, /if \(tab && !tab\.ok\) toast\(T\.popupBlocked, true\); else toast\(msgOf\(data\), !ok\)/)
  for (const lang of ['브라우저가 새 탭을 막았습니다', 'The browser blocked the new tab']) assert.ok(html.includes(lang))
})

test('읽기 전용: 카드 누르기는 웹 주소 열기까지 포함해 전부 막힌다(README의 읽기 전용 설명과 같은 동작)', () => {
  // openCard의 첫 줄이 읽기 전용 게이트이고, 주소 계산·탭 열기는 그 뒤에 있다
  const open = html.slice(html.indexOf('async function openCard(id) {'))
  const gate = open.indexOf('if (!can()) return denied()')
  assert.ok(gate > 0 && gate < open.indexOf('clickPlan(c)') && gate < open.indexOf('openTab('))
  // 판을 아직 못 받았으면(읽기 전용인지 모른다) 막는다
  assert.match(html, /const can = \(\) => board\?\.readonly === false/)
  assert.match(html, /const denied = \(\) => toast\(board \? T\.codes\.read_only : T\.loading, true\)/)   // 막힌 이유를 그대로: 읽기 전용 / 아직 불러오는 중
  const readme = readFileSync(new URL('../README.md', import.meta.url), 'utf8')
  const row = readme.split('\n').find((l) => l.startsWith('| Where a click goes'))
  assert.match(row, /read-only/i)                             // 다른 기기에서 쓸 때의 안내가 읽기 전용과 어긋나지 않게 적혀 있다
  assert.match(readme.split('\n').find((l) => l.startsWith('| Read-only mode')), /blocks clicks/)
})
