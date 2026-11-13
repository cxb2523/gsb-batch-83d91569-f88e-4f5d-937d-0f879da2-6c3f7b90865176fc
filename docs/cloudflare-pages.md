# Cloudflare Pages 独立部署

适合域名由其他账号／DNS 服务商管理、希望由自己的 Cloudflare 账号托管看板的情况。Pages 支持子域名通过 CNAME 接入，无需把整个主域名转入项目账号。

## 准备和发布

先按数据文档导入授权快照，在本地 `.env` 设置 `DATA_MODE=live`、`FTSHARE_SEED_FILE`。运行Key配置在独立采集端。

```sh
npm ci
npx wrangler login
npm run build:pages
```

需要雷达时，先在`.env`设置`ENABLE_RADAR=1`；这是构建开关，发布后仅改后台环境变量不会改已有页面。初次分钟采集需满足60日样本要求，见[数据文档](data.md#雷达数据要求)。

`dist/pages/` 中包含：客户端文件、许可文件、`_worker.js`（服务端入口）及 `_routes.json`。只有 `/api/*` 调用 Pages Functions；其他文件由静态托管提供。404 页面用于关闭未知路径的默认 SPA 回退。

首次创建独立项目，项目名换成自己的名称：

```sh
npx wrangler pages project create YOUR_PROJECT --production-branch main --compatibility-date 2026-11-10
```

Wrangler 4.160.0 可能默认把创建命令转交新版 Workers；若工具明确报告此次转交失败且没有创建项目，可按其兼容提示对**首次创建**添加 `--force`，直接创建经典 Pages 项目。该参数用于绕过产品转交，不用于覆盖项目；项目已经存在后不再加此参数。也可直接在 Cloudflare 控制台创建 Pages Direct Upload 项目。

当前Pages只读数据，不设置FtShare Key。先按 [云端更新与缓存](cloud-scheduled-update.md) 配置独立采集Worker、共享KV，并把KV作为 `FTSHARE_CACHE` 绑定到Pages的production与preview，再发布：

```sh
npx wrangler pages deploy dist/pages --project-name YOUR_PROJECT --branch main
```

多账号时通过 `CLOUDFLARE_ACCOUNT_ID` 显式指定账号。授权需有 Pages 发布权限；只授予旧 Workers 权限不一定能调用当前的 Pages／新版 Workers 发布接口。无需为了本项目申请 AI、容器、邮件或其他不使用的服务权限。

## 验收与域名

- 检查 `/api/health` 的 `mode: live`、`configured: true` 与成员数量。
- 检查 `/api/board` 的日期范围、`/api/live` 的行情日期与分钟覆盖，以及浏览器九张图；启用雷达时检查20／60日样本和逐基金归属日。
- 检查 `/.env`、`/_worker.js`、`/data/private/seed.json` 不提供私有文件。
- 分别监控托管平台、KV与数据服务的用量。
- Pages提供`*.pages.dev`地址，支持绑定自有域名；在目标网络验证访问。

先用新项目提供的地址测试，保持旧正式站不变。测试通过后，在 Pages 项目中登记自定义子域名，再由域名管理员添加平台提供的 CNAME；不要只改 CNAME 而不登记域名。现有 Sites 绑定和正式解析在切换前保留。

Pages不执行Mac的LaunchAgents定时任务。[云端更新与私有历史归档](cloud-scheduled-update.md)提供每天三次日度采集、每分钟盘中采集及共享缓存。访客只读缓存，不触发FtShare请求。

参考：[Pages 自定义域名](https://developers.cloudflare.com/pages/configuration/custom-domains/)、[Advanced mode](https://developers.cloudflare.com/pages/functions/advanced-mode/)、[路由](https://developers.cloudflare.com/pages/functions/routing/)。
