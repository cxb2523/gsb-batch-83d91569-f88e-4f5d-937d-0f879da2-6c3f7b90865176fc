export const BASKET = ['510310.SH','588000.SH','159915.SZ','510300.SH','563360.SH','159352.SZ','512100.SH','159338.SZ','510500.SH','159949.SZ','588080.SH','510050.SH','510210.SH','159845.SZ','159952.SZ','159361.SZ','512050.SH','159633.SZ','560010.SH','159919.SZ'];
export const CATEGORIES = ['沪深300','中证1000','中证500','科创50','中证A500','创业板指','上证50','其他宽基','创业板50','双创50','中证2000','国证2000'];
export const COLORS = ['#d93630','#e8862e','#f0b429','#4c7bf3','#0aa06e','#8e44ad','#16a085','#c0392b','#2980b9','#7f8c8d','#27ae60','#d35400'];
import { fundStartDate, strictCumulative } from '../assets/flow-math.js';
export const FORMULA = 'exchange_aligned_shares_verified_events_v3';
export const FLOW_POLICY = 'verified_events_public_backfill_v3';
export function dateISO(value) {
  const s = String(value).replaceAll('-', '');
  return s.length === 8 ? s.slice(0,4)+'-'+s.slice(4,6)+'-'+s.slice(6,8) : String(value).slice(0,10);
}
export function dateInt(value) { return Number(String(value).replaceAll('-', '')); }
export function chinaDate(ts = Date.now()) { return new Date(ts + 8*3600000).toISOString().slice(0,10); }
export function chinaTime(ts) { return new Date(ts + 8*3600000).toISOString().slice(11,16); }
export function fullAxis() { const a=[]; for(let m=9*60+30;m<=11*60+30;m++)a.push(String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0'));for(let m=13*60+1;m<=15*60;m++)a.push(String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0'));return a; }
export const SLOTS = fullAxis();
const finite = v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));
function fixed(v,precision=8) { if(!finite(v))return null;const [a,b='']=String(v).split('.'),scale=10n**BigInt(precision);return BigInt(a)*scale+BigInt((b+'0'.repeat(precision)).slice(0,precision))*(String(v).startsWith('-')?-1n:1n); }
export function estimateFlow(current, previous, nav, previousNav, splitRatio = 1) {
  if(!current || !previous || !nav || !finite(current.fund_share) || !finite(previous.fund_share) || !finite(nav.unit_nav) || Number(nav.unit_nav)<=0)return null;
  if(!finite(splitRatio)||Number(splitRatio)<=0)return null;
  const sr=Number(current.fund_share)/(Number(previous.fund_share)*splitRatio), nr=Number(nav.unit_nav)/(Number(previousNav?.unit_nav)/splitRatio);
  // A mechanical inverse share/NAV jump is withheld pending a source event; it is never treated as a creation.
  if((sr>1.5||sr<0.67)&&finite(nr)&&Math.abs(sr*nr-1)<0.08)return null;
  const prior=fixed(previous.fund_share)*fixed(splitRatio,12)/1000000000000n;
  return Number((fixed(current.fund_share)-prior)*fixed(nav.unit_nav))/1e24;
}
export function fundDaily(fund, shares, navs, calendar) {
  const sm=new Map(shares.filter(r=>r.statistics_period==='日').map(r=>[dateISO(r.trade_date),r]));
  const evidence=fund.flow_evidence||{};
  // Explicit FtShare PCF recoveries are used only when the normal NAV endpoint is missing.
  const nm=new Map((evidence.navs||[]).map(r=>[dateISO(r.nav_date),r]));
  for(const row of navs)if(finite(row.unit_nav)&&Number(row.unit_nav)>0)nm.set(dateISO(row.nav_date),row);
  const result={};
  for(let i=1;i<calendar.length;i++){
    const d=calendar[i],p=calendar[i-1];
    if(d<fundStartDate(fund)){result[d]={flow:0,...(d<fund.inception_date?{not_yet_incepted:true}:{not_yet_listed:true})};continue;}
    // FtShare share-record dates require exchange alignment. SZ needs the next
    // actual trading-day record; until it exists the attributed day's flow is null.
    const sd=fund.symbol?.endsWith('.SZ')?calendar[i+1]:d;
    const pd=fund.symbol?.endsWith('.SZ')?d:p;
    const s=sm.get(sd),n=nm.get(d),pn=nm.get(p),baseline=evidence.listing_baseline;
    let prev=sm.get(pd),usedBaseline=false,splitRatio=1;
    if(!prev&&fund.symbol?.endsWith('.SH')&&fund.listed_date===d&&baseline?.date===pd&&baseline.subscription_start_date>=d&&baseline.redemption_start_date>=d&&finite(baseline.fund_share)){
      prev={fund_share:baseline.fund_share};usedBaseline=true;
    }
    const split=(evidence.splits||[]).find(e=>e.date===d);
    if(split&&finite(n?.adjustment_factor)&&finite(pn?.adjustment_factor)&&Number(pn.adjustment_factor)>0&&Math.abs((Number(n.adjustment_factor)/Number(pn.adjustment_factor))/Number(split.ratio)-1)<(split.source?.verified_official_event===true?5e-6:1e-8))splitRatio=Number(split.ratio);
    const flow=estimateFlow(s,prev,n,pn,splitRatio),issues=[];
    if(flow===null){
      if(!s||!finite(s.fund_share))issues.push('share_missing');
      if(!prev||!finite(prev.fund_share))issues.push(fund.listed_date===d&&fund.symbol?.endsWith('.SH')?'listing_baseline_missing':'previous_share_missing');
      if(!n||!finite(n.unit_nav)||Number(n.unit_nav)<=0)issues.push('nav_missing');
      if(!issues.length)issues.push('share_change_review');
    }
    result[d]={flow,shares:s?.fund_share??null,nav:n?.unit_nav??null,shares_record_date:sd??null,previous_shares_record_date:pd,publish_date:n?.publish_date?dateISO(n.publish_date):null,...(usedBaseline?{baseline_source:'verified_prelisting_shares'}:{}),...(splitRatio!==1?{split_ratio:splitRatio}:{}),...(n?.source?{nav_source:n.source}:{}),...(issues.length?{issues}:{})};
  }
  return result;
}
export function aggregateFunds(funds, raw, calendar) {
  const dates=calendar.slice(1), group={},issues={};
  for(const c of CATEGORIES)group[c]={dates:[],values:[],valid:[],expected:[]};
  const basket={dates,netflow:[],coverage:[],expected:[]};
  for(const date of dates){
    for(const c of CATEGORIES){let sum=0,valid=0,expected=0;for(const f of funds.filter(f=>f.bucket===c)){if(date<fundStartDate(f))continue;expected++;const row=raw[f.symbol]?.[date],v=row?.flow;if(finite(v)){sum+=Number(v);valid++;}else (issues[date]||=[]).push({symbol:f.symbol,name:f.name,bucket:c,reasons:row?.issues||['source_missing']});} const g=group[c];g.dates.push(date);g.values.push(valid===expected?sum:null);g.valid.push(valid);g.expected.push(expected);}
    let sum=0,valid=0,expected=0;
    for(const symbol of BASKET){const f=funds.find(f=>f.symbol===symbol);if(!f||date<fundStartDate(f))continue;expected++;const v=raw[symbol]?.[date]?.flow;if(finite(v)){sum+=Number(v);valid++;}}
    basket.netflow.push(expected>0&&valid===expected?sum:null);basket.coverage.push(valid);basket.expected.push(expected);
  }
  const total=dates.map((_,i)=>CATEGORIES.every(c=>group[c].values[i]!==null)?CATEGORIES.reduce((s,c)=>s+group[c].values[i],0):null);
  return {dates,basket,broad:{dates,cats:CATEGORIES,colors:COLORS,series:Object.fromEntries(CATEGORIES.map(c=>[c,group[c].values])),coverage:Object.fromEntries(CATEGORIES.map(c=>[c,{valid:group[c].valid,expected:group[c].expected}])),total,issues}};
}
export function aggregateMinute(rows, symbols, date) {
  const by=new Map(symbols.map(s=>[s,new Map()]));
  for(const r of rows){if(chinaDate(r.ts_millis)!==date||!by.has(r.symbol))continue;by.get(r.symbol).set(chinaTime(r.ts_millis),r);}
  return {date,slots:SLOTS,bars:SLOTS.map(t=>{let sum=0;for(const s of symbols){const r=by.get(s).get(t);if(!r||!finite(r.turnover))return null;sum+=Number(r.turnover);}return sum/1e8;}),coverage:SLOTS.map(t=>symbols.filter(s=>by.get(s).has(t)).length)};
}
export function cumulative(bars) { return strictCumulative(bars); }
export async function mapLimit(items, max, fn) {const out=new Array(items.length);let next=0;await Promise.all(Array.from({length:Math.min(max,items.length)},async()=>{while(next<items.length){let i=next++;out[i]=await fn(items[i],i);}}));return out;}
export function split(items,n){const out=[];for(let i=0;i<items.length;i+=n)out.push(items.slice(i,i+n));return out;}
