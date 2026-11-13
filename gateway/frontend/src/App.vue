<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Activity, ArrowDownLeft, ArrowDownToLine, ArrowLeftRight, ArrowRight, ArrowUpRight, Check,
  CheckCheck, ChevronLeft, ChevronRight, CircleHelp, Command, Globe2, LayoutDashboard, LoaderCircle,
  LockKeyhole, LogOut, Network, Radio, RefreshCw, Search, Server, ShieldCheck, Sparkles, Waypoints,
  WifiOff, X, History } from '@lucide/vue'
import type { Node, Provider, Snapshot, ProbeStatus } from './types'
import HistoryPanel from './HistoryPanel.vue'
import PlatformsPanel from './PlatformsPanel.vue'

type Tab = 'overview' | 'nodes' | 'connections' | 'history' | 'platforms'
const appBase = import.meta.env.BASE_URL
const initialTab = window.location.hash.slice(1)
const tab = ref<Tab>(['overview', 'nodes', 'connections', 'history', 'platforms'].includes(initialTab) ? initialTab as Tab : 'overview')
const platformsPanel = ref<InstanceType<typeof PlatformsPanel> | null>(null)
const historyPanel = ref<InstanceType<typeof HistoryPanel> | null>(null)
const authenticated = ref(false)
const booting = ref(true)
const password = ref('')
const loginError = ref('')
const loginBusy = ref(false)
const data = ref<Snapshot | null>(null)
const error = ref('')
const loading = ref(false)
const switching = ref(false)
const probe = ref<ProbeStatus | null>(null)
const probing = ref(false)
const probeDisabled = computed(() => probing.value || probe.value?.status === 'running' || (probe.value?.cooldown_seconds ?? 0) > 0)
const toast = ref('')
const toastError = ref(false)
const search = ref('')
const providerFilter = ref('all')
const healthFilter = ref('all')
const page = ref(0)
const pageSize = 12
const connectionSearch = ref('')
const pendingNode = ref<Node | null>(null)
const dialog = ref<HTMLDialogElement | null>(null)
const points = ref<{ up: number; down: number }[]>([])
const upRate = ref(0)
const downRate = ref(0)
let timer: ReturnType<typeof setInterval> | undefined
let toastTimer: ReturnType<typeof setTimeout> | undefined
let previous: Snapshot | null = null

const tabs = [
  { id: 'overview' as const, label: '网关总览', icon: LayoutDashboard },
  { id: 'nodes' as const, label: '订阅与节点', icon: Waypoints },
  { id: 'connections' as const, label: '实时连接', icon: Network },
  { id: 'history' as const, label: '历史流量', icon: History },
  { id: 'platforms' as const, label: '平台健康', icon: ShieldCheck },
]
const title = computed(() => tabs.find(t => t.id === tab.value)?.label)
const providers = computed(() => data.value?.providers ?? [])
const nodes = computed(() => data.value?.nodes ?? [])
const connections = computed(() => data.value?.connections ?? [])
const activeProvider = computed(() => providers.value.find(p => p.id === data.value?.policy.provider))
const activeNode = computed(() => nodes.value.find(n => n.name === data.value?.policy.node))
const policyLabel = computed(() => data.value?.policy.mode === 'manual' ? '手动固定节点' : '自动优选与故障转移')
const availableCount = computed(() => nodes.value.filter(n => n.alive && n.tested).length)
const filteredNodes = computed(() => nodes.value.filter(n =>
  (providerFilter.value === 'all' || n.provider === providerFilter.value) &&
  (healthFilter.value === 'all' || (healthFilter.value === 'alive' ? n.alive && n.tested : !n.alive || !n.tested)) &&
  `${n.name} ${n.type}`.toLowerCase().includes(search.value.toLowerCase()),
).sort((a, b) => Number(b.alive) - Number(a.alive) || (a.delay || 99999) - (b.delay || 99999)))
const pageCount = computed(() => Math.max(1, Math.ceil(filteredNodes.value.length / pageSize)))
const pagedNodes = computed(() => filteredNodes.value.slice(page.value * pageSize, (page.value + 1) * pageSize))
const filteredConnections = computed(() => connections.value.filter(c =>
  `${c.host} ${c.source} ${c.process} ${c.chains.join(' ')}`.toLowerCase().includes(connectionSearch.value.toLowerCase()),
))
const visibleConnections = computed(() => tab.value === 'overview' ? connections.value.slice(0, 5) : filteredConnections.value)
const lastUpdate = computed(() => data.value ? clock(data.value.timestamp * 1000) : '--:--:--')
const chartMax = computed(() => Math.max(1024, ...points.value.flatMap(p => [p.up, p.down])))

