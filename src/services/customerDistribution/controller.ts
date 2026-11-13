import type {
  AvailableDistributionResult,
  CollectionFailure,
  CustomerDistributionControllerOptions,
  CustomerDistributionDataSource,
  CustomerDistributionState,
  DistributionResult,
  RegionCatalogEntry
} from './types.ts';
import { collectRegion, RegionCollectionError } from './collector.ts';
import { parseCatalog } from './dataSource.ts';

const defaultSleep = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

const initialState = (): CustomerDistributionState => ({
  catalog: [],
  catalogStatus: 'idle',
  catalogError: null,
  datasetInfo: null,
  selectedRegionId: null,
  pendingRegionId: null,
  phase: 'idle',
  current: null,
  lastSuccess: null,
  failure: null,
  requestCount: 0,
  cacheHits: 0,
  coalescedSelections: 0,
  lastSelection: 'none',
  staleResultsIgnored: 0
});

/**
 * 采集单次调用的结果。失败也被缓存，保证“同一区域重复点击不重复请求”，
 * 也意味着失败区域在本次会话中不会自动重试（刷新页面即可重试）。
 */
type CollectionOutcome =
  | { status: 'success'; result: DistributionResult }
  | { status: 'failed'; failure: CollectionFailure };

export interface CustomerDistributionController {
  getState: () => CustomerDistributionState;
  subscribe: (listener: () => void) => () => void;
  /** 加载数据源目录（区域按钮列表 + 来源信息）。 */
  loadCatalog: () => Promise<void>;
  /**
   * 切换区域。每次调用都会推进“最新选择”令牌：
   * - 同一区域已在采集 → 合并到已有请求，不重复请求
   * - 同一区域已采集过（成功/不可用/失败）→ 直接复用缓存
   * - 采集期间再次切换 → 旧结果返回时被丢弃，只应用最后一次选择
   */
  selectRegion: (regionId: string) => Promise<void>;
  dispose: () => void;
}

/**
 * 客户分布采集控制器。
 *
 * 页面所有展示字段（地图、统计卡、国家标签）都读取自 current/lastSuccess，
 * 二者只会被同一次采集结果整体替换，避免出现“地图是新区域、数字是旧区域”的拼接。
 */
