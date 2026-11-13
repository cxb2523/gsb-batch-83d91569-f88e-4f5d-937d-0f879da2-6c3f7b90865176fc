// 近期区块/交易的本地留存。负责抓取、校验、合并、原子写入与本次运行摘要。
// 只依赖 Node 标准库和 shared 中的纯合并规则，可被 Nitro 任务、兜底接口和
// 独立脚本复用。
import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises"
import path from "node:path"
import { randomUUID } from "node:crypto"

// 相对路径而非 `#shared` 别名：同一模块也被独立 Node 脚本复用。
import { RECENT_LIMIT, mergeBlocks, mergeTxs, normalizeBlockRows, normalizeTxRows } from "../../shared/utils/recent-data.js"

export const RECENT_FETCH_TIMEOUT_MS = 5000
const DEFAULT_RELATIVE_FILE = ".data/recent-data.json"
const DEFAULT_API_BASE = "https://alphatestnet-api.nubit.org/v1"

export function resolveRecentDataFile(configured) {
	const value = configured || process.env.NUXT_RECENT_DATA_FILE || DEFAULT_RELATIVE_FILE
	return path.isAbsolute(value) ? value : path.resolve(process.cwd(), value)
}

export function resolveRecentApiBase(configured) {
	const value = configured || process.env.NUXT_PUBLIC_API_BASE || DEFAULT_API_BASE
	return String(value).replace(/\/$/, "")
}

function emptyDocument() {
	return { version: 1, updatedAt: null, blocks: [], txs: [], lastRun: null }
}

// 兼容缺失文件、损坏 JSON 和旧格式：任何异常都回退为空文档，避免页面兜底崩溃。
export async function readRecentData(file) {
	let raw
	try {
		raw = await readFile(file, "utf8")
	} catch (error) {
		if (error?.code === "ENOENT") return emptyDocument()
		throw error
	}
	try {
		const parsed = JSON.parse(raw)
		return {
			version: 1,
			updatedAt: typeof parsed?.updatedAt === "string" ? parsed.updatedAt : null,
			// 读取时同样校验并按高度/哈希去重，防止手工编辑或旧文件绕过规则。
			blocks: mergeBlocks([], parsed?.blocks),
			txs: mergeTxs([], parsed?.txs),
			lastRun: parsed?.lastRun ?? null,
		}
	} catch {
		return emptyDocument()
	}
}

// 先写同目录临时文件再 rename；rename 覆盖目标，失败时不会留下半份文件。
export async function writeRecentDataAtomic(file, document) {
	const directory = path.dirname(file)
	await mkdir(directory, { recursive: true })
	const temporary = path.join(directory, `.${path.basename(file)}.${randomUUID()}.tmp`)
	try {
		await writeFile(temporary, `${JSON.stringify(document, null, "\t")}\n`, "utf8")
		await rename(temporary, file)
	} catch (error) {
		await unlink(temporary).catch(() => {})
		throw error
	}
}

function classifyFailure(error) {
	const name = error?.name
	const code = error?.code
	if (name === "TimeoutError" || name === "AbortError" || code === "ABORT_ERR" || code === "UND_ERR_CONNECT_TIMEOUT") {
		return { reason: "timeout", message: `request timed out after ${RECENT_FETCH_TIMEOUT_MS / 1000}s` }
	}
	const message = error?.message || String(error)
	return { reason: "upstream", message: `request failed: ${message}` }
}

// 单接口抓取：超时 5 秒、不重试，返回原始数组或已分类的失败原因。
async function fetchRows(fetchImpl, url) {
	try {
		const response = await fetchImpl(url, {
			headers: { accept: "application/json" },
			signal: AbortSignal.timeout(RECENT_FETCH_TIMEOUT_MS),
		})
		if (!response.ok) {
			return { ok: false, failure: { reason: "upstream", message: `upstream responded with HTTP ${response.status}`, httpStatus: response.status } }
		}
		let body
		try {
			body = await response.json()
		} catch {
			return { ok: false, failure: { reason: "upstream", message: "upstream returned invalid JSON" } }
		}
		if (!Array.isArray(body)) {
			return { ok: false, failure: { reason: "upstream", message: "expected an array response" } }
		}
		return { ok: true, rows: body.slice(0, RECENT_LIMIT) }
	} catch (error) {
		return { ok: false, failure: classifyFailure(error) }
	}
}

