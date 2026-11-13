# getcheapapi 内容地图

更新：2026-11-03。数据来源：
- DFS-Ads：DataForSEO Google Ads 搜索量，美国、英文，近 12 个月均值，2026-11 取数；趋势写“12 个月前 → 最近一个月”。Google Ads 会合并近似词（如 `serp api pricing` 与 `serpapi pricing`、`claude code skill(s)` 数字完全相同），两者实际怎么分不知道。
- DFS-Labs：DataForSEO Labs keyword_suggestions，含 KD（0–100），2026-11 取数。
- SERP：WebSearch 代看（只看页型和标题写法，不代表真实名次），2026-11。
- DFS-Ads 本地：同口径分市场取数，2026-11-03：日本（2392/ja）、韩国（2410/ko）、墨西哥（2484/es）、巴西（2076/pt）。日本 SERP 用 Chrome 看 google.co.jp（gl=jp）。
- GPT 证据：还没跑 `chatgpt-growth`，全部写“—”。

## 定位：我们能赢在哪

- 我们不是供应商，结构上做不到“最便宜的 SERP API”，**不拿“最便宜”当卖点**。能赢的是**中立比价**：catalog 里有各家真实单价、计费规则（按次/按行/空结果是否收费/批量上限），还有 `quote` 可以免费复现任何比价。
- 独有事实：AnyAPI 同一端点不同来源最高差 28×（X 搜索）到 200×；DataForSEO SERP 加搜索运算符贵 5×；关键词量在 ~30 个词处出现批量与按词计价的交叉点；402 之后继续发请求、拆批这类真实翻车。前排 SERP 基本是**供应商自写的比价博客**（apiserpent、searlo、cloro、scrapebadger、xpoz、data365），立场明显，中立 + 可复现的比价页有空间。
- 第二个优势是 Agent Skill 形态（Claude Code / Codex），“装了就自动省钱、不超预算”，这条主要靠站外收录（Skill 目录、awesome 列表），自有页很难排上 skill 大词。
- 边界：LLM 文本路由不做（README 已声明）；媒体生成只有 Yir 一个来源，而 Yir 是我方服务，按中立原则不在本站打媒体 API 价格词，由 yir.ai 承接。

## 承接原则

- 比价页 `/<品类>-api-pricing`：承接“<品类> API pricing / cost / price / cheapest / best <品类> API”。必含：各家单价表（含我们不能路由的供应商，用官网公开价并写日期）、按 1k/10k/100k 调用的总价、计费陷阱、“用 `getcheapapi quote` 自己复现”的命令、更新日期、利益披露。
- 替代品页 `/<品牌>-alternatives`：承接“<品牌> alternative(s)”，与比价页互链，不重复单价表，讲迁移、字段差异、各替代品适合谁。
- 首页 `/`：品牌词 + “agent skill / claude code skill for API cost”类长尾。
- 新页默认只做英文；其他语种按市场查过词、有量才建，路径 `/<语种>/<slug>/`，与英文页互标 hreflang，主词用当地写法，不直译。

## 主题簇：X / Twitter API 价格

