import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, copyFile, readFile, writeFile, readdir, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { preparePages } from '../scripts/lib/pages.mjs';

test('Pages package separates client assets, server entrypoint and private deployment data', async t => {
  const root = await mkdtemp(resolve(tmpdir(), 'ftshare-pages-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const source = fileURLToPath(new URL('../', import.meta.url));
  const files = ['src/index.html','src/style.css','src/echarts.min.js','src/assets/dashboard.js','src/assets/flow-math.js','src/assets/radar.js','src/assets/radar-math.js','src/assets/brush.js','src/assets/presentation.js','src/assets/ftai-mark.svg','LICENSE','third_party/echarts/LICENSE','third_party/echarts/NOTICE','third_party/echarts/licenses/LICENSE-d3'];
  for (const name of files) { await mkdir(resolve(root, name, '..'), { recursive: true }); await copyFile(resolve(source, name), resolve(root, name)); }
  await mkdir(resolve(root, 'dist/server'), { recursive: true });
  await writeFile(resolve(root, 'dist/metadata.json'), JSON.stringify({ mode: 'live', source_date: '2026-11-10' }));
  await writeFile(resolve(root, 'dist/server/index.js'), 'export default {fetch(){return new Response("ok")}};');
  await writeFile(resolve(root, '.env'), 'SYNTHETIC_SECRET=do-not-publish');
  const result = await preparePages(root);
  assert.equal(result.mode, 'live');
  assert((await readFile(resolve(result.directory, 'index.html'), 'utf8')).includes('data-data-mode="live"'));
  assert.deepEqual(JSON.parse(await readFile(resolve(result.directory, '_routes.json'), 'utf8')), { version: 1, include: ['/api/*'], exclude: [] });
  const names = await readdir(result.directory);
  assert(names.includes('_worker.js') && names.includes('404.html'));
  assert(!names.includes('.env') && !names.includes('data') && !names.includes('server'));
  assert.equal(await readFile(resolve(result.directory, '_worker.js'), 'utf8'), 'export default {fetch(){return new Response("ok")}};');
});
