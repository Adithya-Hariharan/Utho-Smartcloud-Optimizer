import { test, expect, fx } from './fixtures'

const sc = fx('scorecard.json')

test.beforeEach(async ({ page }) => {
  await page.goto('/assumptions')
  await expect(page.getByTestId('pricing-table')).toBeVisible()
})

test('prices, thresholds and presets are rendered from the config data', async ({ page }) => {
  await expect(page.getByTestId('pricing-table')).toContainText('₹6,690')
  await expect(page.getByTestId('pricing-table')).toContainText('Utho Basic 4')
  await expect(page.getByTestId('thresholds-table')).toContainText('Saving floor')
  await expect(page.getByTestId('thresholds-table')).toContainText('strict < / >')
  await expect(page.getByTestId('presets-table').locator('tr[aria-current="true"]')).toContainText('Default')
})

test('scorecard comes from the API: verdict match, zero unsafe downsizes, mock caveat', async ({ page }) => {
  await expect(page.getByTestId('sc-accuracy')).toHaveText(`${sc.correct}/${sc.total}`)
  await expect(page.getByTestId('sc-unsafe')).toHaveText(String(sc.unsafe_downsizes))
  expect(sc.unsafe_downsizes, 'the engine must never propose an unsafe downsize').toBe(0)
  await expect(page.getByTestId('scorecard-mock-note')).toBeVisible()
  await expect(page.getByTestId('sc-verdicts')).toContainText(/recommend/i)
})

test('scorecard is the Default preset (GET /api/scorecard) with precision and recall per archetype', async ({ page, api }) => {
  await page.getByTestId('preset-select').selectOption('max_performance')
  await expect(page.getByTestId('sc-accuracy')).toHaveText(`${sc.correct}/${sc.total}`)
  expect(api.calls.filter((c) => c.path === '/api/scorecard').every((c) => c.query === '')).toBe(true)
  await expect(page.locator('th', { hasText: 'Precision' })).toHaveCount(2)
  await expect(page.locator('th', { hasText: 'Recall' })).toHaveCount(2)
})
