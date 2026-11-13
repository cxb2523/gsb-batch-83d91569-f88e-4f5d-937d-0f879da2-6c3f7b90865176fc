import test from 'node:test';
import assert from 'node:assert/strict';
import { clientAddress, createRequestGuard, positiveOption } from '../scripts/lib/request-guard.mjs';
import { createUpstreamGuard } from '../scripts/lib/upstream-guard.mjs';
import { mkdtemp, mkdir, writeFile, readFile, copyFile, rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { execFileSync } from 'node:child_process';

const url = 'https://market.ft.tech/gateway/mcp';
test('request limits reset, release concurrency once and bound client storage', () => {
  let time = 0;
  const guard = createRequestGuard({ perMinute: 2, concurrent: 1, maxClients: 1, now: () => time });
  const leave = guard.enter('one'); assert(leave);
  assert.equal(guard.enter('one'), null); leave(); leave();
  guard.enter('one')(); assert.equal(guard.enter('one'), null);
  assert.equal(guard.enter('two'), null);
  time = 60001; assert(guard.enter('two'));
});
test('forwarded identities cannot bypass limits on a directly exposed LAN listener', () => {
  const req = (remoteAddress, forwarded) => ({ socket: { remoteAddress }, headers: { 'x-forwarded-for': forwarded } });
  assert.equal(clientAddress(req('192.0.2.20', '198.51.100.7'), true), '192.0.2.20');
  assert.equal(clientAddress(req('::ffff:127.0.0.1', '198.51.100.7'), true), '198.51.100.7');
  assert.equal(clientAddress(req('127.0.0.1', '198.51.100.7'), false), '127.0.0.1');
  assert.equal(clientAddress(req('127.0.0.1', '198.51.100.7, 192.0.2.1'), true), '127.0.0.1');
  assert.throws(() => positiveOption({ LIMIT: '-1' }, 'LIMIT', 1));
});
test('all visitors share the upstream request budget, which resets without leaking key material', async () => {
  let calls = 0, time = 0;
  const guarded = createUpstreamGuard(async () => { calls++; return new Response('{"ok":true}'); }, { perMinute: 2, now: () => time });
  assert.equal((await guarded(url)).status, 200); await guarded(url);
  await assert.rejects(guarded(url), { code: 'quota_exceeded' }); assert.equal(calls, 2);
  time = 60001; await guarded(url); assert.equal(calls, 3);
});
test('upstream concurrency is held until body download finishes, with 204 notifications supported', async () => {
  let finish;
  const firstBody = new ReadableStream({ start(controller) { finish = () => controller.close(); } });
  const guarded = createUpstreamGuard(async () => new Response(firstBody), { concurrent: 1 });
  const pending = guarded(url);
  await assert.rejects(guarded(url), { code: 'quota_exceeded' });
  finish(); assert.equal((await pending).status, 200);
  const notification = createUpstreamGuard(async () => new Response(null, { status: 204 }));
  assert.equal((await notification(url)).status, 204);
});
test('429 responses stop immediate upstream retries and other fetch destinations remain untouched', async () => {
  let calls = 0, time = 0;
  const guarded = createUpstreamGuard(async () => { calls++; return new Response('quota', { status: 429 }); }, { now: () => time });
  assert.equal((await guarded(url)).status, 429);
  await assert.rejects(guarded(url), { code: 'quota_exceeded' }); assert.equal(calls, 1);
  await guarded('http://localhost/api/health'); assert.equal(calls, 2);
  time = 60001; await guarded(url); assert.equal(calls, 3);
});

test('Mac check reports network observations without printing credentials or claiming inbound success', { timeout: 20000 }, async t => {
  const root = await mkdtemp(resolve(tmpdir(), 'ftshare-network-check-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(resolve(root, 'scripts'));
  await copyFile(new URL('../scripts/mac-check.mjs', import.meta.url), resolve(root, 'scripts/mac-check.mjs'));
  const key = 'synthetic-secret-never-display';
  await writeFile(resolve(root, 'local-secret.txt'), key, { mode: 0o600 });
  const preload = resolve(root, 'mock-network.mjs');
  await writeFile(preload, `globalThis.fetch = async input => {
    if (input === 'https://api.ipify.org') return new Response('192.0.2.42');
    if (input === 'https://api6.ipify.org') return new Response('2001:db8::42');
    throw new Error('No network in test');
  };`);
  const output = execFileSync(process.execPath, ['--import', preload, 'scripts/mac-check.mjs'], {
    cwd: root, encoding: 'utf8', timeout: 15000,
    env: { ...process.env, FTSHARE_API_KEY: key, FTSHARE_API_KEY_FILE: 'local-secret.txt', HTTPS_PROXY: 'http://synthetic-user:proxy-password@example.invalid' }
  });
  assert(!output.includes(key)); assert(!output.includes('proxy-password')); assert(!output.includes('synthetic-user'));
  const report = JSON.parse(await readFile(resolve(root, '.local/macmini-check.json'), 'utf8'));
  assert.equal(report.egress_ipv4, '192.0.2.42');
  assert.match(report.public_inbound_access, /Not tested/);
  assert.equal(report.key_file.restrictive_permissions, true);
});
