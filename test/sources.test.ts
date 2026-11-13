import { afterEach, describe, expect, it, vi } from 'vitest';
import { MAINNET, type Candle, type MarketStats, type ProtocolHistory, type ProtocolSummary, type TradingState } from 'papertrade-sdk';
import type { HouseResponse } from '../src/types.js';

const { supplyMock, stakingMock, candlesMock } = vi.hoisted(() => ({
  supplyMock: vi.fn(),
  stakingMock: vi.fn(),
  candlesMock: vi.fn(),
}));

const actual = await vi.importActual<typeof import('papertrade-sdk')>('papertrade-sdk');

vi.mock('papertrade-sdk', async () => {
  const real = await vi.importActual<typeof import('papertrade-sdk')>('papertrade-sdk');
  return {
    ...real,
    publicClient: vi.fn((url: string) => ({ url })),
    paperTotalSupply: supplyMock,
    stakingState: stakingMock,
    fetchCandles: candlesMock,
  };
});

import { buildMetrics } from '../src/metrics.js';
import { ONCHAIN_SOURCES, collectInputs, readOnchain, skippedOnchainReport } from '../src/sources.js';
import { fixture } from './helpers.js';

const fixtures = {
  summary: fixture<ProtocolSummary>('summary'),
  marketStats: fixture<MarketStats>('market-stats'),
  trading: actual.decodeTradingState(fixture('trading')) as TradingState,
  history1h: fixture<ProtocolHistory>('history1h'),
  history1d: fixture<ProtocolHistory>('history1d'),
  house: fixture<HouseResponse>('house'),
};

const btcCandle: Candle = { time: 1, open: 100, high: 101, low: 99, close: 100, volume: 10 };
const ethCandle: Candle = { time: 1, open: 10, high: 11, low: 9, close: 10, volume: 5 };
const symbols = MAINNET.instruments.map((i) => i.name);
const RPC_A = 'https://rpc-a.test/evm';
const RPC_B = 'https://rpc-b.test/evm';

/** Serve the recorded indexer fixtures by request path, so no test leaves the machine. */
function stubFetch(): typeof fetch {
  const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  return (async (input: string | URL | Request) => {
    const path = String(typeof input === 'string' || input instanceof URL ? input : input.url);
    if (path.includes('/query/protocol/summary')) return json(fixtures.summary);
    if (path.includes('/query/protocol/market-stats')) return json(fixtures.marketStats);
    if (path.includes('/state/trading')) return json(fixture('trading'));
    if (path.includes('/query/protocol/history')) {
      return path.includes('interval=1h') ? json(fixtures.history1h) : json(fixtures.history1d);
    }
    if (path.includes('/state/house/current')) return json(fixtures.house);
    throw new Error(`unexpected indexer request: ${path}`);
  }) as typeof fetch;
}

afterEach(() => {
  supplyMock.mockReset();
  stakingMock.mockReset();
  candlesMock.mockReset();
});

describe('readOnchain RPC accounting', () => {
  it('marks every on-chain source failed with each RPC attempt when all RPCs refuse', async () => {
    supplyMock.mockRejectedValue(new Error('rpc down'));
    stakingMock.mockRejectedValue(new Error('rpc down'));
    const report = await readOnchain([RPC_A, RPC_B]);
    expect(report.reads).toBeNull();
    expect(report.sources.map((s) => s.source)).toEqual([...ONCHAIN_SOURCES]);
    for (const source of report.sources) {
      expect(source.status).toBe('failed');
      expect(source.rpcUrl).toBeUndefined();
      expect(source.attempts).toEqual([
        { rpcUrl: RPC_A, ok: false, error: 'rpc down' },
        { rpcUrl: RPC_B, ok: false, error: 'rpc down' },
      ]);
    }
    expect(supplyMock).toHaveBeenCalledTimes(2);
    expect(stakingMock).toHaveBeenCalledTimes(2);
  });

  it('records the first failure and the successful second RPC address', async () => {
    supplyMock.mockReset().mockRejectedValueOnce(new Error('first rpc rate limited')).mockResolvedValueOnce(42n * 10n ** 18n);
    stakingMock
      .mockReset()
      .mockRejectedValueOnce(new Error('first rpc rate limited'))
      .mockResolvedValueOnce({ totalStakedRaw: 7n * 10n ** 18n, accRewardPerShareRaw: 3n * 10n ** 27n, domainSeparator: '0xabc' });
    const report = await readOnchain([RPC_A, RPC_B]);
    expect(report.reads).not.toBeNull();
    expect(report.reads?.paperSupplyRaw).toBe(42n * 10n ** 18n);
    for (const source of report.sources) {
      expect(source.status).toBe('success');
      expect(source.rpcUrl).toBe(RPC_B);
      expect(source.attempts).toHaveLength(2);
      expect(source.attempts[0]).toEqual({ rpcUrl: RPC_A, ok: false, error: 'first rpc rate limited' });
      expect(source.attempts[1]).toEqual({ rpcUrl: RPC_B, ok: true });
    }
    expect(supplyMock).toHaveBeenCalledTimes(2);
    expect(stakingMock).toHaveBeenCalledTimes(2);
  });

  it('returns a skipped accounting with no attempts when the chain read never runs', () => {
    const report = skippedOnchainReport();
    expect(report.reads).toBeNull();
    expect(report.sources).toHaveLength(ONCHAIN_SOURCES.length);
    for (const source of report.sources) {
      expect(source.status).toBe('skipped');
      expect(source.attempts).toEqual([]);
      expect(source.rpcUrl).toBeUndefined();
    }
  });
});

