// I-12 같은 모양의 지뢰를 텍스트로 막는다: 리스너 없는 spawn, 타임아웃 없는 execFile(Sync), 빈 콜백.
// 예외는 같은 줄의 `// guard-ok: 이유` 주석으로만.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const files = ['src', 'src/board', 'src/runtime', 'bin', 'scripts'].flatMap((d) =>
  readdirSync(join(ROOT, d)).filter((f) => f.endsWith('.mjs')).map((f) => join(d, f)))

// 여는 괄호부터 짝이 맞는 닫는 괄호까지(호출 하나)
function callAt(text, i) {
  let depth = 0
  for (let k = text.indexOf('(', i); k < text.length; k++) {
    if (text[k] === '(') depth++
    else if (text[k] === ')' && --depth === 0) return text.slice(i, k + 1)
  }
  return text.slice(i)
}
const lineOf = (text, i) => text.slice(text.lastIndexOf('\n', i) + 1, text.indexOf('\n', i))

test('spawn에는 error 리스너가 붙어 있다', () => {
  const bad = []
  for (const f of files) {
    const text = readFileSync(join(ROOT, f), 'utf8')
    for (const m of text.matchAll(/\bspawn\(/g)) {
      if (/guard-ok/.test(lineOf(text, m.index))) continue
      const before = text.slice(text.lastIndexOf('\n', m.index) + 1, m.index)
      const v = before.match(/(?:const|let)\s+(\w+)\s*=\s*$/)
      const call = callAt(text, m.index)
      const after = text.slice(m.index + call.length, m.index + call.length + 40)
      const ok = v ? new RegExp(`\\b${v[1]}\\.(once|on)\\('error'`).test(text) : /^\s*\.(once|on)\('error'/.test(after)
      if (!ok) bad.push(`${f}: ${lineOf(text, m.index).trim().slice(0, 90)}`)
    }
  }
  assert.deepEqual(bad, [])
})

test('execFile·execFileSync에는 timeout이 있다', () => {
  const bad = []
  for (const f of files) {
    const text = readFileSync(join(ROOT, f), 'utf8')
    for (const m of text.matchAll(/\bexecFile(Sync)?\((?!\s*\))/g)) {
      if (/guard-ok|import /.test(lineOf(text, m.index))) continue
      if (!/timeout/.test(callAt(text, m.index))) bad.push(`${f}: ${lineOf(text, m.index).trim().slice(0, 90)}`)
    }
  }
  assert.deepEqual(bad, [])
})

test('execFile 계열 콜백은 비어 있지 않거나 어디서 관측하는지 적혀 있다', () => {
  const bad = []
  for (const f of files) {
    const text = readFileSync(join(ROOT, f), 'utf8')
    for (const m of text.matchAll(/\bexecFile\(/g)) {
      const call = callAt(text, m.index)
      if (/\(\s*\)\s*=>\s*\{\s*\}\s*\)$/.test(call) && !/observed:/.test(lineOf(text, m.index))) bad.push(`${f}: ${lineOf(text, m.index).trim().slice(0, 90)}`)
    }
  }
  assert.deepEqual(bad, [])
})

test('#11: 상주 서버의 execFileSync는 타임아웃 때 SIGKILL로 끊는다(SIGTERM을 무시하는 자식이 요청을 붙잡지 않게)', () => {
  const bad = []
  for (const f of files.filter((x) => x.startsWith('src/'))) {
    const text = readFileSync(join(ROOT, f), 'utf8')
    for (const m of text.matchAll(/\bexecFileSync\((?!\s*\))/g)) {
      const line = lineOf(text, m.index)
      if (/import /.test(line)) continue
      const call = callAt(text, m.index)
      if (!/SIGKILL/.test(call) && !/quiet/.test(call) && !/guard-ok: SIGKILL/.test(line)) bad.push(`${f}: ${line.trim().slice(0, 90)}`)
    }
  }
  assert.deepEqual(bad, [])
})

test('#11: 화면 새로고침은 한 번에 하나, 8초 타임아웃, 탭 복귀 즉시', () => {
  const html = readFileSync(join(ROOT, 'src/board/index.html'), 'utf8')
  assert.match(html, /AbortSignal\.timeout\(8000\)/)
  assert.match(html, /refreshing/)
  assert.match(html, /visibilitychange/)
})
