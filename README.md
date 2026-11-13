# 🦞 Lobster Browser Tool

Lobster Browser Tool is a zero-config Node.js CLI that lets AI agents and scripts control a real Chromium browser (via Playwright) from the shell — navigate, wait, click, type, screenshot, extract page structure, and optionally ask Gemini to analyze the screenshot.

零配置命令行浏览器控制工具：让 AI Agent 和脚本在终端里用简单命令操控 Chromium 浏览器（打开网页、点击、输入、截图、提取页面结构、Gemini 识图）。

## Why / 适用场景

- Give an AI agent that can run shell commands (Claude Code, Codex, OpenClaw and similar) a browser tool, without writing any Playwright code.
- Take web screenshots, inspect pages, and do simple form interactions on servers or other machines without a desktop (headless Chrome by default).
- 给能执行 shell 命令的 AI Agent 一个现成的浏览器自动化工具；在无桌面的服务器上做网页截图、页面检查、简单表单操作。

## Installation

The package is **not published to npm**; install it from GitHub. Requires Node.js ≥ 18.

```bash
git clone https://github.com/ythx-101/lobster-browser-tool.git
cd lobster-browser-tool
npm install        # postinstall downloads Playwright's Chromium
npm link           # or: npm install -g .   -> provides the `lobster-browser-tool` command
```

Without a global install you can run `node browser-control.js <command>` from the repo directory. If the browser is missing, run `lobster-browser-tool setup` (or `npm run setup`).

## Quick Start

`start` keeps running in the foreground and holds the browser open, so run it in the background (or another terminal). The other commands attach to that browser and leave it running.

```bash
lobster-browser-tool start &                             # browser stays up
lobster-browser-tool navigate https://example.com        # {"success": true, "title": "Example Domain", ...}
lobster-browser-tool snapshot                            # title, text, links, interactive elements
lobster-browser-tool screenshot ./page.png               # full-page PNG
lobster-browser-tool stop                                # closes the browser; `start` process exits
```

The browser listens on a local remote-debugging port (default `18791`, bound to 127.0.0.1) and uses a persistent profile directory, so cookies and logins survive `stop`/`start`.

## Commands

| Command | Description |
|---------|-------------|
| `start` | Launch the browser and stay resident until `stop` / Ctrl+C. Prints `Browser already running` if one is up. |
| `stop` | Close the browser. |
| `navigate <url>` | Open a URL and wait for the network to go idle. |
| `screenshot [path]` | Full-page screenshot (default `/tmp/screenshot.png`). |
| `snapshot` | URL, title, page text, first links, and visible buttons/inputs. |
| `status` | Whether the browser is running, current URL and title. |
| `analyze "<prompt>"` | Screenshot the page and ask Gemini about it (needs `GEMINI_API_KEY`; otherwise returns the screenshot path only). |
| `eval <script>` | Evaluate a JavaScript expression in the page. |
| `wait <selector> [timeoutMs]` | Wait until an element is visible (default 10000 ms). |
| `click <selector>` | Click an element. |
| `type <selector> <text>` | Fill an input with text. |
| `setup` | Install Playwright's Chromium. |

## Examples

Log in to a form:

```bash
lobster-browser-tool navigate https://example.com/login
lobster-browser-tool wait "input[name=email]"
lobster-browser-tool type "input[name=email]" "me@example.com"
lobster-browser-tool type "input[name=password]" "$PASSWORD"
lobster-browser-tool click "button[type=submit]"
```

Give page structure to an LLM:

```bash
lobster-browser-tool navigate https://example.com
lobster-browser-tool snapshot > page.txt     # progress lines + the JSON snapshot
```

Ask Gemini about a page:

```bash
export GEMINI_API_KEY=...          # your own key
lobster-browser-tool analyze "What is this page about?"
```

## Configuration

