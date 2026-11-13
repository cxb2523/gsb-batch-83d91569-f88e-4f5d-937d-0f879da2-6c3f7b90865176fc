import { createDataService } from '../server/service.js';
import { createFTShare } from '../server/ftshare.js';
import { chinaDate, BASKET } from '../server/model.js';
import { requestPacer } from '../../scripts/lib/request-pacer.mjs';
import universe from '../../config/universe.json' with { type: 'json' };

export function tradingMinute(time) {
  const d = new Date(time + 8 * 3600000), hm = d.toISOString().slice(11, 16), day = d.getUTCDay();
  return day > 0 && day < 6 && ((hm >= '09:30' && hm <= '11:30') || (hm >= '13:00' && hm <= '15:02'));
}
export function mergeLiveCache(next, previous) {
  if (!previous || previous.date !== next.date) return next;
  const result = structuredClone(next);
  for (let i = 0; i < result.bars.length; i++) {
    if (result.coverage[i] !== 20 && previous.coverage[i] === 20) { result.bars[i] = previous.bars[i]; result.coverage[i] = 20; }
    if (result.closes[i] == null) result.closes[i] = previous.closes[i];
  }
  result.last_complete_minute = result.slots.filter((s, i) => result.coverage[i] === 20).at(-1) || null;
  let total = 0; result.cumulative = result.bars.map(v => v == null ? null : (total += v));
  return result;
}
export function kvResponseCache(kv, now = Date.now) {
  return {
    async match(request) {
      if (new URL(request.url).pathname.startsWith('/v1/live-')) return undefined;
      const item = await kv.get('aux:' + request.url, 'json'); return item && item.expires > now() ? Response.json(item.value) : undefined;
    },
    async put(request, response) {
      if (new URL(request.url).pathname.startsWith('/v1/live-')) return;
      const ttl = Math.max(60, Number(response.headers.get('cache-control')?.match(/max-age=(\d+)/)?.[1]) || 3600);
      await kv.put('aux:' + request.url, JSON.stringify({ value: await response.json(), expires: now() + ttl * 1000 }), { expirationTtl: ttl });
    }
  };
}
export async function collectMinute(env, { now = Date.now, fetcher = fetch, force = false } = {}) {
  const time = now(); if (!force && !tradingMinute(time)) return { skipped: 'outside_trading_session' };
  const kv = env.FTSHARE_CACHE;
  const prior = await kv.get('live:snapshot', 'json');
  const slot = Math.floor(time / 60000);
  if (prior?.attempt_slot >= slot || Date.parse(prior?.next_attempt_at || '') > time) return { skipped: 'already_collected_or_cooling_down' };
  const stop = new AbortController(), abort = AbortSignal.any([AbortSignal.timeout(45000), stop.signal]), pacer = requestPacer({ intervalMs: 250 });
  let throttle;
  const onLimit = error => { throttle = error; stop.abort(); };
  const pacedFetch = (url, options) => pacer.run(async () => {
    abort.throwIfAborted();
    return fetcher(url, { ...options, signal: AbortSignal.any([abort, options.signal].filter(Boolean)) });
  });
  try {
    const date = chinaDate(time), cache = kvResponseCache(kv, now);
    const calendarKey = 'calendar:' + date;
    let calendar = await kv.get(calendarKey, 'json');
    if (!calendar) {
      const ft = createFTShare(env.FTSHARE_API_KEY, pacedFetch, { timeoutMs: 5000, onLimit });
      const start = chinaDate(time - 90 * 86400000).replaceAll('-', '');
      const r = await ft.call('ft_v1_time_trading_calendar', { market: 'cn', start_date: Number(start), end_date: Number(date.replaceAll('-', '')) });
      calendar = (Array.isArray(r.data) ? r.data[0] : r.data).trade_dates.map(d => String(d).replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3'));
      await kv.put(calendarKey, JSON.stringify(calendar), { expirationTtl: 172800 });
    }
    if (!calendar.includes(date)) return { skipped: 'market_holiday' };
    const seed = { calendar, universe: universe.funds.filter(f => BASKET.includes(f.symbol)) };
    const service = createDataService(seed, { fetcher: pacedFetch, now, persistentCache: cache, onLimit });
    const next = await service.live(env);
    if (throttle) throw throttle;
    if (next.date !== date || next.amount == null || !next.coverage.some(v => v === 20)) throw Object.assign(new Error('Incomplete intraday data'), { code: 'incomplete_snapshot' });
    const throttled = next.warnings.find(w => ['rate_limited', 'quota_exceeded'].includes(w.code));
    const value = mergeLiveCache(next, prior?.value);
    const entry = { value, checked_at: new Date(time).toISOString(), attempt_slot: slot, last_error: throttled?.code || (next.warnings.length ? 'partial_upstream' : null),
      next_attempt_at: throttled ? new Date(time + Math.max(60000, throttled.retry_after_ms || 0)).toISOString() : null };
    await kv.put('live:snapshot', JSON.stringify(entry));
    return { saved: true, as_of: value.date + ' ' + value.last_complete_minute, warnings: next.warnings.length };
  } catch (error) {
    error = throttle || error;
    const code = ['rate_limited','quota_exceeded','incomplete_snapshot'].includes(error.code) ? error.code : 'upstream_error';
    await kv.put('live:snapshot', JSON.stringify({ ...prior, checked_at: new Date(time).toISOString(), attempt_slot: slot, last_error: code,
      next_attempt_at: new Date(time + Math.max(error.code === 'quota_exceeded' ? 3600000 : 60000, error.retryAfterMs || 0)).toISOString() }));
    return { saved: false, retained_last_success: Boolean(prior?.value), error: code };
  }
}
export default {
  fetch(request) { return new Response('Not found', { status: request.method === 'GET' ? 404 : 405 }); },
  async scheduled(event, env, ctx) {
    // A bounded deployment validation window can exercise the real scheduler after close.
    const force = Date.now() < Date.parse(env.VALIDATION_UNTIL || '');
    ctx.waitUntil(collectMinute(env, { force }).then(result => console.log(JSON.stringify(result))));
  }
};
