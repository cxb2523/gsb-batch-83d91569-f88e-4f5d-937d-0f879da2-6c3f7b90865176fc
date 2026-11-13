import { useEffect, useMemo, useRef, useSyncExternalStore } from 'react';
import { createCustomerDistributionController } from './controller';
import { createHttpDataSource } from './dataSource';
import type { CustomerDistributionState } from './types';

/** 本地演示数据源位置：public/demo-data/customer-distribution。 */
const DEFAULT_DATASET_PATH = 'demo-data/customer-distribution';

const resolveDatasetUrl = (): string => {
  const configured = import.meta.env.VITE_DEMO_DATA_URL as string | undefined;
  if (configured && configured.trim() !== '') {
    return configured.replace(/\/+$/, '');
  }
  const base = import.meta.env.BASE_URL || '/';
  return `${base.replace(/\/+$/, '')}/${DEFAULT_DATASET_PATH}`;
};

const serverSnapshot: CustomerDistributionState = {
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
};

export interface UseCustomerDistributionResult {
  state: CustomerDistributionState;
  selectRegion: (regionId: string) => void;
  retryCatalog: () => void;
  datasetUrl: string;
}

/**
 * 演示页使用的采集 Hook。
 * 控制器在组件生命周期内保持单例，因此“重复点击/快速切换”的去重与最新优先
 * 逻辑不会被 React 重新渲染打断。
 */
export const useCustomerDistribution = (): UseCustomerDistributionResult => {
  const datasetUrl = useMemo(resolveDatasetUrl, []);

  const controller = useMemo(
    () =>
      createCustomerDistributionController(
        createHttpDataSource(datasetUrl, (input, init) => fetch(input, init)),
        { autoSelectFirstRegion: true }
      ),
    [datasetUrl]
  );

  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getState,
    () => serverSnapshot
  );

  const startedRef = useRef(false);
  useEffect(() => {
    if (startedRef.current) {
      return;
    }
    startedRef.current = true;
    void controller.loadCatalog();
    // 不在此处 dispose：StrictMode 会执行一次“挂载→卸载→再挂载”，
    // 提前销毁控制器会让页面之后无法再采集。控制器生命周期与页面一致，
    // useSyncExternalStore 会自动取消订阅。
  }, [controller]);

  const selectRegion = (regionId: string): void => {
    void controller.selectRegion(regionId);
  };

  const retryCatalog = (): void => {
    void controller.loadCatalog();
  };

  return { state, selectRegion, retryCatalog, datasetUrl };
};
