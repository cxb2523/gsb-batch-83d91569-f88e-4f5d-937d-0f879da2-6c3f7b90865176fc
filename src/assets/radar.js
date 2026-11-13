import { evaluateRadar, RADAR_DEFAULTS } from './radar-math.js';
const fmt = (v, n = 1) => Number.isFinite(v) ? Number(v).toLocaleString('zh-CN', { minimumFractionDigits: n, maximumFractionDigits: n }) : '—';
const signed = v => Number.isFinite(v) ? (v > 0 ? '+' : '') + fmt(v, 2) : '—';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export function createRadar(root) {
  let seed, live, at = null, expanded = false;
  root.innerHTML = `<div class="radar-heading"><div><p class="eyebrow">ACTIVITY RADAR</p><h2>ETF 异动雷达<span>观察成交与申赎的变化</span></h2></div><span class="radar-session" id="radarSession">等待缓存</span></div>
    <div class="radar-board"><div class="radar-summary"><div><span class="radar-overline">20只核心 ETF · 成交活跃度</span><h3 id="radarState">等待可比数据</h3><p id="radarDescription">从共享缓存读取，不触发额外采集。</p></div><span class="radar-state-badge" id="radarBadge">待齐</span></div>
    <div class="radar-metrics"><div><span>累计成交额</span><strong id="radarAmount">—</strong><small id="radarAmountNote">—</small></div><div><span>20日 · 同进度倍数</span><strong id="radarMultiple">—</strong><small id="radarMultipleNote">—</small></div><div><span>60日 · 同进度倍数</span><strong id="radarLongMultiple">—</strong><small id="radarLongNote">—</small></div><div><span>近5分钟 · 20日 / 60日</span><strong id="radarBurst">—</strong><small id="radarBurstNote">—</small></div><div><span>上证指数涨跌</span><strong id="radarIndex">—</strong><small>与观察时点对应</small></div></div>
    <div class="radar-controls"><span class="radar-baselines">20日近期基准 × 60日辅助基准</span><label class="radar-replay">时点回放<input id="radarTime" type="range" min="0" max="240" value="240" aria-label="回放观察时点"><output id="radarTimeLabel">—</output></label><button id="radarFollow" type="button">跟随最新快照</button></div>
    <details class="radar-rules"><summary>信号规则与样本</summary><div class="radar-rule-inputs"><label>双基准累计阈值<input id="radarCumThreshold" type="number" min="1.1" max="5" step="0.1" value="1.5">倍</label><label>短时放量阈值<input id="radarBurstThreshold" type="number" min="1.2" max="10" step="0.1" value="2">倍</label><label>单只日度净申赎<input id="radarFlowThreshold" type="number" min="1" max="100" step="1" value="10">亿元</label></div><p>20日与60日均与历史同一时点比较，两者累计倍数都达到阈值才提示「持续关注」；仅20日触发为「近期放量」，仅60日触发为「长周期偏高」。短时信号要求5分钟成交额至少5亿元，两个基准连续两个逐分钟窗口都达到阈值才确认。开盘前15个交易分钟仅观察；每个基准须满20／60个完整历史交易日，样本不足不作双基准确认。</p><p id="radarSamples"></p><p>日度净申赎由每日份额与原始净值估算，按归属日期独立展示。以上为测试版初始观察阈值，尚未经过历史回测校准，可自行调整。</p></details></div>
    <div class="radar-funds-heading"><div><h3>单只 ETF · 日度资金信号</h3><p id="radarFundDates">等待共享快照</p></div><div class="radar-fund-counts" id="radarFundCounts"></div></div><div class="radar-funds" id="radarFunds"></div><button class="radar-expand" id="radarExpand" type="button">展开全部20只 ETF</button>`;
  const $ = id => root.querySelector('#' + id), number = (id, fallback, min, max) => { const v = parseFloat($(id).value); return Number.isFinite(v) ? Math.max(min, Math.min(max, v)) : fallback; };
  function render(nextSeed = seed, nextLive = live) {
    seed = nextSeed; live = nextLive; if (!seed || !live) return;
    const s = evaluateRadar(seed, live, { at, cumulative: number('radarCumThreshold', RADAR_DEFAULTS.cumulative, 1.1, 5), burst: number('radarBurstThreshold', RADAR_DEFAULTS.burst, 1.2, 10), fundFlow: number('radarFlowThreshold', RADAR_DEFAULTS.fundFlow, 1, 100) });
    const labels = { normal: '成交处于常态区间', warming: '开盘观察中', insufficient: '20日基准待齐', incomplete: '成交数据待齐' };
    const reasons = { dual_cumulative: ['持续关注 · 双基准放量', '20日与60日的同进度累计成交倍数均达到阈值。', '双基准确认'], dual_burst: ['持续关注 · 短时放量', '20日与60日的同窗短时倍数均已连续两个滚动窗口达到阈值。', '双基准确认'], recent: ['近期放量 · 继续观察', '20日累计倍数达到阈值，60日基准尚未确认。', '近期放量'], long: ['长周期偏高 · 继续观察', '仅60日累计倍数达到阈值，20日近期基准未触发。', '长周期偏高'], burst: ['短时放量 · 继续观察', '短时成交达到观察阈值，尚未满足双基准连续窗口确认。', '短时观察'] };
    let [title, description, badge] = reasons[s.reason] || [labels[s.state], s.state === 'incomplete' ? '当前累计包含缺失分钟，累计倍数暂不判断。' : s.state === 'insufficient' ? '至少需要20个完整历史交易日，样本不足时不产生放量判断。' : s.state === 'warming' ? '开盘初段先观察成交节奏，满15个交易分钟后判定放量。' : '当前可比成交数据未触及所设放量阈值。', ({ normal: '常态', warming: '开盘观察', insufficient: '样本不足', incomplete: '数据待齐' })[s.state]];
    if (!s.long.ready) description += ' 60日样本待齐（' + s.long.samples + '/60），不作双基准确认。';
    root.dataset.state = s.state; $('radarState').textContent = title; $('radarDescription').textContent = description; $('radarBadge').textContent = badge;
    const now = new Date(Date.now() + 8 * 3600000).toISOString(), phase = s.date < now.slice(0, 10) ? '历史快照' : now.slice(11, 16) >= '15:00' ? '已收盘' : now.slice(11, 16) >= '11:30' && now.slice(11, 16) < '13:00' ? '午间休市' : '盘中观察';
    $('radarSession').textContent = phase + ' · ' + s.date;
    $('radarAmount').innerHTML = fmt(s.amount) + '<em>亿元</em>'; $('radarAmountNote').textContent = s.time ? '截至 ' + s.time + (at === null ? ' · 最新缓存' : ' · 回放时点') : '等待完整分钟';
    $('radarMultiple').innerHTML = fmt(s.multiple, 2) + '<em>×</em>'; $('radarMultipleNote').textContent = '均值 ' + fmt(s.reference) + '亿 · ' + s.recent.samples + '/20日';
    $('radarLongMultiple').innerHTML = fmt(s.long.multiple, 2) + '<em>×</em>'; $('radarLongNote').textContent = '均值 ' + fmt(s.long.reference) + '亿 · ' + s.long.samples + '/60日';
    $('radarBurst').innerHTML = fmt(s.recent.short.ratio, 2) + '<em> / </em>' + fmt(s.long.short.ratio, 2) + '<em>×</em>'; $('radarBurstNote').textContent = s.short.range ? seed.minute_slots[s.short.range[0]] + '—' + s.time + ' · ' + fmt(s.short.amount) + '亿' : '当前时段未满5分钟';
    $('radarIndex').textContent = signed(s.indexPct) + (s.indexPct === null ? '' : '%'); $('radarIndex').className = s.indexPct > 0 ? 'positive' : s.indexPct < 0 ? 'negative' : '';
    $('radarTime').max = Math.max(0, s.last); $('radarTime').value = Math.max(0, s.end); $('radarTimeLabel').textContent = s.time || '—'; $('radarFollow').classList.toggle('is-following', at === null);
    $('radarSamples').textContent = [s.recent,s.long].map(b => b.window + '日基准：' + b.samples + '/' + b.window + '日' + (b.samples ? '（' + b.sampleDates.at(-1) + '—' + b.sampleDates[0] + '）' : '')).join('；') + '。仅使用观察日之前的完整快照。';
    $('radarFundDates').textContent = '行情 ' + live.date + ' ' + (live.last_complete_minute || '—') + ' ｜ 净申赎归属 ' + (s.flowDate || '待归档') + '，与回放时点分开展示';
    $('radarFundCounts').innerHTML = `<span class="flow-creation">净申购偏大 ${s.creations}只</span><span class="flow-redemption">净赎回偏大 ${s.redemptions}只</span>`;
    const funds = expanded ? s.table : s.table.slice(0, 6), names = new Map(seed.universe.map(f => [f.symbol, f]));
    $('radarFunds').innerHTML = funds.map(f => { const meta = names.get(f.symbol), badge = f.flowSignal === 'creation' ? '日度净申购偏大' : f.flowSignal === 'redemption' ? '日度净赎回偏大' : !Number.isFinite(f.flow) ? '日度数据待齐' : '未触及日度阈值'; return `<article class="radar-fund ${f.flowSignal || ''}"><div class="radar-fund-title"><h4 title="${esc(meta?.name || f.name)}">${esc(meta?.name || f.name)}</h4><span>${badge}</span></div><p class="radar-fund-code">${esc(f.symbol)} · ${esc(meta?.bucket || '')}</p><div class="radar-fund-values"><div><small>最新价</small><b>${fmt(f.price, 4)}</b></div><div><small>行情涨跌幅</small><b class="${f.pct > 0 ? 'positive' : f.pct < 0 ? 'negative' : ''}">${signed(f.pct)}${f.pct === null ? '' : '%'}</b></div><div><small>当日成交额</small><b>${fmt(f.amount, 2)}<em>亿</em></b></div></div><div class="radar-fund-flow"><span>日度净申购估算<small>${esc(f.flowDate || '数据待齐')}</small></span><strong class="${f.flow > 0 ? 'positive' : f.flow < 0 ? 'negative' : ''}">${signed(f.flow)}<em>亿</em></strong></div></article>`; }).join('');
    $('radarExpand').textContent = expanded ? '收起为重点6只 ETF' : '展开全部' + s.table.length + '只 ETF';
  }
  for (const id of ['radarCumThreshold', 'radarBurstThreshold', 'radarFlowThreshold']) $(id).addEventListener('input', () => render());
  $('radarTime').addEventListener('input', () => { at = Number($('radarTime').value); render(); });
  $('radarFollow').addEventListener('click', () => { at = null; render(); });
  $('radarExpand').addEventListener('click', () => { expanded = !expanded; render(); });
  return { render };
}
