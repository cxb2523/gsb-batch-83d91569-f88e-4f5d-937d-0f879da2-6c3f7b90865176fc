# 云端采集、共享缓存与历史归档

这套方案将采集放在云端，网页只读缓存，电脑关机不影响已配置的任务。它包含盘中采集Worker、共享KV，以及运行在私有仓库的日度归档发布流程。

## 更新周期

| 任务 | 北京时间 | 内容 |
|---|---|---|
| 盘中后台 | 交易日09:30—11:30、13:00—15:02，每分钟 | 统一采集20只ETF与指数行情；收盘后多取两分钟 |
| 网页轮询 | 盘中60秒，非交易时段300秒 | 读取已发布缓存并更新图表、雷达；新打开页面首轮60秒 |
| 日度归档 | 每天08:00、12:30、18:00 | 采集近期重叠窗口、合并历史、校验、归档并发布 |

日度GitHub定时任务可能延迟启动；实际归属日取决于份额和净值是否已可用。日度净申赎按独立归属日发布。页面选中时点回放时保留所选时点，点击“跟随最新快照”恢复最新观察。

## 盘中采集与凭据

1. 在Cloudflare账号创建专用KV。
2. 复制`config/intraday-worker.example.jsonc`为忽略的本地配置，填写自己的采集Worker名称和KV编号；配置路径变化时同步调整`main`相对路径。
3. 将同一个KV以`FTSHARE_CACHE`绑定到采集Worker，以及网页Pages的production／preview或网页Worker。
4. **只在采集Worker配置`FTSHARE_API_KEY` Secret**。网页Pages／Worker不需要该Key。
5. 发布采集Worker，确认定时任务、行情日期与缓存覆盖数正确。

示例命令中的配置路径应替换为自己的文件；Secret由交互输入，不写入命令参数：

```sh
npx wrangler secret put FTSHARE_API_KEY --config config/intraday-worker.local.jsonc
npx wrangler deploy --config config/intraday-worker.local.jsonc
```

本地配置应放在Git忽略路径，或加入本地排除列表，不提交实际账号身份。示例Cron为UTC `* 1-3,5-7 * * MON-FRI`，程序再依据北京时间和交易日历筛选；午休、周末和节假日不采集。`VALIDATION_UNTIL`只用于限时验收，常规部署不设置。定时表达式见[Cloudflare Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)。

采集器没有HTTP更新入口，示例中`workers_dev=false`且不绑定公开路由。`live:snapshot`保存最近成功行情，另缓存交易日历和前收盘。缺失分钟优先保留同日先前完整记录；上游失败或限速时保留旧成功结果和错误状态。

## 网页读取

`/api/live`只读共享KV；KV不可用时可回退构建内的`live_snapshot`，没有成功缓存则显示等待。浏览器和边缘缓存减少重复读取，刷新参数不改变采集策略。

- `/api/board`：已发布历史及日度资金快照。
- `/api/live`：共享分钟行情；雷达复用此响应，不单独查询供应商。
- `/api/history`、`/api/cumulative`：已有历史，不触发补采。
- `/api/daily`：live模式返回410；网页不能启动日度采集。
- 修改阈值、回放时点、多人访问均不启动FtShare请求。

后台统一采集仍使用数据额度，KV和托管平台另有自身额度。KV传播具有延迟，以页面标注的实际行情时点为准。

## 日度私有归档

流程模板见 [`examples/cloud-test-update.yml`](examples/cloud-test-update.yml)。真实归档存入私有运行仓库；公开源码仓库运行模拟数据CI，采集流程按模板配置。

配置以下Secrets和Variables：

| 类型 | 名称 | 用途 |
|---|---|---|
| Secret | `FTSHARE_API_KEY` | 日度采集 |
| Secret | `CLOUDFLARE_PAGES_TEST_TOKEN` | 对应账号的Pages发布权限，不需要DNS权限 |
| Variable | `CLOUDFLARE_TEST_ACCOUNT_ID` | 自己的Cloudflare账号 |
| Variable | `CLOUDFLARE_TEST_PROJECT` | 测试Pages项目；现有保护规则要求名称包含`test` |
| Variable | `CLOUDFLARE_FORMAL_PROJECT` | 可选，正式Pages项目 |
| Variable | `CLOUDFLARE_FORMAL_SOURCE_REF` | 可选，已验收源码的完整40位提交编号 |
| Variable | `CLOUDFLARE_FORMAL_AUTO_PUBLISH` | 可选，正式发布开关，验收前保持关闭 |

正式发布目标通过`CLOUDFLARE_FORMAL_PROJECT`设置；脚本核对目标名称、固定源码和`CLOUDFLARE_TEST_PROJECT`对应的测试归档。域名绑定在托管平台单独配置。

首次将有权使用的基线快照存入自己的私有仓库：

```sh
GITHUB_REPOSITORY=OWNER/PRIVATE_REPO \
  FTSHARE_SEED_FILE=data/private/seed.json \
  node scripts/cloud-update.mjs bootstrap
```

该管理员操作需在环境中提供`GH_TOKEN`或`GITHUB_TOKEN`；日常Actions使用任务自己的`GITHUB_TOKEN`，不保存个人登录Token。没有基线时先按[数据文档](data.md)采集或导入，取得兼容真实快照后再执行归档。

## 采集、发布与回退

1. 从私有Release读取最新完整快照，校验SHA256和结构。
2. 采集最近14天重叠窗口，并保留兼容的完整旧历史；成员、分类或公式不兼容则停止覆盖。
3. 校验日期、分类合计和公开区间完整性。启用雷达时还要求最新20只日度记录齐全、与篮子合计一致，并有60日完整历史分钟。
4. 上传压缩数据，最后上传校验清单；实际重新下载、解压和验证，再构建。
5. 测试项目先验证候选部署，再更新稳定测试站，失败回退旧部署。
6. 正式任务使用固定源码，恢复测试通过的同一归档并独立验证后发布；失败单独回退正式站。

构建雷达需`ENABLE_RADAR=1`；模板两阶段均保留该开关，避免日度更新覆盖新栏目。日度采集复用已计算的20只逐基金结果写入`core_fund_daily`，不为雷达重复请求。

原始响应缓存有效期一小时，Actions保存采集缓存供后续任务恢复。默认日度工具调用间隔1000ms；429由全采集器共同冷却，优先遵守Retry-After，明确配额耗尽不反复请求。

## 状态与恢复

首页和`/api/health`显示最近归档信息；`/api/live`显示采集时间、缓存状态和最后完整分钟。归档是新增版本，不覆盖旧附件。

```sh
CLOUD_ARCHIVE_ID=YYYYMMDDTHHMMSSZ-RUN-ATTEMPT \
  node scripts/cloud-update.mjs restore
DATA_MODE=live ENABLE_RADAR=1 \
  FTSHARE_SEED_FILE=.local/cloud-update/seed.json npm run build:pages
```

先恢复到预览验证。恢复文件本身不更改正式域名。重新发布已有归档可在工作流输入`archive_id`，不会重新采集FtShare。

[Pages部署](cloudflare-pages.md) · [雷达规则](radar-preview.md) · [实际验收记录](auto-refresh-acceptance-20261112.md)
