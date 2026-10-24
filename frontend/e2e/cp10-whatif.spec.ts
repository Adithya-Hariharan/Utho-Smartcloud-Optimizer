import { test, expect } from './fixtures'

test('default policy: dev off 20:00–08:00 + weekends = 108 h, dev-etl-04 would break', async ({ page }) => {
  await page.goto('/what-if')
  await expect(page.getByTestId('wi-off')).toHaveText('108 h')
  const etl = page.getByTestId('wi-row-dev-etl-04')
  await expect(etl.getByTestId('wi-status')).toHaveText('Would break')
  await expect(etl).toContainText('01:00–03:00')
  await expect(page.getByTestId('wi-row-dev-web-03').getByTestId('wi-status')).toHaveText('Safe')
  await expect(page.getByText(/breaks [1-9]\d* VMs?/)).toBeVisible()
})

test('weekend-only load tests break only when weekends are off; keep_running is excluded', async ({ page }) => {
  await page.goto('/what-if')
  await page.getByTestId('wi-env').selectOption('staging')
  await expect(page).toHaveURL(/env=staging/)
  await expect(page.getByTestId('wi-row-staging-load-06').getByTestId('wi-status')).toHaveText('Would break')
  await expect(page.getByTestId('wi-row-staging-demo-10').getByTestId('wi-status')).toHaveText('Excluded')
  await page.getByTestId('wi-weekends').uncheck()
  await expect(page.getByTestId('wi-row-staging-load-06').getByTestId('wi-status')).toHaveText('Safe')
  await expect(page.getByTestId('wi-off')).toHaveText('84 h')
})

test('state lives in the URL; rows open the drawer', async ({ page }) => {
  await page.goto('/what-if?env=dev&from=22&to=6&weekends=0')
  await expect(page.getByTestId('wi-from')).toHaveValue('22')
  await expect(page.getByTestId('wi-off')).toHaveText('56 h')
  await page.getByTestId('wi-row-dev-support-05').click()
  await expect(page.getByTestId('resource-drawer').getByRole('heading', { name: 'dev-support-05' })).toBeVisible()
})

test('sends the request body from the plan to POST /api/whatif', async ({ page, api }) => {
  await page.goto('/what-if')
  await expect(page.getByTestId('wi-off')).toHaveText('108 h')
  const call = api.calls.find((c) => c.method === 'POST' && c.path === '/api/whatif')!
  expect(call.body).toEqual({ env: 'dev', off: '20:00-08:00', weekends: true })
})