| 词簇 | 代表词 | 意图 | 人群 | 页型 | 搜索需求（来源） | GPT 证据 | 承接页 | 现状 | 结论 | 下一步 |
|---|---|---|---|---|---|---|---|---|---|---|
| X API 价格 | x api pricing / twitter api pricing / twitter api cost / twitter api price | 找价格 | 做社媒监控、选题、舆情的开发者与 Agent 用户 | 比价页 | x api pricing 880（590→590）；twitter api pricing 720、cost 720、price 720、prices 720；x api cost 320（170→320，涨）；CPC $8–19，KD 30–44（DFS-Ads/Labs） | — | /twitter-api-pricing | 已建（2026-11-02，未发布） | 新建页 | 发布后提交 sitemap/IndexNow，4–8 周后看 GSC |
| X API 免费 | twitter api free / is twitter api free | 了解 | 同上 | 比价页内一节 | 140 + 50（DFS-Labs） | — | /twitter-api-pricing#free | 已建 | 并入承接页 | FAQ：2026-02 起新注册无免费档 |
| twitterapi.io 价格对比 | twitterapi.io / twitterapi io pricing | 导航+比价 | 已在用 twitterapi.io 的人 | 比价页内一节 | 260（140→320）/ 10（DFS-Ads） | — | /twitter-api-pricing | 已建 | 并入承接页 | 写清它在哪类请求上最便宜（单条/档案）、哪类不是（关键词搜索约贵 5×） |
| X 搜索/抓取 API | twitter search api / twitter scraper api | 找工具 | 同上 | 比价页内一节 | 50 / 50（DFS-Ads） | — | /twitter-api-pricing | 已建 | 并入承接页 | — |
| X API 料金（日本） | 主词 x api 料金；次词 x api 無料、x api 従量課金、twitter api 料金、x api pricing | 找价格 | 日本做 X 自动投稿、监控的个人开发者与小团队 | 比价页（日文） | x api 料金 1,000（720→1,000，涨）；x api 無料 320；x api 従量課金 210；x api pricing 210（CPC $21）；twitter api 料金 170；合计约 1,900/月，超过美国 x api pricing 880（DFS-Ads JP 2026-11） | — | /ja/twitter-api-pricing/ | 已建（2026-11-03，未发布） | 新建页 | 发布后看 GSC 日本查询；SERP 意图对（全是官方价解读文章：ownly、uravation、Zenn、Qiita、docs.x.com），无人做官方 vs 第三方读取的比价；联想词：値上げ、無料枠、高い、料金表。必含日元换算、2026-04 URL 投稿涨价、无免费档 |

## 主题簇：SERP API 价格

| 词簇 | 代表词 | 意图 | 人群 | 页型 | 搜索需求（来源） | GPT 证据 | 承接页 | 现状 | 结论 | 下一步 |
|---|---|---|---|---|---|---|---|---|---|---|
| SERP API 价格 | serp api pricing / serp api price / serp api cost | 找价格 | SEO 工具站、做排名监控和 AI 搜索的开发者 | 比价页 | serp api pricing 720（590→320）；serp api price 720；serp api cost 90；KD 19–32（DFS-Ads/Labs）。注：与 `serpapi pricing` 数字合并，可能部分是 SerpApi 品牌导航 | — | /serp-api-pricing | 已建（2026-11-02，未发布） | 新建页 | 发布后提交 sitemap/IndexNow，4–8 周后看 GSC |
| 最便宜 SERP API | cheapest serp api / cheap serp api / best serp api | 比较 | 同上 | 比价页 | 390 / 390（210→140）/ best 170；CPC $18.6–69；KD 31–34（DFS） | — | /serp-api-pricing | 已建 | 并入承接页 | 标题写“cheapest SERP API”，正文写“按你的量谁最便宜”，不自称最便宜 |
| SerpApi 替代品 | serpapi alternative(s) / serp api alternatives | 比较 | SerpApi 现有用户，嫌贵或限速 | 替代品页 | 140（90→480，涨）；CPC $32；KD 8–9（DFS） | — | （待建）/serpapi-alternatives | 未建 | 新建页 | P2：KD 低、CPC 高、在涨 |
| Google 搜索 API 价格 | google search api pricing / google web search api pricing | 找价格 | 原先用 Google Custom Search 的开发者 | 比价页内一节 | 260（320→140）（DFS） | — | /serp-api-pricing#pick | 已建 | 并入承接页 | 写清官方 Custom Search JSON API 的现状与替代 |
| Brave 搜索 API 价格 | brave search api pricing | 找价格 | 同上 | 比价页内一节 | 480（90→170），KD 9（DFS） | — | /serp-api-pricing#volume | 已建 | 并入承接页 | Brave 用自有索引，不是 Google 结果，单列一行说明 |
| SERP API MCP | serp api mcp / serp mcp | 找工具 | 用 Agent 的开发者 | 首页/比价页 FAQ | 70 / 10（DFS） | — | /serp-api-pricing#agents | 未建 | 并入承接页 | 写 Skill 与 MCP 的区别 |

