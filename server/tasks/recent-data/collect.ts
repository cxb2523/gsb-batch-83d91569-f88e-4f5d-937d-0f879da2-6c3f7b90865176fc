// 采集最近 100 条区块与交易并落到本地文件。
//
// 开发服务器下可用 `GET /_nitro/tasks` 查看、`POST /_nitro/tasks/recent-data:collect`
// 运行。生产构建不注册该 HTTP 路由，请改用 `pnpm collect:recent` 或
// `POST /api/recent/collect`。
import { collectRecentData } from "../../utils/recent-data-store.js"

export default defineTask({
	meta: {
		name: "recent-data:collect",
		description: "Fetch the latest 100 blocks and 100 txs from the index API and persist them locally for fallback rendering",
	},
	async run() {
		const config = useRuntimeConfig()
		const summary = await collectRecentData({
			apiBase: config.public.apiBase,
			file: config.recentDataFile,
		})
		console.log(summary.message)
		return { result: summary }
	},
})
