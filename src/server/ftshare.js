// FtShare is the only market-data provider. This module is shared by the Worker and collector.
export const MCP_URL = 'https://market.ft.tech/gateway/mcp';
export class FTShareError extends Error {
  constructor(message, code = 'upstream_error', details = {}) { super(message); this.code = code; Object.assign(this, details); }
}
export function retryDelay(value, now = Date.now()) {
  if (value === null || value === undefined || value === '') return null;
  const ms = /^\d+(\.\d+)?$/.test(String(value)) ? Number(value) * 1000 : Date.parse(value) - now;
  return Number.isFinite(ms) ? Math.max(1000, ms) : null;
}
export function limitedError(error, retryAfter) {
  // A 429 alone establishes throttling, not exhaustion of the entire account quota.
  const explicitQuota = /^(quota_exceeded|daily_quota_exceeded|monthly_quota_exceeded|insufficient_credits)$/i.test(error?.code || '');
  return new FTShareError('FtShare请求受限', explicitQuota ? 'quota_exceeded' : 'rate_limited', {
    retryAfterMs: retryDelay(retryAfter ?? error?.retry_after), upstreamStatus: 429
  });
}
export function createFTShare(key, fetcher = fetch, { timeoutMs = 25000, onLimit = () => {} } = {}) {
  let session, protocol = '2024-11-05', seq = 0, ready;
  async function rpc(method, params, notification = false) {
    const id = notification ? undefined : ++seq;
    const headers = { 'content-type': 'application/json', accept: 'application/json, text/event-stream', FTSHARE_API_KEY: key };
    if (session) headers['Mcp-Session-Id'] = session;
    if (method !== 'initialize') headers['MCP-Protocol-Version'] = protocol;
    const response = await fetcher(MCP_URL, { method: 'POST', headers, body: JSON.stringify({ jsonrpc: '2.0', method, ...(params === undefined ? {} : { params }), ...(notification ? {} : { id }) }), signal: AbortSignal.timeout(timeoutMs) });
    if (method === 'initialize' && response.ok && response.headers.get('mcp-session-id')) session = response.headers.get('mcp-session-id');
    const raw = await response.text();
    if (notification && response.ok) return {};
    let value;
    try { value = JSON.parse(raw); } catch {
      for (const line of raw.split('\n')) if (line.startsWith('data:')) {
        try { const v = JSON.parse(line.slice(5).trim()); if (v.id === id) value = v; } catch { /* other SSE event */ }
      }
    }
    if (!response.ok || !value || value.error) {
      const expired = method === 'tools/call' && (response.status === 404 || /session.*(expired|invalid|not found)|invalid.*session/i.test(value?.error?.message || raw));
      if (response.status === 429) { const e = limitedError(value?.error, response.headers.get('retry-after')); onLimit(e); throw e; }
      throw new FTShareError('FtShare请求失败', expired ? 'session_expired' : 'upstream_error');
    }
    return value.result;
  }
  async function init() {
    if (!key) throw new FTShareError('FtShare密钥尚未配置', 'not_configured');
    if (!ready) ready = (async () => { const r = await rpc('initialize', { protocolVersion: protocol, capabilities: {}, clientInfo: { name: 'ftshare-etf-dashboard', version: '1.0' } }); protocol = r.protocolVersion || protocol; await rpc('notifications/initialized', undefined, true); })().catch(e => { ready = null; throw e; });
    return ready;
  }
  return {
    async call(name, args) {
      await init();
      let r; const previousSession = session;
      try { r = await rpc('tools/call', { name, arguments: args }); }
      catch (e) {
        if (e.code !== 'session_expired') throw e;
        if (session === previousSession) { session = undefined; ready = null; }
        await init();
        r = await rpc('tools/call', { name, arguments: args });
      }
      let s = r?.structuredContent;
      if (!s) { try { s = JSON.parse(r?.content?.find(c => c.type === 'text')?.text || '{}'); } catch { /* invalid response */ } }
      if (r?.isError || s?.error || !s || s.data === undefined) {
        if (Number(s?.error?.upstream_code) === 429 || Number(s?.error?.status) === 429) { const e = limitedError(s.error); onLimit(e); throw e; }
        throw new FTShareError('FtShare数据暂不可用');
      }
      if (s.metadata?.truncated) throw new FTShareError('FtShare返回数据被截断', 'truncated');
      return s;
    },
    async pages(name, args, pageSize = 200) {
      const rows = [];
      for (let page = 1; page <= 30; page++) {
        const r = await this.call(name, { ...args, page, page_size: pageSize });
        if (!Array.isArray(r.data)) throw new FTShareError('FtShare字段格式异常');
        rows.push(...r.data);
        if (!r.metadata?.pagination?.has_more) return rows;
      }
      throw new FTShareError('FtShare分页未完成', 'truncated');
    }
  };
}