## 主题簇：Reddit / TikTok / Google Trends API

| 词簇 | 代表词 | 意图 | 人群 | 页型 | 搜索需求（来源） | GPT 证据 | 承接页 | 现状 | 结论 | 下一步 |
|---|---|---|---|---|---|---|---|---|---|---|
| Reddit API 价格 | reddit api pricing / reddit api cost | 找价格 | 做社区监控、选题的开发者 | 比价页 | 390（590→260）+ 210；KD 0；CPC $12（DFS） | — | /reddit-api-pricing | 已建（2026-11-02，未发布） | 新建页 | 发布后提交 sitemap/IndexNow，4–8 周后看 GSC |
| Reddit API 关停 | reddit api shutdown / reddit api alternative / reddit api key | 了解/找工具 | 被 Reddit 关停影响的开发者 | 比价页内一节 | 未查量（2026-09-30 公告后的新事件） | — | /reddit-api-pricing#official | 已建 | 并入承接页 | 下次取数时补查这几个词的量；量大就把 H1 改成以关停为主 |
| Reddit 搜索 API | reddit search api / reddit api alternative | 找工具 | 同上 | 比价页内一节 | 140 / 20（DFS） | — | /reddit-api-pricing#compare | 已建 | 并入承接页 | — |
| Google Trends API | google trends api / google trends api pricing / pytrends alternative | 找工具 | 做选题和趋势监控的开发者 | 比价页 | 1,300（1,600→880）；pricing 20；pytrends alternative 10；CPC $13.7（DFS） | — | （待建）/google-trends-api | 未建 | 新建页 | P2：官方 Trends API alpha 的现状 + 第三方单价（AnyAPI $0.002、GoAnyAPI 按词） |
| TikTok API | tiktok api / tiktok search api / tiktok scraper api | 找工具 | 做短视频选题的开发者 | — | 1,900（意图多为官方开放平台）；search 40；scraper 30（DFS） | — | — | — | 放弃主词，长尾观察 | 主词意图不符（官方 SDK/登录）；搜索类长尾量太小，等 GPT 侧证据 |

## 主题簇：SEO 数据 API（关键词量、外链、DR、流量）

| 词簇 | 代表词 | 意图 | 人群 | 页型 | 搜索需求（来源） | GPT 证据 | 承接页 | 现状 | 结论 | 下一步 |
|---|---|---|---|---|---|---|---|---|---|---|
| DataForSEO 价格与用法 | dataforseo pricing / dataforseo api / dataforseo serp api | 找价格 | 用 DataForSEO 做 SEO 工具的开发者 | 价格解读文章 | api 320；pricing 70（40→140）；serp api 70（DFS） | — | （待建）/dataforseo-pricing | 未建 | 新建页 | P3：独有内容——queued vs live、每批 ≤1,000 词同价、运算符 5×、什么时候 GoAnyAPI 更便宜 |
| DataForSEO MCP | dataforseo mcp | 找工具 | Agent 用户 | 价格解读页内一节 | 210（90→260，涨）（DFS） | — | /dataforseo-pricing#mcp | 未建 | 并入承接页 | 讲 MCP 默认 live 调用的成本，以及 Skill 怎样走 queued/批量 |
| SEO API 价格 | seo api / seo data api / semrush api pricing / ahrefs api pricing | 比较 | SEO 工具开发者 | 比价页 | seo api 320（590→110，跌）；seo data api 110；semrush api pricing 170；ahrefs api pricing 90；CPC $20–30（DFS） | — | （待建）/seo-api-pricing | 未建 | 新建页 | P3：Semrush/Ahrefs API 门槛价 vs DataForSEO/GoAnyAPI 按次 |
| 外链 API | backlink api / backlinks api | 找工具 | 同上 | 比价页内一节 | 110（40→90）；CPC $30；KD 22（DFS） | — | /seo-api-pricing#backlinks | 未建 | 并入承接页 | 写批量 bulk 端点 vs 单域查询的价差 |
| 关键词 API | keyword api / keyword research api / keyword search volume api / google keyword planner api | 找工具 | 同上 | 比价页内一节 | 70 / 50 / 30 / 70（DFS） | — | /seo-api-pricing#keywords | 未建 | 并入承接页 | 写清 30 词交叉点 |
| 排名查询 API | keyword rank checker api / google keyword ranking api / serp tracking api | 找工具 | 同上 | 比价页内一节 | 110 / 110 / 170（DFS），KD 6–21 | — | /serp-api-pricing#rank-tracking | 未建 | 并入承接页 | 按“每天追 100 个词”算月成本 |
| DR / 流量 API | domain rating api / website traffic api / similarweb api pricing | 找工具 | 同上 | 比价页内一节 | 10 / 40 / 70（DFS） | — | /seo-api-pricing | 未建 | 并入承接页 | — |

