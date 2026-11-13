import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, cp, mkdir, readFile, writeFile, readlink, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { refreshDeployment } from '../scripts/lib/deployment.mjs';
import { recentCollection } from '../scripts/lib/recent-collection.mjs';
import { macJobs, plist } from '../scripts/lib/macos.mjs';

const source = fileURLToPath(new URL('../', import.meta.url));
async function fixture(t) {
  const root = await mkdtemp(resolve(tmpdir(), 'ftshare-deploy-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  for (const path of ['src', 'scripts', 'data/demo-seed.json', 'package.json', 'LICENSE', 'third_party']) {
    await mkdir(resolve(root, path, '..'), { recursive: true });
    await cp(resolve(source, path), resolve(root, path), { recursive: true });
  }
  const env = { ...process.env, DATA_MODE: 'live', FTSHARE_API_KEY: '', FTSHARE_API_KEY_FILE: '' };
  const seed = JSON.parse(await readFile(resolve(root, 'data/demo-seed.json'), 'utf8'));
  // Synthetic fixture passes the live schema; it is used only inside an ephemeral test directory.
  delete seed.demo; seed.provider = 'FTShare'; seed.sources = ['Synthetic test fixture'];
  await mkdir(resolve(root, 'data/private'), { recursive: true });
  await writeFile(resolve(root, 'data/private/seed.json'), JSON.stringify(seed));
  return { root, env, seed };
}

test('macOS LaunchAgents default to loopback with explicit LAN opt-in and contain no key material', () => {
  const root = resolve(tmpdir(), 'deployment with spaces & unicode 看板');
  const jobs = macJobs({ root, node: '/opt/homebrew/bin/node', port: 8080 });
  assert.equal(jobs.length, 2);
  assert.equal(jobs[0].ProgramArguments[0], '/opt/homebrew/bin/node');
  assert.equal(jobs[0].EnvironmentVariables.HOST, '127.0.0.1');
  assert.equal(macJobs({ root, node: process.execPath, lan: true })[0].EnvironmentVariables.HOST, '0.0.0.0');
  assert.equal(jobs[0].KeepAlive, true);
  assert.equal(jobs[1].StartInterval, 21600);
  assert(!('RunAtLoad' in jobs[1]), 'Installation must not trigger an unsolicited full upstream collection');
  assert(plist(jobs[0]).includes('&amp;'));
  assert(!JSON.stringify(jobs).includes('FTSHARE_API_KEY'));
  assert.equal(macJobs({ root, node: process.execPath, demo: true }).length, 1);
  assert.throws(() => macJobs({ root, node: process.execPath, port: 0 }));
});

test('recent collection overlaps the older source date for corrections and delayed shares', () => {
  const original = { flow_start: '2022-01-01', market_start: '2023-10-09', minute_days: 20 };
  const result = recentCollection(original, { latest_flow_date: '2026-11-05', latest_market_date: '2026-11-09' }, '2026-11-11');
  assert.equal(result.flow_start, '2026-10-22');
  assert.equal(result.market_start, '2026-10-22');
  assert.equal(original.flow_start, '2022-01-01');
  assert.throws(() => recentCollection(original, null, '2026-11-11'));
});

test('upstream collection failure leaves both the running build and historical snapshot unchanged', { timeout: 20000 }, async t => {
  const { root, env } = await fixture(t);
  await refreshDeployment({ root, env, collect: false });
  const prior = await readlink(resolve(root, '.local/current'));
  const data = await readFile(resolve(root, 'data/private/seed.json'), 'utf8');
  await assert.rejects(refreshDeployment({ root, env, run: async script => {
    assert.equal(script, 'scripts/collect.mjs'); throw new Error('Simulated upstream outage');
  } }), /Simulated upstream outage/);
  assert.equal(await readlink(resolve(root, '.local/current')), prior);
  assert.equal(await readFile(resolve(root, 'data/private/seed.json'), 'utf8'), data);
  const artifact = resolve(root, '.local/current/server/index.js');
  const worker = (await import('file://' + artifact)).default;
  assert.equal((await worker.fetch(new Request('http://localhost/'))).status, 200);
  assert.equal((await worker.fetch(new Request('http://localhost/assets/ftai-mark.svg'))).status, 200);
});

test('failed health check rolls back the active release and snapshot, and restarts the old service', { timeout: 20000 }, async t => {
  const { root, env, seed } = await fixture(t);
  await refreshDeployment({ root, env, collect: false });
  const prior = await readlink(resolve(root, '.local/current'));
  const data = await readFile(resolve(root, 'data/private/seed.json'), 'utf8');
  await mkdir(resolve(root, '.local/macos'), { recursive: true });
  await writeFile(resolve(root, '.local/macos/installation.json'), JSON.stringify({ domain: 'gui/1234', label: 'test', port: 8080 }));
  let restarts = 0, probes = 0;
  const run = async (script, args, childEnv) => {
    if (script === 'scripts/collect.mjs') {
      await writeFile(childEnv.FTSHARE_SEED_FILE, JSON.stringify({ ...seed, built_at: '2026-11-11T10:00:00.000Z' }));
    } else execFileSync(process.execPath, [script, ...args], { cwd: root, env: childEnv, stdio: 'pipe' });
  };
  await assert.rejects(refreshDeployment({ root, env, run,
    restart: async () => { restarts++; }, probe: async () => { if (++probes === 1) throw new Error('Simulated bad start'); }
  }), /Simulated bad start/);
  assert.equal(restarts, 2); assert.equal(probes, 2);
  assert.equal(await readlink(resolve(root, '.local/current')), prior);
  assert.equal(await readFile(resolve(root, 'data/private/seed.json'), 'utf8'), data);
});

test('a successful refresh publishes validated data and updates persistent source only after building', { timeout: 20000 }, async t => {
  const { root, env, seed } = await fixture(t);
  await refreshDeployment({ root, env, collect: false });
  const prior = await readlink(resolve(root, '.local/current'));
  const builtAt = '2026-11-11T11:00:00.000Z';
  const run = async (script, args, childEnv) => {
    if (script === 'scripts/collect.mjs') await writeFile(childEnv.FTSHARE_SEED_FILE, JSON.stringify({ ...seed, built_at: builtAt }));
    else execFileSync(process.execPath, [script, ...args], { cwd: root, env: childEnv, stdio: 'pipe' });
  };
  const result = await refreshDeployment({ root, env, run });
  assert.equal(result.built_at, builtAt);
  assert.notEqual(await readlink(resolve(root, '.local/current')), prior);
  assert.equal(JSON.parse(await readFile(resolve(root, 'data/private/seed.json'), 'utf8')).built_at, builtAt);
  assert.equal(JSON.parse(await readFile(resolve(root, '.local/last-refresh.json'), 'utf8')).built_at, builtAt);
});
