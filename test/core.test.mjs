// herdr-core 런타임 — 읽기 경로. 가짜 코어(소켓)와 가짜 herdr-app만 쓴다. 실제 코어·앱·herdr는 띄우지 않는다.
import { test, after } from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { chmodSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { startFakeCore, term, agentTerm } from '../test-support/fake-core.mjs'
import { fileURLToPath } from 'node:url'

const dir = mkdtempSync(join(tmpdir(), 'wc-'))
const SOCK = join(dir, 'core.sock')
process.env.HC_SOCKET = SOCK
process.env.HC_SESSION = 'whosuptest-unit'
process.env.HERDR_APP_BIN = fileURLToPath(new URL('../test-support/fake-herdr-app.mjs', import.meta.url))
chmodSync(process.env.HERDR_APP_BIN, 0o755)
process.env.HERDR_BIN = join(dir, 'no-herdr')          // herdr가 설치되지 않은 기계
delete process.env.HERDR_BIN_PATH
process.env.WHOSUP_STATE_DIR = join(dir, 'state')
process.env.CLAUDE_PROJECTS_DIR = join(dir, 'claude', 'projects')
process.env.WHOSUP_NO_EVENTS = ''
delete process.env.WHOSUP_RUNTIMES
mkdirSync(process.env.CLAUDE_PROJECTS_DIR, { recursive: true })
mkdirSync(join(dir, 'claude', 'sessions'), { recursive: true })

const core = await import('../src/runtime/core.mjs')
const { collectAll, capsOf } = await import('../src/runtime/index.mjs')
const { collectOnce, forgetDownSince } = await import('../src/collector.mjs')
const { computeBoard, computeBoardAsync } = await import('../src/board/board.mjs')
const { coreQuestion, clearContextCache, isTrustScreen, questionOf, TRUST_QUESTION, _cacheKeys } = await import('../src/board/context.mjs')
const { openDb, getMeta, setMeta } = await import('../src/db.mjs')

let fake = await startFakeCore(SOCK)
after(async () => { core.stopWatching(); await fake.close() })
const reset = () => { fake.override = null; fake.terminals.clear(); fake.screens.clear(); fake.calls.length = 0; clearContextCache(); core._resetScreenCache() }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const SPACE = { 'herdr.space': 'spA', 'herdr.tab': 'tb1', where: 'my project / 1' }
const SID = '11111111-1111-4111-8111-111111111111'

test('toSession: 코어 상태를 판의 상태로 옮긴다(작업 중·입력 필요·답변 도착·쉼·오류·셸·그 밖)', () => {
  const st = (t) => core.toSession(t).status
  assert.equal(st(agentTerm('t1', 'working')), 'working')
  assert.equal(st(agentTerm('t1', 'blocked', { kind: 'question', msg: 'answer: A or B?' })), 'blocked')
  assert.equal(st(agentTerm('t1', 'done')), 'done')
  assert.equal(st(agentTerm('t1', 'idle')), 'idle')
  assert.equal(st(term('t1')), 'shell')
  assert.equal(st(term('t1', { argv: ['sleep', '300'], foreground: { argv: ['sleep', '300'], cwd: '/work', name: 'sleep', pid: 1 } })), 'unknown')
  const err = core.toSession(agentTerm('t1', 'error', { msg: 'boom' }))
  assert.deepEqual([err.status, err.fields.failed, err.fields.requiresAttention], ['blocked', true, true])
})

test('toSession: 주소·줄·공급자·대기 시작 시각', () => {
  const s = core.toSession(agentTerm('t4', 'blocked', { kind: 'permission', msg: 'approve Bash: ls', labels: SPACE, cwd: '/work/proj', name: 'fix' }), { sid: SID })
  assert.equal(s.runtime, 'herdr-core')
  assert.equal(s.runtime_ref, 'whosuptest-unit/t4')
  assert.equal(s.provider, 'claude')                       // 이어서 열기 규칙이 아는 이름
  assert.equal(s.provider_session, SID)
  assert.equal(s.pane_label, 'fix')
  assert.deepEqual([s.fields.desk, s.fields.deskLabel, s.fields.tab], ['core:spA', 'my project', 'tb1'])
  assert.deepEqual([s.fields.statusKind, s.fields.statusMsg], ['permission', 'approve Bash: ls'])
  assert.equal(s.attentionTimestamp, new Date(1794000100000).toISOString())
  // 공간 밖 터미널은 한 줄(core:)에 모인다
  const loose = core.toSession(term('t9'))
  assert.deepEqual([loose.fields.desk, loose.fields.deskLabel], ['core:', 'herdr-core'])
})

test('toSession: 앱에서 이미 본 끝난 턴(herdr.seen >= turn)은 답변 도착이 아니라 쉼', () => {
  assert.equal(core.toSession(agentTerm('t1', 'done', { turn: 3, labels: { ...SPACE, 'herdr.seen': '3' } })).status, 'idle')
  assert.equal(core.toSession(agentTerm('t1', 'done', { turn: 3, labels: { 'whosup.seen': '3' } })).status, 'idle')   // 보드에서 열어 본 것(앱 없이 쓸 때)
  assert.equal(core.toSession(agentTerm('t1', 'done', { turn: 4, labels: { 'herdr.seen': '2', 'whosup.seen': '3' } })).status, 'done')
  assert.equal(core.toSession(agentTerm('t1', 'done', { turn: 3, labels: { ...SPACE, 'herdr.seen': '2' } })).status, 'done')
})

// Claude Code 2.1의 폴더 신뢰 화면(격리 시험 코어에서 읽은 그대로). 이때 코어는 status를 알리지 않는다.
const TRUST_SCREEN = `${'─'.repeat(60)}
 Accessing workspace:

 /private/tmp/some-project

 Quick safety check: Is this a project you created or one you trust? (Like your own code, a well-known open source project, or work from your team). If not, take a moment to review what's in this
 folder first.

 Claude Code'll be able to read, edit, and execute files here.

 Security guide

 ❯ No, exit
   Yes, I trust this folder

 Enter to confirm · Esc to cancel
`
const waitingAgent = (address, over = {}) => term(address, { argv: ['sh', '-c', 'claude'], foreground: { argv: ['claude'], cwd: '/work/p', name: '2.1.322', pid: 71000 }, cwd: '/work/p', labels: SPACE, ...over })

test('toSession: 상태를 알리지 않는 터미널의 화면이 폴더 신뢰 질문이면 입력 필요(그 밖에는 화면으로 상태를 정하지 않는다)', () => {
  const s = core.toSession(waitingAgent('t1'), { screenAsk: 'trust' })
  assert.deepEqual([s.status, s.fields.requiresAttention, s.fields.attentionReason, s.fields.statusKind, s.fields.failed], ['blocked', true, 'blocked', 'trust', false])
  assert.equal(core.toSession(waitingAgent('t1')).status, 'unknown')                                  // 화면을 읽지 않았으면 그대로
  assert.equal(core.toSession(term('t2'), { screenAsk: 'trust' }).status, 'shell')                     // 셸은 올리지 않는다
  const idle = core.toSession(agentTerm('t3', 'idle'), { screenAsk: 'trust' })                         // 코어가 상태를 알리면 그 상태가 이긴다
  assert.deepEqual([idle.status, idle.fields.statusKind], ['idle', null])
})

test('폴더 신뢰 화면에 멈춘 에이전트: 입력 필요 카드와 질문 문구로 뜨고, 에이전트가 뜨면 코어가 알린 상태로 돌아간다', async () => {
  reset()
  fake.add(waitingAgent('t1'))
  fake.add(term('t2', { labels: SPACE }))                                                              // 셸
  fake.add(term('t3', { labels: SPACE, argv: ['less', 'notes.txt'], foreground: { argv: ['less', 'notes.txt'], cwd: '/work', name: 'less', pid: 71003 } }))   // 에이전트가 아닌 프로그램
  fake.screens.set('t1', TRUST_SCREEN)
  fake.screens.set('t2', `${TRUST_SCREEN}\n% `)                                                        // 셸 화면에 같은 글자가 남아 있어도
  fake.screens.set('t3', 'meeting notes\nline two\n:')
  const db = openDb(':memory:')
  await collectAll(db)
  const status = (t) => db.prepare('SELECT status FROM session WHERE runtime_ref = ?').get(`whosuptest-unit/${t}`).status
  assert.deepEqual([status('t1'), status('t2'), status('t3')], ['blocked', 'shell', 'unknown'])
  // 화면은 상태를 알리지 않는, 셸이 아닌 터미널만 읽는다
  assert.deepEqual(fake.calls.filter((c) => c.method === 'terminal.read').map((c) => c.params.terminal).sort(), ['t1', 't3'])
  const b = await computeBoardAsync(db)
  const card = Object.values(b.columns).flat().find((c) => c.ref.endsWith('/t1'))
  assert.deepEqual([card.status, card.question, card.ask_kind, card.failed], ['blocked', '이 폴더를 신뢰할까요? (Yes, I trust this folder)', 'approval', false])
  assert.equal(b.next.ref, card.ref)                                                                    // 다음에 볼 칸으로 잡힌다
  // 신뢰를 고르면 에이전트가 뜨고 코어가 상태를 알린다
  fake.set('t1', { status: { app: 'claude-code', state: 'idle' }, status_ms: Date.now() })
  await collectAll(db)
  assert.equal(status('t1'), 'idle')
  // 같은 화면이 몇 초 안에 다시 읽히지 않는다(수집이 잦아도 터미널마다 읽기 한 번)
  fake.set('t1', { status: null }); fake.calls.length = 0; core._resetScreenCache()
  await collectAll(db); await collectAll(db); await collectAll(db)
  assert.equal(fake.calls.filter((c) => c.method === 'terminal.read' && c.params.terminal === 't1' && c.params.lines === 0).length, 1)
  assert.equal(status('t1'), 'blocked')
  // 화면에서 그 질문이 사라졌는데 코어가 여전히 아무것도 알리지 않으면 올리지 않는다(추측하지 않는다)
  core._resetScreenCache(); fake.screens.delete('t1')
  await collectAll(db)
  assert.equal(status('t1'), 'unknown')
})

test('toSession: 끝내자마자 idle로 돌아가는 에이전트(Codex) — 아직 보지 않은 끝난 턴이 있으면 답변 도착, 보면 쉼', () => {
  const codex = (over) => agentTerm('t1', 'idle', { status: { app: 'codex', state: 'idle' }, labels: SPACE, ...over })
  assert.equal(core.toSession(codex({ turn: 0 })).status, 'idle')                                          // 갓 뜬 에이전트
  const fin = core.toSession(codex({ turn: 2, labels: { ...SPACE, 'herdr.seen': '0' } }))                  // 한 턴을 끝내고 idle (실측: done 2초 뒤 idle)
  assert.deepEqual([fin.status, fin.provider, fin.fields.requiresAttention, fin.fields.attentionReason], ['done', 'codex', true, 'finished'])
  assert.equal(core.toSession(codex({ turn: 2, labels: { ...SPACE, 'herdr.seen': '2' } })).status, 'idle')  // 앱에서 봤다
  assert.equal(core.toSession(codex({ turn: 2, labels: { 'whosup.seen': '2' } })).status, 'idle')           // 보드에서 열어 봤다
  assert.equal(core.toSession(codex({ turn: 2, labels: {} })).status, 'done')                               // 본 기록이 없다(앱 밖 터미널)
  assert.equal(core.toSession(agentTerm('t1', 'working', { status: { app: 'codex', state: 'working' }, turn: 3, labels: { 'herdr.seen': '2' } })).status, 'working')
  // done을 볼 때까지 유지하는 에이전트(Claude Code)의 idle은 그대로 쉼이다. 실측: 턴을 Esc로 끊으면 코어는 done 없이
  // idle로 알리고 턴 수만 는다 — 끊긴 턴을 답변 도착으로 올리지 않는다.
  assert.equal(core.toSession(agentTerm('t1', 'idle', { turn: 1, labels: SPACE })).status, 'idle')
  assert.equal(core.toSession(agentTerm('t1', 'idle', { status: { app: 'some-agent', state: 'idle' }, turn: 4, labels: {} })).status, 'idle')   // 모르는 에이전트도 추측하지 않는다
})

test('목록: 살아 있는 이 기계의 터미널만, 대화 id는 Claude 프로세스 등록부(pid)와 실행 인자에서', async () => {
  reset()
  fake.add(agentTerm('t1', 'working', { labels: SPACE }))                                   // foreground pid 70001
  fake.add(agentTerm('t2', 'idle', { labels: SPACE, argv: ['zsh', '-ic', `claude --resume ${SID}`] }))
  fake.add(term('t3', { state: 'finished' }))
  fake.add(term('box/t7'))
  const other = '22222222-2222-4222-8222-222222222222'
  writeFileSync(join(dir, 'claude', 'sessions', '70001.json'), JSON.stringify({ pid: 70001, sessionId: other, cwd: '/work' }))
  const snap = await core.listSnapshotAsync()
  assert.deepEqual(snap.sessions.map((s) => [s.runtime_ref.split('/')[1], s.provider_session]), [['t1', other], ['t2', SID]])
  assert.deepEqual([snap.unreachable, snap.stopped], [[], []])
})

test('래퍼로 띄운 에이전트: 터미널 프로그램의 자식 프로세스에서 대화 id를 찾는다(실제 프로세스 트리)', { skip: process.platform === 'win32' }, async () => {
  reset()
  // 터미널의 프로그램은 셸(래퍼)이고 에이전트는 그 자식이다. 등록부에는 자식의 pid로 적혀 있다.
  const wrapper = spawn('/bin/sh', ['-c', 'sleep 30; true'], { stdio: 'ignore' })
  try {
    let child = null
    for (let i = 0; i < 40 && !child; i++) {
      await new Promise((r) => setTimeout(r, 50))
      const out = await new Promise((r) => spawn('/bin/ps', ['-axo', 'pid=,ppid=']).stdout.setEncoding('utf8').on('data', (d) => { r.buf = (r.buf || '') + d }).on('end', () => r(r.buf || '')))
      child = out.split('\n').map((l) => l.trim().split(/\s+/).map(Number)).find(([, ppid]) => ppid === wrapper.pid)?.[0] ?? null
    }
    assert.ok(child, 'wrapper has a child process')
    const sid = '33333333-3333-4333-8333-333333333333'
    writeFileSync(join(dir, 'claude', 'sessions', `${child}.json`), JSON.stringify({ pid: child, sessionId: sid, cwd: '/work' }))
    fake.add(agentTerm('t6', 'working', { labels: SPACE, pid: wrapper.pid, foreground: { argv: ['sh'], cwd: '/work', name: 'sh', pid: wrapper.pid } }))
    fake.add(agentTerm('t7', 'idle', { labels: SPACE, pid: wrapper.pid, foreground: { argv: ['sh'], cwd: '/work', name: 'sh', pid: wrapper.pid } }))   // 같은 순간에 찾는 터미널이 여럿이어도 된다
    // 프로세스 목록은 5초 동안 다시 읽지 않는다(앞 시험이 방금 읽었다): 갓 뜬 에이전트는 그 뒤 수집에서 잡힌다
    let snap = await core.listSnapshotAsync()
    for (let i = 0; i < 30 && snap.sessions.some((s) => !s.provider_session); i++) { await new Promise((r) => setTimeout(r, 250)); snap = await core.listSnapshotAsync() }
    assert.deepEqual(snap.sessions.map((s) => s.provider_session), [sid, sid])
  } finally { wrapper.kill('SIGKILL') }
})

test('대화 id를 모르면 비워 둔다(같은 폴더의 다른 대화로 추측하지 않는다)', async () => {
  reset()
  fake.add(agentTerm('t5', 'working', { labels: SPACE, cwd: '/work/shared' }))
  mkdirSync(join(process.env.CLAUDE_PROJECTS_DIR, '-tmp-shared'), { recursive: true })
  writeFileSync(join(process.env.CLAUDE_PROJECTS_DIR, '-tmp-shared', `${SID}.jsonl`), `${JSON.stringify({ type: 'user', message: { content: 'someone else' } })}\n`)
  assert.equal((await core.listSnapshotAsync()).sessions[0].provider_session, null)
})

test('수집 → 판: 공간마다 한 줄, 질문은 코어가 알려 준 문구, 할 수 있는 일(caps)', async () => {
  reset()
  fake.add(agentTerm('t1', 'blocked', { kind: 'question', msg: 'answer: Which color do you prefer? (Red · Blue)', labels: SPACE, cwd: '/work/a' }))
  fake.add(agentTerm('t2', 'blocked', { kind: 'permission', msg: 'approve Bash: curl -s https://example.com', labels: SPACE, cwd: '/work/a' }))
  fake.add(agentTerm('t3', 'done', { labels: { 'herdr.space': 'spB', where: 'other / 1' }, cwd: '/work/b' }))
  fake.add(term('t4'))
  fake.screens.set('t3', `⏺ Ran the test suite: 24 passed.\n${'─'.repeat(40)}\n❯ \n${'─'.repeat(40)}\n`)
  const db = openDb(':memory:')
  const { runs, failure } = await collectAll(db)
  assert.equal(failure, null)
  assert.deepEqual(runs.map((r) => [r.name, r.sessions]), [['herdr-core', 4]])   // herdr는 없는 기계: 조용히 건너뜀
  assert.equal(getMeta(db, 'collect_err'), null)
  assert.ok(getMeta(db, 'collect_ok_at'))
  const b = await computeBoardAsync(db)
  const cards = Object.values(b.columns).flat()
  const by = (t) => cards.find((c) => c.ref.endsWith(`/${t}`))
  assert.deepEqual([by('t1').desk, by('t1').desk_label, by('t3').desk, by('t3').desk_label, by('t4').desk, by('t4').desk_label], ['core:spA', 'my project', 'core:spB', 'other', 'core:', 'herdr-core'])
  assert.deepEqual([by('t1').question, by('t1').ask_kind], ['Which color do you prefer? (Red · Blue)', 'question'])
  assert.deepEqual([by('t2').question, by('t2').ask_kind], ['Bash: curl -s https://example.com — 승인할까요?', 'approval'])
  assert.equal(by('t1').failed, false)
  assert.equal(by('t3').last_say, 'Ran the test suite: 24 passed.')
  assert.deepEqual(by('t1').caps, ['focus', 'close', 'resume', 'new', 'toggle', 'web'])
  assert.ok(!by('t4').caps.includes('toggle'))               // 공간 밖 줄에는 닫을 공간이 없다
  assert.equal(b.next.runtime, 'herdr-core')
  assert.equal(b.order.length, 3)
  // 모르는 런타임의 행은 caps가 없다 → 화면이 판에 올리지 않는다
  assert.equal(capsOf({ runtime: 'paseo', runtime_ref: 'x/y' }), null)
})

test('상태가 따라 바뀐다: 작업 중 → 입력 필요 → 답변 도착 (이벤트로 바로 수집)', async () => {
  reset()
  fake.add(agentTerm('t1', 'working', { labels: SPACE }))
  const db = openDb(':memory:')
  await collectAll(db)
  const status = () => db.prepare("SELECT status FROM session WHERE runtime = 'herdr-core'").get().status
  assert.equal(status(), 'working')
  let kicks = 0
  core.watchEvents(() => { kicks += 1 })
  await new Promise((r) => setTimeout(r, 80))
  fake.set('t1', { status: { app: 'claude-code', state: 'blocked', kind: 'question', msg: 'answer: go?' }, turn: 1 })
  await new Promise((r) => setTimeout(r, 80))
  assert.ok(kicks >= 1, 'event → kick')
  await collectAll(db); assert.equal(status(), 'blocked')
  fake.set('t1', { status: { app: 'claude-code', state: 'done' }, turn: 2 })
  await collectAll(db); assert.equal(status(), 'done')
  core.stopWatching()
})

test('주소가 다시 쓰이면 옛 카드와 섞이지 않는다(새 터미널은 새 행, 옛 행은 닫힘)', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE, created_ms: 1000 }))
  const db = openDb(':memory:')
  await collectAll(db)
  const first = db.prepare("SELECT id FROM session WHERE runtime_ref = 'whosuptest-unit/t1'").get().id
  fake.terminals.clear(); fake.add(agentTerm('t1', 'working', { labels: SPACE, created_ms: 2000 }))
  await collectAll(db)
  const rows = db.prepare("SELECT id, runtime_ref, archived, status FROM session WHERE runtime = 'herdr-core' ORDER BY id").all()
  assert.equal(rows.length, 2)
  assert.deepEqual([rows[0].id, rows[0].archived, rows[0].status], [first, 1, 'gone'])
  assert.deepEqual([rows[1].runtime_ref, rows[1].archived, rows[1].status], ['whosuptest-unit/t1', 0, 'working'])
})

