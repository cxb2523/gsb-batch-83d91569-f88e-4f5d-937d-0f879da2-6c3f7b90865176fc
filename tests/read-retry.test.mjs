import test from 'node:test';
import assert from 'node:assert/strict';
import { readWithRetry } from '../scripts/lib/read-retry.mjs';
test('background read retries a transient provider error and continues with successful data', async () => {
  let calls = 0;
  const result = await readWithRetry(async () => { if (++calls < 3) throw Object.assign(new Error('provider unavailable'), { code: 'upstream_error' }); return { data: [123] }; }, { pause: async () => {} });
  assert.equal(calls, 3); assert.deepEqual(result, { data: [123] });
});
test('quota and truncated responses are not repeatedly requested', async () => {
  for (const code of ['quota_exceeded', 'truncated']) {
    let calls = 0;
    await assert.rejects(readWithRetry(async () => { calls++; throw Object.assign(new Error('blocked response'), { code }); }, { pause: async () => {} }));
    assert.equal(calls, 1);
  }
});
test('429 honors the provider wait and applies a shared cooldown before retrying', async () => {
  let calls=0;const waits=[],cooldowns=[];
  assert.equal(await readWithRetry(async()=>{if(++calls===1)throw Object.assign(new Error('slow down'),{code:'rate_limited',retryAfterMs:120000});return 'ok';},
    {pause:async ms=>waits.push(ms),onLimit:ms=>cooldowns.push(ms),random:()=>0}),'ok');
  assert.deepEqual(waits,[120000]);assert.deepEqual(cooldowns,[120000]);assert.equal(calls,2);
});
