# 九张图表、异动雷达与接口

本表描述 `live` 模式的实际接入。`demo` 模式全部由离线生成器提供，不调用下列服务。最新参数及账号权限参见 [FtShare 官方接口文档](https://market.ft.tech/gateway/doc/)。

| 图表 | FtShare 接口 / 输入 | 关键字段 |
|---|---|---|
| 分钟成交与上证指数 | `ft_v4_stock_realtime_minute_kline`；失败时备用 `ft_v4_etf_realtime_minute_kline`；指数 `ft_v4_index_realtime_minute_kline` | `symbol`、`ts_millis`、`turnover`、`close` |
| 分钟累计成交对比 | 当日同上；历史 `ft_v2_etf_minutes_batch` | 每分钟 `turnover` 累计 |
| 放量日分钟结构 | `ft_v2_etf_minutes_batch`；分类条件使用日度份额和净值 | 分钟成交额、净申购估算 |
| 常态日分钟结构 | 同上 | 完整历史样本的分钟均值 |
| 放量日成交额 | `ft_v2_etf_candlesticks_batch`，当日兼用实时日 K | 日成交额 `turnover` |
| 放量日净申购 | `ft_v2_etf_share` + `ft_v2_etf_net_value` | `fund_share`、`trade_date`、`nav_date`、`unit_nav` |
| 核心 ETF 历史成交额 | `ft_v2_etf_candlesticks_batch` + `ft_v1_index_candlesticks` | `turnover`、`close`、`ts_millis` |
| 核心 ETF 历史净申购 | 份额、净值 + 指数日 K | 净申购估算、指数点位 |
| 宽基日度及累计净流入 | 全部配置成员的份额和净值；可选授权历史补充、核实事件 | 分类流量、覆盖数、区间累计 |

辅助接口：

- `ft_v1_time_trading_calendar`：实际交易日，负责沪深份额记录日对齐和分钟日期窗口。
- `ft_v4_stock_realtime_day_kline`：核心 ETF 当日成交额、收盘价，备用为 `ft_v4_etf_realtime_day_kline`。
- `ft_v2_stock_candlesticks_batch`：核心 ETF 前收盘，备用为 `ft_v2_etf_candlesticks_batch`。
- `ft_v4_index_realtime_day_kline`：指数分钟缺失时辅助确定日期。

通用股票行情接口在本项目服务端中用于 ETF 兼容行情，并保留专用 ETF 接口作为备用；这不意味着资金图采用股票资金流接口。看板净流入由基金份额及原始单位净值估算。

供应商请求只由后台采集器发起。网页API读取已发布快照和共享缓存：`/api/board`、`/api/live`、`/api/history`、`/api/cumulative?date=YYYY-MM-DD`；健康状态为`/api/health`。真实模式`/api/daily?batch=N`返回410，不能触发采集。不提供任意工具名或任意 URL 的透传入口。

历史补充格式、缺失值处理及计算口径见 [data.md](data.md)。

宽基净流入图另叠加 `ft_v1_index_candlesticks` 的上证指数日收盘价（`000001.SH`、`Day`、`close`），按交易日期匹配，使用最右侧独立点位轴。缺失日留空，图下显示所选区间的指数覆盖日期。

## 异动雷达

| 展示 | 已有输入 | 计算／归属 |
|---|---|---|
| 20／60日累计倍数 | 当前`live.bars`、`coverage`与已归档`minutes` | 相同观察时点的累计成交额／历史均值；每套基准满20／60日 |
| 近5分钟倍数 | 同一缓存及分钟历史 | 对应5分钟窗口，不跨午休 |
| 上证涨跌 | `live.closes`和`pre_close` | 与所选观察时点对应 |
| 单只日度净申赎信号 | `core_fund_daily` | 已计算的逐基金份额／净值估算，日期独立标注 |
| 单只ETF行情 | `live.table`与`universe` | 最新行情及名称、代码、分类；与回放时点分开展示 |

雷达、回放和阈值控件不新增FtShare请求。无单只ETF历史分钟基准时不提供单只盘中成交倍数；篮子倍数不能据此解释为某只基金异动。[完整规则](radar-preview.md)
