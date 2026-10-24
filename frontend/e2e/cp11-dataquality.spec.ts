import { test, expect, fx } from './fixtures'

type Row = { name: string; type: string; coverage: number | null }
const dq = fx('data-quality.json')
const worst = (dq.resources as Row[]).filter((r) => r.type === 'vm' && r.coverage !== null).sort((a, b) => a.coverage! - b.coverage!)[0]

test.beforeEach(async ({ page }) => {
  await page.goto('/data-quality')
  await expect(page.getByTestId('dq-reconcile')).toBeVisible()
})

test('cleaning totals come from the API', async ({ page }) => {
  await expect(page.getByTestId('dq-dupes')).toHaveText(String(dq.totals.duplicates))
  await expect(page.getByTestId('dq-oor')).toHaveText(String(dq.totals.out_of_range))
  await expect(page.getByTestId('dq-jitter')).toHaveText(String(dq.totals.irregular_ts))
  await expect(page.getByTestId('dq-flat')).toHaveText(String(dq.totals.flatline_slots / 12))
  await expect(page.getByTestId('dq-rows')).toHaveText(new Intl.NumberFormat('en-IN').format(dq.totals.metric_rows))
})

test('every injected fault E1–E10 and D9 is reconciled as handled', async ({ page }) => {
  const rows = page.getByTestId('dq-reconcile').locator('tbody tr')
  await expect(rows).toHaveCount(dq.checks.length)
  await expect(page.getByTestId('dq-ok')).toHaveCount(dq.checks.filter((c: { ok: boolean }) => c.ok).length)
  expect(dq.checks.every((c: { ok: boolean }) => c.ok), 'every injected fault must be detected').toBe(true)
  await expect(page.getByTestId('dq-E1')).toContainText('longest gap 6')
  await expect(page.getByTestId('dq-E6')).toContainText('excluded')
})

test('inventory reconciliation lists the ghost series and the unmonitored VM', async ({ page }) => {
  await expect(page.getByTestId('dq-ghost')).toContainText('vm-ghost-99')
  await expect(page.getByTestId('dq-nometrics')).toContainText('prod-nomon-13')
  await page.getByTestId('dq-nometrics').getByRole('button', { name: 'prod-nomon-13' }).click()
  await expect(page.getByTestId('resource-drawer').getByRole('heading', { name: 'prod-nomon-13' })).toBeVisible()
})

test('coverage table starts with the worst VM', async ({ page }) => {
  const first = page.getByTestId('dq-coverage').locator('tbody tr').first()
  await expect(first).toContainText(worst.name)
  await expect(first).toContainText(`${(worst.coverage! * 100).toFixed(1)}%`)
})
