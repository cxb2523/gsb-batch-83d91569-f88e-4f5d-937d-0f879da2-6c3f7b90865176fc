import { describe, it, expect } from 'vitest';
import { collectFlights } from '../../src/core/collect/collect.ts';
import { ApiFlightFetcher } from '../../src/core/collect/fetcher-api.ts';
import { expandDateRange, isValidIsoDate } from '../../src/core/collect/range.ts';
import { parseFlightsPayload, sortRecords } from '../../src/core/collect/parse.ts';
import { renderCollectReport } from '../../src/core/collect/report.ts';
import { flightsFor, dayMinPrice } from '../../fixtures/sites/server.ts';
import type { FlightFetcher, PageFetch } from '../../src/core/collect/types.ts';

const opts = {
  baseUrl: 'http://fixture.invalid',
  from: { code: 'ALA', name: 'Алматы' },
  to: { code: 'AYT', name: 'Анталия' },
  dateFrom: '2026-10-14',
  dateTo: '2026-10-16',
};

/** A fetcher over the fixture's deterministic data; `failOn` makes the named date/page fail like a bad API. */
function fixtureFetcher(failOn: Array<[string, number]> = [], opts2: { empty?: [string, number] } = {}): FlightFetcher {
  return {
    path: 'api',
    async fetchPage(date: string, page: number): Promise<PageFetch> {
      if (failOn.some(([d, p]) => d === date && p === page)) {
        return { outcome: 'failed', httpStatus: 503, error: 'HTTP 503' };
      }
      if (opts2.empty && opts2.empty[0] === date && opts2.empty[1] === page) {
        return { outcome: 'empty' };
      }
      const all = flightsFor('ALA', 'AYT', date);
      return {
        outcome: 'success',
        httpStatus: 200,
        items: all.slice((page - 1) * 10, page * 10).map(({ price, airline, depart, arrive, stops }) => ({ price, airline, depart, arrive, stops })),
        total: all.length,
      };
    },
  };
}

describe('date range', () => {
  it('expands inclusively across month boundaries', () => {
    expect(expandDateRange('2026-10-30', '2026-11-02')).toEqual(['2026-10-30', '2026-10-31', '2026-11-01', '2026-11-02']);
    expect(expandDateRange('2026-02-27', '2026-03-01')).toEqual(['2026-02-27', '2026-02-28', '2026-03-01']);
  });

  it('rejects malformed or reversed ranges', () => {
    expect(isValidIsoDate('2026-02-30')).toBe(false);
    expect(isValidIsoDate('14.10.2026')).toBe(false);
    expect(() => expandDateRange('2026-10-16', '2026-10-14')).toThrow(/after/);
    expect(() => expandDateRange('2026-13-01', '2026-13-02')).toThrow(/invalid/);
  });
});

describe('payload parsing', () => {
  it('rejects a body without items or total', () => {
    expect(() => parseFlightsPayload({})).toThrow(/items/);
    expect(() => parseFlightsPayload({ items: [] })).toThrow(/total/);
    expect(() => parseFlightsPayload([1, 2])).toThrow(/object/);
  });

  it('drops unusable items instead of failing the page', () => {
    const parsed = parseFlightsPayload({
      items: [
        { price: 38900, airline: 'AJet', depart: '10:45', arrive: '22:05', stops: 1 },
        { price: null, airline: 'X', depart: '10:00', arrive: '11:00', stops: 0 },
        { price: 41000, airline: '', depart: '10:00', arrive: '11:00', stops: 0 },
        { price: '42000', airline: 'SCAT', depart: '08:00', arrive: '09:00', stops: '0' },
      ],
      total: 4,
    });
    expect(parsed.dropped).toBe(2);
    expect(parsed.items.map((i) => i.price)).toEqual([38900, 42000]);
  });

  it('sorts by date then price, stably', () => {
    const mk = (date: string, price: number, page: number) => ({ date, price, airline: 'A', depart: '1', arrive: '2', stops: 0, sourcePage: page });
    expect(sortRecords([mk('2026-10-15', 50000, 1), mk('2026-10-14', 41000, 1), mk('2026-10-14', 41000, 2), mk('2026-10-14', 38900, 2)]))
      .toEqual([mk('2026-10-14', 38900, 2), mk('2026-10-14', 41000, 1), mk('2026-10-14', 41000, 2), mk('2026-10-15', 50000, 1)]);
  });
});

