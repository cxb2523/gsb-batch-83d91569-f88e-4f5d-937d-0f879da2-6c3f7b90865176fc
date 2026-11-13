# 本地 HTML 样例（离线测试夹具）

这些文件是**本地静态样例**，只用于离线验证 `src/g2_collector.py` 的结局判定，
不代表真实 G2 链路已跑通。测试通过假 fetcher（`tests/test_g2_collector.py`
中的 `FakeFetcher` / `FakeResponse`）加载它们，全程不触网。

| 文件 | 模拟场景 | 假 HTTP 状态 | 期望结局 |
| --- | --- | --- | --- |
| `normal.html` | 正常评论页，含等待元素 `.star-wrapper__desc`，3 个 h2、2 个 h3 | 200 | `success`（等待元素命中） |
| `blocked_403.html` | Cloudflare 拦截页（"Sorry, you have been blocked" + 挑战脚本） | 403 | `blocked`（标题数为 0） |
| `wait_missing.html` | 200 页面但故意不含 `.star-wrapper__desc`，2 个 h2、1 个 h3 | 200 | `wait_timeout`（标题保留但不计入成功） |
| （无对应文件） | 请求异常：假 fetcher 直接抛 `requests.ConnectionError` | — | `request_error`（不中断后续页） |

请求异常页不需要 HTML 文件——它由假 fetcher 抛出异常来模拟，
见 `tests/test_g2_collector.py` 的 `build_routing()`。

## 运行

```bash
# 单元测试（20 个用例，隔离模式）
python -I tests/test_g2_collector.py

# 四类结局的汇总输出演示
python -I tests/demo_fixtures.py
```

演示的完整期望输出保存在 `tests/expected_output.txt`。
