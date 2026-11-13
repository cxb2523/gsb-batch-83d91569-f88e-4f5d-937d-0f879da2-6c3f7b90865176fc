// Preserve compatible, previously complete aggregates when a later query lacks old source coverage.
const valid = v => typeof v === 'number' && Number.isFinite(v);
const signature = seed => seed.universe.map(f => [f.symbol, f.bucket, f.is_core_basket, f.inception_date, f.listed_date].join('|')).sort().join('\n');
export function mergeSnapshot(previous, next) {
  if (!previous) return next;
  if (previous.demo || next.demo || previous.formula !== next.formula || signature(previous) !== signature(next)) throw new Error('Existing snapshot uses different members or formula. Import/review a compatible snapshot before collecting; it was not overwritten.');
  const result = structuredClone(next), union = (a, b) => [...new Set([...a, ...b])].sort();
  if (!result.live_snapshot && previous.live_snapshot) result.live_snapshot = previous.live_snapshot;
  if (previous.core_fund_daily?.date && (!result.core_fund_daily?.date || previous.core_fund_daily.date > result.core_fund_daily.date)) result.core_fund_daily = structuredClone(previous.core_fund_daily);
  result.calendar = union(previous.calendar, next.calendar);
  let kept = 0;
  const oldH = new Map(previous.history.dates.map((d, i) => [d, i])), newH = new Map(next.history.dates.map((d, i) => [d, i]));
  const h = result.history = { dates: union(previous.history.dates, next.history.dates), amount: [], idx: [], netflow: [], flow_coverage: [], flow_expected: [] };
  for (const d of h.dates) {
    const oi = oldH.get(d), ni = newH.get(d), useOldFlow = !valid(next.history.netflow[ni]) && valid(previous.history.netflow[oi]);
    for (const key of ['amount', 'idx', 'netflow']) h[key].push(valid(next.history[key][ni]) ? next.history[key][ni] : previous.history[key][oi] ?? null);
    for (const key of ['flow_coverage', 'flow_expected']) h[key].push(useOldFlow ? previous.history[key][oi] : next.history[key][ni] ?? previous.history[key][oi]);
  }
  const oldB = new Map(previous.broad.dates.map((d, i) => [d, i])), newB = new Map(next.broad.dates.map((d, i) => [d, i]));
  const b = result.broad = { dates: union(previous.broad.dates, next.broad.dates), cats: next.broad.cats, colors: next.broad.colors, total: [], series: {}, coverage: {}, issues: {} };
  for (const c of b.cats) { b.series[c] = []; b.coverage[c] = { valid: [], expected: [] }; }
  for (const date of b.dates) {
    const oi = oldB.get(date), ni = newB.get(date), missing = new Set();
    for (const c of b.cats) {
      const fresh = next.broad.series[c][ni], old = previous.broad.series[c][oi];
      const compatible = ni === undefined || next.broad.coverage[c].expected[ni] === previous.broad.coverage[c].expected[oi];
      const retain = !valid(fresh) && valid(old) && compatible;
      const origin = retain || ni === undefined ? previous.broad : next.broad, ix = origin === previous.broad ? oi : ni;
      b.series[c].push(origin.series[c][ix]);
      for (const key of ['valid', 'expected']) b.coverage[c][key].push(origin.coverage[c][key][ix]);
      if (retain) kept++;
      if (!valid(origin.series[c][ix])) missing.add(c);
    }
    b.total.push(missing.size ? null : b.cats.reduce((sum, c) => sum + b.series[c].at(-1), 0));
    const issues = [...(next.broad.issues?.[date] || []), ...(previous.broad.issues?.[date] || [])].filter(r => missing.has(r.bucket));
    if (issues.length) b.issues[date] = [...new Map(issues.map(r => [r.symbol, r])).values()];
  }
  result.minutes = { ...previous.minutes };
  for (const [date, minute] of Object.entries(next.minutes)) if (!minute.quality || !result.minutes[date] || result.minutes[date].quality) result.minutes[date] = minute;
  result.latest_flow_date = h.dates.filter((d, i) => valid(h.netflow[i])).at(-1);
  result.sources = [...new Set([...(previous.sources || []), ...(next.sources || [])])];
  if (previous.provider === 'FTShare+PublicSources') result.provider = previous.provider;
  result.source_audit = { ...result.source_audit, preserved_category_days: kept, previous_snapshot_build: previous.built_at, missing_days: b.dates.filter((d, i) => d <= result.latest_flow_date && b.total[i] === null).length };
  return result;
}