describe('collector: normal multi-day, multi-page run', () => {
  it('pages each day until total is covered and sorts records', async () => {
    const r = await collectFlights(opts, { fetcher: fixtureFetcher() });
    expect(r.days.map((d) => d.date)).toEqual(['2026-10-14', '2026-10-15', '2026-10-16']);
    for (const d of r.days) {
      expect(d.status).toBe('complete');
      expect(d.pages).toBe(3);
      expect(d.records).toBe(30);
      expect(d.total).toBe(30);
    }
    expect(r.summary).toMatchObject({ days: 3, pagesRequested: 9, records: 90 });
    expect(r.pages.every((p) => p.outcome === 'success')).toBe(true);
    expect(r.records).toHaveLength(90);
    // Stable ordering: date ascending, then price ascending.
    for (let i = 1; i < r.records.length; i++) {
      const a = r.records[i - 1];
      const b = r.records[i];
      expect(a.date <= b.date).toBe(true);
      if (a.date === b.date) expect(a.price <= b.price).toBe(true);
    }
    // Every record carries the page it came from and matches the fixture's data for its day.
    const first = r.records.find((x) => x.date === '2026-10-14');
    expect(first?.price).toBe(dayMinPrice('ALA', 'AYT', '2026-10-14'));
    expect(new Set(r.records.filter((x) => x.date === '2026-10-14').map((x) => x.sourcePage))).toEqual(new Set([1, 2, 3]));
  });

  it('produces identical output on repeated runs (no random ordering)', async () => {
    const a = await collectFlights(opts, { fetcher: fixtureFetcher() });
    const b = await collectFlights(opts, { fetcher: fixtureFetcher() });
    expect(b.records).toEqual(a.records);
    expect(b.pages).toEqual(a.pages);
    expect(b.days).toEqual(a.days);
  });

  it('reports an empty day as complete with zero records', async () => {
    const r = await collectFlights({ ...opts, dateFrom: '2026-10-15', dateTo: '2026-10-15' }, { fetcher: fixtureFetcher([], { empty: ['2026-10-15', 1] }) });
    expect(r.days[0]).toMatchObject({ status: 'complete', pages: 1, records: 0 });
    expect(r.summary.outcomes.empty).toBe(1);
  });

  it('flags an empty page that contradicts a non-zero total as incomplete', async () => {
    const fetcher: FlightFetcher = {
      path: 'api',
      async fetchPage(): Promise<PageFetch> {
        return { outcome: 'empty', httpStatus: 200, items: [], total: 30 };
      },
    };
    const r = await collectFlights({ ...opts, dateFrom: '2026-10-14', dateTo: '2026-10-14' }, { fetcher });
    expect(r.days[0]).toMatchObject({ status: 'incomplete', pages: 1, records: 0, total: 30 });
    expect(r.days[0].error).toContain('only 0 of 30');
  });
});

