import { BASKET, cumulative, split } from './model.js';

export function createDemoService(seed) {
  const date = seed.demo.as_of, minute = seed.minutes[date], amount = minute.cumulative.at(-1);
  const groups = split(seed.universe, 8);
  const provider = 'Demo', fetched_at = seed.built_at;
  return {
    seed: () => seed, groups,
    async live() {
      const weights = BASKET.map((_, i) => i + 1), denominator = weights.reduce((s, x) => s + x, 0);
      return { provider, formula: seed.formula, fetched_at, date, slots: seed.minute_slots, bars: minute.bars, cumulative: minute.cumulative,
        coverage: minute.bars.map(() => 20), closes: minute.bars.map((_, i) => 3500 + 22 * Math.sin(i / 42)), pre_close: 3490,
        last_complete_minute: '15:00', trading_dates: seed.calendar, expected_flow_date: seed.latest_flow_date, daily_batches: groups.length, warnings: [], amount,
        table: BASKET.map((symbol, i) => ({ symbol, code: symbol.slice(0, 6), name: seed.universe.find(f => f.symbol === symbol).name, price: 1 + i / 10, amount: amount * weights[i] / denominator, pct: Math.sin(i) * 1.2 })) };
    },
    async dailyBatch(batch) {
      if (!Number.isInteger(batch) || batch < 0 || batch >= groups.length) throw new Error('Invalid batch');
      const dates = seed.history.dates.slice(-3);
      return { provider, dates, funds: groups[batch].map(fund => ({ symbol: fund.symbol, days: Object.fromEntries(dates.map(d => [d, { flow: seed.demo.fund_flows[d][fund.symbol] }])) })) };
    },
    async cumulativeDate(requested) {
      if (!seed.minutes[requested]) throw new Error('Invalid date');
      return { provider, date: requested, slots: seed.minute_slots, ...seed.minutes[requested], cumulative: cumulative(seed.minutes[requested].bars) };
    },
    async marketHistory() {
      return { provider, fetched_at, rows: seed.history.dates.map((d, i) => ({ date: d, amount: seed.history.amount[i], idx: seed.history.idx[i] })) };
    }
  };
}
