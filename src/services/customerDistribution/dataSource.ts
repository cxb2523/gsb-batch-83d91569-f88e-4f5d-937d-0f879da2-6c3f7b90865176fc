import type {
  CustomerDistributionDataSource,
  DemoDatasetInfo,
  RegionCatalogEntry
} from './types.ts';

/** 浏览器内演示数据源：从 public 目录按区域逐个抓取 JSON。 */
export const createHttpDataSource = (
  baseUrl: string,
  fetchImpl: typeof fetch
): CustomerDistributionDataSource => {
  const trimmedBase = baseUrl.replace(/\/+$/, '');

  const getJson = async (url: string): Promise<unknown> => {
    const response = await fetchImpl(url, {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });

    if (!response.ok) {
      throw new Error(`请求 ${url} 失败（HTTP ${response.status}）`);
    }

    const text = await response.text();
    try {
      return JSON.parse(text) as unknown;
    } catch {
      throw new Error(`${url} 返回的内容不是合法 JSON`);
    }
  };

  return {
    location: trimmedBase,
    loadCatalog: () => getJson(`${trimmedBase}/index.json`),
    loadRegionRecord: (regionId) =>
      getJson(`${trimmedBase}/regions/${encodeURIComponent(regionId)}.json`)
  };
};

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/** 解析并校验数据源目录，返回区域列表与展示用元信息。 */
export const parseCatalog = (
  raw: unknown,
  location: string
): { regions: RegionCatalogEntry[]; info: DemoDatasetInfo } => {
  if (!isPlainObject(raw)) {
    throw new Error('数据源目录不是 JSON 对象');
  }

  const { sourceId, sourceName, updatedAt, regions } = raw;

  if (typeof sourceId !== 'string' || sourceId.trim() === '') {
    throw new Error('数据源目录缺少 sourceId');
  }
  if (typeof sourceName !== 'string' || sourceName.trim() === '') {
    throw new Error('数据源目录缺少 sourceName');
  }
  if (typeof updatedAt !== 'string' || Number.isNaN(new Date(updatedAt).getTime())) {
    throw new Error('数据源目录缺少有效的 updatedAt');
  }
  if (!Array.isArray(regions) || regions.length === 0) {
    throw new Error('数据源目录缺少 regions 数组');
  }

  const seen = new Set<string>();
  const parsedRegions = (regions as unknown[]).map((entry, index) => {
    if (!isPlainObject(entry)) {
      throw new Error(`regions[${index}] 不是对象`);
    }
    const { id, name } = entry;
    if (typeof id !== 'string' || id.trim() === '') {
      throw new Error(`regions[${index}] 缺少 id`);
    }
    if (typeof name !== 'string' || name.trim() === '') {
      throw new Error(`regions[${index}] 缺少 name`);
    }
    if (seen.has(id)) {
      throw new Error(`regions 中 id 重复：${id}`);
    }
    seen.add(id);
    return { id, name };
  });

  return {
    regions: parsedRegions,
    info: {
      sourceId,
      sourceName,
      updatedAt,
      location,
      regionCount: parsedRegions.length
    }
  };
};
