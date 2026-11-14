# 使用 AI Agent（Claude Code / OpenClaw）搭建端到端多平台自动分发工作流实战

随着 Claude Code、OpenClaw、Codex 等新一代自主型编程与任务 Agent 的普及，“由 AI 撰写内容，再由 AI 直接分发到各大社交平台”的端到端自动化矩阵创作，已经从设想变成了现实。

本文将带你一步步实战，如何借助 **EasyPost 的 Agent Skill**，在 **Claude Code** 或 **OpenClaw** 中打造一套“一句话完成内容创作与全网零风控矩阵分发”的工作流。

---

## 一、 为什么选择 EasyPost 作为 AI Agent 的分发终端？

在构建 AI Agent 工作流时，调用分发工具通常面临两大难题：
1. **身份凭证泄露风险**：传统工具需要将用户的平台密码或 Cookie 明文存入环境变量，极易被 Agent 误读或泄露；
2. **输出难以解析**：许多 CLI 工具在终端打印带 ANSI 颜色代码、进度条和杂乱日志的非结构化文本，导致 Agent 难以可靠提取任务状态。

**EasyPost 专为 Agent 优化了底层接口**：
- **零凭证存储**：CLI 不接触任何 Cookie，直接复用当前宿主机 Chrome 浏览器中已有的合法登录会话；
- **纯粹的 JSON 契约**：无论成功或失败，stdout/stderr **仅输出单个严格符合 JSON Schema 的对象**，没有任何进度条杂音；
- **已全面适配 `skills.sh`**：提供标准的 `SKILL.md`，可由 Agent 一键拉取安装。

---

## 二、 环境准备（1 分钟快速配置）

### 1. 确保已在本地安装 Chrome 扩展
在 Chrome 浏览器中安装【快推 EasyPost】扩展，并确保 Chrome 正在运行。

### 2. 全局安装 CLI 并配对系统桥
在宿主机终端执行：
```bash
npm install -g easypost-cli
easypost install-host
easypost doctor --wait 30
```
当返回 `ok: true` 且 `bridge.state: "connected"` 时，说明环境已准备就绪。

### 3. 为你的 Agent 安装 EasyPost Skill
如果你的 Agent 支持 `skills.sh` 协议（如 Claude Code 或 OpenClaw），直接在终端执行：
```bash
npx skills add gybin02/easypost --skill easypost
```
Agent 会自动将 EasyPost 的参数格式与各平台规格字典收录至它的上下文知识库中。

---

## 三、 实战：让 AI Agent 驱动全网自动分发

### 场景演示：撰写一篇科技工具推荐并多平台分发

你只需向你的 AI Agent（以 Claude Code 为例）发送一条自然语言指令：

> **创作者 Prompt：**  
> “帮我写一篇关于『2026年独立开发者效率神器推荐』的自媒体图文文案，提取 3 个核心标签，将文案和本地配图 `/Users/me/Pictures/tools.png` 一键推送到小红书和抖音创作者后台。请使用安全模式先执行填充（fill）。”

### Agent 的思考与自主执行过程：

#### Step 1: Agent 自动调用 `easypost capabilities` 确认可用平台
```json
// Agent 自主探测宿主机扩展已开启的能力
{"ok": true, "command": "capabilities", "result": {"supportedTypes": ["imageText", "shortVideo"], "platforms": ["xiaohongshu", "douyin", "shipinhao", "bilibili"]}}
```

#### Step 2: Agent 自动按小红书和抖音字数规格优化文案
- 小红书标题限制：20字以内；
- 抖音文案：300字以内，自带 `#` 标签。

#### Step 3: Agent 自动生成规范的任务配置文件并管道输入执行
```bash
printf '%s\n' '{
  "type": "imageText",
  "platforms": ["xiaohongshu", "douyin"],
  "data": {
    "title": "独开必看！2026极简生产力神器推荐",
    "content": "给各位独立开发者和创作者安利几个提升幸福感的小工具，告别重复内耗：\n1. AI 脚本辅助；\n2. 极速全平台分发工具 EasyPost；\n3. 本地轻量剪辑助手。\n建议收藏备用！#效率工具 #独立开发 #自媒体运营",
    "tags": ["效率工具", "独立开发", "自媒体运营"]
  },
  "assets": [
    {
      "path": "/Users/me/Pictures/tools.png",
      "role": "media"
    }
  ]
}' | easypost fill
```

#### Step 4: 结果反馈
EasyPost CLI 在数秒内向 Agent 返回：
```json
{
  "ok": true,
  "command": "fill",
  "result": {
    "status": "completed",
    "requestId": "9c82fa81-12c8-47a2-9721-654db70409c1"
  }
}
```

Agent 回复你：
> “已自动为您打开小红书和抖音创作中心，文案、标题和图片素材均已自动填入完毕！请在浏览器标签页核对效果后点击发布即可。”

---

## 四、 自动化进阶：结合定时排程（Cron Job）

如果你希望搭建完全自动化的日常定时播发流水线，可以在本地编写一个简单的 Node.js 或 Shell 脚本：

```bash
#!/bin/bash
# 每日上午 10:00 自动触发生成与填充
node my-ai-generator.js > task.json
easypost fill --input task.json
```

由于 EasyPost 会在本地执行完整的输入校验与素材 SHA256 哈希校验，任何格式不合规或超字数的输入都会在提交前被立刻拦截，确保每一次推送都准确无误。

通过结合 AI Agent 的创意生成能力与 EasyPost 的零风控分发底座，你一个人就能轻松驱动起拥有数十个账号矩阵的超级内容工作站！
