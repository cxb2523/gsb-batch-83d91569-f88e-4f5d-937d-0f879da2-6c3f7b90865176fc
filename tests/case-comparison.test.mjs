import test from 'node:test';
import assert from 'node:assert/strict';
import { cumulativeExcess } from '../src/assets/flow-math.js';

test('case line is cumulative excess turnover, including negative minute differences',()=>{
  const event=[8,4,6],normal=[3,5,2];
  const excess=cumulativeExcess(event,normal);
  assert.deepEqual(excess,[5,4,8]);
  assert.equal(excess.at(-1),event.reduce((s,v)=>s+v,0)-normal.reduce((s,v)=>s+v,0));
});
test('missing reference or event data cannot become zero or restart cumulative',()=>{
  assert.deepEqual(cumulativeExcess([8,null,6],[3,5,2]),[5,null,null]);
  assert.deepEqual(cumulativeExcess([8,4,6],[3]),[5,null,null]);
  assert.deepEqual(cumulativeExcess([null,null],[null,null]),[null,null]);
});
