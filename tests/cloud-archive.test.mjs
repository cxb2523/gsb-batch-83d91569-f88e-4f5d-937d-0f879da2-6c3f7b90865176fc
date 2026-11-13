import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { packSnapshot, unpackSnapshot, checkCandidate, githubArchive } from '../scripts/lib/cloud-archive.mjs';

const demo = JSON.parse(await readFile(new URL('../data/demo-seed.json', import.meta.url)));
function seed() { const s = structuredClone(demo); delete s.demo; s.provider = 'FTShare'; return s; }
function packed() { return packSnapshot(seed(), { id: '20261111T120000Z-test-1', trigger: 'schedule', collectedAt: '2026-11-11T12:00:00Z' }); }
test('cloud archive restores the exact data and metadata and rejects corrupt bytes/manifests', () => {
  const p = packed(), restored = unpackSnapshot(p.bytes, p.manifest);
  assert.deepEqual(restored.broad, seed().broad);
  assert.equal(restored.cloud_update.trigger, 'schedule');
  assert.throws(() => unpackSnapshot(Buffer.concat([p.bytes, Buffer.from('corrupt')]), p.manifest), /checksum/);
  assert.throws(() => unpackSnapshot(p.bytes, { ...p.manifest, flow_through: '1990-01-01' }), /contents/);
  assert.throws(() => packSnapshot(demo, { id: '20261111T120000Z-test-1' }), /Demo/);
});
test('cloud candidate cannot drop older history or publish an incomplete flow interval', () => {
  const a = seed(); checkCandidate(a, structuredClone(a));
  const b = seed(); b.latest_flow_date = a.broad.dates[0];
  assert.throws(() => checkCandidate(a, b), /lose historical/);
  const c = seed(), i = c.broad.dates.indexOf(c.latest_flow_date), category = c.broad.cats.find(cat => c.broad.coverage[cat].expected[i] > 0);
  c.broad.series[category][i] = null; c.broad.coverage[category].valid[i] = 0; c.broad.total[i] = null;
  assert.throws(() => checkCandidate(a, c), /lost a complete|incomplete published/);
});
test('archive upload publishes manifest last and ignores incomplete uploads when selecting latest', async () => {
  const p = packed(), uploads = [], release = { id: 7, tag_name: 'etf-test-archive-2026-11', upload_url: 'https://uploads.github.com/test{?name}', assets: [
    { id: 1, name: p.manifest.file }, { id: 2, name: p.manifest.file.replace('.json.gz', '.manifest.json') },
    { id: 3, name: 'seed-20261112T120000Z-test-1.manifest.json' }
  ] };
  const api = githubArchive({ repository: 'test/private', token: 'synthetic-test-token', fetcher: async (url, options) => {
    if (url.endsWith('/repos/test/private')) return Response.json({ private: true });
    if (url.includes('/releases/7/assets?')) return Response.json(url.endsWith('page=1') ? Array.from({ length: 100 }, (_, i) => ({ id: 100 + i, name: 'unrelated-' + i })) : release.assets);
    if (options.method === 'POST') { uploads.push(decodeURIComponent(new URL(url).searchParams.get('name'))); return Response.json({}); }
    if (url.includes('/releases/assets/1')) return new Response(p.bytes);
    if (url.includes('/releases/assets/2')) return Response.json(p.manifest);
    return Response.json(url.includes('/releases/tags/') ? release : [release]);
  } });
  await api.save(p); assert.deepEqual(uploads, [p.manifest.file, p.manifest.file.replace('.json.gz', '.manifest.json')]);
  const restored = await api.restore(); assert.equal(restored.manifest.id, p.manifest.id);
});
test('real snapshots cannot be uploaded to an accidentally public source repository', async () => {
  const api = githubArchive({ repository: 'test/public', token: 'synthetic-test-token', fetcher: async () => Response.json({ private: false }) });
  await assert.rejects(api.save(packed()), /private repository/);
});