test('다른 에이전트 프로그램이 그 터미널을 차지하면 옛 대화 id를 물려주지 않는다(옛 행은 닫힘, 새 행으로 시작)', async () => {
  reset()
  fake.add(agentTerm('t2', 'idle', { labels: SPACE, argv: ['zsh', '-ic', `claude --resume ${SID}`] }))
  const db = openDb(':memory:')
  await collectAll(db)
  const rows = () => db.prepare("SELECT provider, provider_session, archived, status FROM session WHERE runtime = 'herdr-core' ORDER BY id").all().map((r) => Object.values(r))
  assert.deepEqual(rows(), [['claude', SID, 0, 'idle']])
  // 셸로 돌아간 동안에는 그 대화를 기억한다(이어서 열기 대상)
  fake.set('t2', { status: null, argv: ['/bin/zsh', '-l'], foreground: { argv: ['/bin/zsh', '-l'], cwd: '/work', name: 'zsh', pid: 70002 } })
  await collectAll(db)
  assert.deepEqual(rows(), [['claude', SID, 0, 'shell']])
  // 같은 터미널에서 다른 에이전트가 뜬다: 대화 id를 아직 모른다
  fake.set('t2', { status: { app: 'codex', state: 'working' }, foreground: { argv: ['codex'], cwd: '/work', name: 'codex', pid: 70002 } })
  await collectAll(db)
  assert.deepEqual(rows(), [['claude', SID, 1, 'gone'], ['codex', null, 0, 'working']])
})

