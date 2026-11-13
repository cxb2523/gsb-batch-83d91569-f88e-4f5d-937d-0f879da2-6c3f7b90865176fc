/** Human-readable rendering of a collection result: per-day and per-page outcomes. */
import type { CollectResult, PageResult } from './types.ts';

/** One line per day, then a line per page with a non-success outcome. */
export function renderCollectReport(r: CollectResult): string {
  const lines: string[] = [];
  lines.push(`${r.from} → ${r.to} · ${r.dateFrom}..${r.dateTo} · path=${r.path} · maxPagesPerDay=${r.maxPagesPerDay}`);
  lines.push('');
  for (const d of r.days) {
    const total = d.total === null ? '?' : String(d.total);
    lines.push(`  ${d.date}  ${d.status.padEnd(10)} pages=${d.pages} records=${d.records}/${total}${d.error ? `  (${d.error})` : ''}`);
  }
  const notable = r.pages.filter((p) => p.outcome !== 'success' && p.outcome !== 'empty');
  if (notable.length) {
    lines.push('');
    for (const p of notable) lines.push(`  ${describePage(p)}`);
  }
  lines.push('');
  const o = r.summary.outcomes;
  lines.push(`days=${r.summary.days} pages=${r.summary.pagesRequested} records=${r.summary.records}` +
    ` | success=${o.success} empty=${o.empty} failed=${o.failed} timeout=${o.timeout} page_limit=${o.page_limit}`);
  if (r.error) lines.push(`collector error: ${r.error}`);
  return lines.join('\n');
}

export function describePage(p: PageResult): string {
  const status = p.httpStatus === null ? '' : ` HTTP ${p.httpStatus}`;
  const error = p.error ? ` ${p.error}` : '';
  if (p.outcome === 'page_limit') {
    return `${p.date} p${p.page} page_limit: stopped after the page cap` +
      (p.total === null ? '' : ` (total ${p.total})`);
  }
  return `${p.date} p${p.page} ${p.outcome}${status}${error} records=${p.records}`;
}
