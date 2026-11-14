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
// Outcomes that need no operator action; anything else fails a one-shot run.
const QUIET = new Set(['saved', 'outside_trading_session', 'already_collected_or_cooling_down', 'market_holiday']);
async function run() {
  const result = await collectMinute({ FTSHARE_CACHE: cache, FTSHARE_API_KEY: key }, { force: process.argv.includes('--now') });
  console.log(JSON.stringify(result));
  return result;
}
const watch = process.argv.includes('--watch');
const first = await run();
if (!watch && !QUIET.has(first.status)) process.exitCode = 1;
if (watch) for (;;) { await new Promise(resolve => setTimeout(resolve, 60000)); await run(); }
