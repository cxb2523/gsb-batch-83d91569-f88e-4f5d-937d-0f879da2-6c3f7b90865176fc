// herdr-core 런타임 — 조작(이동·닫기·이어서 열기·새 세션·줄 끄고 켜기)과 서버의 길 찾기.
// 가짜 코어(소켓)와 가짜 herdr-app만 쓴다. 실제 코어·앱·herdr·터미널 창은 건드리지 않는다(raise:false).
import { test, after } from 'node:test'
import assert from 'node:assert/strict'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { startFakeCore, term, agentTerm } from '../test-support/fake-core.mjs'
import { fileURLToPath } from 'node:url'

const dir = mkdtempSync(join(tmpdir(), 'wo-'))
const SOCK = join(dir, 'core.sock')
const LOG = join(dir, 'app.log')
process.env.HC_SOCKET = SOCK
process.env.HC_SESSION = 'whosuptest-unit'
// 코어의 위치를 정하는 값은 이 시험이 정한 것만 쓴다. 시험을 돌리는 기계의 XDG_* 값(예: 리눅스의 XDG_RUNTIME_DIR)이
// 새 창 명령에 섞여 들어가 기대값과 달라지지 않게.
delete process.env.XDG_STATE_HOME
delete process.env.XDG_RUNTIME_DIR
process.env.HERDR_APP_BIN = fileURLToPath(new URL('../test-support/fake-herdr-app.mjs', import.meta.url))
chmodSync(process.env.HERDR_APP_BIN, 0o755)
process.env.FAKE_APP_LOG = LOG
process.env.HERDR_BIN = join(dir, 'no-herdr')
delete process.env.HERDR_BIN_PATH
process.env.WHOSUP_STATE_DIR = join(dir, 'state')
process.env.CLAUDE_PROJECTS_DIR = join(dir, 'claude', 'projects')
process.env.WHOSUP_NO_EVENTS = '1'
process.env.AGENT_CMD = 'claude'
delete process.env.WHOSUP_READONLY
mkdirSync(process.env.CLAUDE_PROJECTS_DIR, { recursive: true })
const WORK = join(dir, 'work'); mkdirSync(WORK)

const core = await import('../src/runtime/core.mjs')
const { collectAll, noteChange } = await import('../src/runtime/index.mjs')
const { createBoardServer, openSession, resumeSession, markGoneNow, _clearResumeHolds } = await import('../src/board/server.mjs')
const { clearContextCache } = await import('../src/board/context.mjs')
const { openDb } = await import('../src/db.mjs')

const fake = await startFakeCore(SOCK)
after(async () => { await fake.close() })
const appCalls = () => (existsSync(LOG) ? readFileSync(LOG, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l)) : [])
const doCalls = () => appCalls().filter((a) => a[0] === 'do').map((a) => [a[1], JSON.parse(a[2])])
const reset = () => { fake.override = null; fake.terminals.clear(); fake.calls.length = 0; writeFileSync(LOG, ''); delete process.env.FAKE_APP_MODE; delete process.env.FAKE_APP_NO_KEEP; delete process.env.FAKE_APP_FOLDER; clearContextCache(); _clearResumeHolds() }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const SID2 = '22222222-2222-4222-8222-222222222222'
const SPACE_B = { 'herdr.space': 'spB', 'herdr.tab': 'tb2', where: 'other / 1' }
const SPACE = { 'herdr.space': 'spA', 'herdr.tab': 'tb1', where: 'my project / 1' }
const SID = '11111111-1111-4111-8111-111111111111'
const idOf = (db, t) => db.prepare('SELECT id FROM session WHERE runtime_ref = ? ORDER BY id DESC').get(`whosuptest-unit/${t}`).id
const liveAddrs = () => [...fake.terminals.values()].filter((t) => t.state === 'live').map((t) => t.address)
// 대화 기록 파일(이어서 열기 대상)
const transcript = (sid, cwd) => { const d = join(process.env.CLAUDE_PROJECTS_DIR, cwd.replace(/[^A-Za-z0-9]/g, '-')); mkdirSync(d, { recursive: true }); writeFileSync(join(d, `${sid}.jsonl`), `${JSON.stringify({ type: 'user', timestamp: new Date().toISOString(), message: { content: 'hello' } })}\n`) }

test('이동: Herdr 앱에 그 터미널의 칸으로 가라고 시킨다(pane.focus --terminal)', async () => {
  reset()
  fake.add(agentTerm('t4', 'blocked', { kind: 'question', msg: 'answer: go?', labels: SPACE }))
  const db = openDb(':memory:'); await collectAll(db)
  const r = await openSession(db, idOf(db, 't4'), 1, { raise: false })
  assert.deepEqual([r.ok, r.code, r.window], [true, 'focused', 'skipped'])
  assert.deepEqual(doCalls(), [['pane.focus', { terminal: 't4' }]])
})

