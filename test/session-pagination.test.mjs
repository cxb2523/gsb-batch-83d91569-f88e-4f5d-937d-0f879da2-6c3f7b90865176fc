import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createSessionPager } from '../dist/src/session-pagination.js';
import { createTwitterService } from '../dist/src/twitter.js';
import { loadConfig } from '../dist/src/config.js';

const post = (id) => ({ id: String(id), publishedAt: `2026-10-${String(id).padStart(2, '0')}` });
const page = (ids, cursor) => ({
  tweets: ids.map(post),
  cursor,
  source: 'twscrape',
  fetchedAt: '2026-10-09T00:00:00Z',
  twscrapeVersion: '0.20.1',
});
const args = { query: 'polymarket', sortOrder: 'relevancy', maxResults: 2 };

test('session continuation preserves overflow, upstream order and cross-page deduplication', async () => {
  const calls = [];
  const pager = createSessionPager(async (op, p) => {
    calls.push([op, p]);
    return p.cursor ? page([3, 4, 5], null) : page([1, 2, 3], 'x-bottom');
  }, 1000);
  const a = await pager.read('searchTweets', args);
  assert.deepEqual(
    a.tweets.map((t) => t.id),
    ['1', '2'],
  );
  assert.equal(a.hasMore, true);
  assert.match(a.nextToken, /^session\./);
  assert.ok(!a.nextToken.includes('x-bottom'));
  const b = await pager.read('searchTweets', { ...args, nextToken: a.nextToken });
  assert.deepEqual(
    b.tweets.map((t) => t.id),
    ['3', '4'],
  );
  assert.equal(calls[1][1].cursor, 'x-bottom');
  assert.equal('nextToken' in calls[1][1], false);
  const c = await pager.read('searchTweets', { ...args, nextToken: b.nextToken });
  assert.deepEqual(
    c.tweets.map((t) => t.id),
    ['5'],
  );
  assert.equal(c.nextToken, null);
  assert.equal(c.hasMore, false);
  assert.equal(calls.length, 2);
  // A checkpoint is not consumed: a caller retry cannot skip its remaining items.
  const retry = await pager.read('searchTweets', {
    ...args,
    maxResults: 1,
    nextToken: a.nextToken,
  });
  assert.deepEqual(
    retry.tweets.map((t) => t.id),
    ['3'],
  );
});

test('expired, cross-query, cross-tool and foreign cursors never contact X', async () => {
  let clock = 0;
  let calls = 0;
  const pager = createSessionPager(
    async () => {
      calls++;
      return page([1, 2, 3], null);
    },
    1000,
    () => clock,
  );
  const a = await pager.read('searchTweets', args);
  for (const [op, p] of [
    ['searchTweets', { ...args, nextToken: 'api-cursor' }],
    ['searchTweets', { ...args, query: 'different', nextToken: a.nextToken }],
    ['searchTweets', { ...args, sortOrder: 'recency', nextToken: a.nextToken }],
    ['getUserTweets', { ...args, nextToken: a.nextToken }],
  ])
    await assert.rejects(pager.read(op, p), (e) => e.code === 'INVALID_CURSOR');
  clock += 15 * 60 * 1000;
  await assert.rejects(
    pager.read('searchTweets', { ...args, nextToken: a.nextToken }),
    (e) => e.code === 'INVALID_CURSOR',
  );
  assert.equal(calls, 1);
});

test('empty pages retain continuation, repeated cursors stop and loops stay bounded', async () => {
  let calls = 0;
  const pager = createSessionPager(async () => {
    calls++;
    return page([], `cursor-${calls}`);
  }, 1000);
  const a = await pager.read('searchTweets', args);
  assert.equal(calls, 8);
  assert.equal(a.partial, true);
  assert.equal(a.hasMore, true);
  const stalled = createSessionPager(async () => page([1], 'same'), 1000);
  const b = await stalled.read('searchTweets', args);
  assert.equal(b.hasMore, false);
  assert.equal(b.partial, true);
  assert.equal(b.paginationStopped, true);
});

