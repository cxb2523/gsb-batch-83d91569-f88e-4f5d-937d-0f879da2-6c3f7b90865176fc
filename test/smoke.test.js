const { test } = require('node:test');
const assert = require('node:assert');
const { spawnSync, spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const root = path.join(__dirname, '..');
const cli = path.join(root, 'browser-control.js');
const run = (args, env = {}) =>
  spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8', env: { ...process.env, ...env } });

test('mcp.json and package.json are valid JSON', () => {
  for (const f of ['mcp.json', 'package.json']) {
    assert.doesNotThrow(() => JSON.parse(fs.readFileSync(path.join(root, f), 'utf8')), f);
  }
});

test('help lists the main commands', () => {
  const r = run(['help']);
  assert.strictEqual(r.status, 0);
  for (const c of ['start', 'navigate', 'wait', 'click', 'type']) {
    assert.ok(r.stdout.includes(c), `help output mentions ${c}`);
  }
});

test('navigate without a URL exits with code 1', () => {
  assert.strictEqual(run(['navigate']).status, 1);
});

test('version-check only reports strictly newer versions', () => {
  const { isNewer } = require('../version-check');
  assert.ok(isNewer('1.2.0', '1.1.0'));
  assert.ok(isNewer('1.10.0', '1.9.0'));
  assert.ok(!isNewer('1.0.0', '1.1.0'));
  assert.ok(!isNewer('1.1.0', '1.1.0'));
});

test('end-to-end: start -> navigate -> snapshot -> stop', { skip: process.env.LOBSTER_E2E !== '1' }, async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'lobster-e2e-'));
  const env = { HOME: tmp, LOBSTER_DATA_DIR: path.join(tmp, 'profile'), LOBSTER_PORT: '18793' };
  const server = spawn(process.execPath, [cli, 'start'], { env: { ...process.env, ...env }, stdio: 'ignore' });
  try {
    let started = false;
    for (let i = 0; i < 40 && !started; i++) {
      await new Promise((r) => setTimeout(r, 500));
      started = run(['status'], env).stdout.includes('"running": true');
    }
    assert.ok(started, 'browser started');
    const nav = run(['navigate', 'https://example.com'], env);
    assert.ok(nav.stdout.includes('"success": true') && nav.stdout.includes('Example Domain'), nav.stdout);
    const snap = run(['snapshot'], env);
    assert.ok(snap.stdout.includes('"title": "Example Domain"'), snap.stdout);
  } finally {
    run(['stop'], env);
    await new Promise((r) => (server.exitCode !== null ? r() : server.once('exit', r)));
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  assert.ok(run(['navigate', 'https://example.com'], env).stdout.includes('Browser not started'));
});
