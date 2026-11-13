// 真实事件层不可用的四档分类、回执渲染、错误判定。
//
// 这一组守的是这次改动的核心承诺：降级不能吞成静默失败，也不能把普通事件的
// 结果冒充成真实事件的结果。分类和文案都是纯函数，不必开真 Chrome 就能测。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  L2_CODE, L2_REASONS, classifyAttachError, isL2LayerLost,
  l2ReasonInfo, isL2Unavailable, reasonOfError, l2Lines, l2Tag,
} from '../extension/l2-reason.js';

// ---------- 分类 ----------

test('四类不可用各有自己的错误码，不共用 L2_BUSY', () => {
  // 共用码会把「开关被关」和「DevTools 占着」说成同一件事，
  // 而它们的处理动作完全不同（去开开关 vs 关 DevTools）
  const codes = Object.values(L2_CODE);
  assert.equal(new Set(codes).size, 4, `错误码应互异：${codes.join(', ')}`);
  assert.deepEqual(new Set(codes), new Set(['NEEDS_L2', 'L2_BUSY', 'L2_PROTECTED', 'L2_ATTACH']));
});

test('每一档都有分类词、原因、可操作的处理提示', () => {
  for (const key of Object.keys(L2_REASONS)) {
    const info = l2ReasonInfo(key);
    assert.equal(info.reason, key);
    assert.ok(info.label, `${key} 缺分类词`);
    assert.ok(info.title, `${key} 缺原因`);
    // 处理提示要能照着做：至少得指名一个动作或去处
    assert.match(info.hint, /重试|打开|关掉|换一个|重启|重新加载|手动/, `${key} 的处理提示不可操作：${info.hint}`);
    assert.ok(L2_CODE[key], `${key} 缺错误码`);
  }
});

test('未知分类退到「接入失败」，不抛也不吞', () => {
  const info = l2ReasonInfo('something-new');
  assert.equal(info.reason, 'attach');
  assert.equal(info.code, 'L2_ATTACH');
});

test('attach 报错按内容分到对的档', () => {
  // 用户自己开着 DevTools 是最常见的一种
  assert.equal(classifyAttachError('Another debugger is already attached to the tab with id: 123'), 'busy');
  assert.equal(classifyAttachError('Cannot access a chrome:// URL'), 'protected');
  assert.equal(classifyAttachError('Cannot access contents of the page'), 'protected');
  // 认不出来的一律归「接入失败」——宁可给泛化提示，也不要吞成「页面没反应」
  assert.equal(classifyAttachError('Some new Chrome error we have never seen'), 'attach');
  assert.equal(classifyAttachError(''), 'attach');
  assert.equal(classifyAttachError(undefined), 'attach');
});

test('操作途中断开也归到「接入失败」，且能认出那几种话术', () => {
  assert.ok(isL2LayerLost('Detached while handling command.'));
  assert.ok(isL2LayerLost('Not attached to the page.'));
  assert.ok(isL2LayerLost('Target closed.'));
  assert.ok(!isL2LayerLost('Cannot access contents of the page'));
});

// ---------- 错误判定 ----------

test('只有层不可用的错误才算 L2 不可用', () => {
  // REF_NOT_FOUND / INTERNAL 是动作本身的问题，混进来会让 agent 收到
  // 「真实事件没接上」的错误结论——元素没找到跟路通不通是两件事
  for (const code of Object.values(L2_CODE)) {
    assert.ok(isL2Unavailable({ code }), `${code} 应算层不可用`);
  }
  assert.ok(!isL2Unavailable({ code: 'REF_NOT_FOUND' }));
  assert.ok(!isL2Unavailable({ code: 'INTERNAL' }));
  assert.ok(!isL2Unavailable(null));
  assert.ok(!isL2Unavailable(new Error('plain')));
});