test('failed reads leave an existing checkpoint available; oldest checkpoints are evicted', async () => {
  let fail = false;
  const pager = createSessionPager(async (_, p) => {
    if (fail) throw new Error('network unavailable');
    return page(p.cursor ? [3, 4] : [1, 2], p.cursor ? null : 'next');
  }, 1000);
  const a = await pager.read('searchTweets', args);
  fail = true;
  await assert.rejects(pager.read('searchTweets', { ...args, nextToken: a.nextToken }));
  fail = false;
  assert.deepEqual(
    (await pager.read('searchTweets', { ...args, nextToken: a.nextToken })).tweets.map((t) => t.id),
    ['3', '4'],
  );
  for (let n = 0; n < 32; n++) await pager.read('searchTweets', { ...args, query: String(n) });
  await assert.rejects(
    pager.read('searchTweets', { ...args, nextToken: a.nextToken }),
    (e) => e.code === 'INVALID_CURSOR',
  );
  pager.clear();
});

test('a continuation normal page preserves pagination state and reports expiry', async () => {
  const pager = createSessionPager(
    async (_, p) => page(p.cursor ? [3, 4] : [1, 2], p.cursor ? null : 'next'),
    1000,
    () => 0,
  );
  const a = await pager.read('searchTweets', args);
  assert.equal(a.partial, false);
  assert.equal(a.paginationStopped, undefined);
  assert.equal(a.cursorExpiresAt, new Date(15 * 60 * 1000).toISOString());
  const b = await pager.read('searchTweets', { ...args, nextToken: a.nextToken });
  assert.deepEqual(
    b.tweets.map((t) => t.id),
    ['3', '4'],
  );
  assert.equal(b.nextToken, null);
  assert.equal(b.hasMore, false);
  assert.equal(b.cursorExpiresAt, null);
  assert.equal(b.coverage, 'bounded');
  // The first page keeps its original expiry even if a later call reads more pages.
  assert.equal(a.cursorExpiresAt, new Date(15 * 60 * 1000).toISOString());
});

test('reordered filters and an unchanged page size still share one checkpoint', async () => {
  // Page size is not a query condition: changing maxResults keeps the cursor valid.
  const pager = createSessionPager(
    async (_, p) => page(p.cursor ? [3, 4, 5] : [1, 2], p.cursor ? null : 'next'),
    1000,
  );
  const inputs = {
    query: 'q',
    sortOrder: 'recency',
    maxResults: 2,
    filters: { language: 'zh', excludeReplies: true, minLikes: 5 },
  };
  const a = await pager.read('searchTweets', inputs);
  const b = await pager.read('searchTweets', {
    ...inputs,
    maxResults: 3,
    filters: { minLikes: 5, excludeReplies: true, language: 'zh' },
    nextToken: a.nextToken,
  });
  assert.deepEqual(
    b.tweets.map((t) => t.id),
    ['3', '4', '5'],
  );
  // Same operation but genuinely different filter values must be rejected.
  for (const filters of [
    { ...inputs.filters, language: 'en' },
    { language: 'zh', excludeReplies: true },
    { ...inputs.filters, excludeRetweets: false },
  ])
    await assert.rejects(
      pager.read('searchTweets', { ...inputs, filters, nextToken: a.nextToken }),
      (e) => e.code === 'INVALID_CURSOR',
    );
  // Reordering alone changes nothing, so the original token still resumes.
  assert.deepEqual(
    (await pager.read('searchTweets', { ...inputs, nextToken: a.nextToken })).tweets.map(
      (t) => t.id,
    ),
    ['3', '4'],
  );
});

test('repeated upstream cursors stop pagination while buffered items still drain', async () => {
  let calls = 0;
  const pager = createSessionPager(async () => {
    calls++;
    // Page 1 opens cursor "b"; page 2 repeats "b", a loop that must terminate.
    return page(calls === 1 ? [1, 2, 3] : [4, 5], 'b');
  }, 1000);
  const a = await pager.read('searchTweets', { ...args, maxResults: 2 });
  assert.equal(a.partial, false);
  const b = await pager.read('searchTweets', { ...args, maxResults: 2, nextToken: a.nextToken });
  assert.equal(b.paginationStopped, true);
  assert.equal(b.partial, true);
  assert.equal(calls, 2);
  // Overflow from the last accepted page is still returned, so the caller can drain it.
  const c = await pager.read('searchTweets', { ...args, maxResults: 2, nextToken: b.nextToken });
  assert.deepEqual(
    c.tweets.map((t) => t.id),
    ['5'],
  );
  assert.equal(c.paginationStopped, true);
  assert.equal(c.hasMore, false);
  assert.equal(c.nextToken, null);
  assert.equal(calls, 2);
});

