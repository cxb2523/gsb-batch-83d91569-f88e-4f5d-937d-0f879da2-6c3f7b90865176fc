import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createGateway } from '../src/gateway.js';
import { createReadOnlyService } from '../src/server/read-only.js';
import worker, { collectMinute, tradingMinute, mergeLiveCache, kvResponseCache } from '../src/background/collector.js';
import { requestPacer } from '../scripts/lib/request-pacer.mjs';
const demo = JSON.parse(await readFile(new URL('../data/demo-seed.json', import.meta.url)));
const seed = { ...demo, demo: undefined, provider: 'FTShare' };
const date = '2026-11-12', time = Date.parse(date + 'T10:00:00+08:00');
function kv(initial = {}) { const rows = new Map(Object.entries(initial)); return { rows, async get(k, type) { const v = rows.get(k); return v === undefined ? null : type === 'json' ? JSON.parse(v) : v; }, async put(k, v) { rows.set(k, v); } }; }
test('public reloads, force-query parameters and all data routes perform zero upstream requests', async () => {
  const old = globalThis.fetch; let calls = 0; globalThis.fetch = () => { calls++; throw new Error('No provider access allowed'); };
  try {
    const gateway = createGateway({ seed }), cache = kv({ 'live:snapshot': JSON.stringify({ value: { provider: 'FTShare', fetched_at: new Date(time).toISOString(), date } }) });
    for (let i = 0; i < 5; i++) for (const path of ['/api/board','/api/live?force=true','/api/history','/api/daily?batch=0','/api/cumulative?date=2026-11-12']) {
      const r = await gateway.fetch(new Request('https://board.example' + path), { FTSHARE_CACHE: cache, FTSHARE_API_KEY: 'must-not-be-used' });
      assert([200,404,410].includes(r.status), path);
    }
    assert.equal((await gateway.fetch(new Request('https://board.example/api/live',{method:'POST'}),{FTSHARE_CACHE:cache})).status,405);
    assert.equal(calls, 0);
  } finally { globalThis.fetch = old; }
});
test('missing shared cache returns embedded last success and never invokes a provider fallback', async () => {
  const fallback = { provider: 'FTShare', date, fetched_at: new Date(time).toISOString() };
  const service = createReadOnlyService({ ...seed, live_snapshot: fallback }, { now: () => time + 600000 });
  const result = await service.live({ FTSHARE_CACHE: { get: async () => { throw Error('cache offline'); } } });
  assert.equal(result.date, date); assert.equal(result.cache.stale, true);
  await assert.rejects(createReadOnlyService(seed).live({}), e => e.code === 'cache_not_ready');
});
test('collector has no public HTTP update endpoint', async () => {
  for (const method of ['GET','POST','PUT']) assert([404,405].includes((await worker.fetch(new Request('https://collector.example/refresh',{method}))).status));
});
test('trading clock skips lunch, weekends and out-of-session minutes', () => {
  assert(tradingMinute(time)); assert(!tradingMinute(Date.parse(date+'T12:30:00+08:00')));
  assert(!tradingMinute(Date.parse('2026-11-14T10:00:00+08:00')));
  assert(!tradingMinute(Date.parse(date+'T18:00:00+08:00')));
});
test('duplicate minute and cooldown prevent provider calls', async () => {
  const cache = kv({ 'live:snapshot': JSON.stringify({ attempt_slot: Math.floor(time / 60000) }) });
  const result = await collectMinute({FTSHARE_CACHE:cache},{now:()=>time,fetcher:()=>{throw Error('unexpected fetch');}});
  assert.equal(result.skipped,'already_collected_or_cooling_down');
});
test('a failed background collection retains the last good snapshot and records a retry deadline', async () => {
  const value = { date, fetched_at: new Date(time - 60000).toISOString(), amount: 42 };
  const cache = kv({ 'live:snapshot': JSON.stringify({ value }) });
  const result = await collectMinute({FTSHARE_CACHE:cache,FTSHARE_API_KEY:'test'},{now:()=>time,fetcher:async()=>new Response('rate limited',{status:429,headers:{'retry-after':'120'}})});
  assert.equal(result.retained_last_success,true);const saved=JSON.parse(cache.rows.get('live:snapshot'));
  assert.deepEqual(saved.value,value);assert.equal(saved.last_error,'rate_limited');assert.equal(Date.parse(saved.next_attempt_at),time+120000);
});
test('partial minute responses preserve complete bars only within the same trading day', () => {
  const old={date,bars:[1,2],coverage:[20,20],closes:[3500,3501]},next={date,bars:[null,3],coverage:[0,20],closes:[null,3502],slots:['09:30','09:31']};
  assert.deepEqual(mergeLiveCache(next,old).bars,[1,3]);assert.deepEqual(mergeLiveCache({...next,date:'2026-11-13'},old).bars,[null,3]);
});
test('all concurrent callers obey the same request spacing and cooldown', async () => {
  let now = 0; const starts=[];const pacer=requestPacer({intervalMs:1000,now:()=>now,pause:async ms=>{now+=ms;}});
  await Promise.all([pacer.run(async()=>{starts.push(now);pacer.defer(3000);}),pacer.run(async()=>{starts.push(now);}),pacer.run(async()=>{starts.push(now);})]);
  assert.deepEqual(starts,[0,3000,4000]);
});
test('the scheduled collector re-queries live minutes and only persists reusable reference responses', async () => {
  const store=kv(),cache=kvResponseCache(store,()=>time);
  const live=new Request('https://ftshare-cache.invalid/v1/live-formula-date');
  await cache.put(live,Response.json({old:true}));assert.equal(store.rows.size,0);assert.equal(await cache.match(live),undefined);
  const prev=new Request('https://ftshare-cache.invalid/v1/previous-etf-date');
  await cache.put(prev,Response.json({previous:123}));assert.equal((await(await cache.match(prev)).json()).previous,123);
});
test('shared edge cache normalizes force-query parameters without extra storage reads', async () => {
  const old=globalThis.caches;const entries=new Map();globalThis.caches={default:{async match(k){return entries.get(k.url)?.clone();},async put(k,v){entries.set(k.url,v);}}};
  try{
    let reads=0;const cache={async get(){reads++;return {value:{provider:'FTShare',date,fetched_at:new Date(time).toISOString()}};}};
    const gateway=createGateway({seed});for(const q of ['','?force=1','?refresh=true'])assert.equal((await gateway.fetch(new Request('https://board.example/api/live'+q),{FTSHARE_CACHE:cache})).status,200);
    assert.equal(reads,1);
  }finally{globalThis.caches=old;}
});

test('Cloudflare cron names weekdays explicitly so Friday is not lost to its Sunday=1 convention', async () => {
  const config=JSON.parse(await readFile(new URL('../config/intraday-worker.example.jsonc',import.meta.url),'utf8'));
  assert.equal(config.triggers.crons.length,1);
  const fields=config.triggers.crons[0].split(/\s+/);
  assert.equal(fields[4],'MON-FRI','Cloudflare numeric 1-5 excludes Friday; use explicit weekday names');
  assert.equal(fields[1],'1-3,5-7','Keep the existing UTC session hours');
  for(const [date,allowed]of [['2026-11-13',true],['2026-11-16',true],['2026-11-14',false],['2026-11-15',false]])
    assert.equal(tradingMinute(Date.parse(date+'T10:00:00+08:00')),allowed,date);
});
