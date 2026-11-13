import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { collectSnapshot, mergeShares } from '../scripts/lib/collect.mjs';
import { BASKET, SLOTS } from '../src/server/model.js';
import { validateSeed } from '../scripts/lib/seed.mjs';

const all = JSON.parse(await readFile(new URL('../config/universe.json', import.meta.url), 'utf8'));
const universe = { funds: all.funds.filter(f => BASKET.includes(f.symbol)) };
const calendar = ['2026-02-23', '2026-02-24', '2026-02-25', '2026-02-26'];
const config = { flow_start: calendar[1], market_start: calendar[1], minute_days: 1, concurrency: 2 };
function client(missing = false) {
  return {
    stats: () => ({ requests: 0 }),
    async pages(name, args) {
      if (name === 'ft_v2_etf_share') return calendar.map((d, i) => ({ statistics_period: '日', trade_date: Number(d.replaceAll('-', '')), fund_share: String(100000000 + i * 10000000) }));
      assert.equal(name, 'ft_v2_etf_net_value');
      return calendar.filter(d => !(missing && args.etf_code === BASKET[0] && d === calendar[2])).map(d => ({ nav_date: Number(d.replaceAll('-', '')), unit_nav: '1', adjustment_factor: '1' }));
    },
    async call(name, args) {
      if (name === 'ft_v1_time_trading_calendar') return { data: { trade_dates: calendar.map(d => Number(d.replaceAll('-', ''))) } };
      if (name === 'ft_v2_etf_candlesticks_batch') return { data: calendar.flatMap(d => args.symbols.map(symbol => ({ symbol, ts_millis: Date.parse(d + 'T15:00:00+08:00'), turnover: String(SLOTS.length * 1000000) }))) };
      if (name === 'ft_v1_index_candlesticks') return { data: calendar.map(d => ({ ts_millis: Date.parse(d + 'T15:00:00+08:00'), close: '3500' })) };
      assert.equal(name, 'ft_v2_etf_minutes_batch');
      const d = new Date(args.since_ts_millis + 8 * 3600000).toISOString().slice(0, 10);
      return { data: SLOTS.flatMap(time => args.symbols.map(symbol => ({ symbol, ts_millis: Date.parse(d + 'T' + time + ':00+08:00'), turnover: '1000000' }))) };
    }
  };
}
test('collector works from repository config and preserves SH/SZ alignment and the unpublished last day', async () => {
  const seed = validateSeed(await collectSnapshot({ config, universe, client: client(), end: calendar.at(-1) }), 'live');
  assert.equal(seed.latest_flow_date, '2026-02-25');
  assert(Math.abs(seed.broad.total[0] - 2) < 1e-10); assert.equal(seed.broad.total.at(-1), null);
  assert.deepEqual(Object.keys(seed.minutes), ['2026-02-25']);
  assert(Math.abs(seed.minutes['2026-02-25'].cumulative.at(-1) - seed.history.amount[1]) < 1e-8);
});
test('collector never fills a missing NAV with zero or claims complete historical coverage', async () => {
  const seed = validateSeed(await collectSnapshot({ config, universe, client: client(true), end: calendar.at(-1) }), 'live');
  assert.equal(seed.latest_flow_date, '2026-02-24'); assert.equal(seed.broad.total[1], null);
  assert(seed.broad.issues['2026-02-25'].some(r => r.reasons.includes('nav_missing')));
});
test('conflicting supplementary share values are rejected instead of silently overriding the provider', () => {
  const row = { symbol: '510300.SH', statistics_period: '日', trade_date: 20260224, fund_share: '100' };
  assert.throws(() => mergeShares([row], [{ ...row, fund_share: '101' }]), /Conflicting/);
  assert.equal(mergeShares([row], [{ ...row }]).length, 1);
});

test('index dates cover the flow window without inventing ETF turnover before the market window', async () => {
  const seed = validateSeed(await collectSnapshot({ config: { ...config, market_start: calendar[2], minute_days: 0 }, universe, client: client(), end: calendar.at(-1) }), 'live');
  assert.equal(seed.history.dates[0], config.flow_start);
  assert.equal(seed.history.idx[0], 3500);
  assert.equal(seed.history.amount[0], null);
  assert.equal(seed.history.netflow[0], null);
  assert(seed.history.amount[1] > 0);
});
