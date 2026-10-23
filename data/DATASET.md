# SmartCloud Optimizer: synthetic dataset

This is a simulated fleet for a mid-sized Indian SaaS company: 117 VMs, 15 data volumes and 8 public IPs across Mumbai, Bangalore and Noida, split into prod, staging and dev. All data is **synthetic** and generated with seed 42.

```
pip install -r requirements.txt
python -m generator.build      # ~10 s, writes everything below
python -m generator.validate   # 72 checks -> data/validation_report.md
```

Two runs produce byte-identical files (verified with SHA-256).

## Files

| File | Rows | What it is |
|---|---|---|
| `inventory.csv` | 140 | One row per resource. Columns below |
| `metrics.parquet` | ~959K | VM metrics, 5-minute steps, **UTC**, 2026-09-20 to 2026-10-19 IST. Faults are left in on purpose |
| `volume_metrics.parquet` | ~129K | Volume `iops`, `disk_used_pct`, 5 minutes |
| `billing_daily.parquet` | ~21K | 180 days of daily cost per resource (2026-04-23 to 2026-10-19) |
| `pricing.csv` | 10 | Plan catalogue + storage, snapshot and IP rates. **Illustrative** |
| `truth.csv` | 141 | Archetype, edge case and **expected** verdict for each resource. For tests and the scorecard only; **the engine must never read it** |
| `faults.csv` | ~134 | Log of every injected data-quality fault |
| `validation_report.md` | — | Output of `generator.validate` |
| `fixture/` | 3 resources | prod-batch-07, dev-web-03, vol-orphan-11, so other modules can start early |

### inventory.csv columns
- `resource_id, name, type (vm|volume|ip), region, env, owner_team, purpose, service_group`
- `plan_id, previous_plan_id, vcpu, ram_gb, disk_gb, provisioned_iops, bandwidth_mbps`
- `state (running|stopped|attached|unattached|associated|unassociated), stopped_since, created_at, last_resized_at`
- `attached_to, unattached_since, optimize_policy (default|never|no_schedule), tags (; separated)`

All timestamps are ISO 8601 with +05:30. An empty `env` or `owner_team` is deliberate; see edge cases D5 and D6.

### metrics.parquet columns
`resource_id (category), ts (UTC), cpu_pct, mem_pct, disk_used_pct, iops, net_in_mbps, net_out_mbps`, all float32 rounded to 2 decimals.

- `iops` is absolute. Divide by `provisioned_iops` to get a percentage.
- Network is in Mbps. Divide by `bandwidth_mbps` to get a percentage.

## How the signals are built

Each VM is vectorised over 8,640 slots:

```
cpu  = clip((base + amp x daily(t) x weekly(t)) x drift(day) + AR1(sigma, phi=0.8))
mem  = clip(mem_base + 0.25 x cpu + N(0, 1.5))           # sticky: does not fall when CPU idles
iops = provisioned x (iops_base + 0.3 x cpu)% x lognormal(0, 0.3)
net_in  = bandwidth x (net_base + 0.15 x cpu)% x lognormal(0, 0.35);  net_out = 0.6 x net_in x lognormal(0, 0.2)
disk_used = start + slope x day + N(0, 0.05)
```

- **`daily(t)`:** a sine bump from 08:00 to 20:00 IST, peaking at 14:00.
- **`weekly(t)`:** a weekend factor.
- **`drift`:** one N(1, 0.05) multiplier per day, so no two days are identical.
- Planted resources override individual parts to create their pattern (see below).

**Seeding:** each resource has its own random generator, seeded `[42, crc32(name)]`. A resource's data doesn't change when others are added or reordered.

## Calibration against public datasets

**Caveat:** no public trace was downloaded. The targets below are approximate findings from the published papers, recalled from memory. `validate.py` checks the fleet against each one, and the measured values are in `validation_report.md`.

