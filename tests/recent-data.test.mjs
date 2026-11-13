import { test } from "node:test"
import assert from "node:assert/strict"
import { createServer } from "node:http"
import { once } from "node:events"
import { mkdtemp, readFile, readdir, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import path from "node:path"

import {
	RECENT_LIMIT,
	isValidTxHash,
	mergeBlocks,
	mergeTxs,
	normalizeBlockHeight,
	normalizeBlockRows,
	normalizeTxRows,
} from "../shared/utils/recent-data.js"
import { collectRecentData, readRecentData } from "../server/utils/recent-data-store.js"

const txHash = (n) => n.toString(16).padStart(64, "0")
const blockRow = (height) => ({ height, hash: "ab".repeat(32), time: "2026-11-09T00:00:00Z", stats: {} })
const txRow = (n, time = "2026-11-09T00:00:00Z") => ({ hash: txHash(n), height: n, time })

async function tempFile() {
	const dir = await mkdtemp(path.join(tmpdir(), "recent-data-"))
	return path.join(dir, "recent-data.json")
}

function jsonResponse(body, status = 200) {
	return { ok: status >= 200 && status < 300, status, json: async () => body }
}

function stubFetch(responses) {
	const calls = []
	const impl = async (url) => {
		calls.push(url)
		const key = url.includes("/block") ? "block" : "tx"
		const value = responses[key]
		if (typeof value === "function") return value(url)
		if (value instanceof Error) throw value
		return jsonResponse(value)
	}
	impl.calls = calls
	return impl
}

test("height must be a positive integer and tx hash 64 hex chars", () => {
	assert.equal(normalizeBlockHeight(42), 42)
	assert.equal(normalizeBlockHeight("42"), 42)
	for (const invalid of [0, -1, 1.5, "0", "-1", "", "1e3", null, undefined, NaN, Infinity, {}]) {
		assert.equal(normalizeBlockHeight(invalid), null, `height ${String(invalid)} must be rejected`)
	}
	assert.ok(isValidTxHash("AB".repeat(32)))
	assert.ok(!isValidTxHash("ab".repeat(31)))
	assert.ok(!isValidTxHash(`${"ab".repeat(32)}ff`))
	assert.ok(!isValidTxHash("zz".repeat(32)))
	assert.ok(!isValidTxHash(123))
})

test("invalid rows are skipped and counted without dropping valid siblings", () => {
	const blocks = normalizeBlockRows([blockRow(5), { height: 0 }, { height: "nope" }, null, blockRow(7)])
	assert.deepEqual(blocks.valid.map((b) => b.height), [5, 7])
	assert.equal(blocks.skipped, 3)

	const txs = normalizeTxRows([txRow(1), { hash: "abc" }, txRow(2), { hash: "AB".repeat(32) }])
	assert.equal(txs.valid.length, 3)
	assert.equal(txs.skipped, 1)
})

test("merging dedupes by height/hash, keeps newest rows and caps at 100", () => {
	const existing = [blockRow(1), blockRow(2), { ...blockRow(2), marker: "old" }]
	const incoming = [{ ...blockRow(2), marker: "new" }, blockRow(3)]
	const merged = mergeBlocks(existing, incoming)
	assert.deepEqual(merged.map((b) => b.height), [3, 2, 1])
	assert.equal(merged[1].marker, "new", "incoming row wins")

	const many = Array.from({ length: 130 }, (_, index) => blockRow(index + 1))
	const capped = mergeBlocks([], many)
	assert.equal(capped.length, RECENT_LIMIT)
	assert.equal(capped[0].height, 130)
	assert.equal(capped.at(-1).height, 31)

	const txs = mergeTxs([{ ...txRow(1), time: "2026-11-08T00:00:00Z" }], [{ ...txRow(1), time: "2026-11-10T00:00:00Z" }, txRow(2)])
	// 传入行覆盖旧行时间，按时间倒序排列。
	assert.deepEqual(txs.map((t) => t.hash), [txHash(1), txHash(2)])
	assert.equal(txs[0].time, "2026-11-10T00:00:00Z")
	// 大小写不同的哈希视为同一条。
	assert.equal(mergeTxs([{ hash: "AB".repeat(32) }], [{ hash: "ab".repeat(32) }]).length, 1)
})

test("a run persists valid rows and reports totals, writes and skips", async () => {
	const file = await tempFile()
	const summary = await collectRecentData({
		file,
		apiBase: "http://api.test/v1/",
		fetchImpl: stubFetch({ block: [blockRow(2), blockRow(1), { height: -1 }], tx: [txRow(1), { hash: "bad" }] }),
	})

	assert.equal(summary.ok, true)
	assert.equal(summary.partial, false)
	assert.equal(summary.block.status, "ok")
	assert.equal(summary.block.received, 3)
	assert.equal(summary.block.written, 2)
	assert.equal(summary.block.skipped, 1)
	assert.equal(summary.block.total, 2)
	assert.equal(summary.tx.written, 1)
	assert.equal(summary.tx.skipped, 1)
	assert.equal(summary.totals.blocks, 2)
	assert.equal(summary.totals.txs, 1)
	assert.match(summary.message, /Blocks: ok/)
	assert.match(summary.message, /skipped 1/)

	const document = JSON.parse(await readFile(file, "utf8"))
	assert.deepEqual(document.blocks.map((b) => b.height), [2, 1])
	assert.equal(document.txs.length, 1)
	assert.equal(document.updatedAt, summary.finishedAt)
	assert.equal(document.lastRun.block.status, "ok")
})

test("runs resume: existing rows are merged and deduped with the new fetch", async () => {
	const file = await tempFile()
	await writeFile(file, JSON.stringify({ blocks: [blockRow(1), blockRow(2)], txs: [txRow(1)] }))

	await collectRecentData({ file, apiBase: "http://api.test", fetchImpl: stubFetch({ block: [blockRow(2), blockRow(3)], tx: [txRow(1), txRow(2)] }) })
	const document = await readRecentData(file)

	assert.deepEqual(document.blocks.map((b) => b.height), [3, 2, 1])
	assert.deepEqual(document.txs.map((t) => t.hash), [txHash(1), txHash(2)])
})

test("a failed source keeps previously stored rows while the other source still lands", async () => {
	const file = await tempFile()
	await writeFile(file, JSON.stringify({ blocks: [blockRow(1)], txs: [txRow(9)] }))

	const timeout = Object.assign(new Error("The operation was aborted due to timeout"), { name: "TimeoutError" })
	const summary = await collectRecentData({ file, apiBase: "http://api.test", fetchImpl: stubFetch({ block: timeout, tx: [txRow(2)] }) })

	assert.equal(summary.ok, true, "one healthy source is enough")
	assert.equal(summary.partial, true)
	assert.equal(summary.block.status, "failed")
	assert.equal(summary.block.reason, "timeout")
	assert.match(summary.message, /timeout/)
	assert.equal(summary.block.total, 1, "cached blocks are preserved")
	assert.equal(summary.tx.written, 1)

	const document = await readRecentData(file)
	assert.deepEqual(document.blocks.map((b) => b.height), [1])
	assert.deepEqual(document.txs.map((t) => t.hash).sort(), [txHash(2), txHash(9)].sort())
})

test("upstream errors are reported distinctly and both sources failing leaves the file untouched", async () => {
	const file = await tempFile()
	await writeFile(file, JSON.stringify({ blocks: [blockRow(1)], txs: [] }))
	const before = await readFile(file, "utf8")

	const summary = await collectRecentData({
		file,
		apiBase: "http://api.test",
		fetchImpl: stubFetch({ block: () => jsonResponse("boom", 503), tx: () => jsonResponse({ not: "an array" }) }),
	})

	assert.equal(summary.ok, false)
	assert.equal(summary.block.reason, "upstream")
	assert.equal(summary.block.httpStatus, 503)
	assert.equal(summary.tx.reason, "upstream")
	assert.match(summary.block.message, /HTTP 503/)
	assert.match(summary.message, /upstream error/)
	assert.equal(await readFile(file, "utf8"), before, "failed run must not rewrite the file")
})

test("writes are atomic and leave no temporary files behind", async () => {
	const file = await tempFile()
	await collectRecentData({ file, apiBase: "http://api.test", fetchImpl: stubFetch({ block: [blockRow(1)], tx: [] }) })
	await collectRecentData({ file, apiBase: "http://api.test", fetchImpl: stubFetch({ block: [blockRow(2)], tx: [] }) })

	const entries = await readdir(path.dirname(file))
	assert.deepEqual(entries, ["recent-data.json"])
	assert.deepEqual((await readRecentData(file)).blocks.map((b) => b.height), [2, 1])
})

test("a corrupted or missing cache file degrades to empty data instead of throwing", async () => {
	const missing = await tempFile()
	const empty = await readRecentData(missing)
	assert.deepEqual(empty.blocks, [])
	assert.deepEqual(empty.txs, [])

	const corrupted = await tempFile()
	await writeFile(corrupted, "{ not json")
	const document = await readRecentData(corrupted)
	assert.deepEqual(document.blocks, [])

	// 损坏文件也应按空文件继续采集并恢复。
	const summary = await collectRecentData({ file: corrupted, apiBase: "http://api.test", fetchImpl: stubFetch({ block: [blockRow(4)], tx: [txRow(4)] }) })
	assert.equal(summary.ok, true)
	assert.deepEqual((await readRecentData(corrupted)).blocks.map((b) => b.height), [4])
})

test("requests use limit/sort and a 5 second timeout without retrying", async () => {
	const file = await tempFile()
	const fetchImpl = stubFetch({ block: [blockRow(1)], tx: [] })
	await collectRecentData({ file, apiBase: "http://api.test/v1", fetchImpl })

	assert.ok(fetchImpl.calls.some((url) => url === "http://api.test/v1/block?limit=100&sort=desc"))
	assert.ok(fetchImpl.calls.some((url) => url === "http://api.test/v1/tx?limit=100&sort=desc"))
	assert.equal(fetchImpl.calls.length, 2, "no retries")
})

test("a hung upstream is classified as timeout after 5 seconds", { timeout: 30000 }, async () => {
	const file = await tempFile()
	const requests = []
	const server = createServer((req) => {
		requests.push(req.url)
		// 保持连接但永不响应，模拟上游挂起。
	})
	server.listen(0, "127.0.0.1")
	await once(server, "listening")
	const started = process.hrtime.bigint()
	try {
		const summary = await collectRecentData({ file, apiBase: `http://127.0.0.1:${server.address().port}/v1` })
		const elapsed = Number(process.hrtime.bigint() - started) / 1e9

		assert.equal(summary.ok, false)
		assert.equal(summary.block.reason, "timeout")
		assert.equal(summary.tx.reason, "timeout")
		assert.ok(elapsed >= 4.5 && elapsed < 15, `timed out in ~5s, took ${elapsed}s`)
		assert.equal(requests.length, 2, "each endpoint is requested exactly once")
	} finally {
		server.closeAllConnections()
		server.close()
	}
})
