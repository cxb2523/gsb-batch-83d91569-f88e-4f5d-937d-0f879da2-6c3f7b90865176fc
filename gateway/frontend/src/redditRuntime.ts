// Pure presentation logic for the Reddit browser runtime card.
// No Vue dependency so the cooldown/session/disable rules are unit-testable
// with node:test against the same code the page renders.
export const BROWSER_FAILURE_TEXT: Record<string, string> = {
  forbidden: '平台拒绝访问（403）',
  auth: '需要更新登录会话',
  risk: '需要人工处理平台验证',
  rate_limit: '平台限流（429），浏览器已暂停请求',
  network: '请求超时',
  browser: '浏览器尚未就绪',
  interface: '响应结构异常',
  missing: '缺少登录凭证',
  unknown: '浏览器状态不可用（未知失败）',
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '0 分钟'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return m > 0 ? `${h} 小时 ${m} 分钟` : `${h} 小时`
  if (m > 0) return s > 0 ? `${m} 分 ${s} 秒` : `${m} 分钟`
  return `${s} 秒`
}

// Unknown categories (tampered worker-state, older/newer worker) never render raw.
export function failureText(value?: string | null): string {
  return (value && BROWSER_FAILURE_TEXT[value]) || BROWSER_FAILURE_TEXT.unknown
}

export interface RedditRuntimeFlags {
  redditBusy: () => boolean
  checking: () => boolean
}

export function createRedditRuntime(getRuntime: () => any, now: () => number, flags: RedditRuntimeFlags) {
  const runtime = () => getRuntime() ?? { backend: 'http', available: false }
  const cooldownRemaining = (): number => {
    const until = Number(runtime().cooldown_until ?? 0)
    return Number.isFinite(until) ? Math.max(0, Math.ceil(until - now())) : 0
  }
  const inCooldown = (): boolean => cooldownRemaining() > 0
  const sessionMismatch = (): boolean =>
    !!runtime().session_imported && runtime().session_current === false
  const startBlockedReason = (): string => {
    if (inCooldown()) return `浏览器限流冷却中，剩余 ${formatDuration(cooldownRemaining())}，冷却结束前无法启动`
    if (flags.redditBusy()) return '浏览器操作进行中'
    if (flags.checking()) return '平台检测进行中，请完成后再操作浏览器'
    if (!runtime().available) return '浏览器工作进程未连接'
    if (runtime().busy) return '浏览器正在处理其他请求'
    return ''
  }
  const startDisabled = (): boolean => startBlockedReason() !== ''
  return { runtime, cooldownRemaining, inCooldown, sessionMismatch, startBlockedReason, startDisabled }
}
