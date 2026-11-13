import assert from "node:assert/strict"
import { createServer } from "node:http"
import { spawn } from "node:child_process"
import { once } from "node:events"
import { mkdtemp, readFile, writeFile } from "node:fs/promises"
import { randomBytes } from "node:crypto"
import { tmpdir } from "node:os"
import path from "node:path"

const block = (height) => ({
	height,
	hash: "ab".repeat(32),
	time: "2026-11-09T00:00:00Z",
	proposer: { moniker: "Cached fixture validator", cons_address: "nubitvalcons1234567890" },
	stats: { block_time: 1000, bytes_in_block: 128, blobs_count: 0, blobs_size: 0, events_count: 0, fee: "1000", tx_count: 1 },
})

const requests = []
let mode = "ok"
const api = createServer((req, res) => {
	const url = new URL(req.url, "http://localhost")
	requests.push(url.pathname + url.search)
	res.setHeader("Content-Type", "application/json")
	if (mode === "fail") {
		res.statusCode = 500
		return res.end('{"message":"boom"}')
	}
	if (url.pathname.endsWith("/block/count")) return res.end("400")
	if (url.pathname.endsWith("/block")) {
		const rows = [block(500), block(499)]
		// 采集请求（limit=100）额外混入非法行，验证跳过逻辑；页面请求保持干净。
		if (url.searchParams.get("limit") === "100") rows.push({ height: -3 }, { height: "oops" })
		return res.end(JSON.stringify(rows))
	}
	if (url.pathname.endsWith("/tx")) {
		const rows = [{ hash: "cd".repeat(32), height: 500, time: "2026-11-09T00:00:00Z" }]
		if (url.searchParams.get("limit") === "100") rows.push({ hash: "nothex" })
		return res.end(JSON.stringify(rows))
	}
	if (url.pathname.endsWith("/count")) return res.end("0")
	res.end("[]")
})
api.listen(0, "127.0.0.1")
await once(api, "listening")
const apiBase = `http://127.0.0.1:${api.address().port}/v1`

async function startApp(extraEnv) {
	const child = spawn(process.execPath, [".output/server/index.mjs"], {
		env: {
			...process.env,
			HOST: "127.0.0.1",
			PORT: "0",
			NUXT_SITE_URL: "https://cache-test.example.com",
			NUXT_SITE_INDEXABLE: "false",
			NUXT_PUBLIC_API_BASE: apiBase,
			NUXT_APP_SECRET: randomBytes(32).toString("hex"),
			...extraEnv,
		},
		stdio: ["ignore", "pipe", "pipe"],
	})
	let logs = ""
	child.stderr.on("data", (data) => (logs += data))
	const base = await new Promise((resolve, reject) => {
		const timeout = setTimeout(() => {
			child.kill()
			reject(new Error(`startup timeout: ${logs}`))
		}, 20000)
		child.stdout.on("data", (data) => {
			logs += data
			const match = logs.match(/Listening on (http:\/\/[^\s]+)/)
			if (match) {
				clearTimeout(timeout)
				resolve(match[1])
			}
		})
		child.once("error", reject)
		child.once("exit", (code) => {
			clearTimeout(timeout)
			reject(new Error(`exited ${code}: ${logs}`))
		})
	})
	return { base, child, logs: () => logs }
}

async function stopApp(app) {
	if (app.child.exitCode !== null) return
	app.child.kill("SIGTERM")
	await once(app.child, "exit")
}

