<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Activity, ArrowDownLeft, ArrowRight, ArrowUpRight, ChevronLeft, ChevronRight, CircleHelp, Clock3, History, LoaderCircle, Search, X } from '@lucide/vue'

interface Group { label: string; connections: number; upload: number; download: number }
interface RecordRow {
  key: string; host: string; port: string; source: string; process: string; node: string
  route: string; category: string; network: string; inbound: string; started: number; first_seen: number; last_seen: number
  period_upload: number; period_download: number; preexisting: number; state: string; activity: string
}
interface Gap { started: number; ended: number | null; reason: string }
interface Report {
  range: { start: number; end: number }
  totals: { upload: number; download: number; connections: number }
  groups: { rows: Group[]; total: number; page: number; page_size: number }
  records: { rows: RecordRow[]; total: number; page: number; page_size: number }
  series: { at: number; upload: number; download: number; incomplete: boolean }[]; bucket_seconds: number
  gaps: Gap[]; gap_count: number
  collector: { started: number; retained_from: number; last_success: number | null; healthy: boolean; interval_seconds: number; retention_days: number }
}
const props = defineProps<{ request: (path: string) => Promise<Report> }>()
const report = ref<Report | null>(null)
const loading = ref(false)
const error = ref('')
const quick = ref('24h')
const start = ref(localInput(Date.now() - 86400000))
const end = ref(localInput(Date.now()))
const groupBy = ref('category')
const route = ref('all')
const search = ref('')
const groupValue = ref<string | null>(null)
const page = ref(1)
const groupPage = ref(1)
const groupNames: Record<string, string> = { category: '用途分类', domain: '目标域名', source: '来源 IP', node: '转发节点', route: '出网方式', inbound: '接入入口' }
const routeNames: Record<string, string> = { direct: '直连', proxy: '代理', reject: '拒绝', unknown: '未分类' }
const stateNames: Record<string, string> = { observed: '仍被记录', not_seen: '未再观测', unknown: '状态待确认' }
const gapNames: Record<string, string> = { collector_restart: '采集进程重启', controller_unavailable: '采集连接中断', collection_delay: '采样延迟', counter_reset: '连接计数重置' }
let serial = 0
let timer: ReturnType<typeof setInterval> | undefined
const groupPages = computed(() => Math.max(1, Math.ceil((report.value?.groups.total ?? 0) / (report.value?.groups.page_size ?? 20))))
const recordPages = computed(() => Math.max(1, Math.ceil((report.value?.records.total ?? 0) / (report.value?.records.page_size ?? 20))))
const total = computed(() => (report.value?.totals.upload ?? 0) + (report.value?.totals.download ?? 0))
const chartMax = computed(() => Math.max(1, ...report.value?.series.map(p => p.upload + p.download) ?? []))

