# Backend ↔ frontend integration plan (rev 3; review round 3: SATISFACTORY)

**Status (2026-10-24): implemented (I0–I8).**
- `pytest`: 491 pass.
- The shape diff is 0 / 0 on every endpoint and fixture.
- `check_fixtures.mjs` passes 5,854 checks on the live API.
- The frontend typechecks, its unit tests pass and it builds.
- Live e2e: 53 pass, and the 11 failures are exactly the §9 lines. With the §9 edits (scratch copy only, not in the repo) 64 of 64 pass.

One deviation from E4: `to_plan` = chosen plan, else the last attempt's plan, else the naive target, so the chart and the attempts describe the same machine. Details are in `PLAN_final.md` B11.

**Goal:** the frontend on `main` (`frontend/`) runs against the real backend (`backend/`) with no fallback data. Every endpoint returns exactly the shape **and the text formats** the frontend reads. The numbers come from our engine and the current dataset.

**Decided by the project owner (2026-10-24):**
- `backend/engine/` is the recommendation engine that serves the UI. `engine/` is not used by the API.
- **The dataset (`data/`, `generator/`) is not changed.**
- **The frozen §4.5 schema is extended** where the frontend needs it (§3 lists every extension).
- **Stray series:** `vm-9999` has no inventory row, and its name exists only in `truth.csv`, which the engine must never read. So its `name` is the id, `vm-9999`. (§9 covers how `faults.csv` handles it.)
- **Carbon:** placeholder coefficients go into `config.yaml`, marked as placeholders. The limitation is recorded as future scope.
- **Frontend code is not changed.** The test edits in §9 need the owner's approval.

## 1. Sources of truth
| Question | Authority |
|---|---|
| Response shapes, field names, types, nullability | `frontend/src/types/contract.ts`, `frontend/src/types/api.ts`, `frontend/API_CONTRACT.md` |
| Text formats the UI parses or the tests match (schedule windows, formulas, veto metrics, alert metrics and wording, threshold names) | `docs/reference/mock_engine.py`, the generator of the frontend's fallback data, and `frontend/e2e/*.spec.ts`. We copy its **formulas and templates**, never its verdicts: the mock copies verdicts from `truth.csv` |
| Verdicts, reason codes, options, sizing, replay | Our engine (`backend/engine/`) |
| Thresholds, prices, presets, switches | `config.yaml` |

**Definition of done:**
- A shape diff of every endpoint against the frontend fixtures (`frontend/fallback/api/**`, merged over all list items) reports **0 MISSING and 0 TYPE** fields.
- Every API_CONTRACT rule in §7 holds.
- The frontend's `check_fixtures.mjs` passes on a dump of the live API (mechanism in §8 I7).
- The frontend typechecks, its unit tests pass, and it builds.
- `pytest` is green.
- **`npm run verify:live` (E2E_LIVE=1):**
  - If the §9 edits are approved and applied, the whole suite passes.
  - If they are not, every failure is on a line listed in §9.

  This needs Chromium; the download timed out on this machine. Until it runs, I7 records it as not run, never as passed.