test('사라진 터미널은 연속 미검출 뒤 최근 닫힘으로', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE }))
  const db = openDb(':memory:')
  await collectAll(db)
  fake.terminals.get('t1').state = 'finished'
  for (let i = 0; i < 3; i++) await collectAll(db)
  assert.deepEqual(Object.values(db.prepare("SELECT archived, status FROM session WHERE runtime = 'herdr-core'").get()), [1, 'gone'])
})

test('코어가 꺼지면: 칸이 있었으면 확인 불가로 남기고, 없었으면 조용히 건너뛴다', async () => {
  reset()
  fake.add(agentTerm('t1', 'blocked', { kind: 'question', msg: 'answer: go?', labels: SPACE }))
  const db = openDb(':memory:')
  await collectAll(db)
  await fake.close()                                        // 소켓이 사라진다 = 코어 꺼짐
  try {
    assert.equal(core.available(), false)
    const rt = await core.snapshotRuntime()
    assert.equal(rt.absent, true)
    for (let i = 0; i < 4; i++) await collectAll(db)
    const row = db.prepare("SELECT status, archived, unreachable FROM session WHERE runtime = 'herdr-core'").get()
    assert.deepEqual([row.status, row.archived, row.unreachable], ['blocked', 0, 1])
    // 그 채로 unreachable_ttl_h(기본 24시간)가 지나면 닫힘으로 보낸다(지운 프로그램의 칸이 판에 남지 않게)
    await collectAll(db, { now: new Date(Date.now() + 25 * 3600000) })
    assert.deepEqual(Object.values(db.prepare("SELECT archived, status FROM session WHERE runtime = 'herdr-core'").get()), [1, 'gone'])
    // 칸이 없던 DB: herdr도 코어도 없으면 예전처럼 herdr 없음 오류만 남는다(코어 때문에 새 오류가 생기지 않는다)
    const empty = openDb(':memory:')
    const r = await collectAll(empty)
    assert.deepEqual(r.runs, [])
    assert.equal(r.failure?.code, 'ENOENT')
    assert.equal(getMeta(empty, 'collect_err_kind'), 'no_herdr')
    assert.equal(empty.prepare('SELECT COUNT(*) AS n FROM session').get().n, 0)
  } finally { fake = await startFakeCore(SOCK) }          // 중간에 실패해도 다음 시험들은 켜진 코어로 돈다
})

