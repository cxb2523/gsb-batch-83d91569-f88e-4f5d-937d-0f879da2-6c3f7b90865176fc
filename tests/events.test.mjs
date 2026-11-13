// Synthetic values; these cases exercise verified events, not a market-data fixture.
import test from 'node:test';
import assert from 'node:assert/strict';
import { fundDaily, estimateFlow } from '../src/server/model.js';
test('an IPO baseline requires the preceding day and business opening evidence', () => {
  const fund = { symbol: '510300.SH', inception_date: '2026-02-01', listed_date: '2026-02-24' };
  const baseline = { date: '2026-02-23', fund_share: '100000000', subscription_start_date: '2026-02-24', redemption_start_date: '2026-02-24' };
  const shares = [{ trade_date: 20260224, statistics_period: '日', fund_share: '90000000' }], nav = [{ nav_date: 20260224, unit_nav: '1' }], cal = ['2026-02-23', '2026-02-24'];
  assert(Math.abs(fundDaily({ ...fund, flow_evidence: { listing_baseline: baseline } }, shares, nav, cal)[cal[1]].flow + .1) < 1e-12);
  assert.equal(fundDaily({ ...fund, flow_evidence: { listing_baseline: { ...baseline, redemption_start_date: '2026-02-20' } } }, shares, nav, cal)[cal[1]].flow, null);
});
test('verified splits correct shares and tolerate only the documented factor rounding', () => {
  const fund = { symbol: '159915.SZ', inception_date: '2020-01-01', flow_evidence: { splits: [{ date: '2026-02-24', ratio: 2.5, source: { verified_official_event: true } }] } };
  const shares = [{ statistics_period: '日', trade_date: 20260224, fund_share: '100000000' }, { statistics_period: '日', trade_date: 20260225, fund_share: '251000000' }];
  const nav = [{ nav_date: 20260223, unit_nav: '5', adjustment_factor: '.2' }, { nav_date: 20260224, unit_nav: '2', adjustment_factor: '.500000958' }];
  assert.equal(fundDaily(fund, shares, nav, ['2026-02-23', '2026-02-24', '2026-02-25'])['2026-02-24'].flow, .02);
  assert.equal(fundDaily({ ...fund, flow_evidence: {} }, shares, nav, ['2026-02-23', '2026-02-24', '2026-02-25'])['2026-02-24'].flow, null);
});
test('high precision split ratios retain the economically material residual', () => {
  assert(Math.abs(estimateFlow({ fund_share: '500000000' }, { fund_share: '1000000000' }, { unit_nav: '2' }, { unit_nav: '.943285796' }, .471642898) - .56714204) < 1e-12);
});
