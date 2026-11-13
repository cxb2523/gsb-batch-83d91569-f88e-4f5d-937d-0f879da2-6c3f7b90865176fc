import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { clientAddress, createRequestGuard, positiveOption } from './lib/request-guard.mjs';
import { createUpstreamGuard } from './lib/upstream-guard.mjs';
const root = fileURLToPath(new URL('../', import.meta.url));
// LaunchAgents explicitly select the active managed release; ordinary npm start
// always serves dist so a previous Mac installation cannot override demo builds.
const output = process.env.FTSHARE_BUILD_DIR || 'dist';
globalThis.fetch = createUpstreamGuard(globalThis.fetch, {
  perMinute: positiveOption(process.env, 'UPSTREAM_REQUESTS_PER_MINUTE', 1200),
  concurrent: positiveOption(process.env, 'UPSTREAM_CONCURRENCY', 32)
});
const worker = (await import(pathToFileURL(resolve(root, output, 'server/index.js')).href)).default;

const cache = process.env.FTSHARE_LIVE_CACHE_FILE ? { async get(key, type) {
  const entries = JSON.parse(await readFile(resolve(root, process.env.FTSHARE_LIVE_CACHE_FILE), 'utf8')).entries;
  const value = entries[key]; return value === undefined ? null : type === 'json' ? JSON.parse(value) : value;
} } : undefined;
const host = process.env.HOST || '127.0.0.1', port = Number(process.env.PORT || 8080);
const guard = createRequestGuard({ perMinute: positiveOption(process.env, 'API_REQUESTS_PER_MINUTE', 180), concurrent: positiveOption(process.env, 'API_CONCURRENCY', 32) });
const server = createServer(async (incoming, outgoing) => {
  outgoing.setHeader('x-content-type-options', 'nosniff');
  outgoing.setHeader('referrer-policy', 'same-origin');
  outgoing.setHeader('permissions-policy', 'camera=(), microphone=(), geolocation=()');
  let leave;
  try {
    const method = incoming.method || 'GET';
    if (!['GET', 'HEAD'].includes(method)) { outgoing.writeHead(405, { allow: 'GET, HEAD' }); outgoing.end('Method not allowed'); incoming.resume(); return; }
    if ((incoming.url || '').length > 2048) { outgoing.writeHead(414); outgoing.end('URI too long'); return; }
    // Static history remains readable if expensive API requests reach their budget.
    if ((incoming.url || '').startsWith('/api/') && !(incoming.url || '').startsWith('/api/health')) {
      leave = guard.enter(clientAddress(incoming, process.env.TRUST_LOOPBACK_PROXY === '1'));
      if (!leave) {
        outgoing.writeHead(429, { 'content-type': 'application/json; charset=utf-8', 'retry-after': '60', 'cache-control': 'no-store' });
        outgoing.end(JSON.stringify({ error: '请求较多，请稍后重试', code: 'rate_limited' })); return;
      }
    }
    const request = new Request('http://localhost' + (incoming.url || '/'), { method, headers: incoming.headers });
    const result = await worker.fetch(request, { FTSHARE_CACHE: cache });
    outgoing.writeHead(result.status, Object.fromEntries(result.headers));
    outgoing.end(method === 'HEAD' ? undefined : Buffer.from(await result.arrayBuffer()));
  } catch {
    outgoing.writeHead(500, { 'content-type': 'text/plain; charset=utf-8' }); outgoing.end('Dashboard request failed');
  } finally { leave?.(); }
});
server.requestTimeout = 35000; server.headersTimeout = 10000;
server.maxConnections = 128; server.maxRequestsPerSocket = 200; server.keepAliveTimeout = 5000;
server.listen(port, host, () => console.log('Dashboard: http://' + host + ':' + server.address().port));
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => { server.close(() => process.exit(0)); setTimeout(() => process.exit(1), 5000).unref(); });
