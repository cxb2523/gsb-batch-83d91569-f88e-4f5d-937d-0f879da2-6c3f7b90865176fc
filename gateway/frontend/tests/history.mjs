// Live read-only history verification; browser-only fixtures cover larger lists.
import { chromium, expect } from '@playwright/test'
import { readFile, mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const base = (process.env.GATEWAY_TEST_URL || 'http://192.168.188.3:8091').replace(/\/$/, '')
const artifacts = fileURLToPath(new URL('../../artifacts/', import.meta.url))
await mkdir(artifacts, { recursive: true })
const password = (await readFile(new URL('../../../mihomo/data/gateway-admin-password', import.meta.url), 'utf8')).trim()
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROMIUM_PATH || '/home/lcarus/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome', args: ['--no-sandbox'] })
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, timezoneId: 'UTC' })
const page = await context.newPage()
const errors = []
page.on('pageerror', e => errors.push(e.message))
let lastQuery
page.on('request', request => { if (request.url().includes('/api/history?')) lastQuery = new URL(request.url()).searchParams })

try {
  const login = await context.request.post(`${base}/api/login`, { headers: { 'X-Gateway-Request': '1' }, data: { password } })
  expect(login.ok()).toBeTruthy()
  await page.goto(`${base}/#history`)
  await expect(page.getByRole('heading', { name: '历史流量.' })).toBeVisible()
  await expect(page.getByText('后台持续记录中', { exact: true })).toBeVisible()
  await expect(page.locator('.history-records tbody tr').first()).toBeVisible()
  expect(lastQuery.get('group_by')).toBe('category')
  await page.getByLabel('历史分类方式').selectOption('domain')
  await expect.poll(() => lastQuery.get('group_by')).toBe('domain')
  await expect(page.locator('.history-groups th').first()).toHaveText('目标域名')
  await expect(page.locator('.history-page')).toHaveAttribute('aria-busy', 'false')
  const firstGroup = await page.locator('.history-group-label').first().textContent()
  await page.locator('.history-groups tbody tr').first().getByRole('button', { name: '查看连接' }).click()
  await expect(page.locator('.history-chip')).toContainText(firstGroup)
  await expect.poll(() => lastQuery.get('group_value')).toBe(firstGroup)
  await page.locator('.history-chip').click()
  await page.getByLabel('搜索历史记录').fill('should-not-exist.invalid')
  await page.getByRole('button', { name: '查询记录', exact: true }).click()
  await expect(page.getByText('没有匹配的历史连接', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '清除历史搜索' }).click()
  await expect(page.locator('.history-records tbody tr').first()).toBeVisible()
  await page.getByRole('button', { name: '最近 1 小时', exact: true }).click()
  await expect.poll(() => Math.round(Number(lastQuery.get('end')) - Number(lastQuery.get('start')))).toBe(3600)

  // Custom input is Beijing time even when the user's browser timezone is UTC.
  await page.getByLabel('历史开始时间').fill('2026-11-01T12:00')
  await page.getByLabel('历史结束时间').fill('2026-11-01T13:00')
  await page.getByRole('button', { name: '查询记录', exact: true }).click()
  await expect.poll(() => Number(lastQuery.get('start'))).toBe(Date.parse('2026-11-01T12:00:00+08:00') / 1000)
  await expect(page.locator('.history-page')).toHaveAttribute('aria-busy', 'false')
  await page.getByRole('button', { name: '最近 24 小时', exact: true }).click()
  await expect(page.locator('.history-records tbody tr').first()).toBeVisible()
  await page.getByLabel('历史分类方式').selectOption('category')
  await expect(page.locator('.history-page')).toHaveAttribute('aria-busy', 'false')
  await page.screenshot({ path: `${artifacts}/history-desktop.png`, fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.screenshot({ path: `${artifacts}/history-mobile.png`, fullPage: true })
  await page.setViewportSize({ width: 1440, height: 1080 })

  const response = await context.request.get(`${base}/api/history?start=${Date.now() / 1000 - 3600}&end=${Date.now() / 1000}`)
  expect(response.ok()).toBeTruthy()
  const real = await response.json()
  const seed = real.records.rows[0]
  expect(seed).toBeTruthy()
  let failure = false
  let stale = false
  await page.route('**/api/history?*', async route => {
    if (failure) return route.fulfill({ status: 503, json: { detail: '测试：历史读取暂时中断' } })
    const params = new URL(route.request().url()).searchParams
    const pageNo = Number(params.get('page') || '1')
    const all = Array.from({ length: 21 }, (_, i) => ({ ...seed, key: `fixture-${i}`, host: `history${i + 1}.example`, state: stale ? 'unknown' : 'not_seen', period_upload: 100, period_download: 200 }))
    const fixture = { ...real, totals: { connections: 21, upload: 2100, download: 4200 }, records: { rows: all.slice((pageNo - 1) * 20, pageNo * 20), total: 21, page: pageNo, page_size: 20 } }
    if (stale) { fixture.collector = { ...fixture.collector, healthy: false }; fixture.gap_count = 1; fixture.gaps = [{ started: Date.now() / 1000 - 60, ended: null, reason: 'controller_unavailable' }] }
    return route.fulfill({ json: fixture })
  })
  await page.getByRole('button', { name: '刷新状态' }).click()
  await expect(page.locator('.history-records tbody tr')).toHaveCount(20)
  await page.getByRole('button', { name: '历史下一页' }).click()
  await expect(page.locator('.history-records tbody tr')).toHaveCount(1)
  await expect(page.locator('.history-records')).toContainText('history21.example')
  await page.getByRole('button', { name: '历史上一页' }).click()
  await expect(page.locator('.history-records tbody tr')).toHaveCount(20)
  failure = true
  await page.getByRole('button', { name: '刷新状态' }).click()
  await expect(page.getByRole('alert')).toContainText('测试：历史读取暂时中断')
  await expect(page.locator('.history-records tbody tr')).toHaveCount(20)
  failure = false; stale = true
  await page.getByRole('button', { name: /^重试/ }).click()
  await expect(page.getByText('采集暂停或数据过期', { exact: true })).toBeVisible()
  await expect(page.locator('.history-gaps')).toContainText('采集缺口')
  await page.unroute('**/api/history?*')
  await page.getByRole('button', { name: '刷新状态' }).click()
  await expect(page.getByText('后台持续记录中', { exact: true })).toBeVisible()
  expect(errors).toEqual([])
  console.log('PASS: live history, classifications, drilldown, time ranges, Beijing timezone, search, paging, outage/stale recovery, desktop/mobile. No proxy policy changes or database fixtures written.')
} finally { await browser.close() }
