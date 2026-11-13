/**
 * 客户分布采集链路的数据契约。
 *
 * 一次区域采集的结果必须同时携带：地图视图、统计数字、国家列表、
 * 来源标识与采集时间。页面只允许用同一个结果对象渲染地图、统计卡和国家标签。
 */

/** 地图视图，来源于本次采集结果，而不是另一份区域配置。 */
export interface RegionMapView {
  lat: number;
  lng: number;
  zoom: number;
  address: string;
}

/** 演示数据源目录中的区域项，用于渲染区域切换按钮。 */
export interface RegionCatalogEntry {
  id: string;
  name: string;
}

/**
 * 演示数据源目录（public/demo-data/customer-distribution/index.json）。
 * 各区域的具体数据在 regions/{regionId}.json 中，按区域单独抓取。
 */
export interface DemoCatalog {
  sourceId: string;
  sourceName: string;
  updatedAt: string;
  regions: RegionCatalogEntry[];
}

/** 数据源元信息，用于页面展示“来源”与“更新时间”。 */
export interface DemoDatasetInfo {
  sourceId: string;
  sourceName: string;
  updatedAt: string;
  /** 数据源位置（本地样例为 public 目录下的 URL）。 */
  location: string;
  regionCount: number;
}

/**
 * 单个区域的原始记录（regions/{regionId}.json）字段说明；
 * 实际校验入口见 validator.ts，非法字段不会被兜底成 0。
 */
export interface DemoCustomerDistributionRecord {
  regionId: string;
  regionName: string;
  map: RegionMapView;
  totalCustomers: number;
  activeCustomers: number;
  /** 百分比数值，例如 25 表示 +25%。 */
  growthRate: number;
  topCountries: string[];
  /** 该区域数据的采集时间，ISO-8601。 */
  collectedAt: string;
  /** 仅本地演示使用：填写后该区域采集会走“上游失败”分支。 */
  simulateCollectionFailure?: string;
}

/** 数据源抽象：HTTP 演示源与本地文件验收源都实现该接口。 */
export interface CustomerDistributionDataSource {
  /** 数据源位置说明，写入采集结果并在页面展示。 */
  location: string;
  loadCatalog(): Promise<unknown>;
  loadRegionRecord(regionId: string): Promise<unknown>;
}

export type CollectionMode = 'network' | 'cache';

/** 采集成功且校验通过的结果。地图、统计、国家标签必须全部来自此对象。 */
export interface AvailableDistributionResult {
  status: 'available';
  regionId: string;
  regionName: string;
  map: RegionMapView;
  totalCustomers: number;
  activeCustomers: number;
  growthRate: number;
  topCountries: string[];
  sourceId: string;
  /** 数据源声明的该区域采集时间。 */
  collectedAt: string;
  /** 本页面实际拿到该结果的时间（缓存复用时保留首次抓取时间）。 */
  fetchedAt: string;
  collectionMode: CollectionMode;
}

/**
 * 区域数据不可用（记录缺失、字段缺失或数值非法）。
 * 不携带任何统计数字，避免页面显示 0 / NaN 或静默沿用其他区域数据。
 */
export interface UnavailableDistributionResult {
  status: 'unavailable';
  regionId: string;
  regionName: string;
  sourceId: string;
  datasetUpdatedAt: string;
  reasons: string[];
  fetchedAt: string;
  collectionMode: CollectionMode;
}

export type DistributionResult = AvailableDistributionResult | UnavailableDistributionResult;

/** 采集请求本身失败（网络错误、数据源不可读、演示失败分支等）。 */
export interface CollectionFailure {
  regionId: string;
  regionName: string;
  reason: string;
  at: string;
}

export type CatalogStatus = 'idle' | 'loading' | 'ready' | 'error';
export type CollectionPhase = 'idle' | 'loading' | 'ready';

/**
 * 本次选择的结果来源：
 * - network 实际发起采集请求
 * - cache 缓存命中（含同一区域重复点击、切回已采集区域）
 * - coalesced 同一区域请求进行中，合并到已有请求
 * - failure 本次采集失败，页面展示上一次成功结果
 */
export type SelectionMode = 'none' | 'network' | 'cache' | 'coalesced' | 'failure';

/** 控制器对外暴露的完整状态；React 页面通过 useSyncExternalStore 订阅。 */
export interface CustomerDistributionState {
  catalog: RegionCatalogEntry[];
  catalogStatus: CatalogStatus;
  catalogError: string | null;
  datasetInfo: DemoDatasetInfo | null;
  selectedRegionId: string | null;
  /** 正在采集的区域；仅在 phase === 'loading' 时有值。 */
  pendingRegionId: string | null;
  phase: CollectionPhase;
  /** 最近一次完成的采集结果（成功或不可用）。 */
  current: DistributionResult | null;
  /** 最近一次成功展示的结果；采集失败时页面继续展示它。 */
  lastSuccess: AvailableDistributionResult | null;
  /** 最近一次网络/数据源失败；仅保留，不覆盖 current/lastSuccess。 */
  failure: CollectionFailure | null;
  /** 真正发起的采集请求次数（缓存命中与请求去重不增加）。 */
  requestCount: number;
  /** 缓存命中次数（同一区域重复点击、切回已采集区域）。 */
  cacheHits: number;
  /** 合并到进行中请求的次数（采集未完成时重复点击同一区域）。 */
  coalescedSelections: number;
  lastSelection: SelectionMode;
  /** 因快速切换而被丢弃的过期结果数量。 */
  staleResultsIgnored: number;
}

export interface CustomerDistributionControllerOptions {
  /** 目录加载完成后是否自动选中第一个区域（页面使用，便于演示）。 */
  autoSelectFirstRegion?: boolean;
  /** 最小采集耗时，默认 450ms，让加载态在本地样例上可见。 */
  minLatencyMs?: number;
  /** 时间来源，默认 Date.now；验收脚本可注入固定时钟。 */
  now?: () => number;
  /** 等待实现，默认 setTimeout；验收脚本可注入无延迟实现。 */
  sleep?: (ms: number) => Promise<void>;
}
