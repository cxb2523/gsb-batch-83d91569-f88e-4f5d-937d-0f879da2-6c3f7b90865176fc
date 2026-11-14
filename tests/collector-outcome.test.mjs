import test from 'node:test';
import assert from 'node:assert/strict';
import { collectMinute, COLLECT_OUTCOMES } from '../src/background/collector.js';
import { BASKET } from '../src/server/model.js';

const date = '2026-11-12', prevDay = '2026-11-11';
const time = Date.parse(date + 'T10:00:00+08:00');

function kv(initial = {}) {
  const rows = new Map(Object.entries(initial));
  return { rows, async get(k, type) { const v = rows.get(k); return v === undefined ? null : type === 'json' ? JSON.parse(v) : v; }, async put(k, v) { rows.set(k, v); } };
}
function json(result) {
  return new Response(JSON.stringify({ jsonrpc: '2.0', id: 1, result }), { status: 200, headers: { 'content-type': 'application/json' } });
}
// A fake FtShare MCP endpoint. The handler maps tool names to {data} / {error} payloads,
// or to a raw Response (e.g. a 429) to simulate transport-level limiting.
function rpcFetcher(handler) {
  let calls = 0;
  const fetcher = async (_url, options) => {
    calls++;
    const q = JSON.parse(options.body);
    if (q.method === 'initialize') return json({ protocolVersion: '2024-11-05' });
    if (q.method === 'notifications/initialized') return json({});
    const out = await handler(q.params.name, q.params.arguments || {});
    if (out instanceof Response) return out;
    return json({ structuredContent: { metadata: {}, ...out } });
  };
  fetcher.calls = () => calls;
  return fetcher;
}
const minuteRows = symbols => symbols.flatMap(symbol => ['09:30', '09:31'].map(t => ({ symbol, ts_millis: Date.parse(date + 'T' + t + ':00+08:00'), turnover: '100000000', close: '10' })));
function healthy(name, args) {
  if (name === 'ft_v1_time_trading_calendar') return { data: { trade_dates: [20261111, 20261112] } };
  if (name === 'ft_v4_stock_realtime_minute_kline' || name === 'ft_v4_etf_realtime_minute_kline') return { data: minuteRows(args.symbols) };
  if (name === 'ft_v4_index_realtime_minute_kline') return { data: ['09:30', '09:31'].map(t => ({ symbol: '000001.SH', ts_millis: Date.parse(date + 'T' + t + ':00+08:00'), close: '3500' })) };
  if (name === 'ft_v4_stock_realtime_day_kline' || name === 'ft_v4_etf_realtime_day_kline') return { data: args.symbols.map(symbol => ({ symbol, ts_millis: time, close: '10', turnover: '200000000' })) };
  if (name === 'ft_v4_index_realtime_day_kline') return { data: [{ symbol: '000001.SH', ts_millis: time, close: '3500' }] };
  if (name === 'ft_v2_stock_candlesticks_batch' || name === 'ft_v2_etf_candlesticks_batch') return { data: args.symbols.map(symbol => ({ symbol, ts_millis: Date.parse(prevDay + 'T15:00:00+08:00'), close: '9.9', turnover: '1' })) };
  if (name === 'ft_v1_index_candlesticks') return { data: [{ ts_millis: Date.parse(prevDay + 'T15:00:00+08:00'), close: '3490' }] };
  throw new Error('unexpected tool ' + name);
}
const env = (cache, extra = {}) => ({ FTSHARE_CACHE: cache, FTSHARE_API_KEY: 'test', ...extra });

test('every documented outcome is a non-empty string the collector can return', () => {
  for (const status of ['outside_trading_session', 'already_collected_or_cooling_down', 'market_holiday', 'saved', 'incomplete_snapshot', 'rate_limited', 'quota_exceeded', 'upstream_error'])
    assert(COLLECT_OUTCOMES.includes(status), status);
});