| Variable | Meaning |
|----------|---------|
| `CHROMIUM_PATH` | Use this Chromium/Chrome executable. Default: Playwright's bundled Chromium. If the path is not executable, the tool falls back to the bundled one. |
| `HEADLESS` | `false` to show the browser window (needs a display, e.g. `xvfb-run`). Default: `true`. |
| `GEMINI_API_KEY` | API key for `analyze`. |
| `GEMINI_MODEL` | Gemini model for `analyze`. Default: `gemini-flash-latest`. |
| `LOBSTER_DATA_DIR` | Browser profile directory. Default: `~/.lobster-browser/profile`. |
| `LOBSTER_PORT` | Remote-debugging port. Default: `18791`. |

Runtime state (pid, port) is written to `~/.lobster-browser/state.json`.

## Output format

Every command prints progress lines followed by a JSON object that contains a `success` field (`true`/`false`) and, on failure, an `error` message — easy for an agent to parse. When no browser is running, page commands (`navigate`, `screenshot`, `snapshot`, `analyze`, `eval`, `wait`, `click`, `type`) fail with `Browser not started`; `status` reports `"running": false` and `stop` reports `Browser not running`.

## Comparison / 与同类方案

- **Playwright / Puppeteer directly**: more powerful, but you write and run code. Lobster Browser Tool wraps a small set of operations into shell commands.
- **Playwright MCP, browser-use and similar agent frameworks**: need MCP support or a Python agent framework. Lobster Browser Tool works with any agent that can run shell commands. (`mcp.json` in this repo is only a command manifest, not an MCP server.)
- **Not a good fit**: large-scale crawling, complex multi-tab workflows, or sites that need strong anti-detection.

## FAQ

**How do I let an AI agent control a browser from the command line?**
Run `lobster-browser-tool start &`, then have the agent call `navigate`, `snapshot`, `click`, `type`, `screenshot` and parse the JSON each command prints.

**Does it need a display (headless)?**
No. It runs headless Chromium by default. Set `HEADLESS=false` only if you want a visible window.

**Does it bypass bot detection?**
Not reliably. It applies a basic stealth patch (hides `navigator.webdriver` and common automation hints). Do not rely on it against serious bot protection.

**How do I keep login sessions?**
Log in once; cookies are stored in the profile directory (`~/.lobster-browser/profile` or `LOBSTER_DATA_DIR`) and are still there after `stop` and `start`.

**How do I use Gemini vision?**
Set `GEMINI_API_KEY` and run `lobster-browser-tool analyze "your question"`. Use `GEMINI_MODEL` to pick another model.

**Is it on npm?**
Not currently. Install from GitHub as shown above.

**怎么让 AI 自动操作浏览器？** 让 Agent 通过 shell 调用本工具的 `navigate`、`snapshot`、`click`、`type` 等命令，并解析输出的 JSON。

**无头服务器上怎么截图网页？** `lobster-browser-tool start &`，然后 `navigate <url>` 和 `screenshot ./page.png`，默认就是无头模式。

**和 Playwright MCP 有什么区别？** 本工具是纯命令行，不需要 MCP 支持，任何能执行 shell 的 Agent 都能用；功能范围也小得多。

## 中文说明

Lobster Browser Tool（龙虾浏览器工具）是基于 Playwright Chromium 的浏览器自动化命令行工具，适合作为 AI Agent 浏览器工具，也可用于无头浏览器下的网页截图。

安装（未发布到 npm，从 GitHub 安装，需要 Node.js ≥ 18）：

```bash
git clone https://github.com/ythx-101/lobster-browser-tool.git
cd lobster-browser-tool && npm install && npm link
```

快速开始：

```bash
lobster-browser-tool start &
lobster-browser-tool navigate https://example.com
lobster-browser-tool screenshot ./page.png
lobster-browser-tool stop
```

登录态保存在 `~/.lobster-browser/profile`（可用 `LOBSTER_DATA_DIR` 修改）。反检测只是基础补丁，不保证能绕过网站的检测。

## License

MIT — see [LICENSE](LICENSE).
