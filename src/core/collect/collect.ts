import type {
  CollectOptions, CollectResult, DayStatus, DaySummary, FlightRecord, FlightFetcher, PageOutcome, PageResult,
} from './types.ts';
import { expandDateRange } from './range.ts';
import { ApiFlightFetcher } from './fetcher-api.ts';
import { sortRecords, toRecord } from './parse.ts';

export const DEFAULT_MAX_PAGES_PER_DAY = 5;
export const DEFAULT_PAGE_TIMEOUT_MS = 8_000;

export interface CollectDeps {
  /** Overrides the fetch path (the browser path supplies its own fetcher). */
  fetcher?: FlightFetcher;
  /** Injectable fetch used when the API fetcher is built here. */
  fetchImpl?: typeof fetch;
}

/**
 * Collects every flight for a date range, one day at a time and one page at a time.
 *
 * Failure policy: a page that fails or times out ends that day's pagination (the day's total can no longer be
 * trusted), its already-collected records are kept and the next day still runs. A day cut off by
 * `maxPagesPerDay` before its `total` is covered is reported as `truncated` with a `page_limit` marker. If the
 * fetcher never reported a total, reaching the cap also yields `truncated` (coverage cannot be proven).
 */
export async function collectFlights(opts: CollectOptions, deps: CollectDeps = {}): Promise<CollectResult> {
  const dates = expandDateRange(opts.dateFrom, opts.dateTo);
  if (!opts.baseUrl) throw new Error('baseUrl is required');
  if (!opts.from?.code) throw new Error('from.code is required');
  if (!opts.to?.code) throw new Error('to.code is required');
  const maxPages = opts.maxPagesPerDay ?? DEFAULT_MAX_PAGES_PER_DAY;
  const timeoutMs = opts.pageTimeoutMs ?? DEFAULT_PAGE_TIMEOUT_MS;
  if (!Number.isInteger(maxPages) || maxPages < 1) throw new Error('maxPagesPerDay must be a positive integer');
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error('pageTimeoutMs must be positive');

  const path = opts.path ?? deps.fetcher?.path ?? 'api';
  const fetcher: FlightFetcher = deps.fetcher
    ?? (opts.path === 'browser'
      ? (() => { throw new Error('path "browser" needs deps.fetcher (use selectFetcher with a PageSession)'); })()
      : ApiFlightFetcher.forOptions(opts, deps.fetchImpl));

  const days: DaySummary[] = [];
  const pages: PageResult[] = [];
  const records: FlightRecord[] = [];
  let fatal: unknown = null;

  try {
    for (const date of dates) {
      // A fetcher that throws unexpectedly (a bug, not a page failure) must not lose the other days.
      try {
        days.push(await collectDay(date, fetcher, maxPages, timeoutMs, pages, records));
      } catch (e) {
        fatal ??= e;
        days.push({
          date, status: 'failed', pages: 0, records: 0, total: null,
          error: e instanceof Error ? e.message : String(e),
        });
      }
    }
  } finally {
    await fetcher.dispose?.().catch(() => {});
  }

  return {
    from: opts.from.code,
    to: opts.to.code,
    dateFrom: opts.dateFrom,
    dateTo: opts.dateTo,
    path,
    maxPagesPerDay: maxPages,
    days,
    pages,
    records: sortRecords(records),
    summary: {
      days: days.length,
      pagesRequested: pages.filter((p) => p.requested).length,
      records: records.length,
      outcomes: countOutcomes(pages),
    },
    ...(fatal ? { error: fatal instanceof Error ? fatal.message : String(fatal) } : {}),
  };
}

async function collectDay(
  date: string,
  fetcher: FlightFetcher,
  maxPages: number,
  timeoutMs: number,
  pages: PageResult[],
  records: FlightRecord[],
): Promise<DaySummary> {
  let collected = 0;
  let knownTotal: number | null = null;
  let requested = 0;
  let status: DayStatus | null = null;
  let error: string | null = null;

  for (let page = 1; page <= maxPages; page++) {
    let fetch: Awaited<ReturnType<FlightFetcher['fetchPage']>>;
    try {
      fetch = await fetcher.fetchPage(date, page, timeoutMs);
    } catch (e) {
      // The contract says fetchers resolve failures; a throw is still contained to this page.
      fetch = { outcome: 'failed', error: e instanceof Error ? e.message : String(e) };
    }
    requested++;
    const items = fetch.items ?? [];
    if (fetch.total !== undefined && fetch.total !== null) knownTotal = fetch.total;

    pages.push({
      date,
      page,
      outcome: fetch.outcome,
      requested: true,
      httpStatus: fetch.httpStatus ?? null,
      total: fetch.total ?? null,
      records: items.length,
      error: fetch.error ?? null,
    });

    if (fetch.outcome === 'failed' || fetch.outcome === 'timeout') {
      status = fetch.outcome === 'failed' ? 'failed' : 'timeout';
      error = fetch.error ?? (fetch.httpStatus ? `HTTP ${fetch.httpStatus}` : 'request failed');
      break;
    }

    for (const item of items) {
      records.push(toRecord(date, page, item));
      collected++;
    }

    if (fetch.outcome === 'empty') {
      if (knownTotal !== null && collected < knownTotal) {
        status = 'incomplete';
        error = `page ${page} returned no items but only ${collected} of ${knownTotal} records were collected`;
      } else {
        status = 'complete';
      }
      break;
    }

    if (knownTotal !== null && collected >= knownTotal) {
      status = 'complete';
      break;
    }
  }

  if (status === null) {
    // The page cap was reached before the day's total was covered (or the day never reported a total).
    status = 'truncated';
    error = knownTotal !== null
      ? `stopped at maxPagesPerDay=${maxPages} with ${collected} of ${knownTotal} records`
      : `stopped at maxPagesPerDay=${maxPages} with ${collected} records and no reported total`;
  }

  if (status === 'truncated') {
    pages.push({
      date,
      page: requested + 1,
      outcome: 'page_limit',
      requested: false,
      httpStatus: null,
      total: knownTotal,
      records: 0,
      error: null,
    });
  }

  return { date, status, pages: requested, records: collected, total: knownTotal, error };
}

function countOutcomes(pages: PageResult[]): Record<PageOutcome, number> {
  const out: Record<PageOutcome, number> = { success: 0, empty: 0, failed: 0, timeout: 0, page_limit: 0 };
  for (const p of pages) out[p.outcome]++;
  return out;
}