test('错误 → 分类优先认 reasonKey，退而按 code 认', () => {
  assert.equal(reasonOfError({ reasonKey: 'protected', code: 'L2_BUSY' }), 'protected');
  assert.equal(reasonOfError({ code: 'L2_BUSY' }), 'busy');
  assert.equal(reasonOfError({ code: 'NEEDS_L2' }), 'disabled');
  assert.equal(reasonOfError(new Error('x')), null);
  assert.equal(reasonOfError(null), null);
});

// ---------- 回执 ----------

test('完全没尝试真实事件：一个字都不印', () => {
  // 普通事件成功的回执不该出现「真实事件」四个字，否则 agent 会以为
  // 那次结果来自真实事件
  assert.deepEqual(l2Lines({ attempted: false }), []);
  assert.deepEqual(l2Lines(null), []);
  assert.equal(l2Tag({ attempted: false }), '');
});

test('接上了：明确写「已接入」', () => {
  const lines = l2Lines({ attempted: true, used: true, degraded: false });
  assert.equal(lines.length, 1);
  assert.match(lines[0], /已接入 ✓/);
  // 不能出现「没接上」——成功和失败必须一眼分得开
  assert.doesNotMatch(lines[0], /没接上/);
});

test('没接上：分类、原因、处理三样都要有，并写明普通事件也试过', () => {
  const lines = l2Lines({
    attempted: true, used: false, degraded: true,
    reason: 'disabled', code: 'NEEDS_L2',
    title: '高保真模式被关掉了', detail: '', hint: L2_REASONS.disabled.hint,
  }).join('\n');
  assert.match(lines, /没接上 ✗/);
  assert.match(lines, /开关被关/);
  assert.match(lines, /NEEDS_L2/);
  assert.match(lines, /原因：高保真模式被关掉了/);
  assert.match(lines, /处理：.*打开开关/);
  // 起手就用真实事件（real:true / 风控站起点）：降级后普通事件仍会照常试一次，
  // 回执要说明这一次的结果来自普通事件，不是真实事件
  assert.match(lines, /这次只走了普通事件/);
});

test('自动升级失败：说明是「普通事件无效 → 升级」这条路走到的', () => {
  const lines = l2Lines({
    attempted: true, used: false, degraded: true, auto: true,
    reason: 'busy', code: 'L2_BUSY',
  }).join('\n');
  assert.match(lines, /调试器被占用/);
  // 这条路上普通事件先试过一次、没效果，升级又没接上，两条都要有交代
  assert.match(lines, /普通事件已经照常试过一次/);
  assert.doesNotMatch(lines, /这次只走了普通事件/);
});

test('操作途中断开：提醒可能已部分送达，别直接重试', () => {
  const lines = l2Lines({
    attempted: true, used: false, degraded: true, phase: 'dispatch',
    reason: 'attach', code: 'L2_ATTACH',
  }).join('\n');
  assert.match(lines, /操作途中断开/);
  assert.match(lines, /别直接重试/);
});

test('act 的单行版本只压结论，不铺原因', () => {
  const one = l2Tag({ attempted: true, used: false, degraded: true, reason: 'protected', code: 'L2_PROTECTED' });
  assert.match(one, /浏览器保护页/);
  assert.match(one, /L2_PROTECTED/);
  assert.ok(!one.includes('\n'), 'act 的每一步只占一行');
  assert.ok(!one.includes('处理：'), 'act 的单行版本不铺处理提示');
  // 接上了标一句，压根没尝试时不占用那一行
  assert.equal(l2Tag({ attempted: true, used: true }), '真实事件 ✓');
  assert.equal(l2Tag({ attempted: true, degraded: false }), '');
  assert.equal(l2Tag({ attempted: false }), '');
});

test('detail 会带上 Chrome 的原始报错，便于排查', () => {
  const lines = l2Lines({
    attempted: true, used: false, degraded: true,
    reason: 'attach', code: 'L2_ATTACH', detail: 'boom',
  }).join('\n');
  assert.match(lines, /boom/);
});
