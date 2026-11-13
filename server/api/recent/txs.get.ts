// 读取本地留存的近期交易，供列表页或排查上游故障时核对。
import { readRecentData, resolveRecentDataFile } from "../../utils/recent-data-store.js"

export default defineEventHandler(async (event) => {
	const config = useRuntimeConfig(event)
	const file = resolveRecentDataFile(config.recentDataFile)
	const document = await readRecentData(file)

	setHeader(event, "Cache-Control", "no-store")
	setHeader(event, "X-Recent-Data-Source", "local-file")

	return {
		cached: true,
		updatedAt: document.updatedAt,
		total: document.txs.length,
		txs: document.txs,
		lastRun: document.lastRun,
	}
})
