// I-11 설정 패널은 서버 키 표에서 파생되고, 라벨이 빠진 키는 테스트가 잡는다. 값의 출처도 거짓 없이.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { openDb } from '../src/db.mjs'
import { SETTINGS, setSettings, settingSources } from '../src/settings.mjs'

const html = readFileSync(new URL('../src/board/index.html', import.meta.url), 'utf8')
const I18N = new Function(`${html.match(/const I18N = \{[\s\S]*?\n\}\n/)[0]}; return I18N`)()

test('모든 숫자 설정 키에 ko·en 라벨이 있다', () => {
  for (const lang of ['ko', 'en']) for (const k of Object.keys(SETTINGS)) assert.ok(I18N[lang].setItems[k], `${lang}.setItems.${k} 없음`)
})

test('패널은 T.setItems가 아니라 서버 키 표(ranges)를 돈다', () => {
  assert.doesNotMatch(html, /Object\.entries\(T\.setItems\)/)
})

test('저장은 불러온 값과 달라진 칸만 보낸다', () => {
  assert.match(html, /data-loaded/)
})

test('settingSources: 저장값·환경변수·기본값 출처를 구분한다', () => {
  const db = openDb(':memory:')
  process.env.WHOSUP_RENOTIFY_MIN = '20'
  try {
    setSettings(db, { seen_snooze_min: 10 })
    const src = settingSources(db)
    assert.equal(src.seen_snooze_min, 'saved')
    assert.equal(src.renotify_min, 'env')
    assert.equal(src.renotify_max, 'default')
  } finally { delete process.env.WHOSUP_RENOTIFY_MIN }
})
