// PLATFORM_TEST_ACTIVE=1 checks the ten allowlisted read-only interfaces once.
// Default is read-only; credential saves are always intercepted in-browser.
import { chromium, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
const base = (process.env.GATEWAY_TEST_URL || 'http://192.168.188.3:8091').replace(/\/$/, '')
const active = process.env.PLATFORM_TEST_ACTIVE === '1'
const browser = await chromium.launch({ headless: true,
  executablePath: process.env.CHROMIUM_PATH || '/home/lcarus/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome', args: ['--no-sandbox'] })
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1080 } })
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  const login = await context.request.post(`${base}/api/login`, { data: { password:
    (await readFile(new URL('../../../mihomo/data/gateway-admin-password', import.meta.url), 'utf8')).trim() } })
  expect(login.ok()).toBeTruthy()
  let snapshot
  await expect.poll(async () => {
    try { const r = await context.request.get(`${base}/api/platforms`); if (!r.ok()) return false; snapshot = await r.json(); return snapshot.mcp_connected }
    catch { return false }
  }, { timeout: 90000 }).toBeTruthy()
  expect(snapshot.platforms.length).toBe(5)
  expect(snapshot.platforms.reduce((sum, p) => sum + p.registered_count, 0)).toBe(33)
  expect(JSON.stringify(snapshot)).not.toContain('revision')
  await page.goto(`${base}/#platforms`)
  await expect(page.getByRole('heading', { name: '平台健康.' })).toBeVisible()
  await expect(page.locator('.platform-row')).toHaveCount(5)
  if (active) {
    await page.getByRole('button', { name: '检测 10 个代表接口', exact: true }).click()
    await expect(page.locator('.platform-job')).toContainText('正在检测', { timeout: 10000 })
    let job
    await expect.poll(async () => {
      try {
        const r = await context.request.get(`${base}/api/platforms`)
        if (!r.ok()) return 'reconnecting'
        const next = await r.json(); job = next.job; return job.status
      } catch { return 'reconnecting' }
    }, { timeout: 600000, intervals: [2000] }).toBe('done')
    expect(job.completed).toBe(10)
    console.log(`Live read-only checks completed: passed=${job.passed}, failed=${job.failed}`)
  }
  await page.getByRole('button', { name: '闲鱼', exact: false }).filter({ has: page.locator('strong') }).first().click()
  await expect(page.getByRole('heading', { name: '闲鱼 · 接口可用性' })).toBeVisible()
  const writeRow = page.locator('.platform-endpoints tbody tr').filter({ hasText: 'xianyu_confirm_delivery' })
  await expect(writeRow).toContainText('写操作已排除')
  await expect(writeRow.getByRole('button')).toHaveCount(0)
  const rejected = await context.request.post(`${base}/api/platforms/check`, {
    headers: { 'X-Gateway-Request': '1' }, data: { tool: 'xianyu_confirm_delivery' } })
  expect(rejected.status()).toBe(400)
  let attemptedSave
  await page.route('**/api/platforms/credentials', route => {
    attemptedSave = route.request().postDataJSON()
    return route.fulfill({ status: 503, json: { detail: '测试：更新未确认，未写入真实配置' } })
  })
  await page.getByRole('button', { name: '更新雪球凭证', exact: true }).click()
  await expect(page.getByRole('heading', { name: '更新 雪球 凭证' })).toBeVisible()
  const input = page.getByLabel('xq_a_token 的值', { exact: true })
  await expect(input).toHaveValue('')
  expect(await input.getAttribute('type')).toBe('password')
  await input.fill('BROWSER-ONLY-SECRET')
  await page.getByRole('button', { name: '保存并热加载', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('测试：更新未确认')
  expect(attemptedSave.platform).toBe('xueqiu')
  expect(attemptedSave.updates.xq_a_token).toBe('BROWSER-ONLY-SECRET')
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '更新雪球凭证', exact: true }).click()
  await expect(input).toHaveValue('')
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.unroute('**/api/platforms/credentials')
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await page.screenshot({ path: `../artifacts/platforms-${width}.png`, fullPage: true })
  }
  const html = await page.locator('.platform-page').evaluate(el => el.outerHTML)
  const styles = await page.locator('link[rel=stylesheet]').evaluateAll(elements => elements.map(el => `<link rel="stylesheet" href="${el.href}">`).join('\n'))
  await writeFile('../artifacts/platform-design/screen.html', `<!doctype html><html lang="zh-CN"><head><meta name="viewport" content="width=device-width,initial-scale=1">${styles}<style>body{padding:24px;margin:0;background:#f5f7f6;font-family:Arial,sans-serif}h1{font-size:24px;font-weight:600;margin:0 0 24px}</style></head><body><h1>平台健康</h1>${html}</body></html>`)
  snapshot = await (await context.request.get(`${base}/api/platforms`)).json()
  await writeFile('../artifacts/platforms-verification.json', JSON.stringify(snapshot, null, 2))
  expect(errors).toEqual([])
  console.log('PASS: five platforms, 33 tools, read-only write exclusion, blank masked credentials, failed-save feedback, cleared secrets, desktop/tablet/mobile layouts.')
} catch (error) {
  console.error(String(error.message).replace(/mirage_session=[^\s'"\]]+/g, 'mirage_session=[redacted]'))
  process.exitCode = 1
} finally { await browser.close() }