test('the browsing sequence stops at its unique-post cap and never loops forever', async () => {
  let issued = 0;
  const pager = createSessionPager(async () => {
    const ids = [];
    for (let i = 0; i < 100; i++) ids.push(++issued);
    return page(ids, `cursor-${issued}`);
  }, 1000);
  let count = 0;
  let current = await pager.read('searchTweets', { ...args, maxResults: 100 });
  count++;
  while (current.nextToken && count < 100) {
    current = await pager.read('searchTweets', {
      ...args,
      maxResults: 100,
      nextToken: current.nextToken,
    });
    count++;
  }
  assert.ok(count < 100);
  assert.equal(current.paginationStopped, true);
  assert.equal(current.partial, true);
  assert.equal(current.hasMore, false);
  assert.equal(current.nextToken, null);
});

test('a failed continuation keeps the checkpoint: retry neither loses nor duplicates items', async () => {
  let failCursor = null;
  const pager = createSessionPager(async (_, p) => {
    if (failCursor && p.cursor === failCursor) throw new Error('upstream timeout');
    return page(p.cursor ? [3, 4] : [1, 2], p.cursor ? null : 'next');
  }, 1000);
  const a = await pager.read('searchTweets', args);
  failCursor = 'next';
  // Timeout/upstream error surfaces unchanged and emits no partial snapshot.
  for (let attempt = 0; attempt < 2; attempt++)
    await assert.rejects(
      pager.read('searchTweets', { ...args, nextToken: a.nextToken }),
      (e) => e.message === 'upstream timeout',
    );
  failCursor = null;
  const retried = await pager.read('searchTweets', { ...args, nextToken: a.nextToken });
  assert.deepEqual(
    retried.tweets.map((t) => t.id),
    ['3', '4'],
  );
  assert.equal(retried.nextToken, null);
});

test('a malformed continuation page is an error, not a consumed checkpoint', async () => {
  let corrupt = false;
  const pager = createSessionPager(async (_, p) => {
    if (corrupt) return { tweets: [{ id: 'not-an-id' }], cursor: 'x' };
    return page(p.cursor ? [3, 4] : [1, 2], p.cursor ? null : 'next');
  }, 1000);
  const a = await pager.read('searchTweets', args);
  corrupt = true;
  await assert.rejects(
    pager.read('searchTweets', { ...args, nextToken: a.nextToken }),
    (e) => e.code === 'UPSTREAM_FORMAT',
  );
  corrupt = false;
  const retried = await pager.read('searchTweets', { ...args, nextToken: a.nextToken });
  assert.deepEqual(
    retried.tweets.map((t) => t.id),
    ['3', '4'],
  );
});

test('a request or time budget stops a call early and keeps already-fetched items and token', async () => {
  // Every page is empty but advances its cursor, so the call is request-bound.
  let calls = 0;
  const requestBound = createSessionPager(async () => {
    calls++;
    return page([], `cursor-${calls}`);
  }, 1000);
  const a = await requestBound.read('searchTweets', { ...args, maxResults: 5 });
  assert.equal(calls, 8);
  assert.deepEqual(a.tweets, []);
  assert.equal(a.partial, true);
  assert.equal(a.paginationStopped, undefined);
  assert.equal(a.hasMore, true);
  assert.ok(a.nextToken);

  // A call whose upstream page consumes its time budget returns what it already has.
  let clock = 0;
  let slowCalls = 0;
  const timed = createSessionPager(
    async () => {
      slowCalls++;
      // The second upstream page overruns the call's deadline only once.
      if (slowCalls === 2) clock += 2000;
      return page([slowCalls], `cursor-${slowCalls}`);
    },
    1000,
    () => clock,
  );
  const first = await timed.read('searchTweets', { ...args, maxResults: 5 });
  // Both pages that completed are returned; the overrun only stops further requests.
  assert.deepEqual(
    first.tweets.map((t) => t.id),
    ['1', '2'],
  );
  assert.equal(first.partial, true);
  assert.equal(first.paginationStopped, undefined);
  assert.ok(first.nextToken);
  // The next call has a fresh deadline and resumes from the stored checkpoint.
  // The previous call's budget stop does not permanently mark the sequence partial.
  const resumed = await timed.read('searchTweets', {
    ...args,
    maxResults: 2,
    nextToken: first.nextToken,
  });
  assert.deepEqual(
    resumed.tweets.map((t) => t.id),
    ['3', '4'],
  );
  assert.equal(resumed.partial, false);
  assert.equal(slowCalls, 4);
});

