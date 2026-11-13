// #15 수집 실패를 세 갈래(no_herdr·no_reply·failed)로 나누고 판에 이유를 싣는다.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { openDb } from '../src/db.mjs'
import { collectOnce } from '../src/collector.mjs'
import { computeBoard } from '../src/board/board.mjs'

const fail = (props) => ({ name: 'herdr', TRACKS_GONE: true, FIELDS: [], listSnapshot() { throw Object.assign(new Error(props.message || 'boom'), props) } })
const kindOf = (props) => {
  const db = openDb(':memory:')
  assert.throws(() => collectOnce(db, fail(props)))
  return computeBoard(db, { withContext: false }).health.error_kind
}

test('#15: herdr 실행 파일 없음 → no_herdr', () => assert.equal(kindOf({ code: 'ENOENT', message: 'spawnSync herdr ENOENT' }), 'no_herdr'))
test('#15: 응답 없음(시간 초과·강제 종료) → no_reply', () => {
  assert.equal(kindOf({ code: 'ETIMEDOUT', message: 'spawnSync herdr ETIMEDOUT' }), 'no_reply')
  assert.equal(kindOf({ signal: 'SIGKILL', message: 'killed' }), 'no_reply')
})
test('#15: 그 밖 → failed', () => assert.equal(kindOf({ message: 'Unexpected token' }), 'failed'))
