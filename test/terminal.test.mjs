// 이동 시 앞으로 올릴 터미널 찾기: 앱 인스턴스가 여러 개여도 그 세션을 붙든 인스턴스만 고른다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { appToOpen, isOffApp, openerFor, openerForArgv, terminalHostsFor, terminalPidsFor } from '../src/runtime/herdr.mjs'
import { openDb } from '../src/db.mjs'
import { frontAppChoice, getSettings, setAutoValues, setSettings, settingSources } from '../src/settings.mjs'
import { _setPlatform } from '../src/platform.mjs'

const PS = `
  100     1 /Applications/Ghostty.app/Contents/MacOS/ghostty
  200     1 /Applications/Ghostty.app/Contents/MacOS/ghostty
  300     1 /Applications/Ghostty.app/Contents/MacOS/ghostty
  101   100 /usr/bin/login -flp me /bin/bash --noprofile --norc -c exec -l /Users/me/.local/bin/herdr-launch
  102   101 /opt/homebrew/bin/herdr --session main
  201   200 /usr/bin/login -flp me /bin/bash --noprofile --norc -c exec -l /Users/me/.local/bin/herdr-launch
  202   201 /opt/homebrew/bin/herdr --session side
  301   300 /usr/bin/login -flp me /bin/zsh
  302   301 herdr
  400     1 /opt/homebrew/bin/herdr --session main server
  401     1 /opt/homebrew/bin/herdr server
  500     1 /Applications/iTerm.app/Contents/MacOS/iTerm2
  501   500 /opt/homebrew/bin/herdr --session air
`

test('jump: 세션을 붙든 터미널 인스턴스만 고른다(서버·다른 세션 제외)', () => {
  assert.deepEqual(terminalPidsFor(PS, 'main', 'Ghostty'), [100])
  assert.deepEqual(terminalPidsFor(PS, 'side', 'Ghostty'), [200])
  assert.deepEqual(terminalPidsFor(PS, 'default', 'Ghostty'), [300])
})

test('jump: 창이 없는 세션·다른 앱의 창은 고르지 않는다', () => {
  assert.deepEqual(terminalPidsFor(PS, 'air', 'Ghostty'), [])
  assert.deepEqual(terminalPidsFor(PS, 'air', 'iTerm'), [500])
  assert.deepEqual(terminalPidsFor(PS, 'nope', 'Ghostty'), [])
})

// ── 터미널 앱 자동 감지·새 창 열기(UX 개편 2차 F1~F3) ──
const PS2 = `
  600     1 /Applications/Visual Studio Code.app/Contents/MacOS/Electron
  610   600 /Applications/Visual Studio Code.app/Contents/Frameworks/Code Helper (Plugin).app/Contents/MacOS/Code Helper (Plugin) --type=utility
  611   610 /bin/zsh -il
  612   611 /opt/homebrew/bin/herdr --session code
  700     1 /System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal
  701   700 login -pf me
  702   701 -zsh
  703   702 /opt/homebrew/bin/herdr --session term
  800     1 sshd: me@ttys001
  801   800 /opt/homebrew/bin/herdr --session remote
`

test('auto: 앱을 정하지 않아도 그 세션을 보여 주는 앱을 찾는다(앱 이름과 함께)', () => {
  assert.deepEqual(terminalHostsFor(PS, 'main'), [{ pid: 100, app: 'Ghostty' }])
  assert.deepEqual(terminalHostsFor(PS, 'air'), [{ pid: 500, app: 'iTerm' }])
  assert.deepEqual(terminalHostsFor(PS2, 'term'), [{ pid: 700, app: 'Terminal' }])
  assert.deepEqual(terminalHostsFor(PS2, 'remote'), [], 'SSH로 붙은 클라이언트에는 올릴 창이 없다')
})

test('auto: 앱 안의 도우미 앱은 건너뛰고 창을 가진 본체를 고른다', () => {
  assert.deepEqual(terminalHostsFor(PS2, 'code'), [{ pid: 600, app: 'Visual Studio Code' }])
})

test('auto: 세션을 가리지 않으면 herdr를 보여 주는 앱 전부(서버 프로세스 제외), 최근 것 먼저', () => {
  assert.deepEqual(terminalHostsFor(PS, null).map((h) => h.app), ['iTerm', 'Ghostty', 'Ghostty', 'Ghostty'])
  assert.deepEqual(terminalHostsFor(PS, null).map((h) => h.pid), [500, 300, 200, 100])
})

test('새 창: Ghostty와 Terminal은 여는 방법이 있고, 그 밖의 앱은 없다', () => {
  const g = openerFor('Ghostty', 'side', '/opt/homebrew/bin/herdr')
  assert.deepEqual(g.args, ['-na', 'Ghostty', '--args', '--command=/opt/homebrew/bin/herdr --session side'])
  // Ghostty는 인자가 붙은 명령을 셸로 돌린다: 공백·따옴표가 든 인자는 감싸서 인자 경계를 지킨다(평범한 인자는 그대로)
  assert.deepEqual(openerFor('Ghostty', 'side', "/Users/a b/it's/herdr").args.at(-1), "--command='/Users/a b/it'\\''s/herdr' --session side")
  assert.deepEqual(openerForArgv('Ghostty', ['/usr/bin/env', 'XDG_STATE_HOME=/work/x state', 'HC_SESSION=default', 'hc', 'attach', 't4'], 'core-t4').args.at(-1),
    "--command=/usr/bin/env 'XDG_STATE_HOME=/work/x state' HC_SESSION=default hc attach t4")
  const t = openerFor('terminal', 'default', "/Users/a b/it's/herdr")
  assert.deepEqual(t.args.slice(0, 2), ['-a', 'Terminal'])
  assert.match(t.script, /open-default\.command$/)
  assert.equal(t.body, "#!/bin/sh\nexec '/Users/a b/it'\\''s/herdr'\n", '경로의 공백·따옴표를 셸에 안전하게 넘긴다')
  assert.equal(openerFor('Terminal', 'side', '/x/herdr').body, "#!/bin/sh\nexec '/x/herdr' '--session' 'side'\n")
  assert.equal(openerFor('iTerm', 'side'), null)
})

