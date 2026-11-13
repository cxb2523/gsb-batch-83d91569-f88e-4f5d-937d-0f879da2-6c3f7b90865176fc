/**
 * 本地样例验收脚本。
 *
 * 运行：node scripts/demo-collection/verify.ts
 *
 * 覆盖：
 * 1. 正常切换：地图中心、统计卡、国家标签全部来自同一次采集结果
 * 2. 非法区域：字段缺失/数值非法 → unavailable，不出现 0 / NaN
 * 3. 重复点击：同一区域不重复请求（缓存命中 / 请求合并）
 * 4. 快速切换：只保留最后一次选择对应的结果
 * 5. 采集失败：保留上一次成功结果并给出可见原因
 */
import path from 'node:path';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { createCustomerDistributionController } from '../../src/services/customerDistribution/controller.ts';
import { validateRecord } from '../../src/services/customerDistribution/validator.ts';
import { buildAuditView, buildDistributionView } from '../../src/services/customerDistribution/viewModel.ts';
import { createFileDataSource } from './fsDataSource.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const datasetDir = path.resolve(here, '../../public/demo-data/customer-distribution');

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

const makeController = () =>
  createCustomerDistributionController(createFileDataSource(datasetDir), {
    // 验收脚本无需真实等待；页面默认 450ms 的加载态由控制器默认值提供。
    minLatencyMs: 0,
    sleep: async () => {}
  });