test('이동: 답변 도착 카드를 보드에서 열면 본 것으로 적는다 → 다음 수집에서 쉼으로 내려간다(앱 없이 쓸 때도)', async () => {
  reset()
  process.env.FAKE_APP_MODE = 'no_window'
  fake.add(agentTerm('t4', 'done', { labels: SPACE, turn: 2 }))
  const db = openDb(':memory:'); await collectAll(db)
  const id = idOf(db, 't4')
  assert.equal(db.prepare('SELECT status FROM session WHERE id = ?').get(id).status, 'done')
  await openSession(db, id, 1.5, { raise: false })   // 순번은 뒤 시험들보다 작게(마지막 클릭만 이긴다)
  assert.equal(fake.terminals.get('t4').labels['whosup.seen'], '2')   // 이동이 끝났으면 이미 적혀 있다(따로 기다리지 않는다)
  await collectAll(db)
  assert.equal(db.prepare('SELECT status FROM session WHERE id = ?').get(id).status, 'idle')
  // 새 턴이 끝나면 다시 답변 도착
  fake.set('t4', { turn: 3 }); await collectAll(db)
  assert.equal(db.prepare('SELECT status FROM session WHERE id = ?').get(id).status, 'done')
  // 끝내자마자 idle로 돌아가는 에이전트(Codex)의 답변 도착 카드도 열면 본 것으로 적힌다(격리 코어의 실제 Codex에서 찾은 빈틈)
  fake.set('t4', { status: { app: 'codex', state: 'idle' }, turn: 4 }); await collectAll(db)
  const cid = idOf(db, 't4')                         // 다른 에이전트가 그 터미널을 차지했다: 새 카드다
  assert.notEqual(cid, id)
  assert.equal(db.prepare('SELECT status FROM session WHERE id = ?').get(cid).status, 'done')
  await openSession(db, cid, 1.6, { raise: false })
  assert.equal(fake.terminals.get('t4').labels['whosup.seen'], '4')
  await collectAll(db)
  assert.equal(db.prepare('SELECT status FROM session WHERE id = ?').get(cid).status, 'idle')
  // 쉬는 카드를 여는 것은 아무것도 적지 않는다
  fake.calls.length = 0
  await openSession(db, cid, 1.7, { raise: false })
  assert.equal(fake.calls.filter((c) => c.method === 'terminal.label').length, 0)
})

test('이동: 앱에 그 터미널을 보여 주는 칸이 없으면 칸을 만들어 달라고 한 뒤 간다(terminal.keep)', async () => {
  reset()
  fake.add(term('t5'))                                      // 공간 밖 터미널
  const db = openDb(':memory:'); await collectAll(db)
  const r = await openSession(db, idOf(db, 't5'), 2, { raise: false })
  assert.equal(r.ok, true)
  assert.deepEqual(doCalls().map((c) => c[0]), ['pane.focus', 'terminal.keep', 'pane.focus'])
})

test('이동: 앱 창이 없으면(종료 코드 2) 오류 없이 넘어간다 — 창을 올리지 않는 클릭은 건너뜀으로 끝난다', async () => {
  reset()
  process.env.FAKE_APP_MODE = 'no_window'
  fake.add(agentTerm('t4', 'done', { labels: SPACE }))
  const db = openDb(':memory:'); await collectAll(db)
  const r = await openSession(db, idOf(db, 't4'), 3, { raise: false })
  assert.deepEqual([r.ok, r.window], [true, 'skipped'])
  assert.deepEqual(doCalls().map((c) => c[0]), ['pane.focus'])        // 창이 없으면 칸 만들기를 시도하지 않는다
})

test('이동(창 올리기 켬): 앱이 있으면 앱을 앞으로, 앱 창이 없으면 터미널 창에서 hc attach로 연다', async () => {
  reset()
  const seen = []
  core._setWindowOps({ raiseApp: async (name, split) => { seen.push(['raise', name, split]); return 'raised' }, openWindowRunning: async (...a) => { seen.push(['open', ...a]); return 'opened' } })
  // 새 창 명령: macOS·리눅스는 /usr/bin/env K=V … , 윈도우는 [hc, attach, t4]와 환경변수 묶음(PowerShell $env:로 넣는다)
  const want = (...kv) => (process.platform === 'win32' ? [['hc', 'attach', 't4'], 'core-t4', Object.fromEntries(kv)] : [['/usr/bin/env', ...kv.map(([k, v]) => `${k}=${v}`), 'hc', 'attach', 't4'], 'core-t4'])
  const base = [['HC_SESSION', 'whosuptest-unit'], ['HC_SOCKET', SOCK]]
  fake.add(agentTerm('t4', 'done', { labels: SPACE }))
  const db = openDb(':memory:'); await collectAll(db)
  const a = await openSession(db, idOf(db, 't4'), 10)
  assert.deepEqual([a.ok, a.code, a.window], [true, 'focused', 'raised'])
  assert.deepEqual(seen, [['raise', 'Herdr', 0]])
  process.env.FAKE_APP_MODE = 'no_window'; seen.length = 0
  const b = await openSession(db, idOf(db, 't4'), 11)
  assert.deepEqual([b.ok, b.code, b.window], [true, 'focused_opened', 'opened'])
  // 새 창은 이 서버의 환경을 물려받지 않는다: 코어의 위치를 정하는 값(HC_SESSION·HC_SOCKET·XDG_*)을 함께 넘겨 같은 코어에 붙게 한다
  assert.deepEqual(seen, [['open', ...want(...base)]])
  process.env.XDG_STATE_HOME = '/work/x state'; seen.length = 0
  try { await openSession(db, idOf(db, 't4'), 11.5) } finally { delete process.env.XDG_STATE_HOME }
  assert.deepEqual(seen[0].slice(1), want(...base, ['XDG_STATE_HOME', '/work/x state']))
  process.env.XDG_RUNTIME_DIR = '/run/user/1001'; seen.length = 0                                     // 리눅스 데스크톱·CI에 흔한 값
  try { await openSession(db, idOf(db, 't4'), 11.7) } finally { delete process.env.XDG_RUNTIME_DIR }
  // 윈도우 새 창에는 넘기지 않는다: POSIX 로그인 세션 폴더라 그곳의 hc에는 뜻이 없다(소켓은 HC_SOCKET으로 이미 정해졌다)
  assert.deepEqual(seen[0].slice(1), process.platform === 'win32' ? want(...base) : want(...base, ['XDG_RUNTIME_DIR', '/run/user/1001']))
  // herdr-app 명령이 아예 없는 기계도 같다(오류 없이 터미널 창으로)
  delete process.env.FAKE_APP_MODE; seen.length = 0
  const bin = process.env.HERDR_APP_BIN; process.env.HERDR_APP_BIN = join(dir, 'no-herdr-app')
  try { const c = await openSession(db, idOf(db, 't4'), 12); assert.deepEqual([c.ok, c.window, seen[0][0]], [true, 'opened', 'open']) } finally { process.env.HERDR_APP_BIN = bin }
  core._setWindowOps({ raiseApp: async () => 'off', openWindowRunning: async () => 'off' })
})

