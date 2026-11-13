// Re-query a rolling overlap for corrections; mergeSnapshot preserves older complete history.
export function recentCollection(config, previous, end) {
  if (!previous) throw new Error('--recent requires an imported live snapshot');
  const last = [previous.latest_flow_date, previous.latest_market_date].filter(Boolean).sort()[0];
  const anchor = last < end ? last : end;
  const start = new Date(Date.parse(anchor + 'T00:00:00Z') - 14 * 86400000).toISOString().slice(0, 10);
  return { ...config, flow_start: start > config.flow_start ? start : config.flow_start,
    market_start: start > config.market_start ? start : config.market_start };
}