test('코어 찾기: HC_SOCKET이 없으면 코어가 적어 둔 core.lock에서 소켓 경로를 읽는다. 못 찾으면 오류 없이 코어가 없는 것으로 본다', async () => {
  reset()
  fake.add(agentTerm('t1', 'working', { labels: SPACE }))
  const keep = { HC_SOCKET: process.env.HC_SOCKET, XDG_STATE_HOME: process.env.XDG_STATE_HOME }
  const state = join(dir, 'xdg-state')
  const lockDir = join(state, 'herdr-core', 'whosuptest-unit')
  mkdirSync(lockDir, { recursive: true })
  try {
    delete process.env.HC_SOCKET
    process.env.XDG_STATE_HOME = state
    // 1) lock 파일이 없다(코어를 한 번도 띄운 적 없는 기계, 또는 상태 폴더가 다른 곳에 있는 운영체제)
    assert.equal(core.socketPath(), null)
    assert.equal(core.available(), false)
    const empty = openDb(':memory:')
    const r1 = await collectAll(empty)
    assert.deepEqual(r1.runs, [])                                                    // 코어 쪽은 아무것도 하지 않는다
    assert.equal(empty.prepare("SELECT COUNT(*) AS n FROM session WHERE runtime = 'herdr-core'").get().n, 0)
    assert.equal(getMeta(empty, 'collect_err_kind'), 'no_herdr')                      // 남는 것은 예전부터 있던 herdr 없음뿐
    // 2) lock은 있는데 그 소켓이 없다(코어가 꺼져 있음)
    writeFileSync(join(lockDir, 'core.lock'), `${join(dir, 'gone.sock')}\n`)
    assert.equal(core.socketPath(), join(dir, 'gone.sock'))
    assert.equal(core.available(), false)
    assert.equal((await core.snapshotRuntime()).absent, true)
    // 3) lock이 살아 있는 소켓을 가리킨다
    writeFileSync(join(lockDir, 'core.lock'), `${SOCK}\n`)
    assert.equal(core.available(), true)
    const db = openDb(':memory:')
    const r3 = await collectAll(db)
    assert.deepEqual(r3.runs.map((x) => [x.name, x.sessions]), [['herdr-core', 1]])
    // HC_SOCKET을 주면 lock보다 먼저다
    process.env.HC_SOCKET = join(dir, 'other.sock')
    assert.equal(core.socketPath(), join(dir, 'other.sock'))
  } finally {
    process.env.HC_SOCKET = keep.HC_SOCKET
    if (keep.XDG_STATE_HOME === undefined) delete process.env.XDG_STATE_HOME; else process.env.XDG_STATE_HOME = keep.XDG_STATE_HOME
  }
})