test('이동: 이미 끝난 터미널이면 오류 대신 최근 닫힘으로 옮긴다', async () => {
  reset()
  fake.add(agentTerm('t4', 'idle', { labels: SPACE }))
  const db = openDb(':memory:'); await collectAll(db)
  const id = idOf(db, 't4')
  fake.terminals.get('t4').state = 'finished'
  const r = await openSession(db, id, 40, { raise: false })   // 순번은 앞 시험들보다 커야 한다(마지막 클릭만 이긴다)
  assert.deepEqual([r.ok, r.code], [true, 'pane_gone'])
  assert.deepEqual(Object.values(db.prepare('SELECT archived, status FROM session WHERE id = ?').get(id)), [1, 'gone'])
})

test('닫기: 앱이 열려 있으면 그 칸을 닫고(pane.close), 없으면 터미널을 끝낸다(terminal.kill)', async () => {
  reset()
  fake.add(agentTerm('t4', 'idle', { labels: SPACE })); fake.add(agentTerm('t6', 'idle', { labels: SPACE }))
  await core.closePane('whosuptest-unit/t4')
  assert.deepEqual(doCalls(), [['pane.close', { pane: 'pe-t4' }]])
  assert.deepEqual(liveAddrs(), ['t6'])
  process.env.FAKE_APP_MODE = 'no_window'
  await core.closePane('whosuptest-unit/t6')
  assert.ok(fake.calls.some((c) => c.method === 'terminal.kill' && c.params.terminal === 't6'))
  assert.deepEqual(liveAddrs(), [])
  await assert.rejects(core.closePane('whosuptest-unit/t99'), /not found/)
})

test('이어서 열기: 셸 칸에 실행 명령을 쳐 넣는다. 에이전트가 도는 칸에는 넣지 않는다', async () => {
  reset()
  transcript(SID, WORK)
  fake.add(term('t7', { labels: SPACE, cwd: WORK, foreground: { argv: ['/bin/zsh', '-l'], cwd: WORK, name: 'zsh', pid: 70007 } }))
  fake.add(agentTerm('t8', 'working', { labels: SPACE, cwd: WORK }))
  const db = openDb(':memory:'); await collectAll(db)
  const r = await resumeSession(db, idOf(db, 't7'), undefined, { raise: false })
  assert.deepEqual([r.ok, r.code], [true, 'resumed'])
  assert.deepEqual(fake.sent(), [['t7', `claude --resume ${SID}`]])
  const busy = await resumeSession(db, idOf(db, 't8'), undefined, { raise: false })
  assert.deepEqual([busy.ok, busy.code], [false, 'has_agent'])
  // 셸이 아닌 프로그램이 도는 칸에 명령을 쳐 넣지 않는다
  fake.add(term('t9', { foreground: { argv: ['vim'], cwd: '/work', name: 'vim', pid: 1 } }))
  await assert.rejects(core.focus('whosuptest-unit/t9', { run: 'claude', raise: false }), /not at a shell prompt/)
})

test('최근 닫힘에서 이어서 열기: 같은 공간에 새 탭을 열고 그 대화를 잇는다', async () => {
  reset()
  transcript(SID, WORK)
  fake.add(agentTerm('t2', 'idle', { labels: SPACE }))        // 공간이 남아 있게
  fake.add(agentTerm('t3', 'idle', { labels: SPACE }))        // (행 id를 앞 시험과 다르게: 연타 방지가 id로 3초 막는다)
  fake.add(agentTerm('t1', 'idle', { labels: SPACE, cwd: WORK, argv: ['zsh', '-ic', `claude --resume ${SID}`] }))
  const db = openDb(':memory:'); await collectAll(db)
  const id = idOf(db, 't1')
  fake.terminals.get('t1').state = 'finished'
  for (let i = 0; i < 3; i++) await collectAll(db)
  assert.equal(db.prepare('SELECT status FROM session WHERE id = ?').get(id).status, 'gone')
  const r = await resumeSession(db, id, undefined, { raise: false })
  assert.deepEqual([r.ok, r.code], [true, 'resumed'])
  assert.deepEqual(doCalls().filter((c) => c[0] === 'tab.new'), [['tab.new', { space: 'spA', folder: WORK }]])
  const made = liveAddrs().find((a) => !['t2', 't3'].includes(a))
  assert.deepEqual(fake.sent(), [[made, `claude --resume ${SID}`]])
  assert.equal(fake.terminals.get(made).labels['herdr.space'], 'spA')
  assert.equal(db.prepare('SELECT status FROM session WHERE id = ?').get(id).status, 'reopened')
})

