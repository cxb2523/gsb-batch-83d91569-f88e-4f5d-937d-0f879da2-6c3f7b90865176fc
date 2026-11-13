import test from 'node:test';
import assert from 'node:assert/strict';
import { createFTShare, retryDelay, limitedError } from '../src/server/ftshare.js';
test('429 distinguishes unknown throttling from explicit account quota and retains Retry-After', async () => {
  const limited=[]; const ft=createFTShare('test',async()=>new Response('wait',{status:429,headers:{'retry-after':'120'}}),{onLimit:e=>limited.push(e)});
  await assert.rejects(ft.call('read',{}),e=>e.code==='rate_limited'&&e.retryAfterMs===120000);
  assert.equal(limited.length,1); assert.equal(limitedError({code:'daily_quota_exceeded'}).code,'quota_exceeded');
  assert.equal(retryDelay('Thu, 12 Nov 2026 07:02:00 GMT',Date.parse('2026-11-12T07:00:00Z')),120000);
});
test('MCP business errors and truncated pages fail even when HTTP is 200', async () => {
  for (const code of ['rate_limited', 'truncated']) {
    const ft = createFTShare('test-only-key', async (_, o) => {
      const q = JSON.parse(o.body);
      if (q.method === 'notifications/initialized') return new Response(null, { status: 202 });
      const result = q.method === 'initialize' ? { protocolVersion: '2024-11-05' } : code === 'rate_limited' ? { isError: true, structuredContent: { error: { upstream_code: 429 } } } : { structuredContent: { data: [], metadata: { truncated: true } } };
      return new Response(JSON.stringify({ id: q.id, result }));
    });
    await assert.rejects(ft.call('read-tool', {}), e => e.code === code);
  }
});
test('expired upstream sessions are renewed before retrying the safe read', async () => {
  let sessions = 0, calls = 0;
  const ft = createFTShare('test-only-key', async (_, o) => {
    const q = JSON.parse(o.body);
    if (q.method === 'initialize') return new Response(JSON.stringify({ id: q.id, result: { protocolVersion: '2024-11-05' } }), { headers: { 'mcp-session-id': 'session-' + ++sessions } });
    if (q.method === 'notifications/initialized') return new Response(null, { status: 202 });
    if (++calls === 1) return new Response('Session not found', { status: 404 });
    assert.equal(o.headers['Mcp-Session-Id'], 'session-2');
    return new Response(JSON.stringify({ id: q.id, result: { structuredContent: { data: [], metadata: {} } } }));
  });
  assert.deepEqual((await ft.call('read-tool', {})).data, []); assert.equal(sessions, 2); assert.equal(calls, 2);
});
