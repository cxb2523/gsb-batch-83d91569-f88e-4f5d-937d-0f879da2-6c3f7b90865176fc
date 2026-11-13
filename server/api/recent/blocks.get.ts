// 读取本地留存的近期区块。仅在外部索引 API 不可用时由 /blocks 页面兜底使用。
import { readRecentData, resolveRecentDataFile } from "../../utils/recent-data-store.js"

export default defineEventHandler(async (event) => {
	const config = useRuntimeConfig(event)
	const file = resolveRecentDataFile(config.recentDataFile)
	const document = await readRecentData(file)

	// 兜底数据是"最后一次成功采集"的快照，不能被 CDN 或浏览器缓存成实时数据。
	setHeader(event, "Cache-Control", "no-store")
	setHeader(event, "X-Recent-Data-Source", "local-file")

	return {
		cached: true,
		updatedAt: document.updatedAt,
		total: document.blocks.length,
		blocks: document.blocks,
		lastRun: document.lastRun,
	}
})