test('새 세션: 앱이 있으면 그 공간의 새 탭, 앱 창이 없으면 코어에 바로 띄운다', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE }))
  const a = await core.newSession({ session: 'core:spA', cwd: WORK, command: 'claude', raise: false })
  assert.deepEqual(doCalls().filter((c) => c[0] === 'tab.new'), [['tab.new', { space: 'spA', folder: WORK }]])
  assert.deepEqual(fake.sent(), [[a.pane, 'claude']])
  process.env.FAKE_APP_MODE = 'no_window'
  const b = await core.newSession({ session: 'core:spA', cwd: WORK, command: 'claude', raise: false })
  assert.ok(fake.calls.some((c) => c.method === 'terminal.run' && c.params.cwd === WORK))
  assert.deepEqual(fake.sent().at(-1), [b.pane, 'claude'])
  await assert.rejects(core.newSession({ session: 'core:spA', cwd: '/nonexistent/whosup-test-dir', command: 'claude', raise: false }), (e) => e.code === 'cwd_missing')
  await assert.rejects(core.newSession({ session: 'main', cwd: WORK, command: 'claude', raise: false }), (e) => e.code === 'bad_session')
})

// ── 서버를 거쳐 ──
async function withServer(db, fn) {
  const server = createBoardServer(db)
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  const port = server.address().port
  const post = async (path, body) => { const r = await fetch(`http://127.0.0.1:${port}${path}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ raise: false, ...body }) }); return { status: r.status, data: await r.json() } }
  const get = async (path) => (await fetch(`http://127.0.0.1:${port}${path}`)).json()
  try { await fn({ post, get }) } finally { await new Promise((r) => server.close(r)) }
}

test('줄 끄기 → 켜기: 공간을 닫아 터미널을 끝내고, 켜면 같은 이름·폴더의 공간에 대화를 이어 연다', async () => {
  reset()
  transcript(SID, WORK)
  process.env.FAKE_APP_FOLDER = WORK
  fake.add(agentTerm('t1', 'idle', { labels: SPACE, cwd: WORK, argv: ['zsh', '-ic', `claude --resume ${SID}`] }))
  fake.add(term('t2', { labels: SPACE, cwd: WORK }))
  fake.add(agentTerm('t3', 'working', { labels: { 'herdr.space': 'spB', where: 'other / 1' } }))
  const db = openDb(':memory:'); await collectAll(db)
  await withServer(db, async ({ post, get }) => {
    // 줄 이름이 아닌 것, herdr 세션 이름 규칙에도 코어 줄 규칙에도 안 맞는 것은 거절
    assert.equal((await post('/api/desk', { session: 'core:bad space', on: false })).status, 400)
    assert.equal((await post('/api/desk', { session: 'core:', on: false })).status, 500)          // 공간 밖 줄은 통째로 끌 수 없다
    assert.deepEqual(liveAddrs().sort(), ['t1', 't2', 't3'])
    const off = await post('/api/desk', { session: 'core:spA', on: false })
    assert.deepEqual([off.status, off.data.code], [200, 'desk_stopped'])
    assert.deepEqual(doCalls().filter((c) => c[0] === 'space.close'), [['space.close', { id: 'spA', confirmed: true }]])
    assert.deepEqual(liveAddrs(), ['t3'])                    // 다른 공간은 그대로
    assert.deepEqual(core.offDesks()['core:spA'] && [core.offDesks()['core:spA'].label, core.offDesks()['core:spA'].folder], ['my project', WORK])
    // 꺼 둔 줄의 칸은 닫힘으로 보내지 않고 '꺼짐'으로 둔다(herdr 세션을 끈 것과 같은 모양)
    for (let i = 0; i < 4; i++) await collectAll(db)
    const rows = db.prepare("SELECT runtime_ref, archived, unreachable FROM session WHERE runtime = 'herdr-core' ORDER BY runtime_ref").all()
    assert.deepEqual(rows.map((r) => [r.runtime_ref.split('/')[1], r.archived, r.unreachable]), [['t1', 0, 2], ['t2', 0, 2], ['t3', 0, 0]])
    const b = await get('/api/board')
    assert.deepEqual(b.health.stopped, ['core:spA'])         // herdr가 없는 기계라 코어가 수집 상태를 적는다 → 꺼 둔 줄이 적힌다
    const offCards = Object.values(b.columns).flat().filter((c) => c.off)
    assert.deepEqual(offCards.map((c) => [c.desk, c.desk_label]).sort(), [['core:spA', 'my project'], ['core:spA', 'my project']])

    writeFileSync(LOG, ''); fake.calls.length = 0
    const on = await post('/api/desk', { session: 'core:spA', on: true })
    assert.deepEqual([on.status, on.data.code], [200, 'desk_started'])
    assert.deepEqual(doCalls().filter((c) => c[0] === 'space.new'), [['space.new', { name: 'my project', folder: WORK }]])
    const fresh = [...fake.terminals.values()].filter((t) => t.state === 'live' && t.address !== 't3')
    assert.equal(fresh.length, 1)                             // 대화가 있던 칸 하나만 다시 연다(빈 셸은 다시 만들지 않는다)
    assert.deepEqual(fake.sent(), [[fresh[0].address, `claude --resume ${SID}`]])
    assert.equal(core.offDesks()['core:spA'], undefined)
    const after = db.prepare("SELECT status, archived FROM session WHERE runtime_ref IN ('whosuptest-unit/t1', 'whosuptest-unit/t2') AND status = 'reopened'").all()
    assert.equal(after.length, 2)                             // 옛 칸은 접힌다
  })
  delete process.env.FAKE_APP_FOLDER
})

test('꺼 둔 줄: 끄기 직전에 읽은 목록(옛 터미널이 아직 있음)으로는 다시 켜진 것으로 보지 않는다', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE, created_ms: Date.now() - 60000 }))
  fake.add(agentTerm('t2', 'idle', { labels: { 'herdr.space': 'spB', where: 'other / 1' } }))
  process.env.FAKE_APP_MODE = 'no_window'
  await core.stopSession('core:spA')
  assert.ok(core.offDesks()['core:spA'])
  // 수집이 끄기와 엇갈려, 끝나기 전의 터미널이 목록에 다시 보이는 경우
  fake.terminals.get('t1').state = 'live'
  const snap = await core.listSnapshotAsync()
  assert.deepEqual(snap.stopped, ['core:spA'])
  assert.ok(core.offDesks()['core:spA'])
  // 끈 뒤에 생긴 터미널이 그 공간에 나타나면 켜진 것이다
  fake.terminals.get('t1').state = 'finished'
  fake.add(agentTerm('t3', 'idle', { labels: SPACE, created_ms: Date.now() + 1000 }))
  assert.deepEqual((await core.listSnapshotAsync()).stopped, [])
  // 꺼 둔 적 없는 줄은 켤 수 없다(엉뚱한 공간을 만들지 않는다)
  await assert.rejects(core.startSession('core:spZ', undefined, { raise: false }), (e) => e.code === 'bad_session')
})

