// Private administrator process for Node deployments. The web server cannot start it.
import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { collectMinute } from '../src/background/collector.js';
import { loadAPIKey } from './lib/key.mjs';
const file = resolve(process.env.FTSHARE_LIVE_CACHE_FILE || 'data/private/live-cache.json');
const key = await loadAPIKey(); if (!key) throw new Error('Configure an authorized FtShare collector key');
let entries = {}; try { entries = JSON.parse(await readFile(file, 'utf8')).entries || {}; } catch (e) { if (e.code !== 'ENOENT') throw e; }
await mkdir(dirname(file), { recursive: true }); let pending = Promise.resolve();
const cache = {
  async get(k, type) { return entries[k] === undefined ? null : type === 'json' ? JSON.parse(entries[k]) : entries[k]; },
  put(k, value) {
    entries[k] = value;
    pending = pending.catch(() => {}).then(async () => { await writeFile(file + '.pending', JSON.stringify({ schema: 1, entries }), { mode: 0o600 }); await rename(file + '.pending', file); });
    return pending;
  }
};
async function run() { console.log(JSON.stringify(await collectMinute({ FTSHARE_CACHE: cache, FTSHARE_API_KEY: key }, { force: process.argv.includes('--now') }))); }
await run();
if (process.argv.includes('--watch')) for (;;) { await new Promise(resolve => setTimeout(resolve, 60000)); await run(); }