test('timeline continuation carries the first-page profile and sorts each page descending', async () => {
  const user = { id: '7', username: 'test' };
  const calls = [];
  const pager = createSessionPager(async (_, p) => {
    calls.push(p);
    // Only the first upstream page resolves the profile; later pages omit it.
    const payload = p.cursor ? { ...page([3, 1], null) } : { ...page([2, 5, 4], 'next'), user };
    return payload;
  }, 1000);
  const p = { username: 'test', excludeReplies: true, excludeRetweets: true, maxResults: 3 };
  const a = await pager.read('getUserTweets', p);
  assert.deepEqual(
    a.tweets.map((t) => t.id),
    ['5', '4', '2'],
  );
  assert.deepEqual(a.user, user);
  const b = await pager.read('getUserTweets', { ...p, nextToken: a.nextToken });
  assert.deepEqual(
    b.tweets.map((t) => t.id),
    ['3', '1'],
  );
  // The profile from the first page is replayed even though page two omitted it.
  assert.deepEqual(b.user, user);
  assert.deepEqual(calls[1].user, user);
  // Paging order follows upstream timeline entries, not a global re-sort.
  assert.deepEqual(
    calls.map((c) => c.cursor ?? null),
    [null, 'next'],
  );
});

test('advanced filters compile to session operators and reject invalid or API-only usage', async () => {
  const calls = [];
  const service = createTwitterService(loadConfig({}), {
    fetch: async () => assert.fail('no network'),
    createScrape: () => ({
      read: async (op, p) => {
        calls.push(p);
        return {};
      },
      close: async () => {},
    }),
  });
  await service.searchTweets({
    query: 'polymarket',
    filters: {
      language: 'zh',
      fromUsername: '@Polymarket',
      excludeReplies: true,
      excludeRetweets: true,
      hasMedia: true,
      minLikes: 100,
      minReplies: 2,
      minRetweets: 3,
      sinceDate: '2026-10-01',
      untilDate: '2026-10-10',
    },
  });
  assert.equal(
    calls[0].query,
    'polymarket lang:zh from:Polymarket -filter:replies -filter:retweets filter:media min_faves:100 min_replies:2 min_retweets:3 since:2026-10-01 until:2026-10-10',
  );
  for (const filters of [
    { language: 'zh OR anything' },
    { sinceDate: '2026-02-30' },
    { sinceDate: '2026-10-10', untilDate: '2026-10-01' },
    { minLikes: -1 },
    { fromUsername: 'a b' },
    { unknown: true },
  ])
    await assert.rejects(
      service.searchTweets({ query: 'x', filters }),
      (e) => e.code === 'INVALID_INPUT',
    );
  assert.equal(calls.length, 1);
  const api = createTwitterService(loadConfig({ TWITTER_DISCOVERY_BACKEND: 'api' }), {
    fetch: async () => assert.fail('no network'),
    createApi: () => assert.fail('no API call'),
  });
  await assert.rejects(
    api.searchTweets({ query: 'x', filters: { language: 'zh' } }),
    (e) => e.code === 'INVALID_INPUT',
  );
  await assert.rejects(
    api.searchTweets({ query: 'x', nextToken: 'session.foreign' }),
    (e) => e.code === 'INVALID_CURSOR',
  );
  await assert.rejects(
    api.getUserTweets({ username: 'test', nextToken: 'session.foreign' }),
    (e) => e.code === 'INVALID_CURSOR',
  );
  await api.close();
  await service.close();
});