| Source | Finding used | Target | Measured |
|---|---|---|---|
| Azure Public Dataset (Resource Central, SOSP '17) | Most VMs have low average CPU; interactive (diurnal) and delay-insensitive (batch) classes | 50–85% of VMs with mean CPU < 20% | 76.5% |
| Azure | p95 sits well above the mean | median p95/mean between 1.5 and 5 | 1.57 |
| Azure spike study | Most spikes are not seasonal | random Poisson spikes (prod-queue-02, dev-misc-07) | — |
| Bitbrains GWA-T-12 / Materna | Memory steadier than CPU; disk and network bursty | median memory CV < median CPU CV | 0.13 vs 0.37 |
| Google cluster-data 2011 | Usage far below allocation | median CPU p95 < 50% | 27.6% |
| Alibaba 2018 | Memory stays high while CPU is low | memory_bound archetype at 80–88% | — |
| IBM trace study | Monitoring gaps are common | 0.3–2% random missing | 0.5% |

**Recommended next step:** download Bitbrains fastStorage into `data/external/` (gitignored) and compare per-VM percentiles directly.

## Fleet composition

**Bulk VMs (62)**, generated from archetypes with randomised parameters:

| Archetype | VMs | Shape | Expected outcome |
|---|---|---|---|
| right_sized_prod | 15 | 20–30% base + 20–35% daily bump. 4 of them have disk filling at 0.8%/day | healthy (4 trigger a disk alert) |
| steady_low | 12 | 5–10% flat, on B3–B5 | resize |
| bursty_daily | 7 | 10% base, 75–90% from 09:30 to 10:15 | reject (recurring peak) |
| batch_nightly | 5 | ~3%, 85–95% from 01:00 to 03:00 | reject (recurring peak) |
| office_hours_dev | 15 | weekdays 09–19 at ~38%, else ~2%. 4 are new growth-team VMs created 2026-10-12 | schedule / exclude (history) |
| zombie | 5 | ~1.5% CPU, no network, no IO | stop |
| memory_bound | 3 | CPU ~10%, memory 80–85% | reject (memory) |

**Planted resources (55 VMs, 6 volumes, 3 IPs, plus 1 stray series):** one per edge case in `PLAN.md` §8. The full list, with the expected verdict for each, is in `truth.csv` and below.

**Healthy filler:** 9 attached volumes and 5 associated IPs.

## Data-quality faults (left in the raw data on purpose)

| Case | Resource | Fault |
|---|---|---|
| E1 | prod-api-02 | 6-hour gap, 2026-10-02 10:00–16:00 IST |
| E2 | dev-web-03 | 12 duplicate timestamps with slightly different values (agent re-send) |
| E3 | 3 bulk VMs | 30 CPU values in 103–110% or −3 to −1% |
| E4 | 2 bulk VMs | a block of 20 rows in reverse order |
| E5 | all VMs, 6 bulk | 0.5% random drops; 20-minute reboot gaps |
| E6 | dev-flaky-18 | 30% of hours missing (coverage ~70%) |
| E7 | staging-flaky-19 | 12% of hours missing (coverage ~88%) |
| E8 | dev-api-16 | stuck agent: CPU exactly 0.0 and memory constant for 48 hours |
| E9 | prod-batch-20 | 01:00–04:00 missing on 18 of 30 nights (peak window under-observed) |
| E10 | 1 bulk VM | timestamps offset by +3 minutes for a day (e.g. 05:03) |
| E11 | all | stored in UTC; daily patterns are in IST |

## Billing and pricing assumptions

- Prices are **illustrative**, modelled on Utho's public Basic tiers, and exclude GST. Confirm them with Utho before quoting.
- A month is 730 hours, and daily cost = monthly × 24/730.
- Block volumes cost ₹8/GB-month, snapshots ₹4/GB-month and a public IP ₹200/month.
- All regions are priced the same.
- Stopped VMs pay for disk only (`stopped_vm_billed = false`).
- The legacy plan `L-OLD-4` is billed at ₹3,500 but is deliberately missing from `pricing.csv` (edge case D8).
- **Growth story:** creation dates of 31 bulk VMs (non-prod first) were placed inside the billing window so that last-30-day cost ÷ first-30-day cost = **1.36**. The target was 1.40; the result is coarse because each VM adds a discrete step.

## Deviations from PLAN.md

- 117 VMs (55 planted), not 118 (56 planted): prod-api-02 was counted in both group A and group E.
- prod-batch-20 is missing 18 of 30 nights, not 10, so peak-window coverage falls below the 50% flag threshold.
- dev-cache-13 sits at 74% memory, so the expected result is a memory-veto **reject** rather than a schedule.
- New expected reason codes: `BELOW_FLOOR` (dev-tiny-15), `STOPPED_RECENTLY` (vm-maint-08) and `NOT_IN_INVENTORY` (vm-ghost-99).

## Planted resources and expected outcomes (from truth.csv)

| edge case | name | type | expected verdict | reason code | action | notes |
|---|---|---|---|---|---|---|
| A1 | prod-api-01 | vm | healthy | RIGHT_SIZED | none | p95 ~70%: must be left alone |
| A2 | prod-api-07 | vm | recommend | UNDERUSED | resize | CPU p99 ~31%, mem ~15%: formula says B2, prod one-step rule gives B4->B3 |
| A3 | prod-batch-07 | vm | reject | VETO_RECURRING_PEAK | none | mean ~8%, p99 ~92% in a 40-min window at 02:00 every night |
| A4 | prod-billing-01 | vm | reject | VETO_RECURRING_PEAK | none | idle 6 days, 90% every Sunday 09:00-12:00 (5 Sundays in window) |
| A5 | dev-report-02 | vm | reject | PEAK_REPLAY_FAILED | none | p99 ~22% misses a weekly 1-hour job at 95% (Wed 15:00); replay on B1 fails |
| A6 | prod-reports-02 | vm | flag | ONE_OFF_PEAK | none | single 8-hour 95% spike on 2026-10-01; p99 without that day is low |
| A7 | prod-checkout-03 | vm | reject | VETO_RECURRING_PEAK | none | average ~14%, p99 ~86% at 10:00 daily |
| A8 | prod-queue-02 | vm | reject | PEAK_REPLAY_FAILED | none | unscheduled spikes 10->80% several times a day (no schedule) |
| A9 | prod-cache-04 | vm | reject | VETO_MEMORY | none | CPU ~5%, memory p99 ~85% |
| A10 | prod-search-06 | vm | flag | RESERVED_MEMORY | none | memory flat at 78% (JVM heap reserved), std < 1 |
| A11 | prod-orders-08 | vm | reject | VETO_LEAK | none | memory climbs 40->85% over 7.5 days then drops (restart): 4 cycles; leak check runs before memory veto |
| A12 | prod-db-01 | vm | exclude | STATEFUL_PROD | none | CPU ~12%, IOPS saturated; stateful |
| A13 | prod-ingest-09 | vm | reject | VETO_IOPS | none | stateless but disk-bound: IOPS p95 ~90% |
| A14 | prod-gateway-03 | vm | reject | VETO_NETWORK | none | CPU ~4% but network p95 > 60% of bandwidth |
| A15 | prod-api-04 | vm | healthy | RIGHT_SIZED | none | CPU climbs 20->65% over 30 days: capacity-trend alert expected |
| A16 | prod-search-02 | vm | upsize | UNDER_PROVISIONED | upsize | CPU p99 > 90% |
| A17 | prod-legacy-06 | vm | flag | WENT_QUIET | none | busy until 2026-10-12, near zero for the last 8 days |
| A18 | prod-ml-10 | vm | reject | NO_CHEAPER_PLAN | none | CPU ~8% but memory p99 ~45% of 32 GB needs > 16 GB: no cheaper plan fits both |
| A19 | dev-tiny-14 | vm | recommend | IDLE | stop | already the smallest plan: stop, never resize |
| A20 | staging-web-08 | vm | recommend | UNDERUSED | resize | needs ~3 vCPU: catalogue has 2 or 4, round UP to B2 (4 vCPU) |
| A21 | staging-api-09 | vm | healthy | RIGHT_SIZED | none | rate-limited at exactly 40.00% in business hours: p95 = 40.0 is NOT < 40 |
| A22 | dev-tiny-15 | vm | healthy | BELOW_FLOOR | none | schedule would save ~Rs 495/month (< Rs 500 floor); S1 cannot shrink |
| A23 | prod-web-11a | vm | recommend | UNDERUSED | resize | one group recommendation, sized on the busiest member (11b) |
| A23 | prod-web-11b | vm | recommend | UNDERUSED | resize | one group recommendation, sized on the busiest member (11b) |
| A23 | prod-web-11c | vm | recommend | UNDERUSED | resize | one group recommendation, sized on the busiest member (11b) |
| A24 | prod-k8s-node-1 | vm | exclude | TAG_AUTOSCALED | none | rightsize the node pool, not the node |
| A24 | prod-k8s-node-2 | vm | exclude | TAG_AUTOSCALED | none | rightsize the node pool, not the node |
| A24 | prod-k8s-node-3 | vm | exclude | TAG_AUTOSCALED | none | rightsize the node pool, not the node |
| A25 | prod-checkout-01 | vm | exclude | TAG_SEASONAL | none | looks oversized in a quiet month; festive-sale peak is outside the window |
| B1 | staging-db-02 | vm | recommend | IDLE | snapshot+stop | 1% for 30 days; stateful non-prod: snapshot first, delete after 14 days |
| B2 | prod-old-12 | vm | flag | IDLE_PROD | none | idle prod: review with owner |
| B3 | dev-cache-13 | vm | reject | VETO_MEMORY | none | CPU 2% but memory-resident at 74%: not idle |
| B4/E2 | dev-web-03 | vm | recommend | UNDERUSED | resize+schedule | B4->B2 plus off Mon-Fri 20:00-08:00 and weekends; combined, not additive |
| B5 | dev-etl-04 | vm | recommend | OFF_HOURS | schedule | nightly job 01:00-03:00: off-window must exclude it |
| B6 | dev-support-05 | vm | recommend | OFF_HOURS | schedule | night-shift team busy 22:00-06:00: window must be daytime |
| B7 | staging-load-06 | vm | recommend | OFF_HOURS | schedule | weekend-only load tests: weekdays off |
| B9 | dev-misc-07 | vm | recommend | UNDERUSED | resize | activity scattered across all hours: off-hours fragmented, so no schedule |
| B10 | staging-demo-10 | vm | healthy | RIGHT_SIZED | none | office-hours shape but keep_running tag: never scheduled |
| C1 | vol-orphan-11 | volume | recommend | ORPHAN_VOLUME | snapshot+delete | unattached 65 days; 120 GB used -> snapshot Rs 480 |
| C2 | vol-new-12 | volume | exclude | ORPHAN_TOO_NEW | none | unattached 2 days: under the 7-day gate |
| C3 | vol-idle-04 | volume | flag | IDLE_VOLUME_REVIEW | none | attached to a running VM, zero IOPS for 30 days |
| C4 | vol-stopped-07 | volume | recommend | STOPPED_VM | snapshot+delete | attached to a VM stopped 45 days |
| C5 | vol-oversized-09 | volume | recommend | OVERSIZED_VOLUME | shrink_volume | 500 GB, 40 GB used: migrate to 100 GB (no in-place shrink) |
| C6 | vol-growing-10 | volume | reject | VETO_GROWTH | none | oversized today but growing 2%/day -> disk alert |
| C7 | ip-unused-03 | ip | recommend | UNUSED_IP | release | allocated, never associated |
| C8 | ip-stopped-02 | ip | recommend | STOPPED_VM | release | associated with a VM stopped 45 days |
| C9 | ip-allowlist-04 | ip | exclude | TAG_ALLOWLISTED_IP | none | on a bank/payment-gateway allowlist: cannot be re-acquired |
| C10 | vm-stopped-07 | vm | recommend | STOPPED_VM | snapshot+delete | stopped 45 days; disk + IP still billed |
| C11 | vm-maint-08 | vm | exclude | STOPPED_RECENTLY | none | stopped 3 days ago: maintenance |
| D1 | dev-test-12 | vm | exclude | HISTORY_TOO_SHORT | none | created 3 days ago |
| D2 | staging-app-05 | vm | exclude | RECENTLY_RESIZED | none | resized B4->B3 6 days ago; older data describes a different machine |
| D3 | prod-standby-01 | vm | exclude | TAG_DR_STANDBY | none | DR warm standby: only the tag saves it |
| D4 | prod-nomon-13 | vm | exclude | NO_TELEMETRY | none | monitoring agent missing: no metrics at all |
| D5 | vm-untagged-14 | vm | recommend | UNDERUSED | resize | env tag missing: treated as prod (one step) + UNTAGGED_ENV flag |
| D6 | dev-orphan-owner-15 | vm | recommend | UNDERUSED | resize | owner missing: UNOWNED flag |
| D7 | dev-misnamed-16 | vm | recommend | UNDERUSED | resize | name says dev, tag says prod: trust tag (one step) + TAG_NAME_CONFLICT flag |
| D8 | prod-legacy-plan-17 | vm | exclude | UNKNOWN_PRICE | none | plan L-OLD-4 not in catalogue (billed at Rs 3,500): never guess a price |
| D9 | vm-ghost-99 | vm | exclude | NOT_IN_INVENTORY | none | metrics exist but no inventory row |
| D10/G3 | prod-worker-05 | vm | exclude | ACTIVE_ANOMALY | none | 4x sustained CPU jump from 2026-10-18: anomaly alert, not sized |
| E1 | prod-api-02 | vm | healthy | RIGHT_SIZED | none | 6-hour gap on 2026-10-02 10:00-16:00 must be NaN, not idle |
| E6 | dev-flaky-18 | vm | exclude | LOW_COVERAGE | none | ~70% coverage |
| E7 | staging-flaky-19 | vm | recommend | UNDERUSED | resize | ~88% coverage: allowed, confidence Medium, MEDIUM_COVERAGE flag |
| E8 | dev-api-16 | vm | recommend | OFF_HOURS | schedule | stuck agent reports 0.0 for 48h (days 15-16): treat as missing |
| E9 | prod-batch-20 | vm | flag | PEAK_UNDER_OBSERVED | none | 02:00 batch, but 01:00-04:00 missing on 18 of 30 nights |
| G4 | dev-sandbox-17 | vm | exclude | ACTIVE_ANOMALY | none | CPU 98% + 10x network out from 2026-10-16: critical 'possible compromise' |