test('herdr와 함께: 두 쪽 칸이 다 나오고 herdr 쪽 수집 상태가 판의 건강 상태를 정한다', async () => {
  reset()
  fake.add(agentTerm('t1', 'working', { labels: SPACE }))
  const db = openDb(':memory:')
  const herdrFake = { name: 'herdr', FIELDS: core.FIELDS, TRACKS_GONE: true, listSnapshot: () => ({ sessions: [
    { runtime: 'herdr', runtime_ref: 'main/w1:p1', provider_session: null, cwd: '/work/a', project: 'a', title: 'a', pane_label: 'alpha', provider: 'claude', status: 'blocked', attentionTimestamp: null, archived: false,
      fields: { lastStatus: 'error', requiresAttention: true, attentionReason: 'blocked', lastUserMessageAt: null, title: 'a' } }], unreachable: ['side'], stopped: [] }) }
  collectOnce(db, herdrFake)
  collectOnce(db, await core.snapshotRuntime(), { health: false })
  const b = computeBoard(db, { withContext: false })
  const cards = Object.values(b.columns).flat()
  assert.deepEqual(cards.map((c) => [c.runtime, c.desk, c.desk_label]).sort(), [['herdr', 'main', 'main'], ['herdr-core', 'core:spA', 'my project']])
  assert.deepEqual(b.health.unreachable, ['side'])          // 코어 수집이 herdr의 기록을 덮지 않는다
  assert.ok(cards.every((c) => Array.isArray(c.caps)))
})

test('질문 문구: 코어 꼬리표를 떼고, 문구가 없으면 null(화면에서 찾게)', () => {
  assert.deepEqual(coreQuestion({ statusKind: 'question', statusMsg: 'answer: A와 B 중 어느 쪽? (A · B)' }), { text: 'A와 B 중 어느 쪽? (A · B)', kind: 'question' })
  assert.deepEqual(coreQuestion({ statusKind: 'permission', statusMsg: 'approve Bash: rm -rf x' }), { text: 'Bash: rm -rf x — 승인할까요?', kind: 'approval' })
  assert.equal(coreQuestion({ statusKind: 'question', statusMsg: '' }), null)
})

// ── 코드 리뷰에서 찾은 경계 (2026-11-11) ─────────────────────────────
// Codex 0.167의 폴더 신뢰 화면과 그 다음 화면(격리 시험 코어에서 읽은 그대로)
const CODEX_TRUST = `  Folder access
  /private/tmp/some-project
  Trust this folder? Codex can read, edit, and run files here, subject to your permission settings. Folder settings can run code automatically, even without a model request. Continue only if
  trust these files. Your trust decision will be saved.
› 1. Trust and continue
  2. Back to Agent Command Center
  enter continue · esc back
`
const CODEX_HOOKS = `  Hooks need review
  22 hooks are new or changed.
  Hooks can run outside the sandbox after you trust them.
› 1. Review hooks
  2. Trust all and continue
  3. Continue without trusting (hooks won't run)
  enter confirm · esc skip
`

