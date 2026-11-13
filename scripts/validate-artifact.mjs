import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const path = process.env.BUILD_OUTPUT_DIR ? pathToFileURL(resolve(process.env.BUILD_OUTPUT_DIR, 'server/index.js')) : new URL('../dist/server/index.js', import.meta.url), code = await readFile(path, 'utf8');
assert(!/ftshare_sk_[A-Za-z0-9_-]{20,}/.test(code), 'Credentials in artifact');
assert(!code.includes('appgprj_'), 'Hosted project identity in artifact');
assert(!code.includes('/Users/'), 'Machine-specific path in artifact');
const module = await import(path.href + '?check=' + Date.now());
assert.deepEqual(Object.keys(module), ['default'], 'Worker entrypoint must not expose constant exports as RPC handlers');
const worker = module.default;
assert.equal(typeof worker?.fetch, 'function');
const health = await (await worker.fetch(new Request('http://localhost/api/health'))).json();
assert(['demo', 'live'].includes(health.mode));
assert.equal((await worker.fetch(new Request('http://localhost/'))).status, 200);
if (health.mode === 'demo') {
  const response = await worker.fetch(new Request('http://localhost/api/live'));
  assert.equal(response.status, 200); assert.equal((await response.json()).provider, 'Demo');
}
console.log('Valid Worker and Node artifact; mode=' + health.mode + '; no hosted project or machine paths.');
