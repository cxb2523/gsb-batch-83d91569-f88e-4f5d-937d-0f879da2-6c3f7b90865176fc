# Architecture

WxArticleSaver has two local entry points that share article parsing and formatting:

- The desktop flow runs a `mitmproxy` addon. It observes article pages opened in WeChat, injects an export button, and writes Markdown, HTML, text, metadata, and eligible media to the configured export directory.
- `mcp_server.py` exposes the `read_article(url)` tool over MCP stdio. It fetches an accessible `mp.weixin.qq.com/s...` page directly, validates redirects and response size, extracts the article body with the existing parser helpers, and returns structured metadata plus Markdown. It does not save files or reuse WeChat session credentials. Its environment omits mitmproxy; the shared parsing module treats that desktop-only dependency as optional.

Data flow for MCP:

`agent URL → URL/redirect validation → bounded HTTPS request → existing article selectors → Markdown + metadata → MCP stdio response`

The MCP server uses the official Python MCP SDK. The desktop launchers and their proxy/keychain lifecycle remain separate from the MCP server.

## Media export manifest

`wx_article_saver.save_article` writes `meta.json` with a `resources` section next to the article files:

- `images` and `videos` each contain one row per candidate: sanitized URL, `result` (`saved`/`skipped`/`failed`), `reason` code, optional `local_path`, and optional `detail`.
- `counts` aggregates saved/skipped/failed per kind and in total. Saved rows require a real file, so an all-failure export returns success for the article body while reporting `saved: 0`.
- Image rules: `allowed_image_url` host allowlist and the 25 MiB cap; off-allowlist hosts are `skipped/domain_not_allowed`.
- Video rules: 1 GiB cap, at most 12 candidates per article (extra candidates are `skipped/candidate_limit_exceeded`); encrypted HLS is `skipped/encrypted_hls` and its link is kept in the article placeholders.
- Cookies, Authorization, and `pass_ticket`-like query values are never written to the manifest; URLs and error details are redacted before serialization.