## 2. Engine changes (`backend/engine/`)
1. **Presets.** Enable all four presets, with values from plan §7 (the mock's `PRESETS`):

   | Preset | Prod / non-prod percentile | CPU target | Replay limit |
   |---|---|---|---|
   | max_savings | p90 / p90 | 90 / 90 | 60 / 60 min |
   | balanced | p95 / p95 | 80 / 80 | 30 / 30 min |
   | default | p99 / p95 | 70 / 80 | 0 / 30 min |
   | max_performance | p99.5 / p99.5 | 60 / 60 | 0 / 0 min |

   - Numeric values go into `config.yaml`. `params_for()` returns them, and the engine runs once per preset at startup.
   - The memory target (75%) and cap (95%) are fixed across presets.
   - **Truth only covers `default`.** The other presets must validate against the schema and keep every safety rule.
   - **cp13 depends on the data:** between `default` and `max_performance` it needs at least one retargeted, one dropped and one unchanged recommend item. I2 checks that this holds.
2. **Codes emitted directly.** These replace the old mapping:
   - `healthy / BELOW_FLOOR` (dev-tiny-15)
   - `exclude / STOPPED_RECENTLY` (vm-maint-08)
   - one item per metrics series with no inventory row: `exclude / NOT_IN_INVENTORY` (vm-9999). It has `name` = the id, `type: "vm"`, `env`/`team`/`region`/`purpose`/`service_group`/`state`/`plan_id` = null, `current` all zeros with plan null, options `{none}`, `metrics` null, and a trace that ends at step `inventory.exists`.

   `insights/scorecard.py` drops its `CONTRACT_MAP`.
3. **Naive cut and replay for rejects and flags** (mock `build_recs` lines 742–759). For every `reject` or `flag` VM with metrics and a catalogue plan:
   - `need = vcpu × mean CPU / 80` (fixed at 80% in every preset, as the mock does; vCPU only).
   - The first plan with `vcpu ≥ need`. If it is cheaper, `naive = {action: "resize", target_plan, saving_inr = price difference, basis: "average CPU x.x%", replay_minutes_above_90}`. If the item has no replay yet, its `replay` becomes that single attempt (`passed` false, `chosen_plan` null).
   - Otherwise `naive = {action: "stop" if mean < 5 else "none", target_plan: null, saving_inr: compute if stop else 0, basis, replay_minutes_above_90: null}`.
   - Volume rejects and flags: `{action: "shrink_volume", target_plan: null, saving_inr: (disk_gb − 100) × ₹8, basis: "NN% used today", replay_minutes_above_90: null}`.
   - **A `replay` block is only ever present when it has ≥ 1 attempt.** Otherwise it is null, so the UI never asks `/replay` and gets a 404.
4. **`replay` block:** add `from_vcpu` and `from_ram_gb` (the current plan).
5. **`evidence` block:**
   - `percentile_used` is a string (`"p99"`, `"p95"`, `"p90"`, `"p99.5"`; env-effective, with untagged counting as prod) on every item.
   - Each metric leaf is `{mean, p50, p95, p99, max}`, or **null when that metric has no data**. Volumes: `cpu`, `mem` and `net_pct` are null.
   - **`metrics` itself is null when the resource has no telemetry.** That covers NO_TELEMETRY, HISTORY_TOO_SHORT, IPs, stopped VMs without metrics and the stray series, as in the mock. This replaces the old rule "null only for NO_TELEMETRY / HISTORY_TOO_SHORT".
   - `recurring_peak = {window_ist, days}`, set only when a recurring peak was detected. `window_ist` = the E2 `recurring_window` text, and `days` = the number of peak days.
6. **`resource` block:**
   - Add `state` and `plan_id`.
   - `env`, `team`, `purpose`, `service_group`, `region`, `state` and `plan_id` are **null when empty**. `owner` stays `"unowned"`.
   - `members` = the **names** of all members of the service group, including itself. The UI groups rows when `members.length > 1`.
7. **`trace`:**
   - `value` and `threshold` are **always strings**. The UI calls `.value.match(...)`.
   - `result` ∈ `pass | fail | info | skip`.
   - Exactly one step is terminal.
   - The sizing step is called **`sizing`**. For a service-group member its value contains `sized on <busiest member name>`.
   - The step ids already contain `veto.recurring_peak`, which the tests look up as a substring. Keep that.
8. **`actions[].rollback`:** always a string.
9. **Envelope:** `mock_engine: false`.
10. **Schedule text** (copy the mock's `describe_blocks` lines 323–340 and `busy_excluded` lines 343–353; `Drawer.tsx:204` splits on `' → '`):
    - Identical blocks shorter than 24 h are **grouped across days**: `{days: "Mon–Thu", start: "19:00", end: "09:00 (next day)"}`. `(next day)` is added when the block crosses midnight, and `days` uses an en dash and `day_ranges`.
    - Blocks of 24 h or more are written `{days: "Fri → Mon", start, end}`, with spaces around the arrow.
    - `busy_hours_excluded` = night hours (20:00–08:00) that are busy on ≥ 4 of 5 weekdays, written `"01:00–03:00 daily"`.
    - `off_hours_per_week` and `on_hours_per_week` are integers.
    - Our block detection is unchanged; only the presentation changes.
11. **Option formula templates** (copy the mock, lines 669–706; cp05:24 matches on `× 50/168 h on`):
    - `now = "₹<compute> <plan> + ₹<storage> disk = ₹<current>"`
    - resize/upsize: `"<now> → ₹<target compute> <target plan> + ₹<storage> disk = ₹<after>"`
    - schedule: `"<now> → ₹<compute> × <on>/168 h on + ₹<storage> disk = ₹<after>"`
    - resize+schedule: `"<now> → ₹<target compute> <target plan> × <on>/168 h on + ₹<storage> disk = ₹<after>"`
    - snapshot+stop: `"<now> → ₹<storage> disk kept + ₹<snap> snapshot (<GB> GB × ₹4) = ₹<after>"`
    - stop: `"<now> → compute ₹0 while stopped + ₹<storage> disk = ₹<storage>"`
    - stopped-VM delete: `"₹<storage> disk billed while stopped → ₹<snap> snapshot (<GB> GB × ₹4) after delete"`
    - volume delete: `"<size> GB × ₹8 = ₹<cost> → snapshot <GB> GB × ₹4 = ₹<snap>"`
    - volume shrink: `"<size> GB × ₹8 = ₹<cost> → <new> GB × ₹8 = ₹<after> (<used> GB used)"`
    - IP release: `"₹200/month public IP → ₹0"`
    - `none`: `"₹<current>/month, no change"`

    The amounts are ours. The top-level `formula` = the default option's formula.
12. **Veto normalisation** (copy the mock, lines 761–787; `kept.ts:31` renders `` `${metric}: ${value} (rule ${comparator} ${threshold})` ``, and cp06:31 expects `days with a 30-min peak > 80%: 30`):

    | Code | signal | metric | value | threshold | comparator |
    |---|---|---|---|---|---|
    | VETO_MEMORY | memory | `mem p99` | mem p99 | 70 | `>` |
    | VETO_IOPS | iops | `iops p95 % of provisioned` | value | 70 | `>` |
    | VETO_NETWORK | network | `net p95 % of bandwidth` | value | 60 | `>` |
    | VETO_LEAK | leak | `sawtooth cycles` | leak cycles | 3 | `≥` |
    | VETO_RECURRING_PEAK | recurring_peak | `days with a 30-min peak > 80%` | number of peak days | 3 | `≥` |
    | PEAK_REPLAY_FAILED | replay | `minutes above 90% CPU` | worst attempt's minutes | replay limit | `>` |
    | NO_CHEAPER_PLAN | sizing | `RAM needed (GB)` | needed RAM, 1 dp | largest RAM among cheaper plans | `>` |
    | VETO_GROWTH | growth | `days until disk 85% full` / `days until CPU 85%` (our engine measures 85%) | days, rounded | 60 | `<` |

    Thresholds come from config. `message` uses the mock's sentences with our numbers, and `reason` = `message` for rejects (as in the mock).

    For VETO_RECURRING_PEAK, our rule is "the same IST hour-of-week peaks in ≥ 3 weeks, and p99 ≥ 80". `value` is the number of peak days (cp06:31). `threshold` 3 is that 3-week rule, and the `message` says so in words.
13. **Schema** (`backend/api/schemas.py`): update to all of the above, plus the `Alert` model (§4 E7), keeping `extra="forbid"`. Presence rules:
    - `veto` only on reject.
    - `risk` only on recommend and upsize.
    - `naive` on reject and flag.
    - `replay` null or non-empty.
    - `metrics` null exactly when there is no telemetry.
    - reason codes per verdict, including the three new codes.

## 3. Extensions to the frozen §4.5 schema (complete list)
- Envelope: `mock_engine`.
- `resource`: `state`, `plan_id`. `members` holds names. Empty strings become null.
- New reason codes `BELOW_FLOOR` (healthy), `STOPPED_RECENTLY` (exclude), `NOT_IN_INVENTORY` (exclude), and the stray-series item.
- `evidence`:
  - `percentile_used` is a string.
  - metric leaves gain `mean` and can be null individually.
  - `metrics` is null whenever there is no telemetry.
  - `recurring_peak = {window_ist, days}`.
  - `naive = {action, target_plan, saving_inr, basis, replay_minutes_above_90}`, now also on flags.
- `replay`: `from_vcpu`, `from_ram_gb`; present only when it has attempts.
- `trace`: `value` and `threshold` are strings, `result` is one of 4 values, and there is a `sizing` step id.
- Text formats: schedule windows (§2.10), option formulas (§2.11), veto fields (§2.12).

## 4. Endpoints

**Shared rules:**
- Rupees are integers.
- Missing data is null, never 0.
- Timestamps are ISO 8601. Series `start` is UTC.
- The data window is IST with an **exclusive end** (`2026-10-20T00:00:00+05:30`, as in the mock; cp02:35 expects "Data: 20 Sep – 19 Oct 2026").
- Hour-of-week index = IST Monday 00:00 = 0.

| # | Endpoint | Shape | Derivation |
|---|---|---|---|
| E1 | `GET /api/resources?region=&env=&team=&type=` | `ResourceRow[]` | Every inventory column, with **empty strings as null**. `tags` is a list. `monthly_inr` = the cost model. `has_metrics` = the id has metric rows. `stats` = `{cpu_p95, cpu_p99, cpu_mean, mem_p95, mem_p99, coverage}` (VM with data); a volume gets only `coverage`, the rest null; otherwise null. `daily_p95` = 30 IST-day CPU p95 for VMs, 30 daily **means** of `disk_used_pct` for volumes, null otherwise. `daily_max` = 30 IST-day CPU max for VMs, null otherwise (mock line 1368). Filters: `env=untagged` and `team=unowned` match empty tags. The stray series is not a row |
| E2 | `GET /api/resources/{id}` | `ResourceDetail` | `resource` = the E1 row. `features` = flat `{cpu, mem, iops_pct, net_pct, disk_used, coverage, peak_window_coverage, days_of_data, cpu_slope, disk_slope, level_shift_up, level_shift_down, recurring_peak_days, recurring_window, p99_excl_top_day, mem_std, leak_cycles, how_p95}`; null when there are no metrics; volumes have the VM-only keys null. `recurring_window` = text such as `"02:00–02:40 IST"`, with a weekday prefix when the peak falls on one weekday only (mock lines 266–273), or null. `leak_cycles` = our leak count. `trace` = the default-preset trace. `dq` = the E10 row, or null. 404 for unknown ids |
| E3 | `GET /api/resources/{id}/metrics?metric=&step=` | `MetricSeries` | `metric` ∈ `cpu, mem, disk_used, iops, net_in, net_out` (`disk` alias). `step` `1h` (default) or `5m`, giving `step_seconds` 3600 or 300. `start` = UTC time of grid slot 0. `mean`/`max` cover the full 8,640-slot grid, with 1 h = 12-slot blocks from slot 0; null where there's no data. `gaps[]` = missing runs of ≥ 6 slots inside the observed span, **excluding flatline slots**, plus flatline runs of ≥ 24 slots (`{start, end}` IST, `kind`, `hours` 1 dp). Volumes: `iops` and `disk_used` only, `gaps: []`. No metrics: 200 with empty arrays |
| E4 | `GET /api/resources/{id}/replay?preset=` | `ReplaySeries` | Only for items whose `replay` is non-null. `to_plan` = `chosen_plan`, else `naive.target_plan`, else the last attempt's plan. `actual_cpu` = hourly max CPU (step 3600). `projected_cpu` = actual × `from_vcpu` / `to_vcpu`. Plus `limit_minutes_above_90`, `mem_cap_pct`, `attempts`, `passed`, `from_plan`, `from_vcpu`, `to_vcpu`, `start`, `preset`. 404 otherwise. Default preset is `default`; an unknown preset gives 422 |
| E5 | `GET /api/recommendations?preset=` | `RecEnvelope` | All four presets. 141 items. Unknown preset: 422 |
| E6 | `GET /api/summary` | `Summary` | `monthly_before_inr` = Σ current. `potential_after_inr` = Σ over default-preset items: `options[default].monthly_inr_after` if recommend and saving > 0, else current. **`potential_saving_pct` = (before − after) / before × 100, 2 dp.** `by_env`/`by_team`/`by_region` = `{monthly_before_inr, potential_after_inr}` with `untagged`/`unowned` keys. `counts = {vm, volume, ip, verdicts}`. `bill_trend_6m = {dates[180], total[], by_env{}, by_team{}}`. `growth_waterfall = {first30{start, total_inr}, last30{end, total_inr}, growth_ratio (4 dp), by_env[], by_team[], by_age[], new_resources[]}`, where each `by_*` entry is `{key, first30_inr, last30_inr, delta_inr}`, **sorted by `delta_inr` descending** (Overview uses `by_team[0]`). `by_age` keys are "new resources" (created on or after billing day 30) and "existing resources". Each breakdown sums to last30 − first30 |
| E7 | `GET /api/alerts` | `AlertsResponse` | `{mock_engine: false, items}`. Detection rules as today (B5). Shape and text follow the vocabulary table below. Severity is lowercase. `name` = resource name (the id for vm-9999; `team <name>` for team alerts). `resource_id` is null for team alerts. `window` and `evidence.window` = `{start, end}` IST, or null when there's no time window. Ids are `ALR-<type>-<resource_id>`, or `ALR-<type>-team-<name>` for team alerts (no `:`, so they are valid CSS `#id`s). **The recommendation `alert_ids` are rebuilt from the same list.** The list is **sorted** by severity (critical, warning, info), then `alert_id`, as at mock line 999. Alerts.tsx doesn't sort, and cp09:12 needs a critical alert first |
| E8 | `GET /api/forecast?days=90` | `Forecast` | `days` (1–365), and `method` = "Holt-Winters additive, weekly season, fitted on 180 days of daily cost" (α 0.3, β 0.05, γ 0.2). `monthly_now_inr`. `history` = the last 60 days. `forecast{dates, baseline, lower, upper}` (± 1.96·σ·√k). `carbon = {coefficients (config placeholder), fleet_kwh_month, fleet_kg_co2_month, potential_kwh_month, potential_kg_co2_month, by_option}`. `by_option` covers every option of every recommend and upsize item in every preset (the mock's `vm_kwh_month` / `carbon_by_option`). **Each `by_option[rec_id]` has exactly the item's option keys, in the same order, including `none`** (check_fixtures.mjs:67 compares them in order) |
| E9 | `GET /api/scorecard` | `Scorecard` | The mock's `score()` and `archetype_scores()` on **our** default-preset items vs `truth.csv`. `preset: "default"`, `mock_engine: false`, with lists for `by_verdict` and `by_archetype` |
| E10 | `GET /api/data-quality` | `DataQuality` | `resources[]` = VMs, volumes **and the stray**, which `clean_all` now cleans and reports like any VM. Fields: `name`, `type`, `in_inventory`, `rows_raw`, `irregular_ts` (= snapped), `out_of_order` (= reordered), `duplicates`, `out_of_range`, `flatline_slots` (**the span of each frozen run**, so E8 reports 576), `expected_slots`, `coverage`, `peak_window_coverage`, `days_of_data`, `longest_gap_hours` and `gaps` (**missing gaps only, flatline excluded, using the same ≥ 6-slot rule as E3**, mock lines 1290–1305). Also `faults[]` and `fault_counts` (`faults.csv`, see §9), `not_in_inventory[{resource_id, name = id}]`, `no_metrics[{resource_id, name, state}]` (VMs and volumes), `totals{…, metric_rows}`, and `checks[]` E1–E10 + D9 (the mock's `dq_checks`; all `ok` on this data) |
| E11 | `GET /api/assumptions` | `Assumptions` | `data_window` (exclusive end), `billing_window`, `counts{vm, volume, ip, metric_rows}`, and `pricing[]` (`pricing.csv` rows, NaN → null). `thresholds[{name, value, why}]` is generated from `config.yaml` through a **display-name map** (`saving_floor_inr` → "Saving floor", and so on), so the names match the mock's `THRESHOLDS` list. It includes a "Comparisons / strict < / >" entry, which becomes a new `config.yaml` key `comparisons` (cp12:15–16). `switches[]` = `stopped_vm_billed`, `hours_per_month`, gst excluded, carbon coefficients placeholder. `presets[{id, label, percentile, cpu_target, replay_limit}]` |
| E12 | `POST /api/whatif` | `WhatIfResponse` | The mock's `run_whatif` rules exactly. **Candidate set: VMs that are `running`, have metrics and have a catalogue plan** (mock line 1528; this excludes the stopped vm-maint-08 and the stray). `env` ∈ `dev\|staging\|prod\|nonprod`; whole hours; wrap-around; weekends. `how_busy` = the maximum over weeks of the hourly p95. busy ≥ 5%. Same statuses, notes, sort order and totals. Invalid body: 422 |
| E13 | `POST /api/export` | file | `{accepted: [{rec_id, option_key}], format}`. Each `rec_id` is resolved in its own preset; an unknown `rec_id` or `option_key` gives 422. `csv` / `md` follow `export_reference.ts`. **`sh` puts a header line per change, `# <n>. <name> (<rec_id> <option_key>) …`**, which cp05:74 expects, followed by the reference's commands. `tf` gives one commented placeholder block per change, also naming `<rec_id> <option_key>`. Filenames: `smartcloud-accepted.csv`, `smartcloud-accepted.md`, `apply.sh`, `smartcloud-plan.tf`. `Content-Disposition: attachment; filename="…"`, and CORS exposes it |

**Alert vocabulary.** `evidence.metric` must be a key of `Alerts.tsx` `METRIC_SERIES` whenever a chart is useful. The texts are the mock's templates (lines 897–1000) with our numbers, and cp09 matches parts of them.

| Our rule | `type` | `evidence.metric` | Title / why must contain |
|---|---|---|---|
| G4 | `possible_compromise` (critical) | `net_out_mbps` | why: "network out is N× its normal level" |
| G3 | `level_shift` (critical if prod) | `cpu_pct` | "Level shift…"; "Mean CPU over the last 48 h is N×" |
| G1 | `spike` (warning) | `cpu_pct` | "Unusual spike vs the same hours in other weeks" |
| G5, CPU | `capacity` | `cpu_p95_slope` | title: "CPU capacity: about N days to 90%" |
| G5, disk (VM or volume) | `capacity` | `disk_used_pct` | title: "Disk filling: about N days to 90%" / "Volume filling: about N days to 90%" |
| G6 | `memory_leak` | `mem_pct` | "Memory leak suspected (sawtooth)" |
| G9 | `under_provisioned` | `cpu_p99` | "Under-provisioned: CPU p99 at N%" |
| G10 | `monitoring_missing` | `rows` | "Monitoring missing" (no window) |
| D9 (new) | `orphan_series` (info) | `rows` | "Metrics for a machine not in the inventory" (no window) |
| G7 | `team_cost_jump` | `team_daily_cost` | why: "… New resources: <names>." (no window, `resource_id` null) |

**Removed:** the 501 stubs and the stub fallback mode. If the engine fails at startup, the API fails to start, with a logged error.

## 5. Config additions (`config.yaml`)
- **Presets:** numeric values for each preset, all `enabled: true`.
- **Carbon:** `carbon: {w_per_vcpu_min 0.74, w_per_vcpu_max 3.5, w_per_gb_ram 0.392, pue 1.4, kg_co2_per_kwh 0.71, source, placeholder: true, why}`.
- **Forecast:** `forecast: {alpha, beta, gamma, season_days 7, history_days 60}`.
- **What-if:** `whatif: {busy_cpu_pct 5}`.
- **Metrics:** `metrics: {gap_min_slots 6}`.
- **Comparisons:** `thresholds.comparisons: {value: "strict < / >", why}`.
- **Display names:** `display_name` for each threshold shown on the Assumptions page.

## 6. Code layout
- `backend/api/views.py` (new): one pure function per endpoint. `main.py` keeps routing and validation.
- `backend/insights/forecast.py`, `whatif.py`, `carbon.py` and `export.py` (new); `scorecard.py` and `alerts.py` (rewritten to the vocabulary above).
- `backend/pipeline/clean.py`:
  - clean and report stray series too
  - flatline **span** count
  - expose per-slot flatline and missing masks for `gaps`
- `backend/pipeline/features.py`:
  - `mean` in every metric leaf
  - `daily_max`
  - volume daily-mean `disk_used`
  - `recurring_window` text
  - `leak_cycles` (= our leak count)
  - `how_busy` (for what-if)
- Engine changes as in §2.
- `backend/api/stub.py` is removed.
- No changes to `data/`, `generator/` or `engine/`.
- No changes to `frontend/`, except the test-only edits in §9 (`e2e/fixtures.ts` and four spec lines), and only after the owner approves them.

## 7. API_CONTRACT rules → tests
| Contract rule | Test |
|---|---|
| 1. Missing = null | E3 prod-api-02 gap null; dev-api-16 flatline null |
| 2. Integer rupees; saving = current − after; `none` = current | every option, all 4 presets |
| 3. One run-rate | Σ current (E5) = Σ `monthly_inr` (E1) = `monthly_before_inr` |
| 4. 141 items per preset | E5 |
| 5. Presence by verdict; `resize+schedule` exists | schema, 4 presets |
| 6. `has_metrics` gating; a replay block implies a 200 from `/replay`; 404 for unknown ids | E1 / E3 / E4 cross-check |
| 7. untagged / unowned filters | E1 |
| 8. Waterfall sums, sorted | E6 |
| 9. `carbon.by_option` coverage | E8 |
| 10. Time formats | `start` UTC; window IST with exclusive end |
| 11. Non-2xx `{detail}` | 404 / 422 cases |
| 12. `mock_engine: false` | E5, E7, E9 |

## 8. Checkpoints
Each is implemented, then tested, then the whole suite re-runs.

| CP | Work | Done when |
|---|---|---|
| I0 | Rewrite the existing tests that pin old shapes: `test_api.py` (501, X-Engine, list shapes), `test_schemas.py` (stub imports, presence rules), `test_engine.py` (CONTRACT_MAP, `would_save_inr`, window format), `test_alerts.py` (G-codes, capitalised severity), `test_clean.py` (strays) | Old assertions are replaced by the new contract as each CP lands; nothing is deleted without a replacement |
| I1 | Config additions; four presets | params tests for 4 presets |
| I2 | Engine output (§2.2–2.13) + schema; scorecard without the mapping | `truth.csv` 141/141 on default; 4 presets validate; replay safety in all presets; cp13 data condition holds |
| I3 | Clean and features additions; E1, E2, E3 (+ gaps), E4 | shape diff 0 for these; rules 1, 6, 7 |
| I4 | E6, E7 (+ `alert_ids`) | shape diff 0; rule 8; every alert `evidence.metric` with a chart is in `METRIC_SERIES` |
| I5 | E9, E10, E11 | shape diff 0; E10 checks all `ok`; threshold names match the mock's list |
| I6 | E12, E13, E8 (+ carbon) | shape diff 0; rule 9; dev 20:00–08:00 lists dev-etl-04 as disrupted |
| I7 | Full verification: (a) shape diff over every fixture, 0 / 0; (b) all 12 rules; (c) **live check_fixtures:** copy `frontend/` (without `node_modules`) to the scratchpad, overwrite the copy's `fallback/api/` with a dump of the live API in the same file layout, and run `node scripts/check_fixtures.mjs` there (the repo's fixtures are never touched); (d) frontend typecheck, unit tests and build; (e) `npm run dev` with the backend up, smoke-test every page; (f) `npm run verify:live` if Chromium can be installed, and it must fail only on the §9 lines | all pass, or (f) recorded as "not run: Chromium unavailable" |
| I8 | Docs | `PLAN_final.md` B11; carbon future scope in ASSUMPTIONS / DATASET notes |

## 9. Expected live-mode test failures (frontend test edits that need the owner's approval)
These assertions test the **mock**, not the contract, so a real backend cannot satisfy them:

| Spec line | Asserts | Why it fails live | Proposed edit |
|---|---|---|---|
| `e2e/cp02-shell.spec.ts:38` | `mock-banner` visible | the engine is real: `mock_engine` is false | assert it is absent when `!recs.mock_engine` |
| `e2e/cp12-assumptions.spec.ts:22` | `scorecard-mock-note` visible | same | same condition |
| `e2e/cp05-drawer.spec.ts:76` | text `stub export (tf)` | that is the fallback stub's placeholder (`fallback/resolve.ts:84`) | assert the `rec_id resize+schedule` line, as for `sh` |
| `e2e/cp11-dataquality.spec.ts:30` | text `vm-ghost-99` | the name exists only in `truth.csv`; we show `vm-9999` | expect `vm-9999` |

**Harness limitations in live mode.** These fail with any backend, however correct, because of `frontend/e2e/fixtures.ts`:
- **Empty call log.** `api.calls` is filled only by the in-browser stub, which is off in live mode (`fixtures.ts:34`), so it is always empty. Every assertion that reads `api.calls` fails or throws:
  - `cp05-drawer.spec.ts:77-80` (export request bodies; the same test also has the line-76 stub text above)
  - `cp05-drawer.spec.ts:88-91` (metrics requested at 1 h)
  - `cp08-utilization.spec.ts:14` (`type=volume` request)
  - `cp10-whatif.spec.ts:35-36` (whatif body)
  - `cp13-presets-export.spec.ts:56-62` (export body)
  - `cp14-forecast.spec.ts:10` (`?days=90`)
  - `cp12-assumptions.spec.ts:29` passes only because `every` on an empty list is true.
- **404/502 console errors.** The console guard ignores 404/502 resource errors only outside live mode (`fixtures.ts:62`). So these fail live even though the backend behaves as the contract requires:
  - `cp08-utilization.spec.ts:48` (unknown id → 404)
  - `cp02-shell.spec.ts:65` (the test fakes a 502 itself)
- **Proposed harness edit** (needs approval; `fixtures.ts` only):
  - In live mode, record calls with `page.on('request', …)` for `/api/` URLs into the same `calls` list. Method, path, query and `postData` give the same `ApiCall` shape.
  - Apply the 404/502 exemption in live mode too.

  With that edit, plus the four line edits in the table above, the live suite has no backend-independent failures. **The definition of done for (f): the live suite passes after these approved edits.** Without the edits, every failure must be on the lines listed in this section.

**Other deviations, not failures:**
- **`faults.csv`** (part of the dataset) lists the stray as `vm-9999,vm-ghost-99`. E10 `faults[]` passes the fault log through **unchanged**, as the dataset's own record. Everywhere else the stray is called `vm-9999`. The owner can ask for that row to be masked.
- **Engine verdicts, not truth copies:** 6 resources differ from the stale fallback data and match the current `truth.csv` (prod-web-11a/b/c, staging-demo-10, staging-batch-68, dev-batch-69).
- **Spike alerts:** our G1 rule fires about 60 spike alerts, against 1 in the mock. That's more cards on the Alerts page, not a contract break.

## 10. Future scope (recorded, not built)
- **Carbon:** the coefficients are published averages (CCF, CEA), not measurements. Future dataset work should add per-plan power draw, data-centre PUE and region grid intensity, and count storage and network energy.
- **Stray-series names:** only possible with an inventory or CMDB record.
- **Fallback data:** `frontend/fallback/` can be regenerated from the real API once it serves everything.
