// I-3 화면에 보인 재개 대상 = 실제로 여는 대상(resumeTarget 하나). #9 다른 칸의 살아 있는 대화 제외,
// #20 대화 줄이 있는 기록만, #18 공급자가 다르면 재개하지 않음.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, utimesSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = mkdtempSync(join(tmpdir(), 'whosup-proj-'))
process.env.CLAUDE_PROJECTS_DIR = root
process.env.HERDR_BIN = fileURLToPath(new URL('../test-support/fake-herdr.mjs', import.meta.url))
const { resumeTarget, clearContextCache } = await import('../src/board/context.mjs')
const { openDb } = await import('../src/db.mjs')
const { collectOnce } = await import('../src/collector.mjs')
const { computeBoard } = await import('../src/board/board.mjs')
const { resumeSession } = await import('../src/board/server.mjs')

const CWD = '/work/whosup-resume-proj'
const dir = join(root, CWD.replace(/[^A-Za-z0-9]/g, '-'))
mkdirSync(dir, { recursive: true })
const id = (n) => `0000000${n}-0000-4000-8000-000000000000`
const conv = (n, text, minAgo) => {
  const f = join(dir, `${id(n)}.jsonl`)
  writeFileSync(f, JSON.stringify({ type: 'user', timestamp: '2026-11-08T10:00:00Z', message: { content: text } }) + '\n')
  const t = new Date(Date.now() - minAgo * 60000); utimesSync(f, t, t)
}
const empty = (n, minAgo) => {
  const f = join(dir, `${id(n)}.jsonl`)
  writeFileSync(f, JSON.stringify({ type: 'summary', summary: 'x' }) + '\n')
  const t = new Date(Date.now() - minAgo * 60000); utimesSync(f, t, t)
}
conv(1, '옛 대화', 30)
conv(2, '다른 칸에서 진행 중', 5)
empty(3, 1) // 가장 최신이지만 대화 줄이 없음

const shell = { id: 9, provider: null, provider_session: null, cwd: CWD }

test('#20·#9: 대화 줄 없는 기록과 다른 칸의 살아 있는 대화는 건너뛴다', () => {
  clearContextCache()
  assert.equal(resumeTarget(shell, { cmd: 'claude' }).sid, id(2), '대화 줄 없는 최신 기록은 건너뜀')
  clearContextCache()
  const t = resumeTarget(shell, { cmd: 'claude', exclude: new Set([id(2)]) })
  assert.equal(t.sid, id(1))
  assert.equal(t.from, 'folder')
  assert.equal(t.prompt, '옛 대화')
})

test('I-3: 칸이 기억하는 대화가 살아 있지 않고 기록이 있으면 그 칸의 대화를 연다', () => {
  clearContextCache()
  const t = resumeTarget({ ...shell, provider: 'claude', provider_session: id(1) }, { cmd: 'claude' })
  assert.deepEqual([t.sid, t.from], [id(1), 'pane'])
  clearContextCache()
  const t2 = resumeTarget({ ...shell, provider: 'claude', provider_session: id(1) }, { cmd: 'claude', exclude: new Set([id(1), id(2)]) })
  assert.equal(t2, null, '칸의 대화가 다른 칸에서 살아 있고 폴더에도 남은 게 없으면 새로 시작')
})

test('#18: 실행 명령이나 칸의 공급자가 Claude가 아니면 Claude 기록으로 재개하지 않는다', () => {
  clearContextCache()
  assert.equal(resumeTarget(shell, { cmd: 'codex' }), null)
  assert.equal(resumeTarget({ ...shell, provider: 'codex', provider_session: id(1) }, { cmd: 'claude' }), null)
  assert.ok(resumeTarget(shell, { cmd: 'cco --model x' }), '알 수 없는 래퍼 명령은 막지 않는다')
})

test('I-3: 판이 보여 준 재개 대상과 서버가 다시 계산한 대상이 다르면 실행하지 않는다', async () => {
  clearContextCache()
  const db = openDb(':memory:')
  const pane = (ref, status, ps) => ({ runtime: 'herdr', runtime_ref: ref, provider_session: ps, cwd: CWD, project: 'p', title: ref, pane_label: null,
    provider: status === 'shell' ? null : 'claude', status, attentionTimestamp: null, archived: false,
    fields: { lastStatus: status, requiresAttention: false, attentionReason: null, lastUserMessageAt: null, title: ref } })
  const rt = { name: 'herdr', TRACKS_GONE: true, FIELDS: ['lastStatus', 'requiresAttention', 'attentionReason', 'lastUserMessageAt', 'title'],
    listSnapshot: () => ({ sessions: [pane('main/w1:p1', 'shell', null), pane('main/w1:p2', 'working', id(2))], unreachable: [] }) }
  collectOnce(db, rt, { emit: false })
  const b = computeBoard(db)
  const card = Object.values(b.columns).flat().find((c) => c.ref === 'main/w1:p1')
  assert.equal(card.resume.sid, id(1), '다른 칸(p2)에서 살아 있는 대화는 보이지 않는다')
  assert.equal(card.recent_prompt, '옛 대화')
  const r = await resumeSession(db, card.id, id(2))
  assert.equal(r.code, 'resume_changed')
})