test('줄 끄기: 터미널을 끝내기 전에 꺼짐을 먼저 적는다(끄는 도중의 수집이 칸을 닫힘으로 보내지 않게). 겹친 요청은 받지 않는다', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE, created_ms: Date.now() - 60000 }))
  fake.add(agentTerm('t2', 'working', { labels: SPACE, created_ms: Date.now() - 60000 }))
  const db = openDb(':memory:'); await collectAll(db)
  const OFF = join(process.env.WHOSUP_STATE_DIR, 'core-off.json')
  process.env.FAKE_APP_PROBE = OFF
  const [first, second] = await Promise.allSettled([core.stopSession('core:spA'), core.stopSession('core:spA')])
  delete process.env.FAKE_APP_PROBE
  assert.deepEqual([first.status, second.status, second.reason?.code], ['fulfilled', 'rejected', 'busy'])
  // 앱이 공간을 닫으라는 말을 받은 순간, 꺼짐 기록은 이미 있었다
  assert.ok(JSON.parse(readFileSync(`${OFF}.at-close`, 'utf8'))['core:spA'])
  assert.deepEqual(liveAddrs(), [])
  // 그 뒤 수집이 여러 번 돌아도(닫힘 판정 기준 3회를 넘겨도) 칸은 '꺼짐'으로 남는다
  for (let i = 0; i < 5; i++) await collectAll(db)
  const rows = db.prepare("SELECT archived, unreachable FROM session WHERE runtime = 'herdr-core' ORDER BY runtime_ref").all()
  assert.deepEqual(rows.map((r) => [r.archived, r.unreachable]), [[0, 2], [0, 2]])
  // 켜기도 겹치면 하나만 받는다(연타로 공간이 두 개 생기지 않게)
  writeFileSync(LOG, '')
  const on = await Promise.allSettled([core.startSession('core:spA', undefined, { raise: false }), core.startSession('core:spA', undefined, { raise: false })])
  assert.deepEqual(on.map((r) => r.status).sort(), ['fulfilled', 'rejected'])
  assert.equal(on.find((r) => r.status === 'rejected').reason.code, 'busy')
  assert.equal(doCalls().filter((c) => c[0] === 'space.new').length, 1)
  assert.equal(core.offDesks()['core:spA'], undefined)
})

test('서버: 새 세션·닫기가 줄 열쇠·카드의 런타임을 따라 herdr-core로 간다. 새 세션 대상에 Herdr 앱 공간이 나온다', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE, cwd: WORK }))
  const db = openDb(':memory:'); await collectAll(db)
  const home = process.env.HOME
  await withServer(db, async ({ post, get }) => {
    const h = await get('/api/health')
    assert.deepEqual(h.targets, [{ key: 'core:spA', label: 'my project' }])
    const inHome = join(home, '.whosup-test-nonexistent-dir')
    const bad = await post('/api/new', { session: 'core:spA', cwd: inHome })
    assert.deepEqual([bad.status, bad.data.code], [400, 'no_folder'])    // 폴더 검사는 herdr와 같다
    const closed = await post('/api/close', { id: idOf(db, 't1') })
    assert.deepEqual([closed.status, closed.data.code], [200, 'pane_closed'])
    assert.deepEqual(liveAddrs(), [])
  })
})

test('읽기 전용: herdr-core 카드 조작도 전부 막힌다', async () => {
  reset()
  fake.add(agentTerm('t1', 'blocked', { kind: 'question', msg: 'answer: go?', labels: SPACE }))
  const db = openDb(':memory:'); await collectAll(db)
  process.env.WHOSUP_READONLY = '1'
  try {
    await withServer(db, async ({ post }) => {
      for (const [path, body] of [['/api/open', { id: idOf(db, 't1') }], ['/api/close', { id: idOf(db, 't1') }], ['/api/resume', { id: idOf(db, 't1') }], ['/api/desk', { session: 'core:spA', on: false }], ['/api/new', { session: 'core:spA', cwd: WORK }]]) {
        const r = await post(path, body)
        assert.deepEqual([path, r.status, r.data.code], [path, 403, 'read_only'])
      }
    })
    assert.deepEqual(doCalls(), [])
    assert.deepEqual(fake.calls.filter((c) => !['terminal.list'].includes(c.method)), [])
    assert.deepEqual(liveAddrs(), ['t1'])
  } finally { delete process.env.WHOSUP_READONLY }
})