## 主题簇：Agent Skill（品牌与分发）

| 词簇 | 代表词 | 意图 | 人群 | 页型 | 搜索需求（来源） | GPT 证据 | 承接页 | 现状 | 结论 | 下一步 |
|---|---|---|---|---|---|---|---|---|---|---|
| 品牌词 | getcheapapi | 导航 | — | 首页 | 10（0→10）（DFS） | — | / | 已上线 | 保持 | — |
| Claude Code / Codex Skill 大词 | claude skills / claude code skills / agent skills / codex skills / best claude code skills | 了解/找工具 | 用编码 Agent 的开发者 | 站外（目录、awesome 列表） | 40,500（33,100→18,100）；12,100（6,600→2,900）；8,100（720→6,600）；5,400（90→2,900）；best 590 KD 12（DFS） | — | 站外 | 未收录 | 不做自有页，做站外 | P2：交 `backlink`：提交 claudemarket.ai、claudeskills.info、claudemarketplaces.com、awesome-claude-code 等目录与列表 |
| SEO/营销 Skill | claude code marketing skills / marketing skills for claude code / seo skills for claude code | 找工具 | 用 Agent 做 SEO 的人 | 站外 + 首页一节 | 90 / 70（DFS）；SERP 全是“最佳 SEO Skill”列表 | — | 站外；首页 | 未收录 | 站外为主 | 争取进入这些列表，定位“给 SEO Skill 提供便宜数据的那一层” |

## 待验证候选

- **Agent 花钱失控类问题**（api spending limit、reduce api costs、ai agent api cost、api cost comparison）：Google 侧均为 0–10，可能是 GPT 侧需求。下一步交 `chatgpt-growth` probe：“how do I stop my coding agent from overspending on paid APIs”“cheapest way to get Twitter data for an AI agent”“cheapest SERP API for an agent”，每题 3–5 次。
- **ValueSERP / ScaleSERP**：valueserp 140、scaleserp 40，有人在找。这两个服务现在的状态不知道（是否停服、并入其他产品），核实后决定在 /serpapi-alternatives 里加一节，还是放弃。
- **Bing 搜索 API 停服**：bing search api 720（880→480），bing search api alternative 10。/serp-api-pricing#pick 已加一行（2025-08 退役、AnyAPI/GoAnyAPI 单价）；是否值得单独建页，看 SERP 意图后再定。
- **多语种（2026-11-03 已查日韩墨巴）**：只有日本的 X API 价格簇有量，已进主表。其余结论：韩国 x api 가격 90、트위터 api 가격 40，太小；墨西哥、巴西本地写法（precio/preço）全是 0，英文写法也只有 10–70，由英文页承接；Reddit API、SERP API 的本地写法各市场都 ≤30。各市场 `serp api`/`serpapi` 有 720–2,900，基本是 SerpApi 品牌导航，由英文 /serp-api-pricing 承接。`dataforseo` 品牌词在日本（320→1,300）和巴西（170→1,600）上涨，P3 的 /dataforseo-pricing 可以提前；中文主要搜索在百度，未查。

