// Batch-collection tests. The five required paths all run against local
// fixtures through an injected fake fetch (or a scripted client), so the suite
// needs no HASDATA_API_KEY and makes no network calls.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import { BATCH_STATUS, collectProfiles } from '../lib/batch-profiles.mjs';
import { createProfileClient } from '../lib/instagram-client.mjs';

function loadFixture(name) {
    return JSON.parse(fs.readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), 'utf8'));
}

function serialize(fixture) {
    if (fixture.rawBody !== undefined) return fixture.rawBody;
    const json = JSON.stringify(fixture.body);
    if (fixture.transport === 'sse') {
        return `event: message\ndata: ${json.replace(/\n/g, '\ndata: ')}\n\n`;
    }
    return json;
}

// Route scripted fixtures per handle, so concurrent workers cannot scramble a
// shared response queue. Each route is a queue of fixtures.
function routingFetch(routes) {
    const calls = [];
    const fetchImpl = async (url, init) => {
        const request = JSON.parse(init.body);
        const handle = request.params.arguments.handle;
        calls.push(handle);
        const fixture = routes[handle].shift();
        assert.ok(fixture, `no scripted response left for ${handle}`);
        return {
            status: fixture.httpStatus,
            ok: fixture.httpStatus >= 200 && fixture.httpStatus < 300,
            text: async () => serialize(fixture),
        };
    };
    return { fetchImpl, calls };
}

function batchClient(routes) {
    const fake = routingFetch(routes);
    const client = createProfileClient({ apiKey: 'test-key', fetch: fake.fetchImpl });
    return { client, calls: fake.calls };
}

// Deterministic retry timing: record the requested delays instead of sleeping.
function fakeSleep() {
    const delays = [];
    return { delays, sleep: async (ms) => delays.push(ms) };
}

const retrySettings = (overrides = {}) => ({
    maxAttempts: 5,
    initialDelayMs: 10,
    ...overrides,
});

test('success: one record in input order with exactly the retained fields', async () => {
    const { client, calls } = batchClient({ nasa: [loadFixture('success')] });
    const [record] = await collectProfiles(['nasa'], { client, ...retrySettings() });

    assert.equal(calls.length, 1);
    assert.equal(record.handle, 'nasa');
    assert.equal(record.status, BATCH_STATUS.SUCCESS);
    assert.deepEqual(Object.keys(record).sort(), ['data', 'handle', 'status']);

    const { data } = record;
    assert.deepEqual(Object.keys(data).sort(), [
        'bioLinks',
        'followersCount',
        'followsCount',
        'fullName',
        'id',
        'latestPostsCount',
        'username',
        'verified',
    ]);
    assert.equal(data.id, '528817151');
    assert.equal(data.username, 'nasa');
    assert.equal(data.followersCount, 104345698);
    assert.equal(data.followsCount, 91);
    assert.equal(data.fullName, 'NASA');
    assert.equal(data.verified, true);
    // Only the count survives; the posts themselves are not copied across.
    assert.equal(data.latestPostsCount, 3);
    assert.ok(!('latestPosts' in data));
    assert.ok(Array.isArray(data.bioLinks));
    assert.equal(data.bioLinks[0].url, 'https://www.nasa.gov');
    // Optional-only and upstream-only fields must not leak into the record.
    assert.ok(!('biography' in data));
    assert.ok(!('error' in record));
});

test('private: private:true is its own status and missing bio/posts are not failures', async () => {
    const { client } = batchClient({ 'private.guy': [loadFixture('private')] });
    const [record] = await collectProfiles(['private.guy'], { client, ...retrySettings() });

    assert.equal(record.status, BATCH_STATUS.PRIVATE);
    assert.equal(record.handle, 'private.guy');
    assert.ok(!('error' in record), 'a private account is not an error');
    assert.deepEqual(Object.keys(record).sort(), ['data', 'handle', 'status']);

    const { data } = record;
    assert.equal(data.id, '999000111');
    assert.equal(data.username, 'private.guy');
    assert.equal(data.followersCount, 42);
    assert.equal(data.followsCount, 130);
    assert.equal(data.fullName, 'Private Guy');
    // The fixture deliberately omits verified, bioLinks and latestPosts: their
    // absence must not produce keys or fail the handle.
    assert.ok(!('verified' in data));
    assert.ok(!('bioLinks' in data));
    assert.ok(!('latestPostsCount' in data));
});

test('not found: a 400 / requestMetadata.status=error response is not_found with the reason', async () => {
    const { client, calls } = batchClient({
        'ghost.account': [loadFixture('not-found')],
    });
    const [record] = await collectProfiles(['ghost.account'], { client, ...retrySettings() });

    assert.equal(calls.length, 1, 'a not-found answer is not retried');
    assert.equal(record.handle, 'ghost.account');
    assert.equal(record.status, BATCH_STATUS.NOT_FOUND);
    assert.ok(!('data' in record));
    assert.match(record.error, /400 Bad Request|requestMetadata/);
});

