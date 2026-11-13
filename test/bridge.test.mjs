// These tests run the bridge against a local HTTP server, so they need no network and no
// real API key. The server hands out scripted responses in order, which is how the bridge
// sees plain JSON, event streams, HTTP failures and malformed bodies.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { parseRpcResponse, rpcResult, forwardToHasData, createBridge, HasDataError } from '../src/bridge.js';

async function startServer(script) {
    const requests = [];
    const server = http.createServer((req, res) => {
        let raw = '';
        req.on('data', (chunk) => { raw += chunk; });
        req.on('end', () => {
            requests.push({ headers: req.headers, body: raw ? JSON.parse(raw) : null });
            const next = script.shift();
            if (!next) {
                res.writeHead(500, { 'Content-Type': 'text/plain' });
                res.end('script exhausted');
                return;
            }
            res.writeHead(next.status ?? 200, { 'Content-Type': next.contentType ?? 'application/json' });
            res.end(next.body);
        });
    });
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    const { port } = server.address();
    return {
        url: `http://127.0.0.1:${port}/mcp`,
        requests,
        close: () => new Promise((resolve) => server.close(resolve)),
    };
}

const json = (message) => ({ body: JSON.stringify(message) });
const sse = (body) => ({ body, contentType: 'text/event-stream' });

const capturedLogs = () => {
    const logs = [];
    const log = (...args) => logs.push(args.join(' '));
    return { log, logs };
};

// node:assert's throws/rejects do not hand back the error, and several tests need to
// inspect the message or status of the failure.
function caught(fn) {
    try {
        fn();
    } catch (error) {
        return error;
    }
    throw new Error('expected the call to throw');
}

async function rejected(fn) {
    try {
        await fn();
    } catch (error) {
        return error;
    }
    throw new Error('expected the call to reject');
}

// A request whose id is known to the caller so the scripted responses can carry other ids
// around the answer and still be checked precisely.
const request = (method, params = {}, id = 42) => ({ jsonrpc: '2.0', id, method, params });

test('plain JSON bodies are parsed directly, even when a string field contains "data:"', () => {
    const raw = JSON.stringify({ jsonrpc: '2.0', id: 7, result: { note: 'data: not an event', tools: [] } });
    const message = parseRpcResponse(raw, 7);
    assert.equal(message.id, 7);
    assert.deepEqual(rpcResult(message), { note: 'data: not an event', tools: [] });
});

test('leading whitespace before a JSON body does not turn it into an event stream', () => {
    const raw = `\n  ${JSON.stringify({ jsonrpc: '2.0', id: 1, result: { tools: [{ name: 'a' }] } })}`;
    assert.deepEqual(rpcResult(parseRpcResponse(raw, 1)), { tools: [{ name: 'a' }] });
});

test('an event stream joins multi-line data and picks the message with the request id', () => {
    const raw = [
        'event: message',
        'data: {"jsonrpc":"2.0",',
        'data: "method":"notifications/progress","params":{"progress":50}}',
        '',
        'event: message',
        'data: {"jsonrpc":"2.0",',
        'data: "id":42,',
        'data: "result":{"tools":[{"name":"amazon_product"}]}}',
        '',
        ': keep-alive',
        '',
        'data: not json at all',
        '',
        'data: [DONE]',
        '',
        '',
    ].join('\n');

    const message = parseRpcResponse(raw, 42);
    assert.equal(message.id, 42);
    assert.deepEqual(rpcResult(message), { tools: [{ name: 'amazon_product' }] });
});

test('an event stream without our id fails readably instead of returning the first event', () => {
    const raw = 'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\n\n'
        + 'data: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n';

    const error = caught(() => parseRpcResponse(raw, 42));
    assert.match(error.message, /no JSON-RPC message with id 42/);
    assert.match(error.message, /ids seen: none, 1/);
});

test('an event stream with no parseable message fails readably', () => {
    const raw = ': ping\n\ndata: not-json\n\ndata: [DONE]\n\n';
    const error = caught(() => parseRpcResponse(raw, 42));
    assert.match(error.message, /no parseable JSON-RPC message/);
});

test('CRLF event streams and data: without a space are both understood', () => {
    const raw = [
        'data:{"jsonrpc":"2.0","method":"notifications/progress","params":{"progress":1}}',
        '',
        'data:{"jsonrpc":"2.0",',
        'data:"id":42,',
        'data:"result":{"ok":true}}',
        '',
        'data: [DONE]',
        '',
        '',
    ].join('\r\n');

    const message = parseRpcResponse(raw, 42);
    assert.deepEqual(rpcResult(message), { ok: true });
});

test('malformed JSON fails readably', () => {
    const error = caught(() => parseRpcResponse('{"jsonrpc":"2.0",', 42));
    assert.match(error.message, /invalid JSON/);
});

test('a JSON-RPC error object or a missing result is a failure, not a success', () => {
    assert.match(caught(() => rpcResult({ jsonrpc: '2.0', id: 1, error: { code: -32601, message: 'Method not found' } })).message, /JSON-RPC error \(code -32601\): Method not found/);
    assert.match(caught(() => rpcResult({ jsonrpc: '2.0', id: 1 })).message, /without a result/);
});

