import type { RegionMapView } from './types.ts';

/** 单条原始记录通过校验后的规范形态。 */
export interface ValidatedRecord {
  regionId: string;
  regionName: string;
  map: RegionMapView;
  totalCustomers: number;
  activeCustomers: number;
  growthRate: number;
  topCountries: string[];
  collectedAt: string;
  simulateCollectionFailure?: string;
}

/**
 * 校验结果使用字符串判别字段：项目 `tsconfig.check.json` 以非 strict 模式检查，
 * 布尔判别字段在该模式下无法收窄联合类型，会造成页面误读字段。
 */
export type ValidationOutcome =
  | { status: 'valid'; record: ValidatedRecord }
  | { status: 'invalid'; reasons: string[] };

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const isNonEmptyString = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0;

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

/** ISO-8601，且解析结果有效（拒绝 '2025-13-45' 这类被 Date 宽松接受的字符串）。 */
const isIsoDateString = (value: unknown): value is string => {
  if (typeof value !== 'string' || value.trim().length === 0) {
    return false;
  }
  const parsed = new Date(value);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().startsWith(value.slice(0, 4));
};

/**
 * 校验一条区域记录。
 *
 * 缺字段、类型错误、数值非法（NaN/Infinity/负数/非整数/活跃客户超过总数）都会被
 * 收集为 reasons 并整体判为不可用；绝不把非法值兜底成 0。
 */
export const validateRecord = (
  raw: unknown,
  expectedRegionId: string,
  expectedRegionName: string
): ValidationOutcome => {
  const reasons: string[] = [];

  if (!isPlainObject(raw)) {
    return { status: 'invalid', reasons: [`区域「${expectedRegionName}」缺少采集记录或记录不是对象`] };
  }

  if (!isNonEmptyString(raw.regionId)) {
    reasons.push('regionId 缺失或不是非空字符串');
  } else if (raw.regionId !== expectedRegionId) {
    reasons.push(`regionId 与目录不一致（期望 ${expectedRegionId}，实际 ${raw.regionId}）`);
  }

  if (!isNonEmptyString(raw.regionName)) {
    reasons.push('regionName 缺失或不是非空字符串');
  } else if (raw.regionName !== expectedRegionName) {
    reasons.push(`regionName 与目录不一致（期望 ${expectedRegionName}，实际 ${raw.regionName}）`);
  }

  const map = raw.map;
  let mapView: RegionMapView | null = null;
  if (!isPlainObject(map)) {
    reasons.push('map 缺失或不是对象');
  } else {
    const latOk = isFiniteNumber(map.lat) && map.lat >= -90 && map.lat <= 90;
    const lngOk = isFiniteNumber(map.lng) && map.lng >= -180 && map.lng <= 180;
    const zoomOk = isFiniteNumber(map.zoom) && map.zoom >= 1 && map.zoom <= 22;
    const addressOk = isNonEmptyString(map.address);

    if (!latOk) reasons.push('map.lat 缺失或不在 [-90, 90] 内');
    if (!lngOk) reasons.push('map.lng 缺失或不在 [-180, 180] 内');
    if (!zoomOk) reasons.push('map.zoom 缺失或不在 [1, 22] 内');
    if (!addressOk) reasons.push('map.address 缺失或不是非空字符串');

    if (latOk && lngOk && zoomOk && addressOk) {
      mapView = {
        lat: map.lat as number,
        lng: map.lng as number,
        zoom: map.zoom as number,
        address: map.address as string
      };
    }
  }

  const totalOk = isFiniteNumber(raw.totalCustomers)
    && Number.isInteger(raw.totalCustomers)
    && raw.totalCustomers >= 0;
  if (!totalOk) reasons.push('totalCustomers 缺失或不是非负整数');

  const activeOk = isFiniteNumber(raw.activeCustomers)
    && Number.isInteger(raw.activeCustomers)
    && raw.activeCustomers >= 0;
  if (!activeOk) reasons.push('activeCustomers 缺失或不是非负整数');

  if (totalOk && activeOk && (raw.activeCustomers as number) > (raw.totalCustomers as number)) {
    reasons.push('activeCustomers 大于 totalCustomers');
  }

  const growthOk = isFiniteNumber(raw.growthRate) && raw.growthRate >= -100 && raw.growthRate <= 1000;
  if (!growthOk) reasons.push('growthRate 缺失或不是 [-100, 1000] 内的有限数值');

  let countries: string[] | null = null;
  if (!Array.isArray(raw.topCountries) || raw.topCountries.length === 0) {
    reasons.push('topCountries 缺失或不是非空数组');
  } else if (!raw.topCountries.every(isNonEmptyString)) {
    reasons.push('topCountries 含有空值或非字符串项');
  } else {
    countries = [...new Set(raw.topCountries.map((item) => (item as string).trim()))];
  }

  if (!isIsoDateString(raw.collectedAt)) {
    reasons.push('collectedAt 缺失或不是有效的 ISO-8601 时间');
  }

  if (
    raw.simulateCollectionFailure !== undefined
    && !isNonEmptyString(raw.simulateCollectionFailure)
  ) {
    reasons.push('simulateCollectionFailure 若存在必须是非空字符串');
  }

  if (reasons.length > 0 || !mapView || !countries) {
    return { status: 'invalid', reasons };
  }

  return {
    status: 'valid',
    record: {
      regionId: raw.regionId as string,
      regionName: raw.regionName as string,
      map: mapView,
      totalCustomers: raw.totalCustomers as number,
      activeCustomers: raw.activeCustomers as number,
      growthRate: raw.growthRate as number,
      topCountries: countries,
      collectedAt: raw.collectedAt as string,
      ...(isNonEmptyString(raw.simulateCollectionFailure)
        ? { simulateCollectionFailure: raw.simulateCollectionFailure }
        : {})
    }
  };
};