test('폴더 신뢰 화면: 커서가 어느 선택지에 있어도, Codex의 화면도 같은 대기로 본다. 같은 낱말이 있는 다른 화면은 아니다', () => {
  assert.equal(isTrustScreen(TRUST_SCREEN), true)
  const onYes = TRUST_SCREEN.replace(' ❯ No, exit\n   Yes, I trust this folder', '   No, exit\n ❯ Yes, I trust this folder')
  assert.notEqual(onYes, TRUST_SCREEN)
  assert.equal(isTrustScreen(onYes), true)                                                  // 커서를 Yes로 옮긴 화면
  assert.equal(questionOf(onYes), TRUST_QUESTION)                                           // herdr 카드의 질문 추출도 같은 답
  assert.equal(isTrustScreen(CODEX_TRUST), true)
  assert.equal(isTrustScreen(CODEX_TRUST.replace('› 1. Trust and continue\n  2. Back', '  1. Trust and continue\n› 2. Back')), true)
  assert.equal(isTrustScreen(CODEX_HOOKS), false)                                           // 신뢰를 묻지만 폴더 신뢰가 아니다
  // 문서를 보여 주는 프로그램: 문장이 같아도 대화상자가 아니다(선택지와 맨 아래 Enter 안내가 없다)
  assert.equal(isTrustScreen('notes.md\n\nWhen the agent asks "Do you trust this folder?" pick: Yes, I trust this folder\nMore text here.\n:'), false)
  assert.equal(isTrustScreen('Do you trust this folder?\n(END)'), false)
  assert.equal(isTrustScreen('How to answer the prompt\n\n  Trust this folder?\n  Yes, I trust this folder\n\nSome more prose that goes on.\nAnd on.\nAnd on.\n~'), false)
  assert.equal(isTrustScreen(''), false)
})

test('신뢰 대기 카드의 질문 문구는 화면을 다시 읽지 못해도 나온다(수집이 이미 그 질문으로 확인했다)', async () => {
  reset()
  fake.add(waitingAgent('t1')); fake.screens.set('t1', TRUST_SCREEN)
  const db = openDb(':memory:'); await collectAll(db)
  fake.screens.delete('t1')                                                                 // 보드가 따로 읽을 때는 화면이 비어 있어도
  const card = Object.values((await computeBoardAsync(db)).columns).flat().find((c) => c.ref.endsWith('/t1'))
  assert.deepEqual([card.status, card.question, card.ask_kind], ['blocked', TRUST_QUESTION.text, 'approval'])
  assert.equal(coreQuestion({ statusKind: 'trust', statusMsg: null }), TRUST_QUESTION)
})

test('화면에서 읽은 글은 그 터미널의 것만: 같은 주소를 물려받은 새 터미널에 앞 터미널의 마지막 답변이 붙지 않는다', async () => {
  reset()
  fake.add(agentTerm('t1', 'done', { labels: SPACE, created_ms: 1000 }))
  fake.screens.set('t1', `⏺ Old answer from the first terminal.\n${'─'.repeat(40)}\n❯ \n${'─'.repeat(40)}\n`)
  const db = openDb(':memory:'); await collectAll(db)
  const say = async () => Object.values((await computeBoardAsync(db)).columns).flat().find((c) => c.ref.endsWith('/t1') && c.status === 'done')?.last_say
  assert.equal(await say(), 'Old answer from the first terminal.')
  fake.terminals.clear(); fake.screens.clear(); fake.add(agentTerm('t1', 'done', { labels: SPACE, created_ms: 2000 }))
  await collectAll(db)
  assert.notEqual(await say(), 'Old answer from the first terminal.')
})

test('신뢰 화면 읽기: 겹친 수집은 진행 중인 읽기 하나를 나눠 쓴다', async () => {
  reset()
  fake.add(waitingAgent('t1')); fake.screens.set('t1', TRUST_SCREEN)
  const snaps = await Promise.all([core.listSnapshotAsync(), core.listSnapshotAsync(), core.listSnapshotAsync()])
  assert.equal(fake.calls.filter((c) => c.method === 'terminal.read').length, 1)
  assert.deepEqual(snaps.map((s) => s.sessions[0].status), ['blocked', 'blocked', 'blocked'])
})

test('끝난 턴 하나는 한 사건이다: done이 idle로 바뀌며 코어의 시각이 달라져도 대기 시작 시각과 알림 기록은 그대로다', async () => {
  reset()
  fake.add(agentTerm('t1', 'done', { status: { app: 'codex', state: 'done' }, labels: SPACE, turn: 2, status_ms: 1794000100000 }))
  const db = openDb(':memory:'); await collectAll(db)
  const row = () => db.prepare("SELECT id, status, attention_since, alert_count FROM session WHERE runtime = 'herdr-core'").get()
  const first = row()
  assert.equal(first.status, 'done')
  db.prepare('UPDATE session SET alert_count = 2, last_alert_at = ? WHERE id = ?').run(new Date().toISOString(), first.id)   // 이미 알림이 나갔다
  fake.set('t1', { status: { app: 'codex', state: 'idle' }, status_ms: 1794000102000 })     // 실측: Codex는 done 2초 뒤 idle
  await collectAll(db)
  assert.deepEqual([row().status, row().attention_since, row().alert_count], ['done', first.attention_since, 2])
  // 새 턴이 끝나면 새 사건이다
  fake.set('t1', { turn: 3, status_ms: 1794000200000 })
  await collectAll(db)
  assert.equal(row().status, 'done')
  assert.notEqual(row().attention_since, first.attention_since)
  assert.equal(row().alert_count, 0)
})

test('수집 공백은 런타임마다 잰다: 판의 건강 상태를 herdr가 적는 기계에서도 herdr-core 카드의 대기 시작 시각이 수집마다 새로 잡히지 않는다', async () => {
  reset()
  fake.add(waitingAgent('t1')); fake.screens.set('t1', TRUST_SCREEN)                        // 코어가 시각을 주지 않는 대기
  const db = openDb(':memory:')
  const t0 = Date.parse('2026-11-11T00:00:00Z')
  const stale = new Date(t0 - 600000).toISOString()
  setMeta(db, 'collect_ok_at', stale)                                                       // herdr 쪽은 10분째 읽히지 않는다(판의 건강 상태는 herdr가 적는다)
  const run = async (ms) => collectOnce(db, await core.snapshotRuntime(), { now: new Date(t0 + ms), health: false })
  await run(0)
  const since = () => db.prepare("SELECT attention_since FROM session WHERE runtime = 'herdr-core'").get().attention_since
  const first = since()
  assert.ok(first)
  await run(3000); await run(6000)
  assert.equal(since(), first)
  assert.equal(getMeta(db, 'collect_ok_at'), stale)                                         // 공용 값(판의 건강 상태)은 이 런타임이 적지 않았다
})

