import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chinaDate } from '../src/server/model.js';
import { collectorClient } from './lib/client.mjs';
import { collectSnapshot } from './lib/collect.mjs';
import { validateSeed } from './lib/seed.mjs';
import { recentCollection } from './lib/recent-collection.mjs';
import { mergeSnapshot } from './lib/merge-snapshot.mjs';

if (process.argv.includes('--help')) {
  console.log('npm run collect -- [--end YYYY-MM-DD] [--recent]\nReads config/universe.json and config/collection.json. Requires your own FtShare key. Writes ignored data/private/seed.json only after validation.');
} else {
  const root = fileURLToPath(new URL('../', import.meta.url));
  const read = async path => JSON.parse(await readFile(resolve(root, path), 'utf8'));
  async function optional(path, fallback) { try { return await read(path); } catch (e) { if (e.code === 'ENOENT') return fallback; throw e; } }
  let config = await read('config/collection.json');
  const universe = await read('config/universe.json');
  const path = resolve(root, process.env.FTSHARE_SEED_FILE || 'data/private/seed.json');
  const previous = await optional(path, null);
  if (previous) validateSeed(previous, 'live');
  const endIndex = process.argv.indexOf('--end'), end = endIndex >= 0 ? process.argv[endIndex + 1] : chinaDate();
  const validDate = d => /^\d{4}-\d{2}-\d{2}$/.test(d || '') && new Date(d).toISOString().slice(0, 10) === d;
  if (![config.flow_start, config.market_start, end].every(validDate) || end < config.flow_start || end < config.market_start || !Number.isInteger(config.minute_days) || config.minute_days < 0) throw new Error('Invalid collection dates/minute_days');
  if (process.argv.includes('--recent')) config = recentCollection(config, previous, end);
  const supplement = await optional('data/private/public-shares.json', { rows: [] });
  const events = await optional('data/private/flow-recoveries.json', { funds: {} });
  if (!Array.isArray(supplement.rows)) throw new Error('public-shares.json must contain rows');
  const client = await collectorClient();
  const recoveries = { ...Object.fromEntries((previous?.universe || []).filter(f => f.flow_evidence).map(f => [f.symbol, f.flow_evidence])), ...events.funds };
  const fresh = await collectSnapshot({ config, universe, client, end, publicShares: supplement.rows, recoveries, progress: console.log });
  const seed = validateSeed(mergeSnapshot(previous, fresh), 'live');
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path + '.tmp', JSON.stringify(seed) + '\n'); await rename(path + '.tmp', path);
  console.log(JSON.stringify({ collected_through: seed.latest_flow_date, funds: seed.universe.length, broad_days: seed.broad.dates.length, incomplete_days: seed.source_audit.missing_days, ...client.stats() }));
}