test('concurrency limit: backing off and retrying eventually succeeds', async () => {
    const { client, calls } = batchClient({
        'busy.recovers': [
            loadFixture('concurrency-http-429'),
            loadFixture('concurrency-mcp-429'),
            loadFixture('success'),
        ],
    });
    const sleeper = fakeSleep();
    const [record] = await collectProfiles(['busy.recovers'], {
        client,
        ...retrySettings(),
        sleep: sleeper.sleep,
    });

    assert.equal(calls.length, 3, 'two limit responses then one successful response');
    assert.deepEqual(calls, ['busy.recovers', 'busy.recovers', 'busy.recovers']);
    assert.equal(record.status, BATCH_STATUS.SUCCESS);
    assert.equal(record.data.username, 'nasa');
    assert.equal(sleeper.delays.length, 2, 'one backoff per failed attempt');
    assert.ok(sleeper.delays[1] > sleeper.delays[0], 'backoff grows between attempts');
});

test('retry budget exhausted: the handle is recorded as failed with the reason, others continue', async () => {
    const { client, calls } = batchClient({
        'busy.forever': Array(5).fill(loadFixture('concurrency-http-429')),
    });
    const sleeper = fakeSleep();
    const [record] = await collectProfiles(['busy.forever'], {
        client,
        ...retrySettings(),
        sleep: sleeper.sleep,
    });

    assert.equal(calls.length, 5, 'all five attempts were used');
    assert.equal(sleeper.delays.length, 4, 'no sleep after the final attempt');
    assert.equal(record.handle, 'busy.forever');
    assert.equal(record.status, BATCH_STATUS.ERROR);
    assert.ok(!('data' in record));
    assert.match(record.error, /concurrency_limit/);
    assert.match(record.error, /5 attempts/);
});

test('non-retriable failures use one attempt and never interrupt the other handles', async () => {
    const { client, calls } = batchClient({
        nasa: [loadFixture('success')],
        'ghost.account': [loadFixture('not-found')],
        'private.guy': [loadFixture('private')],
        'locked.out': [loadFixture('unauthorized')],
    });
    const handles = ['nasa', 'ghost.account', 'private.guy', 'locked.out'];
    const records = await collectProfiles(handles, { client, ...retrySettings() });

    // Output order mirrors input order exactly, including the failure slots.
    assert.deepEqual(records.map((r) => r.handle), handles);
    assert.deepEqual(
        records.map((r) => r.status),
        [BATCH_STATUS.SUCCESS, BATCH_STATUS.NOT_FOUND, BATCH_STATUS.PRIVATE, BATCH_STATUS.ERROR]
    );

    const [ok, missing, privateAccount, unauthorized] = records;
    assert.equal(ok.data.followersCount, 104345698);
    assert.match(missing.error, /400 Bad Request|requestMetadata/);
    assert.equal(privateAccount.data.followersCount, 42);
    assert.match(unauthorized.error, /401/);
    // Every handle was attempted exactly once; nothing retried or aborted.
    assert.deepEqual([...calls].sort(), [...handles].sort());
    assert.equal(calls.length, 4);
});

test('the free-tier concurrency ceiling is respected even with many handles', async () => {
    let inFlight = 0;
    let maxInFlight = 0;
    const seenHandles = [];
    const client = {
        getProfile: async (handle) => {
            inFlight += 1;
            maxInFlight = Math.max(maxInFlight, inFlight);
            seenHandles.push(handle);
            // Yield twice so slower workers pile up against the semaphore
            // instead of finishing inside one microtask.
            await new Promise((resolve) => setImmediate(resolve));
            await new Promise((resolve) => setImmediate(resolve));
            inFlight -= 1;
            return { id: 'id-' + handle, username: handle, followersCount: 1, followsCount: 2 };
        },
    };

    const handles = Array.from({ length: 6 }, (_, i) => `user${i}`);
    const records = await collectProfiles(handles, { client, concurrency: 2, ...retrySettings() });

    assert.ok(maxInFlight <= 2, `peak concurrency was ${maxInFlight}, ceiling is 2`);
    assert.equal(records.length, 6);
    assert.deepEqual(records.map((r) => r.handle), handles, 'result order still matches input order');
    assert.ok(records.every((r) => r.status === BATCH_STATUS.SUCCESS));
});

test('an invalid or @-prefixed entry is handled without touching the upstream', async () => {
    let upstreamCalls = 0;
    const client = {
        getProfile: async () => {
            upstreamCalls += 1;
            return { id: '1', username: 'nasa', followersCount: 1, followsCount: 1 };
        },
    };
    const records = await collectProfiles(['  @nasa  ', '   ', ''], { client, ...retrySettings() });

    assert.equal(upstreamCalls, 1, 'only the one valid handle reached the client');
    assert.equal(records[0].handle, 'nasa', 'whitespace and the leading @ are stripped');
    assert.equal(records[0].status, BATCH_STATUS.SUCCESS);
    assert.equal(records[1].status, BATCH_STATUS.ERROR);
    assert.match(records[1].error, /invalid handle/);
    assert.equal(records[2].status, BATCH_STATUS.ERROR);
});

test('an empty batch resolves to an empty array', async () => {
    const records = await collectProfiles([], { client: { getProfile: async () => null } });
    assert.deepEqual(records, []);
});
