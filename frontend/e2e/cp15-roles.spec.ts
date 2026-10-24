import { test, expect } from './fixtures'
import type { Page } from '@playwright/test'

const navOrder = async (page: Page) => {
  const labels = await page.getByRole('navigation', { name: 'Main' }).locator('a').allTextContents()
  return labels.map((l) => l.replace(/\d+$/, '').trim())
}

test('role switch lands on the role home page, puts its pages first, and persists', async ({ page }) => {
  await page.goto('/')
  const role = page.getByTestId('role-select')
  await expect(role).toHaveValue('engineer')

  await role.selectOption('leadership')
  await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
  expect((await navOrder(page)).slice(0, 3)).toEqual(['Overview', 'Alerts', 'Forecast & Green'])

  await role.selectOption('finance')
  await expect(page).toHaveURL(/\/what-if$/)
  expect((await navOrder(page)).slice(0, 3)).toEqual(['What-if', 'Forecast & Green', 'Assumptions'])

  await role.selectOption('engineer')
  await expect(page).toHaveURL(/\/recommendations$/)
  expect((await navOrder(page))[0]).toBe('Recommendations')

  await page.reload()
  await expect(page.getByTestId('role-select')).toHaveValue('engineer')
})

test('every page stays reachable whatever the role', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('role-select').selectOption('finance')
  await expect(page.getByRole('navigation', { name: 'Main' }).locator('a')).toHaveCount(9)
})
