// Deterministic synthetic values. This file never calls a market-data service.
import { readFile, writeFile } from 'node:fs/promises';
import { BASKET, CATEGORIES, COLORS, FORMULA, FLOW_POLICY, SLOTS, cumulative } from '../src/server/model.js';
import { validateSeed } from './lib/seed.mjs';

const root = new URL('../', import.meta.url);
const configured = JSON.parse(await readFile(new URL('config/universe.json', root), 'utf8'));
const universe = BASKET.map(symbol => configured.funds.find(f => f.symbol === symbol));
const calendar = [];
for (let t = Date.parse('2025-10-01T00:00:00Z'); t <= Date.parse('2026-02-27T00:00:00Z'); t += 86400000) {
  const d = new Date(t); if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) calendar.push(d.toISOString().slice(0, 10));
}
const dates = calendar.slice(1), asOf = dates.at(-1), fundFlows = {};
const broad = { dates, cats: CATEGORIES, colors: COLORS, total: [], issues: {}, series: {}, coverage: {} };
for (const c of CATEGORIES) { broad.series[c] = []; const n = universe.filter(f => f.bucket === c).length; broad.coverage[c] = { valid: dates.map(() => n), expected: dates.map(() => n) }; }
for (let i = 0; i < dates.length; i++) {
  const event = i % 17 === 0, daily = {};
  for (let j = 0; j < universe.length; j++) daily[universe[j].symbol] = Number(((event ? 9 : 1.8) * Math.sin(i / 8 + .6) + 1.1 * Math.cos(i / 4 + j / 5)).toFixed(6));
  fundFlows[dates[i]] = daily;
  for (const c of CATEGORIES) broad.series[c].push(universe.filter(f => f.bucket === c).reduce((sum, f) => sum + daily[f.symbol], 0));
  broad.total.push(CATEGORIES.reduce((sum, c) => sum + broad.series[c][i], 0));
}
const minutes = {};
for (let i = 0; i < dates.length; i++) {
  const scale = broad.total[i] > 100 ? 1.55 : .85 + .2 * (1 + Math.sin(i));
  const bars = SLOTS.map((_, j) => Number((scale * (1.2 + 7 * Math.exp(-j / 14) + 4 * Math.exp(-(240 - j) / 10) + .16 * Math.sin(j / 9))).toFixed(6)));
  minutes[dates[i]] = { bars, cumulative: cumulative(bars) };
}
const seed = {
  schema: 1, provider: 'Demo', sources: ['Synthetic examples'], built_at: '2026-03-01T00:00:00.000Z',
  formula: FORMULA, flow_policy: FLOW_POLICY,
  demo: { as_of: asOf, notice: 'All market values and calendar entries are synthetic. ETF names/codes are identifiers only.', fund_flows: fundFlows },
  universe_policy: { eligibility: 'Current configured members; synthetic example only.' }, universe, categories: CATEGORIES, colors: COLORS, calendar,
  history: { dates, amount: dates.map(d => minutes[d].cumulative.at(-1)), idx: dates.map((_, i) => 3200 + 2 * i + 95 * Math.sin(i / 11)), netflow: broad.total, flow_coverage: dates.map(() => 20), flow_expected: dates.map(() => 20) },
  broad, minutes, latest_flow_date: asOf, latest_market_date: asOf, minute_slots: SLOTS,
  source_audit: { provider: 'Demo', generator: 'scripts/generate-demo.mjs' }
};
validateSeed(seed, 'demo');
await writeFile(new URL('data/demo-seed.json', root), JSON.stringify(seed) + '\n');
console.log('Generated offline demo: ' + dates.length + ' synthetic weekdays, 20 ETFs. No real market values.');