test('a healthy run saves a validated snapshot and same-minute reruns skip idempotently', async () => {
  const cache = kv(), fetcher = rpcFetcher(healthy);
  const result = await collectMinute(env(cache), { now: () => time, fetcher });
  assert.equal(result.status, 'saved');
  assert.equal(result.saved, true);
  assert.equal(result.retained_last_success, false);
  const saved = JSON.parse(cache.rows.get('live:snapshot'));
  assert.equal(saved.value.date, date);
  assert.equal(saved.value.coverage[0], 20);
  assert(saved.value.bars[0] > 0 && saved.value.closes[0] > 0);
  assert.equal(saved.last_error, null);
  assert.equal(saved.attempt_slot, Math.floor(time / 60000));
  const calls = fetcher.calls();
  const again = await collectMinute(env(cache), { now: () => time + 30000, fetcher });
  assert.equal(again.status, 'already_collected_or_cooling_down');
  assert.equal(again.retained_last_success, true);
  assert.equal(fetcher.calls(), calls, 'same-minute rerun must not hit the upstream');
});

test('a 429 retains the last good snapshot, cools down per Retry-After and skips while cooling', async () => {
  const value = { date, fetched_at: new Date(time - 60000).toISOString(), bars: [1, 2], closes: [3500, 3501], amount: 42 };
  const cache = kv({ 'live:snapshot': JSON.stringify({ value }) });
  const fetcher = rpcFetcher(() => new Response('rate limited', { status: 429, headers: { 'retry-after': '120' } }));
  const result = await collectMinute(env(cache), { now: () => time, fetcher });
  assert.equal(result.status, 'rate_limited');
  assert.equal(result.saved, false);
  assert.equal(result.retained_last_success, true);
  assert.equal(Date.parse(result.next_attempt_at), time + 120000);
  const saved = JSON.parse(cache.rows.get('live:snapshot'));
  assert.deepEqual(saved.value, value, 'stored bars and closes must survive the failure');
  assert.equal(saved.last_error, 'rate_limited');
  const calls = fetcher.calls();
  const during = await collectMinute(env(cache), { now: () => time + 30000, fetcher });
  assert.equal(during.status, 'already_collected_or_cooling_down');
  assert.equal(fetcher.calls(), calls, 'cooldown must skip without another upstream request');
});

test('an exhausted account quota cools down far longer than a plain 429', async () => {
  const cache = kv();
  const fetcher = rpcFetcher(() => ({ error: { code: 'daily_quota_exceeded', upstream_code: 429 } }));
  const result = await collectMinute(env(cache), { now: () => time, fetcher });
  assert.equal(result.status, 'quota_exceeded');
  assert.equal(result.retained_last_success, false);
  assert.equal(Date.parse(result.next_attempt_at), time + 3600000);
  const calls = fetcher.calls();
  const during = await collectMinute(env(cache), { now: () => time + 120000, fetcher });
  assert.equal(during.status, 'already_collected_or_cooling_down');
  assert.equal(fetcher.calls(), calls);
});

test('incomplete upstream data is never written over the stored snapshot', async () => {
  const value = { date, fetched_at: new Date(time - 60000).toISOString(), bars: [1, 2], closes: [3500, 3501], amount: 42 };
  const cache = kv({ 'live:snapshot': JSON.stringify({ value }) });
  const fetcher = rpcFetcher((name, args) => {
    if (name.includes('realtime_minute_kline')) return { data: [] };
    return healthy(name, args);
  });
  const result = await collectMinute(env(cache), { now: () => time, fetcher });
  assert.equal(result.status, 'incomplete_snapshot');
  assert.equal(result.saved, false);
  assert.equal(result.retained_last_success, true);
  assert(Date.parse(result.next_attempt_at) > time);
  const saved = JSON.parse(cache.rows.get('live:snapshot'));
  assert.deepEqual(saved.value, value, 'partial data must not null out stored bars or closes');
  assert.equal(saved.last_error, 'incomplete_snapshot');
});

test('holidays and minutes outside the session skip without touching the upstream', async () => {
  const fetcher = rpcFetcher(healthy);
  const holiday = kv({ ['calendar:' + date]: JSON.stringify([prevDay]) });
  const closed = await collectMinute(env(holiday), { now: () => time, fetcher });
  assert.equal(closed.status, 'market_holiday');
  assert.equal(fetcher.calls(), 0);
  const weekend = await collectMinute(env(kv()), { now: () => Date.parse('2026-11-14T10:00:00+08:00'), fetcher });
  assert.equal(weekend.status, 'outside_trading_session');
  assert.equal(fetcher.calls(), 0);
});