describe('collector: one day fails, the rest continue', () => {
  it('records the failing page with its status code and keeps other days', async () => {
    const r = await collectFlights(opts, { fetcher: fixtureFetcher([['2026-10-15', 2]]) });
    const middle = r.days.find((d) => d.date === '2026-10-15')!;
    expect(middle.status).toBe('failed');
    expect(middle.pages).toBe(2);
    expect(middle.records).toBe(10); // page 1 kept
    const failed = r.pages.find((p) => p.date === '2026-10-15' && p.outcome === 'failed')!;
    expect(failed.httpStatus).toBe(503);
    expect(failed.error).toContain('503');
    expect(r.days.find((d) => d.date === '2026-10-14')!.status).toBe('complete');
    expect(r.days.find((d) => d.date === '2026-10-16')!.status).toBe('complete');
    expect(r.records).toHaveLength(70);
    expect(r.summary.outcomes.failed).toBe(1);
    // Nothing is swallowed: the report names the date, page and status.
    expect(renderCollectReport(r)).toContain('2026-10-15 p2 failed HTTP 503');
  });

  it('turns an aborted request into timeout instead of throwing', async () => {
    const hanging: typeof fetch = (_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    });
    const fetcher = ApiFlightFetcher.forOptions({ ...opts, baseUrl: 'http://fixture.invalid' }, hanging);
    const r = await collectFlights({ ...opts, dateFrom: '2026-10-14', dateTo: '2026-10-15', pageTimeoutMs: 50 }, { fetcher });
    expect(r.days[0].status).toBe('timeout');
    expect(r.pages[0]).toMatchObject({ outcome: 'timeout', error: expect.stringContaining('50ms') });
    expect(r.days[1].status).toBe('timeout');
    expect(r.summary.outcomes.timeout).toBe(2);
  });

  it('survives a fetcher that throws', async () => {
    const fetcher: FlightFetcher = {
      path: 'api',
      async fetchPage(date) {
        if (date === '2026-10-15') throw new Error('boom');
        return { outcome: 'success', items: [{ price: 1, airline: 'A', depart: '1', arrive: '2', stops: 0 }], total: 1 };
      },
    };
    const r = await collectFlights(opts, { fetcher });
    expect(r.days.map((d) => d.status)).toEqual(['complete', 'failed', 'complete']);
    expect(r.days[1].error).toContain('boom');
    expect(r.records).toHaveLength(2);
  });
});

describe('collector: page cap', () => {
  it('marks the day truncated at the cap and adds a page_limit marker', async () => {
    const r = await collectFlights({ ...opts, maxPagesPerDay: 2 }, { fetcher: fixtureFetcher() });
    for (const d of r.days) {
      expect(d.status).toBe('truncated');
      expect(d.pages).toBe(2);
      expect(d.records).toBe(20);
      expect(d.total).toBe(30);
      expect(d.error).toContain('maxPagesPerDay=2');
    }
    const markers = r.pages.filter((p) => p.outcome === 'page_limit');
    expect(markers).toHaveLength(3);
    expect(markers.every((p) => !p.requested && p.page === 3)).toBe(true);
    expect(r.summary).toMatchObject({ pagesRequested: 6, records: 60 });
    expect(r.summary.outcomes.page_limit).toBe(3);
  });

  it('does not mark a day truncated when its total fits exactly in the cap', async () => {
    const r = await collectFlights({ ...opts, maxPagesPerDay: 3, dateFrom: '2026-10-14', dateTo: '2026-10-14' }, { fetcher: fixtureFetcher() });
    expect(r.days[0].status).toBe('complete');
    expect(r.summary.outcomes.page_limit).toBe(0);
  });
});

describe('API fetcher failure mapping', () => {
  it('maps a non-2xx status to failed with the code', async () => {
    const fetchImpl: typeof fetch = async () => new Response('nope', { status: 500 });
    const f = ApiFlightFetcher.forOptions({ ...opts }, fetchImpl);
    await expect(f.fetchPage('2026-10-14', 1, 1000)).resolves.toMatchObject({ outcome: 'failed', httpStatus: 500 });
  });

  it('maps an invalid JSON body to failed instead of throwing', async () => {
    const fetchImpl: typeof fetch = async () => new Response('<html>', { status: 200 });
    const f = ApiFlightFetcher.forOptions({ ...opts }, fetchImpl);
    await expect(f.fetchPage('2026-10-14', 1, 1000)).resolves.toMatchObject({ outcome: 'failed', error: expect.stringContaining('JSON') });
  });
});
