# SmartCloud Optimizer: frontend

React 18 + TypeScript + Vite + Tailwind + ECharts. **The app gets all its data from the backend API** at `/api/*`. The endpoints are listed in [API_CONTRACT.md](API_CONTRACT.md).

## Run it

```bash
cd frontend
npm install
npx playwright install chromium   # once, for the browser tests
npm run dev                       # http://localhost:5173, proxies /api → http://localhost:8000
```

The backend runs on :8000; to use another address, set `VITE_API_URL`.

**Temporary fallback (dev server only).** While nothing listens on the backend port:
- The dev server answers `/api/*` from `fallback/api/`, a saved snapshot of API responses built from `../data`.
- The header shows **Fallback data · backend offline**.

When the backend starts, requests go to it straight away. Open pages refetch within about 4 seconds and show a "Backend connected" toast. Set `VITE_API_FALLBACK=off` to disable the fallback. Delete `fallback/` once the backend serves everything.

## Checkpoint gate

```bash
npm run verify                 # walk CP01…CP14 in order, stop at the first failure
npm run verify -- --upto CP05  # only as far as CP05
npm run verify -- --force      # ignore cached passes
npm run verify:watch           # re-run whenever code changes
npm run verify:live            # browser tests against the real backend on :8000
```

**What the gate checks:**
- Checkpoints are listed in `checkpoints.config.mjs`.
- A pass is cached only while every source, test, script, config and `../data` file is byte-identical. Touch any of them and every checkpoint is re-checked.
- Browser tests run in real Chromium and fail on any console error.

**How the tests get data:**
- By default, `/api/*` is stubbed **inside the test browser**, using the same resolver and data as the dev-server fallback (`fallback/resolve.ts`, `fallback/api/`).
- `verify:live` turns the stub off and reads expectations from the real API.

## Layout

```
src/api         client.ts (fetch + errors) · data.ts (one hook per endpoint)
src/lib         browser-side logic only: cost totals + F8 reconcile (PLAN §4.5), formatting, labels
src/store       zustand: decisions (persisted), preset, toasts
src/components  layout · common · charts (ECharts wrappers) · recs · resource drawer
src/pages       Overview · Recommendations · Checked & kept · Utilization (+ drill-down) · Alerts · What-if · Data quality · Assumptions
e2e/            one Playwright spec per checkpoint; fixtures.ts holds the in-test API stub
fallback/       TEMPORARY: resolve.ts + api/ (plan-shaped data) used while the backend is down, and by the tests
scripts/        check_fixtures.mjs · verify.mjs
```
