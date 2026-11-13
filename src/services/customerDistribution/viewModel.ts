import type {
  AvailableDistributionResult,
  CustomerDistributionState,
  RegionMapView
} from './types.ts';

/** 页面展示用的统计卡。 */
export interface StatCardView {
  key: 'totalCustomers' | 'activeCustomers' | 'growthRate' | 'coverage';
  label: string;
  value: string;
  /** 覆盖国家卡的副标题，例如“5 个主要国家”。 */
  hint?: string;
}

/**
 * 采集成功时页面可用的完整渲染模型。
 * map、stats、countries 全部拷贝自同一个 result 对象，不允许页面再从别处读取
 * 地图中心或统计数字。
 */
export interface AvailableView {
  kind: 'available';
  regionId: string;
  regionName: string;
  map: RegionMapView;
  stats: StatCardView[];
  countries: string[];
  sourceLabel: string;
  collectedAtLabel: string;
  fetchedAtLabel: string;
  modeLabel: string;
  mode: AvailableDistributionResult['collectionMode'];
}

/** 页面渲染模型，所有分支互斥，不会出现“部分数据来自旧区域”的拼装状态。 */
export type DistributionView =
  | {
      kind: 'idle';
      sourceLabel: string | null;
    }
  | {
      kind: 'loading';
      regionId: string;
      regionName: string;
      /** 采集期间不展示任何地图/数字，避免区域之间拼接展示。 */
      hint: string;
    }
  | AvailableView
  | {
      kind: 'unavailable';
      regionId: string;
      regionName: string;
      reasons: string[];
      sourceLabel: string;
      datasetUpdatedAtLabel: string;
      fetchedAtLabel: string;
      modeLabel: string;
    }
  | {
      kind: 'failure';
      regionId: string;
      regionName: string;
      reason: string;
      /** 上一次成功结果的完整渲染模型；页面继续展示它，并给出可见失败提示。 */
      retained: AvailableView | null;
      sourceLabel: string | null;
    };

const pad = (value: number): string => String(value).padStart(2, '0');

/** 固定为 UTC+8（演示数据的业务时区），避免不同机器时区导致“采集时间”漂移。 */
export const formatTimestamp = (iso: string | null | undefined): string => {
  if (!iso) {
    return '未知';
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return '未知';
  }
  const shifted = new Date(date.getTime() + 8 * 60 * 60 * 1000);
  return `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(
    shifted.getUTCDate()
  )} ${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}:${pad(
    shifted.getUTCSeconds()
  )}`;
};

const formatInteger = (value: number): string => {
  // 校验层已保证是非负整数；这里再做一次防御，异常值显示为“—”，绝不显示 0/NaN。
  if (!Number.isFinite(value) || !Number.isInteger(value) || value < 0) {
    return '—';
  }
  return value.toLocaleString('en-US');
};

const formatSignedPercent = (value: number): string => {
  if (!Number.isFinite(value)) {
    return '—';
  }
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
};

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * 防御性复核“同源”约束：地图与统计确实来自同一份 result。
 * 若未来有人往结果里塞入不一致字段，页面会拒绝展示而不是悄悄拼接。
 */
const isResultConsistent = (result: AvailableDistributionResult): boolean => {
  const map = result.map as unknown;
  if (!isPlainObject(map)) {
    return false;
  }
  const numbersOk = [result.totalCustomers, result.activeCustomers, result.growthRate].every(
    (value) => typeof value === 'number' && Number.isFinite(value)
  );
  const countriesOk = Array.isArray(result.topCountries) && result.topCountries.length > 0;
  return (
    numbersOk
    && countriesOk
    && typeof map.lat === 'number'
    && typeof map.lng === 'number'
    && typeof map.zoom === 'number'
    && typeof map.address === 'string'
    && map.lat >= -90
    && map.lat <= 90
    && map.lng >= -180
    && map.lng <= 180
  );
};

const sourceLabelOf = (state: CustomerDistributionState): string | null => {
  const info = state.datasetInfo;
  if (!info) {
    return null;
  }
  return `${info.sourceName}（ID: ${info.sourceId}）`;
};

