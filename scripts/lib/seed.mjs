import assert from 'node:assert/strict';
import { BASKET, CATEGORIES, FORMULA, SLOTS } from '../../src/server/model.js';

const number = value => value === null || typeof value === 'number' && Number.isFinite(value);
function dates(values, label) {
  assert(Array.isArray(values) && values.length, label + ' must be nonempty');
  assert(values.every((d, i) => /^\d{4}-\d{2}-\d{2}$/.test(d) && (!i || d > values[i - 1])), label + ' must be sorted, unique ISO dates');
}
function values(items, length, label) {
  assert(Array.isArray(items) && items.length === length && items.every(number), label + ' has invalid values or length');
}
export function validateSeed(seed, mode) {
  assert.equal(seed.schema, 1, 'Unsupported seed schema');
  assert(['demo', 'live'].includes(mode), 'DATA_MODE must be demo or live');
  assert.equal(Boolean(seed.demo), mode === 'demo', 'Demo and live data cannot be mixed');
  assert(mode === 'demo' ? seed.provider === 'Demo' : ['FTShare', 'FTShare+PublicSources'].includes(seed.provider), 'Unexpected data provider');
  assert.equal(seed.formula, FORMULA, 'Snapshot must use this release\'s exchange alignment and event policy');
  assert.deepEqual(seed.categories, CATEGORIES, 'Category order must match the model');
  assert.deepEqual(seed.minute_slots, SLOTS, 'Minute slots must match the trading session');
  assert(Array.isArray(seed.universe) && seed.universe.length >= 20, 'Missing ETF universe');
  assert.equal(new Set(seed.universe.map(f => f.symbol)).size, seed.universe.length, 'Duplicate ETF symbols');
  assert(BASKET.every(s => seed.universe.some(f => f.symbol === s && f.is_core_basket)), 'All 20 core ETFs are required');
  assert(seed.universe.filter(f => f.is_core_basket).length === 20, 'Core basket must contain exactly 20 ETFs');
  for (const fund of seed.universe) {
    assert(/^\d{6}\.(SH|SZ)$/.test(fund.symbol) && typeof fund.name === 'string', 'Invalid ETF description');
    assert(CATEGORIES.includes(fund.bucket), 'Unknown category: ' + fund.bucket);
    assert(/^\d{4}-\d{2}-\d{2}$/.test(fund.inception_date) && /^\d{4}-\d{2}-\d{2}$/.test(fund.listed_date), 'Missing inception/listing date');
  }
  dates(seed.calendar, 'calendar'); dates(seed.history?.dates, 'history.dates'); dates(seed.broad?.dates, 'broad.dates');
  for (const key of ['amount', 'idx', 'netflow', 'flow_coverage', 'flow_expected']) values(seed.history[key], seed.history.dates.length, 'history.' + key);
  const broad = seed.broad;
  assert.deepEqual(broad.cats, CATEGORIES);
  values(broad.total, broad.dates.length, 'broad.total');
  for (const category of CATEGORIES) {
    values(broad.series[category], broad.dates.length, category);
    for (const key of ['valid', 'expected']) {
      values(broad.coverage[category][key], broad.dates.length, category + '.' + key);
      assert(broad.coverage[category][key].every(v => Number.isInteger(v) && v >= 0));
    }
    broad.dates.forEach((_, i) => {
      const c = broad.coverage[category];
      assert(c.valid[i] <= c.expected[i], 'Coverage exceeds expected universe');
      assert((broad.series[category][i] !== null) === (c.valid[i] === c.expected[i]), 'Incomplete category must be null');
    });
  }
  broad.dates.forEach((_, i) => {
    const v = CATEGORIES.map(c => broad.series[c][i]);
    if (v.some(x => x === null)) assert.equal(broad.total[i], null, 'Incomplete total must be null');
    else assert(broad.total[i] !== null && Math.abs(v.reduce((a, b) => a + b, 0) - broad.total[i]) < 1e-6, 'Category totals do not reconcile');
  });
  assert(broad.dates.includes(seed.latest_flow_date), 'Latest flow date must belong to broad history');
  assert(seed.minutes && typeof seed.minutes === 'object', 'Missing minute samples');
  for (const minute of Object.values(seed.minutes)) {
    values(minute.bars, SLOTS.length, 'minute.bars'); values(minute.cumulative, SLOTS.length, 'minute.cumulative');
    let sum = 0, missing = false;
    minute.bars.forEach((v, i) => {
      if (v === null) missing = true;
      if (missing) assert.equal(minute.cumulative[i], null, 'Cumulative must stop at a gap');
      else { sum += v; assert(minute.cumulative[i] !== null && Math.abs(sum - minute.cumulative[i]) < 1e-6, 'Minute cumulative does not reconcile'); }
    });
  }
  assert(!/ftshare_sk_[A-Za-z0-9_-]{20,}/.test(JSON.stringify(seed)), 'Credentials must never be included in data');
  return seed;
}
