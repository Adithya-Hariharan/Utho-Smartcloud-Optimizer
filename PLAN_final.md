# CURRENT STEP: Backend MVP (B1–B8) + engine (B10), both implemented

**Status (2026-10-24):** the backend is complete for the MVP. B1–B8 were built first with the engine stubbed; the engine was then added (B10) and replaces the stub. B6 below describes the stub-era behaviour; B10 lists what changed. `pytest` is green (454 tests after the merge with main: 291 for `backend/`, 163 for main's `engine/`).

**Frozen:** the recommendation schema (§4.5), the data contracts (§4.1, §4.2) and the API (§10: paths, methods, parameters, body fields) are not changed by this step. Where this section says "stub", the endpoint keeps its path and parameters and the response keeps the frozen shape. Where §4.5 does not give a shape (list endpoints, metrics, data-quality, assumptions), this section defines it.

**Out of scope for the MVP** (bonus features, per the §12 Phase 4 list and §13 cut lines): forecast, what-if, carbon, Terraform/script export, scorecard UI, role views, presets other than `default`, the resources × days heatmap, budget alert G8. (The engine was out of B1–B8 and is now in, see B10.) Their endpoints exist (paths stay frozen) and answer as set out in B6.

This section overrides the earlier sections where they disagree (the dataset step below is finished and kept for reference).

## B1. Layout and commands (repo root = `D:\Transif\repo`)
```
generator/ data/                       already built (STEP 1 below)
config.yaml                            root, authoritative for the app
requirements.txt                       numpy, pandas, pyarrow, scipy, pyyaml, fastapi, uvicorn, pydantic>=2, httpx, pytest, matplotlib(dev)
backend/
├── config_loader.py                   loads config.yaml; config_hash = sha256 of canonical JSON (sorted keys, no spaces)
├── data_access.py                     reads data/*.csv|parquet once, returns typed frames
├── pipeline/ clean.py · features.py
├── cost/ model.py
├── insights/ alerts.py · growth.py
├── api/ schemas.py (Pydantic v2 copy of §4.5) · main.py
tests/ test_clean.py · test_features.py · test_cost.py · test_alerts.py · test_api.py
```
All commands run from the repo root: `python -m generator.build`, `python -m generator.validate`, `uvicorn backend.api.main:app --port 8000`, `pytest`. The `backend.generator…` paths in §3 and §14 are replaced by `generator…`.

## B2. Facts that replace earlier numbers
- Data as generated: **117 VMs + 15 volumes + 8 IPs = 140 inventory rows**; 55 planted VMs (Group A has 29 names). Wherever G5 says 118/141/56, read 117/140/55.
- `NOW` = 2026-10-20 00:00 IST. Window = 2026-09-20 00:00 to 2026-10-19 23:55 IST, 8,640 slots. Both come from `config.yaml`, which is also the source of `data_window{start,end,timezone}` in the envelope. Every "N days ago", `days_of_data` and "stopped N days" is measured against `NOW`.
- `volume_metrics.parquet` columns: `resource_id, ts (UTC), iops, disk_used_pct`. Empty `owner_team` appears as `""` in `billing_daily`; treat it as `unowned`.
- Parsing: `inventory.csv` timestamps carry `+05:30`; `metrics.parquet` is UTC. `resource_id` is a category dtype in parquet, so cast to `str`. Empty `tags` means `[]`. Empty `owner_team` means owner `"unowned"`. The resource's `team` and `owner` are both the `owner_team` value. `inventory.csv` has one extra column, `previous_plan_id`; the loader keeps it and nothing in the contract changes.
- `faults.csv` lists the injected faults and is used as test input for the cleaner.

## B3. Cost basis (one rule, used by billing, the cost model and every API total)
- Month = 730 h. Daily cost = monthly × 24/730. (This replaces "price ÷ 30" in §5.3; it is what `generator/billing.py` does.)
- VM monthly cost = plan price (compute) + `disk_gb` × ₹8 (boot disk, billed inline). A stopped VM pays disk only (`stopped_vm_billed: false`).
- A volume row costs `disk_gb` × ₹8. An IP row costs ₹200. A snapshot costs ₹4/GB.
- An IP attached to a VM is billed on the **IP's own row**, never on the VM, so nothing is counted twice. Therefore a VM item has `ip_inr = 0`.
- `current{}` fields: `compute_inr` = plan price (0 if stopped), `storage_inr` = `disk_gb` × 8, `ip_inr` = 200 on IP items else 0, `monthly_inr` = the sum. For volume and IP items `plan` is null.
- Every figure is a whole rupee. Σ monthly cost over all 140 items must equal the last day of `billing_daily.parquet` × 730/24 (± ₹1 per resource).
- `prod-legacy-plan-17` has plan `L-OLD-4`, which is not in `pricing.csv`. `generator/config.py` bills it at ₹3,500 (`LEGACY_PLANS`). The cost model reads that rate from `config.yaml` under `legacy_plan_rates` (a billing-only entry that is not part of the price catalogue, so the engine will still see the plan as unknown). Its `current.compute_inr` is 3,500, so the B3 sum identity holds for all 140 rows.

## B4. Cleaner and features: exact definitions
**clean.py** (per resource, per metric column; counts go to the data-quality report):
1. Snap timestamps to the 5-minute grid (floor). Count the rows moved.
2. Stable sort by `ts`.
3. De-duplicate on `(resource_id, ts)`: keep the first row in original file order; if an off-grid row collides with an on-grid row, the on-grid row wins.
4. Percentages outside [0, 100] and negative rates become NaN.
5. Flatline: for VMs only, a run of ≥ 24 consecutive valid samples (2 h; missing slots do not break a run) in which `cpu_pct` **and** `mem_pct` are each constant over the same samples becomes NaN in both columns. One constant metric alone is never nulled (staging-api-09 holds CPU at exactly 40.0 for 10 h each weekday while its memory varies). Net and IOPS are never flatline-checked, because a zombie's network and an idle volume's IOPS are legitimately all zero.
6. Reindex to the full 8,640-slot grid; missing is NaN, never 0. A VM created inside the window or stopped inside it has its grid limited to the time it existed.
7. `coverage` = non-NaN CPU slots ÷ slots the resource existed. `peak_window_coverage` = min coverage across the 168 hour-of-week buckets.
- Must be idempotent (cleaning twice gives the same frame). Cleaning plus features for all VMs finishes in under 30 s.

**features.py** (units fixed):
- Percentiles use linear interpolation over non-NaN values.
- `iops_pct` = `iops` ÷ `provisioned_iops` × 100. `net_pct` = max(`net_in_mbps`, `net_out_mbps`) ÷ `bandwidth_mbps` × 100. The §7 idle test "net < 5 MB/h" means mean(`net_in`+`net_out`) < 0.0111 Mbps (1 Mbps = 450 MB/h).
- `days_of_data` = distinct IST calendar days with at least one valid sample.
- `trend_slope` (percentage points per day) = least-squares fit of the 30 daily p95 values (cpu, mem, disk_used). `days_to_85` / `days_to_90` = (limit − fitted value on the last day) ÷ slope; null if slope ≤ 0. The alert rule G5 uses its own 14-day fit (see B5).
- `recurring_peak_days` = number of days whose 30-minute rolling mean of CPU exceeds 80%.
- `leak_score` = number of consecutive-valid-sample drops of more than 25 percentage points in `mem_pct` (same definition as `generator/validate.py` A11).
- `level_shift_up`, `level_shift_down`, `mem_flatness`, `p99_excl_top_day`, the 168-cell profile: exactly as in §6.
- The features table is stored in memory; the cleaned 5-minute arrays are cached for the metrics endpoint.
- `days_to_85` is a feature only. The H-versus-VETO_GROWTH decision for prod-api-04 (A15) belongs to the engine and is not made here.

## B5. Insights (MVP set)
Alert object = frozen §4.5 shape. `type` is the code in the first column (`G1`, `G3`, …). `alert_id` = `ALR-<type>-<resource_id>` (one alert per resource and type; `occurrences` = number of separate episodes). Team-level alerts use `resource_id` = `team:<name>`. `first_seen` = start of the earliest episode (IST ISO). `title`, `why` and `suggested_action` are fixed templates filled with the measured numbers. G1 compares hour-of-week buckets in IST and needs ≥ 3 non-NaN other weeks.
| Type | Rule | Severity |
|---|---|---|
| G1 spike | CPU > median + 4×MAD of the same hour-of-week in the other weeks (need ≥ 3 other weeks) **and** ≥ 20 points above that median, for ≥ 6 consecutive samples | Warning |
| G2 | not an alert; test only: prod-batch-07 raises no G1 | – |
| G3 level shift | `level_shift_up` > 3 | Critical if prod, else Warning |
| G4 compromise | last-24 h mean CPU > 90 and last-24 h mean `net_out` ≥ 5× the baseline, where baseline = median of the 28 daily mean `net_out` values ending 24 h before `NOW` | Critical |
| G5 capacity | linear fit of the last 14 daily p95 values (cpu, mem, disk_used); fires only if slope ≥ 0.3 points/day and days to 90 = max(0, (90 − fitted last value) ÷ slope) < 30 → alert with ETA. Needs ≥ 7 daily values | Critical if < 7 days, else Warning |
| G6 leak | `leak_score` ≥ 3 | Warning |
| G7 team cost jump | evaluated only for dates inside the 30-day metrics window. A team fires on a date when its daily cost from `billing_daily` is > 1.05 × its previous 7-day mean (threshold in `config.yaml`) **and** at least one resource has its first billed day on that date. One alert per team, `first_seen` = the earliest such date; `why` names those resources. Empty `owner_team` is grouped as `unowned`. Expected: growth on 2026-10-12, mobile on 2026-10-17 | Warning |
| G9 under-provisioned | ≥ 5% of valid CPU samples above 90 (threshold in `config.yaml`; a nightly batch of 1–2 h puts only about 3–4% above 90, so it stays silent) | Warning |
| G10 monitoring missing | a running VM with no metric rows | Warning |
| G11 | the de-duplication rule above | – |
G5 is not evaluated for a resource where G3 or G4 fires (a step change is not a trend). Its daily p95 values use IST calendar days (the last 14 complete days of the window). G1 pools every 5-minute sample in the same IST hour-of-week across the other weeks. G7's previous 7-day mean may reach back before 2026-09-20, since billing has 180 days. Alert `evidence` = `{metric, value, threshold, window}` filled from the rule that fired (for example `{cpu_p99, 93.2, 90, "2026-09-20/2026-10-19"}`).
G8 (budget overrun) is cut from the MVP: no budget data exists. `growth.py` builds `bill_trend_6m` (six consecutive 30-day totals of `billing_daily`) and `growth_waterfall` (month-6 minus month-1, as a list of `{label, group, delta_inr}`: resources first billed after day 30, grouped by env and team, plus one "existing resources" remainder).

## B6. API behaviour in the MVP (shapes of frozen endpoints are unchanged)
| Endpoint | MVP behaviour |
|---|---|
| `GET /api/resources` | Items `{resource_id, name, type, region, env, team, state, plan_id, monthly_inr, cpu_p95, cpu_p99, mem_p99, sparkline}`; `sparkline` = 60 points, 12-hourly mean CPU. Filters `region, env, team, type` are exact matches. Volumes and IPs are included with null CPU fields. |
| `GET /api/resources/{id}` | Inventory row + features + cleaner report; `trace` is `[]`. Unknown id: 404. |
| `GET /api/resources/{id}/metrics` | `metric` ∈ `cpu, mem, disk, iops, net_in, net_out` (volumes: `iops, disk` only; others 422). `step` default `1h`. Returns `{resource_id, metric, step, ts[] (ISO UTC), mean[], max[]}`; for `5m`, `mean` = `max` = the value. Hourly buckets are UTC hours. Cleaned data; NaN is JSON null. A resource with no metric rows (prod-nomon-13, vm-stopped-07, IPs) returns 200 with empty arrays. |
| `GET /api/resources/{id}/replay` | 501 `{"detail":"engine not available"}` |
| `GET /api/recommendations?preset=default` | Valid frozen envelope and one valid frozen item per inventory row (140). Any preset other than `default`: 501. Response header `X-Engine: stub` (CORS exposes it).<br>**Envelope:** `schema_version="1.0"`, `generated_at` = ISO time of server start, `preset="default"`, `config_hash`, `data_window`, `items`, `below_floor={count:0, monthly_inr:0}` (envelope only).<br>**Stub item:** `rec_id="REC-<resource_id>-default"`; `resource` from inventory (`members` = the other resource_ids sharing a non-empty `service_group`, else `[]`; `env` exactly as in inventory, possibly empty); `verdict="healthy"`, `reason_code="RIGHT_SIZED"`; `actions=[]`, `flags=[]`, `default_option="none"`; `current` per B3; `target=null`, `schedule=null`, `replay=null`, `veto=null`, `risk=null`, `explanation_ai=null`; `options={"none":{monthly_inr_after:<monthly_inr>, saving_inr:0, formula}}`; `evidence={window_days:30, days_of_data, coverage, peak_window_coverage, percentile_used:null, metrics:{cpu, mem, iops_pct, net_pct, disk_used}, recurring_peak:null, naive:null}` where each metric is `{p50,p95,p99,max}` with null leaves when the resource has no telemetry (so `metrics` itself is never null); `reason="Engine not enabled; no decision computed."`; `formula="₹<monthly_inr>/month, no change"`; `trace=[]`; `alert_ids` = ids of alerts for that resource. `schemas.py` marks nullable: `target, schedule, replay, veto, risk, explanation_ai, evidence.naive, evidence.recurring_peak, evidence.percentile_used`, `current.plan/vcpu/ram_gb/disk_gb`, and every `evidence.metrics.*` leaf; everything else is required. Without telemetry (volumes with no CPU, IPs, no-metric VMs) `days_of_data=0, coverage=0.0, peak_window_coverage=0.0`; volumes compute `days_of_data` and `coverage` on `iops`/`disk_used_pct`. `peak_window_coverage` ignores hour-of-week buckets in which the resource had zero existing slots. |
| `GET /api/summary` | Real: `monthly_before_inr`, `by_env/by_team/by_region` (current monthly cost; an empty env is keyed `untagged`, an empty team `unowned`), `counts` (by type), `bill_trend_6m` = `[{label, total_inr}]` (six 30-day totals, whole rupees), `growth_waterfall` = `[{label, group, delta_inr}]` with one entry per env/team pair (`group="env/team"`) plus an `existing resources` remainder; the entries sum exactly to month 6 minus month 1. Stub: `potential_after_inr = monthly_before_inr`, `potential_saving_pct = 0`. |
| `GET /api/alerts` | Real, B5 set, sorted by severity then `first_seen`. |
| `GET /api/data-quality` | `{resources:[{resource_id, rows_in, snapped, reordered, duplicates_removed, out_of_range_nulled, flatline_nulled, coverage, peak_window_coverage, longest_gap_slots}], strays:[resource_ids with metrics but no inventory], no_metrics:[inventory VMs with no metric rows]}` |
| `GET /api/assumptions` | `{config_hash, config: <config.yaml as JSON>, dataset_notes: <DATASET.md text>}` |
| `GET /api/forecast`, `POST /api/whatif`, `POST /api/export`, `GET /api/scorecard` | 501 `{"detail":"not in MVP"}` (`/scorecard`: `"engine not available"`) |
| all | CORS for `http://localhost:5173` (exposing `X-Engine`); `/docs` served by FastAPI; data loaded once at startup. |

## B7. `config.yaml` contents
Window, `now`, timezone, `hours_per_month: 730`, plan prices (identical to `data/pricing.csv`), volume/snapshot/IP rates, `stopped_vm_billed`, `legacy_plan_rates: {L-OLD-4: 3500}`, the §7 threshold table, the four presets, the saving floor, each entry with `why:` and `source:`. `config.yaml` is authoritative for the app; a test asserts it equals `pricing.csv`.

## B8. Build order and acceptance checks
Each step is done only when its checks pass.
1. **Setup:** `requirements.txt`, `config.yaml`, loader, `data_access`. Check: `config_hash` is stable across two runs; the config prices equal `pricing.csv`.
2. **clean.py.** Checks: E1 leaves a NaN gap of ≥ 72 slots in prod-api-02; E2 de-duplicates dev-web-03; E3 values become NaN; E8 flatline becomes NaN on dev-api-16 only (no other VM loses more than 1% coverage to it; staging-api-09 keeps its 40.0 plateau and its p95 stays 40.0); E10 timestamps snap to the grid; vol-idle-04 keeps its zero IOPS; a second pass changes nothing.
3. **features.py.** Checks: prod-batch-07 mean CPU 6–10, p99 88–95; prod-cache-04 mem p99 ≥ 80; dev-web-03 weekend p95 < 5; prod-api-04 slope > 1; prod-worker-05 `level_shift_up` ≥ 3.5; prod-legacy-06 `level_shift_down` < 0.2; prod-orders-08 `leak_score` ≥ 3; dev-flaky-18 coverage < 0.8.
4. **cost/model.py.** Checks: B3 identities; Σ before = last billing day × 730/24 within ₹1 per resource; every figure an integer.
5. **schemas.py.** Check: a JSON example of every §4.5 verdict validates; the stub item validates.
6. **API (main.py).** Checks (FastAPI TestClient): every endpoint in B6 returns the documented status; `/recommendations` has 140 items and validates; `/metrics` returns `null` for the E1 gap; unknown id gives 404.
7. **alerts.py, growth.py.** Checks: G1 fires for prod-reports-02 and not for prod-batch-07; G3 for prod-worker-05; G4 critical for dev-sandbox-17 only; the G5 set is exactly prod-api-04, vol-growing-10 and the 4 bulk-disk VMs (so not prod-worker-05 or dev-sandbox-17); other types are checked as "must include" (G3 includes prod-worker-05 and dev-sandbox-17, G9 includes prod-search-02 and not prod-batch-07); G6 for prod-orders-08; G7 for growth on 2026-10-12 and mobile on 2026-10-17; G9 for prod-search-02 (and not for prod-batch-07); G10 for prod-nomon-13; no duplicate (resource, type) pairs.
8. **Tests:** `pytest` is green; startup (clean + features) under 30 s.

Notes: the API takes `resource_id` (for example `vm-0003`); tests map names to ids through `inventory.csv`. During the E8 window only `cpu` and `mem` are nulled, so `iops`, `net` and `disk` still show their stuck values in `/metrics`. §4.3's line "disk billed separately as a volume" is overridden by B3.

## B9a. Review items from the final Opus review (all resolved)
1. **Resolved.** G5 requires fit R² ≥ 0.5 (`alerts.g5_min_r2`); staging-load-06 no longer fires and B8.7's exact G5 set holds.
2. **Resolved.** `schemas.py` allows `evidence.metrics` null and enforces §4.5: null only (and always) for NO_TELEMETRY / HISTORY_TOO_SHORT.
3. **Resolved.** `leak_score` ignores a memory drop that coincides with a CPU drop > 20 points (`thresholds.leak_cpu_drop_pct_points`); G6 = prod-orders-08 only.
4. **Resolved as documented choices:** G1 uses raw MAD (not ×1.4826) plus a 20-point floor; `reordered` = rows that arrive earlier than a row already seen (a reversed block of 20 counts 19); IP `storage_inr` = 0; volumes keep the full window (the generator wrote full-window volume metrics); volume/IP `state` values (attached, unattached, associated, unassociated) pass through unchanged; hourly buckets are UTC hours; empty `purpose`/`service_group` are emitted as `""`; volumes compute `iops_pct` and `disk_used`, with `cpu`, `mem`, `net_pct` null leaves.

## B9. Status
The non-engine MVP (B1–B8) and the engine (B10) are implemented and tested. Still out of scope (bonus): forecast, what-if, carbon, script/Terraform export, presets other than `default`, role views.

## B10. Engine (implemented; `backend/engine/`)
Modules: `params.py` (preset → percentiles, CPU targets, replay limits), `sizing.py`, `replay.py` (Peak Replay), `candidates.py` (off-hours windows), `risk.py`, `noncompute.py` (volumes, IPs, stopped VMs), `compute.py` (the VM pipeline), `decide.py` (orchestrator, §4.5 items), `common.py`. Every new threshold is in `config.yaml` with `why:`/`source:`. The engine never reads `truth.csv`; `backend/insights/scorecard.py` does.

**VM pipeline order** (first terminal verdict wins; strict `<` / `>`; every check goes into `trace`):
1. Inventory: plan not in catalogue → UNKNOWN_PRICE; no metrics → NO_TELEMETRY; empty env → treated as prod + UNTAGGED_ENV; empty owner → UNOWNED; name/env conflict → TAG_NAME_CONFLICT; coverage 80–95% → MEDIUM_COVERAGE.
2. Gates: tags dr_standby / autoscaled / seasonal_peak, policy never, stateful prod, days_of_data < 14, resized < 14 d ago, coverage < 80%, level_shift_up > 3 (ACTIVE_ANOMALY).
3. Went quiet (last 7 d ÷ prior 23 d < 0.2) → flag, before any other test.
4. Leak veto on **every** VM (≥ 3 memory resets not caused by a CPU drop): a leaking VM's memory is an artefact of its restarts.
5. Under-provisioned: CPU p99 > 90 **and** mean CPU ≥ 20% → UPSIZE. A VM idle on average that touches 90% is batchy, not starved (same rule as `engine/components/sizing.py` on main). Memory alone never upsizes.
6. **Looks shrinkable** gate: mean CPU < 20% or CPU P < 40%. Otherwise healthy; capacity vetoes only matter when shrinking is on the table. This resolves A15 (prod-api-04 healthy despite its growth trend; the capacity alert still fires).
7. Capacity vetoes and patterns (shrink candidates only): reserved memory (flat ≥ 75% with std < 0.75) → memory p99 > 70 → IOPS p95 > 70 → network p95 > 60 → CPU growth (slope ≥ 0.3, R² ≥ 0.5, days_to_85 < 60) → peak under-observed (coverage of the IST hours whose p95 ≥ 50% is < 50%) → recurring peak (same IST hour-of-week above 80% in ≥ 3 weeks, and CPU p99 ≥ 80) → one-off peak. A recurring peak blocks **resizing only**: a non-prod VM with a valid off-hours schedule (which keeps the peak window on) gets OFF_HOURS / schedule.
8. Candidates: idle on 4 metrics with lines relative to the plan (CPU P < 5, mem P < 70, mean network < 0.1% of bandwidth, IOPS p95 < 1% of provisioned; prod → IDLE_PROD flag; stateful non-prod → snapshot+stop), underused → sizing (round up; prod one step down; service group sized on its busiest member) → Peak Replay (try bigger, still-cheaper plans). Off-hours for non-prod (policy, keep_running and `stopped_vm_billed` respected).
9. A shrink candidate that ends with no action is explained: formula sizing on P; if a cheaper plan passes replay → healthy; otherwise NO_CHEAPER_PLAN when memory rules out every cheaper plan, else PEAK_REPLAY_FAILED with the replay evidence (the naive mean-CPU cut). This applies to every env (staging-demo-10: keep_running forbids scheduling, not evaluation).
10. Floor: compute right-sizing (idle, underused, off-hours) saving < ₹500 → healthy, counted in `below_floor`. Clean-ups (orphans, stopped VMs, unused IPs) are not floored: they are waste, whatever the amount.

**Non-compute:** volume: unattached < 7 d → ORPHAN_TOO_NEW, else ORPHAN_VOLUME (snapshot of the median used GB + delete); attached to a VM stopped > 30 d → STOPPED_VM; growth → VETO_GROWTH; IOPS p95 < 5 → IDLE_VOLUME_REVIEW; used p99 < 30% → OVERSIZED_VOLUME (migrate to a volume sized for ≤ 50% use, 50 GB steps). IP: allowlisted → exclude; unassociated ≥ 7 d → UNUSED_IP; on a VM stopped > 30 d → STOPPED_VM. Stopped VM > 30 d → STOPPED_VM snapshot + delete.

**Contract gaps (frozen §4.5 kept unchanged):** `truth.csv` uses `BELOW_FLOOR` (dev-tiny-15) and `STOPPED_RECENTLY` (vm-maint-08), which are not in the §4.5 enum. The engine emits `healthy / RIGHT_SIZED` for both: dev-tiny-15 is counted in `below_floor`, vm-maint-08 carries a `STOPPED_RECENTLY` flag. The scorecard maps the two codes explicitly.

**API changes from the stub (shapes unchanged):** `/api/recommendations` serves engine items (`X-Engine: v1`; the stub stays as the fallback if the engine fails at startup, `X-Engine: stub`); `/api/summary` fills `potential_after_inr` (upsizes kept at current cost; their extra cost is `counts.upsize_extra_inr`); `/api/resources/{id}` returns the real `trace`; `/api/resources/{id}/replay` returns `{resource_id, current_plan, replay_plan, passed, minutes_above_90, limit_minutes_above_90, mem_cap_pct, threshold_pct, step, ts[], actual_cpu[], projected_cpu[], actual_mem[], projected_mem[]}` (`step=5m|1h`, hourly = max; 404 when the resource has no replay); `/api/scorecard` returns `{total, matched, accuracy, unsafe_downsizes, unsafe_resources, waste_found, by_verdict, by_archetype, mismatches, contract_mapped}`.

**Checks:** `tests/test_engine.py` runs every `truth.csv` row (140/140 match), the F1–F10 cost rules, replay safety (0 resizes that fail replay), schedule windows (B5–B7) and flags; the default-preset headline is 20.1% on the merged (fitted, label-corrected) data (F9 band 15–35%).

**Merge with main (2026-10-24):** main brought a regenerated dataset (fitted to public traces, 9 label disputes resolved) and a second engine in `engine/`. The rules above were aligned with main's published choices (relative idle lines, batchy-not-starved upsize, leak on every VM, schedule around a recurring peak, refusal explanation for every env) so both engines agree with `truth.csv`. `backend/` and `engine/` coexist; `pytest` runs both suites (454 tests).

## B11. Frontend integration (implemented; plan: `PLAN_frontend_integration.md`)
The backend now serves every endpoint in the frontend's own shapes (`frontend/src/types/*.ts`, `frontend/API_CONTRACT.md`). The B6 stub and "not in MVP" 501s are gone: forecast, what-if, export and all four presets are built. The dataset is unchanged.
- **Schema v1.0 extended** (complete list in `PLAN_frontend_integration.md` §3):
  - envelope `mock_engine: false`
  - `resource.state` and `plan_id`; `members` are names; empty strings become null
  - codes `BELOW_FLOOR`, `STOPPED_RECENTLY` and `NOT_IN_INVENTORY`, plus a stray-series item (vm-9999, named by its id). These are now emitted directly, so the scorecard no longer maps them
  - `percentile_used` is a string; metric leaves `{mean, p50, p95, p99, max}` or null; `recurring_peak {window_ist, days}`
  - `naive {action, target_plan, saving_inr, basis, replay_minutes_above_90}` on rejects and flags, with a naive replay when nothing else was replayed
  - `replay.from_vcpu` and `from_ram_gb`
  - trace values are strings, with results pass / fail / info / skip
- **Text formats** copied from the frontend reference (`docs/reference/mock_engine.py`), with our numbers:
  - schedule windows ("Mon–Thu 19:00–09:00 (next day)", "Fri → Mon") and busy hours ("01:00–03:00 daily")
  - option formulas ("… × 50/168 h on …")
  - veto vocabulary ("days with a 30-min peak > 80%")
  - alert types and wording
- **New modules:** `backend/api/views.py` (one function per endpoint), `backend/engine/present.py`, and `backend/insights/{forecast,whatif,export}.py`. `scorecard.py`, `alerts.py` and `growth.py` were rewritten to the frontend shapes.
- **Carbon** (Forecast & Green) uses PLACEHOLDER coefficients in `config.yaml` (`carbon`: CCF / CEA published averages). The dataset has no power, PUE or grid data. Adding them is **future scope** (§10 of the integration plan).
- **One deliberate deviation from the integration plan (E4):** the replay chart projects onto the plan the replay attempts were run on, i.e. chosen plan, else last attempt, else naive target. The plan said "else naive target, else last attempt", but with that order `dev-report-02` would chart S1 while its rejecting attempt was B1.
- **Verified:**
  - `pytest` passes (491 tests).
  - A shape diff of every endpoint against every frontend fixture finds 0 missing and 0 type mismatches.
  - The frontend's `check_fixtures.mjs` passes all 5,854 checks on a dump of the live API.
  - The frontend typechecks, its unit tests pass (19) and it builds.
  - **Live browser suite** (`E2E_LIVE=1`, installed Chrome): 53 pass, and the 11 failures are exactly the test lines in the integration plan §9. With those test-only edits applied in a scratch copy, 64 of 64 pass (1 test is `fixme`). The edits are not in the repo; they wait for the frontend owner's approval.

---

# STEP 1 (COMPLETED; kept for reference): Generate the synthetic dataset ONLY

**Scope:** build the seeded data generator, run it, and validate the output. **Nothing else.** The engine, API, UI, alerts and everything else in the reference plan below are **not** part of this step.

The full plan is kept for later:
- this file (reference section below)
- a project memory note saved after approval, which points back to this file

## G1. Where it goes
```
Transfinitte/smartcloud-optimizer/
├── requirements.txt            numpy, pandas, pyarrow, pyyaml
├── generator/
│   ├── config.py               window, seed, fleet mix, prices, calibration targets
│   ├── signals.py              building blocks: daily_curve, weekly, drift, AR(1) noise, bursts
│   ├── archetypes.py           7 bulk archetypes
│   ├── planted.py              56 planted VMs + 6 volumes + 3 IPs (one per edge case)
│   ├── quality.py              data-quality fault injection
│   ├── billing.py              180-day daily cost history
│   ├── build.py                entry point: python -m generator.build
│   └── validate.py             checks planted stats, fleet calibration, sizes, determinism
└── data/
    ├── inventory.csv · pricing.csv · truth.csv
    ├── metrics.parquet          VMs, 5-min, UTC
    ├── volume_metrics.parquet   volumes: iops, disk_used_pct
    ├── billing_daily.parquet
    ├── fixture/                 3-resource sample (prod-batch-07, dev-web-03, vol-orphan-11)
    └── DATASET.md               generation logic, calibration sources, fault list
```

## G2. Window and determinism
- **Window:** 30 days, 2026-09-20 00:00 to 2026-10-19 23:55 IST, 5-minute steps, 8,640 slots. "Now" is 2026-10-20.
- **Timestamps:** stored in UTC; daily curves are built in IST.
- **Randomness:** each resource gets its own generator, `np.random.default_rng([42, crc32(name)])`. Its data stays the same even if the list order changes.
- **Precision:** metrics are float32, rounded to 2 decimals.

## G3. Calibration against public datasets

The calibration targets are approximate figures from the published papers, recalled from memory. DATASET.md states this. `validate.py` checks the fleet aggregates against each target.

| Source | What we take from it | Fleet-level target we check |
|---|---|---|
| **Azure** (Resource Central, SOSP '17; 2017/2019 traces) | Most VMs have low average CPU. Workloads split into interactive (daily curve) and delay-insensitive (batch). p95 sits far above the average. Small VM sizes dominate | 50–65% of VMs have mean CPU < 20%; median p95/mean CPU ratio of 2–4 |
| **Azure spike study** | Most VMs have spikes, and most spikes are not seasonal | Bursty archetype uses random (non-scheduled) spikes |
| **Bitbrains GWA-T-12 / Materna** | Business-critical VMs: CPU low and bursty, memory more stable than CPU, disk and network bursty | Median coefficient of variation of memory < that of CPU; heavy-tailed network and IOPS |
| **Google 2011** (Reiss et al., SoCC '12) | Usage far below what was allocated | Fleet median CPU p95 < 50% of allocation |
| **Alibaba 2018** | Memory stays high and sticky even when CPU is low | Memory-bound archetype at 80–88%; memory = base + 0.25 × CPU |
| **IBM trace study** | Gaps are common in monitoring data | ~0.5% random drops plus reboot gaps |

## G4. Signal model (per VM, vectorised over 8,640 slots)
```
cpu = clip(base × daily(t) × weekly(t) × drift(day) + bursts(t) + ar1_noise(t), 0, 100)
mem = clip(mem_base + 0.25 × cpu + noise, 0, 100)
iops = k_iops × cpu × provisioned/100 + lognormal noise
net_in, net_out = k_net × cpu + lognormal noise
disk_used_pct = start + slope × day + small noise
```
- `daily(t)`: business-hours bump peaking at 14:00 IST.
- `weekly(t)`: weekend factor, near 0.1 for dev.
- `drift`: N(1, 0.05) per day.
- `ar1_noise`: eₜ = 0.8·eₜ₋₁ + N(0, σ).

## G5. Fleet: 118 VMs + 15 volumes + 8 IPs = 141 inventory rows

**Bulk VMs (62):**
| Archetype | Count |
|---|---|
| right_sized_prod | 15 |
| steady_low | 12 |
| bursty_daily | 7 |
| batch_nightly | 5 |
| office_hours_dev | 15 |
| zombie | 5 |
| memory_bound | 3 |

- 4 of the office_hours_dev VMs belong to the growth team and were created on day 22. This feeds the team cost-jump case (G7) and the too-short-history case (D1-style).
- Regions are weighted Mumbai 40%, Bangalore 35%, Noida 25%.
- There are 6 teams.

**Planted VMs (56), one per edge case:**
| Group | Resources |
|---|---|
| A (30) | prod-api-01/07/04, prod-batch-07, prod-billing-01, dev-report-02, prod-reports-02, prod-checkout-01/03, prod-queue-02, prod-cache-04, prod-search-06/02, prod-orders-08, prod-db-01, prod-ingest-09, prod-gateway-03, prod-legacy-06, prod-ml-10, dev-tiny-14/15, staging-web-08, staging-api-09, prod-web-11a/b/c, prod-k8s-node-1/2/3 |
| B (9) | staging-db-02, prod-old-12, dev-cache-13, dev-web-03, dev-etl-04, dev-support-05, staging-load-06, dev-misc-07, staging-demo-10 |
| C (2 VMs) | vm-stopped-07 (stopped 45 days, so no metrics), vm-maint-08 (stopped 3 days ago, metrics end then) |
| D (9) | dev-test-12, staging-app-05 (plan changed 6 days ago), prod-standby-01, prod-nomon-13 (no metrics), vm-untagged-14 (env empty), dev-orphan-owner-15 (owner empty), dev-misnamed-16 (tag prod), prod-legacy-plan-17 (plan L-OLD not in pricing), prod-worker-05 (4× jump on day 29) |
| E (5) | prod-api-02, dev-flaky-18, staging-flaky-19, dev-api-16, prod-batch-20 |
| G (1) | dev-sandbox-17 (CPU 98% + 10× network out from day 26) |

Each planted VM gets the exact pattern from the edge-case catalogue in the reference section §8.

**Volumes:** 6 planted plus 9 healthy attached volumes.
- vol-orphan-11: unattached 65 days
- vol-new-12: unattached 2 days
- vol-idle-04: attached, 0 IOPS
- vol-stopped-07: attached to vm-stopped-07
- vol-oversized-09: 500 GB, 40 GB used
- vol-growing-10: +2%/day

**IPs:** 3 planted plus 5 associated with prod VMs.
- ip-unused-03: never associated
- ip-stopped-02: on vm-stopped-07
- ip-allowlist-04: unassociated, tag `allowlisted_ip`

**D9 stray series:** metrics for `vm-ghost-99`, which has no inventory row.

## G6. Data-quality injection (quality.py, applied after the clean signals are built)
| Case | Fault |
|---|---|
| E1 | prod-api-02: rows removed for 6 hours on day 12, 10:00–16:00 |
| E2 | dev-web-03: day 9 14:00–15:00 duplicated with slightly different values (agent re-send) |
| E3 | 3 bulk VMs: 5 values each in 103–110% and −1 to −3% |
| E4 | 2 bulk VMs: 20 rows swapped out of order |
| E5 | All VMs: 0.5% random drops. 6 VMs: a 20-minute reboot gap |
| E6 | dev-flaky-18: ~30% missing, in hour-long chunks |
| E7 | staging-flaky-19: ~12% missing |
| E8 | dev-api-16: CPU exactly 0.0 and memory constant for 48 hours (days 15–16) |
| E9 | prod-batch-20: nightly 02:00 batch, but 01:00–04:00 missing on 10 of 30 nights |
| E10 | 1 bulk VM: timestamps offset by +3 minutes for one day |

## G7. Other outputs
- **inventory.csv:** columns as in reference §4.1. `created_at` dates are spread over 9 months, with dev and staging weighted toward the last 6. They are tuned so billing month 6 ÷ month 1 ≈ 1.40.
- **pricing.csv:** S1–B6 per reference §4.3, plus volume ₹8/GB, snapshot ₹4/GB, IP ₹200, all marked illustrative.
- **billing_daily.parquet:** `date, resource_id, team, env, cost_inr` for 180 days. A resource costs nothing before `created_at`. Resize history (staging-app-05) is reflected, and stopped VMs pay disk and IP only.
- **truth.csv:** `resource_id, name, archetype, edge_case_id, expected_verdict, expected_reason_code, expected_action, notes`. For tests and the scorecard only; the engine never reads it.

## G8. Verification (part of this step)
1. `python -m generator.build` writes all files.
2. `python -m generator.validate` checks:
   - **Planted stats:**
     - prod-batch-07: mean CPU 6–10%, p99 88–95%
     - prod-cache-04: memory p99 ≥ 80%
     - dev-web-03: weekend p95 < 5%
     - prod-api-04: daily-p95 slope > 1%/day
     - prod-worker-05: last-48h ÷ prior mean ≥ 3.5
   - **Faults present:** E1–E10, each confirmed.
   - **Calibration:** the G3 targets.
   - **Bill growth:** month 6 ÷ month 1 between 1.35 and 1.45.
   - **Size:** total ≤ 30 MB.
   - The script prints a table of results.
3. Run the build twice and confirm identical SHA-256 hashes.
4. Plot 3 resources (prod-batch-07, dev-web-03, prod-queue-02) to PNG in the scratchpad (matplotlib, scratchpad only) and look at them.

---

# REFERENCE (not executing now): SmartCloud Optimizer — Final Architecture, Edge-Case Catalogue & 40-Hour Plan

## 0. Context

**Hackathon brief:** build a tool that turns 30 days of VM utilisation data into **safe, explained, costed decisions** for an Indian SaaS team. The team runs 50–150 VMs across Noida, Bangalore and Mumbai, split into prod, staging and dev, and their bill grew 40% in 6 months. Safety of the logic (25%) and cost transparency (20%) together carry 45% of the marks.

This plan merges the three inputs (the case catalogue, the 4-person build plan and the execution plan) into **one build**, and widens the edge cases from about 12 to **about 80**. They are grouped in §8, and each one has a planted resource or a rule, an expected output, and a test.

**The pitch in one line:** *a cloud cost tool that tells you what to shrink and, unlike every other tool, what it refused to shrink and why. Every rupee shows its formula, and every downsize is replayed against 30 days of real peaks.*

**The three signature features:**
1. **Rejections panel ("Checked and kept"):** every resource that *looks* wasteful on its average but was kept, with the signal that vetoed it.
2. **Peak Replay:** each resize is replayed on all 8,640 samples at the new size, with the result printed, e.g. "minutes above 90% CPU: 0".
3. **Engine Scorecard:** the generator writes `truth.csv` (true labels) and the app scores itself against it, e.g. "found 10/10 idle, 0 unsafe downsizes".

Supporting features: the Bill Growth Explainer (a waterfall of the +40%), the preset switcher, and the Assumptions page, which is rendered from the same `config.yaml` the engine reads.

The working folder `Transfinitte/` is empty, so this is a greenfield build.

---

## 1. Final tech stack (decided, no alternatives at build time)

| Layer | Pick | Why |
|---|---|---|
| Generator, engine | Python 3.11, numpy, pandas, pyarrow | Vectorised; about 1M rows generated in seconds |
| Forecast | statsmodels Holt-Winters (weekly season) | Explainable |
| Storage | Parquet + CSV + `config.yaml` on disk | Zero setup (DuckDB is only the "scale" story) |
| API | FastAPI + Pydantic, port 8000 | Free `/docs` page to show in the demo |
| UI | React + Vite + TypeScript + Tailwind + **Apache ECharts** (dataZoom on long series), port 5173 | Polished, and it can zoom from 30 days down to one morning |
| State | Accept/reject kept **client-side** (React state + localStorage) | No server write path, so less can break |
| Tests | pytest | Edge cases become golden tests |
| LLM (bonus) | Rule-based templates; optional "AI-phrased" rewrite | The LLM never produces a number |

**Out of scope:** Docker or Kubernetes for the app itself, real cloud APIs, auth, deployment, a time-series DB. If anyone proposes these at hour 20, the answer is no.

---

## 2. Architecture

```
 config.yaml ─────────────────────────────────────────────┐ (thresholds, presets, prices, switches —
 (single source of truth)                                 │  read by engine AND shown on Assumptions page)
        │                                                 ▼
 ┌─────────────┐   ┌─────────────┐   ┌──────────────┐   ┌──────────────────────────────────┐
 │ GENERATOR   │──▶│ CLEANER     │──▶│ FEATURES     │──▶│ ENGINE  (pure functions)         │
 │ seed=42     │   │ sort, dedupe│   │ p50..p99.5,  │   │ gates → non-compute → vetoes →   │
 │ inventory   │   │ range check,│   │ hour-of-week │   │ patterns → candidates → sizing → │
 │ metrics     │   │ grid, flat- │   │ profile,     │   │ PEAK REPLAY → floor → risk →     │
 │ billing_180d│   │ line → NaN  │   │ trends,      │   │ explanation + formula            │
 │ truth.csv   │   └─────────────┘   │ coverage     │   └───────────────┬──────────────────┘
 └─────────────┘                     └──────────────┘                   │ recommendations.json
        │ truth.csv (engine never reads)                                 │ (one object per resource,
        ▼                                                                ▼  verdict + options)
 ┌─────────────┐   ┌─────────────┐   ┌──────────────┐   ┌──────────────────────────────────┐
 │ SCORECARD   │   │ ALERTS      │   │ FORECAST /   │   │ COST MODEL                       │
 │ engine vs   │   │ MAD spikes, │   │ WHAT-IF /    │   │ per-resource combined cost,      │
 │ truth       │   │ trends, cost│   │ CARBON       │   │ never additive                   │
 └──────┬──────┘   └──────┬──────┘   └──────┬───────┘   └───────────────┬──────────────────┘
        └─────────────────┴────────┬────────┴───────────────────────────┘
                                   ▼
                    FastAPI (runs everything once at startup, holds results in memory;
                             preset change re-runs engine on cached features in ms)
                                   ▼
                    React UI — Overview · Utilization · Recommendations · Rejections ·
                               Alerts · What-if · Forecast & Green · Assumptions
                               (accept/reject + live totals computed in the browser)
```

**Why it's fast and simple:** the heavy work (cleaning, features, replay arrays) is done once. The engine reads a small features table plus the replay series, so changing a preset re-runs everything in well under a second.

---

## 3. Repo layout

```
smartcloud-optimizer/
├── README.md               setup, architecture, screenshots, scaling story + 1,000-VM benchmark
├── ASSUMPTIONS.md          generated from config.yaml + hand-written sections
├── config.yaml             EVERY threshold/price/switch, each with `why:` and `source:`
├── requirements.txt
├── backend/
│   ├── generator/  archetypes.py · planted.py · quality.py · billing.py · build.py
│   ├── pipeline/   clean.py · features.py
│   ├── engine/     gates.py · noncompute.py · vetoes.py · patterns.py · candidates.py
│   │               sizing.py · replay.py · risk.py · explain.py · decide.py (orchestrator)
│   ├── cost/       model.py (combined cost per option)
│   ├── insights/   alerts.py · forecast.py · whatif.py · carbon.py · scorecard.py · growth.py
│   ├── export/     report.py · scripts.py (bash dry-run + rollback, Terraform-style snippet)
│   └── api/main.py
├── tests/
│   ├── expected_outcomes.yaml   one row per planted edge case (§8)
│   ├── test_edge_cases.py       parametrised over expected_outcomes.yaml
│   ├── test_cost.py · test_quality.py · test_alerts.py
├── contracts/recommendation.json
├── data/            generated + committed (seeded); data/fixture/ = 3-resource sample (hour 2)
└── frontend/src/    pages/ · components/ (SummaryBar, Filters, RecCard, RejectionsPanel,
                     ResourceDrawer, ReplayChart, HourOfWeekHeatmap, AlertsPanel, WhatIf)
```

---

## 4. Data contracts (frozen in hour 0–2)

### 4.1 `inventory.csv`
`resource_id, name, type (vm|volume|ip), region, env, owner_team, purpose, service_group, plan_id, vcpu, ram_gb, disk_gb, provisioned_iops, bandwidth_mbps, state (running|stopped), stopped_since, created_at, last_resized_at, attached_to, unattached_since, optimize_policy, tags`

- `optimize_policy`: `default | never | no_schedule | review_only`
- `tags` (semicolon list): `stateful`, `dr_standby`, `autoscaled`, `allowlisted_ip`, `seasonal_peak`, `keep_running`
- Six teams: payments, search, platform, data, growth, mobile.

### 4.2 `metrics.parquet` (long format, **5-minute**, 30 days = 8,640 rows per VM)
`resource_id, ts (UTC), cpu_pct, mem_pct, disk_used_pct, iops, net_in_mbps, net_out_mbps`

Volumes have `iops` and `disk_used_pct` only. IPs have no metrics.

### 4.3 Pricing (`config.yaml`, **illustrative**, modelled on Utho's public Basic tiers, ex-GST)
| Plan | vCPU | RAM | ₹/month | Basis |
|---|---|---|---|---|
| S1 | 1 | 2 | 705 | assumption (half of B1) |
| B1 | 2 | 4 | 1,410 | Utho Basic 1 listing |
| B2 | 4 | 8 | 2,826 | Utho Basic 2 listing |
| B3 | 6 | 16 | 3,978 | Utho Basic 3 listing |
| B4 | 8 | 32 | 6,690 | Utho Basic 4 listing |
| B5 | 16 | 64 | 13,000 | assumption (fills the gap) |
| B6 | 24 | 96 | 25,962 | Utho Basic 6 listing |

Block volume costs ₹8/GB-month, a snapshot ₹4/GB-month and a public IP ₹200/month. A month is 730 hours. All regions are priced the same. There are no commitments, no egress charges and no GST.

**Switch:** `stopped_vm_billed: false`. Compute is free while stopped, but disk and IP are still billed. Confirm this with the Utho mentors.

Compute share of a VM = plan price. Its disk is billed separately as a volume.

### 4.4 Recommendation object (one per resource; the UI is built on this)
```json
{
  "resource_id": "vm-0007", "name": "dev-web-03", "env": "dev", "team": "growth", "region": "mumbai",
  "verdict": "recommend",            // recommend | reject | flag | exclude | healthy | upsize
  "actions": ["resize", "schedule"], // possible: resize, stop, delete, release, shrink_volume, schedule, upsize
  "current": {"plan": "B4", "vcpu": 8, "ram_gb": 32, "monthly_inr": 7490},
  "target":  {"plan": "B2", "vcpu": 4, "ram_gb": 8},
  "schedule": {"off_hours_per_week": 108, "windows": ["Mon-Fri 20:00-08:00", "Sat-Sun all day"]},
  "options": {                        // cost after, for every combination → no double counting
    "resize": 3626, "schedule": 3189, "resize+schedule": 1809
  },
  "evidence": {"cpu_p50": 4.1, "cpu_p95": 9.8, "cpu_p99": 12.0, "mem_p99": 24.3,
               "iops_p95_pct": 3, "net_p95_pct": 1, "coverage": 0.99, "days": 30},
  "replay": {"minutes_above_90_cpu": 0, "max_mem_pct": 62, "limit_minutes": 30, "passed": true},
  "veto": null,                       // e.g. {"signal": "memory", "value": 85, "threshold": 70}
  "risk": {"level": "Low", "points": ["dev +0", "coverage 99% +0"], "confidence": "High"},
  "reason": "CPU p95 9.8% and memory p95 24% over 30 days; B2 keeps replayed peak at 39%...",
  "formula": "₹7,490 − (₹2,826 × 60/168 + ₹800 disk) = ₹5,681/month",
  "trace": [{"step": "gate.history", "pass": true, "value": "30 d", "rule": "≥ 14 d"}]
}
```
The **Rejections panel** is simply `verdict in {reject, flag, exclude}`. It uses the same list and the same endpoint.

### 4.5 Recommendation schema v1.0 (authoritative; supersedes the sketch above)

**Corrected example numbers:** dev-web-03 uses mem p95 15% / p99 17%, so B2 is valid. At 24% memory it would need about 10 GB, which means B3.

**Envelope** (`GET /api/recommendations?preset=`):
`{schema_version, generated_at, preset, config_hash, data_window{start,end,timezone}, items[], below_floor{count, monthly_inr}}`

`items` contains **every** resource, healthy ones included. All pages filter this one list.

**Fields:**
| Group | Field | Notes |
|---|---|---|
| Identity | `rec_id` | `REC-<resource_id>-<preset>`, stable so browser-stored decisions survive reloads |
| Identity | `resource{resource_id, name, type, env, team, owner, region, purpose, service_group, members[], tags[]}` | |
| Decision | `verdict` | recommend \| reject \| flag \| exclude \| healthy \| upsize |
| Decision | `reason_code` | machine-readable cause; the Rejections panel groups by it |
| Decision | `actions[]` | `{type, order, description, requires[], reversible, rollback}`. Order: 1 snapshot/delete/release, 2 stop, 3 resize/shrink/upsize, 4 schedule |
| Decision | `default_option` | the option key the UI shows first |
| Decision | `flags[]` | `{code, message}`, non-terminal warnings: UNTAGGED_ENV, UNOWNED, TAG_NAME_CONFLICT, MEDIUM_COVERAGE |
| Cost | `current`, `target` | `{plan, vcpu, ram_gb, disk_gb, compute_inr, storage_inr, ip_inr, monthly_inr}`, split so scheduling saves compute only |
| Cost | `schedule` | `{timezone, off_hours_per_week, on_hours_per_week, windows[{days, start, end}], busy_hours_excluded}` |
| Cost | `options{key: {monthly_inr_after, saving_inr, formula}}` | key = accepted action types joined by "+" in apply order; always has "none" |
| Evidence | `evidence{window_days, days_of_data, coverage, peak_window_coverage, percentile_used, metrics{cpu, mem, iops_pct, net_pct, disk_used}, recurring_peak, naive}` | `naive` = what an average-based tool would do (the "would have cut this" line) |
| Safety | `replay{limit_minutes_above_90, mem_cap_pct, attempts[{plan, minutes_above_90, max_cpu_pct, max_mem_pct, passed}], passed, chosen_plan}` | |
| Safety | `veto{signal, metric, value, threshold, comparator, message}` | required when verdict = reject |
| Risk | `risk{level, score, points[{factor, points, detail}], confidence, confidence_basis}` | for recommend and upsize only |
| Explain | `reason`, `explanation_ai`, `formula`, `trace[{step, check, value, threshold, result, terminal}]`, `alert_ids[]` | |

**Browser total:** `after = Σ_resources options[key(accepted)].monthly_inr_after`. Each resource counts exactly once.

**reason_code values:**
- **recommend:** IDLE, UNDERUSED, OFF_HOURS, ORPHAN_VOLUME, OVERSIZED_VOLUME, UNUSED_IP, STOPPED_VM
- **reject:** VETO_MEMORY, VETO_IOPS, VETO_NETWORK, VETO_GROWTH, VETO_LEAK, VETO_RECURRING_PEAK, PEAK_REPLAY_FAILED, NO_CHEAPER_PLAN
- **flag:** ONE_OFF_PEAK, WENT_QUIET, RESERVED_MEMORY, PEAK_UNDER_OBSERVED, IDLE_PROD, IDLE_VOLUME_REVIEW
- **exclude:** POLICY_NEVER, TAG_DR_STANDBY, TAG_AUTOSCALED, TAG_SEASONAL, TAG_ALLOWLISTED_IP, STATEFUL_PROD, HISTORY_TOO_SHORT, RECENTLY_RESIZED, LOW_COVERAGE, ACTIVE_ANOMALY, NO_TELEMETRY, UNKNOWN_PRICE, ORPHAN_TOO_NEW
- **healthy:** RIGHT_SIZED
- **upsize:** UNDER_PROVISIONED

**Presence by verdict:**
- `veto` is set only on reject.
- `risk` is set only on recommend and upsize.
- `replay` is set on resize, upsize, and on a reject where the replay was the blocker.
- `naive` is set on reject.
- `evidence.metrics` is null for NO_TELEMETRY and HISTORY_TOO_SHORT.
- `trace`, `reason` and `formula` are always set.

**Related objects:**
- **Alert:** `{alert_id, type, severity, resource_id, title, why, evidence{metric, value, threshold, window}, first_seen, occurrences, suggested_action}`
- **Summary:** `{monthly_before_inr, potential_after_inr, potential_saving_pct, by_env, by_team, by_region, counts, bill_trend_6m, growth_waterfall}`. The "after accepted" total is computed in the browser.

---

## 5. Data generator

### 5.1 Bulk archetypes (about 75 VMs, random parameters, IST curves, ±5% day-to-day drift, AR(1) noise)
| Archetype | Count | CPU shape | Truth label / expected |
|---|---|---|---|
| right_sized_prod | 18 | 35–60%, peak 14:00 | healthy |
| steady_low (over-provisioned) | 15 | 8% ± 3% | resize |
| bursty_daily | 8 | 10% base, 09:30–10:15 at 75–90% | keep |
| batch_nightly | 6 | 2–4%, 01:00–03:00 at 85–95% | keep, never schedule over the window |
| office_hours_dev | 18 | weekdays 09–19 at 25–50%, else 2% | schedule |
| zombie | 6 | ~1.5%, network ≈ 0 | stop/delete |
| memory_bound | 4 | CPU 10%, memory 80–88% | keep RAM |

Signal realism:
- Memory is "sticky": a base level + 0.25 × CPU + noise.
- Network and IOPS = k × CPU + noise.
- 0.5% random drops, plus 20-minute reboot gaps on a few VMs.

**Names** follow the catalogue style (`prod-batch-07`), so the demo reads well. `resource_id` = `vm-0001…`.

### 5.2 Planted edge cases
These are the about 55 named resources in §8, each with a row in `tests/expected_outcomes.yaml` and in `truth.csv`.

### 5.3 Bill growth
`created_at` dates are spread over 9 months, with most dev and staging VMs created in the last 6. `billing_daily.parquet` holds 180 days, where each day = Σ(price ÷ 30) over every resource alive that day. Tune until month 6 ÷ month 1 ≈ **1.40**.

**Seed 42 everywhere.** The data is committed, so the video, README and live demo show identical numbers.

### 5.4 Size budget (estimated)

**Assumptions:** about 120 VMs × 8,640 samples ≈ 1.04M metric rows. Metrics are stored as float32 and `resource_id` as a category.

| File | Size |
|---|---|
| `metrics.parquet` (zstd) | ~15–25 MB |
| volume metrics | ~1–2 MB |
| `inventory.csv`, `truth.csv` | under 100 KB |
| `billing_daily.parquet` | under 1 MB |
| `features.parquet` | under 1 MB |
| `recommendations.json` | ~0.5–1 MB |

- **Total on disk:** about 20–30 MB. That is safe to commit.
- **RAM at runtime:** about 60–100 MB.
- **1,000-VM benchmark:** about 8.6M rows, ~150–200 MB of parquet. Generate it on demand and keep it gitignored.

**Public calibration data:** download Bitbrains GWA-T-12 fastStorage into `data/external/` (gitignored). It is used only to tune archetype parameters.

---

## 6. Pipeline: cleaning and features

**clean.py** (each step is counted in a per-resource data-quality report):
1. Snap timestamps to the 5-minute grid (floor), then sort.
2. De-duplicate on `(resource_id, ts)`, keeping the first.
3. Turn values outside [0, 100] for percentages, or negative values for rates, into NaN.
4. **Flatline detection:** an identical value repeated for ≥ 2 hours is a stuck agent, so turn it into NaN.
5. Reindex to the full grid. **Missing = NaN, never 0.**
6. `coverage = non-NaN / 8,640`, plus `peak_window_coverage` = the minimum coverage across the 168 hour-of-week buckets.

**features.py** (per resource):
- p50/p90/p95/p99/p99.5/max for cpu, mem, iops (% of provisioned) and net (% of bandwidth)
- `mean_cpu`, used for the "looks wasteful" test in the Rejections panel
- a 168-cell hour-of-week p95 CPU profile, kept per week
- `recurring_peak_days`: days whose 30-minute rolling mean exceeds 80%
- `p99_excl_top_day`: p99 recomputed without the busiest day
- `trend_slope` (linear fit of daily p95, for cpu/mem/disk) and `days_to_90`
- `level_shift_up` = mean of the last 48 hours ÷ mean of the prior 28 days
- `level_shift_down` = mean of the last 7 days ÷ mean of the prior 23 days
- `mem_flatness`: the standard deviation of memory, which detects a reserved heap
- `leak_score`: count of sawtooth cycles (memory climbs, then drops sharply)
- `days_of_data`, `coverage`, `peak_window_coverage`

The 5-minute series are kept in memory as numpy arrays for Peak Replay.

---

## 7. Engine: the decision pipeline

Every resource goes through the same ordered steps. Each check is appended to `trace[]`. The **first terminal verdict wins**. All comparisons are **strict `<` / `>`**, as stated in ASSUMPTIONS.

```
STEP 0  INVENTORY VALIDATION
        plan not in catalogue        → exclude  "price unknown — we never guess a price"
        no metrics at all            → exclude  + alert "monitoring missing"
        missing env tag              → treat as PROD (safest), flag "untagged"
        missing owner                → owner = "unowned", flag (still evaluated)
        name/tag env conflict        → trust tag, flag "inconsistent tags"

STEP 1  EXCLUSION GATES                                   → exclude
        optimize_policy = never | tag dr_standby | autoscaled | seasonal_peak
        tag stateful AND env = prod                         (stateful non-prod continues, with snapshot-first)
        days_of_data < 14 ; last_resized_at < 14 d ago
        coverage < 80%
        level_shift_up > 3× (anomaly in progress)          → exclude + anomaly alert

STEP 2  NON-COMPUTE & STOPPED (volumes, IPs, stopped VMs) → recommend / exclude
        (§8 group C rules; 7-day age gate; snapshot cost subtracted)

STEP 3  UNDER-PROVISIONED  cpu p99 > 90% or mem p99 > 90% → upsize (negative saving)

STEP 4  VETOES — any one blocks shrinking                 → reject (names the signal)
        mem p99 > 70%                                        "memory-bound"
        iops p95 > 70% of provisioned                        "disk-bound"
        net p95 > 60% of bandwidth                           "network is the workload"
        cpu trend: days_to_85 < 60                           "growing toward capacity"
        leak_score ≥ 3 cycles                                "memory leak suspected"

STEP 5  PATTERN CHECKS                                     → flag (human review)
        cpu p99 high but p99_excl_top_day low                "single event — one point is not a pattern"
        level_shift_down < 0.2 (busy, then quiet last 7 d)   "went quiet recently — confirm decommission"
        mem flat ≥ 75% with std < 2                          "memory reserved (heap?) — verify before RAM cut"
        peak_window_coverage < 50%                           "peak hours under-observed"
        idle AND env = prod                                  "idle prod — review with owner, never auto-stop"

STEP 6  CANDIDATES  (percentile P = p99 prod, p95 non-prod; preset can change)
        IDLE        cpu P < 5% AND mem P < 70% AND net < 5 MB/h AND iops p95 < 5  → stop (+ snapshot, delete after 14 d)
        UNDERUSED   cpu P < 40% AND mem P < 50%                                 → resize
        OFF-HOURS   non-prod, policy ≠ no_schedule, keep_running absent:
                    hour h is "off" if cpu p95 < 5% in EVERY week; merge into windows;
                    keep only blocks ≥ 4 h; need ≥ 40 off-h/week                → schedule
        none        → healthy (if mean_cpu < 20% → also listed in Rejections as "kept: peaks need it")

STEP 7  SIZING
        need_vcpu = vcpu × cpu_P / target_cpu   (70% prod, 80% non-prod)
        need_ram  = ram  × mem_P / target_mem   (75%)
        cheapest plan with vcpu ≥ need AND ram ≥ need   (ROUND UP)
        prod: max ONE plan step down per change
        service_group: size on the busiest member, same target for all
        target not cheaper than current → reject "no cheaper plan satisfies CPU and memory together"
        already smallest plan → no resize (stop/schedule only)

STEP 8  PEAK REPLAY (hard safety gate)
        cpu_new(t) = cpu(t) × vcpu_old/vcpu_new ; mem_new(t) = mem(t) × ram_old/ram_new
        pass if  minutes(cpu_new > 90%) ≤ 0 (prod) / 30 per month (non-prod)  AND  max(mem_new) ≤ 95%
        fail → try next bigger plan; none cheaper passes → reject "checked and kept: replay shows N min > 90%"

STEP 9  FLOOR  saving < ₹500/month → dropped, counted in "below floor (N items, ₹X)"
STEP 10 RISK + CONFIDENCE + EXPLANATION + FORMULA
```

### Thresholds (all in `config.yaml`, each with a source)
| Parameter | Value | Source / why |
|---|---|---|
| Lookback | 30 days | Above AWS Compute Optimizer's 14-day minimum; catches weekly cycles |
| Percentile | p99 prod, p95 non-prod | AWS default is P99.5; p99 is the conservative read |
| CPU target after resize | 70% prod, 80% non-prod | ≈ AWS 20–30% headroom |
| Memory target / hard cap | p99 ≤ 75%, no sample > 95% | OOM crashes; CPU only slows |
| Replay limit | 0 min > 90% prod, ≤ 30 min/month non-prod | Hard safety gate |
| Idle | CPU P < 5%, net < 5 MB/h, IOPS p95 < 5 | Industry consensus (Datadog, Azure Advisor) |
| Underused | CPU P < 40% and mem P < 50% | Leaves room after headroom |
| Vetoes | mem 70%, IOPS 70%, net 60% | Catalogue doc |
| Min data | 14 days; coverage ≥ 80% (80–95% allowed with lower confidence) | AWS minimum + our quality gate |
| Orphan age | 7 days | Avoids catching resources mid-setup |
| Stopped VM | > 30 days | Not a maintenance stop |
| Saving floor | ₹500/month | Not worth human attention below this |
| Prod step | one plan down per change | Small, reversible moves |

### Presets (dropdown; moves the total live)
| Preset | Percentile | CPU target | Replay limit |
|---|---|---|---|
| Max savings | p90 | 90% | 60 min |
| Balanced | p95 | 80% | 30 min |
| **Default** | p99 prod / p95 non-prod | 70 / 80% | 0 / 30 min |
| Max performance | p99.5 | 60% | 0 min |

### Risk points (every card lists which points fired)
| Factor | Points |
|---|---|
| env prod / staging / dev | +3 / +1 / 0 |
| stateful (non-prod) | +2 |
| projected p99 after change > 70% / 50–70% | +2 / +1 |
| bursty (p99 ÷ p50 > 3) | +1 |
| action is delete / stop | +2 / +1 |
| coverage < 95% | +1 |

**Buckets:** 0–2 Low, 3–4 Medium, 5+ High.

**Confidence:** High if coverage ≥ 95% and weekly p95 varies less than 10% between weeks. Medium otherwise. Low means insufficient data.

---

## 8. Edge-case catalogue (about 80 cases; every row is a test)

Legend: **R** = reject, **F** = flag, **X** = exclude, **H** = healthy, **Rec** = recommend, **U** = upsize.

### A. Workload shape and peak behaviour (compute)
| # | Case | Planted as | Naive tool would… | Our output (signal) |
|---|---|---|---|---|
| A1 | Healthy right-sized prod | prod-api-01 (p95 70%) | — | **H** |
| A2 | Over-provisioned steady prod | prod-api-07 (B4, p99 31%, mem 15%) | jump to B2 | **Rec** B4→B3 (prod one-step), replay 0 min |
| A3 | Nightly batch spike | prod-batch-07 (mean 8%, 02:00 at 92%) | shrink | **R** "recurring peak 02:00, replay 40 min/day > 90%" |
| A4 | Weekly spike (Sunday) | prod-billing-01 | shrink (7-day window) | **R** weekly peak; justifies 30 days |
| A5 | Weekly 1-hour job that p99 misses | dev-report-02 (p99 22%) | shrink to B1 | **R** via **replay** "4 h/month > 90%" |
| A6 | Single monthly spike | prod-reports-02 (95% on the 1st) | ignore or shrink | **F** "1 event in 30 d; may be a month-end job; needs 90 d" |
| A7 | Daily morning burst | prod-checkout-03 (avg 14%, p99 86%) | shrink | **R** "replay 172% every morning" |
| A8 | Unscheduled bursts | prod-queue-02 | shrink | **R** replay; listed as "kept: bursts need headroom" |
| A9 | Memory-bound | prod-cache-04 (CPU 5%, mem p99 85%) | shrink → OOM | **R** memory veto |
| A10 | Flat reserved memory (JVM heap) | prod-search-06 (mem 78% flat) | shrink or always keep | **F** "memory reserved, not proven used" |
| A11 | Memory leak sawtooth | prod-orders-08 | — | **R** leak veto + leak alert |
| A12 | Disk/IOPS-bound, stateful | prod-db-01 | shrink | **X** stateful prod (IOPS note in trace) |
| A13 | IOPS-bound, stateless | prod-ingest-09 | shrink | **R** IOPS veto (shows the veto works without a tag) |
| A14 | Network-bound proxy | prod-gateway-03 | stop as idle | **R** network veto |
| A15 | Growth trend | prod-api-04 (CPU 20→65%) | shrink on average | **H** + capacity alert with ETA |
| A16 | Under-provisioned | prod-search-02 (p99 96%) | — | **U** (negative saving, shown separately) |
| A17 | Being decommissioned (quiet last 8 days) | prod-legacy-06 | keep (30-day p99) | **F** "went quiet; confirm decommission" |
| A18 | CPU low but RAM high-ish: no cheaper plan fits both | prod-ml-10 (8 vCPU/32 GB, CPU 10%, mem 60%) | shrink CPU, OOM | **R** "no cheaper plan satisfies both" |
| A19 | Already the smallest plan | dev-tiny-14 (S1, CPU 2%) | "resize" to nothing | stop/schedule only |
| A20 | Sizing lands between plans | staging-web-08 (needs 3 vCPU) | round down | **Rec** B2 (4 vCPU), rounded **up** |
| A21 | Exactly on threshold | staging-api-09 (p99 = 40.0%) | inconsistent | **H** (strict `<`) |
| A22 | Saving below floor | dev-tiny-15 (₹300) | pads the list | dropped, counted in "below floor" |
| A23 | Load-balanced service group | prod-web-11a/b/c | resize nodes differently | one group rec; size on the busiest member |
| A24 | Autoscaler or K8s node | prod-k8s-node-1..3 | resize a node | **X** "rightsize the node pool, not the node" |
| A25 | Seasonal (festive sale) | prod-checkout-01 tag `seasonal_peak` | shrink in a quiet month | **X** "peak outside the 30-day window" |
| A26 | Upsize-only cheaper? (needs RAM ↑, CPU ↓) | rule | — | recommend only if cheaper, else **R** |

### B. Idle and scheduling
| # | Case | Planted as | Our output |
|---|---|---|---|
| B1 | Idle staging (stateful, non-prod) | staging-db-02 (1%) | **Rec** snapshot → stop → delete after 14 d |
| B2 | Idle prod | prod-old-12 | **F** "review with owner", never auto-stop |
| B3 | CPU idle, memory resident | dev-cache-13 (CPU 2%, mem 60%) | not idle; schedule if quiet hours exist |
| B4 | Dev idle nights and weekends, oversized | dev-web-03 | **Rec** resize + schedule, combined cost |
| B5 | Dev with nightly job inside the off window | dev-etl-04 (01:00–03:00 job) | schedule window excludes 01–03 (derived from profile) |
| B6 | Night-shift team | dev-support-05 (busy 22:00–06:00) | **daytime** window, proving windows are per-VM |
| B7 | Weekend-only load test | staging-load-06 | weekdays off, weekends on |
| B8 | Prod quiet at night | bulk prod | never scheduled (prod excluded) |
| B9 | Fragmented off-hours (< 4 h blocks or < 40 h/week) | dev-misc-07 | no schedule ("start/stop churn not worth it") |
| B10 | `keep_running` tag (sales demo env) | staging-demo-10 | excluded from scheduling |
| B11 | `stopped_vm_billed: true` | config switch | schedule recs suppressed, with a note |
| B12 | Zombie (CPU 1.5%, network ≈ 0) | bulk zombies | **Rec** stop → snapshot → delete |

### C. Non-compute (volumes, IPs, stopped VMs)
| # | Case | Planted as | Our output (severity) |
|---|---|---|---|
| C1 | Unattached volume, 60 d | vol-orphan-11 | **Rec** snapshot + delete (High); saving = vol − snapshot |
| C2 | Unattached volume, 2 d | vol-new-12 | ignored (7-day age gate) |
| C3 | Attached, zero IOPS for 30 d | vol-idle-04 | **F** review (Medium) |
| C4 | Attached to a VM stopped 45 d | vol-stopped-07 | **Rec** with its VM (Medium) |
| C5 | Oversized: 500 GB, 40 GB used | vol-oversized-09 | **Rec** migrate to a 100 GB volume (Medium; no in-place shrink) |
| C6 | Oversized but growing 2%/day | vol-growing-10 | **R** growth veto + disk alert |
| C7 | IP never associated | ip-unused-03 | **Rec** release (Medium) |
| C8 | IP on a stopped VM | ip-stopped-02 | **Rec** release (Low), grouped with C10 |
| C9 | IP unassociated but allowlisted by a bank or payment gateway | ip-allowlist-04 | **X** "the same IP can't be re-acquired" |
| C10 | VM stopped 45 d | vm-stopped-07 | **Rec** snapshot + delete; saving = disk + IP − snapshot |
| C11 | VM stopped 3 d | vm-maint-08 | ignored (maintenance) |

### D. Lifecycle and inventory
| # | Case | Planted as | Our output |
|---|---|---|---|
| D1 | Created 3 days ago | dev-test-12 | **X** "< 14 days" |
| D2 | Resized 6 days ago | staging-app-05 | **X** "pre-change data describes a different machine" |
| D3 | DR warm standby | prod-standby-01 | **X** tag; "telemetry alone is insufficient" |
| D4 | No metrics (agent missing) | prod-nomon-13 | **X** + alert "monitoring missing" |
| D5 | Missing env tag | vm-untagged-14 | treated as **prod**, flagged |
| D6 | Missing owner | dev-orphan-owner-15 | evaluated, owner "unowned", flagged |
| D7 | Name says dev, tag says prod | dev-misnamed-16 | trust tag, flag inconsistency |
| D8 | Legacy plan not in catalogue | prod-legacy-plan-17 | **X** "price unknown" |
| D9 | Metrics without inventory, or the reverse | 1 stray series | listed in data-quality report |
| D10 | Active anomaly (4× jump on day 29) | prod-worker-05 | **X** from sizing + anomaly alert |

### E. Data quality
| # | Fault | Planted in | Handling |
|---|---|---|---|
| E1 | 6-hour gap | prod-api-02 | NaN, not 0; not called idle |
| E2 | Duplicate timestamps | dev-web-03 | dedupe |
| E3 | CPU 103% / −2% | 3 VMs | dropped |
| E4 | Out-of-order rows | 2 VMs | sorted |
| E5 | 0.5% random drops + 20-min reboot gaps | bulk | tolerated |
| E6 | Coverage 70% | dev-flaky-18 | **X** "insufficient data quality" |
| E7 | Coverage 88% | staging-flaky-19 | evaluated, confidence Medium, +1 risk |
| E8 | Stuck agent reports 0.0 for 2 days | dev-api-16 | flatline → NaN (otherwise looks idle) |
| E9 | Gap lands on the peak window (10 of 30 batch nights missing) | prod-batch-20 | **F** "peak hours under-observed" |
| E10 | Irregular timestamps (05:03) | 1 VM | snapped to grid |
| E11 | Timezone | all | stored UTC; off-hours and charts in IST |

### F. Cost math
| # | Case | Rule | Test |
|---|---|---|---|
| F1 | Resize + schedule overlap | cost_after = target_price × on_h/168 + disk + IP | dev-web-03 combined < sum of the two separate savings |
| F2 | Accept only one of resize/schedule | UI picks `options[accepted set]` | each combination matches |
| F3 | Delete/stop | saving = cost − snapshot cost | vol-orphan-11 |
| F4 | Upsize | negative saving in a separate "risk fixes" line; gross, cost and net all shown | prod-search-02 |
| F5 | Rounding | round each option to ₹1; total = sum of cards | exact equality |
| F6 | Scheduling saves compute only | disk and IP keep billing | formula string |
| F7 | Stopped-billing switch | b = 0 or 1 | toggle test |
| F8 | Preset changed after accepting | decisions keyed by (resource, action, target); reset with a toast if the target changed | UI test |
| F9 | Plausibility | default-preset headline must be **15–35%** of the bill | pytest band |
| F10 | Service-group rec | saving = Σ members | A23 |

### G. Alerts
| # | Case | Rule | Planted |
|---|---|---|---|
| G1 | Spike vs the same hour in other weeks | > median + 4×MAD for ≥ 30 min | prod-reports-02 |
| G2 | Batch spike at its usual hour | baseline is hour-of-week, so **no alert** | prod-batch-07 |
| G3 | Level shift | last 48 h > 3× the prior 28 d | prod-worker-05 |
| G4 | Miner-like compromise | CPU 98% + 10× network out from day 26 → **Critical** "possible compromise" | dev-sandbox-17 |
| G5 | Capacity trend (cpu/mem/disk) | linear fit of 14 d; days to 90% < 30, with ETA | prod-api-04, vol-growing-10, 4 bulk disks |
| G6 | Memory leak | sawtooth cycles ≥ 3 | prod-orders-08 |
| G7 | Team cost jump | daily cost > 1.2 × its 7-day average; names the new resources | growth team, day 22 |
| G8 | Budget overrun | spent + run-rate × days left > team budget | data team |
| G9 | Under-provisioned | CPU p99 > 90% | prod-search-02 |
| G10 | Monitoring missing | no metrics | prod-nomon-13 |
| G11 | De-duplication | one alert per (resource, type) with an occurrence count | — |

**Severity:**
- **Critical:** a prod anomaly, a possible compromise, budget overrun > 10%, or capacity < 7 days.
- **Warning** and **Info** for the rest.

Every alert has a `why` sentence built from real numbers and links to its chart with the problem window shaded.

### H. Known limitations (stated, not built)
- Single-thread bottlenecks are hidden by aggregate CPU %.
- CPU is assumed to scale linearly with vCPU count. Headroom, the prod one-step rule and easy rollback cover the error.
- Yearly seasonality is not visible in 30 days; the `seasonal_peak` tag covers it.
- There are no reserved commitments or egress charges, and prices are illustrative.
- Resizing usually needs a reboot, so prod recs say "apply in maintenance window".

---

## 9. Cost model (no double counting)

- **Before** = Σ the current monthly cost of every resource.
- **After** = Σ, per resource, `options[accepted action set]`. A resource with nothing accepted keeps its current cost.
- **One resource contributes exactly once.** Overlapping actions never add up.
- Breakdowns: per recommendation, environment, team and region, plus the total. Upsizes appear on a separate line.
- **Every card shows its formula string**, e.g. "₹6,690 − ₹3,978 = ₹2,712/month".

---

## 10. API (all read-only; accept/reject lives in the browser)

```
GET  /api/resources?region=&env=&team=&type=         fleet table + p95/p99 + sparkline
GET  /api/resources/{id}                             inventory + features + trace + DQ report
GET  /api/resources/{id}/metrics?metric=&step=5m|1h  hourly mean+max by default (keeps peaks)
GET  /api/resources/{id}/replay                      actual vs projected series
GET  /api/recommendations?preset=default             recommendation objects (the contract)
GET  /api/summary                                    bill now, 6-month trend, growth waterfall, counts
GET  /api/alerts
GET  /api/forecast?days=90
POST /api/whatif     {"env":"dev","off":"20:00-08:00","weekends":true} → saving + VMs it would break
POST /api/export     {"accepted":[...], "format":"csv|md|sh|tf"}
GET  /api/scorecard  · GET /api/data-quality · GET /api/assumptions
```

CORS is enabled for `localhost:5173`.

---

## 11. UI pages (role switch: Engineer, Finance, Leadership)

1. **Recommendations (Engineer):**
   - A table showing action, resource, reason, saving, a risk chip and an accept/reject toggle.
   - A **sticky SummaryBar** showing ₹ before → after, with bars per environment, updating on every click.
   - A drawer per row with the evidence, formula, risk points, **Peak Replay chart** (grey = actual, blue = projected, red dashed line at 90%) and the script snippet.
2. **Rejections ("Checked and kept"):** grouped by vetoing signal (memory, IOPS, network, recurring peak, replay, stateful, tag, insufficient data, flagged for review). Each row says "an average-based tool would have cut this".
3. **Utilization (Engineer):**
   - Filters for region, env, team, type and verdict.
   - A fleet table with sparklines.
   - A resources × days heatmap.
   - Drill-down: CPU, memory, disk and network over 30 days with p50/p95/p99 lines, a 7×24 hour-of-week heatmap and the decision trace (✓/✗ for each rule).
4. **Overview (Leadership):**
   - KPIs: monthly bill, +40% trend, waste ₹, potential saving, CO₂.
   - The **Bill Growth Explainer** waterfall (growth by team, env and new resources).
   - The "Monday morning list": top 5 actions, low risk and high saving first.
5. **Alerts:** sorted by severity, with the why text and a shaded chart.
6. **What-if (Finance):** choose an environment, off window and weekends, then see the saving and the VMs it would disrupt.
7. **Forecast & Green:** 90-day forecast with and without accepted actions, plus kWh and kg CO₂ saved. Coefficients come from the Cloud Carbon Footprint methodology: 0.74–3.5 W per vCPU, 0.392 W/GB, PUE 1.4, India grid ≈ 0.71 kg/kWh (CEA).
8. **Assumptions:** prices, thresholds, switches, presets and generator logic rendered from `config.yaml`, plus the **Engine Scorecard** (precision and recall per archetype).

**Design rules:**
- `Intl.NumberFormat('en-IN')` everywhere, so amounts read like ₹1,23,456.
- Green = saving, amber = Medium risk, red = High risk. Every colour is paired with a word.
- Every number has a "how computed" tooltip.

---

## 12. Team (4 people) and the 40-hour timeline

| Person | Owns | Helps later |
|---|---|---|
| **A — Data** | generator, archetypes, planted cases (§8), quality faults, billing history, truth.csv, data half of ASSUMPTIONS | engine tests from h10 |
| **B — Engine** (strongest logician) | features, gates, vetoes, patterns, sizing, **Peak Replay**, risk, cost options, thresholds half of ASSUMPTIONS | owns judge Q&A |
| **C — API + UI shell** | FastAPI, React scaffold, filters, state, accept/reject, SummaryBar | finishes UI after h28 |
| **D — Visuals + submission** | ECharts components, drill-down, Replay chart, **Rejections panel**, styling | video + README from h28 |

| Phase | Hours | Work | Gate (cut scope if it fails; never extend) |
|---|---|---|---|
| 0 Contracts | 0–2 | all four: freeze §4; A commits the 3-resource fixture; C gets both servers talking | fixture renders in the browser |
| 1 Foundations | 2–10 | A: archetypes + planted A/B/C/D cases. B: clean + features + gates on the fixture. C: filters and table on mock JSON. D: drill-down chart | prod-batch-07 plotted: mean ≈ 8%, p99 ≈ 92%; 3 archetypes eyeballed |
| 2 Core engine | 10–18 | B: vetoes, patterns, sizing, replay, risk, cost options. A: quality faults (E) + edge-case YAML, then pairs with B. C: real API. D: Rejections panel | **`pytest test_edge_cases.py` green on groups A–E** |
| 3 Integration | 18–24 | live totals, before/after per env, alerts (G), Bill Growth Explainer | full end-to-end demo path (ugly is fine) |
| 4 Depth | 24–32 | bonuses in order: preset switcher → what-if → export → forecast → carbon → scorecard UI → role views; polish | **h32 feature freeze** |
| 5 Submission | 32–38 | D: video (3–4 takes). README tested on a clean machine. ASSUMPTIONS final. 1,000-VM benchmark | everything submitted except final checks |
| 6 Buffer | 38–40 | deliberately empty | — |

**Sleep:** two people rest from about h14–20 and the other two from about h20–26. Post a message in the shared channel at every gate.

---

## 13. Cut lines (decided now)

Cut in this order if you fall behind:
1. Forecast
2. Terraform export
3. Role views
4. Carbon
5. What-if
6. Preset switcher (hardcode Default)
7. Alerts reduced to a static list
8. Edge cases reduced to the demo core: A3, A9, A12, A17, B4, B1, C1, C7, D3, D10, E1
9. One chart type in the drill-down

**Never cut:** the Rejections panel, Peak Replay, the live total, ASSUMPTIONS, the video.

**Risks:**
- Generator slips → ship the demo-core cases first.
- npm conflicts → freeze `package.json` after h2.
- Totals look too large → the F9 band test catches it.
- Data looks fake → plot it at h10.
- Video left to the end → hard start at h32.

---

## 14. Verification

- `pytest`: parametrised over `expected_outcomes.yaml`. Every case in §8 must match its **verdict + vetoing signal + action**.
- Cost tests: F1–F10, including the **total equals the card sum to the rupee**.
- Quality tests: a 6-hour gap is never "idle", and a flatline becomes NaN.
- Alert tests: G1–G11 fire or stay silent as specified.
- Scorecard: 100% recall on zombies and orphans, and **0 resizes that fail replay**.
- Reproducibility: `python -m backend.generator.build` twice gives an identical hash.
- Scale: generate 1,000 VMs, time the engine and write the figure in the README.
- Manual run of the app:
  - drill into prod-batch-07 and see the 02:00 spike and rejection
  - accept dev-web-03 and watch the total move by exactly the combined option
  - switch the preset and watch the total move
  - run the "dev off 20:00–08:00" what-if and see dev-etl-04 listed as disrupted
  - export `apply.sh`
- Fresh-clone test by someone who didn't write the README.

---

## 15. Demo video (6 minutes)

| Time | Show | Key line |
|---|---|---|
| 0:00–0:45 | +40% bill trend, Bill Growth Explainer | "Most of the growth is dev and staging created since May." |
| 0:45–1:30 | The data: archetypes, planted traps, injected faults | "Real monitoring data is dirty, so ours is too." |
| 1:30–3:30 | Utilization → prod-checkout-03 drill-down → Recommendations → accept dev-web-03, totals move → **Rejections: prod-batch-07** (rehearse this) → Peak Replay chart | "Mean 8%. p99 92% at 2 AM. We refuse." |
| 3:30–4:15 | Alerts: miner-like dev-sandbox-17, prod-api-04 ETA | "30× its normal 2 AM level." |
| 4:15–5:15 | Architecture diagram, `/docs`, Assumptions page, **scorecard** | "Every number has a formula; 0 unsafe downsizes." |
| 5:15–6:00 | Headline ₹/month and ₹/year (in the 15–35% band), CO₂, limitations | "Open on Monday, act before lunch." |

---

# Appendix: Public datasets considered (for calibration)

These figures are approximate and were written from memory. Check size, columns and licence on each download page before citing them.

| Dataset | Scale | Metrics | Approx. size | Free? | Fit |
|---|---|---|---|---|---|
| **Bitbrains GWA-T-12** (TU Delft GWA) | fastStorage ~1,250 VMs, 1 month; Rnd ~500 VMs, 3 months; ~5-min | CPU cores/MHz/%, memory KB, disk read/write KB/s, network rx/tx KB/s | hundreds of MB to ~1 GB | Yes (research) | **Best fit**: tune archetypes; optional real-data demo |
| **Materna GWA-T-13** | ~500+ VMs, 3 months, 5-min | Similar to Bitbrains | hundreds of MB | Yes (research) | Good second source |
| **Azure Public Dataset** V1 (2017) / V2 (2019) | ~2M+ VMs, 30 days, 5-min | CPU min/avg/max, VM size and category | ~100+ GB full; chunked downloads | Yes (CC-BY) | CPU shape reference only |
| **Google cluster-data 2011** | ~12.5K machines, 29 days | task CPU and memory | ~40 GB compressed | Yes | Weak (tasks, not VMs) |
| **Google cluster-data 2019** | 8 clusters, 1 month | task CPU and memory | ~2.4 TB (BigQuery) | Data free; BigQuery may cost | Avoid |
| **Alibaba cluster trace 2018** | ~4K machines, 8 days | machine CPU %, mem %, net, disk I/O % | tens to hundreds of GB | Yes | Weak (containers) |
| **Live cloud APIs (Utho)** | real fleet | everything | — | — | Out of scope; swappable loader later |

**Bitbrains needs conversion:**
- memory % = usage KB ÷ provisioned KB
- disk is throughput, not IOPS
- no env, team or region tags and no prices
- no truth labels

**Decision:**
- Synthetic data is primary, because it gives known answers.
- Calibrate against Bitbrains and Azure published statistics.
- Keep external data in gitignored `data/external/`.