// ── 코드 리뷰에서 찾은 경계 (2026-11-11) ─────────────────────────────
test('주소가 다른 터미널에 넘어간 뒤의 옛 카드: 열기·닫기가 새 터미널을 건드리지 않고 옛 카드만 닫힘으로 간다', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE, created_ms: 1000 }))
  fake.add(agentTerm('t2', 'idle', { labels: SPACE, created_ms: 1000 }))
  const db = openDb(':memory:'); await collectAll(db)
  const [id1, id2] = [idOf(db, 't1'), idOf(db, 't2')]
  // 수집이 따라오기 전에 두 주소가 새 터미널에 넘어갔다
  fake.terminals.clear()
  fake.add(agentTerm('t1', 'working', { labels: SPACE, created_ms: 2000 }))
  fake.add(agentTerm('t2', 'working', { labels: SPACE, created_ms: 2000 }))
  writeFileSync(LOG, ''); fake.calls.length = 0
  const r = await openSession(db, id1, 50, { raise: false })
  assert.deepEqual([r.ok, r.code], [true, 'pane_gone'])
  await withServer(db, async ({ post }) => {
    const closed = await post('/api/close', { id: id2 })
    assert.deepEqual([closed.status, closed.data.code], [200, 'pane_closed'])
  })
  assert.deepEqual(doCalls().filter((c) => ['pane.focus', 'pane.close', 'terminal.keep'].includes(c[0])), [])
  assert.deepEqual(fake.calls.filter((c) => ['terminal.kill', 'terminal.send', 'terminal.label'].includes(c.method)), [])
  assert.deepEqual(liveAddrs().sort(), ['t1', 't2'])                                        // 새 터미널은 그대로 살아 있다
  const old = db.prepare('SELECT archived, status FROM session WHERE id IN (?, ?) ORDER BY id').all(id1, id2)
  assert.deepEqual(old.map((x) => [x.archived, x.status]), [[1, 'gone'], [1, 'gone']])
  // 다른 코어의 카드(코어 세션 이름이 다른 참조)는 이 코어의 같은 주소로 가지 않는다
  await assert.rejects(core.focus('another-core/t1', { raise: false }), /not found/)
  await assert.rejects(core.closePane('another-core/t1'), /not found/)
  assert.deepEqual(liveAddrs().sort(), ['t1', 't2'])
})

test('본 것으로 적기: 적기 직전에 터미널을 다시 읽어 그때의 턴을 적고, 적지 못하면 그렇다고 돌려준다(카드는 답변 도착으로 남는다)', async () => {
  reset()
  process.env.FAKE_APP_MODE = 'no_window'
  fake.add(agentTerm('t4', 'done', { labels: SPACE, turn: 2 }))
  // 창을 보여 주는 사이 새 턴이 끝났다: 적는 값은 클릭할 때의 턴(2)이 아니라 적을 때의 턴(3)
  let gets = 0
  fake.override = (m) => { if (m === 'terminal.get' && ++gets === 2) fake.terminals.get('t4').turn = 3 }
  const a = await core.focus(core.refOf('t4'), { raise: false })
  assert.equal(a.seen, true)
  assert.equal(fake.terminals.get('t4').labels['whosup.seen'], '3')
  // 적기가 실패하면 성공한 척하지 않는다
  fake.terminals.get('t4').turn = 4
  fake.override = (m) => (m === 'terminal.label' ? `${JSON.stringify({ jsonrpc: '2.0', id: 1, error: { code: -32000, message: 'no' } })}\n` : undefined)
  const b = await core.focus(core.refOf('t4'), { raise: false })
  assert.equal(b.seen, false)
  assert.equal(fake.terminals.get('t4').labels['whosup.seen'], '3')
  fake.override = null
  assert.equal(core.toSession(fake.terminals.get('t4')).status, 'done')
  // 쉬는 카드는 적을 것이 없다
  fake.terminals.get('t4').labels['whosup.seen'] = '4'
  assert.equal((await core.focus(core.refOf('t4'), { raise: false })).seen, null)
})

test('꺼 둔 줄 둘을 함께 켜도 서로의 터미널을 집지 않는다(만들기는 한 번에 하나)', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE, cwd: WORK, created_ms: Date.now() - 60000 }))
  fake.add(agentTerm('t2', 'idle', { labels: SPACE_B, cwd: WORK, created_ms: Date.now() - 60000 }))
  await core.stopSession('core:spA'); await core.stopSession('core:spB')
  assert.deepEqual(liveAddrs(), [])
  fake.calls.length = 0
  const [a, b] = await Promise.all([
    core.startSession('core:spA', undefined, { raise: false, commands: [{ id: 1, cwd: WORK, command: 'echo A' }] }),
    core.startSession('core:spB', undefined, { raise: false, commands: [{ id: 2, cwd: WORK, command: 'echo B' }] }),
  ])
  assert.notEqual(a.session, b.session)
  const sent = Object.fromEntries(fake.sent().map(([t, text]) => [text, t]))
  assert.equal(fake.sent().length, 2)
  assert.notEqual(sent['echo A'], sent['echo B'])
  const deskOfTerm = (t) => `core:${fake.terminals.get(t).labels['herdr.space']}`
  assert.deepEqual([deskOfTerm(sent['echo A']), deskOfTerm(sent['echo B'])], [a.session, b.session])
  assert.deepEqual([a.done, a.failed, b.done, b.failed], [[1], [], [2], []])
})

