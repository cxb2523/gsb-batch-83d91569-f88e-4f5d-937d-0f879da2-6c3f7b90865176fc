# Reddit 浏览器试点

独立 Node 工作进程，通过现有 WebMirage 配置卷中的 Unix socket 接收请求；不发布 HTTP/CDP 对外端口，不修改防火墙或 Mira。

## 安装

需要 Node.js >= 20.18.1，以及已有可执行的 Chrome/Chromium。先安装固定依赖，跳过会自动拉取可变适配器的安装脚本：

```sh
cd browser-worker
npm ci --ignore-scripts --no-audit --no-fund
python3 prepare_runtime.py
python3 install_service.py --browser /absolute/path/to/chrome
```

npm 固定 OpenCLI 2.0.2；`reddit-source-lock.json` 单独锁定已审查的 Reddit 适配器提交和 SHA256。`prepare_runtime.py` 从该提交获取四个文件并校验后写入本地依赖，worker 启动时再次验证，避免 npm 发布包中的旧适配器和可变 main 混用。可用 `--source /path/to/reviewed/opencli` 从相同内容的本地 checkout 准备。适配器遵循上游 Apache-2.0 许可，源码及许可见 https://github.com/jackwener/opencli/tree/36bbbd7f60bd361a96e62e417a28ea09d6c2266b 。

`install_service.py` 安装用户级 `mirage-reddit-browser.service`。默认使用已有 Mihomo HTTP 代理 `http://127.0.0.1:7890`；如部署地址不同，应设置工作进程 `REDDIT_BROWSER_PROXY`，不改代理服务。浏览器按需启动，单并发，空闲 10 分钟关闭。CDP 监听本机随机端口，OpenCLI 绑定专用 page 的 WebSocket，不依赖个人电脑或扩展。

## 数据与会话

配置文件仍由 WebMirage 维护。Cookie 只在 Unix socket 请求体传递，不放命令行、日志或 CLI 参数。socket 为 0600；profile 在已忽略的 `gateway/data/reddit-browser/profile`，目录 0700。完整 Cookie 属性导入尚未实现；当前导入现有 Reddit Cookie 字符串。浏览器自动更新的 Cookie 随 profile 保存；配置未变化时重用它，更换凭证或点击“启动 / 更新会话”时重新导入。会话导入和实际接口通过分开显示。

只允许 Reddit 搜索、社区帖子两个只读命令。OpenCLI 结果转换为已有 MCP 数据格式；合法空列表保持成功，异常结构拒绝，HTTP 403 不根据上游 AUTH 标签误判凭证过期。用户资料、动态、帖子详情和翻页在此试点中显式报告不支持，需切回 HTTP。不会静默换后端。

一次操作总预算约 32 秒；CLI 超时会被终止，并关闭浏览器以中止仍在运行的页面请求。收到 429 后冷却一小时，冷却状态持久化，重启工作进程不会取消。状态查询不启动浏览器，不访问 Reddit。搜索的上游实现可能请求搜索网页和详情，不能宣称每次仅一个站点请求；使用小 limit 和低频代表接口检测。

管理台“平台健康 → Reddit”可选择 HTTP/OpenCLI，启动或停止浏览器。默认 HTTP；切换方式会使此前结果失效，统一 `webmirage_check_health` 记录实际后端，不把进程在线或导入 Cookie 算作平台健康。

## 验证与回退

```sh
npm test
systemctl --user status mirage-reddit-browser.service
```

在管理台切回 HTTP 即恢复原请求路径；停止 worker 不影响其他平台。若 worker 未安装，默认 HTTP 仍可使用；选择 OpenCLI 后会明确报告浏览器不可用。新主机需将现有配置目录映射至 WebMirage 的 `~/.webmirage`，以共享 Unix socket；无需新增端口映射。
