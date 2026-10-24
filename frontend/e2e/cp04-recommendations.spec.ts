import { test, expect, fx } from './fixtures'

// Expected numbers come from the same exported data the app reads.
const recs = fx('recommendations/default.json')
const by = (n: string) => recs.items.find((i: { resource: { name: string } }) => i.resource.name === n)
const runRate: number = recs.items.reduce((s: number, i: { current: { monthly_inr: number } }) => s + i.current.monthly_inr, 0)
const inr = (v: number) => `₹${new Intl.NumberFormat('en-IN').format(v)}`

test.beforeEach(async ({ page }) => {
  await page.goto('/recommendations')
  await expect(page.getByTestId('recs-table')).toBeVisible()
})

test('summary starts at the run-rate with nothing accepted', async ({ page }) => {
  await expect(page.getByTestId('summary-before')).toContainText(inr(runRate))
  await expect(page.getByTestId('summary-after')).toContainText(inr(runRate))
  await expect(page.getByTestId('summary-belowfloor')).toContainText('1 item')
  await expect(page.getByTestId('summary-potential')).toContainText('%')
})

test('lists only recommend verdicts, with dev-web-03 as resize + schedule', async ({ page }) => {
  const n = recs.items.filter((i: { verdict: string }) => i.verdict === 'recommend').length
  await expect(page.locator('[data-testid^="rec-row-"]')).toHaveCount(n + 1) // + the upsize row in Risk fixes
  const row = page.getByTestId('rec-row-dev-web-03')
  await expect(row).toContainText('Resize B4 → B2 + schedule')
  await expect(row.getByTestId('row-saving')).toHaveText(inr(by('dev-web-03').options['resize+schedule'].saving_inr))
  await expect(page.getByTestId('rec-row-prod-batch-07')).toHaveCount(0)
})

test('accepting dev-web-03 moves the total by exactly the combined option, and survives reload', async ({ page }) => {
  const saving = by('dev-web-03').options['resize+schedule'].saving_inr
  await page.getByRole('button', { name: 'Accept dev-web-03' }).click()
  await expect(page.getByTestId('summary-after')).toContainText(inr(runRate - saving))
  await expect(page.getByTestId('summary-saving')).toContainText(inr(saving))
  await page.reload()
  await expect(page.getByTestId('summary-after')).toContainText(inr(runRate - saving))
  await expect(page.getByTestId('rec-row-dev-web-03').getByTestId('decision-status')).toContainText('Accepted')
})

test('choosing a single option uses that option only; undo restores the total', async ({ page }) => {
  const r = by('dev-web-03')
  const row = page.getByTestId('rec-row-dev-web-03')
  await row.getByTestId('option-select').selectOption('resize')
  await page.getByRole('button', { name: 'Accept dev-web-03' }).click()
  await expect(page.getByTestId('summary-after')).toContainText(inr(runRate - r.options.resize.saving_inr))
  await page.getByRole('button', { name: 'Undo decision for dev-web-03' }).click()
  await expect(page.getByTestId('summary-after')).toContainText(inr(runRate))
})

test('rejecting leaves the total unchanged', async ({ page }) => {
  await page.getByRole('button', { name: 'Reject dev-web-03' }).click()
  await expect(page.getByTestId('rec-row-dev-web-03').getByTestId('decision-status')).toHaveText('Rejected')
  await expect(page.getByTestId('summary-after')).toContainText(inr(runRate))
})

test('upsize sits in Risk fixes and its cost is shown on its own line', async ({ page }) => {
  const cost = -by('prod-search-02').options.upsize.saving_inr
  const fixes = page.getByTestId('risk-fixes')
  await expect(fixes.getByTestId('rec-row-prod-search-02')).toBeVisible()
  await page.getByRole('button', { name: 'Accept prod-search-02' }).click()
  await expect(page.getByTestId('summary-riskfixes')).toContainText(inr(cost))
  await expect(page.getByTestId('summary-after')).toContainText(inr(runRate + cost))
})

// Blocked by a data issue: in data 7b73730 the only service group (prod-web-11a/b/c) can no longer be
// resized, so no group row is shown. Re-enable when the data owner fixes the data or the truth label.
test.fixme('service group collapses into one group row sized on the busiest member', async ({ page }) => {
  const group = page.getByTestId('group-row-web-frontend')
  await expect(group).toContainText('3 VMs')
  await expect(group).toContainText('prod-web-11b')
  await group.getByRole('button', { name: 'Accept group' }).click()
  const total = ['prod-web-11a', 'prod-web-11b', 'prod-web-11c'].reduce((s, n) => s + by(n).options[by(n).default_option].saving_inr, 0)
  await expect(page.getByTestId('summary-saving')).toContainText(inr(total))
})

test('filters live in the URL and narrow the table', async ({ page }) => {
  await page.getByTestId('filter-env').selectOption('dev')
  await expect(page).toHaveURL(/env=dev/)
  const names = await page.locator('[data-testid="recs-table"] [data-testid^="rec-row-"]').evaluateAll((els) => els.map((e) => e.getAttribute('data-testid')))
  const expected = recs.items
    .filter((i: { verdict: string; resource: { env: string } }) => i.verdict === 'recommend' && i.resource.env === 'dev')
    .map((i: { resource: { name: string } }) => `rec-row-${i.resource.name}`)
  expect(names.length).toBeGreaterThan(0)
  expect([...names].sort()).toEqual([...expected].sort())
  await page.reload()
  await expect(page.getByTestId('filter-env')).toHaveValue('dev')
})

test('accept all low-risk accepts only Low-risk rows', async ({ page }) => {
  const low = recs.items.filter((i: { verdict: string; risk: { level: string } | null }) => i.verdict === 'recommend' && i.risk?.level === 'Low')
  const saving = low.reduce((s: number, i: { options: Record<string, { saving_inr: number }>; default_option: string }) => s + i.options[i.default_option].saving_inr, 0)
  await page.getByTestId('accept-low-risk').click()
  await expect(page.getByTestId('summary-saving')).toContainText(inr(saving))
  await page.getByTestId('reset-decisions').click()
  await expect(page.getByTestId('summary-after')).toContainText(inr(runRate))
})
