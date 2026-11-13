import test from 'node:test';
import assert from 'node:assert/strict';
import {fundStartDate,strictCumulative,cumulativeWindow} from '../src/assets/flow-math.js';
import {fundDaily,aggregateFunds,FLOW_POLICY} from '../src/server/model.js';
test('interval cumulative stops at the first gap and cannot hide later outflows',()=>{
 assert.deepEqual(strictCumulative([3,null,-100,8]),[3,null,null,null]);
 assert.deepEqual(strictCumulative([null,3]),[null,null]);
 assert.deepEqual(strictCumulative([3,0,-1]),[3,3,2]);
});
test('coverage counts valid later dates while keeping whole-interval cumulative unknown',()=>{
 const r=cumulativeWindow(['2026-04-27','2026-04-28','2026-04-29','2026-04-30'],[1,null,-10,5]);
 assert.equal(r.completeDays,3);assert.equal(r.missingDays,1);assert.equal(r.firstMissingDate,'2026-04-28');assert.equal(r.cumulativeThrough,'2026-04-27');assert.deepEqual(r.values,[1,null,null,null]);assert.deepEqual(r.lastCompleteRange,{start:'2026-04-29',end:'2026-04-30'});
});
test('a selected complete interval restarts cumulative at its own first day',()=>{
 const r=cumulativeWindow(['2026-04-29','2026-04-30'],[-10,5]);assert.deepEqual(r.values,[-10,-5]);assert.equal(r.missingDays,0);assert.equal(r.cumulativeThrough,'2026-04-30');
 assert.equal(cumulativeWindow(['2026-04-28'],[null]).lastCompleteRange,null);
});
test('fund eligibility uses the later of inception and listing dates',()=>{
 assert.equal(fundStartDate({inception_date:'2026-04-09',listed_date:'2026-04-28'}),'2026-04-28');
 assert.equal(fundStartDate({inception_date:'2025-09-11',listed_date:'2021-06-28'}),'2025-09-11');
});
const cal=['2026-04-24','2026-04-27','2026-04-28','2026-04-29'];
const fund={symbol:'589270.SH',name:'科创100Q',bucket:'其他宽基',inception_date:'2026-04-09',listed_date:'2026-04-28'};
const shares=[{statistics_period:'日',trade_date:20260428,fund_share:'100000000'},{statistics_period:'日',trade_date:20260429,fund_share:'110000000'}];
const navs=[{nav_date:20260428,unit_nav:'1'},{nav_date:20260429,unit_nav:'1'}];
test('pre-listing funds do not create missing category days, but listing-day baseline remains unknown',()=>{
 const days=fundDaily(fund,shares,navs,cal);assert.equal(days['2026-04-27'].not_yet_listed,true);assert.equal(days['2026-04-28'].flow,null);assert.deepEqual(days['2026-04-28'].issues,['listing_baseline_missing']);assert(Math.abs(days['2026-04-29'].flow-0.1)<1e-12);
 const a=aggregateFunds([fund],{[fund.symbol]:days},cal);assert.equal(a.broad.coverage['其他宽基'].expected[0],0);assert.equal(a.broad.total[0],0);assert.equal(a.broad.total[1],null);assert.equal(a.broad.issues['2026-04-27'],undefined);assert.equal(a.broad.issues['2026-04-28'][0].reasons[0],'listing_baseline_missing');
});
test('missing NAV and mechanical share/NAV anomalies retain distinct reasons',()=>{
 const f={symbol:'510300.SH',inception_date:'2010-01-01',listed_date:'2010-01-01'},c=['2026-11-02','2026-11-03'];
 const shares=[{statistics_period:'日',trade_date:20261102,fund_share:'100'},{statistics_period:'日',trade_date:20261103,fund_share:'200'}];
 assert.deepEqual(fundDaily(f,shares,[],c)['2026-11-03'].issues,['nav_missing']);
 assert.deepEqual(fundDaily(f,shares,[{nav_date:20261102,unit_nav:'1'},{nav_date:20261103,unit_nav:'0.5'}],c)['2026-11-03'].issues,['share_change_review']);
});