test('줄 켜기: 이어 열지 못한 대화의 옛 칸은 접지 않는다. 첫 대화도 제 폴더에서 연다. 다시 눌러도 공간이 또 생기지 않는다', async () => {
  reset()
  const SUB = join(WORK, 'api'); mkdirSync(SUB, { recursive: true })
  transcript(SID, SUB); transcript(SID2, WORK)
  process.env.FAKE_APP_FOLDER = WORK                                                        // 공간의 폴더
  fake.add(agentTerm('t1', 'idle', { labels: SPACE, cwd: SUB, argv: ['zsh', '-ic', `claude --resume ${SID}`] }))   // 첫 대화는 공간 폴더의 하위 폴더에서 돌았다
  fake.add(agentTerm('t2', 'idle', { labels: SPACE, cwd: WORK, argv: ['zsh', '-ic', `claude --resume ${SID2}`] }))
  const db = openDb(':memory:'); await collectAll(db)
  const [id1, id2] = [idOf(db, 't1'), idOf(db, 't2')]
  await withServer(db, async ({ post }) => {
    assert.equal((await post('/api/desk', { session: 'core:spA', on: false })).status, 200)
    writeFileSync(LOG, ''); fake.calls.length = 0
    // 둘째 대화의 재개 명령은 들어가지 않는다
    fake.override = (m, p) => (m === 'terminal.send' && String(p.text).includes(SID2) ? `${JSON.stringify({ jsonrpc: '2.0', id: 1, error: { code: -32000, message: 'send failed' } })}\n` : undefined)
    const on = await post('/api/desk', { session: 'core:spA', on: true })
    fake.override = null
    assert.deepEqual([on.status, on.data.code, on.data.not_resumed], [200, 'desk_started', 1])
    // 첫 대화: 공간의 첫 터미널(공간 폴더)이 아니라 그 대화의 폴더로 연 새 탭에 들어간다
    const sent = fake.sent()
    assert.deepEqual(sent.map((s) => s[1]), [`claude --resume ${SID}`])
    assert.equal(fake.terminals.get(sent[0][0]).cwd, SUB)
    assert.equal(doCalls().filter((c) => c[0] === 'tab.new' && c[1].folder === SUB).length, 1)
    // 이어 연 대화의 옛 칸만 접힌다. 못 연 대화의 옛 칸은 닫힌 칸으로 가서 하나씩 이어 열 수 있다
    const st = (id) => db.prepare('SELECT status, archived FROM session WHERE id = ?').get(id)
    assert.deepEqual(Object.values(st(id1)), ['reopened', 1])
    assert.notEqual(st(id2).status, 'reopened')
    for (let i = 0; i < 4; i++) await collectAll(db)
    assert.deepEqual(Object.values(st(id2)), ['gone', 1])
    // 줄은 켜졌다: 다시 눌러도 공간을 또 만들지 않는다
    assert.equal(core.offDesks()['core:spA'], undefined)
    const again = await post('/api/desk', { session: 'core:spA', on: true })
    assert.equal(again.status, 500)
    assert.equal(doCalls().filter((c) => c[0] === 'space.new').length, 1)
  })
})

test('줄 끄기·켜기 요청은 그 뒤의 수집까지 끝나야 다음 것을 받는다(끄자마자 겹친 요청은 바쁨으로 돌려보낸다)', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE, created_ms: Date.now() - 60000 }))
  const db = openDb(':memory:'); await collectAll(db)
  await withServer(db, async ({ post }) => {
    const both = await Promise.all([post('/api/desk', { session: 'core:spA', on: false }), post('/api/desk', { session: 'core:spA', on: true })])
    assert.deepEqual(both.map((r) => r.status).sort(), [200, 409])
    assert.equal(both.find((r) => r.status === 409).data.code, 'busy')
    assert.equal(doCalls().filter((c) => c[0] === 'space.new').length, 0)                   // 켜기는 받지 않았다
    assert.ok(core.offDesks()['core:spA'])
    assert.equal(db.prepare("SELECT unreachable FROM session WHERE runtime = 'herdr-core'").get().unreachable, 2)   // 응답이 왔을 때 판은 이미 꺼진 줄을 안다
  })
})

test('끄는 도중의 수집은 그 줄의 꺼짐 기록을 지우지 않는다(끄는 사이 그 공간에 터미널이 새로 보여도)', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE, created_ms: Date.now() - 60000 }))
  // 끄는 도중(앱이 공간을 닫으며 첫 터미널을 끝내는 순간) 그 공간에 새 터미널이 생기고 수집이 돈다.
  // 그 수집은 목록을 끄는 도중에 읽지만, 새 터미널의 화면 읽기에 붙잡혀 끄기가 끝난 뒤에야 목록을 마저 본다.
  let snap = null
  fake.override = (m) => {
    if (m === 'terminal.read') return false                                                  // 답하지 않는다(읽기가 시간 초과까지 기다린다)
    if (m !== 'terminal.kill' || snap) return undefined
    fake.terminals.set('t9', term('t9', { labels: SPACE, created_ms: Date.now() + 5000, argv: ['sh', '-c', 'claude'], foreground: { argv: ['claude'], cwd: '/work', name: '2.1.322', pid: 71009 } }))
    snap = core.listSnapshotAsync()
    return undefined
  }
  await core.stopSession('core:spA')
  let settled = false
  snap.then(() => { settled = true })
  await sleep(20)
  assert.equal(settled, false, '끄기가 끝난 뒤에도 그 수집은 아직 목록을 다 보지 못했다')
  assert.deepEqual((await snap).stopped, ['core:spA'])
  fake.override = null
  assert.ok(core.offDesks()['core:spA'])                                                     // 다시 켤 수 있다
  assert.deepEqual(liveAddrs(), [])                                                          // 끄는 사이 생긴 터미널도 함께 끝났다
})

