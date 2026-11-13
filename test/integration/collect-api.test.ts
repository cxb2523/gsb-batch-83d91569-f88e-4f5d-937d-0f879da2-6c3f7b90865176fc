import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { startFixtureServer, type FixtureServer, flightsFor } from '../../fixtures/sites/server.ts';
import { collectFlights } from '../../src/core/collect/collect.ts';
import { ApiFlightFetcher } from '../../src/core/collect/fetcher-api.ts';
import { selectFetcher } from '../../src/core/collect/fetcher-select.ts';
import type { CollectResult } from '../../src/core/collect/types.ts';

let srv: FixtureServer;
let faulty: FixtureServer;
let slow: FixtureServer;
beforeAll(async () => {
  srv = await startFixtureServer();
  faulty = await startFixtureServer({ faults: [{ date: '2026-10-14', page: 2, status: 503 }] });
  slow = await startFixtureServer({ faults: [{ date: '2026-10-15', page: 1, delayMs: 2_000 }] });
});
afterAll(async () => { await srv.close(); await faulty.close(); await slow.close(); });

const base = (url = () => srv.url('')) => ({
  baseUrl: url(),
  from: { code: 'ALA', name: 'Алматы' },
  to: { code: 'AYT', name: 'Анталия' },
  dateFrom: '2026-10-13',
  dateTo: '2026-10-15',
});

describe('collector against the real fixture API', () => {
  it('collects three days over the network with the exact fixture data', async () => {
    const r = await collectFlights(base());
    expect(r.days.map((d) => d.status)).toEqual(['complete', 'complete', 'complete']);
    expect(r.records).toHaveLength(90);
    for (const date of ['2026-10-13', '2026-10-14', '2026-10-15']) {
      const expected = flightsFor('ALA', 'AYT', date).map((f) => f.price).sort((a, b) => a - b);
      expect(r.records.filter((x) => x.date === date).map((x) => x.price)).toEqual(expected);
    }
    // The fixture's known cheapest fare for 2026-10-14 is found on page 2.
    const cheapest = r.records.find((x) => x.date === '2026-10-14')!;
    expect(cheapest.price).toBe(38900);
    expect(cheapest.sourcePage).toBe(2);
  });

  it('is reproducible across runs', async () => {
    const a = await collectFlights(base());
    const b = await collectFlights(base());
    expect(b.records).toEqual(a.records);
    expect(b.days).toEqual(a.days);
  });

  it('reports a real HTTP failure per day without aborting the run', async () => {
    // A port with nothing listening: every request fails at the network level.
    const dead = `http://127.0.0.1:${Number(new URL(srv.url('')).port) + 1000}`;
    const fetcher = ApiFlightFetcher.forOptions({ ...base(), baseUrl: dead });
    const r: CollectResult = await collectFlights({ ...base(), baseUrl: dead, dateFrom: '2026-10-14', dateTo: '2026-10-15' }, { fetcher });
    expect(r.days.map((d) => d.status)).toEqual(['failed', 'failed']);
    expect(r.pages[0].outcome).toBe('failed');
    expect(r.pages[0].error).toBeTruthy();
    expect(r.records).toEqual([]);
  });

  it('selectFetcher builds the API fetcher for the api path', () => {
    expect(selectFetcher(base(), 'api').path).toBe('api');
    expect(() => selectFetcher(base(), 'browser')).toThrow(/PageSession/);
  });

  it('keeps the good days and reports the injected 503 with its status code', async () => {
    const opts = { ...base(() => faulty.url('')) };
    const r = await collectFlights(opts);
    expect(r.days.map((d) => d.status)).toEqual(['complete', 'failed', 'complete']);
    const failedDay = r.days[1];
    expect(failedDay).toMatchObject({ date: '2026-10-14', pages: 2, records: 10, total: 30 });
    const failedPage = r.pages.find((p) => p.date === '2026-10-14' && p.outcome === 'failed')!;
    expect(failedPage.httpStatus).toBe(503);
    expect(failedPage.error).toContain('503');
    // 10 records from page 1 of the failed day + 30 from each healthy day.
    expect(r.records).toHaveLength(70);
    expect(r.summary.outcomes.failed).toBe(1);
  });

  it('times out a slow day and still finishes the others', async () => {
    const opts = { ...base(() => slow.url('')), pageTimeoutMs: 400 };
    const r = await collectFlights(opts);
    expect(r.days.map((d) => d.status)).toEqual(['complete', 'complete', 'timeout']);
    expect(r.pages.find((p) => p.date === '2026-10-15')!.outcome).toBe('timeout');
    expect(r.records).toHaveLength(60);
  });
});
