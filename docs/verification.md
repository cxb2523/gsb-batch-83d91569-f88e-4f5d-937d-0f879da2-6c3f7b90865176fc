# v0.1.0 验证指南

## 自动检查

```sh
npm ci
npm test
npm run build:pages
npm run validate
npm run check:release
npm run deploy:check
```

自动测试覆盖沪深份额对齐、净申赎估算、缺失与折算处理、20／60日基准、午休窗口、日度归属、缓存共享、失败恢复和发布回退。测试使用合成数据。

## 页面检查

```sh
ENABLE_RADAR=1 npm run dev
```

访问`http://127.0.0.1:8080`，检查九图、异动雷达、20／60日样本、阈值调整、时点回放、文字导航、深浅主题和手机布局。资金卡片按演示样本的日度记录显示。

## 真实部署检查

按[部署指南](deployment.md)配置快照、后台采集与缓存，核对`/api/health`、`/api/board`和`/api/live`的模式、日期、成员及缓存时间；日度信号与归属日核对，20／60日基准使用完整历史分钟。

以多个客户端同时读取缓存，核对响应和采集时间；通过隔离环境的出站计数检查网页读取与后台采集的分工。[自动刷新与并发验证](auto-refresh-acceptance-20261112.md)

Docker、Mac登录任务、HTTPS及自有域名在对应目标环境验收。

## 源码包检查

```sh
npm run release:archive
```

核对SHA-256，将包解压到新目录，执行上面的自动与页面检查。逐文件清单与验证结果见候选目录的`releases/`。