test('대화 id는 지금 그 터미널에서 도는 Claude의 것만: 다른 에이전트로 바뀌면 남아 있는 등록부·실행 인자를 읽지 않는다', async () => {
  reset()
  writeFileSync(join(dir, 'claude', 'sessions', '70009.json'), JSON.stringify({ pid: 70009, sessionId: SID, cwd: '/work' }))
  fake.add(agentTerm('t9', 'working', { labels: SPACE }))
  assert.equal((await core.listSnapshotAsync()).sessions[0].provider_session, SID)
  fake.set('t9', { status: { app: 'codex', state: 'working' } })                            // 같은 pid의 등록부 파일이 남아 있어도
  const s = (await core.listSnapshotAsync()).sessions[0]
  assert.deepEqual([s.provider, s.provider_session], ['codex', null])
})

test('실행 인자에서 대화 id: 진짜 옵션만 읽는다(프롬프트 글 속의 같은 글자는 아니다)', () => {
  const f = core.sidFromArgv
  assert.equal(f(['claude', '--resume', SID]), SID)
  assert.equal(f(['claude', '-r', SID]), SID)
  assert.equal(f(['claude', `--session-id=${SID}`]), SID)
  assert.equal(f(['zsh', '-ic', `claude --resume ${SID}`]), SID)
  assert.equal(f(['zsh', '-ic', `claude -r ${SID}`]), SID)
  assert.equal(f(['claude', '-p', `explain what --resume ${SID} does`]), null)               // 프롬프트 글 속
  assert.equal(f(['zsh', '-ic', `claude -p "run with --resume ${SID}"`]), null)              // 셸 줄의 따옴표 안
  assert.equal(f(['claude', '--resume', `${SID}x`]), null)
  assert.equal(f(['python3', '-c', `print("--resume ${SID}")`]), null)                       // 셸이 아닌 프로그램의 -c
  assert.equal(f([]), null)
})

test('다른 에이전트로 바뀌면 옛 대화 id를 몰랐어도 새 카드로 시작한다(고정·확인이 새 프로그램의 카드로 넘어가지 않는다)', async () => {
  reset()
  fake.add(agentTerm('t2', 'idle', { labels: SPACE }))                                      // Claude, 대화 id는 모른다
  const db = openDb(':memory:'); await collectAll(db)
  db.prepare("UPDATE session SET pinned_at = ? WHERE runtime = 'herdr-core'").run(new Date().toISOString())
  fake.set('t2', { status: { app: 'codex', state: 'working' }, foreground: { argv: ['codex'], cwd: '/work', name: 'codex', pid: 70002 } })
  await collectAll(db)
  const rows = db.prepare("SELECT provider, archived, status, pinned_at FROM session WHERE runtime = 'herdr-core' ORDER BY id").all()
  assert.deepEqual(rows.map((r) => [r.provider, r.archived, r.status, Boolean(r.pinned_at)]), [['claude', 1, 'gone', true], ['codex', 0, 'working', false]])
})

test('toSession: 턴 값이 정수가 아니면 없는 것으로 본다. 지금 턴보다 큰 "본 턴"은 앞 프로그램이 남긴 기록이라 쓰지 않는다', () => {
  const codexIdle = (over) => core.toSession(agentTerm('t1', 'idle', { status: { app: 'codex', state: 'idle' }, ...over }))
  assert.equal(codexIdle({ turn: 'x' }).status, 'idle')
  assert.equal(codexIdle({ turn: 1.5 }).status, 'idle')
  assert.equal(codexIdle({ turn: -3 }).status, 'idle')
  const fin = core.toSession(agentTerm('t1', 'done', { turn: 1, labels: { 'whosup.seen': '12' } }))
  assert.deepEqual([fin.status, fin.fields.turn, fin.fields.attentionKey], ['done', 1, 'done:1'])
  assert.equal(core.toSession(agentTerm('t1', 'working', { turn: 1 })).fields.attentionKey, null)
  assert.equal(core.toSession(agentTerm('t1', 'done', { turn: 0 })).fields.attentionKey, null)            // 턴 수를 모르면 사건 열쇠도 없다
  // 옛 기록 하나가 맞는 기록까지 지우지 않는다: 앞 프로그램이 남긴 큰 값은 그것만 빼고 본다
  const done = (turn, labels) => core.toSession(agentTerm('t1', 'done', { turn, labels })).status
  assert.equal(done(2, { 'herdr.seen': '7', 'whosup.seen': '2' }), 'idle')
  assert.equal(done(1, { 'herdr.seen': '1', 'whosup.seen': '12' }), 'idle')
  assert.equal(done(3, { 'herdr.seen': '99', 'whosup.seen': '2' }), 'done')
  assert.equal(codexIdle({ turn: 2, labels: { 'herdr.seen': '7', 'whosup.seen': '2' } }).status, 'idle')
})

test('실패 표시는 코어가 오류라고 알린 칸뿐이다(답변 글 속의 오류 낱말로 추측하지 않는다)', async () => {
  reset()
  fake.add(agentTerm('t1', 'done', { labels: SPACE }))
  fake.screens.set('t1', `⏺ Fixed the API Error: 500 handler and added a test.\n${'─'.repeat(40)}\n❯ \n${'─'.repeat(40)}\n`)
  fake.add(agentTerm('t2', 'error', { labels: SPACE }))
  const db = openDb(':memory:'); await collectAll(db)
  const cards = Object.values((await computeBoardAsync(db)).columns).flat()
  const by = (t) => cards.find((c) => c.ref.endsWith(`/${t}`))
  assert.deepEqual([by('t1').failed, by('t1').last_say], [false, 'Fixed the API Error: 500 handler and added a test.'])
  assert.equal(by('t2').failed, true)
})