test('tools/list and tools/call follow the four scripted response classes in order', async (t) => {
    const server = await startServer([
        // 1. Plain JSON.
        json({ jsonrpc: '2.0', id: 100, result: { tools: [{ name: 'google_serp_search' }] } }),
        // 2. Event stream: a progress notification first, the answer with our id after it.
        sse([
            'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{"progress":10}}',
            '',
            'data: {"jsonrpc":"2.0",',
            'data: "id":101,',
            'data: "result":{"content":[{"type":"text","text":"scraped"}]}}',
            '',
            'data: [DONE]',
            '',
        ].join('\n')),
        // 3. HTTP failure, once for each of tools/list and tools/call.
        { status: 503, body: 'upstream unavailable', contentType: 'text/plain' },
        { status: 503, body: 'upstream unavailable', contentType: 'text/plain' },
        // 4. Broken JSON, once for each.
        { body: '{"jsonrpc":"2.0","id":103,' },
        { body: '{"jsonrpc":"2.0","id":103,' },
    ]);
    t.after(() => server.close());

    const { log, logs } = capturedLogs();
    const bridge = createBridge({ endpoint: server.url, apiKey: 'test-key', log });

    // 1. Plain JSON.
    const tools = await bridge.listTools(request('tools/list', {}, 100));
    assert.deepEqual(tools, { tools: [{ name: 'google_serp_search' }] });

    // 2. Event stream with the target id second.
    const called = await bridge.callTool(request('tools/call', { name: 'google_serp_search', arguments: {} }, 101));
    assert.deepEqual(called, { content: [{ type: 'text', text: 'scraped' }] });

    // 3. Non-2xx: list degrades, call throws with the status code.
    const empty = await bridge.listTools(request('tools/list', {}, 102));
    assert.deepEqual(empty, { tools: [] });
    const httpError = await rejected(() => bridge.callTool(request('tools/call', { name: 'x' }, 102)));
    assert.ok(httpError instanceof HasDataError);
    assert.equal(httpError.status, 503);
    assert.match(httpError.message, /HTTP 503/);
    assert.match(httpError.message, /upstream unavailable/);

    // 4. Bad JSON: list degrades, call throws.
    assert.deepEqual(await bridge.listTools(request('tools/list', {}, 103)), { tools: [] });
    assert.match((await rejected(() => bridge.callTool(request('tools/call', { name: 'x' }, 103)))).message, /invalid JSON/);

    assert.ok(logs.some((line) => /Failed to fetch tools: HasData responded with HTTP 503/.test(line)));
    assert.ok(logs.some((line) => /Failed to fetch tools: .*invalid JSON/.test(line)));
});

test('a non-2xx status and the request id surface in the thrown error', async (t) => {
    const server = await startServer([{ status: 500, body: '{"error":"boom"}' }]);
    t.after(() => server.close());

    const error = await rejected(() => forwardToHasData(request('tools/call', {}, 8), { endpoint: server.url, apiKey: 'k' }));
    assert.ok(error instanceof HasDataError);
    assert.equal(error.status, 500);
    assert.match(error.message, /HTTP 500/);
});

test('a response with the wrong id throws rather than returning another request result', async (t) => {
    const wrongId = json({ jsonrpc: '2.0', id: 999, result: { tools: [{ name: 'other' }] } });
    const server = await startServer([wrongId, wrongId]);
    t.after(() => server.close());

    const { log, logs } = capturedLogs();
    const bridge = createBridge({ endpoint: server.url, apiKey: 'k', log });
    assert.deepEqual(await bridge.listTools(request('tools/list', {}, 7)), { tools: [] });
    assert.match((await rejected(() => bridge.callTool(request('tools/call', { name: 'x' }, 7)))).message, /no JSON-RPC message with id 7/);
    assert.ok(logs.some((line) => /Failed to fetch tools: .*id 7/.test(line)));
});

test('a JSON-RPC error result is not passed back as a success', async (t) => {
    const errorResult = json({ jsonrpc: '2.0', id: 5, error: { code: -32601, message: 'Method not found' } });
    const noResult = json({ jsonrpc: '2.0', id: 5 });
    const server = await startServer([errorResult, errorResult, noResult, noResult]);
    t.after(() => server.close());

    const bridge = createBridge({ endpoint: server.url, apiKey: 'k', log: () => {} });
    assert.deepEqual(await bridge.listTools(request('tools/list', {}, 5)), { tools: [] });
    assert.match((await rejected(() => bridge.callTool(request('tools/call', { name: 'x' }, 5)))).message, /JSON-RPC error \(code -32601\)/);
    assert.match((await rejected(() => bridge.callTool(request('tools/call', { name: 'x' }, 5)))).message, /without a result/);
});

test('requests carry the key when set and omit the header when HASDATA_API_KEY is missing', async (t) => {
    const server = await startServer([
        json({ jsonrpc: '2.0', id: 1, result: { tools: [] } }),
        { status: 401, body: 'Unauthorized' },
        { status: 401, body: 'Unauthorized' },
    ]);
    t.after(() => server.close());

    await forwardToHasData(request('tools/list', {}, 1), { endpoint: server.url, apiKey: 'secret-key' });
    assert.equal(server.requests[0].headers['x-api-key'], 'secret-key');

    // No key: the request is still forwarded, just without credentials.
    const noKey = await rejected(() => forwardToHasData(request('tools/list', {}, 2), { endpoint: server.url, apiKey: '' }));
    assert.equal(server.requests[1].body.id, 2, 'the request should still be forwarded without a key');
    assert.equal(server.requests[1].headers['x-api-key'], undefined, 'no key header should be sent');
    assert.equal(noKey.status, 401);
    assert.match(noKey.message, /authentication failed.*HASDATA_API_KEY is not set/);

    // A rejected key is distinguishable from a missing one.
    const badKey = await rejected(() => forwardToHasData(request('tools/list', {}, 3), { endpoint: server.url, apiKey: 'wrong-key' }));
    assert.equal(badKey.status, 401);
    assert.match(badKey.message, /authentication failed.*rejected HASDATA_API_KEY/);
});