function bytes(value: number, rate = false): string {
  if (!Number.isFinite(value) || value < 0) value = 0
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++ }
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}${rate ? '/s' : ''}`
}
function clock(ms: number) { return new Date(ms).toLocaleTimeString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' }) }
function checkedAt(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' }) : '尚未检测' }
function nodeName(name: string) { return name.replace(/^\[[^\]]+\]\s*/, '') }
function providerName(id: string) { return providers.value.find(p => p.id === id)?.label ?? id }
function latencyClass(delay: number) { return delay < 300 ? 'good' : delay < 1000 ? 'moderate' : 'slow' }
function duration(start: string) {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(start).getTime()) / 1000))
  if (!Number.isFinite(seconds)) return '—'
  return seconds < 60 ? `${seconds}s` : seconds < 3600 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${Math.floor(seconds / 3600)}h ${Math.floor(seconds / 60) % 60}m`
}
function chartLine(key: 'up' | 'down') {
  const values = points.value
  if (!values.length) return '0,100 600,100'
  return values.map((v, i) => `${values.length === 1 ? 0 : i / (values.length - 1) * 600},${100 - v[key] / chartMax.value * 88}`).join(' ')
}
function notify(message: string, isError = false) {
  toast.value = message
  toastError.value = isError
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 4500)
}
async function api(path: string, options: RequestInit = {}) {
  const response = await fetch(`${appBase}api${path}`, {
    ...options, credentials: 'same-origin', signal: AbortSignal.timeout(12000),
    headers: { 'Content-Type': 'application/json', 'X-Gateway-Request': '1', ...options.headers },
  })
  const result = await response.json()
  if (!response.ok) {
    if (response.status === 401 && path !== '/login') authenticated.value = false
    throw new Error(typeof result.detail === 'string' ? result.detail : '请求失败，请重试')
  }
  return result
}
async function refresh() {
  if (!authenticated.value || loading.value) return
  loading.value = true
  try {
    const [next, job]: [Snapshot, ProbeStatus] = await Promise.all([api('/snapshot'), api('/healthcheck')])
    probe.value = job
    if (previous && next.timestamp > previous.timestamp) {
      const interval = next.timestamp - previous.timestamp
      upRate.value = Math.max(0, next.totals.upload - previous.totals.upload) / interval
      downRate.value = Math.max(0, next.totals.download - previous.totals.download) / interval
      points.value = [...points.value, { up: upRate.value, down: downRate.value }].slice(-60)
    }
    previous = next
    data.value = next
    error.value = ''
  } catch (e) { error.value = e instanceof Error ? e.message : '无法获取连接状态' }
  finally { loading.value = false }
}
async function login() {
  loginBusy.value = true
  loginError.value = ''
  try {
    await api('/login', { method: 'POST', body: JSON.stringify({ password: password.value }) })
    password.value = ''
    authenticated.value = true
    await refresh()
  } catch (e) { loginError.value = e instanceof Error ? e.message : '登录失败' }
  finally { loginBusy.value = false }
}
async function logout() {
  try { await api('/logout', { method: 'POST' }); authenticated.value = false; data.value = null; previous = null; points.value = [] }
  catch (e) { notify(e instanceof Error ? e.message : '退出失败', true) }
}
async function setPolicy(mode: 'auto' | 'manual', node?: Node) {
  switching.value = true
  try {
    await api('/policy', { method: 'POST', body: JSON.stringify({ mode, node: node?.name }) })
    dialog.value?.close()
    await refresh()
    notify(mode === 'auto' ? '已启用自动模式：订阅内优选低延迟，主备故障转移' : `已固定出口：${nodeName(node!.name)}`)
  } catch (e) { notify(e instanceof Error ? e.message : '切换未成功', true); await refresh() }
  finally { switching.value = false }
}
async function choose(node: Node) {
  pendingNode.value = node
  await nextTick()
  dialog.value?.showModal()
}
function browseProvider(provider: Provider) {
  providerFilter.value = provider.id
  tab.value = 'nodes'
}
function visibilityChanged() { if (!document.hidden) void refresh() }
async function runProbe(scope: 'current' | 'page' | 'provider' | 'all') {
  if (probeDisabled.value) return
  probing.value = true
  try {
    probe.value = await api('/healthcheck', { method: 'POST', body: JSON.stringify({ scope, provider: providerFilter.value, nodes: scope === 'page' ? pagedNodes.value.map(n => n.name) : undefined }) })
    notify(`已开始检测 ${probe.value!.total} 个节点，最多同时检测 4 个`)
  } catch (e) { notify(e instanceof Error ? e.message : '无法开始检测', true) }
  finally { probing.value = false }
}
async function refreshPage() {
  if (tab.value === 'platforms') { void platformsPanel.value?.refresh(true); return }
  if (tab.value === 'history') { void historyPanel.value?.refresh(); return }
  await refresh()
  if (!error.value && data.value && (tab.value === 'overview' || tab.value === 'nodes')) await runProbe(tab.value === 'nodes' ? 'page' : 'current')
}
watch(tab, value => { window.history.replaceState(null, '', `#${value}`) })
watch([search, providerFilter, healthFilter], () => { page.value = 0 })
watch(pageCount, count => { if (page.value >= count) page.value = count - 1 })
onMounted(async () => {
  try { const session = await api('/session'); authenticated.value = session.authenticated; if (!session.configured) loginError.value = '请先配置服务器管理密码'; await refresh() }
  catch { loginError.value = '管理服务暂时无法连接，请刷新重试' }
  finally { booting.value = false }
  timer = setInterval(() => { if (!document.hidden) void refresh() }, 5000)
  document.addEventListener('visibilitychange', visibilityChanged)
})
onUnmounted(() => { clearInterval(timer); clearTimeout(toastTimer); document.removeEventListener('visibilitychange', visibilityChanged) })
</script>

