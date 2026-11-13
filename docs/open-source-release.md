# v0.1.0 开源发布交接

目标仓库：[FtShare 开源仓库](https://github.com/FTShare-Lab/FtShare_fincase)，分支`main`。以本候选的源码包及逐文件清单作为推送依据；外部推送在用户审查许可后执行。

## 本版内容

ETF异动雷达、20／60日双基准、短时成交观察、阈值调整与时点回放；自动更新、后台统一采集与共享缓存；文字导航、九张图表、12类宽基资金和手机浏览。

## 部署说明

v0.1.0采用后台采集、共享缓存和只读网页。部署者配置自己的Key、历史数据、采集任务与缓存，再发布网页。README链接到可执行的部署指南。

## 发布文件

| 内容 | 位置 |
|---|---|
| 产品介绍、在线体验和使用入口 | [README](../README.md) |
| 数据结构、净申赎计算与雷达要求 | [数据文档](data.md)、[雷达规则](radar-preview.md) |
| Node、Docker、Cloudflare、Mac | [部署指南](deployment.md) |
| 后台采集、KV、定时归档及回退 | [云端配置](cloud-scheduled-update.md) |
| 模拟数据CI、计算与缓存测试 | `.github/workflows/ci.yml`、`tests/` |
| 可选采集工作流 | `docs/examples/cloud-test-update.yml` |
| 许可与贡献 | [MIT](../LICENSE)、[第三方声明](../THIRD_PARTY_NOTICES.md)、[贡献](../CONTRIBUTING.md) |

公开文件由`scripts/lib/release.mjs`生成允许清单。运行数据、凭据、原始响应和部署记录保存在私有运行环境。公开仓库从本候选建立新历史。

## 推送前检查

```sh
npm ci
npm test
npm run build:pages
npm run validate
npm run deploy:check
npm run check:release
npm run release:archive
```

另用`ENABLE_RADAR=1 npm run build:pages`检查雷达构建。将源码包解压到新目录，核对文件清单、校验值、文档链接、默认演示和雷达资源。发布审查记录保存在`releases/`，源码包与审查记录分别管理。

## 审查后执行

1. 再次核对远端状态、版本和逐文件SHA-256。
2. 将本候选源码作为目标仓库的初始提交推送。
3. 核对GitHub展示、README图片与链接、CI结果。

网站部署、域名操作和数据归档按各自的发布流程执行。
