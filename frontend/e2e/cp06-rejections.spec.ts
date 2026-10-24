import { test, expect, fx } from './fixtures'

type Item = { verdict: string; reason_code: string; resource: { name: string; type: string }; evidence: { metrics: { cpu: { mean: number } | null } | null; naive: { saving_inr: number } | null } }
const recs = fx('recommendations/default.json')
const items: Item[] = recs.items
const isKept = (i: Item) =>
  ['reject', 'flag', 'exclude'].includes(i.verdict) ||
  (i.verdict === 'healthy' && i.reason_code === 'RIGHT_SIZED' && i.resource.type === 'vm' && (i.evidence.metrics?.cpu?.mean ?? 100) < 20)
const kept = items.filter(isKept)
const inr = (v: number) => `₹${new Intl.NumberFormat('en-IN').format(v)}`

test.beforeEach(async ({ page }) => {
  await page.goto('/kept')
})

test('headline counts match the data', async ({ page }) => {
  await expect(page.getByTestId('kept-count')).toHaveText(String(kept.length))
  await expect(page.getByTestId('kept-vetoed')).toHaveText(String(items.filter((i) => i.verdict === 'reject').length))
  const naive = kept.reduce((s, i) => s + (i.evidence.naive?.saving_inr ?? 0), 0)
  await expect(page.getByTestId('kept-naive')).toContainText(inr(naive))
})

test('groups cover every kept resource exactly once', async ({ page }) => {
  await expect(page.getByTestId('kept-count')).toHaveText(String(kept.length))
  const counts = await page.getByTestId('group-count').allTextContents()
  expect(counts.reduce((s, c) => s + Number(c), 0)).toBe(kept.length)
})

test('recurring-peak group holds the nightly batch, with its veto number', async ({ page }) => {
  const group = page.getByTestId('kept-group-recurring')
  await expect(group.getByTestId('group-count')).toHaveText(String(items.filter((i) => i.reason_code === 'VETO_RECURRING_PEAK').length))
  await group.getByRole('button', { name: /Show \d+ more/ }).click()
  const row = group.getByTestId('kept-row-prod-batch-07')
  const batch = items.find((i) => i.resource.name === 'prod-batch-07')!
  await expect(row).toContainText(`${batch.evidence.metrics!.cpu!.mean.toFixed(1)}%`)
  await expect(row.getByTestId('kept-because')).toContainText('days with a 30-min peak > 80%: 30')
  await expect(row).toContainText('min > 90%')
})

test('memory veto shows the value against the 70% rule', async ({ page }) => {
  const row = page.getByTestId('kept-group-memory').getByTestId('kept-row-prod-cache-04')
  const cache = items.find((i) => i.resource.name === 'prod-cache-04') as unknown as { veto: { value: number } }
  await expect(row.getByTestId('kept-because')).toContainText(cache.veto.value.toLocaleString('en-IN', { maximumFractionDigits: 1 }))
  await expect(row.getByTestId('kept-because')).toContainText('> 70')
})

test('search narrows to one resource and expands its group; clicking opens the drawer', async ({ page }) => {
  await page.getByLabel('Search by name').fill('prod-gateway-03')
  await expect(page.locator('[data-testid^="kept-row-"]')).toHaveCount(1)
  await page.getByTestId('kept-row-prod-gateway-03').click()
  await expect(page.getByTestId('resource-drawer').getByRole('heading', { name: 'prod-gateway-03' })).toBeVisible()
  await expect(page.getByTestId('veto')).toContainText('Network')
})

test('quiet-but-peaky healthy machines are listed as "peaks need the size"', async ({ page }) => {
  const n = kept.filter((i) => i.verdict === 'healthy').length
  if (n === 0) test.skip()
  await expect(page.getByTestId('kept-group-peaks').getByTestId('group-count')).toHaveText(String(n))
})
