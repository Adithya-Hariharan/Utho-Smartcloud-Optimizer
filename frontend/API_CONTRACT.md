# SmartCloud Optimizer: API the frontend calls

The frontend implements PLAN.md §10 exactly. It has one addition, `?preset=` on `/replay`, explained below. All data comes from these endpoints. In dev, Vite proxies `/api` to `VITE_API_URL` (default `http://localhost:8000`). Until that server is up, the dev server answers from `fallback/api/` and the UI labels it "Fallback data".

- **Types:** `src/types/contract.ts` and `src/types/api.ts` define every request and response shape.
- **Examples:** every endpoint has an example response in `fallback/api/`. The dev server serves those files while the backend is down, and the browser tests serve them in place of the backend.
- **Validation:** `npm run verify:live` runs the same tests against your server.

## Endpoints (PLAN §10)

| Method + path | Response (TS type) | Example fixture |
|---|---|---|
| `GET /api/__health` | Dev server only, not the backend: `{"backend": true}` or `false`. The UI polls it while on fallback data | — |
| `GET /api/resources?region=&env=&team=&type=` | `ResourceRow[]`: fleet table rows with p95/p99 (`stats`), a 30-day sparkline (`daily_p95`, `daily_max`), and `has_metrics` | `resources.json` |
| `GET /api/resources/{id}` | `ResourceDetail`: inventory, `features` (percentiles, trends, level shifts, recurring peak, leak cycles, 168-cell `how_p95`), `trace` (Default preset), `dq` report | `resources/vm-0003.json` |
| `GET /api/resources/{id}/metrics?metric=&step=5m\|1h` | `MetricSeries`: one metric, `{mean[], max[], gaps[]}`. Default `step=1h` is hourly mean + max, which keeps peaks | `metrics/vm-0003/cpu_1h.json`, `…/cpu_5m.json` |
| `GET /api/resources/{id}/replay?preset=` | `ReplaySeries`: actual vs projected CPU on the target plan, plus `attempts[]` | `replay/default/vm-0033.json` |
| `GET /api/recommendations?preset=default` | `RecEnvelope`: one recommendation object per resource (PLAN §4.5) | `recommendations/default.json` |
| `GET /api/summary` | `Summary` (PLAN §4.5): `monthly_before_inr`, `potential_after_inr`, `potential_saving_pct`, `by_env`, `by_team`, `by_region`, `counts`, `bill_trend_6m`, `growth_waterfall` | `summary.json` |
| `GET /api/alerts` | `AlertsResponse` | `alerts.json` |
| `GET /api/forecast?days=90` | `Forecast`: history, 90-day forecast with lower/upper band, and `carbon` including kWh and kg CO₂ **per recommendation option** (`by_option[rec_id][option_key]`) | `forecast_90.json` |
| `POST /api/whatif` | body `{"env":"dev","off":"20:00-08:00","weekends":true}` → `WhatIfResponse`: saving, plus the VMs it would break | `whatif/dev_2000_0800_1.json` |
| `POST /api/export` | body `{"accepted":[{"rec_id","option_key"}], "format":"csv\|md\|sh\|tf"}` → a file with `Content-Disposition: attachment; filename="…"` | — |
| `GET /api/scorecard` | `Scorecard`: Default-preset verdicts vs `truth.csv`, with precision/recall per verdict and per archetype | `scorecard.json` |
| `GET /api/data-quality` | `DataQuality`: per-resource cleaning counts, fault log, totals, and `checks[]` (injected vs detected) | `data-quality.json` |
| `GET /api/assumptions` | `Assumptions`: data window, counts, prices, thresholds, switches, presets | `assumptions.json` |

**The one addition to PLAN §10:** `?preset=` on `/replay`. The replayed target plan depends on the preset, so without it the drawer would show the Default target under every preset. If you'd rather not add it, the UI can fall back to Default.

The drawer's **script snippet** reuses `POST /api/export`, with a single accepted item and format `sh` or `tf`, so the snippet and the bulk export always match.

## Rules the UI relies on

1. **Missing data is `null`, never `0`.** This applies to every metric series (E1, E8).
2. **Rupees are integers.** For every option, `saving_inr === current.monthly_inr − monthly_inr_after`, and `options.none` equals current. The browser only adds these up.
3. **One run-rate everywhere:**
   - `Σ current.monthly_inr` over `/recommendations`
   - `Σ monthly_inr` over `/resources`
   - `summary.monthly_before_inr`

   All three must be equal.
4. **Every resource appears in `/recommendations`**, healthy ones included, plus metrics series with no inventory row (exclude `NOT_IN_INVENTORY`).
5. **Field presence depends on the verdict:**
   - `veto` is set only on `reject`.
   - `risk` is set only on `recommend` and `upsize`.
   - `trace`, `reason` and `formula` are always set.
   - `resize+schedule` has its own combined option (F1).
6. **`has_metrics` decides which calls the UI makes.** The UI requests `/metrics` and `/replay` only when it is true. An unknown resource id returns 404.
7. **Filters on `/resources`:** `env=untagged` and `team=unowned` match resources whose tag is missing.
8. **Every `growth_waterfall` breakdown adds up.** `by_env`, `by_team` and `by_age` (new vs existing resources) each sum to `last30.total_inr − first30.total_inr`.
9. **`carbon.by_option` covers every option** of every `recommend` and `upsize` item, in every preset, keyed by `rec_id`. The browser adds up the accepted ones, exactly like cost.
10. **Time:** timestamps are ISO 8601. Series `start` is UTC, the data window is IST (`+05:30`), and hour-of-week arrays use IST with Monday 00:00 as index 0.
11. **Errors:** return a non-2xx status with a short text or `{detail}`. The UI doesn't retry 4xx responses. When the proxy can't reach the server (502/504), the UI says the backend is down.
12. **`mock_engine: true`** on `/recommendations`, `/alerts` or `/scorecard` shows a "Mock engine" badge.

## Kept in the browser (PLAN §1, §4.5)

Accept/reject decisions and the live "after accepted" total stay in the browser: `after = Σ options[accepted].monthly_inr_after`. The same applies to the accepted kWh and CO₂ on Forecast & Green. Decisions reach the backend only through `POST /api/export`.
