import { test, expect, fx } from './fixtures'

const resources = fx('resources.json')
const id = (n: string) => resources.find((r: { name: string }) => r.name === n).resource_id

test('fleet table lists every inventory resource', async ({ page }) => {
  await page.goto('/utilization')
  await expect(page.locator('[data-testid^="util-row-"]')).toHaveCount(resources.length)
  await expect(page.getByTestId('util-count')).toHaveText(`${resources.length} shown`)
})

test('region/env/team/type filters are sent to GET /api/resources; verdict narrows in the browser', async ({ page, api }) => {
  await page.goto('/utilization?type=volume')
  await expect.poll(() => api.calls.some((c) => c.path === '/api/resources' && new URLSearchParams(c.query).get('type') === 'volume')).toBe(true)
  await expect(page.locator('[data-testid^="util-row-"]')).toHaveCount(resources.filter((r: { type: string }) => r.type === 'volume').length)
  await page.getByTestId('filter-verdict').selectOption('reject')
  await expect(page).toHaveURL(/verdict=reject/)
  await expect(page.getByTestId('util-row-vol-growing-10')).toBeVisible()
})

test('low coverage is called out in the table', async ({ page }) => {
  await page.goto('/utilization?q=dev-flaky-18')
  await expect(page.getByTestId('util-row-dev-flaky-18')).toContainText('70%')
  const r = resources.find((x: { name: string }) => x.name === 'dev-flaky-18')
  await expect(page.getByTestId('util-row-dev-flaky-18')).toContainText(`${r.stats.cpu_p99.toFixed(1)}%`)
})

test('heatmap view renders resources × days', async ({ page }) => {
  await page.goto('/utilization')
  await page.getByRole('button', { name: 'heatmap' }).click()
  await expect(page.getByTestId('fleet-heatmap').locator('canvas').first()).toBeVisible()
})

test('row click drills down to the full resource page', async ({ page }) => {
  await page.goto('/utilization?q=prod-batch-07')
  await page.getByTestId('util-row-prod-batch-07').click()
  await expect(page).toHaveURL(new RegExp(`/utilization/${id('prod-batch-07')}$`))
  await expect(page.getByRole('heading', { level: 1, name: 'prod-batch-07' })).toBeVisible()
  for (const c of ['chart-cpu', 'chart-mem', 'chart-net', 'chart-disk', 'how-heatmap']) await expect(page.getByTestId(c).locator('canvas')).toHaveCount(1)
  await expect(page.getByTestId('trace-terminal')).toContainText('veto.recurring_peak')
  await expect(page.getByTestId('dq-report')).toContainText('Coverage')
  await expect(page.getByTestId('features')).toContainText('Days with a 30-min peak > 80%')
  await page.getByRole('button', { name: 'Open decision' }).click()
  await expect(page.getByTestId('resource-drawer')).toBeVisible()
})

test('unknown id shows a not-found page', async ({ page }) => {
  await page.goto('/utilization/vm-nope')
  await expect(page.getByRole('heading', { level: 1, name: 'Resource not found' })).toBeVisible()
})
