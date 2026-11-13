// 近期区块/交易的本地留存规则。纯函数，无 Node 或 Nuxt 依赖，供服务端任务、
// 兜底接口与单测共用。
export const RECENT_LIMIT = 100

const TX_HASH_PATTERN = /^[0-9a-f]{64}$/i
const POSITIVE_INTEGER_PATTERN = /^\d+$/

// 区块高度必须是正整数；兼容上游以数字字符串返回的情况，统一归一化为数字。
export function normalizeBlockHeight(value) {
	const height = typeof value === "string" && POSITIVE_INTEGER_PATTERN.test(value.trim()) ? Number(value.trim()) : value
	return typeof height === "number" && Number.isSafeInteger(height) && height > 0 ? height : null
}

// 交易哈希必须是 64 位十六进制（大小写不敏感）。
export function isValidTxHash(value) {
	return typeof value === "string" && TX_HASH_PATTERN.test(value)
}

// 逐行校验区块，返回有效行与跳过数。高度统一为数字，其余字段原样保留。
export function normalizeBlockRows(rows) {
	const valid = []
	let skipped = 0
	for (const row of Array.isArray(rows) ? rows : []) {
		const height = row && typeof row === "object" ? normalizeBlockHeight(row.height) : null
		if (height === null) {
			skipped += 1
			continue
		}
		valid.push({ ...row, height })
	}
	return { valid, skipped }
}

// 逐行校验交易，返回有效行与跳过数。
export function normalizeTxRows(rows) {
	const valid = []
	let skipped = 0
	for (const row of Array.isArray(rows) ? rows : []) {
		if (!row || typeof row !== "object" || !isValidTxHash(row.hash)) {
			skipped += 1
			continue
		}
		valid.push(row)
	}
	return { valid, skipped }
}

function txTime(row) {
	const value = row?.time ?? row?.timestamp
	const parsed = Date.parse(value ?? "")
	return Number.isFinite(parsed) ? parsed : 0
}

// 按高度合并去重；本次抓取的行覆盖旧行，只保留最新的 100 条（高度倒序）。
export function mergeBlocks(existing, incoming) {
	const byHeight = new Map()
	for (const row of [...(Array.isArray(existing) ? existing : []), ...(Array.isArray(incoming) ? incoming : [])]) {
		const height = row && typeof row === "object" ? normalizeBlockHeight(row.height) : null
		if (height === null) continue
		byHeight.set(height, { ...row, height })
	}
	return [...byHeight.values()].sort((a, b) => b.height - a.height).slice(0, RECENT_LIMIT)
}

// 按哈希（忽略大小写）合并去重；本次抓取的行覆盖旧行，按时间倒序保留最近 100 条。
export function mergeTxs(existing, incoming) {
	const byHash = new Map()
	for (const row of [...(Array.isArray(existing) ? existing : []), ...(Array.isArray(incoming) ? incoming : [])]) {
		if (!row || typeof row !== "object" || !isValidTxHash(row.hash)) continue
		byHash.set(row.hash.toLowerCase(), row)
	}
	return [...byHash.values()].sort((a, b) => txTime(b) - txTime(a)).slice(0, RECENT_LIMIT)
}