function localInput(ms: number) {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(ms).replace(' ', 'T')
}
function bytes(n: number) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`
}
function date(n: number | null, short = false) {
  return n === null ? '等待采集' : new Date(n * 1000).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai', hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', ...(short ? {} : { second: '2-digit' }),
  })
}
function groupLabel(value: string) { return groupBy.value === 'route' ? routeNames[value] ?? value : value }
function gapAt(at: number) {
  if (!report.value) return false
  return report.value.series.find(point => point.at === at)?.incomplete ?? false
}
async function load() {
  const current = ++serial
  loading.value = true
  error.value = ''
  try {
    let from: number, until: number
    if (quick.value !== 'custom') {
      until = Date.now() / 1000
      from = until - ({ '1h': 3600, '24h': 86400, '7d': 604800 }[quick.value] ?? 86400)
      start.value = localInput(from * 1000); end.value = localInput(until * 1000)
    } else { from = new Date(`${start.value}+08:00`).getTime() / 1000; until = new Date(`${end.value}+08:00`).getTime() / 1000 }
    if (!Number.isFinite(from) || !Number.isFinite(until) || from >= until || until - from > 31 * 86400) throw new Error('请选择有效的时间范围，单次最多查询 31 天')
    const params = new URLSearchParams({ start: String(from), end: String(until), group_by: groupBy.value, search: search.value, route: route.value, page: String(page.value), group_page: String(groupPage.value) })
    if (groupValue.value !== null) params.set('group_value', groupValue.value)
    const next = await props.request(`/history?${params}`)
    if (current !== serial) return
    report.value = next
    if (page.value > recordPages.value || groupPage.value > groupPages.value) {
      page.value = Math.min(page.value, recordPages.value); groupPage.value = Math.min(groupPage.value, groupPages.value)
      await load()
    }
  } catch (e) { if (current === serial) error.value = e instanceof Error ? e.message : '无法读取历史记录' }
  finally { if (current === serial) loading.value = false }
}
function query() { page.value = 1; groupPage.value = 1; void load() }
function preset(value: string) { quick.value = value; query() }
function classify() { groupValue.value = null; query() }
function drill(value: string | null) { groupValue.value = value; query() }
function move(which: 'records' | 'groups', delta: number) {
  if (which === 'records') page.value += delta; else groupPage.value += delta
  void load()
}
onMounted(() => { void load(); timer = setInterval(() => { if (!document.hidden && !loading.value) void load() }, 10000) })
onUnmounted(() => { serial++; clearInterval(timer) })
defineExpose({ refresh: load })
</script>

<template>
  <div class="history-page" :aria-busy="loading">
    <form class="panel history-filter" @submit.prevent="query">
      <div class="history-presets"><span><Clock3 :size="15" /> 查询时间段</span><button v-for="item in [{ id: '1h', label: '最近 1 小时' }, { id: '24h', label: '最近 24 小时' }, { id: '7d', label: '最近 7 天' }]" :key="item.id" type="button" :class="{ selected: quick === item.id }" @click="preset(item.id)">{{ item.label }}</button><span class="history-timezone">北京时间</span></div>
      <div class="history-fields"><label>开始时间<input v-model="start" type="datetime-local" aria-label="历史开始时间" required @input="quick = 'custom'" /></label><label>结束时间<input v-model="end" type="datetime-local" aria-label="历史结束时间" required @input="quick = 'custom'" /></label><label>分类方式<select v-model="groupBy" aria-label="历史分类方式" @change="classify"><option v-for="(name, key) in groupNames" :key="key" :value="key">{{ name }}</option></select></label><label>出网方式<select v-model="route" aria-label="历史出网方式" @change="query"><option value="all">全部方式</option><option v-for="(name, key) in routeNames" :key="key" :value="key">{{ name }}</option></select></label><button class="button primary" :disabled="loading"><LoaderCircle v-if="loading" :size="15" class="spin" /><Search v-else :size="15" />查询记录</button></div>
      <div class="history-search-row"><div class="search-input"><Search :size="16" /><input v-model="search" aria-label="搜索历史记录" placeholder="搜索域名、来源 IP、节点或进程…" /><button v-if="search" type="button" aria-label="清除历史搜索" @click="search = ''; query()"><X :size="14" /></button></div><button v-if="groupValue !== null" type="button" class="history-chip" @click="drill(null)">{{ groupNames[groupBy] }}：{{ groupLabel(groupValue) }} <X :size="13" /></button><span v-if="report" :class="['badge', report.collector.healthy ? 'green' : 'amber']"><span class="status-dot" :class="{ offline: !report.collector.healthy }" />{{ report.collector.healthy ? '后台持续记录中' : '采集暂停或数据过期' }}</span></div>
    </form>

    <div v-if="error" class="notice error-notice" role="alert"><CircleHelp :size="18" /><div><strong>{{ error }}</strong><span v-if="report">下方保留上次查询结果，请重试。</span></div><button @click="load">重试 <ArrowRight :size="14" /></button></div>
    <div v-if="!report && loading" class="empty"><LoaderCircle :size="26" class="spin" /><strong>正在查询历史记录</strong></div>
    <template v-if="report">
      <div class="history-coverage"><span>开始记录：{{ date(report.collector.started) }}</span><span>最后采集：{{ date(report.collector.last_success) }}</span><span>每 {{ report.collector.interval_seconds }} 秒采样 · 保留 {{ report.collector.retention_days }} 天</span></div>
      <div class="history-explanation"><CircleHelp :size="16" /><p>流量按所选时间段内观测到的增量统计；开始采集前已有的累计流量不计入。短连接可能漏采，关闭时间与最终字节数可能不完整。用途按目标域名归类；来源 IP 共用时无法可靠区分调用服务。</p></div>
      <section class="stat-grid history-stats"><article class="stat-card"><div class="stat-label">时间段总流量 <Activity :size="17" /></div><div class="stat-value rate-value">{{ bytes(total) }}</div><div class="stat-foot">上传与下载的采样合计</div></article><article class="stat-card"><div class="stat-label">时间段下载 <ArrowDownLeft :size="17" /></div><div class="stat-value rate-value">{{ bytes(report.totals.download) }}</div><div class="stat-foot">所选范围内新增下载</div></article><article class="stat-card"><div class="stat-label">时间段上传 <ArrowUpRight :size="17" /></div><div class="stat-value rate-value">{{ bytes(report.totals.upload) }}</div><div class="stat-foot">所选范围内新增上传</div></article><article class="stat-card"><div class="stat-label">观测连接 <History :size="17" /></div><div class="stat-value">{{ report.totals.connections }}<span>条</span></div><div class="stat-foot">含仍被记录及未再观测的连接</div></article></section>

      <section class="panel history-chart-panel"><div class="panel-title"><h2><Activity :size="17" /> 时间段流量</h2><span class="panel-meta">每格 {{ Math.round(report.bucket_seconds / 60) }} 分钟 · 采样估算</span></div><div class="chart-legend"><span><i class="legend-dot download"></i>下载</span><span><i class="legend-dot upload"></i>上传</span><span>斜纹：未完整采集</span></div><div class="history-bars" role="img" aria-label="所选时间段的上传下载流量分布"><div v-for="point in report.series" :key="point.at" :class="['history-bar-slot', { unobserved: gapAt(point.at) }]" :title="`${date(point.at)}，下载 ${bytes(point.download)}，上传 ${bytes(point.upload)}${gapAt(point.at) ? '（该时段采集不完整）' : ''}`"><i class="history-bar upload" :style="{ height: `${point.upload / chartMax * 100}%` }"></i><i class="history-bar download" :style="{ height: `${point.download / chartMax * 100}%` }"></i></div></div><div class="chart-caption"><span>{{ date(report.range.start, true) }}</span><span>{{ date(report.range.end, true) }}</span></div></section>
      <details v-if="report.gap_count || report.range.start < report.collector.retained_from" class="history-gaps"><summary>所选范围存在未采集时段{{ report.gap_count ? `，含 ${report.gap_count} 段采集缺口` : '' }}；没有记录不代表没有流量。</summary><p v-if="report.range.start < report.collector.retained_from">{{ date(report.collector.retained_from) }} 之前没有保留的流量记录。</p><p v-for="(gap, i) in report.gaps" :key="i">{{ date(gap.started) }} — {{ gap.ended === null ? '尚未恢复' : date(gap.ended) }} · {{ gapNames[gap.reason] ?? '采集缺口' }}</p><p v-if="report.gap_count > report.gaps.length">仅列出最近 {{ report.gaps.length }} 段缺口。</p></details>

      <section class="section-heading"><div><h2>分类用量 <span>{{ report.groups.total }}</span></h2><p>按{{ groupNames[groupBy] }}汇总，点击分类查看对应连接。</p></div></section>
      <section class="panel history-groups-panel"><p class="history-scroll-hint">左右滑动表格，可查看全部字段和明细入口。</p><div class="table-scroll"><table class="history-groups"><thead><tr><th>{{ groupNames[groupBy] }}</th><th>连接数</th><th>上传</th><th>下载</th><th>总流量 / 占比</th><th class="align-right">明细</th></tr></thead><tbody><tr v-for="group in report.groups.rows" :key="group.label"><td><strong class="history-group-label">{{ groupLabel(group.label) }}</strong></td><td>{{ group.connections }}</td><td>{{ bytes(group.upload) }}</td><td>{{ bytes(group.download) }}</td><td><div class="history-share"><span>{{ bytes(group.upload + group.download) }}</span><small>{{ total ? ((group.upload + group.download) / total * 100).toFixed(1) : '0.0' }}%</small><i :style="{ width: `${total ? (group.upload + group.download) / total * 100 : 0}%` }"></i></div></td><td class="align-right"><button class="text-button" @click="drill(group.label)">查看连接 <ArrowRight :size="14" /></button></td></tr></tbody></table></div><div v-if="!report.groups.rows.length" class="empty"><History :size="24" /><strong>该时间段暂无分类记录</strong><span>记录从采集启动后逐步积累，可调整时间或筛选条件。</span></div><div class="table-footer"><span>共 {{ report.groups.total }} 个分类</span><div class="pagination"><button :disabled="loading || groupPage <= 1" @click="move('groups', -1)" aria-label="分类上一页"><ChevronLeft :size="16" /></button><span>{{ groupPage }} / {{ groupPages }}</span><button :disabled="loading || groupPage >= groupPages" @click="move('groups', 1)" aria-label="分类下一页"><ChevronRight :size="16" /></button></div></div></section>

      <section class="section-heading"><div><h2>连接历史列表 <span>{{ report.records.total }}</span></h2><p>保留连接的开始时间、最后观测时间、分类与时间段用量；状态不表示业务请求成功或失败。</p></div></section>
      <section class="panel history-records-panel"><p class="history-scroll-hint">左右滑动表格，可查看时间、用量和状态。</p><div class="table-scroll"><table class="history-records"><thead><tr><th>目标 / 协议</th><th>来源 / 入口</th><th>节点 / 出网方式</th><th>连接开始 / 最后观测</th><th>时间段上传 / 下载</th><th>观测状态</th></tr></thead><tbody><tr v-for="record in report.records.rows" :key="record.key"><td><div class="source-cell"><strong>{{ record.host }}:{{ record.port }}</strong><small>{{ record.network.toUpperCase() }} · {{ record.category }}</small></div></td><td><div class="source-cell"><span>{{ record.process || record.source }}</span><small>{{ record.inbound }}</small></div></td><td><div class="source-cell"><span>{{ record.node }}</span><small>{{ routeNames[record.route] }}</small></div></td><td><div class="source-cell"><span>{{ date(record.started) }}</span><small>最后观测 {{ date(record.last_seen) }}</small><small v-if="record.preexisting">首次观测时以累计值为基线</small></div></td><td><div class="traffic-cell"><span><ArrowUpRight :size="12" />{{ bytes(record.period_upload) }}</span><span><ArrowDownLeft :size="12" />{{ bytes(record.period_download) }}</span></div></td><td><div class="source-cell"><span :class="['badge', record.state === 'observed' ? 'green' : 'neutral']">{{ stateNames[record.state] }}</span><small v-if="record.state === 'observed'">{{ record.activity === 'recent' ? '最近有流量' : '近期无流量' }}</small></div></td></tr></tbody></table></div><div v-if="!report.records.rows.length" class="empty"><History :size="24" /><strong>没有匹配的历史连接</strong><span>试试其他时间段或清除筛选；已关闭连接的记录会继续保留。</span></div><div class="table-footer"><span>共 {{ report.records.total }} 条 · 每页 {{ report.records.page_size }} 条</span><div class="pagination"><button :disabled="loading || page <= 1" @click="move('records', -1)" aria-label="历史上一页"><ChevronLeft :size="16" /></button><span>{{ page }} / {{ recordPages }}</span><button :disabled="loading || page >= recordPages" @click="move('records', 1)" aria-label="历史下一页"><ChevronRight :size="16" /></button></div></div></section>
    </template>
  </div>
</template>

<style>
.history-scroll-hint{display:none}@media(max-width:720px){.history-scroll-hint{display:block;padding:12px 14px;color:#8b9d90;font-size:10px;line-height:1.8;border-bottom:1px solid #edf1ed}}
.history-filter{padding:20px;margin-bottom:16px}.history-presets{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:18px}.history-presets>span:first-child{display:flex;align-items:center;gap:7px;font-size:12px;margin-right:10px}.history-presets>button{padding:7px 10px;border-radius:6px;font-size:11px;color:#7c8e84;border:1px solid transparent}.history-presets>button.selected{background:#eaf3ef;border-color:#d4e8df;color:#237354}.history-timezone{margin-left:auto;font-size:10px;color:#94a198}.history-fields{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap}.history-fields>label{display:flex;flex-direction:column;gap:7px;font-size:11px;color:#7e8e84;flex:1;min-width:135px}.history-fields input,.history-fields select{width:100%;background:#fff;border:1px solid #e1e8e2;color:#456553;border-radius:6px;font-size:12px;min-height:38px;padding:8px}.history-fields>button{height:38px}.history-search-row{display:flex;align-items:center;gap:10px;margin-top:15px;flex-wrap:wrap}.history-search-row>.search-input{max-width:420px}.history-search-row>.badge{margin-left:auto}.history-chip{display:flex;align-items:center;gap:6px;background:#edf4ef;color:#347657;border-radius:5px;padding:7px 9px;font-size:10px;max-width:100%;overflow-wrap:anywhere}.history-coverage{display:flex;gap:20px;flex-wrap:wrap;font-size:10px;color:#8a998f;line-height:1.8}.history-explanation{display:flex;gap:8px;align-items:flex-start;color:#8a9b8d;margin:12px 0 19px;font-size:11px;line-height:1.9}.history-explanation>svg{flex-shrink:0;margin-top:3px}.history-stats{margin-bottom:22px}.history-chart-panel{padding:21px;margin-bottom:17px}.history-bars{height:142px;display:flex;gap:2px;align-items:stretch;border-bottom:1px solid #e5ede7;margin-top:20px;background:linear-gradient(#e9efeb 1px,transparent 1px);background-size:100% 47px}.history-bar-slot{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:flex-end}.history-bar-slot.unobserved{background:repeating-linear-gradient(135deg,#e4eae780 0px,#e4eae780 2px,transparent 2px,transparent 6px)}.history-bar{display:block;flex-shrink:0}.history-bar.download{background:#56ae90}.history-bar.upload{background:#a4b5aa}.history-gaps{padding:13px 15px;border:1px solid #ede5d6;border-radius:7px;background:#fcfaf5;color:#a38d63;font-size:11px;line-height:1.9;margin-bottom:25px}.history-gaps summary{cursor:pointer}.history-gaps p{padding-top:7px}.history-groups-panel{margin-bottom:27px}.history-group-label{font-weight:500;overflow-wrap:anywhere;color:#47684f}.history-share{display:flex;flex-wrap:wrap;align-items:center;gap:7px;width:150px;font-size:11px}.history-share small{margin-left:auto;color:#9ba995;font-size:10px}.history-share i{display:block;flex-basis:auto;height:3px;background:#88b89e;min-width:0;border-radius:2px}.history-records{min-width:1080px}.history-records .source-cell>strong{font-weight:500;font-size:12px;overflow-wrap:anywhere}.history-records .source-cell>small{white-space:nowrap}.history-records .badge{width:max-content}.history-records-panel{margin-bottom:25px}.history-page .table-footer{gap:10px}.history-page .stat-foot{line-height:1.5}
@media(max-width:720px){.history-filter{padding:14px}.history-presets{gap:4px}.history-presets>span:first-child{width:100%;margin-bottom:5px}.history-presets>button{font-size:10px;padding:6px}.history-timezone{font-size:9px}.history-fields{gap:10px}.history-fields>label{min-width:110px;flex-basis:40%}.history-fields input{font-size:10px;padding:7px 4px;min-width:0}.history-fields>button{width:100%;justify-content:center}.history-search-row>.search-input{flex-basis:100%;max-width:none}.history-search-row>.badge{margin-left:0}.history-coverage{gap:3px;font-size:9px;flex-direction:column}.history-explanation{font-size:10px}.history-chart-panel{padding:15px}.history-chart-panel .panel-title{gap:10px;align-items:flex-start}.history-chart-panel .panel-meta{font-size:9px;text-align:right}.history-chart-panel .chart-legend{gap:10px;flex-wrap:wrap;font-size:9px}.history-gaps{font-size:10px}.history-stats .stat-value.rate-value{font-size:23px}.history-page .section-heading p{line-height:1.8}.history-groups{min-width:680px}.history-bars{gap:1px}}
</style>
