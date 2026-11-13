// I-10 읽기 전용 게이트는 모든 입구에: 서버는 code read_only로 답하고, 화면의 동작 함수는 모두 같은 문지기를 지난다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { openDb } from '../src/db.mjs'
import { createBoardServer } from '../src/board/server.mjs'

test('I-10: 읽기 전용이면 POST는 code read_only', async () => {
  process.env.WHOSUP_READONLY = '1'
  const srv = createBoardServer(openDb(':memory:'))
  await new Promise((r) => srv.listen(0, '127.0.0.1', r))
  try {
    const res = await fetch(`http://127.0.0.1:${srv.address().port}/api/seen`, { method: 'POST', body: '{"id":1}' })
    assert.equal(res.status, 403)
    assert.equal((await res.json()).code, 'read_only')
  } finally { srv.close(); delete process.env.WHOSUP_READONLY }
})

test('I-10: 읽기 전용이면 폴더 목록(GET /api/folders·/api/dirs)도 code read_only', async () => {
  process.env.WHOSUP_READONLY = '1'
  const srv = createBoardServer(openDb(':memory:'))
  await new Promise((r) => srv.listen(0, '127.0.0.1', r))
  try {
    for (const path of ['/api/folders', '/api/dirs', '/api/dirs?path=%2F']) {
      const res = await fetch(`http://127.0.0.1:${srv.address().port}${path}`)
      assert.equal(res.status, 403, path)
      assert.equal((await res.json()).code, 'read_only', path)
    }
    delete process.env.WHOSUP_READONLY
    const res = await fetch(`http://127.0.0.1:${srv.address().port}/api/folders`)
    assert.equal(res.status, 200, '읽기 전용이 아니면 그대로 열린다')
  } finally { srv.close(); delete process.env.WHOSUP_READONLY }
})

test('I-10: 열기·확인함·이어서 열기·알림 클릭·키보드가 모두 can()을 지난다', () => {
  const html = readFileSync(new URL('../src/board/index.html', import.meta.url), 'utf8')
  for (const fn of ['openCard', 'doAct', 'resumeCard', 'showNew', 'saveSettings', 'createSession']) assert.match(html, new RegExp(`async function ${fn}\\([^)]*\\) \\{\\n\\s+if \\(!can\\(\\)\\)`), fn)
  assert.doesNotMatch(html, /async function markSeen/, '확인함은 doAct 경로 하나로(실패하면 토스트)')
  assert.match(html, /read_only:/)
})

test('I-10: 읽기 전용 화면은 + 새 세션 버튼을 숨기고, 설정 패널에는 언어만 두고 저장 버튼을 내지 않는다', () => {
  const html = readFileSync(new URL('../src/board/index.html', import.meta.url), 'utf8')
  assert.match(html, /querySelector\('\[data-new\]'\)\.hidden = Boolean\(ro\)/)
  const fn = html.match(/async function showSettings\(\) \{[\s\S]*?\n\}\n/)[0]
  const ro = fn.match(/if \(!can\(\)\) \{([\s\S]*?)\n  \}/)
  assert.ok(ro, 'showSettings에 읽기 전용 분기가 있다')
  assert.ok(fn.indexOf('if (!can())') < fn.indexOf("fetch('/api/settings')"), '읽기 전용이면 서버 설정을 불러오기 전에 끝난다')
  assert.doesNotMatch(ro[1], /data-save-settings|data-setting/, '읽기 전용 패널에는 저장 버튼·설정 칸이 없다')
  assert.match(ro[1], /langRow/, '언어 전환은 남는다')
  for (const lang of ['ko', 'en']) assert.match(html, new RegExp(`${lang}: \\{ roSettings: '`), lang)
})