test('코어에 닿지 못해도 꺼 둔 줄은 꺼 둔 줄로 남는다', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE, created_ms: Date.now() - 60000 }))
  process.env.FAKE_APP_MODE = 'no_window'
  await core.stopSession('core:spA')
  fake.override = () => 'close'
  const rt = await core.snapshotRuntime()
  const snap = rt.listSnapshot()
  fake.override = null
  assert.ok(rt.err)
  assert.deepEqual([snap.holdAll, snap.stopped], [true, ['core:spA']])
})

test('같은 대화를 서로 다른 두 칸에서 동시에 이어 열지 않는다', async () => {
  reset()
  transcript(SID, WORK)
  for (const n of [11, 12, 13, 14, 15, 16, 17]) fake.add(agentTerm(`t${n}`, 'working', { labels: SPACE_B }))   // 행 id를 앞 시험들과 다르게(연타 방지가 id로 3초 막는다)
  const shell = (t, pid) => term(t, { labels: SPACE, cwd: WORK, foreground: { argv: ['/bin/zsh', '-l'], cwd: WORK, name: 'zsh', pid } })
  fake.add(shell('t1', 70001)); fake.add(shell('t2', 70002))
  const db = openDb(':memory:'); await collectAll(db)
  fake.calls.length = 0
  const both = await Promise.all([resumeSession(db, idOf(db, 't1'), undefined, { raise: false }), resumeSession(db, idOf(db, 't2'), undefined, { raise: false })])
  assert.deepEqual(both.map((r) => r.code).sort(), ['busy', 'resumed'])
  assert.equal(fake.sent().length, 1)
  assert.equal(fake.sent()[0][1], `claude --resume ${SID}`)
})

test('닫은 카드는 닫기 전에 읽기 시작한 수집이 되살리지 못한다', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE }))
  const db = openDb(':memory:'); await collectAll(db)
  const id = idOf(db, 't1')
  // 느린 수집: 닫기 전의 목록을 붙잡아 두었다가 닫은 뒤에 돌려준다
  let release
  const held = new Promise((r) => { release = r })
  let first = true
  fake.override = (m, p, sock) => {
    if (m !== 'terminal.list' || !first) return undefined
    first = false
    const stale = JSON.stringify({ jsonrpc: '2.0', id: 1, result: { hidden_finished: 0, terminals: [...fake.terminals.values()].filter((x) => x.state === 'live').map((x) => ({ ...x })) } })
    held.then(() => sock.write(`${stale}\n`))
    return false
  }
  const slow = collectAll(db)
  await sleep(50)
  fake.terminals.get('t1').state = 'finished'                                                // 그 사이 보드에서 닫았다
  markGoneNow(db, id)
  release(); await slow
  fake.override = null
  assert.deepEqual(Object.values(db.prepare('SELECT archived, status FROM session WHERE id = ?').get(id)), [1, 'gone'])
})

// ── 위 수정 묶음을 다시 검토해 찾은 경계 ──────────────────────────────
test('판이 계속 바뀌는 동안에는 낡은 목록을 적용하지 않고 그 수집을 건너뛴다', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE }))
  const db = openDb(':memory:'); await collectAll(db)
  fake.calls.length = 0
  fake.override = (m) => { if (m === 'terminal.list') noteChange() }                         // 목록을 읽을 때마다 보드에서 무언가를 닫는다
  const r = await collectAll(db)
  fake.override = null
  assert.deepEqual([r.skipped, r.runs], [true, []])
  assert.equal(fake.calls.filter((c) => c.method === 'terminal.list').length, 3)             // 세 번까지 다시 읽어 본다
  const ok = await collectAll(db)
  assert.deepEqual([ok.skipped, ok.runs.length], [undefined, 1])
})

test('이어 열기를 잡아 둔 대화: 같은 칸에서 다시 누르는 것은 받는다(다른 칸만 돌려보낸다)', async () => {
  reset()
  transcript(SID, WORK)
  for (const n of [21, 22, 23, 24, 25, 26, 27, 28, 29, 30]) fake.add(agentTerm(`t${n}`, 'working', { labels: SPACE_B }))   // 행 id를 앞 시험들과 다르게
  const shell = (t, pid) => term(t, { labels: SPACE, cwd: WORK, foreground: { argv: ['/bin/zsh', '-l'], cwd: WORK, name: 'zsh', pid } })
  fake.add(shell('t1', 70001)); fake.add(shell('t2', 70002))
  const db = openDb(':memory:'); await collectAll(db)
  const first = await resumeSession(db, idOf(db, 't1'), undefined, { raise: false })
  assert.equal(first.code, 'resumed')
  assert.equal((await resumeSession(db, idOf(db, 't2'), undefined, { raise: false })).code, 'busy')
  await sleep(3200)                                                                           // 같은 칸의 연타 방지(3초)가 풀린 뒤: 에이전트가 바로 꺼져 다시 셸인 칸에서 다시 누른다
  const again = await resumeSession(db, idOf(db, 't1'), undefined, { raise: false })
  assert.equal(again.code, 'resumed')
  assert.equal((await resumeSession(db, idOf(db, 't2'), undefined, { raise: false })).code, 'busy')
})
