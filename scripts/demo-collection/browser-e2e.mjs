/**
 * 浏览器端验收（需要本机 Chrome / Edge）。
 *
 * 前置：先启动开发服务器（`pnpm dev`，默认 5173）。
 * 运行：
 *   node scripts/demo-collection/browser-e2e.mjs [url]
 *
 * 脚本会启动一个临时无头浏览器，通过 DevTools 协议点击“在线演示”页的区域按钮，
 * 校验地图中心、统计卡、国家标签是否始终来自同一次采集结果，并覆盖：
 * 正常切换、加载态、重复点击、非法区域、快速切换、采集失败保留上一次结果。
 */
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const targetUrl = process.argv[2] ?? 'http://localhost:5173/demo';
const port = 9333;

const chromeCandidates = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium'
].filter(Boolean);

const chromePath = chromeCandidates.find((candidate) => existsSync(candidate));
if (!chromePath) {
  console.error('未找到 Chrome/Edge，请通过 CHROME_PATH 环境变量指定浏览器路径。');
  process.exit(2);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (name, condition, detail) => {
  if (condition) {
    console.log(`  PASS  ${name}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${name}${detail === undefined ? '' : `\n        ${JSON.stringify(detail)}`}`);
  }
};

const profileDir = await mkdtemp(path.join(os.tmpdir(), 'demo-e2e-'));
const chrome = spawn(
  chromePath,
  [
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profileDir}`,
    'about:blank'
  ],
  { stdio: 'ignore' }
);

const waitForDevtools = async () => {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (response.ok) {
        return;
      }
    } catch {
      // Chrome 尚未就绪
    }
    await sleep(250);
  }
  throw new Error('等待浏览器 DevTools 超时');
};

const cleanup = async () => {
  chrome.kill();
  await sleep(300);
  await rm(profileDir, { recursive: true, force: true }).catch(() => {});
};

try {
  await waitForDevtools();

  const opened = await fetch(
    `http://127.0.0.1:${port}/json/new?${encodeURIComponent(targetUrl)}`,
    { method: 'PUT' }
  ).then((response) => response.json());

  const ws = new WebSocket(opened.webSocketDebuggerUrl);
  let messageId = 0;
  const pending = new Map();
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  };
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  const send = (method, params = {}) =>
    new Promise((resolve) => {
      const id = (messageId += 1);
      pending.set(id, resolve);
      ws.send(JSON.stringify({ id, method, params }));
    });

  const evaluate = async (expression) => {
    const response = await send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true
    });
    if (response.result.exceptionDetails) {
      return { __exception: response.result.exceptionDetails.exception?.description };
    }
    return response.result.result.value;
  };

  await send('Runtime.enable');
  await send('Page.enable');

  const reload = async () => {
    await send('Page.reload', { ignoreCache: true });
    await sleep(2500);
  };

  const clickRegion = (regionId) =>
    evaluate(`document.querySelector('[data-testid="region-button-${regionId}"]')?.click()`);

  const snapshot = () =>
    evaluate(`(() => {
      const query = (selector) => document.querySelector(selector);
      const text = (selector) => query(selector)?.textContent?.replace(/\\s+/g, ' ').trim() ?? null;
      const map = query('[data-testid="region-map"]');
      const stats = query('[data-testid="region-stats"]');
      const countries = query('[data-testid="region-countries"]');
      const audit = query('[data-testid="collection-audit-strip"]');
      const unavailable = query('[data-testid="region-unavailable"]');
      const failure = query('[data-testid="collection-failure"]');
      return {
        mapRegion: map?.getAttribute('data-region-id') ?? null,
        mapLat: map?.getAttribute('data-lat') ?? null,
        mapLng: map?.getAttribute('data-lng') ?? null,
        statsRegion: stats?.getAttribute('data-region-id') ?? null,
        total: text('[data-testid="stat-value-totalCustomers"]'),
        active: text('[data-testid="stat-value-activeCustomers"]'),
        growth: text('[data-testid="stat-value-growthRate"]'),
        coverage: text('[data-testid="stat-value-coverage"]'),
        countriesRegion: countries?.getAttribute('data-region-id') ?? null,
        countries: [...document.querySelectorAll('[data-testid="region-countries"] span')].map((node) => node.textContent.trim()),
        unavailable: unavailable !== null,
        unavailableText: unavailable?.textContent?.replace(/\\s+/g, ' ').trim().slice(0, 260) ?? null,
        failure: failure !== null,
        failureText: failure?.textContent?.replace(/\\s+/g, ' ').trim().slice(0, 260) ?? null,
        loading: query('[aria-busy="true"]') !== null,
        requests: audit?.getAttribute('data-request-count') ?? null,
        cacheHits: audit?.getAttribute('data-cache-hits') ?? null,
        stale: audit?.getAttribute('data-stale-ignored') ?? null,
        provenance: text('[data-testid="region-provenance"]'),
        mapPanels: document.querySelectorAll('[data-testid="region-map"]').length,
        statPanels: document.querySelectorAll('[data-testid="region-stats"]').length,
        countryPanels: document.querySelectorAll('[data-testid="region-countries"]').length,
        bodyHasNaN: document.body.innerText.includes('NaN')
      };
    })()`);

  console.log(`目标页面：${targetUrl}\n`);
  await reload();

  console.log('[1] 初始加载（自动选中 global）');
  let state = await snapshot();
  check('地图/统计/国家三处同源为 global', state.mapRegion === 'global' && state.statsRegion === 'global' && state.countriesRegion === 'global', state);
  check('地图中心 20/0 来自采集结果', state.mapLat === '20' && state.mapLng === '0', state);
  check('统计卡 52,780 / 36,120 / +25.4% / 5', state.total === '52,780' && state.active === '36,120' && state.growth === '+25.4%' && state.coverage === '5', state);
  check('国家标签 5 个', state.countries.length === 5, state.countries);
  check('展示来源标识与采集时间', state.provenance?.includes('demo-customer-distribution') && state.provenance?.includes('本次网络采集结果'), state.provenance);
  check('初始请求数 1', state.requests === '1', state.requests);

  console.log('\n[2] 正常切换 + 加载态');
  await clickRegion('asia');
  await sleep(120);
  const mid = await snapshot();
  check('采集期间显示加载态', mid.loading === true, mid);
  check('加载期间不展示旧区域地图/数字', mid.mapPanels === 0 && mid.statPanels === 0 && mid.countryPanels === 0, mid);
  await sleep(900);
  state = await snapshot();
  check('asia 三处同源', state.mapRegion === 'asia' && state.statsRegion === 'asia' && state.countriesRegion === 'asia', state);
  check('asia 地图中心 35/105', state.mapLat === '35' && state.mapLng === '105', state);
  check('asia 统计 18,640 / 12,730 / +34.8%', state.total === '18,640' && state.active === '12,730' && state.growth === '+34.8%', state);
  check('asia 国家标签', state.countries.join('|') === '中国|日本|韩国|新加坡|印度', state.countries);
  check('asia 请求数 2', state.requests === '2', state.requests);

  console.log('\n[3] 重复点击同一区域');
  await clickRegion('asia');
  await sleep(250);
  await clickRegion('asia');
  await sleep(250);
  state = await snapshot();
  check('重复点击不新增请求', state.requests === '2', state.requests);
  check('缓存命中 2 次', state.cacheHits === '2', state.cacheHits);
  check('标注缓存复用结果', state.provenance?.includes('缓存复用结果'), state.provenance);

  console.log('\n[4] 非法区域（america）');
  await clickRegion('america');
  await sleep(900);
  state = await snapshot();
  check('整块标记不可用', state.unavailable === true, state);
  check('原因包含 activeCustomers 与 growthRate', /activeCustomers/.test(state.unavailableText ?? '') && /growthRate/.test(state.unavailableText ?? ''), state.unavailableText);
  check('不可用时不渲染地图/统计/国家', state.mapPanels === 0 && state.statPanels === 0 && state.countryPanels === 0, state);
  check('页面无 NaN', state.bodyHasNaN === false, state);
  check('america 是新的一次采集请求', state.requests === '3', state.requests);

  console.log('\n[5] 快速切换');
  await reload();
  await clickRegion('europe');
  await sleep(80);
  await clickRegion('global');
  await sleep(80);
  await clickRegion('asia');
  await sleep(1200);
  state = await snapshot();
  check('最终停在最后一次选择的 asia', state.mapRegion === 'asia' && state.statsRegion === 'asia' && state.countriesRegion === 'asia', state);
  check('最终统计为 asia', state.total === '18,640', state);
  check('过期结果被丢弃', Number(state.stale) >= 1, state.stale);

  console.log('\n[6] 采集失败保留上一次成功结果');
  await clickRegion('europe');
  await sleep(900);
  const beforeFailure = await snapshot();
  check('europe 正常展示', beforeFailure.mapRegion === 'europe' && beforeFailure.total === '15,290', beforeFailure);
  await clickRegion('africa');
  await sleep(900);
  state = await snapshot();
  check('显示失败提示', state.failure === true, state);
  check('失败原因包含 429', (state.failureText ?? '').includes('429'), state.failureText);
  check('继续展示 europe 数据', state.mapRegion === 'europe' && state.total === '15,290', state);

  console.log(
    `\n审计：请求 ${state.requests} 次，缓存命中 ${state.cacheHits} 次，过期丢弃 ${state.stale} 次`
  );
  console.log(failures === 0 ? '\n浏览器端验收全部通过 ✅' : `\n浏览器端验收有 ${failures} 项失败 ❌`);
  ws.close();
  process.exitCode = failures === 0 ? 0 : 1;
} finally {
  await cleanup();
}