describe('collectInputs degraded collection', () => {
  it('falls back to indexer PAPER values and flags every source failed when all RPCs fail', async () => {
    supplyMock.mockReset().mockRejectedValue(new Error('rpc down'));
    stakingMock.mockReset().mockRejectedValue(new Error('rpc down'));
    candlesMock.mockReset().mockResolvedValue([btcCandle]);
    const inputs = await collectInputs({ http: { fetch: stubFetch(), retries: 0 }, nowMs: 1_000, onchain: () => readOnchain([RPC_A, RPC_B]) });

    expect(inputs.onchain).toBeNull();
    for (const source of inputs.sourceReport.onchain) {
      expect(source.status).toBe('failed');
      expect(source.attempts.map((a) => a.rpcUrl)).toEqual([RPC_A, RPC_B]);
      expect(source.attempts.every((a) => a.ok === false)).toBe(true);
    }
    const metrics = buildMetrics(inputs);
    expect(metrics.source.onchain).toBe(false);
    expect(metrics.paper.supplySource).toBe('indexer');
    expect(metrics.paper.stakedSource).toBe('indexer');
    expect(metrics.paper.supply).toBeCloseTo(Number(fixtures.summary.paper.supply) / 1e18, 6);
    expect(metrics.paper.staked).toBeCloseTo(Number(fixtures.summary.paper.staked) / 1e18, 6);
  });

  it('uses on-chain supply and staking and reports the winning RPC when the fallback succeeds', async () => {
    supplyMock.mockReset().mockRejectedValueOnce(new Error('first rpc rate limited')).mockResolvedValueOnce(42n * 10n ** 18n);
    stakingMock
      .mockReset()
      .mockRejectedValueOnce(new Error('first rpc rate limited'))
      .mockResolvedValueOnce({ totalStakedRaw: 7n * 10n ** 18n, accRewardPerShareRaw: 3n * 10n ** 27n, domainSeparator: '0xabc' });
    candlesMock.mockReset().mockResolvedValue([btcCandle]);
    const inputs = await collectInputs({
      http: { fetch: stubFetch(), retries: 0 },
      nowMs: 1_000,
      onchain: () => readOnchain([RPC_A, RPC_B]),
    });
    const metrics = buildMetrics(inputs);
    expect(metrics.source.onchain).toBe(true);
    expect(metrics.paper.supply).toBe(42);
    expect(metrics.paper.staked).toBe(7);
    expect(metrics.paper.supplySource).toBe('onchain');
    expect(inputs.sourceReport.onchain.every((s) => s.status === 'success' && s.rpcUrl === RPC_B)).toBe(true);
    expect(inputs.sourceReport.onchain[0].attempts[0].error).toBe('first rpc rate limited');
  });

  it('keeps an empty candle array for a failed market while the other market and protocol metrics survive', async () => {
    candlesMock.mockReset().mockImplementation((symbol: string) =>
      symbol === 'BTC'
        ? Promise.reject(new Error('hyperliquid 502'))
        : Promise.resolve(symbol === 'ETH' ? [ethCandle] : []),
    );
    const inputs = await collectInputs({
      http: { fetch: stubFetch(), retries: 0 },
      nowMs: 1_000,
      onchain: async () => skippedOnchainReport(),
    });

    expect(inputs.candles.BTC).toEqual([]);
    expect(inputs.candles.ETH).toEqual([ethCandle]);
    const candleReport = Object.fromEntries(inputs.sourceReport.candles.map((c) => [c.symbol, c]));
    expect(candleReport.BTC).toEqual({ symbol: 'BTC', status: 'failed', error: 'hyperliquid 502' });
    expect(candleReport.ETH).toEqual({ symbol: 'ETH', status: 'success' });

    const metrics = buildMetrics(inputs);
    const bySymbol = Object.fromEntries(metrics.markets.map((m) => [m.symbol, m]));
    expect(bySymbol.BTC.priceUsd).toBeNull();
    expect(bySymbol.ETH.priceUsd).toBe(ethCandle.close);
    expect(bySymbol.ETH.sparkline).toEqual([ethCandle.close]);
    // Protocol-level reads are untouched by the candle failure.
    expect(metrics.protocol.tvlUsd).toBeCloseTo(124_170_607.73, 1);
    expect(metrics.protocol.openPositions).toBe(4857);
  });

  it('accounts one candle report per instrument in instrument order', async () => {
    candlesMock.mockReset().mockResolvedValue([btcCandle]);
    const inputs = await collectInputs({
      http: { fetch: stubFetch(), retries: 0 },
      nowMs: 1_000,
      onchain: async () => skippedOnchainReport(),
    });
    expect(inputs.sourceReport.candles.map((c) => c.symbol)).toEqual(symbols);
    expect(inputs.sourceReport.candles.every((c) => c.status === 'success')).toBe(true);
    expect(inputs.sourceReport.onchain.every((s) => s.status === 'skipped')).toBe(true);
  });
});
