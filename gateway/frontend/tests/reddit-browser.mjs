// UI controls are intercepted; this test never changes live backend/session state.
import { chromium, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'
const base = process.env.GATEWAY_TEST_URL || 'http://192.168.188.3:8091'
const browser = await chromium.launch({ headless: true,
  executablePath: '/home/lcarus/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome', args: ['--no-sandbox'] })
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
  expect((await context.request.post(`${base}/api/login`, { data: { password:
    (await readFile(new URL('../../../mihomo/data/gateway-admin-password', import.meta.url), 'utf8')).trim() } })).ok()).toBeTruthy()
  const page = await context.newPage(), errors = [], writes = []
  page.on('pageerror', e => errors.push(e.message))
  const initial = await (await context.request.get(`${base}/api/platforms?platform=reddit`)).json()
  expect(initial.mcp_connected).toBeTruthy()
  expect(initial.reddit_runtime.backend).toBe('http')
  const runtimeFixture = { backend: 'http', available: true, running: true, session_imported: true, session_current: true, busy: false, version: '2.0.2', idle_seconds: 600, last_failure: null, cooldown_until: 0 }
  await page.route('**/api/platforms?*', async route => {
    const response = await route.fetch()
    const data = await response.json()
    data.reddit_runtime = { ...runtimeFixture }
    data.job = { status: 'idle', cooldown_seconds: 0 }
    await route.fulfill({ response, json: data })
  })
  await page.route('**/api/platforms/reddit/*', route => {
    writes.push({ url: route.request().url(), body: route.request().postDataJSON() })
    return route.fulfill({ status: 409, json: { detail: '测试：操作未确认，未修改真实配置' } })
  })
  await page.route('**/api/platforms/check', route => {
    writes.push({ url: route.request().url(), body: route.request().postDataJSON() })
    return route.fulfill({ status: 202, json: { status: 'idle', total: 2, cooldown_seconds: 0 } })
  })
  await page.goto(`${base}/#platforms`)
  await page.getByLabel('查看平台', { exact: true }).selectOption('reddit')
  await expect(page.getByRole('heading', { name: 'Reddit · 请求方式与浏览器' })).toBeVisible()
  await expect(page.getByLabel('当前请求方式', { exact: true })).toHaveValue('http')
  await page.getByLabel('当前请求方式', { exact: true }).selectOption('opencli')
  await expect(page.getByRole('alert')).toContainText('测试：操作未确认')
  await expect(page.getByLabel('当前请求方式', { exact: true })).toHaveValue('http')
  expect(writes[0].body).toEqual({ backend: 'opencli' })
  await page.getByRole('button', { name: '启动 / 更新会话', exact: true }).click()
  await expect.poll(() => writes.length).toBe(2)
  expect(writes[1].body).toEqual({ operation: 'start' })
  await expect(page.locator('.reddit-runtime')).toHaveAttribute('aria-busy', 'false')
  await page.getByRole('button', { name: '停止浏览器', exact: true }).click()
  await expect.poll(() => writes.length).toBe(3)
  expect(writes[2].body).toEqual({ operation: 'stop' })
  await expect(page.locator('.reddit-runtime')).toHaveAttribute('aria-busy', 'false')
  await page.getByRole('button', { name: '检测两个代表接口', exact: true }).click()
  await expect.poll(() => writes.length).toBe(4)
  expect(writes[3].body).toEqual({ platform: 'reddit' })

  // Cooldown after a 429: start is disabled pre-emptively with a reason, no 409 round trip.
  Object.assign(runtimeFixture, { running: false, last_failure: 'rate_limit', cooldown_until: Date.now() / 1000 + 1800 })
  const startButton = page.getByRole('button', { name: '启动 / 更新会话', exact: true })
  await expect.poll(async () => (await startButton.isDisabled()) ? 'disabled' : 'enabled', { timeout: 10000 }).toBe('disabled')
  await expect(page.getByText(/限流冷却中/)).toBeVisible()
  await expect(page.getByText(/429/).first()).toBeVisible()
  expect((await startButton.getAttribute('title'))).toContain('冷却')
  await startButton.click({ force: false }).catch(() => {})
  expect(writes.length).toBe(4)

  // Config cookie changed while an old session stays imported: mismatch prompt, no raw failure text.
  Object.assign(runtimeFixture, { running: true, last_failure: null, cooldown_until: 0, session_current: false })
  await expect(page.getByText(/会话与当前配置不一致/)).toBeVisible({ timeout: 10000 })
  await expect(page.getByText(/重新导入/)).toBeVisible()
  await expect.poll(async () => (await startButton.isDisabled()) ? 'disabled' : 'enabled', { timeout: 10000 }).toBe('enabled')

  // An unknown failure category is normalised to the generic copy rather than echoed.
  Object.assign(runtimeFixture, { last_failure: 'mystery_blob_9f3a', session_current: true })
  await expect(page.getByText(/未知失败/)).toBeVisible({ timeout: 10000 })
  expect(await page.locator('.reddit-runtime').innerText()).not.toContain('mystery_blob_9f3a')

  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1100 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await page.screenshot({ path: `../artifacts/reddit-browser/ui-${width}.png`, fullPage: true })
  }
  expect(errors).toEqual([])
  console.log('PASS: Reddit backend/lifecycle controls, failed-operation feedback, fixed two-tool checks, desktop/mobile layouts. All mutations intercepted.')
} finally { await browser.close() }
