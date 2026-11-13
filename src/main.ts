import 'ol/ol.css';
import './style.css';
import { createMap, type Tool } from './map';
import { assignUniqueIds, countVertices, validateCollection, type Collection } from './geojson';

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
$('app').innerHTML = `
<header class="topbar"><a class="brand" href="/">◈ <span>Map Lab<small>交互地图教学实验室</small></span></a><span class="edition">OPENLAYERS / LESSON 01</span><a href="#guide" class="guide-link">学习指引 ↗</a></header>
<main><aside class="panel"><div class="intro"><span class="eyebrow">LEARN BY EXPLORING</span><h1>把想法，放到地图上。</h1><p>从一个点开始，理解图层、交互与地理数据。</p></div>
<section><div class="section-head"><h2>交互工具</h2><span>01</span></div><div class="tools" aria-label="交互工具"><button data-tool="select" class="active">↖ 选择</button><button data-tool="Point">⊕ 标注点</button><button data-tool="LineString">⌁ 绘制线</button><button data-tool="Polygon">◇ 绘制面</button><button data-tool="modify">⤧ 编辑顶点</button><button id="fit">⊞ 适配视图</button></div><p id="tool-hint" class="hint">点击地图要素或下方列表查看属性。</p></section>
<section><div class="section-head"><h2>数据图层</h2><span id="feature-count">0 个要素</span></div><label class="toggle"><input id="online" type="checkbox"><span>OpenStreetMap 在线底图<small>需联网 · 显示提供方署名</small></span></label><div id="features" class="feature-list"></div></section>
<section id="inspector" hidden><div class="section-head"><h2>选中要素</h2><span id="geometry-type"></span></div><label for="feature-name">要素名称</label><input id="feature-name" maxlength="80"><p id="measure" class="hint"></p><div class="inline"><button id="rename">保存名称</button><button id="delete" class="danger">删除要素</button></div></section>
<section><div class="section-head"><h2>GeoJSON 数据</h2><span>02</span></div><div class="data-actions"><button id="export">↓ 导出 GeoJSON</button><button id="import">↑ 批量导入</button><input id="file" type="file" accept=".geojson,.json,application/geo+json,application/json" multiple hidden></div><div id="import-report" class="import-report" hidden><div class="section-head"><h3>导入结果</h3><span id="import-summary"></span></div><ul id="import-list"></ul></div><div class="inline"><button id="reset" class="text-button">恢复示例</button><button id="clear" class="text-button danger">清空图层</button></div></section>
</aside><div class="map-column"><div class="map-heading"><div><span class="live-dot"></span><strong>教学园区 · 示意数据</strong></div><span id="basemap-mode">离线底图</span></div><div id="map" tabindex="0" aria-label="交互地图，使用侧边工具添加或选择要素"></div><div class="map-status"><span>EPSG:3857 <b>→</b> WGS84</span><output id="coordinates">移动指针查看经纬度</output></div><div id="message" role="status">示意底图不代表真实建筑或道路。所有操作都在本地完成。</div><section id="guide" class="guide"><span class="eyebrow">THREE THINGS TO TRY</span><div><article><b>01 / 图层与要素</b><p>选择「标注点」，点击地图新增；再切回选择工具，修改名称。</p></article><article><b>02 / 坐标与投影</b><p>地图显示使用 Web Mercator，GeoJSON 导入导出始终使用 WGS84。</p></article><article><b>03 / 数据往返</b><p>导出你的图层，再导入文件。多点线面可以一起保存。</p></article></div></section></div></main>
<dialog id="confirm"><h2 id="confirm-title">确认操作</h2><p id="confirm-text">此操作会替换当前工作区的要素，请先导出需要保留的数据。</p><div class="inline"><button id="cancel">取消</button><button id="confirm-go" class="primary">确认</button></div></dialog>`;
const message = (text: string, error = false) => { $('message').textContent = text; $('message').classList.toggle('error', error); };
let refreshPending = false;
const app = createMap($('map'), {
 change: () => { if (!refreshPending) { refreshPending = true; queueMicrotask(() => { refreshPending = false; refresh(); }); } },
 select: (feature) => { $('inspector').hidden = !feature; if (feature) { $<HTMLInputElement>('feature-name').value = String(feature.get('name') ?? ''); $('geometry-type').textContent = feature.getGeometry()!.getType(); $('measure').textContent = app.measure(feature); } },
 coordinate: (value) => { $('coordinates').textContent = value; }, tileError: () => message('在线瓦片加载失败；可关闭在线底图，继续使用离线示例。', true),
});
const hints: Record<Tool, string> = { select: '点击地图要素或下方列表查看属性。', Point: '点击地图添加一个点，可连续添加。', LineString: '点击添加节点，双击结束绘制；Esc 取消当前绘制。', Polygon: '点击添加节点，双击闭合区域；Esc 取消当前绘制。', modify: '先选择要素，再拖动顶点调整形状。面积与长度为球面近似。' };
function tool(value: Tool) { app.setTool(value); updateTool(); }
function updateTool() { const current = app.getMode(); document.querySelectorAll<HTMLButtonElement>('[data-tool]').forEach((button) => { button.classList.toggle('active', button.dataset.tool === current); button.setAttribute('aria-pressed', String(button.dataset.tool === current)); }); $('tool-hint').textContent = hints[current]; }
function refresh() {
 const features = app.source.getFeatures(); $('feature-count').textContent = `${features.length} 个要素`; $('features').replaceChildren();
 if (!features.length) $('features').textContent = '暂无要素，试试在地图上添加一个点。';
 for (const feature of features) { const button = document.createElement('button'); button.className = 'feature-item'; button.textContent = `${feature.getGeometry()?.getType() === 'Point' ? '●' : '◇'}  ${feature.get('name')}`; button.addEventListener('click', () => { app.choose(String(feature.getId())); updateTool(); }); $('features').append(button); }
 if (app.selected()) $('measure').textContent = app.measure(app.selected()!);
 updateTool();
}
let confirmed: (() => void) | null = null; let cancelled: (() => void) | null = null;
function confirm(title: string, run: () => void, text = '此操作会替换当前工作区的要素，请先导出需要保留的数据。', onCancel?: () => void) { $('confirm-title').textContent = title; $('confirm-text').textContent = text; confirmed = run; cancelled = onCancel ?? null; $<HTMLDialogElement>('confirm').showModal(); }
$('cancel').addEventListener('click', () => { $<HTMLDialogElement>('confirm').close(); confirmed = null; const run = cancelled; cancelled = null; run?.(); }); $('confirm-go').addEventListener('click', () => { $<HTMLDialogElement>('confirm').close(); cancelled = null; confirmed?.(); confirmed = null; });
document.querySelectorAll<HTMLButtonElement>('[data-tool]').forEach((button) => button.addEventListener('click', () => tool(button.dataset.tool as Tool)));
$('fit').addEventListener('click', app.fit); $('online').addEventListener('change', () => { const enabled = $<HTMLInputElement>('online').checked; app.toggleOnline(enabled); $('basemap-mode').textContent = enabled ? 'OpenStreetMap' : '离线底图'; });
$('rename').addEventListener('click', () => { const name = $<HTMLInputElement>('feature-name').value.trim(); if (!name || name.length > 80) { message('名称应为 1–80 个字符', true); return; } app.selected()?.set('name', name); message('名称已更新。'); });
$('delete').addEventListener('click', () => { app.removeSelected(); message('要素已删除。'); });
$('reset').addEventListener('click', () => confirm('恢复示例数据？', () => { app.reset(); message('已恢复三个示例标注。'); }));
$('clear').addEventListener('click', () => confirm('清空当前图层？', () => { app.clear(); refresh(); message('图层已清空。'); }));
$('export').addEventListener('click', () => { try { const data = app.exportData(); const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/geo+json' })); const a = document.createElement('a'); a.href = url; a.download = 'map-lab.geojson'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); message(`已导出 ${data.features.length} 个要素，坐标为 WGS84。`); } catch (error) { message((error as Error).message, true); } });
$('import').addEventListener('click', () => $('file').click());
const MAX_BYTES = 1024 * 1024;
const MAX_FEATURES = 200;
const MAX_VERTICES = 10000;
// 单个批次文件数上限，避免误选整个目录时浏览器长时间阻塞（超出部分不读取并记为失败）。
const MAX_FILES = 50;
type ImportOutcome = { file: string; added: number; error?: string };
type ImportPlan = { file: File; data: Collection | null; error?: string; added: number };
function renderReport(outcomes: ImportOutcome[], summary: { added: number; failed: number; total: number }) {
 $('import-report').hidden = false; $('import-list').replaceChildren();
 for (const outcome of outcomes) {
  const item = document.createElement('li');
  item.className = outcome.error ? 'failed' : 'succeeded';
  item.dataset.file = outcome.file;
  item.dataset.status = outcome.error ? 'failed' : 'succeeded';
  const name = document.createElement('strong'); name.textContent = outcome.file;
  const detail = document.createElement('span'); detail.textContent = outcome.error ? `失败：${outcome.error}` : `成功：${outcome.added} 个要素`;
  item.append(name, detail); $('import-list').append(item);
 }
 $('import-summary').textContent = `成功 ${outcomes.length - summary.failed} · 失败 ${summary.failed} · 新增 ${summary.added} 个要素`;
}
async function readPlan(file: File): Promise<ImportPlan> {
 if (file.size > MAX_BYTES) return { file, data: null, error: '文件超过 1MB 限制', added: 0 };
 try { return { file, data: validateCollection(JSON.parse(await file.text())), added: 0 }; }
 catch (error) { return { file, data: null, error: (error as Error).message, added: 0 }; }
}
$('file').addEventListener('change', async () => {
 const files = Array.from($<HTMLInputElement>('file').files ?? []); if (!files.length) return;
 $<HTMLInputElement>('file').value = '';
 message(`正在读取 ${files.length} 个文件…`);
 // 先逐个读取并校验，全部结论确定后再统一确认，避免中途替换或半份数据。
 const plans: ImportPlan[] = [];
 for (const [index, file] of files.entries()) plans.push(index >= MAX_FILES ? { file, data: null, error: `单次最多导入 ${MAX_FILES} 个文件`, added: 0 } : await readPlan(file));
 const candidates: ImportPlan[] = [];
 let current = app.stats();
 const plannedIds = new Set(app.source.getFeatures().map((feature) => String(feature.getId())));
 for (const plan of plans) {
  if (plan.error || !plan.data) continue;
  const vertices = countVertices(plan.data);
  if (current.features + plan.data.features.length > MAX_FEATURES) { plan.error = `追加后将超过 ${MAX_FEATURES} 个要素上限（当前 ${current.features}，本文件 ${plan.data.features.length}）`; continue; }
  if (current.vertices + vertices > MAX_VERTICES) { plan.error = `追加后将超过 ${MAX_VERTICES} 个顶点上限（当前 ${current.vertices}，本文件 ${vertices}）`; continue; }
  try { plan.data = assignUniqueIds(plan.data, plannedIds); } catch (error) { plan.error = (error as Error).message; continue; }
  for (const feature of plan.data.features) plannedIds.add(feature.id);
  plan.added = plan.data.features.length;
  current = { features: current.features + plan.added, vertices: current.vertices + vertices };
  candidates.push(plan);
 }
 const failures = plans.filter((plan) => plan.error);
 const added = candidates.reduce((total, plan) => total + plan.added, 0);
 const report = (cancelled = false) => renderReport(
  plans.map((plan) => plan.error ? { file: plan.file.name, added: 0, error: plan.error } : cancelled ? { file: plan.file.name, added: 0, error: '已取消，未追加' } : { file: plan.file.name, added: plan.added }),
  { added: cancelled ? 0 : added, failed: cancelled ? plans.length : failures.length, total: plans.length },
 );
 if (added) confirm(`追加 ${added} 个要素到当前图层？`, () => {
  for (const plan of candidates) app.append(plan.data!);
  refresh(); report();
  message(`批量导入完成：成功 ${candidates.length} 个文件、新增 ${added} 个要素；失败 ${failures.length} 个文件。`, failures.length > 0);
 }, `本次将从 ${plans.length} 个文件中新增 ${added} 个要素，另有 ${failures.length} 个文件失败；当前已有要素不会被替换。`, () => {
  report(true); message('已取消批量导入，当前图层未改动。', true);
 });
 else {
  report();
  message(`批量导入失败：共 ${plans.length} 个文件，全部未能导入，当前图层未改动。`, true);
 }
});

window.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !$<HTMLDialogElement>('confirm').open) tool('select'); });
new ResizeObserver(() => app.map.updateSize()).observe($('map'));
