<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RefreshCw, ShieldCheck, AlertCircle, LoaderCircle, X, ChevronLeft, ChevronRight } from '@lucide/vue'
import { credentialFields, credentialSources, cookieForms } from './credentialGuides'
import { createRedditRuntime, failureText, formatDuration } from './redditRuntime'

const props = defineProps<{ request: (path: string, options?: RequestInit) => Promise<any> }>()
const state = ref<any>(null)
const error = ref('')
const busy = ref(false)
const selected = ref('twitter')
const page = ref(1)
const dialog = ref<HTMLDialogElement | null>(null)
const editing = ref<any>(null)
const values = ref<Record<string, string>>({})
const saving = ref(false)
const credentialMode = ref('values')
const cookieForm = computed(() => cookieForms[editing.value?.id])
const editingFields = computed<string[]>(() => cookieForm.value && credentialMode.value === 'values'
  ? cookieForm.value.primary : editing.value?.fields ?? [])
const fieldGroups = computed(() => [
  { key: 'primary', label: '', fields: editingFields.value },
  ...(cookieForm.value?.optional.length && credentialMode.value === 'values'
    ? [{ key: 'optional', label: editing.value?.id === 'xianyu' ? '其他会话 Cookie / 用户 ID（可选）' : '其他会话 Cookie（可选）', fields: cookieForm.value.optional }] : []),
])
const saveError = ref('')
const notice = ref('')
const monitoringEnabled = ref(true)
const monitoringInterval = ref(30)
const monitoringDirty = ref(false)
const monitoringBusy = ref(false)
const monitoringError = ref('')
const monitoringNotice = ref('')
const redditBusy = ref(false)
const redditError = ref('')
const redditNotice = ref('')
const redditBackendChoice = ref('http')
const nowTs = ref(Date.now() / 1000)
let clockTimer: ReturnType<typeof setInterval> | undefined
const redditModel = createRedditRuntime(
  () => state.value?.reddit_runtime,
  () => nowTs.value,
  { redditBusy: () => redditBusy.value, checking: () => checking.value },
)
const redditRuntime = computed(redditModel.runtime)
const cooldownRemaining = computed(redditModel.cooldownRemaining)
const inCooldown = computed(redditModel.inCooldown)
const sessionMismatch = computed(redditModel.sessionMismatch)
const startBlockedReason = computed(redditModel.startBlockedReason)
const startDisabled = computed(redditModel.startDisabled)
let timer: ReturnType<typeof setInterval>
const platforms = computed<any[]>(() => state.value?.platforms ?? [])
const current = computed(() => platforms.value.find(p => p.id === selected.value))
const attention = computed(() => platforms.value.filter(p => !['ok', 'unknown'].includes(p.category)))
const registered = computed(() => platforms.value.reduce((sum, p) => sum + p.registered_count, 0))
const checking = computed(() => state.value?.job.status === 'running')
const blocked = computed(() => busy.value || checking.value || saving.value || !state.value?.mcp_connected || state.value?.job.cooldown_seconds > 0)
const fieldLabels: Record<string, string> = { twitter_auth_token: 'Twitter auth_token', twitter_ct0: 'Twitter ct0', xueqiu_cookie: '雪球 Cookie（含 xq_a_token）', xianyu_cookie: '闲鱼 Cookie（含 _m_h5_tk、_m_h5_tk_enc、cookie2、unb）', xianyu_user_id: '闲鱼用户 ID（可选）', reddit_cookie: 'Reddit Cookie（含 reddit_session）', github_tokens: 'GitHub Token（替换文件中的 Token 列表）' }
function date(value: number | null) { return value ? new Date(value * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—' }
function passiveDate(p: any) { return date(Math.max(p.passive?.last_success_at ?? 0, p.passive?.last_error_at ?? 0)) }
function tone(category: string) { return category === 'ok' ? 'green' : category === 'unknown' ? 'neutral' : 'amber' }
async function refresh(force = false) {
  try {
    if (force) await props.request('/platforms/refresh', { method: 'POST' })
    const result = await props.request(`/platforms?platform=${selected.value}&page=${page.value}`)
    state.value = result
    if (!redditBusy.value) redditBackendChoice.value = result.reddit_runtime?.backend ?? 'http'
    if (result.monitoring && !monitoringDirty.value && !monitoringBusy.value) {
      monitoringEnabled.value = result.monitoring.enabled
      monitoringInterval.value = result.monitoring.interval_minutes
    }
    error.value = ''
  } catch (e) { error.value = e instanceof Error ? e.message : '平台状态读取失败' }
}
async function saveMonitoring() {
  monitoringBusy.value = true
  monitoringError.value = ''
  try {
    await props.request('/platforms/monitoring', { method: 'POST', body: JSON.stringify({ enabled: monitoringEnabled.value, interval_minutes: monitoringInterval.value }) })
    monitoringDirty.value = false
    monitoringNotice.value = monitoringEnabled.value ? '自动检测设置已保存。' : '已暂停自动检测，已发出的请求结束后不再检测后续接口。'
  } catch (e) { monitoringError.value = e instanceof Error ? e.message : '无法保存自动检测设置' }
  finally { monitoringBusy.value = false }
  await refresh()
}
async function select(id: string) { selected.value = id; page.value = 1; await refresh() }
async function redditAction(action: 'http' | 'opencli' | 'start' | 'stop') {
  redditBusy.value = true; redditError.value = ''; redditNotice.value = ''
  try {
    const backend = action === 'http' || action === 'opencli'
    const result = await props.request(`/platforms/reddit/${backend ? 'backend' : 'browser'}`, {
      method: 'POST', body: JSON.stringify(backend ? { backend: action } : { operation: action }),
    })
    if (result.reddit_runtime) state.value.reddit_runtime = result.reddit_runtime
    redditNotice.value = backend ? '请求方式已保存，旧结果不用于新方式的健康判定，请重新检测。'
      : action === 'start' ? '浏览器已启动并导入当前凭证；登录有效性仍需接口检测确认。' : '浏览器已停止。'
    await refresh()
  } catch (e) { redditError.value = e instanceof Error ? e.message : '操作未确认，请刷新状态后核对' }
  finally { redditBusy.value = false; redditBackendChoice.value = redditRuntime.value.backend }
}
async function check(platform?: string, tool?: string) {
  if (blocked.value) return
  busy.value = true
  notice.value = ''
  try {
    const job = await props.request('/platforms/check', { method: 'POST', body: JSON.stringify({ platform, tool }) })
    state.value.job = job
    notice.value = `已开始检查 ${job.total} 个只读接口；逐个执行，不调用写操作。`
  } catch (e) { error.value = e instanceof Error ? e.message : '无法开始检测' }
  finally { busy.value = false }
}
function edit(platform: any) {
  editing.value = platform
  credentialMode.value = 'values'
  values.value = {}
  saveError.value = ''
  dialog.value?.showModal()
}
function clearForm() { editing.value = null; values.value = {}; saveError.value = '' }
function locked(field: string) { return editing.value?.credentials.locked?.includes(credentialFields[field]?.configField ?? field) }
function changeCredentialMode() { values.value = {}; saveError.value = '' }
function requiredCredential(field: string) {
  if (editing.value?.id === 'reddit') return field === (credentialMode.value === 'full' ? 'reddit_cookie' : 'reddit_session')
  return editing.value?.id === 'xianyu' && (credentialMode.value === 'full' ? field === 'xianyu_cookie' : cookieForms.xianyu.primary.includes(field))
}
async function save() {
  const updates = Object.fromEntries(Object.entries(values.value).filter(([, value]) => value.trim()))
  if (!Object.keys(updates).length) { saveError.value = '请至少填入一个需要更新的字段。'; return }
  if (editing.value?.id === 'xianyu') {
    const present = credentialMode.value === 'full'
      ? Object.fromEntries((updates.xianyu_cookie ?? '').split(';').filter(p => p.includes('=')).map(p => {
        const index = p.indexOf('='); return [p.slice(0, index).trim(), p.slice(index + 1).trim()]
      })) : updates
    const missing = cookieForms.xianyu.primary.filter(key => !present[key]?.trim())
    if (missing.length) { saveError.value = `闲鱼必填 Cookie 缺少：${missing.join('、')}；请填写同一次登录的完整必填项。`; return }
  }
  for (const [field, value] of Object.entries(updates)) {
    const guide = credentialFields[field]
    if (guide?.valueOnly && (value.includes(';') || (guide.valueName && value.trim().startsWith(`${guide.valueName}=`))
      || (field === 'github_tokens' && /^bearer /i.test(value.trim())))) {
      saveError.value = `${guide.name} 这里只填写 Value（值）。${cookieForm.value ? '整段 Cookie 请切换到“导入完整 Cookie”。' : field === 'github_tokens' ? '请直接粘贴 Token 本身。' : '请将各 Cookie 的值分别填入对应字段。'}`
      return
    }
  }
  saving.value = true
  saveError.value = ''
  try {
    await props.request('/platforms/credentials', { method: 'POST', body: JSON.stringify({ platform: editing.value.id, updates }) })
    values.value = {}
    dialog.value?.close()
    notice.value = '凭证已保存并热加载；旧检测结果不会作为新凭证的验证，请重新检查平台。'
    await refresh()
  } catch (e) { saveError.value = e instanceof Error ? e.message : '更新未确认，请刷新状态后核对' }
  finally { saving.value = false }
}
onMounted(async () => { await refresh(); timer = setInterval(() => { if (!document.hidden) void refresh() }, 5000); clockTimer = setInterval(() => { nowTs.value = Date.now() / 1000 }, 1000) })
onUnmounted(() => { clearInterval(timer); clearInterval(clockTimer); values.value = {} })
defineExpose({ refresh })
</script>

<template>
  <div class="platform-page" :aria-busy="busy">
    <div v-if="error" class="notice error-notice" role="alert">
      <AlertCircle :size="18" aria-hidden="true" />
      <div><strong>{{ error }}</strong><span v-if="state">保留最后一次记录，请重试。</span></div>
      <button @click="refresh(true)">重试 <ChevronRight :size="14" /></button>
    </div>
    <div v-if="!state" class="empty"><LoaderCircle class="spin" :size="26" aria-hidden="true" /><strong>正在读取平台状态</strong></div>
    <template v-else>
      <section class="probe-summary platform-overview" aria-label="WebMirage 接入概况">
        <div>
          <strong>WebMirage 平台接入 · {{ platforms.length }} 个平台 · {{ registered }} 个已注册工具</strong>
          <p>本地状态每 2 分钟同步 · 页面刷新只读记录 · 自动检测{{ state.monitoring?.enabled ? `每 ${state.monitoring.interval_minutes} 分钟运行` : '已暂停' }}</p>
          <p v-if="attention.length" class="platform-finding">{{ attention.map(p => p.label).join('、') }} 存在需要处理的接口，选择平台查看原因。</p>
          <p v-else>仅检测 10 个代表只读接口；统一记录 MCP 与网页的检测结果，已知异常单独复测。</p>
          <p>状态来源：webmirage_check_health · 调用统计仅供参考</p>
        </div>
        <div class="platform-service">
          <span :class="['badge', state.mcp_connected ? 'green' : 'amber']"><span class="status-dot" :class="{ offline: !state.mcp_connected }" />{{ state.syncing ? '正在同步 MCP' : state.mcp_connected ? 'MCP 已连接' : 'MCP 未连接' }}</span>
          <span class="platform-sync">最近同步 {{ date(state.synced_at) }}</span>
          <button class="button secondary" :disabled="blocked" @click="check()"><RefreshCw :size="14" aria-hidden="true" />检测 10 个代表接口</button>
        </div>
      </section>
      <form class="panel platform-monitoring" aria-label="平台自动检测设置" @submit.prevent="saveMonitoring">
        <div class="node-toolbar"><label class="monitoring-toggle"><input v-model="monitoringEnabled" type="checkbox" aria-label="启用平台自动检测" :disabled="monitoringBusy" @change="monitoringDirty = true" />自动检测</label><label for="monitoring-interval">基础周期</label><select id="monitoring-interval" v-model.number="monitoringInterval" :disabled="monitoringBusy" @change="monitoringDirty = true"><option v-for="minutes in [15, 30, 60, 120]" :key="minutes" :value="minutes">每 {{ minutes }} 分钟</option></select><button class="button secondary" :disabled="monitoringBusy || !monitoringDirty"><LoaderCircle v-if="monitoringBusy" :size="14" class="spin" />保存检测设置</button><span v-if="monitoringNotice" class="monitoring-note" role="status">{{ monitoringNotice }}</span></div>
        <p>各接口通过统一 MCP 工具串行检测，共用 60 秒接口冷却；来自 MCP 客户端的新检测结果会同步计划。连续失败最长退避 4 小时。结果超过基础周期加 5 分钟会标记过期，不代表故障；暂停后仍可手动检查。</p>
        <p v-if="monitoringError" class="monitoring-error" role="alert">{{ monitoringError }}</p>
      </form>
      <div v-if="state.error" class="notice manual-notice" role="alert"><AlertCircle :size="18" /><div><strong>{{ state.error }}</strong><span>缓存结果不能证明当前可用。</span></div></div>
      <div v-if="notice || state.job.status !== 'idle'" class="notice probe-notice platform-job" role="status">
        <LoaderCircle v-if="checking" class="spin" :size="17" aria-hidden="true" /><ShieldCheck v-else :size="17" aria-hidden="true" />
        <div><strong v-if="state.job.status !== 'idle'">{{ state.job.source === 'auto' ? '自动' : '手动' }} · {{ checking ? '正在检测' : state.job.status === 'cancelled' ? '已暂停' : state.job.status === 'error' ? '检测未完整完成' : '检测结束' }} {{ state.job.completed }} / {{ state.job.total }} · 通过 {{ state.job.passed }} · 未通过 {{ state.job.failed }}</strong><span>{{ state.job.current || state.job.error || notice || '检测记录已保存。' }}<template v-if="state.job.cooldown_seconds"> · 冷却 {{ state.job.cooldown_seconds }} 秒</template></span></div>
      </div>

      <section aria-labelledby="platform-register-title">
        <div class="section-heading"><div><h2 id="platform-register-title">平台状态与处理 <span>{{ platforms.length }}</span></h2><p>区分未检测、结果已过期及凭证变更；失败原因与历史记录保留。</p></div><span class="badge neutral">{{ state.monitoring?.enabled ? '低频自动检测已开启' : '自动检测已暂停' }}</span></div>
        <div class="panel nodes-table-panel platform-register">
          <p class="platform-scroll-hint">左右滑动表格，可查看凭证状态与管理操作。</p>
          <div class="table-scroll">
            <table class="nodes-table platform-register-table">
              <thead><tr><th>接入平台</th><th>连接 / 检测状态</th><th>凭证 / 调用统计</th><th class="align-right">操作</th></tr></thead>
              <tbody>
                <tr v-for="platform in platforms" :key="platform.id" :class="['platform-row', { chosen: platform.id === selected }]">
                  <td><button class="platform-identity" :aria-pressed="platform.id === selected" @click="select(platform.id)"><strong>{{ platform.label }}</strong><span>{{ platform.route }} · {{ platform.registered_count }} 个工具 · 已检查 {{ platform.checked_count }} 个</span></button></td>
                  <td><div class="platform-cell"><span :class="['badge', 'platform-state', tone(platform.category)]">{{ platform.message }}</span><small>最近检测 {{ date(platform.last_checked_at) }} · 真实调用约 {{ passiveDate(platform) }}</small><small v-if="platform.monitoring">{{ platform.monitoring.message }}<template v-if="platform.monitoring.next_check_at"> · 下次 {{ date(platform.monitoring.next_check_at) }}</template></small></div></td>
                  <td><div class="platform-cell"><span>{{ platform.credentials.configured ? '已配置凭证' : platform.anonymous ? '可尝试匿名访问' : '需要配置凭证' }}</span><small v-if="platform.credentials.missing?.length">缺少：{{ platform.credentials.missing.join('、') }}</small><small v-else>自 MCP 启动：{{ platform.passive.calls ?? 0 }} 次 · 失败 {{ platform.passive.fail ?? 0 }}</small><small v-if="platform.passive.business_verified === false">旧版调用计数未校验业务结果，以统一检测为准</small></div></td>
                  <td><div class="platform-row-actions"><button class="text-button" :disabled="blocked || !platform.registered_count" @click="check(platform.id)" :aria-label="`检查${platform.label}平台`">检查平台</button><button class="button secondary" :disabled="saving || checking" @click="edit(platform)" :aria-label="`更新${platform.label}凭证`">更新凭证</button></div></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section v-if="selected === 'reddit'" class="panel platform-monitoring reddit-runtime" aria-labelledby="reddit-runtime-title" :aria-busy="redditBusy">
        <div class="section-heading"><div><h2 id="reddit-runtime-title">Reddit · 请求方式与浏览器</h2><p>浏览器试点支持帖子搜索和社区帖子；其他三个工具及翻页需切回 HTTP。凭证导入不代表登录有效。</p></div></div>
        <div class="node-toolbar platform-toolbar">
          <label for="reddit-backend">当前请求方式</label>
          <select id="reddit-backend" v-model="redditBackendChoice" :disabled="redditBusy || checking || redditRuntime.backend_locked" @change="redditAction(redditBackendChoice as 'http' | 'opencli')"><option value="http">HTTP · 现有方式</option><option value="opencli">OpenCLI · 浏览器试点</option></select>
          <span :class="['badge', redditRuntime.available ? 'green' : 'amber']">{{ redditRuntime.available ? '工作进程已连接' : '工作进程未连接' }}</span>
          <span class="badge neutral">{{ redditRuntime.running ? '浏览器运行中' : '浏览器已停止' }}</span>
          <span :class="['badge', redditRuntime.session_imported ? (redditRuntime.session_current ? 'green' : 'amber') : 'neutral']">{{ redditRuntime.session_imported ? (redditRuntime.session_current ? '会话与当前配置一致' : '会话与当前配置不一致 · 需重新导入') : '尚未导入会话' }}</span>
        </div>
        <div class="node-toolbar platform-toolbar">
          <button class="button secondary" :disabled="startDisabled" :title="startBlockedReason" @click="redditAction('start')">启动 / 更新会话</button>
          <button class="button secondary" :disabled="redditBusy || checking || !redditRuntime.running || redditRuntime.busy" @click="redditAction('stop')">停止浏览器</button>
          <button class="button primary" :disabled="blocked || redditBusy" @click="check('reddit')">检测两个代表接口</button>
        </div>
        <p>浏览器按需启动，空闲 {{ Math.round((redditRuntime.idle_seconds ?? 600) / 60) }} 分钟自动关闭；刷新页面仅读取本地状态。</p>
        <p v-if="redditRuntime.version">OpenCLI {{ redditRuntime.version }} · 最近活动 {{ date(redditRuntime.last_activity) }}</p>
        <p v-if="redditRuntime.last_failure" class="platform-finding" role="status">最近浏览器结果：{{ failureText(redditRuntime.last_failure) }}。当前接口状态以下方统一检测记录为准。</p>
        <p v-if="inCooldown" class="platform-finding reddit-cooldown" role="status">限流冷却中 · 剩余 {{ formatDuration(cooldownRemaining) }} · 冷却至 {{ date(redditRuntime.cooldown_until) }}；期间启动按钮已禁用。</p>
        <p v-if="sessionMismatch" class="monitoring-error" role="alert">配置中的 Reddit Cookie 已变更，与浏览器已导入会话不一致，请点击“启动 / 更新会话”重新导入。</p>
        <p v-if="redditNotice" role="status">{{ redditNotice }}</p><p v-if="redditError" class="monitoring-error" role="alert">{{ redditError }}</p>
      </section>

      <section v-if="current" class="platform-endpoints" aria-labelledby="platform-endpoints-title">
        <div class="section-heading"><div><h2 id="platform-endpoints-title">{{ current.label }} · 接口可用性</h2><p>{{ current.advice }} 检查通过只覆盖对应接口，其他工具保留为未验证。</p></div></div>
        <div class="node-toolbar platform-toolbar"><label for="platform-select">查看平台</label><select id="platform-select" :value="selected" @change="select(($event.target as HTMLSelectElement).value)"><option v-for="platform in platforms" :key="platform.id" :value="platform.id">{{ platform.label }}</option></select><span class="platform-toolbar-note">{{ current.endpoints.length }} 个接口 · 按接口分别记录检测结果</span></div>
        <div class="panel nodes-table-panel">
          <p class="platform-scroll-hint">左右滑动表格，可查看检测时间与单独检测入口。</p>
          <div class="table-scroll">
            <table class="nodes-table platform-tools-table">
              <thead><tr><th>接口 / 工具</th><th>最近结果</th><th class="align-right">完整调用耗时</th><th class="align-right">24h 主动检测</th><th>最后检测（北京时间）</th><th class="align-right">操作</th></tr></thead>
              <tbody><tr v-for="endpoint in current.endpoints" :key="endpoint.name">
                <td><div class="platform-cell"><strong>{{ endpoint.label }}</strong><code>{{ endpoint.name }}</code><small v-if="endpoint.backend">请求方式：{{ endpoint.backend === 'opencli' ? 'OpenCLI 浏览器' : 'HTTP' }}</small></div></td>
                <td><div class="platform-cell"><span :class="['badge', 'platform-state', tone(endpoint.stale && endpoint.category === 'ok' ? 'unknown' : endpoint.category)]">{{ endpoint.message }}</span><small v-if="endpoint.stale || endpoint.freshness === 'credentials_changed' || endpoint.category !== 'ok'">{{ endpoint.advice }}</small></div></td>
                <td class="align-right platform-number">{{ endpoint.elapsed_ms == null ? '—' : `${(endpoint.elapsed_ms / 1000).toFixed(2)} s` }}</td>
                <td class="align-right platform-number"><div class="platform-cell">{{ endpoint.success_rate == null ? '—' : `${endpoint.success_rate.toFixed(1)}%` }}<small>{{ endpoint.samples }} 次样本</small></div></td>
                <td><div class="platform-cell"><span>{{ date(endpoint.checked_at) }}</span><small v-if="endpoint.check_source">{{ endpoint.check_source === 'auto' ? '自动检测' : endpoint.check_source === 'mcp' ? 'MCP 客户端检测' : '手动检测' }}</small></div></td>
                <td class="align-right"><button v-if="endpoint.probeable" class="button secondary" :disabled="blocked || !endpoint.registered" @click="check(current.id, endpoint.name)" :aria-label="`检测${endpoint.name}`">单独检测</button><span v-else class="platform-muted">{{ endpoint.write ? '不自动调用' : '需业务参数验证' }}</span></td>
              </tr></tbody>
            </table>
          </div>
        </div>
      </section>

      <section class="platform-history" aria-labelledby="platform-history-title">
        <div class="section-heading"><div><h2 id="platform-history-title">{{ current?.label }} · 检测历史 <span>{{ state.history.total }}</span></h2><p>保留 30 天，最多 10,000 条。仅保存结论与耗时，不保存 Cookie 或响应正文。</p></div></div>
        <div class="panel nodes-table-panel">
          <div v-if="!state.history.rows.length" class="empty"><ShieldCheck :size="24" /><strong>暂无此平台的主动检测记录</strong><span>可在上方运行一次只读检查。</span></div>
          <template v-else>
            <div class="table-scroll"><table class="nodes-table platform-history-table"><thead><tr><th>接口 / 工具</th><th>检测结果</th><th class="align-right">检测时间（北京时间）</th></tr></thead><tbody><tr v-for="record in state.history.rows" :key="record.id"><td><div class="platform-cell"><code>{{ record.tool }}</code><small v-if="record.backend">请求方式：{{ record.backend === 'opencli' ? 'OpenCLI 浏览器' : 'HTTP' }}</small><small>{{ record.source === 'auto' ? '自动检测' : record.source === 'configuration' ? '凭证更新' : record.source === 'mcp' ? 'MCP 客户端检测' : '手动检测' }}</small></div></td><td><div class="platform-cell"><span :class="['badge', 'platform-state', tone(record.category)]">{{ record.message }}</span><small>{{ record.advice }}</small></div></td><td class="align-right"><time>{{ date(record.timestamp) }}</time></td></tr></tbody></table></div>
            <div class="table-footer"><span>共 {{ state.history.total }} 条检测记录</span><div v-if="state.history.total > 20" class="pagination"><button :disabled="page <= 1" @click="page--; refresh()" aria-label="平台历史上一页"><ChevronLeft :size="16" /></button><span>{{ page }} / {{ Math.ceil(state.history.total / 20) }}</span><button :disabled="page * 20 >= state.history.total" @click="page++; refresh()" aria-label="平台历史下一页"><ChevronRight :size="16" /></button></div></div>
          </template>
        </div>
      </section>
    </template>

    <dialog ref="dialog" class="switch-dialog platform-dialog" aria-labelledby="platform-credential-title" @close="clearForm" @cancel="saving && $event.preventDefault()">
      <form v-if="editing" @submit.prevent="save">
        <div class="dialog-heading"><span class="dialog-icon"><ShieldCheck :size="24" aria-hidden="true" /></span><button type="button" class="icon-button" :disabled="saving" @click="dialog?.close()" aria-label="关闭凭证窗口"><X :size="19" aria-hidden="true" /></button></div>
        <h2 id="platform-credential-title">更新 {{ editing.label }} 凭证</h2>
        <p>{{ editing.id === 'xianyu' ? '闲鱼四个必填项需一并填写，使用同一次登录的值；其他可选项留空保留原值。' : '仅修改填入的字段，留空保留原值。' }}当前密钥不会回显；保存后热加载，仍需重新检测确认。</p>
        <section v-if="credentialSources[editing.id]" class="credential-guide" :aria-label="`${editing.label}凭证获取说明`">
          <strong>获取位置 · <a :href="credentialSources[editing.id].url" target="_blank" rel="noopener noreferrer">{{ credentialSources[editing.id].domain }}</a></strong>
          <p>{{ credentialSources[editing.id].instruction }}</p>
          <p v-if="cookieForm && credentialMode === 'full'">完整 Cookie 可在 F12 → Network（网络）中选择该站请求，从 Request Headers（请求标头）的 Cookie 项复制键值对；填写时从名称开始，例如 name=value。</p>
          <p v-if="credentialSources[editing.id].note">{{ credentialSources[editing.id].note }}</p>
        </section>
        <div v-if="cookieForm" class="platform-field"><label for="credential-mode">更新方式</label><select id="credential-mode" v-model="credentialMode" class="credential-mode" @change="changeCredentialMode"><option value="values">逐项填写（默认，仅填值）</option><option value="full">导入完整 Cookie（替换全部 Cookie）</option></select></div>
        <component v-for="group in fieldGroups" :is="group.label ? 'details' : 'div'" :key="group.key" :class="{ 'credential-additional': group.label }">
          <summary v-if="group.label">{{ group.label }}</summary>
        <div v-for="field in group.fields" :key="field" class="platform-field">
          <div class="credential-field-heading"><label :for="`platform-${field}`">{{ credentialFields[field]?.configField && credentialFields[field]?.valueOnly ? `${credentialFields[field].name} 的值` : fieldLabels[field] ?? field }}</label><span v-if="credentialFields[field]" class="badge neutral">{{ credentialFields[field].requirement }}</span></div>
          <dl v-if="credentialFields[field] && !credentialFields[field].valueOnly" class="credential-mapping">
            <dt>{{ editing.id === 'github' ? '凭证名称' : 'Cookie 名称' }}</dt><dd><code>{{ credentialFields[field].name }}</code></dd>
            <dt>系统字段</dt><dd><code>{{ credentialFields[field].configField ?? field }}</code></dd>
            <dt>填写格式</dt><dd><code>{{ credentialFields[field].example }}</code></dd>
          </dl>
          <input :id="`platform-${field}`" v-model="values[field]" type="password" autocomplete="new-password" maxlength="16000" :required="requiredCredential(field)" :placeholder="credentialFields[field]?.example" :aria-describedby="`platform-${field}-help`" :disabled="saving || locked(field)" />
          <small :id="`platform-${field}-help`" class="credential-hint">{{ credentialFields[field]?.hint ?? '填写要替换的新值，留空保留原配置。' }}</small>
          <small v-if="locked(field)">此字段由环境变量覆盖，请在服务配置中更新。</small>
        </div>
        </component>
        <p v-if="saveError" class="platform-form-error" role="alert">{{ saveError }}</p>
        <div class="dialog-actions"><button class="button secondary" type="button" :disabled="saving" @click="dialog?.close()">取消</button><button class="button primary" type="submit" :disabled="saving"><LoaderCircle v-if="saving" class="spin" :size="15" aria-hidden="true" />{{ saving ? '正在保存' : '保存并热加载' }}</button></div>
      </form>
    </dialog>
  </div>
</template>

<style scoped>
/* Panels, headings, controls, tables and status colours use the gateway's shared classes. */
.platform-page { font-variant-numeric: tabular-nums; }
.platform-monitoring { padding: 15px 18px; margin: 0 0 18px; }
.platform-monitoring .node-toolbar { margin: 0; flex-wrap: wrap; }
.platform-monitoring label { color: var(--ink); font-size: 11px; }
.monitoring-toggle { display: inline-flex; align-items: center; gap: 7px; margin-right: 10px; }
.monitoring-toggle input { accent-color: var(--green); width: 15px; height: 15px; margin: 0; }
.platform-monitoring p, .monitoring-note { color: var(--muted); font-size: 10px; line-height: 1.8; }
.platform-monitoring p { margin: 9px 0 0; }
.platform-monitoring .monitoring-error { color: #a2573c; }
.platform-service { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 8px 12px; max-width: 360px; }
.platform-sync { color: var(--muted); font-size: 10px; white-space: nowrap; }
.platform-overview .platform-finding { color: var(--green-dark); }
.platform-register-table { min-width: 900px; }
.platform-page .platform-row.chosen { background: #f4f8f5; }
.platform-identity { text-align: left; display: flex; flex-direction: column; gap: 6px; }
.platform-identity strong, .platform-cell > strong { color: var(--ink); font-size: 12px; font-weight: 500; }
.platform-identity > span, .platform-cell > small, .platform-toolbar-note, .platform-muted { color: var(--muted); font-size: 10px; }
.platform-cell { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; white-space: normal; min-width: 0; }
.platform-cell > small { line-height: 1.6; }
.platform-page code { font-family: inherit; font-size: 10px; color: var(--muted); overflow-wrap: anywhere; }
.platform-row-actions { display: flex; align-items: center; justify-content: flex-end; gap: 14px; }
.platform-state { max-width: 240px; white-space: normal; }
.platform-toolbar > label { color: var(--muted); font-size: 11px; }
.platform-toolbar-note { margin-left: auto; }
.platform-tools-table { min-width: 1080px; }
.platform-tools-table td:first-child { width: 25%; }
.platform-number { font-variant-numeric: tabular-nums; }
.platform-number .platform-cell { align-items: flex-end; }
.platform-history-table { min-width: 780px; }
.platform-history-table td:nth-child(2) { max-width: 420px; }
.platform-scroll-hint { display: none; }
.platform-dialog { max-height: 85dvh; overflow-y: auto; }
.platform-field { display: flex; flex-direction: column; gap: 8px; margin-top: 18px; }
.platform-field label { color: var(--ink); font-size: 12px; }
.platform-field input { min-height: 40px; border: 1px solid var(--border); border-radius: 7px; padding: 9px 11px; font: inherit; width: 100%; }
.credential-additional { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border); }
.credential-additional summary { cursor: pointer; color: var(--ink); font-size: 12px; line-height: 1.7; }
.credential-mode { min-height: 40px; border: 1px solid var(--border); border-radius: 7px; padding: 9px 11px; background: white; color: var(--ink); font-size: 11px; width: 100%; }
.platform-field small { font-size: 10px; line-height: 1.6; color: var(--muted); }
.platform-dialog .platform-form-error { color: #a2573c; margin-top: 16px; }
.credential-guide { margin-top: 16px; padding: 12px 14px; border: 1px solid var(--border); border-radius: 7px; }
.credential-guide strong { font-size: 12px; font-weight: 500; }
.credential-guide a { color: var(--green-dark); text-decoration: underline; text-underline-offset: 3px; }
.platform-dialog .credential-guide p { margin: 7px 0 0; color: var(--ink); font-size: 11px; line-height: 1.8; }
.credential-field-heading { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.credential-mapping { display: grid; grid-template-columns: 66px minmax(0, 1fr); gap: 6px 10px; margin: 0; font-size: 11px; line-height: 1.7; }
.credential-mapping dt { color: var(--muted); }
.credential-mapping dd { margin: 0; min-width: 0; }
.credential-mapping code { font-size: 11px; color: var(--ink); }
.platform-field .credential-hint { color: var(--ink); font-size: 11px; line-height: 1.8; }
@media (max-width: 1100px) {
  .platform-service { justify-content: flex-start; max-width: none; }
  .platform-register-table { min-width: 850px; }
}
@media (max-width: 720px) {
  .platform-overview { align-items: stretch; }
  .platform-service { gap: 10px; }
  .platform-service .button { min-height: 44px; }
  .platform-toolbar > label { width: 100%; }
  .platform-toolbar-note { margin-left: 0; width: 100%; line-height: 1.6; }
  .platform-scroll-hint { display: block; padding: 10px 15px; color: var(--muted); font-size: 10px; line-height: 1.6; border-bottom: 1px solid var(--border); }
  .platform-row-actions .button, .platform-row-actions .text-button, .platform-tools-table .button { min-height: 44px; }
  .platform-page .section-heading { flex-wrap: wrap; }
  .platform-dialog .button { min-height: 44px; }
}
</style>
