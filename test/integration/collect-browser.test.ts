import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { startHarness, type Harness } from './harness.ts';
import { startFixtureServer, type FixtureServer } from '../../fixtures/sites/server.ts';
import { collectFlights, selectFetcher } from '../../src/core/collect/index.ts';
import type { CollectResult, FlightRecord } from '../../src/core/collect/types.ts';

let h: Harness;
let faulty: FixtureServer;
let slow: FixtureServer;
beforeAll(async () => {
  h = await startHarness();
  faulty = await startFixtureServer({ faults: [{ date: '2026-10-13', page: 1, status: 503 }] });
  slow = await startFixtureServer({ faults: [{ date: '2026-10-14', page: 1, delayMs: 3_000 }] });
}, 120_000);
afterAll(async () => { await h?.close(); await faulty?.close(); await slow?.close(); });

const base = () => ({
  baseUrl: h.fixtures.url(''),
  from: { code: 'ALA', name: 'Алматы' },
  to: { code: 'AYT', name: 'Анталия' },
  dateFrom: '2026-10-13',
  dateTo: '2026-10-14',
});

const fieldNames = (r: FlightRecord) => Object.keys(r).sort();

describe('collector through the browser page', () => {
  it('drives the search form and "show more" and yields the same records as the API path', async () => {
    const page = await h.open('flights.html');
    const actions: string[] = [];
    const opts = base();
    const browser = await collectFlights(
      { ...opts, path: 'browser', maxPagesPerDay: 3 },
      { fetcher: selectFetcher({ ...opts, path: 'browser' }, 'browser', { page, onAction: (n) => actions.push(n) }) },
    );
    const api = await collectFlights({ ...opts, maxPagesPerDay: 3 });

    expect(browser.path).toBe('browser');
    expect(browser.days.map((d) => d.status)).toEqual(['complete', 'complete']);
    expect(browser.records).toHaveLength(60);
    // Same fields, same values, same order: the browser path is not a different schema.
    expect(browser.records).toEqual(api.records);
    expect(fieldNames(browser.records[0])).toEqual(['airline', 'arrive', 'date', 'depart', 'price', 'sourcePage', 'stops']);
    // Every page was requested by the page itself (the JSON was captured from the network).
    expect(browser.summary.pagesRequested).toBe(6);
    expect(browser.pages.every((p) => p.requested && p.httpStatus === 200)).toBe(true);
    expect(actions.some((a) => /calendar/.test(a))).toBe(true);
  }, 180_000);

  it('records a failed page with its status code and keeps collecting the next day', async () => {
    const page = await h.open('about:blank');
    const opts = { ...base(), baseUrl: faulty.url(''), path: 'browser' as const, pageTimeoutMs: 8_000 };
    const r: CollectResult = await collectFlights(opts, { fetcher: selectFetcher(opts, 'browser', { page }) });
    expect(r.days.map((d) => d.status)).toEqual(['failed', 'complete']);
    const failedPage = r.pages.find((p) => p.date === '2026-10-13')!;
    expect(failedPage).toMatchObject({ outcome: 'failed', httpStatus: 503, page: 1, requested: true });
    expect(r.days[1].records).toBe(30);
    expect(r.records.every((x) => x.date === '2026-10-14')).toBe(true);
  }, 120_000);

  it('times out a slow day instead of hanging the run', async () => {
    const page = await h.open('about:blank');
    const opts = { ...base(), baseUrl: slow.url(''), path: 'browser' as const, pageTimeoutMs: 1_000, dateFrom: '2026-10-14', dateTo: '2026-10-14' };
    const r: CollectResult = await collectFlights(opts, { fetcher: selectFetcher(opts, 'browser', { page }) });
    expect(r.days[0]).toMatchObject({ status: 'timeout', pages: 1, records: 0 });
    expect(r.pages[0]).toMatchObject({ outcome: 'timeout', requested: true });
    expect(r.pages[0].error).toContain('1000ms');
  }, 60_000);

  it('reports an unreachable site as a failed day without crashing the run', async () => {
    // Port with nothing listening: the page cannot even load, so each day fails on its own.
    const port = Number(new URL(h.fixtures.url('')).port);
    const dead = `http://127.0.0.1:${port + 1000}/`;
    const page = await h.open('about:blank');
    const opts = { ...base(), baseUrl: dead, path: 'browser' as const, pageTimeoutMs: 2_000 };
    const r: CollectResult = await collectFlights(opts, { fetcher: selectFetcher(opts, 'browser', { page }) });
    expect(r.days.map((d) => d.date)).toEqual(['2026-10-13', '2026-10-14']);
    expect(r.days.every((d) => d.status === 'failed' || d.status === 'timeout')).toBe(true);
    expect(r.records).toEqual([]);
    expect(r.pages.length).toBe(2);
    expect(r.pages.every((p) => p.outcome === 'failed' || p.outcome === 'timeout')).toBe(true);
  }, 90_000);
});
