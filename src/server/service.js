import { fundStartDate } from '../assets/flow-math.js';
import { createFTShare } from './ftshare.js';
import { BASKET, CATEGORIES, FORMULA, SLOTS, chinaDate, chinaTime, dateInt, dateISO, aggregateMinute, cumulative, fundDaily, mapLimit, split } from './model.js';
export function createDataService(seed, { fetcher = fetch, now = () => Date.now(), persistentCache = globalThis.caches?.default, onLimit = () => {} } = {}) {
  const memory = new Map(), inflight = new Map(); let client, currentKey, quoteClient;
  function ft(env){if(!client||env.FTSHARE_API_KEY!==currentKey){currentKey=env.FTSHARE_API_KEY;client=createFTShare(currentKey,fetcher,{onLimit});quoteClient=createFTShare(currentKey,fetcher,{timeoutMs:5000,onLimit});}return client;}
  async function cached(key,ttl,job){
    const hit=memory.get(key);if(hit&&hit.expires>now())return hit.value;
    if(inflight.has(key))return inflight.get(key);
    const promise=(async()=>{
      const request=new Request('https://ftshare-cache.invalid/v1/'+encodeURIComponent(key));
      if(persistentCache){try{const r=await persistentCache.match(request);if(r){const value=await r.json();memory.set(key,{value,expires:now()+Math.max(1000,ttl/2)});return value;}}catch{}}
      const value=await job();memory.set(key,{value,expires:now()+ttl});
      if(memory.size>80)memory.delete(memory.keys().next().value);
      if(persistentCache){try{await persistentCache.put(request,new Response(JSON.stringify(value),{headers:{'content-type':'application/json','cache-control':'public,max-age='+Math.floor(ttl/1000)}}));}catch{}}
      return value;
    })().finally(()=>inflight.delete(key));inflight.set(key,promise);return promise;
  }
  async function tradingCalendar(env){
    return cached('calendar-'+chinaDate(now()),3600000,async()=>{
      let r;try{r=await ft(env).call('ft_v1_time_trading_calendar',{market:'cn',start_date:dateInt(seed.calendar.at(-30)),end_date:dateInt(chinaDate(now()))});}catch{return seed.calendar.filter(d=>d<=chinaDate(now()));}
      return (Array.isArray(r.data)?r.data[0]:r.data).trade_dates.map(dateISO).sort();
    });
  }
  // ETF-specific quote routes can fail independently of the generic quote routes.
  // Both return FtShare exchange OHLC/turnover; keep each component independent.
  async function quote(api,primary,backup,args){
    try{return await api.call(primary,args);}catch(first){
      if(['rate_limited','quota_exceeded','not_configured'].includes(first.code))throw first;
      try{return await api.call(primary,args);}catch(error){if(['rate_limited','quota_exceeded','not_configured'].includes(error.code))throw error;}
      return api.call(backup,args);
    }
  }
  const groups=split(seed.universe,8);
  async function live(env){return cached('live-'+FORMULA+'-'+chinaDate(now()),45000,async()=>{
    ft(env);const api=quoteClient,warnings=[];
    async function optional(label,job){try{return await job();}catch(error){warnings.push({component:label,code:error.code||'upstream_error',retry_after_ms:error.retryAfterMs||null});return {data:[]};}}
    const [minuteGroups,indexMinutes,days,indexDay,previousDays,previousIndex,calendar]=await Promise.all([
      mapLimit(split(BASKET,4),5,symbols=>optional('ETF分钟 '+symbols.join(','),()=>quote(api,'ft_v4_stock_realtime_minute_kline','ft_v4_etf_realtime_minute_kline',{symbols}))),
      optional('指数分钟',()=>api.call('ft_v4_index_realtime_minute_kline',{symbols:['000001.SH']})),
      optional('ETF当日行情',()=>quote(api,'ft_v4_stock_realtime_day_kline','ft_v4_etf_realtime_day_kline',{symbols:BASKET})),
      optional('指数当日行情',()=>api.call('ft_v4_index_realtime_day_kline',{symbols:['000001.SH']})),
      optional('ETF前收盘',()=>cached('previous-etf-'+chinaDate(now()),3600000,()=>quote(api,'ft_v2_stock_candlesticks_batch','ft_v2_etf_candlesticks_batch',{symbols:BASKET,interval_unit:'Day',adjust_kind:'none',until_ts_millis:now(),limit:3}))),
      optional('指数前收盘',()=>cached('previous-index-'+chinaDate(now()),3600000,()=>api.call('ft_v1_index_candlesticks',{symbol:'000001.SH',interval_unit:'Day',adjust_kind:'none',since_ts_millis:now()-14*86400000,until_ts_millis:now(),limit:14}))),
      tradingCalendar(env)
    ]);
    const indexRows=indexMinutes.data.filter(r=>r.symbol==='000001.SH').sort((a,b)=>a.ts_millis-b.ts_millis);
    const date=indexRows.length?chinaDate(indexRows.at(-1).ts_millis):chinaDate(indexDay.data[0]?.ts_millis||now());
    const all=minuteGroups.flatMap(r=>r.data);
    const agg=aggregateMinute(all,BASKET,date);
    const im=new Map(indexRows.filter(r=>chinaDate(r.ts_millis)===date).map(r=>[chinaTime(r.ts_millis),Number(r.close)]));
    const latestDays=new Map(days.data.filter(r=>chinaDate(r.ts_millis)===date).map(r=>[r.symbol,r]));
    const prevPrice=symbol=>previousDays.data.filter(r=>r.symbol===symbol&&chinaDate(r.ts_millis)<date).sort((a,b)=>b.ts_millis-a.ts_millis)[0]?.close;
    const prevIndex=previousIndex.data.filter(r=>chinaDate(r.ts_millis)<date).sort((a,b)=>b.ts_millis-a.ts_millis)[0];
    const table=BASKET.map(symbol=>{const r=latestDays.get(symbol),p=prevPrice(symbol),f=seed.universe.find(f=>f.symbol===symbol);return {symbol,code:symbol.slice(0,6),name:f?.name||symbol,price:r?Number(r.close):null,amount:r?Number(r.turnover)/1e8:null,pct:r&&p?(Number(r.close)/Number(p)-1)*100:null};});
    const expectedFlowDate=calendar.filter(d=>d<chinaDate(now())).at(-1);
    return {provider:'FTShare',formula:FORMULA,warnings,quote_interfaces:['ft_v4_stock_realtime_minute_kline','ft_v4_stock_realtime_day_kline','ft_v2_stock_candlesticks_batch'],fetched_at:new Date(now()).toISOString(),date,slots:SLOTS,bars:agg.bars,coverage:agg.coverage,closes:SLOTS.map(t=>im.get(t)??null),pre_close:prevIndex?Number(prevIndex.close):null,cumulative:cumulative(agg.bars),table,amount:table.every(r=>r.amount!==null)?table.reduce((s,r)=>s+r.amount,0):null,last_complete_minute:SLOTS.filter((t,i)=>agg.coverage[i]===20).at(-1)||null,expected_flow_date:expectedFlowDate,trading_dates:calendar,daily_batches:groups.length};
  });}
  async function dailyBatch(batch,env){
    if(!Number.isInteger(batch)||batch<0||batch>=groups.length)throw new Error('Invalid batch');
    return cached('daily-'+seed.built_at+'-'+chinaDate(now())+'-'+batch,3600000,async()=>{
      const api=ft(env),cal=await tradingCalendar(env),start=seed.calendar.at(-10),end=chinaDate(now());
      const funds=groups[batch];
      const rows=await mapLimit(funds,2,async fund=>{
        const [shares,navs]=await Promise.all([api.pages('ft_v2_etf_share',{etf_code:fund.symbol,stati_perd:'日',start_date:dateInt(start),end_date:dateInt(end)}),api.pages('ft_v2_etf_net_value',{etf_code:fund.symbol,start_date:dateInt(start),end_date:dateInt(end)})]);
        return {symbol:fund.symbol,bucket:fund.bucket,inception_date:fund.inception_date,listed_date:fund.listed_date,days:fundDaily(fund,shares,navs,cal)};
      });
      return {provider:'FTShare',formula:FORMULA,fetched_at:new Date(now()).toISOString(),batch,batches:groups.length,dates:cal.filter(d=>d>start),funds:rows};
    });
  }
  async function cumulativeDate(date,env){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(date)||date<'2026-01-05'||date>chinaDate(now()))throw new Error('Invalid date');
    if(seed.minutes[date])return {provider:'FTShare',date,...seed.minutes[date]};
    return cached('minute-'+date,date<chinaDate(now())?86400000:45000,async()=>{
      const symbols=BASKET.filter(s=>fundStartDate(seed.universe.find(f=>f.symbol===s))<=date);
      const rows=(await mapLimit(split(symbols,4),3,g=>ft(env).call('ft_v2_etf_minutes_batch',{symbols:g,interval_value:1,adjust_kind:'none',since_ts_millis:Date.parse(date+'T09:00:00+08:00'),until_ts_millis:Date.parse(date+'T15:30:00+08:00'),limit:1000}))).flatMap(r=>r.data);
      const m=aggregateMinute(rows,symbols,date);return {provider:'FTShare',date,bars:m.bars,cumulative:cumulative(m.bars),coverage:m.coverage};
    });
  }
  async function marketHistory(env){return cached('market-history-'+seed.built_at+'-'+chinaDate(now()),3600000,async()=>{
    const api=ft(env),start=seed.calendar.at(-10),end=chinaDate(now()),windows=[];
    let cursor=new Date(start+'T00:00:00+08:00');
    while(chinaDate(cursor.getTime())<=end){const stop=new Date(cursor);stop.setUTCMonth(stop.getUTCMonth()+6);const upper=Math.min(stop.getTime()-1,Date.parse(end+'T23:59:59+08:00'));windows.push([cursor.getTime(),upper]);cursor=stop;}
    const rows={};
    for(const [since,until] of windows){
      const args={interval_unit:'Day',adjust_kind:'none',since_ts_millis:since,until_ts_millis:until,limit:200};
      const candles=await mapLimit(split(BASKET,4),2,symbols=>api.call('ft_v2_etf_candlesticks_batch',{...args,symbols}));
      const idx=await api.call('ft_v1_index_candlesticks',{...args,symbol:'000001.SH'});
      for(const r of idx.data){const d=chinaDate(r.ts_millis);rows[d]||={date:d,idx:Number(r.close),by_symbol:{}};rows[d].idx=Number(r.close);}
      for(const r of candles.flatMap(r=>r.data)){const d=chinaDate(r.ts_millis);rows[d]||={date:d,idx:null,by_symbol:{}};rows[d].by_symbol[r.symbol]=Number(r.turnover)/1e8;}
    }
    return {provider:'FTShare',fetched_at:new Date(now()).toISOString(),rows:Object.values(rows).sort((a,b)=>a.date.localeCompare(b.date)).map(r=>{const symbols=BASKET.filter(s=>fundStartDate(seed.universe.find(f=>f.symbol===s))<=r.date);return {date:r.date,idx:r.idx,amount:symbols.every(s=>r.by_symbol[s]!==undefined)?symbols.reduce((v,s)=>v+r.by_symbol[s],0):null};})};
  });}
  return {live,dailyBatch,cumulativeDate,marketHistory,seed:()=>seed,groups};
}
