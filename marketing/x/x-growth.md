# x-growth 项目配置：getcheapapi

## 账号与文件
- 发帖账号：待定（主页简介需写明 getcheapapi 作者身份，置顶第一条主帖）
- 台账：`marketing/x/reply-log.csv`
- 默认查询：`marketing/x/queries.txt`
- 可用配图与自有数据：官网三张价格页的对比表（截图即可作配图）、`getcheapapi quote` 终端输出、`site/public/og.png`

## 价格真源
- 官网价格页 `site/twitter-api-pricing/`、`site/serp-api-pricing/`、`site/reddit-api-pricing/`，页面写明核对日期；引用前看日期，超过 7 天先用 `getcheapapi quote` 或 `prices refresh` 复核。
- 官方/基准价：X 取 docs.x.com 定价页，Reddit 取其 2023 年 API 公告。
- 不引用：限时折扣、新号赠送额度、没写在价格页上的上游内部价。

## 措辞
- 品类词：price router / cheapest route for data APIs；不说 "LLM router"（不做 LLM 文本路由）。
- 只说事实和口径，不说某家“坑”“骗”；讲 failover 时说“默认会重试到更贵的源”。
- 身份写法轮换：`I built getcheapapi (open source)` / `Disclosure: I make getcheapapi` / `(I'm the author of getcheapapi)`；页面上部分链接是推荐链接，自回复里提一句。

## 链接
- 默认指向具体价格页，其次 GitHub 仓库；首页最后。
- 发帖时段：英文主帖 UTC 13:00–16:00（美东上午）；日文主帖 UTC 00:00–03:00。
- 主帖：正文不放链接；链接与身份披露放发帖后立刻补的第一条自回复。

## 发帖限制
- 待定（建议起步：带链接条数滚动 24 小时 ≤3，条间隔 ≥30 分钟，同一作者 7 天冷却）。
