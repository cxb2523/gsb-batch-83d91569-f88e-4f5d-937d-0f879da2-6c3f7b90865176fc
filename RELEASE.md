# 🦞 Lobster Browser Tool 发布公告

**零配置浏览器控制工具，简单且强大。**

## 特性

- ✅ 零配置
- ✅ 基础 Stealth 补丁（隐藏 navigator.webdriver 等常见自动化特征）
- ✅ 持久登录支持
- ✅ 纯本地运行
- ✅ 轻量 CLI 工具

## 安装

```bash
git clone https://github.com/ythx-101/lobster-browser-tool.git
cd lobster-browser-tool
npm install        # postinstall 会下载 Playwright Chromium
npm link           # 或 npm install -g .，得到 lobster-browser-tool 命令
```

> 默认无头模式，不需要 xvfb；仅在 `HEADLESS=false` 时才需要显示环境（如 `xvfb-run`）。

## 快速使用

```bash
# 启动浏览器（常驻，放到后台）
lobster-browser-tool start &

# 访问页面
lobster-browser-tool navigate <url>

# 截图
lobster-browser-tool screenshot

# 关闭
lobster-browser-tool stop
```

## 命令列表

| 命令 | 说明 |
|------|------|
| `start` | 启动浏览器并常驻，直到 `stop` |
| `stop` | 关闭浏览器 |
| `navigate <url>` | 访问页面 |
| `screenshot [path]` | 截图 |
| `snapshot` | 获取页面结构 |
| `eval <script>` | 在页面执行 JS |
| `wait <selector> [timeoutMs]` | 等待元素可见 |
| `click <selector>` | 点击元素 |
| `type <selector> <text>` | 输入文本 |
| `status` | 查看状态 |
| `analyze "<提示词>"` | AI 识图分析 |

## 项目地址

🔗 https://github.com/ythx-101/lobster-browser-tool

---

**灵感来源：** 看了 OpenClaw 项目后，自己领悟并生长的工具。

**License:** MIT