<template>
  <div v-if="booting" class="boot"><LoaderCircle class="spin" :size="28" /><span>正在连接管理台</span></div>

  <main v-else-if="!authenticated" class="login-page">
    <div class="login-visual"><div class="login-grid"></div><div class="brand brand-light"><span class="brand-symbol">M</span><span>mirage<span class="brand-dot">.</span></span></div>
      <div class="login-copy"><span class="eyebrow">YOUR NETWORK, IN VIEW.</span><h1>连接有迹可循，<br />出口由你掌控。</h1><p>一个控制台，了解你的网关、节点与每一条实时连接。</p><div class="login-pills"><span><Radio :size="14" /> 实时连接</span><span><ShieldCheck :size="14" /> 自动故障转移</span><span><ArrowLeftRight :size="14" /> 手动切换</span></div></div>
      <span class="login-footer">MIRAGE NETWORK CONTROL</span>
    </div>
    <section class="login-form-wrap"><form class="login-form" @submit.prevent="login"><div class="login-icon"><LockKeyhole :size="24" /></div><span class="eyebrow">GATEWAY CONSOLE</span><h2>登录网关控制台</h2><p>输入管理密码，查看并管理当前网络。</p><label for="password">管理密码</label><input id="password" v-model="password" type="password" autocomplete="current-password" required placeholder="请输入管理密码" :disabled="loginBusy" autofocus /><div v-if="loginError" role="alert" class="form-error">{{ loginError }}</div><button class="button primary login-submit" :disabled="loginBusy || !password"><LoaderCircle v-if="loginBusy" :size="17" class="spin" /><span>{{ loginBusy ? '正在登录' : '进入控制台' }}</span><ArrowRight v-if="!loginBusy" :size="17" /></button><div class="login-note"><ShieldCheck :size="15" /> 控制器凭证仅保存在服务器端</div></form></section>
  </main>

  <div v-else class="app-shell">
    <aside class="sidebar">
      <a class="brand" :href="appBase" aria-label="Mirage 首页"><span class="brand-symbol">M</span><span>mirage<span class="brand-dot">.</span></span></a>
      <div class="workspace"><span class="workspace-icon"><Server :size="17" /></span><div><strong>本机网关</strong><span>Production gateway</span></div><span :class="['status-dot', { offline: error }]" /></div>
      <span class="nav-label">工作空间</span>
      <nav aria-label="主导航"><button v-for="item in tabs" :key="item.id" :aria-label="item.label" :title="item.label" :class="['nav-item', { selected: tab === item.id }]" @click="tab = item.id"><component :is="item.icon" :size="18" /><span>{{ item.label }}</span><span v-if="item.id === 'connections' && data" class="nav-count">{{ connections.length }}</span></button></nav>
      <div class="sidebar-bottom"><div class="engine-card"><div><span class="status-dot" :class="{ offline: error }" /><strong>Mihomo 内核</strong></div><p>{{ data?.version ?? '等待连接' }} <span>{{ error ? '连接异常' : '运行中' }}</span></p></div><button class="logout" @click="logout" aria-label="退出登录"><span class="avatar">A</span><span>管理员<small>本地工作空间</small></span><LogOut :size="16" /></button></div>
    </aside>

    <div class="main-shell">
      <header class="topbar"><div class="breadcrumb"><a :href="appBase" title="WebMirage 管理首页">WebMirage</a><ChevronRight :size="13" /><span>网络管理</span><ChevronRight :size="13" /><strong>{{ title }}</strong></div><div class="topbar-right"><span :class="['connection-status', { interrupted: error }]"><span class="status-dot" :class="{ offline: error }" />{{ tab === 'platforms' ? '平台管理' : error ? '数据连接中断' : data ? '实时连接中' : '连接中' }}</span><span class="topbar-divider"></span><span class="top-avatar">A</span></div></header>
      <main class="content">
        <section class="page-heading"><div><div class="eyebrow">NETWORK / {{ tab.toUpperCase() }}</div><h1>{{ title }}<span class="heading-dot">.</span></h1><p>{{ tab === 'overview' ? '看清每一条连接，让网络始终保持畅通。' : tab === 'nodes' ? '独立管理每个订阅，选择最适合当前任务的出口。' : tab === 'platforms' ? '查看接入平台与只读接口的状态，识别需要处理的异常。' : tab === 'history' ? '按时间段查看连接历史，了解流量用在了哪里。' : '查看当前内核记录的连接，以及它们实际使用的转发路径。' }}</p></div><button class="button secondary" :disabled="tab !== 'history' && tab !== 'platforms' && (loading || ((tab === 'overview' || tab === 'nodes') && probeDisabled))" :title="tab === 'nodes' ? '重新检测当前页节点并刷新状态' : tab === 'overview' ? '重新检测当前出口并刷新状态' : '读取最新状态'" @click="refreshPage"><RefreshCw :size="15" :class="{ spin: loading && tab !== 'platforms' }" />刷新状态</button></section>

        <div v-if="error && tab !== 'history' && tab !== 'platforms'" class="notice error-notice" role="alert"><WifiOff :size="18" /><div><strong>{{ error }}</strong><span v-if="data">正在展示 {{ lastUpdate }} 的最后一次数据，恢复连接后会自动刷新。</span></div><button @click="refresh">重试 <ArrowRight :size="14" /></button></div>
        <div v-if="data?.policy.mode === 'manual'" class="notice manual-notice"><CircleHelp :size="18" /><div><strong>当前处于手动模式</strong><span>出口已固定，节点异常时不会自动换线。恢复自动后，将在订阅内优选低延迟节点，并在订阅故障时切换备用。</span></div><button :disabled="switching || !data.policy.ready" @click="setPolicy('auto')">恢复自动 <ArrowRight :size="14" /></button></div>
        <div v-if="!data && !error && tab !== 'history' && tab !== 'platforms'" class="empty loading-empty"><LoaderCircle class="spin" :size="26" /><strong>正在读取网关状态</strong></div>

        <HistoryPanel v-if="tab === 'history'" ref="historyPanel" :request="api" />
        <PlatformsPanel v-if="tab === 'platforms'" ref="platformsPanel" :request="api" />

        <template v-if="data && tab !== 'history'">
          <section v-if="tab === 'overview' || tab === 'nodes'" class="probe-summary">
            <div><strong>HTTPS 探测 · 最近一次结果</strong><p>全量每 {{ data.health_check.full_interval / 60 }} 分钟 · 各来源优选出口每 {{ data.health_check.exit_interval / 60 }} 分钟 · 页面自动刷新只读取状态</p><p>点击刷新状态：{{ tab === 'nodes' ? '检测当前页节点' : '检测当前出口' }}。成功率与波动基于最近最多 10 次样本，不代表带宽或业务可用性。</p></div>
            <div v-if="tab === 'nodes'" class="probe-actions"><button class="button secondary" :disabled="probeDisabled || providerFilter === 'all'" @click="runProbe('provider')">检测此订阅</button><button class="button secondary" :disabled="probeDisabled" @click="runProbe('all')">检测全部 {{ nodes.length }} 个</button></div>
          </section>
          <div v-if="probe && probe.status !== 'idle' && (tab === 'overview' || tab === 'nodes')" class="notice probe-notice" role="status"><LoaderCircle v-if="probe.status === 'running'" :size="17" class="spin" /><CheckCheck v-else :size="17" /><div><strong>{{ probe.status === 'running' ? '正在检测' : probe.status === 'error' ? '检测未完整完成' : '检测完成' }} {{ probe.completed }} / {{ probe.total }} · 通过 {{ probe.passed }} · 未通过 {{ probe.failed }}</strong><span>{{ probe.error || (probe.status === 'running' ? '后台限流检测中，可以继续查看连接；重复点击不会新建任务。' : probe.cooldown_seconds ? `冷却剩余 ${probe.cooldown_seconds} 秒，避免重复探测。` : '可再次手动检测。') }}</span></div></div>
          <template v-if="tab === 'overview'">
            <section class="stat-grid">
              <article class="stat-card"><div class="stat-label">活跃连接 <Network :size="17" /></div><div class="stat-value">{{ connections.length }}<span>条</span></div><div class="stat-foot"><span class="tiny-live"></span> 当前内核记录的连接，含空闲连接</div></article>
              <article class="stat-card"><div class="stat-label">最近探测通过 <Globe2 :size="17" /></div><div class="stat-value">{{ availableCount }}<span>/ {{ nodes.length }}</span></div><div class="stat-foot">来自 {{ providers.filter(p => !p.local).length }} 个订阅与本地救援源</div></article>
              <article class="stat-card"><div class="stat-label">实时下载 <ArrowDownLeft :size="18" /></div><div class="stat-value rate-value">{{ bytes(downRate, true) }}</div><div class="stat-foot">内核累计 {{ bytes(data.totals.download) }}</div></article>
              <article class="stat-card"><div class="stat-label">实时上传 <ArrowUpRight :size="18" /></div><div class="stat-value rate-value">{{ bytes(upRate, true) }}</div><div class="stat-foot">内核累计 {{ bytes(data.totals.upload) }}</div></article>
            </section>

            <section class="overview-grid">
              <article class="panel exit-panel"><div class="panel-title"><h2><Waypoints :size="17" /> 当前出口</h2><span :class="['badge', data.policy.mode !== 'manual' ? 'green' : 'amber']"><span class="status-dot" />{{ policyLabel }}</span></div><div class="active-node"><div class="node-globe"><Globe2 :size="29" /></div><div><span class="muted-label">正在使用的节点</span><h3>{{ nodeName(data.policy.node) }}</h3><p>{{ activeProvider?.label ?? '网关出口' }}<span>·</span>{{ activeProvider?.host ?? '—' }}</p></div><div class="active-delay" :title="`HTTPS 最近探测：${checkedAt(activeNode?.checked_at ?? null)}，不包含完整首次建连耗时`"><strong>{{ data.policy.delay || '—' }}</strong><span>ms</span></div></div><p class="exit-checked">最近节点探测：{{ checkedAt(activeNode?.checked_at ?? null) }}<span v-if="activeNode?.stale"> · 结果较旧</span><span v-if="activeNode?.samples"> · 最近 {{ activeNode.samples }} 次通过 {{ activeNode.success_rate }}%</span></p><div class="mode-control"><button :class="{ active: data.policy.mode === 'auto' }" :disabled="switching || !data.policy.ready" @click="data.policy.mode !== 'auto' && setPolicy('auto')"><ShieldCheck :size="16" />自动优选与故障转移<Check v-if="data.policy.mode === 'auto'" :size="15" /></button><button :class="{ active: data.policy.mode === 'manual' }" :disabled="switching || !data.policy.ready" @click="tab = 'nodes'"><Command :size="16" />手动选择节点<Check v-if="data.policy.mode === 'manual'" :size="15" /></button></div><div class="exit-description"><span class="small-shield"><ShieldCheck :size="14" /></span><p>{{ data.policy.mode === 'auto' ? (data.policy.optimized ? `主订阅内优选低延迟，无可用节点时依次切换备用。全量每 ${data.health_check.full_interval / 60} 分钟检测，快 ${data.policy.latency_tolerance_ms}ms 以上才换线。` : '按主备顺序自动换线，等待订阅内优选配置生效。') : '手动固定节点，异常时不会自动换线。' }}</p><button @click="tab = 'nodes'" aria-label="查看所有节点"><ArrowRight :size="16" /></button></div></article>

              <article class="panel chart-panel"><div class="panel-title"><h2><Activity :size="17" /> 流量概览</h2><span class="panel-meta">本次会话采样</span></div><div class="chart-legend"><span><i class="legend-dot download"></i>下载 <strong>{{ bytes(downRate, true) }}</strong></span><span><i class="legend-dot upload"></i>上传 <strong>{{ bytes(upRate, true) }}</strong></span></div><div class="chart"><span class="chart-ceiling">{{ bytes(chartMax, true) }}</span><div class="chart-lines"></div><svg viewBox="0 0 600 110" preserveAspectRatio="none" role="img" aria-label="本次会话上传与下载速率曲线"><defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#35a281" stop-opacity=".2" /><stop offset="100%" stop-color="#35a281" stop-opacity="0" /></linearGradient></defs><polygon :points="`0,110 ${chartLine('down')} 600,110`" fill="url(#fill)" /><polyline :points="chartLine('down')" stroke="#299a78" stroke-width="2.5" fill="none" vector-effect="non-scaling-stroke" /><polyline :points="chartLine('up')" stroke="#9caeae" stroke-width="1.8" stroke-dasharray="4 4" fill="none" vector-effect="non-scaling-stroke" /></svg></div><div class="chart-caption"><span>{{ points.length ? `${points.length} 个采样点` : '正在积累采样数据' }}</span><span>现在</span></div></article>
            </section>

            <section class="section-heading"><div><h2>订阅来源 <span>{{ providers.length }}</span></h2><p>各来源独立维护，按配置优先级自动回退。</p></div><button class="text-button" @click="tab = 'nodes'">管理节点 <ArrowRight :size="15" /></button></section>
            <section class="provider-grid"><button v-for="(provider, i) in providers" :key="provider.id" class="provider-card" @click="browseProvider(provider)"><div class="provider-top"><span :class="['provider-icon', { local: provider.local }]"><Server v-if="provider.local" :size="19" /><Globe2 v-else :size="19" /></span><span class="provider-priority">{{ provider.local ? '本地缓存' : `优先级 ${i + 1}` }}</span></div><h3>{{ provider.label }}<span v-if="provider.id === data.policy.provider" class="provider-active">使用中</span></h3><p>{{ provider.host }}</p><div class="provider-bottom"><span><i :class="['status-dot', { offline: !provider.alive }]" />{{ provider.alive }} <small>/ {{ provider.count }} 可用</small></span><ArrowUpRight :size="16" /></div></button></section>
          </template>

          <template v-if="tab === 'nodes'">
            <section class="nodes-summary"><div><span class="summary-icon"><Waypoints :size="22" /></span><div><strong>{{ availableCount }}<small> 个节点最近探测通过</small></strong><p>{{ providers.filter(p => !p.local).length }} 个订阅独立维护，原有节点保留为本地救援。</p></div></div><span :class="['badge', data.policy.mode !== 'manual' ? 'green' : 'amber']">当前：{{ policyLabel }}</span></section>
            <div class="node-toolbar"><div class="search-input"><Search :size="17" /><input v-model="search" aria-label="搜索节点" placeholder="搜索节点名称或协议…" /><button v-if="search" @click="search = ''" aria-label="清除搜索"><X :size="14" /></button></div><select v-model="providerFilter" aria-label="筛选订阅"><option value="all">所有来源</option><option v-for="provider in providers" :key="provider.id" :value="provider.id">{{ provider.label }} · {{ provider.host }}</option></select><select v-model="healthFilter" aria-label="筛选状态"><option value="all">所有状态</option><option value="alive">检测可用</option><option value="failed">异常或未检测</option></select><button v-if="data.policy.mode === 'manual'" class="button secondary auto-button" :disabled="switching || !data.policy.ready" @click="setPolicy('auto')"><ShieldCheck :size="15" />恢复自动</button></div>
            <section class="panel nodes-table-panel"><div class="table-scroll"><table class="nodes-table"><thead><tr><th>节点名称</th><th>来源</th><th>协议</th><th>检测状态</th><th>HTTPS 探测</th><th>近期成功率</th><th>中位数 / 波动</th><th>最后检测</th><th class="align-right">出口操作</th></tr></thead><tbody><tr v-for="node in pagedNodes" :key="`${node.provider}:${node.name}`" :class="{ 'current-row': data.policy.node === node.name }"><td><div class="node-title"><span class="table-node-icon"><Globe2 :size="17" /></span><div><strong>{{ nodeName(node.name) }}</strong><span v-if="node.name === data.policy.node" class="current-tag">当前出口</span></div></div></td><td class="secondary-cell">{{ providerName(node.provider) }}</td><td><span class="protocol">{{ node.type }}</span></td><td><span :class="['node-status', { healthy: node.alive && node.tested }]"><i class="status-dot" :class="{ offline: !node.alive || !node.tested }" />{{ !node.tested ? '未检测' : node.stale ? '结果较旧' : node.alive ? '探测通过' : '未通过' }}</span></td><td><span v-if="node.alive && node.delay" :class="['latency', latencyClass(node.delay)]"><i></i><i></i><i></i><b>{{ node.delay }}</b><small>ms</small></span><span v-else class="muted">—</span></td><td><div class="quality-cell"><strong>{{ node.success_rate == null ? '—' : `${node.success_rate}%` }}</strong><small>{{ node.samples }} 次样本</small></div></td><td><div class="quality-cell" title="成功样本的中位延迟 / 最大与最小延迟之差；不足两次成功样本不计算波动"><strong>{{ node.median_delay == null ? '—' : `${node.median_delay} ms` }}</strong><small>波动 {{ node.jitter == null ? '—' : `${node.jitter} ms` }}</small></div></td><td><div class="quality-cell"><strong>{{ checkedAt(node.checked_at) }}</strong><small v-if="node.stale" class="stale-result">结果较旧，请重新检测</small></div></td><td class="align-right"><button v-if="node.name === data.policy.node && data.policy.mode === 'manual'" class="node-action selected-action" disabled><Check :size="13" />已固定</button><button v-else class="node-action" :disabled="!node.alive || !node.tested || switching || !data.policy.ready" @click="choose(node)">{{ node.alive && node.tested ? '使用此节点' : '暂不可用' }}<ArrowRight v-if="node.alive && node.tested" :size="13" /></button></td></tr></tbody></table></div><div v-if="!filteredNodes.length" class="empty"><Search :size="24" /><strong>没有匹配的节点</strong><span>试试其他关键词或取消筛选。</span></div><div class="table-footer"><span>共 {{ filteredNodes.length }} 个节点 · 每页 {{ pageSize }} 个</span><div class="pagination"><button :disabled="page === 0" @click="page--" aria-label="上一页"><ChevronLeft :size="16" /></button><span>{{ page + 1 }} / {{ pageCount }}</span><button :disabled="page + 1 >= pageCount" @click="page++" aria-label="下一页"><ChevronRight :size="16" /></button></div></div></section>
          </template>

          <section v-if="tab === 'overview' || tab === 'connections'" class="connections-section"><div class="section-heading"><div><h2>实时连接 <span>{{ connections.length }}</span></h2><p>含空闲或待释放连接；连接保留时长不等于持续传输时间。</p></div><button v-if="tab === 'overview'" class="text-button" @click="tab = 'connections'">查看全部 <ArrowRight :size="15" /></button><span v-else class="badge neutral"><Radio :size="12" /> 每 5 秒刷新</span></div><div v-if="tab === 'connections'" class="search-input connection-search"><Search :size="17" /><input v-model="connectionSearch" placeholder="搜索域名、来源 IP、进程或节点…" aria-label="搜索连接" /></div><div class="panel connections-panel"><div class="table-scroll"><table><thead><tr><th>目标地址</th><th>转发路径</th><th>来源 / 协议</th><th>上传 / 下载</th><th class="align-right">持续时间</th></tr></thead><tbody><tr v-for="connection in visibleConnections" :key="connection.id"><td><div class="host-cell"><span class="host-icon"><Globe2 :size="15" /></span><div><strong>{{ connection.host }}</strong><small>:{{ connection.port }}</small></div></div></td><td><div class="chain-cell"><span>{{ connection.chains[0] ? nodeName(connection.chains[0]) : connection.rule }}</span><small>{{ connection.chains.length > 1 ? connection.chains.slice(1).reverse().join(' → ') : connection.rule }}</small></div></td><td><div class="source-cell"><span>{{ connection.process || connection.source || '未知来源' }}</span><small>{{ connection.network.toUpperCase() }}{{ connection.inbound ? ` · ${connection.inbound}` : '' }}</small></div></td><td><div class="traffic-cell"><span><ArrowUpRight :size="12" />{{ bytes(connection.upload) }}</span><span><ArrowDownLeft :size="12" />{{ bytes(connection.download) }}</span></div></td><td class="align-right duration-cell">{{ duration(connection.start) }}</td></tr></tbody></table></div><div v-if="!visibleConnections.length" class="empty"><Network :size="25" /><strong>{{ connectionSearch ? '没有匹配的连接' : '当前没有活跃连接' }}</strong><span>{{ connectionSearch ? '试试其他域名或节点名称。' : '服务发起代理请求后，连接将在这里出现。' }}</span></div></div></section>

          <footer class="page-footer"><span><span :class="['status-dot', { offline: error }]" />{{ error ? '连接中断 · ' : '已同步 · ' }}{{ lastUpdate }}<span class="footer-separator">/</span>北京时间</span><span>流量为实时采样估算 <span class="footer-separator">·</span> MIRAGE GATEWAY</span></footer>
        </template>
      </main>
    </div>
    <Transition name="toast"><div v-if="toast" :class="['toast-message', { 'toast-error': toastError }]" role="status"><CircleHelp v-if="toastError" :size="18" /><CheckCheck v-else :size="18" />{{ toast }}</div></Transition>
    <dialog ref="dialog" class="switch-dialog" aria-labelledby="switch-title" @close="pendingNode = null" @cancel="switching && $event.preventDefault()"><div v-if="pendingNode"><div class="dialog-heading"><span class="dialog-icon"><ArrowLeftRight :size="24" /></span><button class="icon-button" :disabled="switching" @click="dialog?.close()" aria-label="关闭"><X :size="19" /></button></div><span class="eyebrow">SWITCH OUTBOUND</span><h2 id="switch-title">固定到这个节点？</h2><p>切换后将进入手动模式，暂停自动优选与故障转移。节点异常时需要手动换线，也可以恢复自动。</p><div class="dialog-node"><Globe2 :size="23" /><div><strong>{{ nodeName(pendingNode.name) }}</strong><span>{{ providerName(pendingNode.provider) }}</span></div><span class="badge green">{{ pendingNode.delay }} ms</span></div><p class="dialog-note">新连接使用新出口，已有连接可能继续使用原节点。</p><div class="dialog-actions"><button class="button secondary" :disabled="switching" @click="dialog?.close()">取消</button><button class="button primary" :disabled="switching" @click="setPolicy('manual', pendingNode)"><LoaderCircle v-if="switching" :size="16" class="spin" /><ArrowLeftRight v-else :size="16" />{{ switching ? '正在切换' : '确认使用此节点' }}</button></div></div></dialog>
  </div>
</template>
