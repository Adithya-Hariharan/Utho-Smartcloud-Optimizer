import { test, expect, API_ROUTE } from './fixtures'
import { resolveFallback } from '../fallback/resolve'

const pages = [
  ['/', 'Overview'],
  ['/recommendations', 'Recommendations'],
  ['/kept', 'Checked & kept'],
  ['/utilization', 'Utilization'],
  ['/alerts', 'Alerts'],
  ['/what-if', 'What-if'],
  ['/forecast', 'Forecast & Green'],
  ['/data-quality', 'Data quality'],
  ['/assumptions', 'Assumptions'],
] as const

test('every route renders its page title', async ({ page }) => {
  for (const [path, title] of pages) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
  }
})

test('sidebar navigates between pages', async ({ page }) => {
  await page.goto('/')
  const nav = page.getByRole('navigation', { name: 'Main' })
  for (const [path, title] of pages.slice(1)) {
    await nav.getByRole('link', { name: title }).click()
    await expect(page).toHaveURL(new RegExp(`${path}$`))
    await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
  }
})

test('header shows data window, mock banner and preset; preset persists across reload', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('data-window')).toHaveText('Data: 20 Sep – 19 Oct 2026')
  await expect(page.getByText('Times in IST · prices illustrative')).toHaveCount(0)
  await expect(page.getByText(/target \d+% \/ \d+% · replay/)).toHaveCount(0)
  await expect(page.getByTestId('mock-banner')).toBeVisible()
  const preset = page.getByTestId('preset-select')
  await expect(preset).toHaveValue('default')
  await preset.selectOption('balanced')
  await page.reload()
  await expect(page.getByTestId('preset-select')).toHaveValue('balanced')
})

test('unknown routes fall back to Overview', async ({ page }) => {
  await page.goto('/no-such-page')
  await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
})

test('the app gets its data from /api only (no static data files)', async ({ page }) => {
  const dataRequests: string[] = []
  page.on('request', (r) => {
    if (['fetch', 'xhr'].includes(r.resourceType())) dataRequests.push(new URL(r.url()).pathname)
  })
  for (const path of ['/', '/recommendations', '/kept', '/utilization', '/alerts', '/what-if', '/forecast', '/data-quality', '/assumptions']) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  }
  await page.waitForLoadState('networkidle')
  expect(dataRequests.length).toBeGreaterThan(0)
  for (const p of dataRequests) expect(p, 'every data request must go to the backend').toMatch(/^\/api\//)
})

test('when the backend is down, pages say so instead of rendering stale or fake data', async ({ page }) => {
  await page.route(API_ROUTE, (route) => route.fulfill({ status: 502, body: 'Bad Gateway' }))
  await page.goto('/recommendations')
  await expect(page.getByTestId('api-error').first()).toContainText("backend isn't reachable")
})

test('fallback data is labelled, and the app switches to the backend by itself when it comes up', async ({ page }) => {
  // the dev server marks fallback answers with X-Data-Source: fallback and reports the backend on /api/__health
  let backendUp = false
  await page.route(API_ROUTE, async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/__health') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ backend: backendUp }) })
    const body = route.request().postData() ? JSON.parse(route.request().postData()!) : null
    const r = resolveFallback(route.request().method(), url, body)!
    return route.fulfill({ status: r.status, contentType: r.contentType, body: r.body, headers: { ...r.headers, ...(backendUp ? {} : { 'X-Data-Source': 'fallback' }) } })
  })
  await page.goto('/recommendations')
  await expect(page.getByTestId('fallback-banner')).toContainText('backend offline')
  await expect(page.getByTestId('mock-banner')).toHaveCount(0)

  backendUp = true
  await expect(page.getByTestId('toast')).toContainText('Backend connected', { timeout: 10_000 })
  await expect(page.getByTestId('fallback-banner')).toHaveCount(0)
  await expect(page.getByTestId('recs-table')).toBeVisible()
})
