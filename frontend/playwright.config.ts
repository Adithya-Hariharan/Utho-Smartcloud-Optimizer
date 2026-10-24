import { defineConfig, devices } from '@playwright/test'

// Runs against the dev server on :5173. If you already have `npm run dev` open, it is reused.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  workers: 4,
  retries: 0,
  use: {
    baseURL: 'http://localhost:5173',
    viewport: { width: 1366, height: 768 },
    timezoneId: 'UTC', // charts must still label IST correctly on a non-IST machine
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 768 } } }],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 60_000,
  },
})
