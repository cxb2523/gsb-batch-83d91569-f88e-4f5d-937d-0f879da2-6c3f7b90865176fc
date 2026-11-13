// Read-only live data plus intercepted manual checks. No external probes or
// policy changes are initiated by this browser regression test.
import { chromium, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'

const base = (process.env.GATEWAY_TEST_URL || 'http://192.168.188.3:8091').replace(/\/$/, '')
const browser = await chromium.launch({ headless: true,
  executablePath: process.env.CHROMIUM_PATH || '/home/lcarus/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome',
  args: ['--no-sandbox'] })
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1080 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  const login = await context.request.post(`${base}/api/login`, { data: {
    password: (await readFile(new URL('../../../mihomo/data/gateway-admin-password', import.meta.url), 'utf8')).trim() } })
  expect(login.ok()).toBeTruthy()
  const snap = await (await context.request.get(`${base}/api/snapshot`)).json()
  expect(snap.health_check.full_interval).toBe(900)
  expect(snap.health_check.exit_interval).toBe(120)
  let job = { status: 'idle', total: 0, completed: 0, passed: 0, failed: 0, cooldown_seconds: 0 }
  const submitted = []
  await page.route('**/api/healthcheck', async route => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON()
      submitted.push(body)
      job = { ...job, status: 'running', total: body.scope === 'page' ? body.nodes.length : 1 }
      return route.fulfill({ status: 202, json: job })
    }
    return route.fulfill({ json: job })
  })
  await page.goto(`${base}/#nodes`)
  await expect(page.getByRole('heading', { name: '订阅与节点.' })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: 'HTTPS 探测', exact: true })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '近期成功率', exact: true })).toBeVisible()
  await expect(page.getByRole('columnheader', { name: '最后检测', exact: true })).toBeVisible()
  await expect(page.locator('.probe-summary')).toContainText('全量每 15 分钟')
  await expect(page.locator('.probe-summary')).toContainText('每 2 分钟')
  await page.waitForTimeout(5500)
  expect(submitted).toHaveLength(0)
  await page.getByRole('button', { name: '刷新状态', exact: true }).click()
  await expect.poll(() => submitted.length).toBe(1)
  expect(submitted[0].scope).toBe('page')
  expect(submitted[0].nodes.length).toBe(12)
  await expect(page.getByRole('button', { name: '刷新状态', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: /^检测全部/ })).toBeDisabled()
  job = { ...job, status: 'done', completed: job.total, passed: job.total, cooldown_seconds: 45 }
  await expect(page.locator('.probe-notice')).toContainText('冷却剩余', { timeout: 10000 })
  await expect(page.getByRole('button', { name: /^检测全部/ })).toBeDisabled()
  job = { ...job, cooldown_seconds: 0 }
  await expect(page.getByRole('button', { name: '刷新状态', exact: true })).toBeEnabled({ timeout: 10000 })
  await page.getByLabel('筛选订阅').selectOption('managed-primary')
  await page.getByRole('button', { name: '检测此订阅', exact: true }).click()
  await expect.poll(() => submitted.length).toBe(2)
  expect(submitted[1].scope).toBe('provider')
  expect(submitted[1].provider).toBe('managed-primary')
  job = { ...job, status: 'done', completed: job.total, passed: job.total, cooldown_seconds: 0 }
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
  await page.getByRole('button', { name: '网关总览', exact: true }).click()
  await expect(page.getByRole('button', { name: '刷新状态', exact: true })).toBeEnabled({ timeout: 10000 })
  await page.getByRole('button', { name: '刷新状态', exact: true }).click()
  await expect.poll(() => submitted.length).toBe(3)
  expect(submitted[2].scope).toBe('current')
  expect(errors).toEqual([])
  console.log('PASS: status polling never probes; page/provider/current scopes, progress, cooldown, quality columns and mobile overflow. All manual probes intercepted.')
} finally { await browser.close() }
