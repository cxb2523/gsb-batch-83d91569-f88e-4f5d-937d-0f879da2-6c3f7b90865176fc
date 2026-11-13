import { readFile } from 'node:fs/promises';
import path from 'node:path';
import type { CustomerDistributionDataSource } from '../src/services/customerDistribution/types.ts';

/**
 * 验收用数据源：直接读取仓库内 public/demo-data/customer-distribution 下的文件，
 * 与浏览器端 HTTP 数据源读取同一份样例，保证验收结论对应页面实际数据。
 */
export const createFileDataSource = (datasetDir: string): CustomerDistributionDataSource => ({
  location: datasetDir,
  loadCatalog: async () => {
    const file = path.join(datasetDir, 'index.json');
    return JSON.parse(await readFile(file, 'utf8')) as unknown;
  },
  loadRegionRecord: async (regionId) => {
    const file = path.join(datasetDir, 'regions', `${regionId}.json`);
    return JSON.parse(await readFile(file, 'utf8')) as unknown;
  }
});
