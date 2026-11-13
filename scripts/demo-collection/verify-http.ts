/**
 * HTTP 数据源端到端验收（可选）。
 *
 * 前置：另开终端运行 `pnpm dev`（默认 5173）或指定 URL：
 *   node scripts/demo-collection/verify-http.ts http://localhost:5173
 *
 * 验证页面实际使用的 createHttpDataSource 能按区域抓取 public 下的样例文件，
 * 并确认控制器在 HTTP 数据源下同样满足“同区域不重复请求 / 非法区域不可用”。
 */
import { createCustomerDistributionController } from '../../src/services/customerDistribution/controller.ts';
import { createHttpDataSource } from '../../src/services/customerDistribution/dataSource.ts';
import { buildAuditView, buildDistributionView } from '../../src/services/customerDistribution/viewModel.ts';

const origin = (process.argv[2] ?? 'http://localhost:5173').replace(/\/+$/, '');
const baseUrl = `${origin}/demo-data/customer-distribution`;

let failures = 0;
const check = (name: string, condition: boolean, detail?: unknown): void => {
  if (condition) {
    console.log(`  PASS  ${name}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${name}`);
    if (detail !== undefined) {
      console.log(`        ${JSON.stringify(detail)}`);
    }
  }
};

const main = async (): Promise<void> => {
  console.log(`数据源：${baseUrl}\n`);

  const controller = createCustomerDistributionController(
    createHttpDataSource(baseUrl, fetch),
    { minLatencyMs: 0, sleep: async () => {} }
  );

  await controller.loadCatalog();
  let state = controller.getState();
  check('HTTP 目录加载成功', state.catalogStatus === 'ready', state.catalogError);
  check('目录来源标识正确', state.datasetInfo?.sourceId === 'demo-customer-distribution', state.datasetInfo);

  await controller.selectRegion('asia');
  state = controller.getState();
  const view = buildDistributionView(state);
  check('HTTP 采集 asia 成功', view.kind === 'available', view);
  if (view.kind === 'available') {
    check('asia 地图中心 35/105', view.map.lat === 35 && view.map.lng === 105, view.map);
    check('asia 统计来自采集结果', view.stats[0].value === '18,640', view.stats);
    check('asia 国家标签完整', view.countries.length === 5 && view.countries[0] === '中国', view.countries);
  }

  const requestsBefore = controller.getState().requestCount;
  await controller.selectRegion('asia');
  check('HTTP 重复点击不重复请求', controller.getState().requestCount === requestsBefore, controller.getState().requestCount);

  await controller.selectRegion('america');
  state = controller.getState();
  const badView = buildDistributionView(state);
  check('HTTP 非法区域标记不可用', badView.kind === 'unavailable', badView);
  check('HTTP 非法区域不出现占位数字', state.current?.status === 'unavailable' && !('totalCustomers' in (state.current ?? {})), state.current);

  await controller.selectRegion('africa');
  const failureView = buildDistributionView(controller.getState());
  check('HTTP 演示失败区域保留上一次结果', failureView.kind === 'failure' && failureView.retained?.regionId === 'asia', failureView);

  const audit = buildAuditView(controller.getState());
  console.log(`\n请求数=${audit.requestCount} 缓存命中=${audit.cacheHits} 合并=${audit.coalescedSelections}`);

  controller.dispose();
  console.log(failures === 0 ? '\nHTTP 验收全部通过 ✅' : `\nHTTP 验收有 ${failures} 项失败 ❌`);
  process.exitCode = failures === 0 ? 0 : 1;
};

main().catch((error) => {
  console.error('HTTP 验收异常（请确认开发服务器已启动）：', error);
  process.exitCode = 1;
});
