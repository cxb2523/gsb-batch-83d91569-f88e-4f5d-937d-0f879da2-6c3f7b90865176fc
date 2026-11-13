import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { once } from 'node:events';
import { fileURLToPath } from 'node:url';

test('standalone Node server serves all chart assets and demo APIs without local credentials', { timeout: 20000 }, async () => {
  const root = fileURLToPath(new URL('../', import.meta.url));
  execFileSync(process.execPath, ['scripts/build.mjs'], { cwd: root, env: { ...process.env, DATA_MODE: 'demo' }, stdio: 'pipe' });
  const child = spawn(process.execPath, ['scripts/serve.mjs'], { cwd: root, env: { ...process.env, HOST: '127.0.0.1', PORT: '0', FTSHARE_API_KEY: '', FTSHARE_API_KEY_FILE: '', FTSHARE_BUILD_DIR: 'dist', API_REQUESTS_PER_MINUTE: '3', TRUST_LOOPBACK_PROXY: '0' }, stdio: ['ignore', 'pipe', 'pipe'] });
  try {
    const url = await new Promise((resolve, reject) => {
      let text = ''; const timeout = setTimeout(() => reject(new Error('Server did not start')), 10000);
      child.stdout.on('data', chunk => { text += chunk; const match = text.match(/Dashboard: (http:\/\/127\.0\.0\.1:\d+)/); if (match) { clearTimeout(timeout); resolve(match[1]); } });
      child.on('error', error => { clearTimeout(timeout); reject(error); });
      child.on('exit', () => { clearTimeout(timeout); reject(new Error('Server exited before becoming ready')); });
    });
    const page = await (await fetch(url)).text();
    assert(page.includes('data-data-mode="demo"')); assert(page.includes('演示模式'));
    for (const id of ['chart','chartCum','chartTypCase','chartTypNorm','chartAmt','chartNf','chartDAmt','chartDNf','chartBroad']) assert(page.includes('id="' + id + '"'));
    for (const path of ['/style.css','/assets/ftai-mark.svg','/echarts.min.js','/assets/presentation.js','/assets/dashboard.js','/assets/flow-math.js','/api/board','/api/live','/api/history','/licenses/MIT.txt','/licenses/echarts-NOTICE.txt','/licenses/echarts-LICENSE.txt','/licenses/d3-LICENSE.txt']) assert.equal((await fetch(url + path)).status, 200, path);
    const health = await (await fetch(url + '/api/health')).json(); assert.equal(health.mode, 'demo'); assert.equal(health.configured, false);
    assert.equal(await (await fetch(url, { method: 'HEAD' })).text(), '');
    assert.equal((await fetch(url + '/api/live', { method: 'POST', body: 'x' })).status, 405);
    assert.equal((await fetch(url + '/.env')).status, 404);
    assert.equal((await fetch(url + '/data/private/seed.json')).status, 404);
    const limited = await fetch(url + '/api/board');
    assert.equal(limited.status, 429); assert.equal(limited.headers.get('retry-after'), '60');
    assert.equal((await fetch(url)).status, 200, 'API throttling must leave the page available');
    assert.equal((await fetch(url + '/api/health')).status, 200);
  } finally { child.kill('SIGTERM'); await once(child, 'exit'); }
});
