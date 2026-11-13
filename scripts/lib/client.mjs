import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { createFTShare } from '../../src/server/ftshare.js';
import { loadAPIKey } from './key.mjs';
import { readWithRetry } from './read-retry.mjs';
import { requestPacer } from './request-pacer.mjs';

export async function collectorClient({ env = process.env, fetcher = fetch } = {}) {
  const key = await loadAPIKey(env);
  if (!key) throw new Error('Configure FTSHARE_API_KEY or FTSHARE_API_KEY_FILE before collecting live data');
  const upstream = createFTShare(key, fetcher), dir = new URL('../../.local/ftshare-cache/', import.meta.url);
  const pacer = requestPacer({ intervalMs: Math.max(500, Number(env.FTSHARE_REQUEST_INTERVAL_MS) || 1000) });
  const inflight = new Map();
  await mkdir(dir, { recursive: true });
  let requests = 0, hits = 0;
  async function call(name, args) {
    const path = new URL(createHash('sha256').update(JSON.stringify({ name, args })).digest('hex') + '.json', dir);
    // Cached market responses expire; a later collection can see corrected records.
    try { const entry = JSON.parse(await readFile(path, 'utf8')); if (Date.now() - Date.parse(entry.captured_at) < 3600000) { hits++; return entry.result; } } catch {}
    if (inflight.has(path.href)) return inflight.get(path.href);
    const pending = (async () => {
      const result = await readWithRetry(() => pacer.run(async () => {
        requests++;
        try { return await upstream.call(name, args); }
        catch (error) { if (error.code === 'rate_limited') pacer.defer(error.retryAfterMs || 60000); throw error; }
      }), { onLimit: ms => { pacer.defer(ms); console.log('Provider throttled ' + name + '; shared cooldown ' + Math.ceil(ms / 1000) + 's'); } });
      await writeFile(path, JSON.stringify({ captured_at: new Date().toISOString(), request: { name, args }, result }));
      return result;
    })().finally(() => inflight.delete(path.href));
    inflight.set(path.href, pending); return pending;
  }
  return {
    call, stats: () => ({ requests, hits }),
    async pages(name, args) {
      const rows = [];
      for (let page = 1; page <= 30; page++) {
        const result = await call(name, { ...args, page, page_size: 200 });
        if (!Array.isArray(result.data)) throw new Error('Unexpected response table: ' + name);
        rows.push(...result.data); if (!result.metadata?.pagination?.has_more) return rows;
      }
      throw new Error('Pagination incomplete: ' + name);
    }
  };
}