## 派活清单

| 优先级 | 事项 | 证据 | 交给 | 完成标准 |
|---|---|---|---|---|
| 已完成 | 新建 /twitter-api-pricing | X API 价格簇合计约 3–4k/月，CPC $8–19；有独有比价数据 | `landing-page-designer` | 单价表带日期；按 1 万条推文算各家总价；附可复现的 `quote` 命令；FAQ 写免费档；有利益披露 |
| 已完成 | 新建 /serp-api-pricing | SERP 价格簇约 2k/月，CPC $18+；前排全是供应商自写比价 | `landing-page-designer` | 至少 7 家单价，按 1k/10k/100k 算总价；陷阱一节（运算符 5×、失败自动切到更贵来源）；不自称最便宜 |
| 已完成 | 新建 /reddit-api-pricing | 600/月，KD 0 | `landing-page-designer` | 官方价核实到出处；第三方按 1k 条算 |
| 已完成 | 新建 /ja/twitter-api-pricing/（日文 X API 料金页） | 日本簇约 1,900/月且在涨；SERP 全是官方价解读，无比价 | `landing-page-designer` | 主词 X API 料金 进 title/H1；官方料金表 + 第三方比价 + 日元换算 + 値上げ/無料枠 FAQ；与英文页互标 hreflang |
| P2 | 新建 /serpapi-alternatives | 140→480 在涨，KD 8，CPC $32 | `landing-page-designer` | 与 /serp-api-pricing 互链，不重复单价表 |
| P2 | 新建 /google-trends-api | 1,300/月，CPC $13.7 | `landing-page-designer` | 官方 alpha 现状、pytrends 现状、第三方单价 |
| P2 | Skill 目录与 awesome 列表收录 | skill 词 4 万+/月，而且是列表型 SERP | `backlink` | 提交 5 个以上目录/列表，并在台账记录收录情况 |
| P2 | GPT 侧 probe | 待验证候选里的问题 | `chatgpt-growth` | 每题 3–5 次，回填本表“GPT 证据”列 |
| P3 | 新建 /dataforseo-pricing（含 MCP 一节） | api 320、mcp 210 在涨 | `seo-article-copywriter` | 写清 queued/live、批量、运算符的实测价差 |
| P3 | 新建 /seo-api-pricing | seo api 320、semrush api pricing 170、backlink api 110 | `landing-page-designer` | 关键词/外链/DR/流量四节，各有单价表 |

## 放弃 / 已完成

- **LLM 路由与 LLM API 价格**（litellm 27,100、openrouter alternative 880、llm router 720、openai/claude/gemini api pricing 千到万级）：README 明确不做 LLM 路由，没有可路由的事实，放弃。
- **媒体生成 API 价格**（cheapest image/video generation api、nano banana / veo / sora api pricing、fal ai pricing、elevenlabs api pricing）：本站只有 Yir 一个来源，且 Yir 是我方服务，按中立原则不在本站做；交给 yir.ai 承接。
- **API 市场 / 统一 API**（api marketplace 590、unified api 170、api aggregator 90、rapidapi alternative 20）：意图是找 API 市场或集成平台，我们不是，放弃。
- **主流品牌导航词**（serper api 1,000、google search api 2,400、tiktok api 1,900、apify pricing 390）：搜的人要找的是官网，意图不符；只在比价页里覆盖对应长尾。
- **中文价格页**（/zh/ 下三页，2026-11-03 由另一会话按用户要求翻译）：中文市场没查过词，主要搜索在百度。上线后看 GSC 的中文查询，没有曝光就考虑 noindex 或合并。
