#!/usr/bin/env node
// 独立运行近期数据采集，适合 cron / CI。不启动 Nuxt 服务，也不需要构建产物。
//
//   node scripts/collect-recent-data.mjs
//   NUXT_PUBLIC_API_BASE=... NUXT_RECENT_DATA_FILE=... node scripts/collect-recent-data.mjs
//
// 退出码：0 全部成功；1 全部失败（未写入）；2 部分成功（另一来源已落盘）。
import { collectRecentData, formatRecentSummary, resolveRecentApiBase, resolveRecentDataFile } from "../server/utils/recent-data-store.js"

const summary = await collectRecentData({
	apiBase: resolveRecentApiBase(),
	file: resolveRecentDataFile(),
})

console.log(formatRecentSummary(summary))

if (!summary.ok) process.exitCode = 1
else if (summary.partial) process.exitCode = 2
