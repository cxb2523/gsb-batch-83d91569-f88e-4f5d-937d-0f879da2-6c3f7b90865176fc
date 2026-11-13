import { test } from 'node:test'
import assert from 'node:assert/strict'
import { argv, input, rows, failure } from './contract.mjs'

test('read allowlist excludes writes, arbitrary commands and invalid arguments', () => {
  for (const tool of ['reddit_comment', 'reddit_upvote', 'browser', 'reddit_post']) {
    assert.throws(() => input({ action: 'query', tool, cookie: '', args: {} }), /unsupported/)
  }
  assert.throws(() => input({ action: 'query', tool: 'reddit_subreddit_posts', cookie: '', args: { subreddit: '../x' } }), /bad_input/)
  assert.throws(() => input({ action: 'query', tool: 'reddit_search', cookie: '', args: { query: 'x', limit: 1000 } }), /bad_input/)
  const body = input({ action: 'query', tool: 'reddit_search', cookie: 'PRIVATE', args: { query: '--help; $(echo hi)', limit: 1 } })
  const args = argv(body)
  assert.deepEqual(args.slice(-2), ['--', '--help; $(echo hi)'])
  assert.equal(args.some(a => a.includes('PRIVATE')), false)
})
test('valid empty results differ from malformed/error envelopes', () => {
  assert.deepEqual(rows({ ok: true, data: [] }, 0), [])
  for (const data of [{}, null, [{ id: 'x', title: 'x', url: 'https://example.com/comments/x' }]]) {
    assert.throws(() => rows({ ok: true, data }, 0), /interface/)
  }
  assert.throws(() => rows({ ok: true, data: [] }, 1), /interface/)
})
test('upstream auth labels cannot turn bare 403 into expired credentials', () => {
  assert.equal(failure({ error: { code: 'AUTH_REQUIRED', message: 'HTTP 403 SECRET' } }), 'forbidden')
  assert.equal(failure({ error: { code: 'SECURITY_BLOCK' } }), 'forbidden')
  assert.equal(failure({ error: { code: 'RATE_LIMITED' } }), 'rate_limit')
  assert.equal(failure({ error: { code: 'AUTH_REQUIRED' } }), 'auth')
})
test('listing fields preserve the existing MCP post contract', () => {
  const result = rows({ ok: true, data: [{ id: 'abc', title: 'Title', subreddit: 'r/python', upvotes: 3, comments: 2, url: 'https://www.reddit.com/r/python/comments/abc/title/' }] }, 0)
  assert.equal(result[0].score, 3)
  assert.equal(result[0].num_comments, 2)
  assert.equal(result[0].subreddit, 'python')
  assert.equal(result[0].permalink, '/r/python/comments/abc/title/')
})
