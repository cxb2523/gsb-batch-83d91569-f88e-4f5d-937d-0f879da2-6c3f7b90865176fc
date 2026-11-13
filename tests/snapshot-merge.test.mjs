import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { mergeSnapshot } from '../scripts/lib/merge-snapshot.mjs';
import { validateSeed } from '../scripts/lib/seed.mjs';
const example = JSON.parse(await readFile(new URL('../data/demo-seed.json', import.meta.url), 'utf8'));
function live() { const s = structuredClone(example); delete s.demo; s.provider = 'FTShare'; return s; }
test('recollection retains previously complete historical aggregates when the API no longer returns old records', () => {
  const previous = live(), next = live(), c = next.categories[0];
  next.broad.series[c][0] = null; next.broad.coverage[c].valid[0] = 0; next.broad.total[0] = null;
  next.broad.issues[next.broad.dates[0]] = [{ symbol: '510300.SH', bucket: c, reasons: ['share_missing'] }];
  next.history.netflow[0] = null; next.history.flow_coverage[0] = 0;
  const merged = validateSeed(mergeSnapshot(previous, next), 'live');
  assert.equal(merged.broad.total[0], previous.broad.total[0]); assert.equal(merged.history.netflow[0], previous.history.netflow[0]);
  assert.equal(merged.broad.issues[merged.broad.dates[0]], undefined); assert(merged.source_audit.preserved_category_days > 0);
});
test('changed member classification cannot silently reuse an old aggregate', () => {
  const old = live(), next = live(); next.universe[0].bucket = '其他宽基';
  assert.throws(() => mergeSnapshot(old, next), /different members/); assert.throws(() => mergeSnapshot(example, next));
});
