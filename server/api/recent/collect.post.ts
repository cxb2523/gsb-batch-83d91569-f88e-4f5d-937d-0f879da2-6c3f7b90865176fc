// 手动触发一次近期数据采集。适合 cron / 运维手工补抓。
//
//   curl -X POST -H "x-recent-collect-token: $NUXT_RECENT_COLLECT_TOKEN" \
//     https://explorer.example.com/api/recent/collect
//
// 未配置 NUXT_RECENT_COLLECT_TOKEN 时仅允许本机回环地址调用，避免公开实例被反复
// 触发外部请求。采集本身是幂等的：失败不会覆盖已有文件。
import { getRequestHeader, getRequestIP, setHeader, setResponseStatus } from "h3"

import { collectRecentData, formatRecentSummary } from "../../utils/recent-data-store.js"

function isLoopback(ip) {
	return ip === "127.0.0.1" || ip === "::1" || ip === "::ffff:127.0.0.1"
}

export default defineEventHandler(async (event) => {
	const config = useRuntimeConfig(event)
	const configuredToken = config.recentCollectToken
	const providedToken = getRequestHeader(event, "x-recent-collect-token")

	if (configuredToken) {
		if (providedToken !== configuredToken) {
			setHeader(event, "Cache-Control", "no-store")
			throw createError({ statusCode: 401, statusMessage: "Invalid collect token" })
		}
	} else if (!isLoopback(getRequestIP(event, { xForwardedFor: true }))) {
		throw createError({
			statusCode: 403,
			statusMessage: "Set NUXT_RECENT_COLLECT_TOKEN to allow remote collection",
		})
	}

	const summary = await collectRecentData({
		apiBase: config.public.apiBase,
		file: config.recentDataFile,
	})

	setHeader(event, "Cache-Control", "no-store")
	setHeader(event, "Content-Type", "text/plain; charset=utf-8")
	setResponseStatus(event, summary.ok ? 200 : 503)
	return `${formatRecentSummary(summary)}\n`
})
