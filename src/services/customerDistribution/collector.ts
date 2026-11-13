import type {
  AvailableDistributionResult,
  CustomerDistributionDataSource,
  RegionCatalogEntry,
  UnavailableDistributionResult
} from './types.ts';
import { validateRecord } from './validator.ts';

export class RegionCollectionError extends Error {
  readonly cause?: unknown;

  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'RegionCollectionError';
    this.cause = cause;
  }
}

export interface CollectRegionOptions {
  /** 采集时间来源，由调用方注入，便于验收脚本固定时间。 */
  now: () => number;
  /** 人为增加的最小采集耗时，让加载态在本地样例上可见。 */
  minLatencyMs?: number;
  /** 用于让出事件循环并模拟真实网络等待。 */
  sleep: (ms: number) => Promise<void>;
}

/**
 * 抓取一个区域的客户分布并校验。
 *
 * - 上游请求失败 / 演示失败分支 → 抛 RegionCollectionError（由控制器保留上一次成功结果）
 * - 上游返回了记录但字段缺失/非法 → 返回 unavailable 结果（页面标记该区域不可用）
 * 两种情况都不会产出 0、NaN 或回退到写死数字。
 */
export const collectRegion = async (
  source: CustomerDistributionDataSource,
  region: RegionCatalogEntry,
  sourceId: string,
  datasetUpdatedAt: string,
  options: CollectRegionOptions
): Promise<AvailableDistributionResult | UnavailableDistributionResult> => {
  const startedAt = options.now();
  const minLatency = options.minLatencyMs ?? 0;

  let raw: unknown;
  try {
    raw = await source.loadRegionRecord(region.id);
  } catch (error) {
    throw new RegionCollectionError(
      `采集「${region.name}」失败：${error instanceof Error ? error.message : String(error)}`,
      error
    );
  }

  const outcome = validateRecord(raw, region.id, region.name);

  if (outcome.status === 'invalid') {
    await waitRemaining(startedAt, minLatency, options);
    return {
      status: 'unavailable',
      regionId: region.id,
      regionName: region.name,
      sourceId,
      datasetUpdatedAt,
      reasons: outcome.reasons,
      fetchedAt: new Date(options.now()).toISOString(),
      collectionMode: 'network'
    };
  }

  if (outcome.record.simulateCollectionFailure) {
    await waitRemaining(startedAt, minLatency, options);
    throw new RegionCollectionError(
      `采集「${region.name}」失败：${outcome.record.simulateCollectionFailure}`
    );
  }

  await waitRemaining(startedAt, minLatency, options);

  return {
    status: 'available',
    regionId: outcome.record.regionId,
    regionName: outcome.record.regionName,
    map: outcome.record.map,
    totalCustomers: outcome.record.totalCustomers,
    activeCustomers: outcome.record.activeCustomers,
    growthRate: outcome.record.growthRate,
    topCountries: outcome.record.topCountries,
    sourceId,
    collectedAt: outcome.record.collectedAt,
    fetchedAt: new Date(options.now()).toISOString(),
    collectionMode: 'network'
  };
};

const waitRemaining = async (
  startedAt: number,
  minLatencyMs: number,
  options: CollectRegionOptions
): Promise<void> => {
  if (minLatencyMs <= 0) {
    return;
  }
  const remaining = minLatencyMs - (options.now() - startedAt);
  if (remaining > 0) {
    await options.sleep(remaining);
  }
};
