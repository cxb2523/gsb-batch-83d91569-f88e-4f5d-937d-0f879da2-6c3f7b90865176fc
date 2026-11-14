# EasyPost CLI 详细使用指南

EasyPost CLI (`easypost` / `ep`) 是面向开发者和 AI Agent 的本地命令行工具。通过 Chrome 原生 Native Messaging IPC 管道与浏览器中的【快推 EasyPost】扩展协同工作，直接复用浏览器已有登录会话完成零风控的多平台自动填充与发布。

---

## 1. 安装与配置

### 全局安装
```bash
npm install -g easypost-cli
```

### 注册系统级 Native Messaging Host
```bash
easypost install-host
```
* **macOS**：注册清单写入 `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.easypost.cli.json`；
* **Windows**：注册表键写入 `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.easypost.cli`，wrapper 写入 `%USERPROFILE%\.easypost\native-host\`；
* **Linux**：注册清单写入 `~/.config/google-chrome/NativeMessagingHosts/com.easypost.cli.json`。

### 健康诊断
```bash
easypost doctor --repair --wait 30
```
返回 `ok: true` 且 `bridge.state: "connected"` 即表示通信一切就绪。

---

## 2. 核心命令清单

| 命令 | 语法 | 说明 |
| :--- | :--- | :--- |
| `help` | `easypost help` | 输出机器可读的帮助信息与退出码对照 |
| `doctor` | `easypost doctor [--repair] [--wait <sec>]` | 诊断桥接状态，可自动修复 ID 漂移 |
| `capabilities` | `easypost capabilities` | 列出扩展支持的内容形态、平台与预置组合 |
| `bridges` | `easypost bridges list` | 查看当前已连接的 Profile 桥接实例 |
| `prepare` | `easypost prepare [--input <file>]` | 本机校验输入合法性，流式计算素材哈希 |
| `fill` | `easypost fill [--input <file>]` | **打开创作中心并填充素材文案（留待人工点击发布）** |
| `publish` | `easypost publish --yes [--input <file>]` | **直接执行自动发布（必须带 `--yes` 显式确认）** |
| `status` | `easypost status <requestId>` | 查看指定任务的逐平台执行状态 |
| `cancel` | `easypost cancel <requestId>` | 尝试取消未进入不可逆阶段的平台任务 |
| `uninstall-host` | `easypost uninstall-host` | 清理系统注册的 Native Host |

---

## 3. 输入任务规范（JSON Schema）

支持通过 `--input <file>` 读取 JSON 文件，或通过管道从标准输入（`stdin`）传入：

```json
{
  "requestId": "可选，自定义UUID或安全字符串，默认自动生成",
  "browserContext": "regular (默认普通窗口) 或 incognito (无痕窗口)",
  "type": "imageText (图文笔记) 或 shortVideo (短视频) 或 dynamic (动态)",
  "platforms": ["xiaohongshu", "douyin", "shipinhao", "bilibili"],
  "comboName": "可选，预设组合名称（如 '通用（国内）'），传此项可省略 platforms",
  "data": {
    "title": "作品标题",
    "content": "正文内容与 #话题",
    "tags": ["标签1", "标签2"],
    "allowDownload": true
  },
  "assets": [
    {
      "path": "/绝对路径/视频或主图.mp4",
      "role": "media"
    },
    {
      "path": "/绝对路径/竖版封面.jpg",
      "role": "cover"
    },
    {
      "path": "/绝对路径/横版封面.jpg",
      "role": "horizontalCover"
    }
  ]
}
```

---

## 4. 退出码（Exit Codes）

| 退出码 | 标识 | 含义 |
| :--- | :--- | :--- |
| `0` | `OK` | 执行成功 |
| `2` | `INPUT` | 输入格式错误、参数缺失或超长限制 |
| `10` | `CONFIRMATION_REQUIRED` | 执行 `publish` 缺少 `--yes` 确认标志 |
| `20` | `AUTH` | 对应平台未登录或登录态失效 |
| `30` | `BRIDGE` | Chrome 未打开或扩展桥接未连通 |
| `40` | `EXECUTION` | 任务部分失败或需要人工排查（needs_check） |
