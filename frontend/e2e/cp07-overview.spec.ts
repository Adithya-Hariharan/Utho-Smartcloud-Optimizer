import { test, expect, fx } from './fixtures'

type Delta = { key: string; delta_inr: number }
const summary = fx('summary.json')
const forecast = fx('forecast_90.json')
const g = summary.growth_waterfall
const inr = (v: number) => `₹${new Intl.NumberFormat('en-IN').format(v)}`

test.beforeEach(async ({ page }) => {
  await page.goto('/')
})

test('KPI tiles are the five in the plan: bill, trend, waste, potential, CO₂', async ({ page }) => {
  await expect(page.getByTestId('kpi-bill')).toHaveText(inr(summary.monthly_before_inr))
  await expect(page.getByTestId('kpi-growth')).toHaveText(`+${((g.growth_ratio - 1) * 100).toFixed(1)}%`)
  await expect(page.getByTestId('kpi-waste')).toContainText('₹')
  await expect(page.getByTestId('kpi-potential')).toHaveText(`${inr(summary.monthly_before_inr - summary.potential_after_inr)}/mo`)
  await expect(page.getByTestId('kpi-co2')).toContainText(`${new Intl.NumberFormat('en-IN').format(Math.round(forecast.carbon.potential_kg_co2_month))} kg/mo`)
})

test('the monthly bill is the run-rate, identical to Now on Recommendations', async ({ page }) => {
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Recommendations' }).click()
  await expect(page.getByTestId('summary-before')).toContainText(inr(summary.monthly_before_inr))
})

test('growth story comes from /api/summary growth_waterfall', async ({ page }) => {
  const env = (k: string) => (g.by_env as Delta[]).find((x) => x.key === k)?.delta_inr ?? 0
  const share = Math.round(((env('staging') + env('dev')) / (g.last30.total_inr - g.first30.total_inr)) * 100)
  await expect(page.getByTestId('growth-story')).toContainText(`${share}% of that growth is non-prod`)
  await expect(page.getByTestId('growth-story')).toContainText(`${g.new_resources.length} resources created after the first month`)
})

test('bill trend and Bill Growth Explainer render; explainer splits by env, team and new resources', async ({ page }) => {
  await expect(page.getByTestId('bill-trend').locator('canvas')).toHaveCount(1)
  await expect(page.getByTestId('growth-waterfall').locator('canvas')).toHaveCount(1)
  for (const label of ['by team', 'new resources', 'by env']) {
    await page.getByRole('button', { name: label }).click()
    await expect(page.getByRole('button', { name: label })).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByTestId('growth-waterfall').locator('canvas')).toHaveCount(1)
  }
})

test('Monday morning list: 5 low-risk rows, opens the drawer', async ({ page }) => {
  const rows = page.getByTestId('monday-list').locator('tr')
  await expect(rows).toHaveCount(5)
  const first = rows.first()
  const name = (await first.locator('.font-medium').first().textContent())!.trim()
  await expect(first).toContainText('Low risk')
  await first.click()
  await expect(page.getByTestId('resource-drawer').getByRole('heading', { name })).toBeVisible()
})
