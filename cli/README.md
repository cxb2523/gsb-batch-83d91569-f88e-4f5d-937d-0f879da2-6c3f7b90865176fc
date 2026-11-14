# easypost-cli

快推 EasyPost CLI 让本地 Agent 和开发者通过当前真实 Chrome 浏览器中的【快推 EasyPost】扩展执行零风控多平台自动填入与发布。CLI 不保存账号密码、凭证或平台 Cookie，直接复用浏览器已有登录会话。

本 CLI 采用 Chrome Native Messaging 本地标准 IPC 管道通信，支持 `regular`（普通）与 `incognito`（无痕）上下文，支持多 Profile 确定性路由。视频号短视频 `prepare` 会自动校验 16 字及标点符号限制，拒绝不合规输入。

## 安装与快速开始

### 1. 前置准备：安装 Chrome 扩展
在 Chrome 浏览器中安装【快推 EasyPost】扩展，并保持 Chrome 处于打开状态。

### 2. 全局安装 CLI
```sh
npm install -g easypost-cli
# 或者从本地源码安装：npm install -g ./cli
```

### 3. 安装 Native Messaging Host 注册表
```sh
easypost install-host
```
安装器会自动从 Chrome 发现已安装的 EasyPost 扩展 ID 并写入系统白名单。开发或受管环境也可显式传 `--extension-id <id>`。

### 4. 验证连通性
```sh
easypost doctor --wait 30
```
当返回 `ok: true` 且 `bridge.state: connected` 即表示与 Chrome 扩展建立安全连接。

---

## 常用命令

所有成功命令只向 `stdout` 输出结构化 JSON 对象；失败向 `stderr` 写错误 JSON，天然契合 AI Agent（Claude Code、OpenClaw、Codex）与自动化脚本解析。

| 命令 | 说明 |
| :--- | :--- |
| `easypost help` | 返回机器可读的命令列表、输入 Schema 与退出码 |
| `easypost doctor` | 检查 Native Host 连通性、扩展状态；加 `--repair` 自动修复配置 |
| `easypost capabilities` | 查询当前支持的内容类型、平台以及预设组合（Combos） |
| `easypost prepare` | 本地输入校验，流式计算素材大小、MIME 与 SHA256 哈希 |
| `easypost fill` | **自动打开对应平台并填充素材与文案**（默认安全模式，留待人工确认发布） |
| `easypost publish --yes` | **直接执行发布**（需加 `--yes` 显式确认） |
| `easypost status <id>` | 根据 `requestId` 查询逐平台执行结果 |
| `easypost cancel <id>` | 尝试取消尚未进入不可逆平台动作的任务 |
| `easypost install-host` | 自动发现扩展 ID 并注册系统级 Native Messaging Host |
| `easypost uninstall-host`| 卸载系统级 Host |

---

## 输入示例

### 1. 极速发布图文笔记（小红书 / 抖音图文 / 视频号）
创建任务文件 `task.json`：
```json
{
  "type": "imageText",
  "platforms": ["xiaohongshu", "douyin"],
  "data": {
    "title": "测试图文标题",
    "content": "这里是发布的内容正文... #AI工具 #创作",
    "tags": ["AI工具", "效率工具"]
  },
  "assets": [
    {
      "path": "/Users/username/Pictures/cover.jpg",
      "role": "media"
    }
  ]
}
```

执行自动填充：
```sh
easypost fill --input task.json
```
扩展会自动打开对应平台创作页，自动上传图片、填充标题与正文。

### 2. 使用预设组合（Combos）一次性并发多平台
```json
{
  "type": "imageText",
  "comboName": "通用（国内）",
  "data": {
    "title": "爆款内容分发",
    "content": "多平台同步测试..."
  },
  "assets": [
    { "path": "/Users/username/Pictures/1.png", "role": "media" }
  ]
}
```
运行：
```sh
easypost fill --input task.json
```

---

## 退出码定义

