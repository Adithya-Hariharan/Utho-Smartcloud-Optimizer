import { test, expect, fx } from './fixtures'

const alerts: { alert_id: string; severity: string; type: string; name: string; why: string; title: string }[] = fx('alerts.json').items

test.beforeEach(async ({ page }) => {
  await page.goto('/alerts')
  await expect(page.getByTestId('alert-list')).toBeVisible()
})

test('every alert is listed, critical first, with severity counts', async ({ page }) => {
  await expect(page.locator('article')).toHaveCount(alerts.length)
  for (const s of ['critical', 'warning', 'info']) await expect(page.getByTestId(`sev-${s}`)).toContainText(String(alerts.filter((a) => a.severity === s).length))
  await expect(page.locator('article').first()).toContainText('Critical')
})

test('possible compromise on dev-sandbox-17: critical, numbers in the why, chart with the window', async ({ page }) => {
  const card = page.getByTestId('alert-possible_compromise-dev-sandbox-17')
  await expect(card).toContainText('Critical')
  await expect(card.getByTestId('alert-why')).toContainText('network out is')
  await expect(card.getByTestId('alert-chart').locator('canvas')).toHaveCount(1)
})

test('capacity alert gives an ETA for prod-api-04', async ({ page }) => {
  await expect(page.getByTestId('alert-capacity-prod-api-04')).toContainText('days to 90%')
})

test('growth-team cost jump names the new resources', async ({ page }) => {
  const jump = alerts.find((a) => a.type === 'team_cost_jump')!
  const card = page.locator('article', { hasText: jump.title })
  await expect(card).toContainText('New resources:')
  await expect(card).toContainText('Team-level')
})

test('severity chip filters the list; resource link opens the drawer', async ({ page }) => {
  await page.getByTestId('sev-critical').click()
  await expect(page).toHaveURL(/severity=critical/)
  await expect(page.locator('article')).toHaveCount(alerts.filter((a) => a.severity === 'critical').length)
  await page.getByTestId('alert-level_shift-prod-worker-05').getByRole('button', { name: 'prod-worker-05' }).click()
  await expect(page.getByTestId('resource-drawer').getByRole('heading', { name: 'prod-worker-05' })).toBeVisible()
})

test('drawer alert links land on the alert', async ({ page }) => {
  const a = alerts.find((x) => x.name === 'prod-orders-08')!
  await page.goto(`/alerts#${a.alert_id}`)
  await expect(page.locator(`#${a.alert_id}`)).toBeInViewport()
})
