// All credential saves are intercepted. Never writes production configuration.
import { chromium, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'
const base = process.env.GATEWAY_TEST_URL || 'http://192.168.188.3:8091'
const browser = await chromium.launch({ headless: true,
  executablePath: process.env.CHROMIUM_PATH || '/home/lcarus/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome', args: ['--no-sandbox'] })
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1080 } })
  expect((await context.request.post(`${base}/api/login`, { data: { password:
    (await readFile(new URL('../../../mihomo/data/gateway-admin-password', import.meta.url), 'utf8')).trim() } })).ok()).toBeTruthy()
  const page = await context.newPage()
  const attempts = []
  await page.route('**/api/platforms/credentials', route => {
    attempts.push(route.request().postDataJSON())
    return route.fulfill({ status: 503, json: { detail: '测试：凭证保存未确认，未写入真实配置' } })
  })
  await page.goto(`${base}/#platforms`)
  await page.getByRole('button', { name: '更新闲鱼凭证', exact: true }).click()
  const values = { _m_h5_tk: 'browser-test_9999999999999', _m_h5_tk_enc: 'browser-enc', cookie2: 'browser-session==', unb: '1' }
  for (const key of Object.keys(values)) {
    await expect(page.getByLabel(`${key} 的值`, { exact: true })).toBeVisible()
    await expect(page.getByLabel(`${key} 的值`, { exact: true })).toHaveJSProperty('required', true)
    await expect(page.getByLabel(`${key} 的值`, { exact: true })).toHaveValue('')
  }
  await page.getByRole('button', { name: '保存并热加载', exact: true }).click()
  expect(attempts).toHaveLength(0)
  for (const [key, value] of Object.entries(values)) await page.getByLabel(`${key} 的值`, { exact: true }).fill(value)
  await page.getByRole('button', { name: '保存并热加载', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('测试：凭证保存未确认')
  expect(attempts[0].updates).toEqual(values)
  await page.getByLabel('更新方式').selectOption('full')
  const full = page.locator('#platform-xianyu_cookie')
  await full.fill('_m_h5_tk=test; unb=1')
  await page.getByRole('button', { name: '保存并热加载', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('_m_h5_tk_enc、cookie2')
  expect(attempts).toHaveLength(1)
  await full.fill(Object.entries(values).map(([k, v]) => `${k}=${v}`).join('; '))
  await page.getByRole('button', { name: '保存并热加载', exact: true }).click()
  await expect.poll(() => attempts.length).toBe(2)
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '更新Reddit凭证', exact: true }).click()
  await expect(page.getByLabel('reddit_session 的值', { exact: true })).toHaveJSProperty('required', true)
  await expect(page.getByText(/尚未验证的字段不统一设为必填/)).toBeVisible()
  await page.getByLabel('reddit_session 的值', { exact: true }).fill('browser-session')
  await page.locator('.credential-additional summary').click()
  const extras = ['token_v2', 'csrf_token', 'session_tracker', 'loid', 'edgebucket', 'csv']
  for (const key of extras) {
    const field = page.getByLabel(`${key} 的值`, { exact: true })
    await expect(field).toHaveValue('')
    await expect(field).toHaveJSProperty('required', false)
    await field.fill(`browser-${key}`)
  }
  await page.getByRole('button', { name: '保存并热加载', exact: true }).click()
  await expect.poll(() => attempts.length).toBe(3)
  for (const key of extras) expect(attempts[2].updates[key]).toBe(`browser-${key}`)
  await page.getByLabel('更新方式').selectOption('full')
  await page.locator('#platform-reddit_cookie').fill('reddit_session=browser-test; extra_cookie=keep')
  await page.getByRole('button', { name: '保存并热加载', exact: true }).click()
  await expect.poll(() => attempts.length).toBe(4)
  expect(attempts[3].updates.reddit_cookie).toContain('extra_cookie=keep')
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '更新Reddit凭证', exact: true }).click()
  await expect(page.getByLabel('reddit_session 的值', { exact: true })).toHaveValue('')
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1080 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await page.screenshot({ path: `../artifacts/required-cookies/reddit-${width}.png`, fullPage: true })
  }
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '更新闲鱼凭证', exact: true }).click()
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1080 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
    await page.screenshot({ path: `../artifacts/required-cookies/xianyu-${width}.png`, fullPage: true })
  }
  console.log('PASS: four required Xianyu fields, empty submission blocked, full import validated, Reddit session required and extra cookies retained. All saves intercepted.')
} finally { await browser.close() }
