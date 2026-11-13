import test from 'node:test';
import assert from 'node:assert/strict';
import { promoteTest, publicationTarget, verifyFormalSource, verifyRadarSnapshot } from '../scripts/lib/cloud-publication.mjs';

test('formal publication requires its explicit project and pinned source revision', () => {
  assert.throws(() => publicationTarget({ CLOUDFLARE_PAGES_PROJECT: 'example-etf' }));
  assert.throws(() => publicationTarget({ CLOUD_PUBLISH_TARGET: 'formal', CLOUDFLARE_FORMAL_PROJECT: 'example-etf', CLOUDFLARE_PAGES_PROJECT: 'other', CLOUDFLARE_FORMAL_SOURCE_REF: 'a'.repeat(40) }));
  assert.throws(() => publicationTarget({ CLOUD_PUBLISH_TARGET: 'formal', CLOUDFLARE_FORMAL_PROJECT: 'example-etf', CLOUDFLARE_PAGES_PROJECT: 'example-etf', CLOUDFLARE_FORMAL_SOURCE_REF: 'main' }));
  assert.equal(publicationTarget({ CLOUD_PUBLISH_TARGET: 'formal', CLOUDFLARE_FORMAL_PROJECT: 'example-etf', CLOUDFLARE_PAGES_PROJECT: 'example-etf', CLOUDFLARE_FORMAL_SOURCE_REF: 'a'.repeat(40) }), 'formal');
});
const evidence = () => ({ expected: { cloud_update: { archive_id: 'accepted-data' } }, testProject: 'example-etf-test', sourceRef: 'a'.repeat(40), checkedOutRef: 'a'.repeat(40), proof: { target: 'test', archive_id: 'accepted-data', published: 'https://abc123.example-etf-test.pages.dev' } });
test('formal publication rejects a different source, archive or untrusted verification URL', async () => {
  let calls = 0; const verify = async () => { calls++; };
  await assert.rejects(verifyFormalSource({ ...evidence(), checkedOutRef: 'b'.repeat(40), verify }), /approved revision/);
  await assert.rejects(verifyFormalSource({ ...evidence(), proof: { ...evidence().proof, archive_id: 'other' }, verify }), /matching verified/);
  await assert.rejects(verifyFormalSource({ ...evidence(), proof: { ...evidence().proof, published: 'https://arbitrary.example' }, verify }), /matching verified/);
  await assert.rejects(verifyFormalSource({ ...evidence(), testProject: 'another-test', verify }), /matching verified/);
  assert.equal(calls, 0);
});
test('formal publication independently checks the accepted immutable test deployment', async () => {
  const urls = []; await verifyFormalSource({ ...evidence(), verify: async url => { urls.push(url); } });
  assert.deepEqual(urls, [evidence().proof.published]);
  await assert.rejects(verifyFormalSource({ ...evidence(), verify: async () => { throw new Error('test snapshot mismatch'); } }), /test snapshot mismatch/);
});

test('a broken candidate is never promoted to the test main branch', async () => {
  const branches = [];
  await assert.rejects(promoteTest({ before: { id: 'working' }, deploy: async b => { branches.push(b); return 'preview'; }, verify: async () => { throw new Error('bad snapshot'); } }), /bad snapshot/);
  assert.deepEqual(branches, ['cloud-archive-candidate']);
});
test('an upload that activated main before timing out is rolled back and confirmed', async () => {
  let active = { id: 'working' }; const rollbacks = [];
  await assert.rejects(promoteTest({ before: active, stableURL: 'stable',
    deploy: async branch => { if (branch === 'main') { active = { id: 'broken' }; throw new Error('timeout after activation'); } return 'preview'; },
    verify: async () => {}, current: async () => active,
    rollback: async id => { rollbacks.push(id); active = { id }; }
  }), /previous deployment restored/);
  assert.equal(active.id, 'working'); assert.deepEqual(rollbacks, ['working']);
});
test('a failed rollback is not reported as a restored site', async () => {
  let active = { id: 'working' };
  await assert.rejects(promoteTest({ before: active, stableURL: 'stable',
    deploy: async branch => { if (branch === 'main') active = { id: 'broken' }; return branch; },
    verify: async url => { if (url === 'stable') throw new Error('bad response'); },
    current: async () => active, rollback: async () => {}
  }), /rollback could not be confirmed/);
});

function radarSeed() {
  const rows = Array.from({length:20},(_,i)=>({symbol:'ETF'+i,flow:i}));
  return {universe:rows.map(r=>({symbol:r.symbol,is_core_basket:true})),core_fund_daily:{date:'2026-11-11',rows},latest_flow_date:'2026-11-11',latest_market_date:'2026-11-12',history:{dates:['2026-11-11'],netflow:[190]},minute_slots:['09:30'],minutes:Object.fromEntries(Array.from({length:60},(_,i)=>[new Date(Date.UTC(2026,8,1+i)).toISOString().slice(0,10),{bars:[1]}]))};
}
test('radar release requires a reconciled latest daily snapshot and 60 minute samples',()=>{assert.doesNotThrow(()=>verifyRadarSnapshot(radarSeed()));});
test('radar release rejects missing, stale or duplicate fund rows',()=>{
 const a=radarSeed();delete a.core_fund_daily;assert.throws(()=>verifyRadarSnapshot(a));
 const b=radarSeed();b.core_fund_daily.date='2026-11-10';assert.throws(()=>verifyRadarSnapshot(b));
 const c=radarSeed();c.core_fund_daily.rows[0].symbol=c.core_fund_daily.rows[1].symbol;assert.throws(()=>verifyRadarSnapshot(c));
});
test('radar release rejects nonfinite or unreconciled fund flows',()=>{
 const a=radarSeed();a.core_fund_daily.rows[0].flow=null;assert.throws(()=>verifyRadarSnapshot(a));
 const b=radarSeed();b.core_fund_daily.rows[0].flow=100;assert.throws(()=>verifyRadarSnapshot(b));
});
test('radar release cannot count current or incomplete days toward the 60-day baseline',()=>{
 const a=radarSeed();a.minutes[Object.keys(a.minutes)[0]].quality='incomplete';a.minutes['2026-11-12']={bars:[1]};assert.throws(()=>verifyRadarSnapshot(a));
});
