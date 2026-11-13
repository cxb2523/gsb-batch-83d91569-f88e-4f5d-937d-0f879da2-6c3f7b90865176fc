# 在线演示 · 客户分布采集链路

“在线演示”页（`/demo` 的地图分析标签页）不再使用两份互不关联的写死数据。区域按钮、地图中心、
统计卡、国家标签全部来自同一条可核对的服务端采集链路。

## 数据流

```
public/demo-data/customer-distribution/index.json      ← 数据源目录（区域列表 + 来源信息）
        │
        │  createHttpDataSource / createFileDataSource
        ▼
regions/{regionId}.json                                 ← 每个区域一份采集记录
        │
        │  collector.ts  → validateRecord（validator.ts）
        ▼
DistributionResult（available | unavailable）
        │
        │  controller.ts（缓存、请求合并、最新优先令牌）
        ▼
CustomerDistributionState → viewModel.ts → DemoPage.tsx
```

关键约束：`buildDistributionView` 只从**一个** `DistributionResult` 生成地图、统计卡与国家标签，
三者共用同一个 `regionId`；页面上对应 `data-testid` 也带 `data-region-id`，便于核对“同源”。

## 文件路径与字段

数据源目录：`public/demo-data/customer-distribution/index.json`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `sourceId` | string | 数据源 ID，展示在页面上 |
| `sourceName` | string | 数据源名称 |
| `updatedAt` | ISO-8601 string | 数据源目录更新时间 |
| `regions` | `{ id, name }[]` | 区域按钮列表；id 即区域文件名 |

区域记录：`public/demo-data/customer-distribution/regions/{regionId}.json`

| 字段 | 类型 | 校验规则 |
| --- | --- | --- |
| `regionId` / `regionName` | string | 必须与目录一致 |
| `map` | `{ lat, lng, zoom, address }` | lat ∈ [-90,90]、lng ∈ [-180,180]、zoom ∈ [1,22]、address 非空 |
| `totalCustomers` | number | 非负整数 |
| `activeCustomers` | number | 非负整数且 ≤ `totalCustomers` |
| `growthRate` | number | 有限数值，∈ [-100, 1000]；25 表示 +25%（不是字符串 `"25%"`） |
| `topCountries` | string[] | 非空，逐项非空字符串 |
| `collectedAt` | ISO-8601 string | 有效时间 |
| `simulateCollectionFailure` | string（可选） | 存在时该区域模拟“上游采集失败” |

校验失败或字段缺失 → 该区域结果 `status: 'unavailable'`，页面整块标记不可用并列出原因，
**不会**显示 0、NaN，也不会沿用其它区域数字。

## 本地样例覆盖

| 区域 | 用途 | 结果 |
| --- | --- | --- |
| `global` 全球视图 | 正常 | available，lat 20 / lng 0，52,780 / 36,120 / +25.4% |
| `asia` 亚洲市场 | 正常 | available，lat 35 / lng 105，18,640 / 12,730 / +34.8% |
| `europe` 欧洲市场 | 正常 | available，lat 50 / lng 10，15,290 / 10,980 / +19.6% |
| `america` 美洲市场 | **字段缺失/数值非法** | unavailable：缺 `activeCustomers`，`growthRate` 为字符串 `"22%"` |
| `africa` 非洲市场 | **采集失败** | 上游返回 429 模拟错误，页面保留上一次成功结果并提示 |

> 若还需演示“记录缺失”，删除 `regions/europe.json` 后刷新，该区域会显示“缺少采集记录”。

## 行为语义

- **加载态**：采集期间只显示骨架屏与“正在采集…”，不展示旧区域的地图或数字。
- **重复点击**：已采集区域命中缓存；采集进行中重复点击同一区域合并到已有请求。均不会新增请求。
- **快速切换**：选择令牌保证只有最后一次选择的结果会写入页面，其余结果只进缓存并计入“过期丢弃”。
- **采集失败**：`current` / `lastSuccess` 不被覆盖，继续展示上一次成功结果，并在页面上显示失败原因。
- **来源与时间**：结果携带 `sourceId`、`collectedAt`、`fetchedAt`，页面“本次采集”区块与底部核对条可见。

## 验收

### 1. 服务层（无需服务器）

```bash
pnpm verify:demo
```

覆盖正常切换同源、非法区域、重复点击、请求合并、快速切换、采集失败、来源与采集时间字段。

### 2. HTTP 数据源（需要开发服务器）

```bash
pnpm dev                      # 终端 A
pnpm verify:demo:http         # 终端 B，默认 http://localhost:5173
```

### 3. 浏览器交互（需要开发服务器 + 本机 Chrome/Edge）

```bash
pnpm dev
pnpm verify:demo:browser
# 或指定端口：node scripts/demo-collection/browser-e2e.mjs http://localhost:5199/demo
```

### 手动复现步骤

1. `pnpm dev`，浏览器打开 <http://localhost:5173/demo>，确认“地图分析”标签页。
2. 页面自动选中“全球视图”：地图中心 20/0；统计卡 52,780 / 36,120 / +25.4% / 5；“主要国家分布”5 个标签；
   下方“本次采集”显示来源 `demo-customer-distribution`、数据源采集时间与页面获取时间。
3. 点击“亚洲市场”：先出现约 0.5 秒加载骨架；完成后地图中心变为 35/105，统计与 5 个国家标签同时切换。
   底部“采集核对”条中请求数 +1。
4. 再次点击“亚洲市场”两次：请求数不变，缓存命中次数增加，“结果类型”显示“缓存复用结果”。
5. 点击“美洲市场”：地图与统计卡整体消失，出现红色“区域数据不可用”面板，列出
   `activeCustomers 缺失或不是非负整数`、`growthRate 缺失或不是 … 有限数值`；页面无 NaN。
6. 连续快速点击“欧洲市场 → 全球视图 → 欧洲市场”（间隔 < 0.5 秒）：最终只显示欧洲市场；
   “采集核对”条中“过期结果丢弃”≥ 1。
7. 在“欧洲市场”成功展示后点击“非洲市场（演示采集失败）”：出现失败提示（含 HTTP 429），
   地图与统计卡仍为欧洲市场数据，不被写死数字覆盖。
8. 展开“采集链路核对信息”，可见数据源 URL、字段清单与请求/缓存/合并/过期计数。

## 页面上的核对锚点

| `data-testid` | 用途 |
| --- | --- |
| `region-button-{id}` | 区域按钮（`data-active`） |
| `region-map` | 地图容器，`data-region-id` / `data-lat` / `data-lng` / `data-zoom` |
| `region-stats` | 统计卡容器，`data-region-id` |
| `stat-card-{key}` | 单张统计卡容器 |
| `stat-value-{key}` | 单个统计数值（totalCustomers / activeCustomers / growthRate / coverage） |
| `region-countries` | 国家标签容器，`data-region-id` |
| `region-provenance` | 来源、采集时间、结果类型 |
| `region-unavailable` | 不可用面板 |
| `collection-failure` | 采集失败提示 |
| `collection-audit-strip` | 请求/缓存/合并/过期计数 |

核对方式：切换区域后，`region-map`、`region-stats`、`region-countries` 三个 `data-region-id` 必须相同。

## 可配置项

- `VITE_DEMO_DATA_URL`：覆盖数据源 URL（默认 `${BASE_URL}demo-data/customer-distribution`）。
- 采集最小耗时：`createCustomerDistributionController` 的 `minLatencyMs`（页面默认 450ms）。
