import { test as base, expect, type Route } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { FALLBACK_DIR, endpointFor, fileFor, resolveFallback } from '../fallback/resolve'

// The app only calls the backend. In tests, the backend is stubbed INSIDE the browser under
// test: every /api/* request is answered by the same resolver the dev-server fallback uses
// (fallback/resolve.ts, data in fallback/api/). Nothing in the app knows about these files.
//
// E2E_LIVE=1 turns the stub off: requests go through the Vite proxy to the real API, and
// fx() reads the expected values from that API instead of the files.

export const LIVE = process.env.E2E_LIVE === '1'
/** backend calls only: paths starting with /api/ (not Vite modules such as /src/api/data.ts) */
export const API_ROUTE = (url: URL) => url.pathname.startsWith('/api/')
const API = process.env.VITE_API_URL ?? 'http://localhost:8000'

/** Expected data for assertions: the fallback file, or (E2E_LIVE=1) the same endpoint on the real API. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function fx<T = any>(file: string): T {
  if (!LIVE) return JSON.parse(readFileSync(FALLBACK_DIR + file, 'utf8')) as T
  const url = API + endpointFor(file)
  const out = execFileSync(process.execPath, ['-e', `fetch(${JSON.stringify(url)}).then(r=>r.text()).then(t=>process.stdout.write(t))`], { encoding: 'utf8' })
  return JSON.parse(out) as T
}

export interface ApiCall { method: string; path: string; query: string; body: Record<string, unknown> | null }

export const test = base.extend<{ api: { calls: ApiCall[] }; consoleGuard: void }>({
  api: [
    async ({ page }, use) => {
      const calls: ApiCall[] = []
      const missing: string[] = []
      if (!LIVE) {
        await page.route(API_ROUTE, async (route: Route) => {
          const req = route.request()
          const url = new URL(req.url())
          const body = req.postData() ? (JSON.parse(req.postData()!) as Record<string, unknown>) : null
          calls.push({ method: req.method(), path: url.pathname, query: url.search, body })
          const r = resolveFallback(req.method(), url, body)
          if (!r) {
            const file = fileFor(req.method(), url, body)
            missing.push(`${req.method()} ${url.pathname}${url.search}${file ? `  (expected fallback/api/${file})` : ''}`)
            return route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"no fallback data"}' })
          }
          return route.fulfill({ status: r.status, contentType: r.contentType, headers: r.headers, body: r.body })
        })
      }
      await use({ calls })
      expect(missing, 'the app called endpoints with no fallback data: add them in docs/reference/mock_engine.py').toEqual([])
    },
    { auto: true },
  ],
  // Every test fails if the page logs a console error or throws. Font CDN failures are ignored
  // so the suite also passes offline; a stubbed 404 is reported by the api fixture instead.
  consoleGuard: [
    async ({ page }, use) => {
      const errors: string[] = []
      page.on('console', (m) => {
        const text = m.text() + (m.location().url ?? '')
        if (m.type() !== 'error' || /fonts\.(googleapis|gstatic)/.test(text)) return
        if (!LIVE && /Failed to load resource: the server responded with a status of (404|502)/.test(m.text())) return
        errors.push(m.text())
      })
      page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
      await use()
      expect(errors, 'console errors').toEqual([])
    },
    { auto: true },
  ],
})

export { expect }