function sourceSummary(status, detail) {
	return {
		status,
		reason: null,
		httpStatus: null,
		message: "",
		received: 0,
		written: 0,
		skipped: 0,
		total: 0,
		...detail,
	}
}

function describeSource(label, summary) {
	if (summary.status === "ok") {
		return `${label}: ok — received ${summary.received}, written ${summary.written}, skipped ${summary.skipped}, total ${summary.total}`
	}
	return (
		`${label}: failed (${summary.reason === "timeout" ? "timeout" : "upstream error"}) — ${summary.message}; ` +
		`received ${summary.received}, written ${summary.written}, skipped ${summary.skipped}, total ${summary.total}`
	)
}

/**
 * 抓取一次并持久化。
 *
 * 两个接口并发且互不影响：任意一个成功就只合并该来源，失败来源保留文件中已有行。
 * 两个都失败时文件保持原样。写入采用临时文件 + rename 的原子替换。
 */
export async function collectRecentData({
	apiBase,
	file,
	fetchImpl = globalThis.fetch,
	now = () => new Date().toISOString(),
} = {}) {
	if (typeof fetchImpl !== "function") throw new TypeError("fetchImpl must be a function")
	const base = resolveRecentApiBase(apiBase)
	const target = resolveRecentDataFile(file)
	const startedAt = now()

	const existing = await readRecentData(target)

	// 接口参数与约定一致：`limit=100&sort=desc`。
	const [blockFetch, txFetch] = await Promise.all([
		fetchRows(fetchImpl, `${base}/block?limit=${RECENT_LIMIT}&sort=desc`),
		fetchRows(fetchImpl, `${base}/tx?limit=${RECENT_LIMIT}&sort=desc`),
	])

	let blocks = existing.blocks
	let blockSummary
	if (blockFetch.ok) {
		const normalized = normalizeBlockRows(blockFetch.rows)
		blocks = mergeBlocks(existing.blocks, normalized.valid)
		blockSummary = sourceSummary("ok", {
			received: blockFetch.rows.length,
			written: normalized.valid.length,
			skipped: normalized.skipped,
			total: blocks.length,
		})
	} else {
		blockSummary = sourceSummary("failed", {
			...blockFetch.failure,
			// 失败来源不丢弃已有数据。
			total: blocks.length,
		})
	}

	let txs = existing.txs
	let txSummary
	if (txFetch.ok) {
		const normalized = normalizeTxRows(txFetch.rows)
		txs = mergeTxs(existing.txs, normalized.valid)
		txSummary = sourceSummary("ok", {
			received: txFetch.rows.length,
			written: normalized.valid.length,
			skipped: normalized.skipped,
			total: txs.length,
		})
	} else {
		// 失败时统计文件内已有行，便于确认另一来源没有被牵连。
		txSummary = sourceSummary("failed", { ...txFetch.failure, total: txs.length })
	}

	const anySuccess = blockFetch.ok || txFetch.ok
	const finishedAt = now()

	const summary = {
		ok: anySuccess,
		partial: anySuccess && !(blockFetch.ok && txFetch.ok),
		startedAt,
		finishedAt,
		file: target,
		apiBase: base,
		block: blockSummary,
		tx: txSummary,
		totals: { blocks: blocks.length, txs: txs.length },
		message: `${describeSource("Blocks", blockSummary)}\n${describeSource("Txs", txSummary)}`,
	}

	if (anySuccess) {
		const document = {
			version: 1,
			updatedAt: finishedAt,
			blocks,
			txs,
			lastRun: { ...summary, message: summary.message },
		}
		await writeRecentDataAtomic(target, document)
	}

	return summary
}

// 人类可读的本次运行结局。任务返回该文本，CLI 直接打印。
export function formatRecentSummary(summary, { verbose = true } = {}) {
	const status = summary.ok ? (summary.partial ? "PARTIAL" : "OK") : "FAILED"
	const lines = [
		`[recent-data] ${status} at ${summary.finishedAt}`,
		describeSource("  block", summary.block),
		describeSource("  tx", summary.tx),
		`  totals: blocks=${summary.totals.blocks} txs=${summary.totals.txs}`,
	]
	if (summary.block.status === "failed" || summary.tx.status === "failed") {
		lines.push("  note: failed source kept its previously stored rows; nothing was dropped")
	}
	if (verbose) lines.push(`  file: ${summary.file}`)
	return lines.join("\n")
}
