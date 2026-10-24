import { test, expect, fx } from './fixtures'

type Rec = { rec_id: string; verdict: string; resource: { name: string; resource_id: string }; target: { plan: string } | null; options: Record<string, { saving_inr: number }>; default_option: string; current: { monthly_inr: number } }
const def: { items: Rec[] } = fx('recommendations/default.json')
const maxPerf: { items: Rec[] } = fx('recommendations/max_performance.json')
const byName = (env: { items: Rec[] }, n: string) => env.items.find((i) => i.resource.name === n)!
const actionable = (r: Rec) => r.verdict === 'recommend' || r.verdict === 'upsize'
const runRate = def.items.reduce((s, i) => s + i.current.monthly_inr, 0)
const inr = (v: number) => `₹${new Intl.NumberFormat('en-IN').format(v)}`

// Pick the F8 cases from the data: one whose target moves, one that stops being actionable,
// and one that is unchanged under Max performance.
const changes = def.items.filter(actionable).map((r) => ({ r, m: byName(maxPerf, r.resource.name) }))
const retargeted = changes.find(({ r, m }) => actionable(m) && r.target && m.target && r.target.plan !== m.target.plan)!
const dropped = changes.find(({ m }) => !actionable(m))!
const unchanged = changes.find(({ r, m }) => actionable(m) && r.target && r.target.plan === m.target?.plan && Object.keys(r.options).join() === Object.keys(m.options).join())!

test('preset switch resets only decisions whose target changed, and says why (F8)', async ({ page }) => {
  await page.goto('/recommendations')
  for (const { r } of [retargeted, dropped, unchanged]) await page.getByRole('button', { name: `Accept ${r.resource.name}` }).click()
  await page.getByTestId('preset-select').selectOption('max_performance')
  const toast = page.getByTestId('toast')
  await expect(toast).toContainText('2 decisions reset')
  await expect(toast).toContainText(`${retargeted.r.resource.name}: target changed ${retargeted.r.target!.plan} → ${retargeted.m.target!.plan}`)
  await expect(toast).toContainText(`${dropped.r.resource.name}: now ${dropped.m.verdict}`)
  const keep = unchanged.m
  await expect(page.getByTestId('summary-after')).toContainText(inr(runRate - keep.options[keep.default_option].saving_inr))
  await expect(page.getByTestId(`rec-row-${keep.resource.name}`).getByTestId('decision-status')).toContainText('Accepted')
})

test('switching back with still-valid decisions resets nothing', async ({ page }) => {
  await page.goto('/recommendations')
  await page.getByRole('button', { name: 'Accept dev-web-03' }).click()
  await page.getByTestId('preset-select').selectOption('balanced')
  await page.getByTestId('preset-select').selectOption('default')
  await expect(page.getByTestId('rec-row-dev-web-03').getByTestId('decision-status')).toContainText('Accepted')
  await expect(page.getByTestId('toast')).toHaveCount(0)
})

test('export posts the accepted decisions to the backend and downloads its file', async ({ page, api }) => {
  await page.goto('/recommendations')
  await expect(page.getByTestId('export-button')).toBeDisabled()
  await page.getByRole('button', { name: 'Accept dev-web-03' }).click()
  await page.getByRole('button', { name: 'Accept vol-orphan-11' }).click()
  await expect(page.getByTestId('export-button')).toContainText('(2)')

  for (const [label, format, filename] of [
    ['CSV (finance)', 'csv', 'smartcloud-accepted.csv'],
    ['Markdown (ticket)', 'md', 'smartcloud-accepted.md'],
    ['apply.sh (dry run)', 'sh', 'apply.sh'],
    ['Terraform snippet', 'tf', 'smartcloud-plan.tf'],
  ] as const) {
    await page.getByTestId('export-button').click()
    const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('menuitem', { name: label }).click()])
    expect(dl.suggestedFilename()).toBe(filename)
    const call = api.calls.filter((c) => c.method === 'POST' && c.path === '/api/export').at(-1)!
    expect(call.body).toEqual({
      format,
      accepted: expect.arrayContaining([
        { rec_id: byName(def, 'dev-web-03').rec_id, option_key: 'resize+schedule' },
        { rec_id: byName(def, 'vol-orphan-11').rec_id, option_key: byName(def, 'vol-orphan-11').default_option },
      ]),
    })
    expect((call.body!.accepted as unknown[]).length).toBe(2)
  }
})