test('코어의 답이 이상해도 죽지 않는다: JSON-RPC 꼴이 아닌 줄은 오류로, 답 없이 끊긴 연결은 기다리지 않고 오류로. 수집은 그 사정을 알린다', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE }))
  const db = openDb(':memory:'); await collectAll(db)
  for (const junk of ['null\n', '[1,2]\n', '"text"\n', '7\n']) {
    fake.override = () => junk
    await assert.rejects(core.rpc('terminal.list', {}), (e) => e.code === 'EPROTO', junk.trim())
  }
  fake.override = () => 'close'
  const at = Date.now()
  await assert.rejects(core.rpc('terminal.list', {}), (e) => e.code === 'ECONNRESET')
  assert.ok(Date.now() - at < 1500, '끊긴 연결을 시간 초과까지 기다리지 않는다')
  // 수집: 칸은 확인 불가로 남고, 왜 그런지가 결과에 실린다
  const r = await collectAll(db)
  assert.equal(r.notes.length, 1)
  assert.match(r.notes[0], /^herdr-core: /)
  assert.deepEqual(Object.values(db.prepare("SELECT archived, unreachable FROM session WHERE runtime = 'herdr-core'").get()), [0, 1])
  fake.override = null
  assert.deepEqual((await collectAll(db)).notes, [])
  assert.deepEqual(Object.values(db.prepare("SELECT archived, unreachable FROM session WHERE runtime = 'herdr-core'").get()), [0, 0])
})

test('변화 알림: event 줄만 수집을 깨운다(다른 줄 안에 같은 글자가 있어도 아니다)', async () => {
  reset()
  let kicks = 0
  core.watchEvents(() => { kicks += 1 })
  await sleep(80); kicks = 0
  fake.emitRaw('{"jsonrpc":"2.0","id":7,"result":{"note":{"method":"event"}}}\n')           // 줄 안에 "method":"event" 글자가 있지만 event가 아니다
  await sleep(60)
  assert.equal(kicks, 0)
  fake.emitRaw('{"jsonrpc":"2.0","method":"event","params":{"type":"status","terminal":"t1"}}\n')
  await sleep(60)
  assert.equal(kicks, 1)
  core.stopWatching()
})

test('오래 닿지 않은 칸만 닫는다: 후즈업을 오래 꺼 두었다 켠 직후 코어에 한 번 닿지 못했다고 닫지 않는다', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE }))
  const db = openDb(':memory:')
  const t0 = Date.parse('2026-11-01T00:00:00Z')
  await collectAll(db, { now: new Date(t0) })
  const row = () => Object.values(db.prepare("SELECT archived, status, unreachable FROM session WHERE runtime = 'herdr-core'").get())
  fake.override = () => 'close'                                                              // 30시간 뒤 다시 켰는데 코어가 답하지 않는다
  await collectAll(db, { now: new Date(t0 + 30 * 3600000) })
  assert.deepEqual(row(), [0, 'idle', 1])                                                    // 닿지 않은 것은 방금부터다
  await collectAll(db, { now: new Date(t0 + 31 * 3600000) })
  assert.deepEqual(row(), [0, 'idle', 1])
  await collectAll(db, { now: new Date(t0 + 55 * 3600000) })                                 // 닿지 않은 채로 하루가 넘었다
  assert.deepEqual(row().slice(0, 2), [1, 'gone'])
  fake.override = null
})

// ── 위 수정 묶음을 다시 검토해 찾은 경계 ──────────────────────────────
test('턴 수를 알리지 않는 터미널: 끝난 턴이 새로 오면 새 사건이다(사건 열쇠가 없으면 코어의 시각을 따른다)', async () => {
  reset()
  fake.add(agentTerm('t1', 'done', { labels: SPACE, turn: 0, status_ms: 1794000100000 }))
  const db = openDb(':memory:'); await collectAll(db)
  const since = () => db.prepare("SELECT attention_since FROM session WHERE runtime = 'herdr-core'").get().attention_since
  const first = since()
  fake.set('t1', { status_ms: 1794000200000 })                                                // 그 사이 한 턴이 더 끝났다(수집은 작업 중을 보지 못했다)
  await collectAll(db)
  assert.notEqual(since(), first)
})

test('닿지 않기 시작한 때는 후즈업이 지켜본 동안만 센다: 꺼지기 직전에 적힌 값으로 다시 켠 첫 수집에서 칸을 닫지 않는다', async () => {
  reset()
  fake.add(agentTerm('t1', 'idle', { labels: SPACE }))
  const t0 = Date.parse('2026-11-01T00:00:00Z')
  const run = async (restart) => {
    const db = openDb(':memory:')
    fake.override = null
    await collectAll(db, { now: new Date(t0) })
    fake.override = () => 'close'
    await collectAll(db, { now: new Date(t0 + 3000) })                                        // 코어가 답하지 않기 시작했고, 곧 후즈업도 꺼졌다
    if (restart) forgetDownSince(db)                                                          // 30시간 뒤 후즈업이 다시 뜬다
    await collectAll(db, { now: new Date(t0 + 30 * 3600000) })
    return Object.values(db.prepare("SELECT archived, status FROM session WHERE runtime = 'herdr-core'").get())
  }
  assert.deepEqual(await run(true), [0, 'idle'])
  assert.deepEqual(await run(false), [1, 'gone'])                                             // 같은 프로세스가 30시간 내내 닿지 못한 것이면 닫는다
  fake.override = null
})

test('화면 캐시는 지금 판의 카드 것만 남긴다(턴이 넘어갈 때마다 쌓이지 않는다)', async () => {
  reset()
  fake.add(agentTerm('t1', 'done', { labels: SPACE, turn: 1 }))
  const db = openDb(':memory:')
  const coreKeys = () => _cacheKeys().filter((k) => k.startsWith('pane:core:'))
  for (const turn of [1, 2, 3, 4]) { fake.set('t1', { turn }); await collectAll(db); await computeBoardAsync(db) }
  assert.equal(coreKeys().length, 1)
  assert.match(coreKeys()[0], /:done:4$/)
})
