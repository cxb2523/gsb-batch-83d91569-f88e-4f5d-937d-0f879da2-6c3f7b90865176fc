# 独立部署

网页服务读取发布快照和共享行情缓存，FtShare Key配置在独立后台采集器。依次准备历史数据、采集与缓存，再启动网页。

## 配置

需要Node.js 24+。先运行 `npm ci`，将 `.env.example` 复制为 `.env`。

| 变量 | 使用位置 | 含义 |
|---|---|---|
| `DATA_MODE` | 构建 | 默认`demo`，真实模式为`live` |
| `ENABLE_RADAR` | 构建 | 默认关闭，设`1`启用ETF异动雷达 |
| `FTSHARE_SEED_FILE` | 构建／日度采集 | 授权快照，默认`data/private/seed.json` |
| `FTSHARE_LIVE_CACHE_FILE` | Node网页／盘中采集 | 两个进程共享的行情缓存文件 |
| `FTSHARE_API_KEY` | 仅采集器 | 采集端的数据账号Key |
| `FTSHARE_API_KEY_FILE` | 仅Node采集器 | 可选的受限Key文件路径，环境变量Key优先 |
| `FTSHARE_REQUEST_INTERVAL_MS` | 日度采集 | 工具调用间隔，默认1000ms |
| `HOST` / `PORT` | Node网页 | 默认`127.0.0.1:8080` |

配置和快照变化后需要重新构建。Cloudflare不读取本机`.env`；共享KV和后台采集Secret在部署账号中配置。

## Node.js

演示无需Key：

```sh
npm run dev
```

真实模式先 [导入或采集授权快照](data.md)，在`.env`中设置`DATA_MODE=live`及需要的雷达开关：

```sh
npm run build
npm run validate
npm start
```

另开一个后台采集进程，使用同一`FTSHARE_LIVE_CACHE_FILE`：

```sh
node --env-file-if-exists=.env scripts/collect-live.mjs --watch
```

这个命令只负责交易时段分钟行情，不负责日度历史归档。部署验收时管理员可使用`--now`取一次当前缓存；网页没有对应更新入口。Key只需传给采集进程，正式网页进程可使用不含Key的独立环境配置。

日度更新需另行调度`npm run collect`、重新构建并重启网页服务，或使用云端归档发布流程。`npm run data:refresh`使用受管理的版本目录，配合Mac安装器运行，不会直接替换普通`npm start`使用的`dist`。Node进程通过进程管理器长期运行；HTTPS可由同机Caddy或Nginx提供：

```caddyfile
etf.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

把域名换成自己的地址。公网访问还取决于DNS、证书和入站网络；[Mac专用指南](macmini.md) 不替代公网接入。

## Docker / Compose

```sh
npm run build
npm run validate
docker compose up -d --build
```

镜像使用预先构建的`dist`。演示镜像无需Key；真实构建内含用于展示的快照，按该数据的授权范围分发。

Docker镜像运行网页服务，实时行情由外部采集器提供，并用本地Compose覆盖文件挂载**包含行情缓存的目录**：

```yaml
services:
  dashboard:
    environment:
      FTSHARE_LIVE_CACHE_FILE: /runtime/live-cache.json
    volumes:
      - ./.local/live-cache:/runtime:ro
```

先创建`.local/live-cache/`，在`.env`中把`FTSHARE_LIVE_CACHE_FILE`设为`.local/live-cache/live-cache.json`供宿主机采集器使用；容器环境以上述绝对路径覆盖。挂载目录可看到采集器原子替换后的新文件。容器通过只读挂载读取行情，FtShare Key配置在外部采集器。

```sh
docker compose -f compose.yaml -f compose.local.yaml up -d --build
```

默认网页端口只映射至宿主机`127.0.0.1:8080`，对外由HTTPS代理提供服务。

## Cloudflare Workers

修改`wrangler.jsonc`中的`name`为自己的名称，先构建检查：

```sh
npm run deploy:check
```

演示可直接登录自己的账号后发布：

```sh
npx wrangler login
npm run deploy
```

真实模式按 [云端更新指南](cloud-scheduled-update.md) 配置独立采集Worker和KV。把同一个KV以`FTSHARE_CACHE`绑定到**网页Worker**，网页只读缓存，不设置FtShare Key。采集Worker使用单独配置和Secret，不能把它与网页入口混为同一程序。

Pages部署另见 [Pages指南](cloudflare-pages.md)。自定义域名在自己的托管项目与DNS服务中配置。

## 上线检查

| 检查 | 预期 |
|---|---|
| `/api/health` | demo为`mode: demo`；live为`mode: live`。live的`configured`表示绑定缓存或携带兜底快照；数据覆盖通过board与live接口核对 |
| `/api/live` | 行情日期、20只覆盖数、最后完整分钟、`cache.mode`与采集时间正确 |
| `/api/board` | 历史范围、日度归属日期、分类合计及缺失日期符合快照 |
| 雷达 | 启用后20／60日样本数、倍数和逐基金日度日期正确；不足样本不确认 |
| 访客采集 | live模式`/api/daily?batch=0`返回410，POST到`/api/live`返回405 |
| 界面 | 导航、折叠、深浅主题、九图、雷达和数据来源可用；演示／真实不混用 |

## 更新与排错

页面盘中约每60秒读取缓存，非交易时段约300秒；新页面首轮倒计时为60秒。雷达默认跟随最新缓存，选择时点回放后保持所选观察时点，点击“跟随最新快照”恢复。日度信号跟随后台新归档更新，不因分钟行情变化而推算当天净申赎。

| 现象 | 处理 |
|---|---|
| 无Key也有图 | 默认模拟演示；真实站也可只读运营者后台缓存 |
| live构建缺少数据 | 先采集／导入兼容快照，配置构建路径 |
| 历史有图，实时等待 | 检查后台采集器、文件缓存路径或KV绑定；给网页填Key不能代替缓存 |
| 没有异动雷达 | 构建时设置`ENABLE_RADAR=1`并重新发布 |
| 60日样本待齐 | 初次采集将`minute_days`设为至少60，或导入已有完整分钟历史；缺失样本不补零 |
| 日度净申赎仍是前一天 | 按归属日期观察份额／净值可用性，检查下一轮后台采集 |
| 历史更新后仍是旧内容 | 确认后台已重建并发布新快照；只改磁盘JSON不足以替换嵌入的历史数据 |
| 数据缺口／累计中断 | 查看日期原因，补充原始数据或核实事件后重建，不跳过缺失续接 |

网页只读接口不会放大FtShare调用；后台采集仍使用数据额度。生产环境应监控缓存时间、采集失败、归档恢复和平台请求额度。[安全说明](../SECURITY.md) · [自动更新实测](auto-refresh-acceptance-20261112.md)
