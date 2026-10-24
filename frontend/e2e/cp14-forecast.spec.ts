import { test, expect, fx } from './fixtures'

const forecast = fx('forecast_90.json')
const recs = fx('recommendations/default.json')
const fmt = (v: number) => new Intl.NumberFormat('en-IN').format(Math.round(v))

test('Forecast & Green: 90-day forecast from GET /api/forecast?days=90', async ({ page, api }) => {
  await page.goto('/forecast')
  await expect(page.getByTestId('forecast-chart').locator('canvas')).toHaveCount(1)
  expect(api.calls.some((c) => c.path === '/api/forecast' && c.query === '?days=90')).toBe(true)
  await expect(page.getByTestId('fc-co2')).toHaveText('0 kg/mo')
})

test('accepting a change moves the forecast and the energy / CO₂ saved by exactly its option', async ({ page }) => {
  const rec = recs.items.find((i: { resource: { name: string } }) => i.resource.name === 'dev-web-03')
  const c = forecast.carbon.by_option[rec.rec_id]['resize+schedule']
  await page.goto('/recommendations')
  await page.getByRole('button', { name: 'Accept dev-web-03' }).click()
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Forecast & Green' }).click()
  await expect(page.getByTestId('fc-kwh')).toHaveText(`${fmt(c.kwh_month)} kWh/mo`)
  await expect(page.getByTestId('fc-co2')).toHaveText(`${fmt(c.kg_co2_month)} kg/mo`)
  await expect(page.getByText(`saves ₹${new Intl.NumberFormat('en-IN').format(rec.options['resize+schedule'].saving_inr)}/month`)).toBeVisible()
})
