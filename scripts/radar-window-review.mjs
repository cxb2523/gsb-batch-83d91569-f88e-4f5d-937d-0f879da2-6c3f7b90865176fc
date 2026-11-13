// Offline diagnostic replay. Reads a local snapshot; never queries a data provider.
import { readFile, writeFile } from 'node:fs/promises';
import { evaluateRadar } from '../src/assets/radar-math.js';
const [seedPath, outputPath] = process.argv.slice(2);
if (!seedPath || !outputPath) throw new Error('Usage: node scripts/radar-window-review.mjs <seed.json> <report.md>');
const seed = JSON.parse(await readFile(seedPath, 'utf8'));
const rows = Object.entries(seed.minutes || {}).filter(([,r]) => !r.quality && r.bars?.length === seed.minute_slots.length && r.bars.every(Number.isFinite)).sort(([a],[b]) => a.localeCompare(b));
const checkpoints = ['10:00','11:00','14:00','15:00'];
const lines = ['# ETF异动雷达 · 20／60日窗口回放', '', '本报告只读取已有分钟缓存。对每个观察日，仅使用该日之前的完整快照，不引入当日或未来数据。', '', `完整快照：${rows[0]?.[0]}—${rows.at(-1)?.[0]}，${rows.length}日；各比较仅纳入此前已满60个完整快照的同一批观察日。`, '', '## 累计成交触发频率', '', '| 时点 | 倍数阈值 | 可比观察日 | 20日触发 | 60日触发 | 两者均触发 | 仅20日 | 仅60日 |', '|---|---|---|---|---|---|---|---|'];
const results=[];
for (const time of checkpoints) for (const threshold of [1.5,2]) {
  const at=seed.minute_slots.indexOf(time);if(at<0)continue;
  const count={days:0,recent:0,long:0,both:0,recentOnly:0,longOnly:0};
  for(const [date,r] of rows){
    const live={date,bars:r.bars,coverage:r.bars.map(()=>20),table:[]};
    const s=evaluateRadar(seed,live,{at,cumulative:threshold});
    if(!s.recent.ready||!s.long.ready||s.recent.multiple===null||s.long.multiple===null)continue;
    count.days++;if(s.recent.cumulativeAlert)count.recent++;if(s.long.cumulativeAlert)count.long++;
    if(s.cumulativeSignal==='both')count.both++;if(s.cumulativeSignal==='recent')count.recentOnly++;if(s.cumulativeSignal==='long')count.longOnly++;
  }
  const cell=n=>`${n}（${count.days?(100*n/count.days).toFixed(1):'—'}%）`;
  lines.push(`| ${time} | ${threshold}× | ${count.days} | ${cell(count.recent)} | ${cell(count.long)} | ${cell(count.both)} | ${cell(count.recentOnly)} | ${cell(count.longOnly)} |`);
  results.push({time,threshold,...count});
}
lines.push('', '## 如何解释', '', '- 以上是指定时点的触发频率，不是交易胜率、预测准确率或全天提醒次数。连续满足多分钟不重复计为多个交易日。', '- 60日窗口包含最近20日，两者相关；双基准确认是一种更严格的筛选条件，不代表两份独立证据。', '- 快照不完整的日期被剔除，窗口因此可能跨越更长的日历区间。样本范围及市场阶段会影响结果。', '- 暂保留1.5倍累计观察阈值、2倍短时阈值和5亿元短时下限。本次回放仅比较窗口与敏感度，没有按结果反复调参，也没有验证投资效果。', '- 日度净申赎阈值独立于分钟成交倍数，不参与本表。', '');
await writeFile(outputPath,lines.join('\n'));
console.log(JSON.stringify({completeDays:rows.length,first:rows[0]?.[0],last:rows.at(-1)?.[0],results},null,2));