const main = async (): Promise<void> => {
  const controller = makeController();
  await controller.loadCatalog();

  let state = controller.getState();
  check('目录加载成功', state.catalogStatus === 'ready', state.catalogError);
  check(
    '目录包含 5 个区域（含非法/失败样例）',
    state.catalog.length === 5,
    state.catalog.map((item) => item.id)
  );
  check('展示数据源标识', state.datasetInfo?.sourceId === 'demo-customer-distribution', state.datasetInfo);

  console.log('\n[1] 正常切换：地图/统计/国家同源');
  for (const regionId of ['global', 'asia', 'europe']) {
    await controller.selectRegion(regionId);
    state = controller.getState();
    const view = buildDistributionView(state);
    const result = state.current;
    const source = JSON.parse(
      await readFile(path.join(datasetDir, 'regions', `${regionId}.json`), 'utf8')
    ) as Record<string, unknown>;

    check(`${regionId}: 结果为 available`, view.kind === 'available', view);
    if (view.kind !== 'available' || result?.status !== 'available') {
      continue;
    }

    const map = source.map as { lat: number; lng: number; zoom: number; address: string };
    check(`${regionId}: 地图中心来自本次结果`, view.map.lat === map.lat && view.map.lng === map.lng && view.map.zoom === map.zoom, view.map);
    check(`${regionId}: 地图地址来自本次结果`, view.map.address === map.address, view.map);
    check(
      `${regionId}: 总客户数来自本次结果`,
      view.stats[0].value === (source.totalCustomers as number).toLocaleString('en-US'),
      view.stats
    );
    check(
      `${regionId}: 活跃客户来自本次结果`,
      view.stats[1].value === (source.activeCustomers as number).toLocaleString('en-US'),
      view.stats
    );
    check(
      `${regionId}: 增长率来自本次结果`,
      view.stats[2].value === `+${(source.growthRate as number).toFixed(1)}%`,
      view.stats
    );
    check(
      `${regionId}: 国家标签来自本次结果`,
      JSON.stringify(view.countries) === JSON.stringify(source.topCountries),
      view.countries
    );
    check(`${regionId}: 结果携带采集时间`, view.collectedAtLabel !== '未知', view.collectedAtLabel);
    check(`${regionId}: 结果携带来源标识`, view.sourceLabel.includes('demo-customer-distribution'), view.sourceLabel);
  }

  console.log('\n[2] 非法区域（america 缺 activeCustomers、growthRate 为字符串）');
  await controller.selectRegion('america');
  state = controller.getState();
  const unavailableView = buildDistributionView(state);
  check('america 标记为 unavailable', unavailableView.kind === 'unavailable', unavailableView);
  if (unavailableView.kind === 'unavailable') {
    check(
      '原因包含 activeCustomers 缺失',
      unavailableView.reasons.some((reason) => reason.includes('activeCustomers')),
      unavailableView.reasons
    );
    check(
      '原因包含 growthRate 非法',
      unavailableView.reasons.some((reason) => reason.includes('growthRate')),
      unavailableView.reasons
    );
    check(
      '不可用区域不渲染地图/统计/国家',
      !('map' in unavailableView) && !('stats' in unavailableView) && !('countries' in unavailableView),
      Object.keys(unavailableView)
    );
    check(
      '不可用视图不含 NaN',
      !JSON.stringify(unavailableView).includes('NaN'),
      unavailableView.reasons
    );
  }
  check('不可用结果不携带统计数字', state.current?.status === 'unavailable' && !('totalCustomers' in (state.current ?? {})), state.current);

  // 额外：NaN / Infinity 直接出现在原始 JSON 中不可行，改为校验负数与字符串数字两类非法值。
  const negativeCases: Array<{ name: string; record: unknown; expect: string }> = [
    {
      name: 'totalCustomers 为负数',
      expect: 'totalCustomers',
      record: {
        regionId: 'x', regionName: 'X', map: { lat: 0, lng: 0, zoom: 3, address: 'A' },
        totalCustomers: -1, activeCustomers: 0, growthRate: 1, topCountries: ['a'],
        collectedAt: '2026-11-10T00:00:00.000Z'
      }
    },
    {
      name: 'totalCustomers 为字符串数字',
      expect: 'totalCustomers',
      record: {
        regionId: 'x', regionName: 'X', map: { lat: 0, lng: 0, zoom: 3, address: 'A' },
        totalCustomers: '1200', activeCustomers: 1, growthRate: 1, topCountries: ['a'],
        collectedAt: '2026-11-10T00:00:00.000Z'
      }
    },
    {
      name: 'activeCustomers 大于 totalCustomers',
      expect: 'activeCustomers',
      record: {
        regionId: 'x', regionName: 'X', map: { lat: 0, lng: 0, zoom: 3, address: 'A' },
        totalCustomers: 10, activeCustomers: 11, growthRate: 1, topCountries: ['a'],
        collectedAt: '2026-11-10T00:00:00.000Z'
      }
    },
    {
      name: 'map 缺失',
      expect: 'map',
      record: {
        regionId: 'x', regionName: 'X',
        totalCustomers: 10, activeCustomers: 5, growthRate: 1, topCountries: ['a'],
        collectedAt: '2026-11-10T00:00:00.000Z'
      }
    }
  ];
  for (const item of negativeCases) {
    const outcome = validateRecord(item.record, 'x', 'X');
    check(
      `非法规格：${item.name} 被拒绝`,
      outcome.status === 'invalid' && outcome.reasons.some((reason) => reason.includes(item.expect)),
      outcome
    );
  }

  console.log('\n[3] 重复点击不重复请求');
  const beforeRepeat = controller.getState();
  await controller.selectRegion('asia');
  const afterFirstRepeat = controller.getState();
  check(
    '已采集区域重复点击命中缓存',
    afterFirstRepeat.lastSelection === 'cache' && afterFirstRepeat.requestCount === beforeRepeat.requestCount,
    { lastSelection: afterFirstRepeat.lastSelection, before: beforeRepeat.requestCount, after: afterFirstRepeat.requestCount }
  );
  await controller.selectRegion('asia');
  check(
    '连续重复点击仍不增加请求数',
    controller.getState().requestCount === beforeRepeat.requestCount,
    controller.getState().requestCount
  );

  console.log('\n[4] 快速切换只保留最后一次选择');
  const rapidController = makeController();
  await rapidController.loadCatalog();
  const p1 = rapidController.selectRegion('europe');
  const p2 = rapidController.selectRegion('asia');
  const p3 = rapidController.selectRegion('global');
  await Promise.all([p1, p2, p3]);
  const rapidState = rapidController.getState();
  const rapidView = buildDistributionView(rapidState);
  check(
    '最终展示区域为最后一次点击的 global',
    rapidState.selectedRegionId === 'global' && rapidView.kind === 'available' && rapidView.regionId === 'global',
    { selected: rapidState.selectedRegionId, view: rapidView.kind }
  );
  check(
    '最终统计/地图属于 global',
    rapidView.kind === 'available' && rapidView.stats[0].value === '52,780' && rapidView.map.lat === 20,
    rapidView
  );
  check(
    '存在被丢弃的过期结果',
    rapidState.staleResultsIgnored >= 1,
    rapidState.staleResultsIgnored
  );
  check(
    '快速切换按区域各请求一次（新控制器从 0 起算）',
    rapidState.requestCount === 3,
    rapidState.requestCount
  );

  console.log('\n[4b] 采集进行中重复点击同一区域 → 请求合并');
  const slowController = createCustomerDistributionController(createFileDataSource(datasetDir), {
    minLatencyMs: 60
  });
  await slowController.loadCatalog();
  const slow1 = slowController.selectRegion('europe');
  const slow2 = slowController.selectRegion('europe');
  await Promise.all([slow1, slow2]);
  const slowState = slowController.getState();
  check('同一区域并发点击只发起一次请求', slowState.requestCount === 1, slowState.requestCount);
  check('第二次点击被记为请求合并', slowState.coalescedSelections === 1, slowState.coalescedSelections);
  check(
    '合并后展示 europe 且未重复请求',
    slowState.lastSuccess?.regionId === 'europe' && slowState.phase === 'ready',
    { region: slowState.lastSuccess?.regionId, phase: slowState.phase }
  );
  slowController.dispose();

  console.log('\n[5] 采集失败保留上一次成功结果');
  await controller.selectRegion('europe');
  const successBeforeFailure = controller.getState().lastSuccess;
  await controller.selectRegion('africa');
  state = controller.getState();
  const failureView = buildDistributionView(state);
  check('africa 触发采集失败', failureView.kind === 'failure', failureView);
  if (failureView.kind === 'failure') {
    check('失败原因可见', failureView.reason.includes('429'), failureView.reason);
    check(
      '保留上一次成功结果（europe）',
      failureView.retained?.regionId === 'europe' && successBeforeFailure?.regionId === 'europe',
      failureView.retained?.regionId
    );
  }
  check(
    '失败后 current 未被写死数字覆盖',
    state.current?.regionId === 'europe' && state.lastSuccess?.regionId === 'europe',
    { current: state.current?.regionId, lastSuccess: state.lastSuccess?.regionId }
  );

  console.log('\n[6] 审计信息');
  const audit = buildAuditView(controller.getState());
  console.log(`  请求数=${audit.requestCount} 缓存命中=${audit.cacheHits} 合并=${audit.coalescedSelections} 过期丢弃=${audit.staleResultsIgnored}`);

  controller.dispose();
  rapidController.dispose();

  console.log(failures === 0 ? '\n全部验收项通过 ✅' : `\n有 ${failures} 个验收项失败 ❌`);
  process.exitCode = failures === 0 ? 0 : 1;
};

main().catch((error) => {
  console.error('验收脚本异常：', error);
  process.exitCode = 1;
});