test('새 창을 열 앱: 고른 앱 > 지금 herdr를 보여 주는 앱(여는 방법을 아는 것) > 기본 터미널', () => {
  assert.equal(appToOpen('iTerm', PS), 'iTerm', '고른 앱이 먼저')
  assert.equal(appToOpen('', PS), 'Ghostty', '안 골랐으면 떠 있는 앱 — iTerm은 여는 방법을 몰라 건너뛴다')
  assert.equal(appToOpen('', PS2), 'Terminal')
  assert.equal(appToOpen('', ''), 'Terminal', '아무것도 없으면 기본 터미널')
})

test('자동 세팅 앱(L4)은 고른 앱이 아니라 새 창 앱의 후보: 떠 있는 앱 > 자동 앱 > 기본 터미널, off는 끔', () => {
  assert.equal(appToOpen('', PS, 'Terminal'), 'Ghostty', '떠 있는 앱이 자동 앱보다 먼저')
  assert.equal(appToOpen('', '', 'Ghostty'), 'Ghostty', '떠 있는 앱이 없으면 자동 앱')
  assert.equal(appToOpen('', '', 'iTerm'), 'Terminal', '여는 방법을 모르는 자동 앱이면 기본 터미널')
  assert.equal(appToOpen('Terminal', '', 'Ghostty'), 'Terminal', '사람이 고른 앱이 먼저')
  for (const v of ['off', 'OFF', ' none ', '끔']) assert.equal(isOffApp(v), true, v)
  for (const v of ['', 'Ghostty', 'offline']) assert.equal(isOffApp(v), false, v)
  const prev = process.env.FRONT_APP
  delete process.env.FRONT_APP
  const db = openDb(':memory:')
  try {
    setAutoValues({ values: { front_app: 'Ghostty' } })
    assert.deepEqual(frontAppChoice(db), ['', 'Ghostty'], '자동 값은 사람 값 자리로 가지 않는다')
    process.env.FRONT_APP = 'iTerm'
    assert.deepEqual(frontAppChoice(db), ['iTerm', 'Ghostty'])
    setSettings(db, { front_app: 'Terminal' })
    assert.deepEqual(frontAppChoice(db), ['Terminal', 'Ghostty'])
  } finally {
    setAutoValues(null)
    if (prev === undefined) delete process.env.FRONT_APP; else process.env.FRONT_APP = prev
  }
})

test('설정 front_app: 기본은 빈 값(자동), 저장값 > FRONT_APP, 이상한 글자는 거절, 비우면 되돌아간다', () => {
  const prev = process.env.FRONT_APP
  delete process.env.FRONT_APP
  _setPlatform('darwin')   // 맥·리눅스의 앱 이름 규칙(윈도우는 경로·창 제목도 받는다 — windows.test.mjs)
  try {
    const db = openDb(':memory:')
    assert.equal(getSettings(db).front_app, '')
    assert.equal(settingSources(db).front_app, 'default')
    process.env.FRONT_APP = 'Ghostty'
    assert.equal(getSettings(db).front_app, 'Ghostty')
    assert.equal(settingSources(db).front_app, 'env')
    assert.equal(setSettings(db, { front_app: 'Terminal' }).ok, true)
    assert.equal(getSettings(db).front_app, 'Terminal', '설정 패널 값이 환경변수보다 먼저')
    assert.equal(settingSources(db).front_app, 'saved')
    for (const bad of ['Term"inal', 'a; echo hi', 'x'.repeat(61), 'tell app\nfoo']) assert.equal(setSettings(db, { front_app: bad }).ok, false, bad)
    assert.equal(getSettings(db).front_app, 'Terminal')
    assert.equal(setSettings(db, { front_app: null }).ok, true)
    assert.equal(getSettings(db).front_app, 'Ghostty', '비우면 환경변수로')
    delete process.env.FRONT_APP
    assert.equal(getSettings(db).front_app, '', '환경변수도 없으면 자동')
  } finally { _setPlatform(null); if (prev === undefined) delete process.env.FRONT_APP; else process.env.FRONT_APP = prev }
})

test('새 창에서 아무 명령이나 돌리기(herdr-core 터미널을 hc attach로 열 때): Ghostty는 --command, Terminal은 실행 파일', () => {
  const g = openerForArgv('Ghostty', ['hc', 'attach', 't4'], 'core-t4')
  assert.deepEqual(g.args, ['-na', 'Ghostty', '--args', '--command=hc attach t4'])
  const t = openerForArgv('Terminal', ['/usr/bin/env', 'HC_SESSION=x y', 'hc', 'attach', 't4'], 'core-t4')
  assert.match(t.script, /open-core-t4\.command$/)
  assert.equal(t.body, "#!/bin/sh\nexec '/usr/bin/env' 'HC_SESSION=x y' 'hc' 'attach' 't4'\n")
  assert.equal(openerForArgv('iTerm', ['hc'], 'k'), null)
})
