# Reddit 请求方式：Agent Reach 与 WebMirage 源码对照

日期：2026-11-06。性质：源码研究、实施建议及后续试点结果；以下研究结论保留各自证据范围。

## 结论与证据范围

Agent Reach 值得借鉴的是**在受管理的持久浏览器中复用同站点会话，再由 OpenCLI 发起请求**，以及会话、错误和请求节奏的管理。它不是找到另一套不受限制的 Reddit API，也没有证明增加某个固定 Cookie 字段就能解决 403。WebMirage 当前使用 Python HTTP 客户端直接请求 Reddit `.json` 接口；OpenCLI 对应版本则在 Reddit 页面上下文中以 `credentials: 'include'` 请求同类接口。两者最主要的差别是执行环境和会话管理。具体调用链见下文。

本次读取以下固定版本的一手源码：

- Agent Reach：[`47898829204ad27521d8a1719e3aeca3b8a3e0ca`](https://github.com/Panniantong/Agent-Reach/tree/47898829204ad27521d8a1719e3aeca3b8a3e0ca)，本地位于 `/home/lcarus/reference-repos/Agent-Reach`。
- WebMirage：[`3c0be83c847a98f17a678ea4d5808cd82369400e`](https://github.com/lca1rus01/webmirage/tree/3c0be83c847a98f17a678ea4d5808cd82369400e)。
- OpenCLI：`v1.8.7` 固定提交 [`87b60a36590c3e2a466c37266c3348d73d7f68fe`](https://github.com/jackwener/opencli/tree/87b60a36590c3e2a466c37266c3348d73d7f68fe)。Agent Reach 的版本说明指定新安装使用 **1.8.7**，排除 1.8.8，2.x 尚未完成其业务验收。因此下文请求实现按 `v1.8.7` 阅读，不能拿最新 `main` 代替这个依赖版本；已有安装也可能保留其他版本，实际接入前仍需核对。参见 [Agent Reach 依赖版本说明](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/docs/cloakbrowser.md)。

本轮会话已有的实际检测记录是：用户提供的 11 项 Reddit Cookie 已保存，`reddit_subreddit_posts` 和 `reddit_search` 两个只读接口仍返回 HTTP 403。**保存成功不等于会话有效，403 也不能单独区分 Cookie、权限、出口限制或其他访问策略。** 此记录来自本次会话，不是外部仓库的运行结果。本次研究只读取源码，没有运行 Agent Reach、安装或启动浏览器，也没有增加 Reddit 网络实测；因而不能宣称 Agent Reach 或浏览器路线在当前环境中已成功。

## 实施进度：Reddit 可选浏览器后端已上线

已实现 OpenCLI 2.0.2 / CDP 工作进程，仅开放搜索和社区帖子；固定适配器提交及 SHA256、私有 Unix socket、单并发、32 秒操作上限、空闲回收、持久 profile 和跨进程重启的限流冷却。管理台可切换 HTTP/OpenCLI，启动、更新会话或停止浏览器；统一 MCP 检测历史记录实际后端，切换后旧记录不用于另一后端的健康判定，切回原配置可以恢复同一配置的已有有效证据。

本次真实对照中，HTTP 的两个代表接口均为 403（约 0.83 秒 / 3.47 秒），OpenCLI 同样均为 403（约 10.40 秒 / 6.91 秒）。浏览器路径已能调用，但尚未恢复 Reddit 访问。默认已恢复 HTTP，浏览器按需启动。超时清理和冷却重启测试使用本地假代理与隔离 profile，不向 Reddit 增加请求；会话生命周期验证也仅操作本地浏览器。

部署及回退见 [浏览器工作进程说明](../browser-worker/README.md)。本次没有调整防火墙、Mihomo 配置、现有端口映射或 Mira 服务。后续阶段建议中超出这两个只读动作的部分仍未实施。

## 2026-11-06 评估补充：官方访问安排已改变

Reddit 的 2026-10-08 官方更新说明宣布：2026-10-31 起不再接受新的 public API 访问申请，2026-11-13 停止支持 RSS；未注册或未响应迁移通知的应用自 2027-01-12 起开始失去访问，剩余 public API 访问计划在 2027 年 3 月结束。因此，上述源码中存在 RSS/OAuth 路线，不代表今天适合新建长期依赖；已有获批访问也应单独核对迁移安排。[官方公告](https://support.reddithelp.com/hc/en-us/articles/54353370049684-Changelog-October-8-2026)。这修正了此前把 RSS 作为 Reddit 新备选路线的推荐；下文公共网页搜索/阅读与 Reddit 原生 RSS 是不同路线。

针对当前 WebMirage，建议保留现有 MCP 工具和 HTTP 适配器，优先做**服务器独立浏览器 + OpenCLI 本机 CDP**的小范围试点。官方为无桌面环境提供直接 CDP 连接方式；这条方式无需先依赖 Browser Bridge 扩展，但需逐项验证目标适配器在 CDP 路径的兼容性。[OpenCLI CDP 文档](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/docs/advanced/cdp.md)。个人电脑浏览器适合诊断，不适合作为长期在线前提；自行维护完整 Playwright 平台适配器则会增加本站点解析维护工作。这些是针对当前项目的工程判断，不是已测可用性结论。

本机只读采样约为 4 个逻辑 CPU、7.6 GiB 内存、3.7 GiB available，2 GiB swap 接近用满；swap 占用不能单独证明当前正在频繁换页，但也不能承诺新增浏览器没有资源影响。试点先使用一个浏览器上下文、单并发和空闲回收，测实际资源峰值及既有服务延迟。

第一轮只验证 Reddit 搜索和社区帖子：相同会话、相同代理配置，并核对实际出口；分别记录 HTTP 与浏览器请求结果。对浏览器启动、CDP 断连、登录、限流、HTTP 拒绝和响应结构分别分类。浏览器须在原有健康探针 40 秒时限内有明确结果，避免每次查询冷启动；重启后检查就绪状态，会话保存和恢复按平台结果验证。合法空结果不报故障，异常结构不算通过。只有重复只读测试、会话恢复及资源验证通过，才考虑设为 Reddit 默认后端。其他平台保持现有请求方式；本评估不修改运行服务或网络配置。

## 1. 请求到底怎样发出

### WebMirage：Python 直接调用 JSON 接口

`RedditClient` 使用 `urllib.request`、`HTTPCookieProcessor` 和 `CookieJar`，发送固定的 User-Agent、Accept、Accept-Language，请求超时 15 秒。配置 Cookie 优先，其次尝试从 Chrome/Edge 读取；两者都没有时允许匿名尝试。它不是只发送 `reddit_session`：传入 Cookie 字符串中的各项都会被解析进 CookieJar。字符串导入统一使用 `.reddit.com`、`/`、`secure=True`，无法表达原始 Cookie 各自的 domain/path/expiry/SameSite 等属性。浏览器提取路径则保留所读取 Cookie 对象的属性。参见 [客户端与 Cookie 导入](https://github.com/lca1rus01/webmirage/blob/3c0be83c847a98f17a678ea4d5808cd82369400e/webmirage/platforms/reddit/client.py#L48-L150)、[HTTP 请求与错误处理](https://github.com/lca1rus01/webmirage/blob/3c0be83c847a98f17a678ea4d5808cd82369400e/webmirage/platforms/reddit/client.py#L152-L177)。

站内搜索访问 `/search.json` 或 `/r/<subreddit>/search.json`；社区列表访问 `/r/<subreddit>/<sort>.json`；帖子和评论访问 `/comments/<id>.json`。还有用户资料与动态接口，不能因 Agent Reach 的三个动作存在就认为能够完整替代本项目全部能力。参见 [WebMirage Reddit API 方法](https://github.com/lca1rus01/webmirage/blob/3c0be83c847a98f17a678ea4d5808cd82369400e/webmirage/platforms/reddit/client.py#L183-L397)。

### Agent Reach：通道包装 → OpenCLI → 浏览器上下文

Agent Reach 的 `RedditChannel` 提供 `search`、`read`、`subreddit`，站内后端均为 `opencli`。它构造以下命令，不在自己的 Reddit 通道内实现 HTTP 抓取或 DOM 提取规则：

```text
opencli reddit search <query> --limit <limit> -f json
opencli reddit read <target> --limit 20 -f json
opencli reddit subreddit <name> --limit <limit> -f json
```

其中 `read` 把第一项当作帖子，其余项当作评论，合并为一个标准结果，并在 `raw` 中保留帖子和评论原始数据。参见 [Reddit 通道动作和包装](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/channels/reddit.py#L20-L96)、[OpenCLI 命令执行](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/backends/opencli.py#L61-L82)。

OpenCLI 1.8.7 的 Reddit 实现仍然使用 `.json`：搜索在浏览器内 `fetch('/search.json?...', {credentials:'include'})`，限定社区时改为 `/r/<sub>/search.json`；社区列表同样请求 `/r/<sub>/<sort>.json`；读取帖子请求 `/comments/<id>.json`。它额外使用 `raw_json=1` 等参数。帖子读取的注释说明框架已通过 `navigateBefore` 进入 Reddit origin，无需每次重复导航首页。因此准确说法是**浏览器同源 JSON 请求**，不能描述为单纯 DOM 抓取、官方 OAuth 接入，或发现神秘新接口。参见 [OpenCLI v1.8.7 search](https://github.com/jackwener/opencli/blob/87b60a36590c3e2a466c37266c3348d73d7f68fe/clis/reddit/search.js#L57-L73)、[subreddit](https://github.com/jackwener/opencli/blob/87b60a36590c3e2a466c37266c3348d73d7f68fe/clis/reddit/subreddit.js#L51-L70)、[read 的浏览器上下文](https://github.com/jackwener/opencli/blob/87b60a36590c3e2a466c37266c3348d73d7f68fe/clis/reddit/read.js#L131-L138) 和 [read 的 JSON 请求](https://github.com/jackwener/opencli/blob/87b60a36590c3e2a466c37266c3348d73d7f68fe/clis/reddit/read.js#L204-L225)。

由此可作的推断是：浏览器路线适合检验“相同出口和会话下，实际浏览器上下文能否正常访问”这一假设；源码本身不能证明当前 403 是浏览器指纹导致，更不能证明此路线一定成功。

## 2. 浏览器和 Cookie 管理有什么可借鉴

Agent Reach 使用同一个自有浏览器 profile。`environment()` 先准备站点会话、检查绑定与 Bridge 兼容性，再向 OpenCLI 指定 `OPENCLI_PROFILE`，后台窗口，并清空其他 CDP 目标变量。它的 Bridge 扩展与本地 daemon 是实际依赖，不能只复制三条 CLI 命令就当作完成接入。参见 [浏览器绑定环境](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/browser_binding.py#L19-L45)、[OpenCLI 后端说明](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/backends/opencli.py#L1-L7)。

Cookie 复用有以下具体语义，不能简化成“多复制几个 Cookie”：

1. 从已连接的非专用浏览器通过 Bridge 读取目标站点 Cookie；多个来源均有本站 Cookie 时要求选择来源，不默默挑账号。来源不可用时可继续使用已有 Reach 会话。来源浏览器只读。参见 [来源发现与歧义处理](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/session_reuse.py#L34-L88)、[Bridge Cookie 导出](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/backends/opencli.py#L119-L140)。
2. 按站点 domain 过滤有效 Cookie，携带 name、value、domain、path、secure、httpOnly、expires，并规范化 SameSite；不是克隆整个个人浏览器 profile。参见 [Cookie 过滤与属性映射](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/session_reuse.py#L18-L32)。
3. 导入是同站点快照替换，按 `(name, domain, path)` 比较，过期目标中独有的旧 Cookie，保留其他站点。写入失败会尝试回滚；这属于恢复措施，不能宣称任何失败下均保证原子回滚。参见 [快照替换与回滚](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/session_reuse.py#L113-L130)。
4. 已导入快照通常复用到显式刷新；手工登录和显式阻止状态有优先级。导入记录的 `verified` 初始为 `False`：复制到 Cookie 不代表通过站点业务验证。参见 [prepare 状态控制](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/session_reuse.py#L91-L134)。

运行时通过 CloakBrowser 的公开 `launch_persistent_context` 启动持久上下文、加载扩展，读取配置的代理；watcher 保存会话、跟踪活动，并按默认 600 秒空闲期关闭浏览器。安装或下载 CloakBrowser 失败时，可回退到已安装的系统 Chrome；这是**启动能力回退**，并不是 Reddit 返回 403 后自动换引擎突破封锁。参见 [持久上下文及 watcher](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/browser_watcher.py#L72-L148)、[默认空闲期](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/browser.py#L62)、[安装失败回退 Chrome](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/browser.py#L327-L347)。

## 3. `public_web` 是真实执行路线，且有选择条件

当前固定提交的行为不能概括为“只是建议 Agent 自己搜索”。虽然 Web 通道注释建议已有可用搜索工具的 Agent 优先使用自身工具，但 `public_web.attempt()` **确实构造查询或 URL 并调用 `run_action(WebChannel())`**：搜索追加 Reddit 站点范围，阅读限定在声明的 Reddit URL 范围内；结果再次按范围过滤，阅读还检查明显登录墙和挑战页。Web 通道的搜索后端为 Exa，阅读后端为 Jina、Exa。参见 [公共路线实现](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/public_web.py#L48-L89)、[Web 通道动作](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/channels/web.py#L162-L193)。

默认调度语义是：

| 条件 | 行为 |
|---|---|
| Reddit 通道尚未添加、动作声明 `public_web`，且未指定后端 | 先尝试公共路线，失败后可进入站内后端 |
| Reddit 通道已添加、未指定后端 | 先使用站内后端；仅满足源码的暂时性故障条件且还有时间时，再尝试公共路线 |
| 显式指定 `--backend public-web` | 只走公共路线，输入必须存在公共路由 |
| 显式指定 `--backend opencli` | 只走站内浏览器后端，不自动改成公共搜索 |
| 明确登录墙、平台验证、限流等最终错误 | 停止切换后端；现有 Reddit 冷却也在路线选择前检查 |

参见 [默认优先级与显式选择](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/dispatch.py#L219-L247)、[失败后回退条件](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/dispatch.py#L287-L308)、[最终错误集合](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/result.py#L32-L33)。

`search` 和 `read` 声明公共范围，`subreddit` 没有；裸帖子 ID 也不能直接作为公共网页 URL。公共结果会标记 `access=public`、`content_scope=search_results/page_text`、`completeness_verified=False`。它可以补足公开信息，但不保证站内排序、实时状态、全文或全部评论，不能冒充结构化社区列表接口成功。参见 [Reddit 动作范围](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/channels/reddit.py#L41-L69)、[结果范围声明](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/public_web.py#L79-L88)。

## 4. 错误处理和节流：借鉴设计，不照搬所有判断

Agent Reach 将 OpenCLI 的错误映射为登录、平台验证、限流、上游异常等类别。裸 `HTTP 403 Forbidden` 不会单独被当成需要登录；具有验证码、账户风险等明确提示才归平台拦截，明确登录提示才归登录问题。`opencli_call()` 本身执行一次有时限的命令，不做查询重试。参见 [错误分类与单次调用](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/backends/opencli.py#L16-L82)。

调度器另有站点级冷却、临时故障暂停、搜索间隔和跨进程槽位：默认同站点 2 个浏览器查询、总计 4 个；搜索启动间隔 10 秒；确认限流后冷却 3600 秒。暂停和排队不等于重新发起站点请求。公共提供商错误记录在 Web 路线，不应当成 Reddit 自身限流。Web 提供商实现也存在针对截断传输的一次有界重试，因此应说“站内查询不无脑重试”，不能笼统宣称整个项目绝不重试。参见 [槽位和排队](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/browser_binding.py#L11-L16)、[冷却与节奏](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/dispatch.py#L27-L30)、[冷却状态及搜索间隔实现](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/runtime/dispatch.py#L93-L146)、[Web 截断响应重试](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/channels/web.py#L83-L102)。

WebMirage 已有正确的基础：403 文案明确原因未确认；健康检测区分 `forbidden`、`auth`、`risk`、`rate_limit` 等，并为 Reddit 选择两个只读代表接口。因此无需因引入参考方案而退回“所有 403 都要重新登录”。本项目现有分类主要依赖文本标记，可以进一步借鉴结构化错误码和尝试记录。参见 [现有 403 文案](https://github.com/lca1rus01/webmirage/blob/3c0be83c847a98f17a678ea4d5808cd82369400e/webmirage/platforms/reddit/client.py#L166-L176)、[只读探针与分类](https://github.com/lca1rus01/webmirage/blob/3c0be83c847a98f17a678ea4d5808cd82369400e/webmirage/checks.py#L16-L68)。

参考实现也有需要避免照搬的边界：

- OpenCLI 1.8.7 的搜索和社区列表直接调用 `res.json()`，并用缺失 `data.children` 时返回空数组的方式解析；返回非预期 JSON 时可能和合法零结果混淆。其帖子读取路径则显式检查 HTTP 状态和 JSON 解析异常。WebMirage 的列表解析也使用 `children ... or []`，同样值得补充响应结构验证。参见 [OpenCLI search 解析](https://github.com/jackwener/opencli/blob/87b60a36590c3e2a466c37266c3348d73d7f68fe/clis/reddit/search.js#L65-L74)、[subreddit 解析](https://github.com/jackwener/opencli/blob/87b60a36590c3e2a466c37266c3348d73d7f68fe/clis/reddit/subreddit.js#L59-L70)、[read 检查](https://github.com/jackwener/opencli/blob/87b60a36590c3e2a466c37266c3348d73d7f68fe/clis/reddit/read.js#L204-L225)、[WebMirage 列表解析](https://github.com/lca1rus01/webmirage/blob/3c0be83c847a98f17a678ea4d5808cd82369400e/webmirage/platforms/reddit/client.py#L226-L272)。
- Agent Reach `_reddit()` 将任何空 items 判为 `UPSTREAM_BROKEN`，可能误判正常零命中搜索。应验证响应确为合法空列表后保留成功空结果，将异常结构、登录页和解析失败分别处理。参见 [空结果判断](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/agent_reach/channels/reddit.py#L20-L24)。
- `tests/test_reddit_channel.py` 对 URL 匹配、未配置浏览器不先假设需要登录、登录错误只调用一次、裸 403 不分类为登录、CLI 后端选择提供单元覆盖；其中关键外部行为使用 mock。它不能证明实时 Reddit 请求在本机成功，也不能证明两个项目的字段、分页和评论语义一致。参见 [Reddit 单元测试](https://github.com/Panniantong/Agent-Reach/blob/47898829204ad27521d8a1719e3aeca3b8a3e0ca/tests/test_reddit_channel.py#L11-L67)。

### 依赖最新源码中可另行借鉴的改进

另外读取了 OpenCLI `main` 固定提交 `36bbbd7f60bd361a96e62e417a28ea09d6c2266b`，**它不代表上述 Agent Reach 新装所用的 1.8.7**。此版本把 Reddit 请求集中到 `redditFetchJson()`：先读文本和 Content-Type，区分明确的 network-security HTML、429、其他 HTML、HTTP 错误及 JSON 解析失败；列表读取还验证 `data.children` 必须为数组。这种分层检测比直接 `res.json()` 后取空列表更适合借鉴。但它仍把 JSON HTTP 401/403 统一抛为 `AuthRequiredError`；WebMirage 应保留裸 403 原因未确认的语义，不能完整照搬该映射。参见 [最新参考提交的响应检测](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/clis/reddit/api.js#L16-L42)、[错误映射](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/clis/reddit/api.js#L51-L88)、[Listing 结构验证](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/clis/reddit/api.js#L114-L121)。

### 服务器纯 CDP 接入核对（后续实现依据）

若实现服务器专用浏览器、不开扩展的路线，建议固定 OpenCLI **`36bbbd7f60bd361a96e62e417a28ea09d6c2266b` 整体源码与 adapter**（该提交包版本为 2.0.2，Node 要求 `>=20.18.1`），再以真实只读接口验收。原因是 1.8.7 的 `getBrowserFactory(site)` 仅对登记的 Electron 应用选择 CDP，Reddit CLI 仍走 BrowserBridge；当前提交才按 `OPENCLI_CDP_ENDPOINT` 显式选择 CDPBridge。不能仅给 1.8.7 设置该环境变量就认为 Reddit 已脱离扩展。参见 [1.8.7 工厂选择](https://github.com/jackwener/opencli/blob/87b60a36590c3e2a466c37266c3348d73d7f68fe/src/runtime.ts#L9-L15)、[当前工厂选择](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/src/runtime.ts#L8-L15)、[包版本与 Node 要求](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/package.json#L1-L11)。

当前 CDPBridge 可直连 **page-level** `ws://127.0.0.1:<port>/devtools/page/<id>`，或从 HTTP endpoint 的 `/json` 列表选择页面；它直接发送 `Page.enable`，不依赖 extension/daemon。worker 应创建固定专用 page，传该 page 的 WebSocket URL，并串行处理本站操作；`OPENCLI_CDP_TARGET` 只是评分偏好，不是严格目标过滤，`--profile`、逻辑 `site:reddit` 也不会替 CDPBridge 绑定实际页面。浏览器 profile、Cookie 和页面生命周期由 worker 管理。参见 [CDP 连接](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/src/browser/cdp.ts#L58-L103)、[页面评分](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/src/browser/cdp.ts#L551-L592)。

建议调用参数如下；环境设置 `OPENCLI_CDP_ENDPOINT=<上述专用页面 URL>`，可设 `OPENCLI_SITE_SESSION=persistent`，清除 `OPENCLI_SITE_SLOTS`。CDP 不提供 Bridge 的槽位池；同时配置会被拒绝。持久模式是生命周期选项，不能替代实际浏览器 profile 持久化。参见 [CDP 与槽位限制](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/src/execution.ts#L219-L227)、[模式与逻辑 session](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/src/execution.ts#L600-L645)。

```text
opencli reddit search python --sort new --time all --limit 2 --site-session persistent --trace off -f json
opencli reddit subreddit python --sort new --time all --limit 2 --site-session persistent --trace off -f json
```

搜索支持 `--subreddit python`、排序 `relevance/hot/top/new/comments`；社区排序 `hot/new/top/rising/controversial`，`--time` 仅在社区 top/controversial 时添加到请求中。当前 search 已与 1.8.7 不同：先请求 `/search/` 网页及至多 10 页分页，提取网页结果顺序，再用 `/by_id/t3_<id>,....json` 补详情；仅特定首页标记不兼容才回退旧 `search.json`。因此应限制 limit 并施加外层执行时限，不能把它当一次 JSON 请求。参见 [搜索参数](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/clis/reddit/search.js#L123-L154)、[实际搜索请求链](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/clis/reddit/web-search.js#L2-L92)、[社区参数](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/clis/reddit/subreddit.js#L11-L49)。

当前 CLI 成功 stdout 示例形状为 `{"ok":true,"data":[{"id":"abc","title":"...","subreddit":"r/python","author":"u","score":1,"comments":2,"url":"https://www.reddit.com/r/python/comments/abc/...","created_utc":1,"selftext":"","post_hint":"","url_overridden_by_dest":"","preview_image_url":"","gallery_urls":[]}]}`；社区同形状但得分名为 `upvotes`。合法零结果是 `{"ok":true,"data":[]}`。失败 stdout 示例为 `{"ok":false,"error":{"code":"RATE_LIMITED","message":"Reddit rate limited ... (HTTP 429).","hint":"Wait before making another request; the request was not retried.","exitCode":75}}`。应同时检查退出状态与 `ok`，不能沿用 1.8.7 的裸 JSON 数组/YAML stderr 假设。参见 [成功与失败 wire 格式](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/src/command-output.ts#L16-L48)、[得分字段](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/clis/reddit/search.js#L62-L75)。

Cookie 只通过 worker 的受控 stdin 或内部请求体传入，在 worker 内导入专用 context，不放命令行参数、不回显 stdin、不开 `--verbose` 或 trace；日志白名单只含动作、状态码、耗时、Cookie 数量。上游 error message/hint 需脱敏，不能盲目打印。worker 超时应中止当前页面任务或更换受控页面后再服务下一次调用，避免只杀 CLI 后页面中的 fetch 仍在进行。固定依赖还应隔离个人 `~/.opencli/clis` 的 override 和插件，避免实际运行的 adapter 漂移；源码明确这些用户目录可以包含不同于包基线的覆盖。参见 [用户 adapter 目录](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/src/discovery.ts#L23-L28)、[包基线与覆盖说明](https://github.com/jackwener/opencli/blob/36bbbd7f60bd361a96e62e417a28ea09d6c2266b/src/discovery.ts#L85-L94)。本节是源码核对，尚未证明服务器实际请求成功。

## 5. 适用于 WebMirage 的分阶段建议

以下是后续可以评审的建议，**本次没有实施**。

### 阶段一：保留现有 HTTP 路线，先建立可解释的检测结果

保留当前 403 分类，记录后端、接口、HTTP 状态、响应类型、耗时和检测时间；只记录 Cookie 数量及会话是否存在，不写 Cookie 值。将“配置已保存”“会话已导入”“当前接口验证通过”设为独立状态。先校验 JSON 结构，再把合法空列表视为成功；HTTP 200 的错误页或异常对象不能显示接口通过。限流或验证提示应中止连续主动检测。

验收重点是：当前两个 403 仍准确显示为拒绝访问、原因未确认；异常结构不会变成成功空列表；合法零命中不报上游故障。此阶段不能承诺恢复可用性。

### 阶段二：增加可选的浏览器只读后端，验证环境差异

将请求机制收在一个 Reddit 后端边界内，保留现有 MCP 工具名称和返回契约。先适配 `search`、社区列表、帖子阅读这三个有源码依据的动作，逐项明确字段、排序、分页和评论深度差异；用户资料与动态仍需另外设计。OpenCLI 是可选实现候选，接入前固定已验证版本，不静默升级。

使用持久 profile，显式配置并核对浏览器出口。以同一出口、同一用户会话、同一只读接口比较直接 HTTP 和浏览器内请求，限制并发与频率，保存不含敏感内容的结果摘要。浏览器仍遇到 403 时应报告该路线也失败，不能通过自动换账号、连续换引擎或反复刷新 Cookie 掩盖结果。只有实际只读探针通过，才能把对应动作标记可用。

### 阶段三：规范会话导入与生命周期

提供目标站点的结构化 Cookie 快照导入，保留属性；导入替换该站点旧快照，避免叠加不同会话。来源账号有歧义时要求用户选择；个人浏览器来源只读。导入失败保留恢复能力，已手工登录或主动退出的状态不被自动导入覆盖。复用持久上下文，并增加空闲回收和受控启动；导入完成后继续显示未验证，直到代表接口成功。

### 阶段四：按内容能力提供公共网页补充

若需要公开搜索或网页阅读，可增加明确标记来源的公共路线。返回内容应带 `backend`、`access`、`content_scope`、`completeness_verified` 等信息，并限制域名和 URL。搜索结果或页面文本只能作为公开内容补充，不能假装实现了社区实时列表、精确排序、完整评论树或登录会话验证。明确站点限流和风控时暂停主动自动化；公共搜索提供商限流应单独记录。

## 尚待确认

当前证据不能确定导致 WebMirage 403 的具体因素，也未验证当前出口下浏览器的 Reddit 页面和同源 JSON 请求是否可用。Cookie 的数量不是有效性的充分条件；持久浏览器、CloakBrowser 或 OpenCLI 的存在也不是绕过访问限制的保证。后续是否采用浏览器后端，应由有限的真实只读对照结果、契约兼容性和维护成本共同决定。