/** 把一次采集成功结果转换为渲染模型；数据不一致时返回 null（页面拒绝展示）。 */
export const buildAvailableView = (
  result: AvailableDistributionResult,
  state: CustomerDistributionState
): AvailableView | null => {
  if (result.status !== 'available' || !isResultConsistent(result)) {
    return null;
  }

  const sourceLabel = sourceLabelOf(state) ?? `未知来源（ID: ${result.sourceId}）`;

  return {
    kind: 'available',
    regionId: result.regionId,
    regionName: result.regionName,
    map: { ...result.map },
    stats: [
      { key: 'totalCustomers', label: '总客户数', value: formatInteger(result.totalCustomers) },
      { key: 'activeCustomers', label: '活跃客户', value: formatInteger(result.activeCustomers) },
      { key: 'growthRate', label: '增长率', value: formatSignedPercent(result.growthRate) },
      {
        key: 'coverage',
        label: '覆盖国家',
        value: `${result.topCountries.length}`,
        hint: '主要国家'
      }
    ],
    countries: [...result.topCountries],
    sourceLabel,
    collectedAtLabel: formatTimestamp(result.collectedAt),
    fetchedAtLabel: formatTimestamp(result.fetchedAt),
    modeLabel: result.collectionMode === 'cache' ? '缓存复用结果' : '本次网络采集结果',
    mode: result.collectionMode
  };
};

export const buildDistributionView = (state: CustomerDistributionState): DistributionView => {
  const sourceLabel = sourceLabelOf(state);

  if (state.phase === 'loading') {
    const region =
      state.catalog.find((entry) => entry.id === state.pendingRegionId)
      ?? state.catalog.find((entry) => entry.id === state.selectedRegionId);
    return {
      kind: 'loading',
      regionId: state.pendingRegionId ?? state.selectedRegionId ?? 'unknown',
      regionName: region?.name ?? '未知区域',
      hint: '地图、统计卡与国家标签将在本次采集完成后一起更新。'
    };
  }

  if (state.failure) {
    return {
      kind: 'failure',
      regionId: state.failure.regionId,
      regionName: state.failure.regionName,
      reason: state.failure.reason,
      retained: state.lastSuccess ? buildAvailableView(state.lastSuccess, state) : null,
      sourceLabel
    };
  }

  const current = state.current;

  if (current?.status === 'unavailable') {
    return {
      kind: 'unavailable',
      regionId: current.regionId,
      regionName: current.regionName,
      reasons: current.reasons,
      sourceLabel: sourceLabel ?? `未知来源（ID: ${current.sourceId}）`,
      datasetUpdatedAtLabel: formatTimestamp(current.datasetUpdatedAt),
      fetchedAtLabel: formatTimestamp(current.fetchedAt),
      modeLabel: current.collectionMode === 'cache' ? '缓存复用结果' : '本次网络采集结果'
    };
  }

  if (current?.status === 'available') {
    const available = buildAvailableView(current, state);
    if (available) {
      return available;
    }
  }

  return { kind: 'idle', sourceLabel };
};

/** 采集链路审计信息，在页面底部可见，便于核对是否真的按区域采集。 */
export interface CollectionAuditView {
  requestCount: number;
  cacheHits: number;
  coalescedSelections: number;
  staleResultsIgnored: number;
  lastSelectionLabel: string;
}

const selectionLabels: Record<CustomerDistributionState['lastSelection'], string> = {
  none: '尚未选择',
  network: '本次发起采集请求',
  cache: '缓存命中（未重复请求）',
  coalesced: '合并到进行中的请求',
  failure: '本次采集失败'
};

export const buildAuditView = (state: CustomerDistributionState): CollectionAuditView => ({
  requestCount: state.requestCount,
  cacheHits: state.cacheHits,
  coalescedSelections: state.coalescedSelections,
  staleResultsIgnored: state.staleResultsIgnored,
  lastSelectionLabel: selectionLabels[state.lastSelection]
});
