// End-to-end check of the stdio entry point: a real child process, a local scripted HTTP
// server standing in for HasData. This is what proves src/index.js wires the bridge handlers
// the way the parsing tests assume, without any network or real key.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const ENTRY = fileURLToPath(new URL('../src/index.js', import.meta.url));

// The child process imports the MCP SDK, so this test only runs where the dependency is
// installed. The parsing tests in bridge.test.mjs cover everything else without it.
const hasSdk = (() => {
    try {
        createRequire(import.meta.url).resolve('@modelcontextprotocol/sdk/server/index.js');
        return true;
    } catch {
        return false;
    }
})();

async function startServer(script) {
    const server = http.createServer((req, res) => {
        let raw = '';
        req.on('data', (chunk) => { raw += chunk; });
        req.on('end', () => {
            const request = JSON.parse(raw);
            const next = script.shift() ?? { status: 500, body: 'script exhausted' };
            const body = typeof next.body === 'function' ? next.body(request) : next.body;
            res.writeHead(next.status ?? 200, { 'Content-Type': next.contentType ?? 'application/json' });
            res.end(body);
        });
    });
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    return {
        url: `http://127.0.0.1:${server.address().port}/mcp`,
        close: () => new Promise((resolve) => server.close(resolve)),
    };
}

function startBridge(endpoint) {
    const child = spawn(process.execPath, [ENTRY], {
        env: { ...process.env, HASDATA_ENDPOINT: endpoint, HASDATA_API_KEY: '' },
        stdio: ['pipe', 'pipe', 'pipe'],
    });
    const responses = new Map();
    let stderr = '';
    let pending = '';
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.stdout.on('data', (chunk) => {
        pending += chunk.toString();
        let newline;
        while ((newline = pending.indexOf('\n')) >= 0) {
            const line = pending.slice(0, newline).trim();
            pending = pending.slice(newline + 1);
            if (!line) continue;
            const message = JSON.parse(line);
            responses.set(message.id, message);
        }
    });

    const send = (message) => child.stdin.write(`${JSON.stringify(message)}\n`);
    const waitFor = async (id, { timeout = 5000 } = {}) => {
        const started = Date.now();
        while (!responses.has(id)) {
            if (Date.now() - started > timeout) throw new Error(`no response for id ${id}; stderr: ${stderr}`);
            await new Promise((resolve) => setTimeout(resolve, 10));
        }
        return responses.get(id);
    };

    return {
        send,
        waitFor,
        stderr: () => stderr,
        close: () => child.kill(),
    };
}

const reply = (result) => ({ body: (request) => JSON.stringify({ jsonrpc: '2.0', id: request.id, result }) });

test('the stdio bridge forwards tools/list and shows tools/call auth failures', { skip: !hasSdk && 'the MCP SDK is not installed' }, async (t) => {
    const server = await startServer([
        reply({ tools: [{ name: 'fake_tool', inputSchema: { type: 'object' } }] }),
        { status: 401, body: '{"message":"no key"}', contentType: 'application/json' },
    ]);
    t.after(() => server.close());
    const bridge = startBridge(server.url);
    t.after(() => bridge.close());

    bridge.send({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'test', version: '1' } } });
    assert.equal((await bridge.waitFor(1)).result.serverInfo.name, 'hasdata-mcp-bridge');

    bridge.send({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} });
    const list = await bridge.waitFor(2);
    assert.deepEqual(list.result.tools.map((tool) => tool.name), ['fake_tool']);

    bridge.send({ jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'fake_tool', arguments: {} } });
    const call = await bridge.waitFor(3);
    // The SDK turns a thrown handler error into a JSON-RPC error, never a bare result.
    assert.ok(call.error, `expected an error response, got ${JSON.stringify(call)}`);
    assert.match(call.error.message, /HTTP 401/);
    assert.match(call.error.message, /authentication failed.*HASDATA_API_KEY is not set/);
});