export const createCustomerDistributionController = (
  source: CustomerDistributionDataSource,
  options: CustomerDistributionControllerOptions = {}
): CustomerDistributionController => {
  const now = options.now ?? Date.now;
  let state = initialState();
  const listeners = new Set<() => void>();
  /** 已完成的采集（含不可用与失败）；key 为 regionId。 */
  const cache = new Map<string, CollectionOutcome>();
  /** 进行中的请求，按区域合并，保证同一区域重复点击不重复请求。 */
  const inFlight = new Map<string, Promise<CollectionOutcome>>();
  /** 最新一次选择令牌；旧令牌的结果只计数，不渲染。 */
  let selectionToken = 0;
  let disposed = false;

  const setState = (patch: Partial<CustomerDistributionState>): void => {
    state = { ...state, ...patch };
    for (const listener of listeners) {
      listener();
    }
  };

  const getState = (): CustomerDistributionState => state;

  const subscribe = (listener: () => void): (() => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  };

  const loadCatalog = async (): Promise<void> => {
    if (state.catalogStatus === 'loading' || state.catalogStatus === 'ready') {
      return;
    }

    setState({ catalogStatus: 'loading', catalogError: null });

    try {
      const raw = await source.loadCatalog();
      const { regions, info } = parseCatalog(raw, source.location);
      setState({
        catalog: regions,
        catalogStatus: 'ready',
        datasetInfo: info
      });

      if (options.autoSelectFirstRegion && regions.length > 0 && !state.selectedRegionId) {
        await selectRegion(regions[0].id);
      }
    } catch (error) {
      if (disposed) {
        return;
      }
      setState({
        catalogStatus: 'error',
        catalogError: error instanceof Error ? error.message : String(error)
      });
    }
  };

  const startCollection = (
    region: RegionCatalogEntry,
    info: NonNullable<CustomerDistributionState['datasetInfo']>
  ): Promise<CollectionOutcome> => {
    setState({
      selectedRegionId: region.id,
      pendingRegionId: region.id,
      phase: 'loading',
      lastSelection: 'network',
      requestCount: state.requestCount + 1
    });

    const task = collectRegion(source, region, info.sourceId, info.updatedAt, {
      now,
      minLatencyMs: options.minLatencyMs ?? 450,
      sleep: options.sleep ?? defaultSleep
    })
      .then<CollectionOutcome>((result) => ({ status: 'success', result }))
      .catch<CollectionOutcome>((error: unknown) => ({
        status: 'failed',
        failure: {
          regionId: region.id,
          regionName: region.name,
          reason: error instanceof RegionCollectionError
            ? error.message
            : `采集「${region.name}」失败：${error instanceof Error ? error.message : String(error)}`,
          at: new Date(now()).toISOString()
        }
      }))
      .then((outcome) => {
        cache.set(region.id, outcome);
        return outcome;
      })
      .finally(() => {
        inFlight.delete(region.id);
      });

    inFlight.set(region.id, task);
    return task;
  };

  const applyOutcome = (
    region: RegionCatalogEntry,
    outcome: CollectionOutcome,
    mode: CustomerDistributionState['lastSelection']
  ): void => {
    if (outcome.status === 'failed') {
      // 失败不覆盖 current / lastSuccess：页面继续展示上一次成功结果并给出提示。
      setState({
        selectedRegionId: region.id,
        pendingRegionId: null,
        phase: 'ready',
        failure: outcome.failure,
        lastSelection: 'failure'
      });
      return;
    }

    const result = outcome.result;
    if (result.status === 'available') {
      const withMode: AvailableDistributionResult = { ...result, collectionMode: mode === 'cache' ? 'cache' : 'network' };
      setState({
        selectedRegionId: region.id,
        pendingRegionId: null,
        phase: 'ready',
        current: withMode,
        lastSuccess: withMode,
        failure: null,
        lastSelection: mode
      });
      return;
    }

    // 不可用区域：显式清空数字来源，绝不保留其他区域的统计或显示 0 / NaN。
    setState({
      selectedRegionId: region.id,
      pendingRegionId: null,
      phase: 'ready',
      current: { ...result, collectionMode: mode === 'cache' ? 'cache' : 'network' },
      failure: null,
      lastSelection: mode
    });
  };

  const selectRegion = async (regionId: string): Promise<void> => {
    if (disposed) {
      return;
    }

    if (state.catalogStatus === 'idle') {
      await loadCatalog();
    }
    if (disposed || state.catalogStatus !== 'ready' || !state.datasetInfo) {
      return;
    }

    const region = state.catalog.find((entry) => entry.id === regionId);
    if (!region) {
      return;
    }

    // 推进令牌：任何更晚的选择都会让先前返回的结果失效。
    selectionToken += 1;
    const token = selectionToken;

    const cached = cache.get(region.id);
    const pending = inFlight.get(region.id);
    const mode = cached ? 'cache' : pending ? 'coalesced' : 'network';

    setState({
      selectedRegionId: region.id,
      pendingRegionId: mode === 'cache' ? null : region.id,
      phase: mode === 'cache' ? 'ready' : 'loading',
      lastSelection: mode,
      ...(mode === 'cache' ? { cacheHits: state.cacheHits + 1 } : {}),
      ...(mode === 'coalesced' ? { coalescedSelections: state.coalescedSelections + 1 } : {})
    });

    let outcome: CollectionOutcome;
    if (cached) {
      outcome = cached;
    } else if (pending) {
      outcome = await pending;
    } else {
      setState({ pendingRegionId: region.id, phase: 'loading', lastSelection: 'network' });
      if (disposed) {
        return;
      }
      outcome = await startCollection(region, state.datasetInfo);
    }

    if (disposed) {
      return;
    }

    if (token !== selectionToken) {
      // 快速切换产生的过期结果：只保留在缓存里，不覆盖当前页面。
      // 同一区域的重复点击会合并到同一次请求，不属于“过期结果”。
      if (state.selectedRegionId !== region.id) {
        setState({ staleResultsIgnored: state.staleResultsIgnored + 1 });
      }
      return;
    }

    applyOutcome(region, outcome, mode);
  };

  const dispose = (): void => {
    disposed = true;
    inFlight.clear();
    listeners.clear();
  };

  return {
    getState,
    subscribe,
    loadCatalog,
    selectRegion,
    dispose
  };
};
