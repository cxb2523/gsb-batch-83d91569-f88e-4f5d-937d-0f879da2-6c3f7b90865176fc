// Only the two reviewed read actions are executable. Never return upstream errors.
export const VERSION = '2.0.2'
export const TOOLS = ['reddit_search', 'reddit_subreddit_posts']
export function input(body) {
  if (!body || !['status', 'start', 'stop', 'query'].includes(body.action)) throw new Error('bad_input')
  if (body.action === 'status' || body.action === 'stop') return { action: body.action,
    revision: typeof body.revision === 'string' && /^[a-f0-9]{64}$/.test(body.revision) ? body.revision : null }
  if (typeof body.cookie !== 'string' || body.cookie.length > 16000 || /[\r\n\0]/.test(body.cookie)) throw new Error('bad_input')
  if (body.action === 'start') return { action: body.action, cookie: body.cookie }
  if (!TOOLS.includes(body.tool)) throw new Error('unsupported')
  const a = body.args || {}, limit = a.limit ?? 25
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error('bad_input')
  const subreddit = String(a.subreddit || '').replace(/^r\//, '')
  if (subreddit && !/^[a-zA-Z0-9_]{1,30}$/.test(subreddit)) throw new Error('bad_input')
  if (body.tool === 'reddit_subreddit_posts' && !subreddit) throw new Error('bad_input')
  if (a.after) throw new Error('unsupported')
  const sort = a.sort || (body.tool === 'reddit_search' ? 'relevance' : 'hot')
  if (!(body.tool === 'reddit_search' ? ['relevance','hot','new','top','comments'] : ['hot','new','top','rising','controversial']).includes(sort)) throw new Error('bad_input')
  const query = a.query || ''
  if (body.tool === 'reddit_search' && (typeof query !== 'string' || !query.trim() || query.length > 1000 || /[\r\n\0]/.test(query))) throw new Error('bad_input')
  return { action: 'query', tool: body.tool, cookie: body.cookie, args: { query, subreddit, sort, limit } }
}
export function argv(body) {
  const a = body.args
  const flags = ['--sort', a.sort, '--time', 'all', '--limit', String(a.limit), '--site-session', 'persistent', '--trace', 'off', '-f', 'json']
  if (body.tool === 'reddit_search') return ['reddit', 'search', ...flags, ...(a.subreddit ? ['--subreddit', a.subreddit] : []), '--', a.query]
  return ['reddit', 'subreddit', ...flags, '--', a.subreddit]
}
export function failure(envelope) {
  const e = envelope?.error || {}, code = String(e.code || ''), text = String(e.message || '').toLowerCase()
  if (code === 'RATE_LIMITED' || /\b429\b/.test(text)) return 'rate_limit'
  if (code === 'SECURITY_BLOCK' || /\b403\b/.test(text)) return 'forbidden'
  if (/captcha|account_risk|验证码/.test(code.toLowerCase() + text)) return 'risk'
  if (code === 'AUTH_REQUIRED') return 'auth'
  if (code === 'TIMEOUT') return 'network'
  return 'interface'
}
export function rows(envelope, exitCode) {
  if (exitCode !== 0 || envelope?.ok !== true) throw new Error(failure(envelope))
  if (!Array.isArray(envelope.data)) throw new Error('interface')
  return envelope.data.map(row => {
    if (!row || typeof row.id !== 'string' || !/^[a-z0-9]+$/i.test(row.id) || typeof row.title !== 'string') throw new Error('interface')
    let url
    try { url = new URL(row.url) } catch { throw new Error('interface') }
    if (url.origin !== 'https://www.reddit.com' || !url.pathname.includes('/comments/')) throw new Error('interface')
    const numbers = [Number(row.score ?? row.upvotes ?? 0), Number(row.comments || 0), Number(row.created_utc || 0)]
    if (!numbers.every(Number.isFinite)) throw new Error('interface')
    return { id: row.id, title: row.title, selftext: typeof row.selftext === 'string' ? row.selftext : '',
      author: typeof row.author === 'string' ? row.author : '', subreddit: String(row.subreddit || '').replace(/^r\//, ''),
      score: numbers[0], num_comments: numbers[1],
      created_utc: numbers[2], permalink: url.pathname, url: url.href }
  })
}
