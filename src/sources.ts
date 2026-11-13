import {
  MAINNET,
  PapertradeClient,
  fetchCandles,
  paperTotalSupply,
  publicClient,
  stakingState,
  type Candle,
  type HttpOptions,
} from 'papertrade-sdk';
import {
  buildMetrics,
  type MetricsInputs,
  type OnchainReadReport,
  type OnchainReads,
  type OnchainSourceReport,
  type RpcAttempt,
  type SourceReport,
} from './metrics.js';
import type { HouseResponse, Metrics, Snapshot } from './types.js';

/** The two on-chain reads behind a PAPER economics block, in the order the accounting lists them. */
export const ONCHAIN_SOURCES = ['supply', 'staking'] as const;

const DEFAULT_RPC_URLS = [MAINNET.network.rpcUrl, ...MAINNET.network.fallbackRpcUrls];

/** Pull a stable, non-empty failure reason out of whatever a client threw. */
export function describeError(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'string' && error) return error;
  try {
    return JSON.stringify(error) ?? 'unknown error';
  } catch {
    return 'unknown error';
  }
}

/** Read PAPER supply and staking state from HyperEVM, trying each configured RPC in order. */
export async function readOnchain(rpcUrls: readonly string[] = DEFAULT_RPC_URLS): Promise<OnchainReadReport> {
  const attempts: RpcAttempt[] = [];
  for (const rpcUrl of rpcUrls) {
    try {
      const client = publicClient(rpcUrl);
      const [paperSupplyRaw, staking] = await Promise.all([paperTotalSupply(client), stakingState(client)]);
      attempts.push({ rpcUrl, ok: true });
      const reads: OnchainReads = {
        paperSupplyRaw,
        totalStakedRaw: staking.totalStakedRaw,
        accRewardPerShareRaw: staking.accRewardPerShareRaw,
      };
      return { reads, sources: ONCHAIN_SOURCES.map((source) => ({ source, status: 'success', attempts, rpcUrl })) };
    } catch (error) {
      attempts.push({ rpcUrl, ok: false, error: describeError(error) });
    }
  }
  const sources: OnchainSourceReport[] = ONCHAIN_SOURCES.map((source) => ({ source, status: 'failed', attempts }));
  return { reads: null, sources };
}

/** Accounting for on-chain reads that never ran (injected reader, empty RPC list). */
export function skippedOnchainReport(): OnchainReadReport {
  return { reads: null, sources: ONCHAIN_SOURCES.map((source) => ({ source, status: 'skipped', attempts: [] })) };
}

/** Injected reader: anything collectInputs can call instead of readOnchain, returning its own accounting. */
export type OnchainReader = () => Promise<OnchainReadReport>;

/** Fetch everything the KPI document needs. Reads run in parallel; only the on-chain and candle reads may degrade. */
export async function collectInputs(params: {
  http?: HttpOptions;
  snapshots?: readonly Snapshot[];
  nowMs?: number;
  onchain?: OnchainReader;
}): Promise<MetricsInputs> {
  const client = new PapertradeClient({ clientBuild: 'papertrade-analytics', ...params.http });
  const nowMs = params.nowMs ?? Date.now();
  const symbols = MAINNET.instruments.map((i) => i.name);
  const [summary, marketStats, trading, history1h, history1d, house, onchainReport, ...candleResults] = await Promise.all([
    client.protocolSummary(),
    client.marketStats(),
    client.tradingState(),
    client.protocolHistory('1h'),
    client.protocolHistory('1d'),
    client.http.get<HouseResponse>('/state/house/current'),
    (params.onchain ?? readOnchain)(),
    ...symbols.map((symbol) =>
      fetchCandles(symbol, '1h', nowMs - 8 * 86_400_000, nowMs).then(
        (candles): { symbol: string; candles: Candle[]; error?: string } => ({ symbol, candles }),
        (error): { symbol: string; candles: Candle[]; error?: string } => ({
          symbol,
          candles: [],
          error: describeError(error),
        }),
      ),
    ),
  ]);
  const candles: Record<string, Candle[]> = {};
  const sourceReport: SourceReport = { onchain: onchainReport.sources, candles: [] };
  for (const result of candleResults) {
    candles[result.symbol] = result.candles;
    sourceReport.candles.push(
      result.error
        ? { symbol: result.symbol, status: 'failed', error: result.error }
        : { symbol: result.symbol, status: 'success' },
    );
  }
  return {
    nowMs,
    summary,
    marketStats,
    trading,
    history1h,
    history1d,
    house,
    candles,
    onchain: onchainReport.reads,
    sourceReport,
    snapshots: params.snapshots ?? [],
  };
}

export async function computeMetrics(params: Parameters<typeof collectInputs>[0]): Promise<{ metrics: Metrics; inputs: MetricsInputs }> {
  const inputs = await collectInputs(params);
  return { metrics: buildMetrics(inputs), inputs };
}

/** One KV sample of the house book, taken from the same inputs as a metrics document. */
export function snapshotFrom(inputs: MetricsInputs): Snapshot {
  const head = inputs.house.head;
  return {
    t: head[0] ?? inputs.nowMs,
    tvl: Number(inputs.summary.balances.tvl) / 1e18,
    margin: Number(inputs.summary.balances.margin) / 1e18,
    lp: head[1] ?? 0,
    pnl: head[2] ?? 0,
    open: inputs.summary.activity.open,
    btcLong: head[4] ?? 0,
    btcShort: head[5] ?? 0,
    ethLong: head[6] ?? 0,
    ethShort: head[7] ?? 0,
  };
}
