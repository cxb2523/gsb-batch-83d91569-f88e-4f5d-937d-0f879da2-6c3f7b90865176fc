export const RADAR_DEFAULTS = { cumulative: 1.5, burst: 2, minBurstAmount: 5, fundFlow: 10 };
const valid = v => typeof v === 'number' && Number.isFinite(v);
const sum = rows => rows.every(valid) ? rows.reduce((a, b) => a + b, 0) : null;
const mean = rows => rows.length ? rows.reduce((a, b) => a + b, 0) / rows.length : null;
function windowRange(slots, end) {
  const start = end - 4;
  if (start < 0 || !slots[end]) return null;
  const minute = s => Number(s.slice(0, 2)) * 60 + Number(s.slice(3));
  return minute(slots[end]) - minute(slots[start]) === 4 ? [start, end] : null;
}
export function evaluateRadar(seed, live, options = {}) {
  const rules = { ...RADAR_DEFAULTS, ...options };
  const slots = seed.minute_slots || [], actual = live?.bars || [], coverage = live?.coverage || [];
  const last = actual.map((v, i) => valid(v) && coverage[i] === 20 ? i : -1).reduce((a, b) => Math.max(a, b), -1);
  const end = Number.isInteger(options.at) ? Math.max(-1, Math.min(last, options.at)) : last;
  const history = Object.entries(seed.minutes || {}).filter(([date, r]) => date < live?.date && !r.quality && r.bars?.length === slots.length && r.bars.every(valid))
    .sort(([a], [b]) => b.localeCompare(a)).slice(0, 60);
  const covered = (start, stop) => stop >= start && actual.slice(start, stop + 1).length === stop - start + 1 && coverage.slice(start, stop + 1).length === stop - start + 1 && coverage.slice(start, stop + 1).every(n => n === 20);
  const amount = end >= 0 && covered(0, end) ? sum(actual.slice(0, end + 1)) : null;
  function baseline(window) {
    const rows = history.slice(0, window), ready = rows.length === window;
    const reference = ready && end >= 0 ? mean(rows.map(([, r]) => sum(r.bars.slice(0, end + 1)))) : null;
    const multiple = valid(amount) && reference > 0 ? amount / reference : null;
    function burstAt(i) {
      const range = windowRange(slots, i);
      if (!range || !ready || !covered(...range)) return { ratio: null, amount: null, reference: null, range };
      const value = sum(actual.slice(range[0], range[1] + 1)), ref = mean(rows.map(([, r]) => sum(r.bars.slice(range[0], range[1] + 1))));
      return { ratio: ref > 0 && valid(value) ? value / ref : null, amount: value, reference: ref, range };
    }
    const short = burstAt(end), priorShort = burstAt(end - 1);
    const burst = valid(short.ratio) && short.ratio >= rules.burst && short.amount >= rules.minBurstAmount;
    const burstConfirmed = burst && valid(priorShort.ratio) && priorShort.ratio >= rules.burst && priorShort.amount >= rules.minBurstAmount;
    return { window, ready, samples: rows.length, sampleDates: rows.map(([d]) => d), reference, multiple, short, burst, burstConfirmed,
      cumulativeAlert: valid(multiple) && multiple >= rules.cumulative };
  }
  const recent = baseline(20), long = baseline(60);
  const cumulativeSignal = recent.cumulativeAlert && long.cumulativeAlert ? 'both' : recent.cumulativeAlert ? 'recent' : long.cumulativeAlert ? 'long' : 'none';
  const burstDualConfirmed = recent.burstConfirmed && long.burstConfirmed;
  let state = 'normal', reason = 'none';
  if (!valid(amount)) state = 'incomplete';
  else if (!recent.ready || !valid(recent.multiple)) state = 'insufficient';
  else if (end < 14) state = 'warming';
  else if (cumulativeSignal === 'both') { state = 'strong'; reason = 'dual_cumulative'; }
  else if (burstDualConfirmed) { state = 'strong'; reason = 'dual_burst'; }
  else if (cumulativeSignal === 'recent') { state = 'watch'; reason = 'recent'; }
  else if (cumulativeSignal === 'long') { state = 'watch'; reason = 'long'; }
  else if (recent.burst || long.burst) { state = 'watch'; reason = 'burst'; }
  const core = seed.core_fund_daily;
  const flowDate = core?.date && core.date <= live?.date ? core.date : null;
  const flows = new Map((flowDate ? core.rows : []).map(row => [row.symbol, row]));
  const table = (live?.table || []).map(q => {
    const f = flows.get(q.symbol), flow = valid(f?.flow) ? f.flow : null;
    return { ...q, flow, flowDate: flow !== null ? flowDate : null, flowSignal: flow === null ? null : flow >= rules.fundFlow ? 'creation' : flow <= -rules.fundFlow ? 'redemption' : null };
  }).sort((a, b) => Number(Boolean(b.flowSignal)) - Number(Boolean(a.flowSignal)) || (b.amount ?? -1) - (a.amount ?? -1));
  const index = end >= 0 ? live?.closes?.[end] : null;
  return { rules, state, reason, date: live?.date || null, end, last, time: slots[end] || null, amount, recent, long, cumulativeSignal, burstDualConfirmed,
    // The legacy display aliases always refer to the 20-day baseline.
    reference: recent.reference, multiple: recent.multiple, short: recent.short, burst: recent.burst, burstConfirmed: recent.burstConfirmed,
    samples: recent.samples, sampleDates: recent.sampleDates, baseline: 20,
    indexPct: valid(index) && live?.pre_close > 0 ? (index / live.pre_close - 1) * 100 : null,
    table, flowDate, creations: table.filter(r => r.flowSignal === 'creation').length, redemptions: table.filter(r => r.flowSignal === 'redemption').length };
}
