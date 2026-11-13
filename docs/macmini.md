# Mac mini 部署

适合在自己的Mac上运行网页和后台采集。域名、证书和入站网络按[网络说明](security-and-network.md)验证。

## 安装与准备

需要Node.js 24+和Git。拉取你准备部署的源码，在项目目录运行：

```sh
npm ci
cp config/macmini.env.example .env
npm run mac:check
```

`mac:check`是只读检查，不修改DNS、防火墙、系统代理和共享设置。使用普通登录用户运行项目，不需要`sudo npm`。

## 准备真实快照和Key

优先从自己有权使用的数据源采集，或导入兼容快照：

```sh
npm run data:import -- /path/to/authorized-seed.json
```

已有GitHub数据附件时，设置`FTSHARE_ARCHIVE_REPO=OWNER/REPO`与`FTSHARE_ARCHIVE_TAG=TAG`，运行`npm run data:bootstrap`，按SHA-256校验后导入。

按`.env`内的`FTSHARE_API_KEY_FILE`准备受限Key文件，例如：

```sh
mkdir -p data/private
touch data/private/api-key.txt
chmod 600 .env data/private/api-key.txt
```

本机填写自己的Key；仅后台采集使用，不写入前端和启动配置。真实模式选择`DATA_MODE=live`，需要雷达时加`ENABLE_RADAR=1`。

## 常驻网页与日度更新

```sh
npm run mac:install
npm run mac:status
```

安装器构建独立运行版本、生成当前登录用户的LaunchAgents，默认监听`127.0.0.1:8080`，探测健康状态。真实模式安装器要求本机具备采集配置；演示模式不要求Key。

现有安装器包含网页服务与每六小时执行的日度刷新任务。云端日度方案按08:00／12:30／18:00运行；Mac盘中分钟采集按下一节单独配置。登录后才运行，机器应保持供电、联网和唤醒。

## 盘中分钟采集

在同目录、同一环境中另行运行：

```sh
node --env-file-if-exists=.env scripts/collect-live.mjs --watch
```

网页与采集器的`FTSHARE_LIVE_CACHE_FILE`应指向同一文件。长期使用时把该命令另行纳入自己的后台进程管理；登录自启由所选进程管理器配置。管理员验收可加`--now`取一次缓存，网页访问不能触发它。

若不运行分钟采集且没有嵌入的成功行情快照，历史图仍可读，实时区域显示等待。

## HTTPS与外部访问

同机Caddy可代理至回环服务：

```caddyfile
etf.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

替换为自己的域名。先验证本机、内网和外网HTTPS，再切换公共DNS；运营商、NAT及路由规则可能影响外部连接。需要服务其他公网用户时，也可使用[云端部署](cloudflare-pages.md)，无需暴露办公电脑。

## 更新与停止

更新源码前记录当前提交编号，再执行：

```sh
git pull --ff-only
npm run mac:install
```

重新安装会使用本机快照构建网页并更新启动设置；日度数据可另运行`npm run data:refresh`。安装器使用已验证版本切换，失败保留或恢复旧快照和运行版本。

```sh
npm run mac:uninstall
```

卸载保留本机Key、历史数据、备份与日志；单独配置的分钟采集进程也需由其进程管理器停止。
