// Real browser / real gateway check. Temporarily pins the existing active node,
// then restores the original mode, including on test failures.
import { chromium, expect } from '@playwright/test'
import { readFile, mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const base = (process.env.GATEWAY_TEST_URL || 'http://127.0.0.1:8091').replace(/\/$/, '')
const readOnly = process.env.GATEWAY_TEST_READ_ONLY === '1'
const passwordFile = fileURLToPath(new URL('../../../mihomo/data/gateway-admin-password', import.meta.url))
const artifactDir = fileURLToPath(new URL('../../artifacts/', import.meta.url))
await mkdir(artifactDir, { recursive: true })
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.CHROMIUM_PATH || '/home/lcarus/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome',
  args: ['--no-sandbox'],
})
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 } })
const page = await context.newPage()
const pageErrors = []
page.on('pageerror', e => pageErrors.push(e.message))
let before
let changedPolicy = false

async function snapshot() {
  const response = await context.request.get(`${base}/api/snapshot`)
  expect(response.ok()).toBeTruthy()
  return response.json()
}

try {
  await page.goto(base)
  await expect(page.getByRole('heading', { name: '登录网关控制台' })).toBeVisible()
  await page.screenshot({ path: `${artifactDir}/login.png`, fullPage: true })
  await page.getByLabel('管理密码', { exact: true }).fill((await readFile(passwordFile, 'utf8')).trim())
  await page.getByRole('button', { name: '进入控制台' }).click()
  await expect(page.getByRole('heading', { name: '网关总览.' })).toBeVisible()
  await expect(page.locator('.provider-card')).toHaveCount(4)
  before = (await snapshot()).policy
  expect(before.ready).toBeTruthy()
  expect(before.optimized).toBeTruthy()
  await expect(page.locator('.mode-control > button')).toHaveCount(2)
  await expect(page.getByRole('button', { name: '自动优选与故障转移', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '订阅与节点', exact: true }).click()
  await page.getByLabel('筛选订阅').selectOption(before.provider)
  await page.getByLabel('搜索节点').fill(before.node.replace(/^\[[^\]]+\]\s*/, ''))
  await expect(page.locator('.nodes-table tbody tr')).toHaveCount(1)
  if (before.mode !== 'manual') {
    await page.getByRole('button', { name: '使用此节点', exact: true }).click()
    await expect(page.getByRole('heading', { name: '固定到这个节点？' })).toBeVisible()
    if (readOnly) {
      await page.getByRole('button', { name: '取消', exact: true }).click()
      expect((await snapshot()).policy.mode).toBe(before.mode)
    } else {
      changedPolicy = true
      await page.getByRole('button', { name: '确认使用此节点' }).click()
      await expect(page.locator('.manual-notice')).toBeVisible({ timeout: 15000 })
      expect((await snapshot()).policy.mode).toBe('manual')
      expect((await snapshot()).policy.node).toBe(before.node)
      await page.getByRole('button', { name: '恢复自动', exact: true }).first().click()
      await expect(page.locator('.manual-notice')).toHaveCount(0, { timeout: 15000 })
      expect((await snapshot()).policy.mode).toBe('auto')
    }
  }
  await page.getByRole('button', { name: /^实时连接/ }).click()
  await expect(page.getByLabel('搜索连接')).toBeVisible()
  await page.getByLabel('搜索连接').fill('this-domain-should-not-exist.invalid')
  await expect(page.getByText('没有匹配的连接', { exact: true })).toBeVisible()
  await page.getByLabel('搜索连接').fill('')
  // Read-only refresh on the connections tab must never start node probes.
  await page.getByRole('button', { name: /^实时连接/ }).click()
  await page.route('**/api/snapshot', route => route.abort())
  await page.getByRole('button', { name: '刷新状态' }).click()
  await expect(page.getByText('数据连接中断', { exact: true })).toBeVisible()
  await expect(page.getByText(/最后一次数据/)).toBeVisible()
  await page.unroute('**/api/snapshot')
  await page.getByRole('button', { name: /重试/ }).click()
  await expect(page.getByText('实时连接中', { exact: true })).toBeVisible()
  await expect(page.locator('.toast-message')).toHaveCount(0, { timeout: 6000 })
  await page.getByRole('button', { name: '网关总览', exact: true }).click()
  await page.screenshot({ path: `${artifactDir}/desktop.png`, fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: `${artifactDir}/mobile.png`, fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.getByRole('button', { name: '订阅与节点', exact: true }).click()
  await expect(page.getByLabel('搜索节点')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  expect(pageErrors).toEqual([])
  console.log(`PASS: login, live data, filters, ${readOnly ? 'switch dialog (read-only)' : 'manual/auto switching'}, outage/recovery, desktop and mobile layouts.`)
} finally {
  if (before && changedPolicy) {
    const result = await context.request.post(`${base}/api/policy`, {
      headers: { 'X-Gateway-Request': '1' },
      data: { mode: before.mode, node: before.mode === 'manual' ? before.node : undefined },
    })
    if (!result.ok()) console.error('Original mode could not be restored; check the gateway policy.')
  }
  await browser.close()
}
