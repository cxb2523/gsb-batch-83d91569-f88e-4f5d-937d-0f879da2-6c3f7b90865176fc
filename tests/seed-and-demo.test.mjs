import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createGateway } from '../src/gateway.js';
import { validateSeed } from '../scripts/lib/seed.mjs';

const seed = JSON.parse(await readFile(new URL('../data/demo-seed.json', import.meta.url), 'utf8'));
const request = path => new Request('http://localhost' + path);
test('demo is internally consistent and cannot be imported as live market data', () => {
  validateSeed(seed, 'demo'); assert.throws(() => validateSeed(seed, 'live'));
  const bad = structuredClone(seed); bad.broad.total[0] += 1;
  assert.throws(() => validateSeed(bad, 'demo'), /reconcile/);
});
test('all demo APIs work without a key or any upstream network', async () => {
  const oldFetch = globalThis.fetch; globalThis.fetch = () => { throw new Error('Offline test must not fetch'); };
  try {
    const gateway = createGateway({ seed, assets: { '/index.html': { body: '<html>demo</html>', type: 'text/html' } } });
    for (const route of ['/api/board', '/api/live', '/api/history', '/api/daily?batch=0', '/api/cumulative?date=' + seed.demo.as_of]) {
      const result = await gateway.fetch(request(route)); assert.equal(result.status, 200, route); assert.equal((await result.json()).provider, 'Demo');
    }
    assert.equal((await gateway.fetch(request('/api/daily?batch=99'))).status, 400);
    assert.equal((await gateway.fetch(request('/api/cumulative?date=bad'))).status, 400);
    const health = await (await gateway.fetch(request('/api/health'), { FTSHARE_API_KEY: 'test-only-secret' })).json();
    assert.equal(health.mode, 'demo'); assert.equal(health.configured, false); assert(!JSON.stringify(health).includes('test-only-secret'));
    const live = await (await gateway.fetch(request('/api/live'))).json();
    assert(Math.abs(live.table.reduce((s, f) => s + f.amount, 0) - live.amount) < 1e-8);
  } finally { globalThis.fetch = oldFetch; }
});
test('a live service failure keeps the snapshot accessible and hides private upstream errors', async () => {
  const liveSeed = { ...seed, demo: undefined, provider: 'FTShare' };
  const data = { seed: () => liveSeed, live: async () => { throw new Error('test-only-secret'); } };
  const gateway = createGateway({ seed: liveSeed, service: data });
  assert.equal((await gateway.fetch(request('/api/board'))).status, 200);
  const result = await gateway.fetch(request('/api/live')); assert.equal(result.status, 503); assert(!(await result.text()).includes('test-only-secret'));
});
