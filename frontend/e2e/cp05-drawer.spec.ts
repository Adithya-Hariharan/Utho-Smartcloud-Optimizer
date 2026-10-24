import { test, expect, fx } from './fixtures'

const recs = fx('recommendations/default.json')
const id = (n: string) => recs.items.find((i: { resource: { name: string } }) => i.resource.name === n).resource.resource_id
const inr = (v: number) => `₹${new Intl.NumberFormat('en-IN').format(v)}`

test('clicking a row opens the drawer; Escape closes it', async ({ page }) => {
  await page.goto('/recommendations')
  await page.getByTestId('rec-row-dev-web-03').click()
  const drawer = page.getByTestId('resource-drawer')
  await expect(drawer.getByRole('heading', { name: 'dev-web-03' })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`r=${id('dev-web-03')}`))
  await page.keyboard.press('Escape')
  await expect(drawer).toHaveCount(0)
})

test('dev-web-03: every option with its formula, combined option cheaper than the sum, replay passes', async ({ page }) => {
  await page.goto(`/recommendations?r=${id('dev-web-03')}`)
  const drawer = page.getByTestId('resource-drawer')
  const table = drawer.getByTestId('options-table')
  for (const k of ['none', 'resize', 'schedule', 'resize+schedule']) await expect(table.getByTestId(`option-${k}`)).toBeVisible()
  await expect(table.getByTestId('option-resize+schedule').getByTestId('formula')).toContainText('× 50/168 h on')
  await expect(drawer.getByTestId('schedule-windows')).toContainText('Mon–Thu 19:00–09:00 (next day)')
  await expect(drawer.getByTestId('replay-attempts')).toContainText('B2: 0 min > 90%')
  await expect(drawer.getByTestId('replay-chart').locator('canvas')).toHaveCount(1)
  await expect(drawer.getByTestId('evidence-table')).toContainText('CPU %')
  // accept from the drawer: the option row highlights and the total moves
  await drawer.getByRole('button', { name: 'Accept dev-web-03' }).click()
  const saving = recs.items.find((i: { resource: { name: string } }) => i.resource.name === 'dev-web-03').options['resize+schedule'].saving_inr
  await expect(drawer.getByTestId('decision-status')).toContainText('Accepted')
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('summary-saving')).toContainText(inr(saving))
})

test('prod-batch-07: kept, with the naive resize and its failing replay shown', async ({ page }) => {
  await page.goto(`/recommendations?r=${id('prod-batch-07')}`)
  const drawer = page.getByTestId('resource-drawer')
  await expect(drawer.getByText('Checked & kept')).toBeVisible()
  await expect(drawer.getByTestId('drawer-reason')).toContainText('02:00')
  await expect(drawer.getByTestId('naive-box')).toContainText('min above 90% CPU')
  await expect(drawer.getByTestId('naive-box')).toContainText('We kept it')
  await expect(drawer.getByTestId('veto')).toContainText('Recurring Peak')
  await expect(drawer.getByTestId('replay-chart').locator('canvas')).toHaveCount(1)
  await drawer.getByRole('tab', { name: 'trace' }).click()
  await expect(drawer.getByTestId('trace-terminal')).toContainText('veto.recurring_peak')
})

test('charts tab: prod-api-02 lists its 6-hour gap as missing, not zero', async ({ page }) => {
  await page.goto(`/recommendations?r=${id('prod-api-02')}&tab=charts`)
  const drawer = page.getByTestId('resource-drawer')
  await expect(drawer.getByTestId('chart-cpu').locator('canvas')).toHaveCount(1)
  await expect(drawer.getByTestId('chart-mem').locator('canvas')).toHaveCount(1)
  await expect(drawer.getByTestId('how-heatmap').locator('canvas')).toHaveCount(1)
  await expect(drawer.getByTestId('gap-list')).toContainText('2 Oct, 10:00 IST for 6 h')
})

test('charts tab: dev-api-16 stuck agent is shown as a flatline gap', async ({ page }) => {
  await page.goto(`/recommendations?r=${id('dev-api-16')}&tab=charts`)
  await expect(page.getByTestId('gap-list')).toContainText('stuck agent')
})

test('volume and IP drawers degrade gracefully', async ({ page }) => {
  await page.goto(`/recommendations?r=${id('vol-orphan-11')}&tab=charts`)
  await expect(page.getByTestId('chart-disk').locator('canvas')).toHaveCount(1)
  await page.goto(`/recommendations?r=${id('ip-unused-03')}&tab=charts`)
  await expect(page.getByText('Public IPs have no metrics.')).toBeVisible()
  await page.goto(`/recommendations?r=${id('prod-nomon-13')}&tab=charts`)
  await expect(page.getByTestId('no-metrics')).toBeVisible()
})

test('script tab: the backend builds the apply script for this one change (sh and Terraform)', async ({ page, api }) => {
  await page.goto(`/recommendations?r=${id('dev-web-03')}&tab=script`)
  const rec = recs.items.find((i: { resource: { name: string } }) => i.resource.name === 'dev-web-03')
  await expect(page.getByTestId('script-text')).toContainText(`${rec.rec_id} resize+schedule`)
  await page.getByRole('button', { name: 'Terraform' }).click()
  await expect(page.getByTestId('script-text')).toContainText('stub export (tf)')
  const bodies = api.calls.filter((c) => c.path === '/api/export').map((c) => c.body)
  expect(bodies).toContainEqual({ accepted: [{ rec_id: rec.rec_id, option_key: 'resize+schedule' }], format: 'sh' })
  expect(bodies).toContainEqual({ accepted: [{ rec_id: rec.rec_id, option_key: 'resize+schedule' }], format: 'tf' })
})

test('charts: one request per metric (hourly), 5-minute on demand, percentile lines explained', async ({ page, api }) => {
  await page.goto(`/recommendations?r=${id('prod-batch-07')}&tab=charts`)
  await expect(page.getByTestId('chart-cpu').locator('canvas')).toHaveCount(1)
  await expect(page.getByText('dotted lines are the p50 / p95 / p99 from the engine')).toBeVisible()
  const cpu = recs.items.find((i: { resource: { name: string } }) => i.resource.name === 'prod-batch-07').evidence.metrics.cpu
  await expect(page.getByTestId('chart-cpu-percentiles')).toHaveText(`dotted: p50 ${cpu.p50.toFixed(1)} · p95 ${cpu.p95.toFixed(1)} · p99 ${cpu.p99.toFixed(1)}`)
  const q = (step: string) => api.calls.filter((c) => c.path.endsWith('/metrics') && new URLSearchParams(c.query).get('step') === step).map((c) => new URLSearchParams(c.query).get('metric'))
  expect(q('1h').sort()).toEqual(['cpu', 'disk_used', 'mem', 'net_out'])
  await page.getByRole('button', { name: '5-minute' }).click()
  await expect.poll(() => q('5m').sort()).toEqual(['cpu', 'disk_used', 'mem', 'net_out'])
  await expect(page.getByTestId('chart-cpu').locator('canvas')).toHaveCount(1)
})
