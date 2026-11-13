// Flight collector CLI: collects a date range from a fixture-style flight site through the JSON API or the page
// itself. Usage:
//   node scripts/collect-flights.ts --base http://localhost:PORT --from ALA --to AYT \
//     --date-from 2026-10-13 --date-to 2026-10-15 [--path api|browser] [--max-pages 3] \
//     [--from-name Алматы --to-name Анталия] [--timeout-ms 8000] [--json out.json]
// The browser path launches its own headless Chrome; the API path needs no browser.
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { collectFlights, renderCollectReport, selectFetcher, type CollectOptions, type CollectPath } from '../src/core/collect/index.ts';

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const baseUrl = arg('base') ?? process.env.FLIGHTS_BASE_URL;
const from = arg('from');
const to = arg('to');
const dateFrom = arg('date-from');
const dateTo = arg('date-to');
const path = (arg('path') ?? 'api') as CollectPath;
if (!baseUrl || !from || !to || !dateFrom || !dateTo || !['api', 'browser'].includes(path)) {
  console.error('usage: node scripts/collect-flights.ts --base URL --from ALA --to AYT --date-from YYYY-MM-DD --date-to YYYY-MM-DD [--path api|browser] [--max-pages N] [--from-name NAME --to-name NAME] [--json out.json]');
  process.exit(2);
}

const opts: CollectOptions = {
  baseUrl,
  from: { code: from, name: arg('from-name') },
  to: { code: to, name: arg('to-name') },
  dateFrom,
  dateTo,
  path,
  maxPagesPerDay: arg('max-pages') ? Number(arg('max-pages')) : undefined,
  pageTimeoutMs: arg('timeout-ms') ? Number(arg('timeout-ms')) : undefined,
  sort: arg('sort'),
};

let driver: { close(o?: { force?: boolean }): Promise<void> } | null = null;
let page: { close(): Promise<void> } | null = null;
let profile: string | null = null;
try {
  let fetcher;
  if (path === 'browser') {
    const { ChromiumDriver } = await import('../src/core/cdp/chromium.ts');
    const { PageSession } = await import('../src/core/cdp/page.ts');
    profile = mkdtempSync(join(tmpdir(), 'jev-collect-'));
    const d = await ChromiumDriver.launch({ headless: true, profileDir: profile });
    driver = d;
    const tab = await d.openTab('about:blank');
    const p = await PageSession.open(d, tab.id);
    page = p;
    fetcher = selectFetcher(opts, 'browser', { page: p, onAction: (n) => console.error(`[browser] ${n}`) });
  } else {
    fetcher = selectFetcher(opts, 'api');
  }
  const result = await collectFlights(opts, { fetcher });
  console.log(renderCollectReport(result));
  if (arg('json')) {
    writeFileSync(arg('json')!, JSON.stringify(result, null, 2));
    console.error(`wrote ${arg('json')}`);
  }
  process.exitCode = result.records.length > 0 ? 0 : 1;
} finally {
  await page?.close().catch(() => {});
  await driver?.close({ force: true }).catch(() => {});
  if (profile) rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}