const dataDir = await mkdtemp(path.join(tmpdir(), "recent-e2e-"))
const dataFile = path.join(dataDir, "recent-data.json")
let app
try {
	/* ---------- 1. 采集：成功路径 ---------- */
	app = await startApp({ NUXT_RECENT_DATA_FILE: dataFile, NUXT_RECENT_COLLECT_TOKEN: "secret-token" })

	const collect = await fetch(`${app.base}/api/recent/collect`, {
		method: "POST",
		headers: { "x-recent-collect-token": "secret-token" },
		signal: AbortSignal.timeout(20000),
	})
	const collectText = await collect.text()
	assert.equal(collect.status, 200, collectText)
	assert.match(collectText, /\[recent-data\] OK/, collectText)
	assert.match(collectText, /block: ok/)
	assert.match(collectText, /received 4, written 2, skipped 2/)
	assert.match(collectText, /tx: ok/)
	assert.match(collectText, /received 2, written 1, skipped 1/)
	assert.match(collectText, /totals: blocks=2 txs=1/)

	const document = JSON.parse(await readFile(dataFile, "utf8"))
	assert.deepEqual(document.blocks.map((b) => b.height), [500, 499])
	assert.equal(document.txs.length, 1)

	// 未授权请求被拒绝
	const denied = await fetch(`${app.base}/api/recent/collect`, { method: "POST", signal: AbortSignal.timeout(10000) })
	assert.equal(denied.status, 401)
	const wrongToken = await fetch(`${app.base}/api/recent/collect`, {
		method: "POST",
		headers: { "x-recent-collect-token": "nope" },
		signal: AbortSignal.timeout(10000),
	})
	assert.equal(wrongToken.status, 401)

	const recentApi = await fetch(`${app.base}/api/recent/blocks`, { signal: AbortSignal.timeout(10000) })
	assert.equal(recentApi.headers.get("x-recent-data-source"), "local-file")
	assert.match(recentApi.headers.get("cache-control"), /no-store/)
	const recentBody = await recentApi.json()
	assert.equal(recentBody.total, 2)
	assert.equal(recentBody.cached, true)

	const recentTxs = await (await fetch(`${app.base}/api/recent/txs`, { signal: AbortSignal.timeout(10000) })).json()
	assert.equal(recentTxs.total, 1)
	assert.equal(recentTxs.txs[0].hash, "cd".repeat(32))

	/* ---------- 2. /blocks：API 正常时不读本地文件 ---------- */
	const healthy = await fetch(`${app.base}/blocks`, { signal: AbortSignal.timeout(20000) })
	const healthyHtml = await healthy.text()
	assert.equal(healthy.status, 200, `${healthyHtml.slice(0, 2000)}\n---LOGS---\n${app.logs()}`)
	assert.ok(!healthyHtml.includes("Index API unavailable"), "healthy page must not show cache notice")
	assert.ok(!requests.some((url) => url.includes("/api/recent")), "healthy page must not read local cache")
	assert.match(healthyHtml, /Cached fixture validator|Blocks/)

	/* ---------- 3. /blocks：API 故障时回退本地文件 ---------- */
	mode = "fail"
	const degraded = await fetch(`${app.base}/blocks`, { signal: AbortSignal.timeout(20000) })
	const degradedHtml = await degraded.text()
	assert.equal(degraded.status, 200, degradedHtml.slice(0, 400))
	assert.ok(degradedHtml.includes("Index API unavailable"), "cache notice must be visible")
	assert.ok(degradedHtml.includes("Cached fixture validator"), `cached rows must render: ${degradedHtml.slice(0, 3000)}\n---LOGS---\n${app.logs()}`)
	assert.ok(degradedHtml.includes("500"), "cached block height must render")
	assert.ok(!degradedHtml.includes("Genesis"), "cached rows keep their proposer instead of falling back to Genesis")

	/* ---------- 4. 上游恢复后重新采集：合并去重与失败不覆盖 ---------- */
	mode = "ok"
	const rerun = await fetch(`${app.base}/api/recent/collect`, {
		method: "POST",
		headers: { "x-recent-collect-token": "secret-token" },
		signal: AbortSignal.timeout(20000),
	})
	assert.equal(rerun.status, 200)
	const merged = JSON.parse(await readFile(dataFile, "utf8"))
	assert.equal(merged.blocks.length, 2, "same heights must not duplicate")

	await stopApp(app)

	/* ---------- 5. 全部上游失败时文件保持不变 ---------- */
	const before = await readFile(dataFile, "utf8")
	mode = "fail"
	app = await startApp({ NUXT_RECENT_DATA_FILE: dataFile, NUXT_RECENT_COLLECT_TOKEN: "secret-token" })
	const failed = await fetch(`${app.base}/api/recent/collect`, {
		method: "POST",
		headers: { "x-recent-collect-token": "secret-token" },
		signal: AbortSignal.timeout(30000),
	})
	const failedText = await failed.text()
	assert.equal(failed.status, 503, failedText)
	assert.match(failedText, /FAILED/)
	assert.match(failedText, /block: failed \(upstream error\)/)
	assert.equal(await readFile(dataFile, "utf8"), before, "failed collection must not rewrite the file")

	/* ---------- 6. 无本地文件时页面仍可渲染 ---------- */
	await stopApp(app)
	app = await startApp({ NUXT_RECENT_DATA_FILE: path.join(dataDir, "absent.json") })
	const empty = await fetch(`${app.base}/blocks`, { signal: AbortSignal.timeout(20000) })
	const emptyHtml = await empty.text()
	assert.equal(empty.status, 200)
	assert.ok(emptyHtml.includes("no cached data is available"), "empty-state notice")

	console.log("PASS: collection summary, validation/skips, atomic resume, /blocks cache fallback and healthy path")
} finally {
	if (app) await stopApp(app)
	api.close()
	api.closeAllConnections()
}
