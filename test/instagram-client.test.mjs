// Unit tests for the JSON-RPC profile client. Every response is a local fixture
// served by an injected fake fetch: no network, no HASDATA_API_KEY required.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {
    ConcurrencyLimitError,
    DEFAULT_ENDPOINT,
    InstagramApiError,
    PROFILE_TOOL,
    ProfileNotFoundError,
    createProfileClient,
    parseRpcMessages,
} from '../lib/instagram-client.mjs';

// JSON fixtures live next to this file; readFileSync keeps the test
// synchronous at setup time.
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

// Serve a scripted list of fixtures, one per fetch call, in order.
function fakeFetch(script) {
    const queue = [...script];
    const calls = [];
    return {
        calls,
        fetch: async (url, init) => {
            calls.push({ url, init });
            const fixture = queue.shift();
            assert.ok(fixture, 'fakeFetch ran out of scripted responses');
            return {
                status: fixture.httpStatus,
                ok: fixture.httpStatus >= 200 && fixture.httpStatus < 300,
                text: async () => serialize(fixture),
            };
        },
    };
}

function clientFor(script) {
    const fake = fakeFetch(script.map(loadFixture));
    const client = createProfileClient({ apiKey: 'test-key', fetch: fake.fetch });
    return { client, calls: fake.calls };
}

test('a successful lookup unwraps the envelope and returns the profile json', async () => {
    const { client, calls } = clientFor(['success']);
    const profile = await client.getProfile('nasa');

    assert.equal(profile.username, 'nasa');
    assert.equal(profile.id, '528817151');
    assert.equal(profile.followersCount, 104345698);
    assert.equal(profile.followsCount, 91);
    assert.equal(profile.verified, true);
    assert.ok(Array.isArray(profile.latestPosts));

    // The call targets the documented profile tool with the bare handle.
    assert.equal(calls.length, 1);
    const request = JSON.parse(calls[0].init.body);
    assert.equal(calls[0].url, DEFAULT_ENDPOINT);
    assert.equal(request.method, 'tools/call');
    assert.equal(request.params.name, PROFILE_TOOL);
    assert.deepEqual(request.params.arguments, { handle: 'nasa' });
    assert.equal(calls[0].init.headers['x-api-key'], 'test-key');
});

test('an SSE stream is parsed the same way as a plain JSON body', async () => {
    const { client } = clientFor(['private']);
    const profile = await client.getProfile('private.guy');
    assert.equal(profile.private, true);
    assert.equal(profile.username, 'private.guy');
});

test('parseRpcMessages ignores keep-alive lines and picks data events', () => {
    const sse = [
        ': keep-alive',
        '',
        'event: message',
        'data: {"jsonrpc":"2.0","id":7,"result":{"ok":true}}',
        '',
    ].join('\n');
    const messages = parseRpcMessages(sse);
    assert.equal(messages.length, 1);
    assert.equal(messages[0].id, 7);
});

test('a 400 Bad Request tool error with requestMetadata.status=error is ProfileNotFoundError', async () => {
    const { client } = clientFor(['not-found']);
    await assert.rejects(client.getProfile('definitely.not.a.real.account.xyz'), (err) => {
        assert.ok(err instanceof ProfileNotFoundError);
        assert.ok(err instanceof InstagramApiError);
        assert.match(err.message, /400 Bad Request|requestMetadata/);
        assert.equal(err.retriable, false);
        return true;
    });
});

test('an HTTP 429 gateway response is a retriable ConcurrencyLimitError', async () => {
    const { client } = clientFor(['concurrency-http-429']);
    await assert.rejects(client.getProfile('nasa'), (err) => {
        assert.ok(err instanceof ConcurrencyLimitError);
        assert.equal(err.httpStatus, 429);
        assert.equal(err.retriable, true);
        assert.match(err.message, /concurrency_limit|429/);
        return true;
    });
});

test('a 429 delivered inside an MCP isError result is classified the same way', async () => {
    const { client } = clientFor(['concurrency-mcp-429']);
    await assert.rejects(client.getProfile('nasa'), (err) => {
        assert.ok(err instanceof ConcurrencyLimitError);
        assert.equal(err.retriable, true);
        return true;
    });
});

test('a 401 is a generic, non-retriable failure rather than a missing account', async () => {
    const { client } = clientFor(['unauthorized']);
    await assert.rejects(client.getProfile('nasa'), (err) => {
        assert.ok(err instanceof InstagramApiError);
        assert.ok(!(err instanceof ProfileNotFoundError));
        assert.ok(!(err instanceof ConcurrencyLimitError));
        assert.equal(err.httpStatus, 401);
        assert.equal(err.retriable, false);
        return true;
    });
});

test('a 502 is a generic call failure', async () => {
    const { client } = clientFor(['bad-gateway']);
    await assert.rejects(client.getProfile('nasa'), (err) => {
        assert.ok(err instanceof InstagramApiError);
        assert.ok(!(err instanceof ConcurrencyLimitError));
        assert.equal(err.httpStatus, 502);
        return true;
    });
});

test('a network-level rejection becomes an InstagramApiError, not a raw TypeError', async () => {
    const client = createProfileClient({
        apiKey: 'test-key',
        fetch: async () => {
            throw new TypeError('fetch failed: ENOTFOUND');
        },
    });
    await assert.rejects(client.getProfile('nasa'), (err) => {
        assert.ok(err instanceof InstagramApiError);
        assert.match(err.message, /never produced a response|ENOTFOUND/);
        return true;
    });
});

test('creating a client without a key fails before any request is made', () => {
    const saved = process.env.HASDATA_API_KEY;
    delete process.env.HASDATA_API_KEY;
    try {
        assert.throws(() => createProfileClient(), /HASDATA_API_KEY/);
    } finally {
        if (saved !== undefined) process.env.HASDATA_API_KEY = saved;
    }
});
