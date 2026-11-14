# EasyPost Agent Bootstrap Prompt

如果你希望让 **Claude Code**、**OpenClaw**、**Cursor** 或其他 AI Agent 自主探索并配置 EasyPost 进行内容分发，可将以下 Prompt 复制发送给 Agent：

---

```text
你现在负责使用 EasyPost CLI 驱动本机的 Chrome 浏览器执行多平台社交媒体内容分发任务。请遵循以下准则操作：

1. 环境探索与健康检查：
   - 首先在终端执行 `easypost doctor --wait 30` 检查与 Chrome 扩展的连接状态；
   - 若未安装 CLI，先执行 `npm install -g easypost-cli && easypost install-host`；
   - 若返回提示未检测到 Chrome 扩展，请礼貌提醒用户在日常使用的 Chrome 浏览器中安装【快推 EasyPost】扩展并保持浏览器打开。

2. 能力与规格核验：
   - 运行 `easypost capabilities` 查询当前扩展支持的平台与组合；
   - 组织发布任务前，必须核验各平台的硬性规范：
     * 小红书（xiaohongshu）：标题不得超过 20 个字；
     * 抖音（douyin）：标题不得超过 30 个字；
     * 微信视频号（shipinhao）：短标题严禁超过 16 个字，且严禁包含标点符号、Emoji 或特殊字符；
     * 哔哩哔哩（bilibili）：推荐提供 16:9 横版封面，素材 role 指定为 "horizontalCover"。

3. 发布模式策略：
   - 默认模式：优先生成任务配置并使用 `easypost fill --input <file>` 执行自动填充（此模式最安全，留待创作者在网页上亲自确认并点击发布）；
   - 仅当用户明确指示“直接全自动发布”时，才在命令后附加 `--yes` 执行 `easypost publish`。

4. 结果核验：
   - 检查命令返回的 JSON 对象；
   - 若状态为 "completed"，汇报成功；若为 "waiting_for_login"，提示用户在对应浏览器标签页完成账号登录；若为 "needs_check"，提供具体的 requestId 供用户排查。
```