| 退出码 | 含义 |
| :--- | :--- |
| `0` | 命令成功 |
| `2` | 输入参数无效或平台不支持 |
| `10` | `publish` 缺少 `--yes` 显式确认 |
| `20` | 平台未登录或会话失效 |
| `30` | 本地 Native Host 或 Chrome 扩展未连通 |
| `40` | 执行异常或需要人工核查（needs_check） |

      "type": "image/png",
      "sourceUrl": "https://example.com/original.png"
    }
  ]
}
```

- `requestId` 可省略；CLI 会生成 UUID。也可传 8 到 128 位的字母、数字、点、下划线、冒号或连字符安全标识。相同业务请求应复用同一 ID。
- `browserContext` 只能是 `regular` 或 `incognito`，省略时为 `regular`。如果同时传入 `--browser-context`，两者必须完全一致，否则在本机校验阶段拒绝。
- `comboName` 是插件里保存的发布组合名称。提供后可省略 `platforms`；扩展会读取该组合的平台顺序、公共标签、平台专属标签以及圈子/分组目标。运行 `yijianfa capabilities` 可读取当前可用的 `publishCombos`。
- `groupName` 可省略，只覆盖本次任务的 Chrome Tab 分组显示名；未传时使用组合名称。
- `type` 是 `dynamic`、`imageText`、`article`、`shortVideo` 或 `podcast`。
- `platforms` 与 `comboName` 至少提供一项。按组合发布时建议省略 `platforms`；若两者同时提供，平台集合必须与组合一致，实际执行顺序以组合为准。
- `data` 是传给扩展的 JSON 对象。
- 直接传 `platforms` 执行 `publish` 时必须提供 `data.publishGuard`；按 `comboName` 发布且未显式提供 guard 时，扩展会从组合目标生成 guard，并固定要求公开链接读回。所有平台使用所选浏览器上下文中用户已登录的账号，无需补填账号名称、显示名或昵称。旧 `expectedAccounts` 字段兼容接收但完全忽略，不做名称匹配；即刻目标来自组合或 `expectedTargets.jike`，两者冲突时会在打开平台页前拒绝。没有公开链接时返回 `needs_check`，不得按成功归档。
- 扩展 `0.1.31` 的动态 capabilities 包含 `weibo`、`toutiao`、`juejin`。三者支持 CLI `fill` 与 `publish --yes`；掘金指定圈子时可同时传 `extra.juejin.topic` 与 `publishGuard.expectedTargets.juejin` 做精确核对。
- `fill` 保持兼容，可不传 guard；一旦提供 `data.publishGuard`，仍校验圈子和公开链接配置，账号名称不参与校验。`capabilities` 返回 `accountPolicy=current_browser_session`、`accountNameRequired=false` 和 `expectedAccounts=deprecated_ignored`。
- `assets[].path` 必须是绝对路径且指向普通文件。`role` 只能是 `media`、`cover`、`horizontalCover` 或 `wordFile`，省略时为 `media`；`type` 省略时从文件头和扩展名识别；`sourceUrl` 只接受不含用户名/密码的 HTTP(S)。

### 平台特殊规范

X 文章正文自动填入前 25 张图片，独立封面不占名额。超出的图片在原位置替换为 `【超过25张图片上限，需人工替换】` 和原始图片地址，不再上传；本地素材保留绝对路径，方便手动补图。`prepare` / `fill --dry-run` 的 `data.xArticleImageOverflow` 返回超限图片的位置与地址。多平台任务仅在 X 插件适配器中处理，不影响其他平台。

部分平台（如 X 文章）对输入有额外要求（图片嵌入方式、宽高比处理等），不在上述通用格式中覆盖。构建输入前请先阅读对应平台指南：

| 平台 | 指南路径 |
|------|----------|
| X 文章 (`type: "article"`, `platforms: ["x"]`) | [`cli/skills/x-article/SKILL.md`](skills/x-article/SKILL.md) |

`prepare`、`fill --dry-run` 和 `publish --yes --dry-run` 返回 `status: "prepared_local"`。素材内容以流方式读取，不会为计算 SHA256 把整个大文件载入内存。

非 dry-run 的 `fill` / `publish` 不接受 `--timeout`：首次 execute 会一直保持素材服务，直到扩展给出终态。登录等待也属于同一请求；需要中止时，从另一个进程运行 `yijianfa cancel <requestId>`。

发布前 CLI 最多等待 35 秒，让 MV3 周期 alarm 唤醒 service worker 并恢复 Native 端口；这一阶段只发送只读 `doctor`，桥上线后只发送一次 `execute`，不会因唤醒超时重复发布。

执行中收到 `SIGINT` 或 `SIGTERM` 时，CLI 会先通过桥请求取消，并继续保留素材服务、等待原 execute 返回终态。不要用 `kill -9` 强杀执行进程；它无法协商取消，并可能让已开始的平台任务只能进入 `needs_check`。

## 输出和退出码

成功：

```json
{"ok":true,"command":"fill","result":{"status":"completed","requestId":"..."}}
```

失败：

```json
{"ok":false,"command":"publish","error":{"code":"CONFIRMATION_REQUIRED","message":"publish 必须显式传 --yes","hint":"..."}}
```

| 退出码 | 含义 |
| --- | --- |
| `0` | 命令成功 |
| `2` | 输入、参数或平台环境不支持 |
| `10` | `publish` 缺少显式确认 |
| `20` | 未登录或会话失效 |
| `21` | 额度不足 |
| `22` | 授权服务不可用，按 fail-closed 处理 |
| `30` | host、桥或扩展连接失败 |
| `40` | 执行失败、部分成功、需要人工检查或部分取消 |

## 多 profile 确定性连接（本地源码）

先运行 `node cli/bin/yijianfa.js bridges list`。选择目标扩展注册的 `bridgeId`：

```sh
node cli/bin/yijianfa.js doctor --bridge-id bridge-<32位十六进制标识> --wait 30
node cli/bin/yijianfa.js capabilities --bridge-id bridge-<32位十六进制标识>
node cli/bin/yijianfa.js fill --bridge-id bridge-<32位十六进制标识> --input task.json
node cli/bin/yijianfa.js status <requestId>
```

`--bridge-id` 可用于 doctor、capabilities、prepare、fill、publish、status、cancel，也可放在输入 JSON 的 `bridgeId`。输入与参数冲突会拒绝。`prepare` 和 `--dry-run` 保持离线，返回 `bridgeSelection.state=not_connected`，不能作为目标在线的证据。

扩展按普通/无痕分别保存安装 UUID，使用不同 storage.local 键，避免两种上下文首次初始化竞争。更新和后台重启保持身份；卸载或清除扩展存储会改变身份。复制 profile 导致相同身份同时在线时，CLI 拒绝自动选择。

可选 `--profile <别名>` 对应扩展本地 `cliBridgeProfileName` 设置。别名必须唯一；它不是 Chrome 的 `Default/Profile 1` 目录名，也不是账号昵称。首次配对需在目标 profile 的扩展中核对身份，不能凭任务空间名推断。两个扩展渠道的身份独立，不自动合并。

执行前先核实目标，等待休眠扩展恢复，再启动素材服务。execute、信号取消固定同一连接 instanceId；断开不转投其他桥、不自动重发任务。CLI 在私有运行目录保存 requestId 到稳定 bridgeId 的路由，后续 status/cancel 可在重连后回到同一目标。路由丢失时需显式提供目标；已有请求不能重新绑定到另一目标。

新桥的 execute/cancel 必须携带 `bridgeTarget`；host 与扩展均检查稳定身份和连接实例。任务 `bridgeId` 必须与 envelope 一致，并与 browserContext 一起参与摘要。旧任务仍用旧摘要；升级后查询旧任务，不要以同一 requestId 重新执行，否则可能返回摘要冲突。

旧 host/扩展仍可通过固定端点查询。`YIJIANFA_SOCKET_PATH` 可锁定兼容路径，但不能提供 profile 身份保证；新 CLI 不将它提升为已校验身份。新桥没有固定端口写入别名，旧 CLI 需升级才能执行。此改动只锁定 profile，平台当前登录账号变化仍沿用现有账号策略。

测试隔离可设置绝对路径 `YIJIANFA_RUNTIME_DIR`；CLI 与 host 必须使用同一目录。Unix 目录为 0700、socket 与登记/路由文件为 0600。登记文件不是信任依据，CLI 会向在线 host 握手确认；只清理本实例的端点和登记，不删除其他桥。Windows 使用独立 named pipe，登记文件放在用户临时目录。

## 桥协议 v1 与路由能力 v2

CLI 与 host 使用当前用户本机 IPC 的 NDJSON；传输仍为 protocolVersion=1，新路由通过登记身份和 bridgeTarget 协商。以下固定端点描述仅适用于旧桥。macOS/Linux 普通上下文保持 `/tmp/yijianfa-<uid>/bridge-v1.sock`，无痕上下文使用 `/tmp/yijianfa-<uid>/bridge-v1-incognito.sock`（商店版两者均带 `store` 标识）；Windows 在原 named pipe 后为无痕上下文加 `-incognito`。目录权限为 `0700`，socket 权限为 `0600`。请求 envelope：

```json
{"protocolVersion":1,"kind":"request","id":"transport-uuid","browserContext":"incognito","action":"execute","payload":{}}
```

扩展 action 为 `doctor`、`capabilities`、`execute`、`status` 和 `cancel`；新 host 另提供本地 `describe` 身份握手，不向扩展派发。`status` / `cancel` 的 payload 是 `{ "requestId": "..." }`；执行 payload 是：

```json
{
  "task": {
    "requestId": "...",
    "browserContext": "incognito",
    "comboName": "AI赛道图文",
    "groupName": "AI赛道图文",
    "type": "dynamic",
    "mode": "fill",
    "platforms": [],
    "data": {},
    "assets": [
      {
        "role": "media",
        "name": "example.png",
        "type": "image/png",
        "size": 1234,
        "sha256": "...",
        "blobUrl": "http://127.0.0.1:随机端口/随机令牌/..."
      }
    ],
    "confirmed": false,
    "payloadDigest": "..."
  }
}
```

host 与 Chrome 使用官方 Native Messaging 的“32 位本机字节序长度 + UTF-8 JSON”帧，单条消息严格小于 1 MiB。host 的 stdout 只写协议帧，日志只写 stderr，并通过 transport `id` 代理多个并发 CLI 请求。

`incognito: split` 下普通/无痕扩展后台共享 extension ID，因此每个 Native host 启动后先由扩展发送 `bridge_registration` 注册真实上下文，再绑定对应 IPC。host 会校验 envelope 上下文，扩展还会校验任务上下文；任一层不一致都返回 `browser_context_mismatch`。两个上下文使用独立任务存储键，不会互相恢复或取消任务。

CLI 自动打开工作台时会显式查找 `incognito` 标志相符的现有 Chrome 窗口。找不到时返回 `needs_check/browser_context_window_unavailable`，不会新建窗口或转投另一上下文。在选定上下文内使用当前已登录账号，不读取或比较昵称作为发布门槛；账号信息检测仅供展示及必要的平台元数据补全。平台登录失效、编辑器不可用、圈子不匹配及公开链接缺失仍按执行结果失败或返回 needs_check。

平台结果同时包含字段状态和生命周期：`filled`、`publish_clicked`、`published`、`failed`、`needs_check`。`published` 只在成功提示、业务回执、本人最新内容/公开 URL 等强信号，或编辑器清空与发布框关闭等两个独立弱信号组合成立时返回。公开链接可选返回为 `publicUrl`；正文、token、Cookie 和本机完整路径不会进入持久化结果。

### 素材安全边界

执行期间 CLI 临时启动 `127.0.0.1:0` HTTP 服务，每次使用随机 256 位令牌。服务只提供当前任务素材，支持 `OPTIONS`、`HEAD`、`GET` 和单段 `Range`，返回 CORS、Private Network Access 和 `no-store` 响应头；桥返回后立即关闭。

扩展只收到 `blobUrl`、文件名、MIME、大小、SHA256、role 和可选 `sourceUrl`，永远不会收到本机 `path`。`payloadDigest` 对 `{comboName?, groupName?, type, mode, platforms, data, assets}` 做对象键排序后计算 SHA256；平台顺序和素材顺序保持不变，随机 `blobUrl` 与本机路径不参与摘要。组合内容由扩展在执行时从本地存储读取，不由外部 CLI 伪造。

## 开发验证

```sh
node --test test/*.test.js
npm pack --dry-run
```

抖音、快手短视频可在任务 JSON 中设置 `data.allowDownload: false` 禁止下载，或设为 `true` 允许下载；省略时沿用扩展保存的偏好。单个平台可用 `data.extra.douyin.allowDownload` 或 `data.extra.kuaishou.allowDownload` 覆盖。此设置应用于填入和发布，不修改保存的偏好。

也可直接传命令参数，`prepare`、`fill`、`publish` 都支持，参数覆盖本次任务 JSON 的 `data.allowDownload`，平台级设置仍优先。

```bash
yijianfa fill --input task.json --allow-download false
yijianfa publish --input task.json --allow-download false --yes
```
