# 数据接入、计算与历史补全

**数据服务：FtShare。** ETF行情、份额、净值、交易日历、公告与PCF通过FtShare接口接入；历史数据保留内部溯源记录。

## 模式

`demo` 使用 `data/demo-seed.json`。文件由 `npm run demo:generate` 确定性生成，所有金额、价格、涨跌幅和示例日历均为模拟；ETF 代码与名称只用于演示界面。演示接口不读取 Key，也不调用网络。

`live` 的网页读取自己的授权快照和共享缓存；FtShare Key只供后台采集器使用。源码提供成员配置、计算模型、接口适配与导入工具；历史数据及原始响应由部署者管理。

## 导入兼容快照

```sh
npm run data:import -- /path/to/authorized-seed.json
```

只接受真实来源、当前公式版本、结构与长度一致且分类合计可核对的快照；模拟数据不能按真实数据导入。成功后写到忽略的 `data/private/seed.json`。已有快照不会因验证失败而被替换。

在 `.env` 设置：

```dotenv
DATA_MODE=live
FTSHARE_SEED_FILE=data/private/seed.json
FTSHARE_API_KEY=
```

仅采集器需要填写Key。`npm run build && npm start`启动只读网页；分钟行情还需配置下文的文件缓存或共享KV。

## 从自己的 FtShare 账号采集

先配置 Key，再编辑 `config/collection.json`：

```json
{
  "flow_start": "2022-01-01",
  "market_start": "2023-10-09",
  "minute_days": 20,
  "concurrency": 2
}
```

```sh
npm run collect -- --help
npm run collect
# 或指定采集截至日
npm run collect -- --end 2026-11-09
```

日期配置决定查询范围，取得的数据日期与覆盖数保存在快照中。首次采集可先缩短区间，成员清单保持包含全部20只核心ETF。`minute_days=0` 可跳过历史分钟采集。异动雷达的60日基准需要至少60个完整的既往交易日；初次采集时将`minute_days`设为至少60，初次采集请将`minute_days`设为至少60。已有兼容完整分钟样本会在增量采集中保留。

采集器读取仓库内配置，不访问上级研究目录；原始响应放在忽略的 `.local/ftshare-cache/` 中，缓存一小时后可重新取得修订值。采集会继承已有同口径快照中的核实事件；接口暂缺旧数据时，保留先前完整的同成员分类聚合值并记录来源批次。成员／分类／公式不一致时停止覆盖，需先人工核对。只有采集及结构校验成功后才原子替换快照；已取得的历史中若有缺失，保留 `null` 和原因，不伪造连续数据。

成员清单为 `config/universe.json`，含 `symbol`、`name`、`bucket`、`is_core_basket`、`inception_date`、`listed_date`。当前配置按 2026-11-05 的分类快照回溯；新的成员、上市日期和指数变更需要运营者更新元信息。核心篮子同时定义在 `src/server/model.js` 中。

## 份额与净值口径

- 沪市：归属日份额减前一交易日份额，再乘归属日原始单位净值。
- 深市：下一交易日份额记录减归属日份额记录，再乘归属日原始单位净值；下一日记录未取得时不提前填值。
- 金额除以 `1e8`，展示为亿元。
- 有效成员从成立日与上市日的较晚者开始纳入。
- 缺失日不当作零；区间累计遇到缺失即停止。
- 官方确认的折算比例用于修正份额变化，分红不充当份额折算比例；没有可靠事件依据的机械异常不直接计为申赎。

这些是本项目明确实现并测试的估算口径。图中的“净流入”采用基金份额变化与净值估算的净申赎金额。

## 历史校正记录

使用已核实的上市基准、份额折算或净值记录校正历史；核实依据随记录保留。

`data/private/flow-recoveries.json`：

```json
{"funds": {}}
```

按基金代码填写经过核实的 `listing_baseline`、`splits` 或 `navs`；字段约束见 `src/server/model.js` 的 `fundDaily`，具体分支在测试中有合成样本。事件资料应保留公告来源、日期和核验依据。已有授权快照中携带的 `flow_evidence` 会随快照一起导入，不需要重新填写。

## 快照结构

结构版本为 `schema: 1`，示例可查看 `data/demo-seed.json` 的组织方式，但其中数值为程序生成的演示样本。

| 字段 | 内容 |
|---|---|
| `provider` / `sources` | 数据服务为FtShare；字段保留原始快照的内部溯源标签，演示为Demo |
| `formula` / `flow_policy` | 与本版模型一致的计算版本 |
| `universe` / `categories` / `calendar` | 成员、12 分类与交易日历 |
| `history` | 核心 20 只的日期、成交额、指数、净申购与覆盖数 |
| `broad` | 分类日度资金、每日总额、覆盖数和问题明细 |
| `minutes` / `minute_slots` | 历史分钟样本及 241 个交易时点 |
| `core_fund_daily` | 最新归属日的20只核心ETF逐基金日度记录，供雷达日度信号使用 |
| `live_snapshot` | 可选的上次成功行情，作为共享缓存不可用时的兜底 |
| `latest_flow_date` / `built_at` | 最新资金归属日及快照生成时间 |

`scripts/lib/seed.mjs` 负责校验：日期顺序、数组长度、成员、分类合计、覆盖完整性和分钟累计。演示与真实模式的浏览器数据缓存分别保存，避免换模式后混用。

## 接口与长期保存

网页只读取已发布的历史及共享行情缓存，刷新网页不请求FtShare；接口对照见 [chart-interfaces.md](chart-interfaces.md)。[云端更新指南](cloud-scheduled-update.md)包含日度定时采集、私有历史归档和盘中每分钟采集。

Node独立部署可在另一个后台进程运行 `node --env-file-if-exists=.env scripts/collect-live.mjs --watch`；Web进程通过 `FTSHARE_LIVE_CACHE_FILE` 只读同一文件。后台进程需自己的Key，Web进程不读取Key。管理员可用 `--now` 在部署验收时取一次当前行情；网页没有对应更新接口。缓存缺失时显示等待，历史图表继续可用。

## 雷达数据要求

构建时设置`ENABLE_RADAR=1`。`minutes`提供观察日之前的完整20／60日样本，`/api/live`提供当前20只篮子的分钟成交与覆盖数。短时比较使用相同5分钟窗口，不跨午休。

`core_fund_daily`示意结构如下，金额单位为亿元；示意未列出20行：

```json
{
  "date": "2026-11-11",
  "captured_at": "2026-11-12T08:00:00Z",
  "rows": [{"symbol": "510300.SH", "flow": 1.25}]
}
```

正式日度发布要求20只记录齐全，日期等于`latest_flow_date`，合计与`history.netflow`对应日期一致；采集器复用已计算的逐基金结果，不另发请求。直接导入的旧快照未带此字段时，页面显示日度数据待齐，需在后台补全后归档。雷达发布门槛见`scripts/lib/cloud-publication.mjs`。

分钟成交与日度净申赎分别判断。日度记录按归属日展示，不因成交放量而推断盘中申购或交易主体。[规则与阈值](radar-preview.md) · [窗口回放](radar-window-review.md)
