[English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md) | 中文 | [Español](README.es.md)

# whosup

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.png">
    <img src="assets/logo.png" alt="whosup" width="360">
  </picture>
</p>

> **别再把会话晾在一边。** whosup 把所有 herdr 会话放进一块看板，告诉你下一个该看哪个窗格。

你在 [herdr](https://herdr.dev) 的窗格里同时跑着六个、十个、十五个编码代理。有的还在干活，有的一小时前就结束了，还有一个停在你根本没看到的权限确认上。whosup 会把所有运行中的 herdr 会话的每个窗格汇总到一个浏览器页面：谁需要你输入，谁刚刚完成，谁还在运行，谁已经安静下来。点一下格子，herdr 就会跳到对应的窗格。

<p align="center">
  <img src="assets/hero.png" alt="whosup —— 把散落、被遗忘的终端会话收进一块看板，下一个要看的窗格标成橙色" width="900">
</p>

[快速开始](#快速开始) • [为什么选择 whosup？](#为什么选择-whosup) • [你会看到什么](#你会看到什么) • [工作原理](#工作原理) • [功能](#功能) • [设置](#设置) • [按环境设置](#按环境设置) • [环境要求](#环境要求)

---

## 快速开始

### 1. 安装 herdr 插件

```bash
herdr plugin install fivetaku/whosup --yes
```

### 2. 启动（或者直接重启 herdr）

```bash
herdr plugin action invoke fivetaku.whosup.start
```

看板会在 `http://127.0.0.1:4790` 启动，并在浏览器中自动打开一次。此后它会随 herdr 一起启动。

### 3. 想开多少 herdr 会话都行

```bash
herdr --session work      # 名字随意，终端随意
```

所有运行中的会话都会自动出现在看板上，无需维护任何列表。

### 在 Windows 上

同一个插件也能在 Windows 上运行，操作名带 `win-` 前缀（`win-start`、`win-doctor` 等）。见 [Windows](#windows)。

---

## 为什么选择 whosup？

- **不用再挨个窗格查看。** 顶部状态条会告诉你有多少窗格需要输入、已失败、已完成或正在运行。**next** 一行会指出最该先看的那个窗格，并引用它正在提出的问题。
- **一键直达对应窗格。** 点击格子，herdr 就会聚焦到那个窗格，不论它在哪个会话的哪个标签页。在 macOS 上还可以把你的终端应用切到最前面。
- **重启不会丢失对话。** 重启后 herdr 会恢复窗格，但不会恢复代理。空窗格的格子上会出现 **resume** 按钮，它会找到该文件夹下最新的一次 Claude Code 对话，并在窗格里运行 `AGENT_CMD --resume <id>`。resume 只读取 Claude Code 的对话记录；其他代理会开始一段新对话。
- **颜色有明确含义。** 整体黑白，橙色只标出下一个该看的，红色表示失败。没有持续闪烁。
- **切到别的窗口也会提醒。** 标签页标题会显示等待的窗格数，如 `(3) whosup`，网站图标的橙色格会亮起。刚举手的格子会闪过一次橙色边框。顶栏的排序按钮在 **by desk**（按 desk 顺序）和 **neglected first**（搁置久的优先）之间切换；后者会把等得最久的窗格移到每个 desk 的最前面。打开顶栏的 **alerts** 可收到桌面通知，点击即跳到该窗格。
- **等待中的窗格不会丢。** 需要你的窗格会一直留在看板上，直到你处理它——过了午夜、重启之后、herdr 短暂无响应时都一样。**seen** 只会推迟 30 分钟，之后仍在等待就会重新出现。关闭的窗格在 **recently closed** 行保留 7 天，你用 **stash** 收起的窗格则一直保留到你恢复它，都可以在那里继续打开或恢复。收起的窗格重新开始工作时会自动回来。常看的窗格可以用图钉固定在最上方。
- **不知道就说不知道。** 连不上 herdr 时，顶栏显示 *disconnected · last collect HH:MM*，标签页标题变成 `(!) whosup`，网站图标变灰，而不是安静地显示过期的看板。
- **浅色、深色、你的语言。** 顶栏按钮切换模式（auto / light / dark），**settings** 面板切换语言（English / 한국어）。界面没有中文，所以本 README 中的按钮名沿用英文界面。配色参考真实 IDE 主题，文字对比度保持在 WCAG AA 水平。

---

## 你会看到什么

<p align="center">
  <img src="assets/board-light-en.png" alt="whosup 看板，浅色" width="900"><br>
  <img src="assets/board-dark-ko.png" alt="whosup 看板，深色，韩语界面" width="900">
</p>

| 区域 | 含义 |
|---|---|
| **状态条** | 需要输入 · 失败 · 完成 · 运行中 · 空闲的窗格数和窗格总数，以及今天的关注事件数和其中 3 分钟内处理完的比例。点击数字可以筛选。 |
| **next 一行** | 最该先看的那个窗格及原因：待回答的问题、失败信息或已完成的答复。 |
| **desk** | 每个 herdr 会话一行（desk），每个窗格一个格子，按窗格顺序排列。格子标题：标签 · git 分支（没有分支时显示会话名） · 状态；按统一顺序排在前面的 9 个等待中窗格带 1–9 编号（如 `needs input 3`，按 3 跳过去） · 已等待时间（运行中和空闲的窗格显示距你上次请求的时间） · 失败类型（如 usage limit）和 *unreachable* 标签。下面是一行上下文。 |
| **格子内的一行** | 代理正在提出的问题（权限框、文件夹信任确认、二选一），或它的最后一句话，或你的最后一次请求，取决于当前状态下哪个最重要。 |
| **resume** | 重启后的空窗格上：接着该文件夹下最新的一次对话继续。 |
| **+ new pane** | 选一个会话和一个文件夹；whosup 会在那里开一个标签页，启动你的代理，并聚焦过去。 |

---

## 工作原理

```
herdr sessions (main, side, …)
   └─ pane list + agent list, every 3 s  ──►  whosup collector  ──►  SQLite (node:sqlite)
                                                                       │
browser  ◄──  http://127.0.0.1:4790  ◄──  board server  ◄─────────────┘
   │
   └─ click  ──►  pane.focus over herdr's socket  ──►  the pane
```

只有一个 Node 进程，无需构建。herdr 的启动钩子是一次性命令：herdr 启动时，它把 whosup 作为后台服务器启动后就结束。之后服务器会自己一直运行，herdr 不会监管或停止它；要停止它，请使用 `stop` 操作。窗格状态来自 herdr 的代理检测（working / blocked / done / idle）；问题文本从窗格屏幕上读取；最后一次请求取自 Claude Code 的对话记录（`~/.claude/projects` 或 `CLAUDE_PROJECTS_DIR`）。运行其他代理的窗格不显示最后一次请求，resume 也会开始新对话。收集器还会监听 herdr 的事件：窗格状态一变就立即收集，不用等下一次 3 秒收集，并马上通知已打开的看板标签页。收不到事件时，3 秒收集照常运行。

**信任模型。** 服务器只监听 127.0.0.1，没有登录。来自其他网站、试图修改内容的浏览器请求会被拒绝（修改只接受从看板自身地址以 JSON 发送的请求），但同一台电脑上运行的任何程序都能调用它的 API，包括修改 `AGENT_CMD` 之类的设置——这是 whosup 在 resume 和 new pane 时输入到窗格里的命令。不要把端口暴露给其他人。对于 `Host` 头不是 `127.0.0.1`、`localhost` 或 `[::1]` 的请求，服务器一律返回 403 `local only`，所以转发公网主机名的隧道（Tailscale Serve、cloudflared、ngrok）根本打不开看板。要从你自己的另一台机器查看，请用保持 localhost 主机名的端口转发，例如 `ssh -L 4790:127.0.0.1:4790 <host>`，再打开 `http://localhost:4790`，并用 `WHOSUP_READONLY=1` 启动服务器。只读模式只阻止修改，不阻止查看：它不会列出主目录下的文件夹，但看板上的内容都看得到——格子提示中的窗格文件夹路径、最后一次请求、问题原文——而且 `GET /api/settings` 仍会返回 `agent_cmd`。

---

## 功能

| 功能 | 说明 |
|---|---|
| 自动发现 | 所有运行中的 herdr 会话和窗格，无需配置 |
| 关注状态 | needs input · failed · finished · running · idle · empty |
| 问题提取 | 权限框、文件夹信任确认和"A 还是 B？"类问题会原文显示 |
| 跳转 | 点击 → `pane.focus`，在 macOS 上显示该会话的终端窗口会切到前台。终端应用会自动找到；如果没有窗口显示该会话，就打开一个新窗口（Ghostty、Terminal） |
| 点击后打开的位置 | **settings** → *Clicking a pane opens*：terminal window（默认）、web address 或 both，按浏览器分别保存。web address 会在 herdr 的网页终端里用新标签页打开该窗格，地址中的 `{session}` 和 `{pane}` 会被替换，每个 herdr 会话可以单独填写地址（网页终端通常每个会话各有一个服务器和端口）。Herdr 应用的行只有在该行填写了自己的地址时才会在网页中打开。标签页按行复用，因此会与打开它的看板保持关联：请只填写你信任的网页终端地址。从其他设备使用看板时请选它。只读模式下不可用（只读会拦住所有点击） |
| Herdr 应用的终端 | 本机上如果 herdr-core（Herdr 桌面应用的终端）正在运行，它的每个终端也会成为一张卡片：应用的每个空间占一行，状态和提问文字以核心报告的为准。点击会跳到 Herdr 应用里的那个窗格并把应用带到前台；应用没有打开时，会在终端窗口中打开该终端（`hc attach`）。关闭、继续、新窗格以及整行的关闭和开启与 herdr 会话相同。无需配置，whosup 也不会启动未运行的核心。核心不会报告的信任文件夹提示会从屏幕读取，并显示为等待输入；除此之外不会根据屏幕内容猜测状态 |
| resume | 窗格自己的对话，否则是该文件夹下没有在其他窗格运行的最新对话 → `AGENT_CMD --resume`；点击前看板会显示是哪一段。仅支持 Claude Code 对话，其他代理会重新开始 |
| new pane | 选择会话和文件夹，运行你的代理命令 |
| desk（可选） | 在 `desks.json` 中按显示器声明会话和窗格；`desks-apply` 操作只补齐缺失的部分，可重复执行 |
| 多语言 | 默认 English，한국어 在 **settings** 面板或用 `?lang=ko` 选择 |
| 主题 | auto / light / dark（顶栏按钮，`?theme=`），参考 IDE 配色调研而来 |
| 只读模式 | `WHOSUP_READONLY=1` 会隐藏操作按钮和 **+ new pane**，阻止点击、Enter、1–9、`n`、点击提醒和修改设置（设置面板只显示语言选择），也不列出文件夹。只阻止修改，不阻止查看——见信任模型 |
| seen = 推迟 | 等待中格子的 **seen** 只隐藏 30 分钟，**unsee** 立即恢复 |
| 固定 | 固定的窗格不受排序影响，放在所有 desk 上方的固定行 |
| stash 与 recently closed | 收起空闲窗格；关闭的窗格在 **recently closed** 保留 7 天，收起的窗格保留到你恢复为止；收起的窗格重新开始工作时会自动回来 |
| 同一顺序 | next 一行、Enter、1–9、提醒和搁置排序使用同一顺序：失败 → 需要输入 → 已完成，等待久的在前 |
| 键盘 | `n`（韩文键盘布局下为 `ㅜ`）打开 new pane · Tab 在窗格间移动，Enter 或 Space 打开获得焦点的窗格 · 没有窗格获得焦点时 Enter 跳到 next 窗格，面板打开时为保存或打开 · 1–9 跳到对应编号的窗格 · Esc 关闭面板。在输入框中输入时忽略 `n` 和 1–9 |
| 重复提醒 | 未处理的窗格每 15 分钟再提醒一次，最多 4 次；处理后关闭提醒 |
| macOS 提醒（可选） | 即使标签页关闭，服务器也可发送 macOS 通知——默认关闭 |
| 分屏（可选，macOS） | 点击格子时把看板放在屏幕左侧、终端占据其余部分（`split_pct`）。默认关闭，需要辅助功能权限 |
| 如实的状态 | 顶栏显示最后采集时间，采集停止时显示 *disconnected*，herdr 无法确认的会话中的窗格会保留并标记 *unreachable* |
| 设置面板 | 顶栏 **settings**：推迟时长、重复提醒间隔与次数、判定关闭的标准、断开警告、recently closed 保留天数、搁置标记天数、macOS 提醒、unreachable 判定时间、分屏、代理命令、点击后打开的位置（仅限当前浏览器）、终端应用。只读模式下只显示语言选择 |

### 插件操作

| 操作 | 作用 |
|---|---|
| `fivetaku.whosup.start` | 启动看板（herdr 启动时也会运行） |
| `fivetaku.whosup.stop` | 停止看板 |
| `fivetaku.whosup.status` | URL（端口）、PID |
| `fivetaku.whosup.open` | 在浏览器中打开看板 |
| `fivetaku.whosup.desks-apply` | 根据 `desks.json` 创建会话/窗格 |
| `fivetaku.whosup.desks-status` | 已声明与实际存在的窗格对比 |
| `fivetaku.whosup.autoconf` | 重新检查本机，更新自动检测的值并显示出来（见[值的来源与自动设置](#值的来源与自动设置)） |
| `fivetaku.whosup.win-*` | Windows 上的同名操作（`win-start`、`win-stop`、`win-status`、`win-open`、`win-desks-apply`、`win-desks-status`、`win-autoconf`），外加 `win-doctor` |

---

## 设置

在插件配置目录（`herdr plugin config-dir fivetaku.whosup`；在 herdr 之外运行时为 `~/.config/whosup`）下的 `.env` 里写入 `KEY=value` 行。这个文件只在 `start` 启动服务器时读取，所以修改后要先运行 `stop` 操作，再运行 `start`。这里写的值优先于自动设置，设置面板又优先于两者（见[值的来源与自动设置](#值的来源与自动设置)）。`desks-apply` 操作不读取 `.env`，代理命令取自 `desks.json` 里的 `agent_cmd`。

| 键 | 默认值 | 含义 |
|---|---|---|
| `PORT` | 4790 | 端口被占用时使用下一个空闲端口 |
| `OPEN_BROWSER` | 1 | herdr 启动时打开一次浏览器标签页 |
| `AGENT_CMD` | claude | resume 和 new pane 使用的命令，如果你有包装脚本，就填在这里；**settings** 面板中改的值优先 |
| `FRONT_APP` | 自动 | 跳转时要切到前台的 macOS 终端应用，例如 `Ghostty`。未设置时由自动设置选择（[规则表](#值的来源与自动设置)中的 L4 通道）；没有窗口时用 Terminal 打开新窗口。在 Windows 上：留空 = 自动（有 Windows Terminal 就用它，否则 PowerShell 窗口）、`PowerShell`、`Windows Terminal` 或 `off`（任何值都接受）。在 **settings** 面板里修改后无需重启即可生效 |
| `STALE_DAYS`（或 `WHOSUP_STALE_DAYS`） | 3 | 窗格多少天没有动静后标记为可收起 |
| `WHOSUP_READONLY` | 0 | 设为 1 即只读：不能修改，也不列出文件夹 |
| `WHOSUP_SEEN_SNOOZE_MIN` · `WHOSUP_RENOTIFY_MIN` · `WHOSUP_RENOTIFY_MAX` · `WHOSUP_GONE_MISSES` · `WHOSUP_STALE_COLLECT_SEC` · `WHOSUP_CLOSED_KEEP_DAYS` · `WHOSUP_OS_NOTIFY` · `WHOSUP_UNREACHABLE_TTL_H` · `WHOSUP_SPLIT_PCT` | 30 · 15 · 4 · 3 · 30 · 7 · 0 · 24 · 0 | 初始值；顶栏 **settings** 面板中改的值在这台电脑上优先 |
| `WHOSUP_INTERVAL` | 3 | 采集间隔（秒） |
| `CLAUDE_PROJECTS_DIR` | `~/.claude/projects` | resume 和最后一次请求查找 Claude Code 对话的目录 |
| `HERDR_BIN_PATH`（或 `HERDR_BIN`） | 自动 | herdr 可执行文件路径；未设置时依次查找 `/opt/homebrew/bin`、`/usr/local/bin`、`~/.local/bin`、`PATH` |
| `WHOSUP_RUNTIMES` | auto | 读取对象：`auto`（herdr 会话和 herdr-core 终端，有哪个读哪个）、`herdr` 或 `herdr-core` |
| `HC_SOCKET` | 自动 | herdr-core 的套接字；未设置时从核心自己的 `core.lock` 读取（遵循 `HC_SESSION` 和 `XDG_STATE_HOME`） |
| `WHOSUP_CLICK_TARGET` | terminal | 尚未选择的浏览器中点击后打开的位置：`terminal`、`web` 或 `both`；由首次运行卡片设置，**settings** 中的 *点击后打开的位置* 可在单个浏览器里覆盖 |
| `HERDR_APP_BIN` · `HERDR_APP_NAME` · `HC_BIN` | `herdr-app` · `Herdr` · `hc` | Herdr 应用的命令（跳转、新标签页、关闭空间）、macOS 上要带到前台的应用名，以及在终端窗口中打开 herdr-core 终端所用的命令 |

### desk（可选）

如果你喜欢固定的布局，比如每个显示器对应一个 herdr 会话，只需描述一次，剩下的交给 whosup 来创建：

```json
{ "agent_cmd": "claude",
  "desks": [
    { "session": "main", "note": "left monitor", "agent": true,
      "panes": [ { "label": "api", "cwd": "~/src/api" }, { "label": "web", "cwd": "~/src/web" } ] },
    { "session": "side", "panes": [ { "label": "notes", "cwd": "~/notes" } ] }
  ] }
```

把上面的内容保存为插件配置目录（`herdr plugin config-dir fivetaku.whosup`；在 herdr 之外运行时为 `~/.config/whosup`）下的 `desks.json`，然后运行 `herdr plugin action invoke fivetaku.whosup.desks-apply`。它只会补上缺失的部分。每个会话想在哪个终端里打开都行（`herdr --session main`）。

### 代理恢复

herdr 自己也可以在重启后重新启动代理（`[session] resume_agents_on_restore`）。如果你是通过包装脚本启动代理的，请把它设为 `false`，改用 whosup 的 **resume**，这样才会走你的包装脚本。

---

## 按环境设置

### Herdr 桌面应用

whosup 通过 Herdr 桌面应用的核心 herdr-core 读取应用里的终端。满足下面几点就无需任何配置：

- **herdr-core 正在本机运行。** 核心会把套接字路径写入 `<state>/herdr-core/<session>/core.lock`（`<state>` 为 `XDG_STATE_HOME`，否则为 `~/.local/state`，在 Windows 上还会查看 `%LOCALAPPDATA%`；`<session>` 为 `HC_SESSION`，否则为 `default`）；设置了 `HC_SOCKET` 时以它为准。套接字存在期间就视为核心在运行。whosup 不会启动核心。
- **`herdr-app` 在 `PATH` 中**（或设置 `HERDR_APP_BIN`）。跳转、新建标签页和关闭空间都通过它完成。没有它也能读取卡片。
- **`hc` 在 `PATH` 中**（或设置 `HC_BIN`）。应用没有打开窗口时，用它在终端窗口中打开该终端。

自动设置（L6 通道）会在安装时和每次启动时检查套接字和 `herdr-app`。点击 Herdr 应用的卡片，会在应用中显示该终端并把应用（`HERDR_APP_NAME`，默认 `Herdr`）切到前台；应用没有窗口时，会在终端窗口中打开 `hc attach <terminal>`。

终端没有出现在看板上时，请检查：

- `WHOSUP_RUNTIMES` 必须是 `auto`（默认）或包含 `herdr-core`；只写 `herdr` 会排除应用。
- 如果给 whosup 设置了 `HC_SOCKET`、`HC_SESSION`、`XDG_STATE_HOME`，它们必须指向应用所用的同一个核心。
- `node scripts/doctor.mjs` 会显示 core 行（套接字，或 *not running*）、查找过的状态目录，以及是否找到 `herdr-app`；`autoconf` 操作会显示 L6 通道及其依据（见[值的来源与自动设置](#值的来源与自动设置)）。
- 在 Windows 上 herdr-core 是否通过 named pipe 监听，尚未确认。

### ovis：在其他设备或手机上打开窗格

[ovis](https://github.com/devswha/ovis) 是 herdr 的 Web 客户端（聊天、实时终端、手机应用）。whosup 只负责找到正在运行的 ovis 并填好地址，不会启动或停止它。

```bash
herdr plugin install devswha/ovis --yes          # 依据 ovis 的 INSTALL.md
herdr plugin action invoke devswha.ovis.start
```

- 作为 herdr 插件安装的 ovis 会随 herdr 一起在 `http://127.0.0.1:7317` 启动，并跟随启动它的那个 herdr 会话的套接字。
- 一个 ovis 服务器只对应一个 herdr 会话。要查看其他会话，就在另一个端口再启动一个 ovis 服务器，并设置 `PORT` 和 `HERDR_SOCKET=~/.config/herdr/sessions/<名称>/herdr.sock`（见 ovis INSTALL.md 的 Configuration）。whosup 会查看 7317–7330 端口。
- whosup 在安装时和每次启动时检查这些端口（L7 通道）。只有当 `GET /api/health?scope=bridge` 用 ovis 自有的字段应答时才视为 ovis。会话取自监听该端口的进程的 `HERDR_SOCKET`（没有则取 `HERDR_SESSION`），macOS 用 `ps` 读取，Linux 用 `/proc`。对 herdr 列出的每个会话，填入地址 `http://127.0.0.1:<port>/?pane={pane}`。
- 无法判断会话时（Windows、herdr 列表中没有的会话、同一会话有两个服务器），不填任何地址，并把该端口标为“需确认”。这时请在 **settings** 里自己填写地址。
- 无论有没有 ovis，点击默认都会打开终端窗口。第一次打开看板时会出现一张卡片，汇总检测到的环境；如果有与会话对应的 ovis，还会询问点击后打开哪里：终端窗口、ovis 或两者。卡片中的选择保存在服务器上（`click_target`），作为所有浏览器的默认值；**settings** → *点击后打开的位置* 只在当前浏览器里修改选择和地址，浏览器里有自己保存的值时就用它。

填入的地址是 `127.0.0.1`，所以会在运行 ovis 的电脑上打开。从其他设备访问时，把那个端口也转发过去（`ssh -L 4790:127.0.0.1:4790 -L 7317:127.0.0.1:7317 <host>`），或在 **settings** 里换成该设备能访问到的地址。在手机上请使用 ovis 自己的应用和中继（见 ovis 的 README）。要从看板打开窗格，看板不能是只读模式。

### Windows

whosup 也能在 Windows 上运行（Node 和 PowerShell，无需 `sh`）。插件里有 herdr 用 `node` 运行的 Windows 专用条目，所以安装和启动方式相同，操作名带 `win-` 前缀：

```powershell
herdr plugin install fivetaku/whosup --yes
herdr plugin action invoke fivetaku.whosup.win-start
herdr plugin action invoke fivetaku.whosup.win-doctor    # 只读检查本机
herdr plugin action invoke fivetaku.whosup.win-autoconf  # 自动设置检测到的内容
```

如果想手动运行（在 whosup 目录下，于 **桌面会话** 中运行——不要通过 SSH，那样窗口不可见）：

```powershell
node scripts\doctor.mjs                 # whosup 能看到什么：Node、herdr、pipe、PowerShell、Windows Terminal、桌面会话
node scripts\launch.mjs start           # 与 start 操作相同（也有 status · stop · open）
# 或在前台直接运行；设置用 PowerShell 变量传入（VAR=值 是 sh 语法，这里不可用）：
$env:FRONT_APP='Windows Terminal'; node bin\whosup.mjs
```

- 自动设置在安装时（`launch.mjs preflight`）和每次启动前运行。`PATH` 中有 `wt.exe` 时选择 **Windows Terminal**，否则点击时打开 PowerShell 窗口。
- 通过 SSH 启动，或处于 Windows 会话 0（服务；先看 `SESSIONNAME`，没有时看进程的会话编号——桌面上的登录计划任务没有 `SESSIONNAME` 也算桌面）时，whosup 视为远程：桌面上什么也不会显示，所以既不打开浏览器，也不把窗口切到前台（*终端应用* = 关闭）。要用窗口，请从桌面会话启动。
- 点击窗格会把显示该会话的终端窗口切到前台；没有这样的窗口时，会新开一个连接到该会话的 PowerShell 窗口。可在设置面板的 *终端应用* 中选择 **自动**、**PowerShell**、**Windows Terminal** 或 **关闭**（也可设置 `FRONT_APP`）。
- `node bin\whosup.mjs` 不读取 `.env`；`launch.mjs` 和插件操作会读取（只有 `KEY=value` 行，不执行任何内容）。
- 需要 Windows 版 Node 22.13+（[nodejs.org](https://nodejs.org)，或 nvm-windows、Volta、fnm）在 `PATH` 中，herdr 在 `PATH` 中（或设置 `HERDR_BIN_PATH`）。
- 尚未在 Windows 真机上确认：Herdr 桌面应用（herdr-core）在 Windows 上是否通过 named pipe 监听，以及启动钩子返回后 herdr 是否让 whosup 继续运行。`win-doctor` 会显示这两点。在 Windows 上能找到 ovis 端口，但无法得知每个端口对应的会话，所以标为“需确认”。

### 值的来源与自动设置

每项设置按以下顺序取第一个找到的值：**设置面板 > 环境变量（含 `.env`）> 自动检测 > 内置默认值。** 你在面板或环境变量里设的值，自动设置永远不会改动；自动设置也不会写入 `.env` 或面板的值。

- **设置面板**：保存在本机 whosup 的数据库中，立即生效。清空某一栏，就回到下一层的值。
- **环境变量 / `.env`**：写在插件配置目录（`herdr plugin config-dir fivetaku.whosup`；在 herdr 之外为 `~/.config/whosup`）下 `.env` 里的 `KEY=value` 行。只在 `start` 启动服务器时读取，所以编辑后先运行 `stop`，再运行 `start`。
- **自动检测**：在安装时（build 钩子）和每次启动前重新检查，写入状态目录（herdr 的插件状态目录；在 herdr 之外为 `~/.config/whosup`）下的 `auto.json`。服务器启动时，如果这个文件是刚写入的（同一平台、2 分钟内）就读取；否则（例如直接运行 `bin/whosup.mjs`）会重新检测并重写，检测失败时不带自动值启动。

要查看检测结果，运行 `autoconf` 操作（Windows 上为 `win-autoconf`），或在 whosup 目录下运行 `node scripts/autoconf.mjs`（加 `--json` 输出 JSON）。它会列出每个通道的值和依据，并标出由环境变量胜出的值。运行中的看板会应答 `GET /api/autoconf`，`GET /api/settings` 的 `origins` 给出每项设置的来源。

| 通道 | 检查什么 | 设为什么 | 在哪里修改 |
|---|---|---|---|
| L1 | 操作系统 | 仅报告：herdr 在 macOS 和 Linux 上运行 `sh` 条目，在 Windows 上运行 `node` 条目；Windows 上不提供系统通知选项 | — |
| L2 | Node 22.13+ 与 `node:sqlite` | 版本更低时安装会给出提示并停止 | 升级 Node |
| L3 | 是否为桌面会话：SSH（`SSH_CONNECTION`、`SSH_TTY`）、会话 0 的 Windows（无 `SESSIONNAME` 且会话编号为 0）、没有 `DISPLAY`/`WAYLAND_DISPLAY` 的 Linux | 远程时不打开浏览器（`OPEN_BROWSER` 0）；还会关闭把窗口切到前台（macOS 和 Windows，`FRONT_APP` 值为 `off`） | `OPEN_BROWSER`、`FRONT_APP`、*终端应用* |
| L4 | 终端应用。macOS：当前显示 herdr 的应用，否则为已安装的 Ghostty、iTerm、WezTerm 或 kitty。Windows：`PATH` 中的 `wt.exe`。Linux：不检查 | macOS：没有窗口显示该会话时用来打开新窗口的应用（点击时仍切到正在显示该会话的应用，面板显示为*自动*）。Windows：使用的终端。找不到时用点击时显示 herdr 的应用，再没有则用 Terminal（macOS）或 PowerShell 窗口（Windows） | *终端应用*、`FRONT_APP` |
| L5 | herdr：可执行文件、版本、运行中的会话 | 仅报告；找到 herdr 时读取 herdr 会话 | `HERDR_BIN_PATH`、`WHOSUP_RUNTIMES` |
| L6 | Herdr 桌面应用：herdr-core 套接字、`herdr-app` 命令 | 仅报告；核心运行期间读取它的终端 | `WHOSUP_RUNTIMES`、`HC_SOCKET`、`HERDR_APP_*` |
| L7 | 127.0.0.1:7317–7330 上的 ovis，以及每个服务器对应的 herdr 会话 | 每个会话的 Web 地址；点击仍打开终端窗口 | 首次运行卡片、*点击后打开的位置* 及每个会话的地址 |
| L8 | `PATH` 中的 `claude`，否则 `codex`；Claude Code 的对话目录 | 恢复和新建窗格所用的代理命令；恢复能否找到对话 | **settings** 中的代理命令、`AGENT_CMD` |
| L9 | macOS 辅助功能权限（点击把窗口切到前台时才知道） | 缺少权限时标记分屏不可用 | 系统设置 → 隐私与安全性 → 辅助功能 |
| L10 | 从 `PORT`（4790）起的空闲端口 | 仅报告；whosup 会自己换到下一个空闲端口 | `PORT` |

---

## 环境要求

- [herdr](https://herdr.dev) 0.9.0 或更高版本。Herdr 桌面应用的终端（herdr-core）在运行时也会一并读取，两者有其一即可
- Node.js 22.13 或更高版本（无需标志即可使用 `node:sqlite`）；不需要 bun，也无需构建
- curl（在 macOS 和 Linux 上 `start`、`status` 和 `open` 操作用它做健康检查；Windows 用 Node 自带的 `fetch`）
- macOS、Linux 或 Windows 10/11（PowerShell 5.1+，在桌面会话中运行；见 [Windows](#windows)）

---

## 不是 whosup 的范围

终端镜像、聊天，以及用手机输入：请看 [ovis](https://github.com/devswha/ovis)。看板驱动的代理：herdr-board。whosup 只负责看和跳转。

## 许可证

MIT —— 见 [LICENSE](LICENSE)。

---

<div align="center">

**看一眼，直接跳到需要你的那个。**

</div>
