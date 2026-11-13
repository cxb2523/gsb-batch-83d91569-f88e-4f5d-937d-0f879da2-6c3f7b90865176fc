export const UPDATE_POLICY = { mode: 'background', timezone: 'Asia/Shanghai', daily: ['08:00', '12:30', '18:00'], intraday_seconds: 60, visitor_collection: false };
// Public requests only read published snapshots. No key, provider client or collection fallback.
export function createReadOnlyService(seed, { now = Date.now } = {}) {
  return {
    seed: () => ({ ...seed, update_policy: UPDATE_POLICY }),
    async live(env) {
      let entry;
      try { entry = await env.FTSHARE_CACHE?.get('live:snapshot', 'json'); } catch { /* use embedded last success */ }
      const value = entry?.value || seed.live_snapshot;
      if (!value) throw Object.assign(new Error('等待后台行情快照'), { code: 'cache_not_ready' });
      return { ...value, daily_batches: 0, cache: { mode: 'background', collected_at: value.fetched_at,
        checked_at: entry?.checked_at || null, stale: now() - Date.parse(value.fetched_at) > 180000,
        last_error: entry?.last_error || null, refresh_seconds: 60 } };
    },
    async marketHistory() { return { provider: seed.provider, rows: seed.history.dates.map((date, i) => ({ date, amount: seed.history.amount[i], idx: seed.history.idx[i] })) }; },
    async dailyBatch() { throw new Error('Visitor collection disabled'); },
    async cumulativeDate(date) {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date || '')) throw new Error('Invalid date');
      if (!seed.minutes[date]) throw Object.assign(new Error('尚未归档该日期'), { code: 'not_archived' });
      return { provider: seed.provider, date, ...seed.minutes[date] };
    }
  };
}
