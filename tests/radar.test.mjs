import test from 'node:test';
import assert from 'node:assert/strict';
import { evaluateRadar } from '../src/assets/radar-math.js';
function fixture() {
  const slots = Array.from({length:31},(_,i)=>'09:'+String(30+i).padStart(2,'0'));
  const minutes = Object.fromEntries(Array.from({length:60},(_,i)=>[new Date(Date.UTC(2026,8,1+i)).toISOString().slice(0,10),{bars:slots.map(()=>1)}]));
  const seed = {minute_slots:slots,minutes,core_fund_daily:{date:'2026-11-11',rows:[{symbol:'ETF',flow:12}]}};
  const live = {date:'2026-11-12',bars:slots.map(()=>1),coverage:slots.map(()=>20),closes:slots.map(()=>3500),pre_close:3520,table:[{symbol:'ETF',amount:123}]};
  return {seed,live};
}
test('cumulative volume compares the same progress and ignores later minutes',()=>{
  const{seed,live}=fixture();live.bars=live.bars.map((_,i)=>i<=15?2:10000);
  const s=evaluateRadar(seed,live,{at:15});assert.equal(s.amount,32);assert.equal(s.reference,16);assert.equal(s.multiple,2);assert.equal(s.state,'strong');
});
test('today, future days and incomplete baseline days cannot enter the comparison',()=>{
  const{seed,live}=fixture();seed.minutes['2026-11-12']={bars:live.bars.map(()=>10000)};seed.minutes['2026-11-13']={bars:live.bars.map(()=>20000)};
  seed.minutes['2026-11-10']={bars:[1,null]};seed.minutes['2026-11-09']={bars:live.bars,quality:'incomplete'};
  const s=evaluateRadar(seed,live);assert.equal(s.samples,20);assert.equal(s.multiple,1);assert(!s.sampleDates.some(d=>d>='2026-11-12'));
});
test('missing current minutes do not become zero or a normal cumulative signal',()=>{
  const{seed,live}=fixture();live.bars[2]=null;live.coverage[2]=0;const s=evaluateRadar(seed,live);assert.equal(s.amount,null);assert.equal(s.multiple,null);assert.equal(s.state,'incomplete');
  live.coverage=[];assert.equal(evaluateRadar(seed,live).state,'incomplete');
});
test('short windows never bridge the lunch break',()=>{
  const{seed,live}=fixture();seed.minute_slots=['11:28','11:29','11:30','13:01','13:02','13:03','13:04','13:05'];
  for(const r of Object.values(seed.minutes))r.bars=seed.minute_slots.map(()=>1);live.bars=seed.minute_slots.map(()=>1);live.coverage=seed.minute_slots.map(()=>20);
  assert.equal(evaluateRadar(seed,live,{at:6}).short.ratio,null);assert.equal(evaluateRadar(seed,live,{at:7}).short.ratio,1);
});
test('one burst window is an observation; two qualifying overlapping windows confirm persistence',()=>{
  const{seed,live}=fixture();live.bars[20]=10;
  assert.equal(evaluateRadar(seed,live,{at:20}).burstConfirmed,false);assert.equal(evaluateRadar(seed,live,{at:21}).burstConfirmed,true);
});
test('warmup, too few samples and zero denominators cannot produce strong signals',()=>{
  const{seed,live}=fixture();live.bars.fill(10);assert.equal(evaluateRadar(seed,live,{at:5}).state,'warming');
  seed.minutes=Object.fromEntries(Object.entries(seed.minutes).slice(0,4));assert.equal(evaluateRadar(seed,live).state,'insufficient');
  for(let i=5;i<=10;i++)seed.minutes['2026-09-'+String(i).padStart(2,'0')]={bars:live.bars.map(()=>0)};
  for(const r of Object.values(seed.minutes))r.bars.fill(0);assert.equal(evaluateRadar(seed,live).multiple,null);
});
test('daily flow retains its own attribution date, and absent or future records cannot imply a creation',()=>{
  const{seed,live}=fixture();const s=evaluateRadar(seed,live,{at:15});assert.equal(s.table[0].flowSignal,'creation');assert.equal(s.flowDate,'2026-11-11');
  delete seed.core_fund_daily;assert.equal(evaluateRadar(seed,live).table[0].flow,null);assert.equal(evaluateRadar(seed,live).creations,0);
  seed.core_fund_daily={date:'2026-11-13',rows:[{symbol:'ETF',flow:50}]};assert.equal(evaluateRadar(seed,live).creations,0);
});
test('raising the cumulative threshold changes both baselines together',()=>{
  const{seed,live}=fixture();live.bars.fill(2.2);
  const s=evaluateRadar(seed,live,{cumulative:4,burst:10});assert.equal(s.state,'normal');
});

test('both complete baselines must trigger before cumulative confirmation',()=>{
  const{seed,live}=fixture();live.bars.fill(1.6);const s=evaluateRadar(seed,live,{burst:10});
  assert.equal(s.recent.samples,20);assert.equal(s.long.samples,60);assert.equal(s.cumulativeSignal,'both');assert.equal(s.reason,'dual_cumulative');assert.equal(s.state,'strong');
});
test('a recent-only trigger stays an observation even when the recent ratio exceeds two',()=>{
  const{seed,live}=fixture();Object.entries(seed.minutes).sort(([a],[b])=>a.localeCompare(b)).slice(0,40).forEach(([,r])=>r.bars.fill(3));live.bars.fill(2.1);
  const s=evaluateRadar(seed,live,{burst:10});assert(s.recent.multiple>2);assert(s.long.multiple<1.5);assert.equal(s.reason,'recent');assert.equal(s.state,'watch');
});
test('a long-only trigger is not mislabeled as recent or dual confirmation',()=>{
  const{seed,live}=fixture();Object.entries(seed.minutes).sort(([a],[b])=>a.localeCompare(b)).slice(0,40).forEach(([,r])=>r.bars.fill(.3));live.bars.fill(1.2);
  const s=evaluateRadar(seed,live,{burst:10});assert.equal(s.cumulativeSignal,'long');assert.equal(s.reason,'long');assert.equal(s.state,'watch');
});
test('missing 60-day samples cannot silently fall back to a shorter confirmation window',()=>{
  const{seed,live}=fixture();delete seed.minutes[Object.keys(seed.minutes)[0]];live.bars.fill(3);
  const s=evaluateRadar(seed,live);assert.equal(s.long.samples,59);assert.equal(s.long.reference,null);assert.equal(s.long.multiple,null);assert.equal(s.long.burst,false);assert.equal(s.state,'watch');
  seed.minutes=Object.fromEntries(Object.entries(seed.minutes).slice(0,19));assert.equal(evaluateRadar(seed,live).state,'insufficient');
});
test('short-term confirmation requires sustained triggers against both windows',()=>{
  const{seed,live}=fixture();Object.entries(seed.minutes).sort(([a],[b])=>a.localeCompare(b)).slice(0,40).forEach(([,r])=>r.bars.fill(4));live.bars.fill(1);live.bars[20]=10;
  const s=evaluateRadar(seed,live,{at:21,cumulative:5});assert.equal(s.recent.burstConfirmed,true);assert.equal(s.long.burstConfirmed,false);assert.equal(s.burstDualConfirmed,false);assert.equal(s.state,'watch');
});
