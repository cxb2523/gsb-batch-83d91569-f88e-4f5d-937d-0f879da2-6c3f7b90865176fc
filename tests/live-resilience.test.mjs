import test from 'node:test';
import assert from 'node:assert/strict';
import {createDataService} from '../src/server/service.js';
import {BASKET} from '../src/server/model.js';
const ts=Date.parse('2026-11-10T09:30:00+08:00');
function service(failMinutes=false){
 const fetcher=async(_url,options)=>{
  const q=JSON.parse(options.body);let result;
  if(q.method==='initialize')result={protocolVersion:'2024-11-05'};
  else if(q.method==='notifications/initialized')result={};
  else{
   const {name,arguments:a}=q.params;let data=[];
   if(name==='ft_v1_time_trading_calendar'||name.includes('index_')||(failMinutes&&name.includes('minute'))||name.includes('ft_v4_etf_'))result={isError:true,structuredContent:{error:{code:'UPSTREAM_UNAVAILABLE'}}};
   else{if(name==='ft_v4_stock_realtime_minute_kline'||name==='ft_v4_stock_realtime_day_kline')data=a.symbols.map(symbol=>({symbol,ts_millis:ts,close:'1',turnover:'100000000'}));result={structuredContent:{data,metadata:{}}};}
  }
  return new Response(JSON.stringify({jsonrpc:'2.0',id:q.id,result}),{status:200,headers:{'content-type':'application/json'}});
 };
 return createDataService({calendar:['2026-11-06','2026-11-09','2026-11-10'],universe:BASKET.map(symbol=>({symbol,name:symbol}))},{fetcher,now:()=>ts,persistentCache:null});
}
test('working ETF-compatible quotes survive index and calendar outages',async()=>{
 const r=await service().live({FTSHARE_API_KEY:'test'});assert.equal(r.date,'2026-11-10');assert.equal(r.amount,20);assert.equal(r.coverage[0],20);assert.equal(r.expected_flow_date,'2026-11-09');assert.equal(r.table.length,20);assert(r.warnings.some(w=>w.component==='指数分钟'));
});
test('a minute outage does not discard working ETF daily quotes',async()=>{
 const r=await service(true).live({FTSHARE_API_KEY:'test'});assert.equal(r.amount,20);assert.equal(r.coverage[0],0);assert.equal(r.bars[0],null);assert(r.warnings.some(w=>w.component.startsWith('ETF分钟')));
});
