# Validation report

72 / 72 checks passed.

Monthly run-rate (last day x 730/24): Rs 657,303

| case | resource | check | result | value |
|---|---|---|---|---|
| A1 | prod-api-01 | cpu p95 60-80 | PASS | 73.2 |
| A2 | prod-api-07 | cpu p99 25-35, mem p99 < 25 | PASS | (30.4, 18.2) |
| A3 | prod-batch-07 | mean 6-10, p99 88-95 | PASS | (7.9, 92.5) |
| A4 | prod-billing-01 | p99 >= 85 (Sunday peak), mean < 10 | PASS | (5.8, 90.1) |
| A5 | dev-report-02 | p99 < 30 but max >= 90 (p99 misses weekly job) | PASS | (23.6, 97.0) |
| A6 | prod-reports-02 | p99 >= 85, p99 without top day < 40 | PASS | (93.2, 25.1) |
| A7 | prod-checkout-03 | mean 11-17, p99 >= 80 | PASS | (13.9, 87.7) |
| A8 | prod-queue-02 | mean < 20, p99 >= 70 | PASS | (13.3, 81.7) |
| A9 | prod-cache-04 | cpu p99 < 10, mem p99 >= 80 | PASS | (7.3, 86.4) |
| A10 | prod-search-06 | mem mean >= 75, std < 2 | PASS | (78.0, 0.5) |
| A11 | prod-orders-08 | >= 3 sawtooth resets (mem drop > 25 pts) | PASS | 4 |
| A12 | prod-db-01 | iops p95 >= 70% of provisioned | PASS | 94.2 |
| A13 | prod-ingest-09 | iops p95 >= 70% of provisioned | PASS | 90.8 |
| A14 | prod-gateway-03 | cpu p99 < 10, net p95 >= 60% bw | PASS | (6.7, 78.7) |
| A15 | prod-api-04 | daily p95 slope > 1 %/day | PASS | 1.65 |
| A16 | prod-search-02 | cpu p99 > 90 | PASS | 100.0 |
| A17 | prod-legacy-06 | last-7d / prior mean < 0.2 | PASS | 0.034 |
| A18 | prod-ml-10 | cpu p99 < 15, mem p99 in 37.5-50 | PASS | (11.6, 44.9) |
| A19 | dev-tiny-14 | S1 and cpu p95 < 5 | PASS | 2.82 |
| A20 | staging-web-08 | cpu p95 27-33 (needs ~3 vCPU of 8) | PASS | 30.5 |
| A21 | staging-api-09 | cpu p95 == 40.0 exactly | PASS | 40.0 |
| A23 | prod-web-11a/b/c | 3 members share service_group | PASS | 3 |
| A24 | prod-k8s-node-* | 3 nodes tagged autoscaled | PASS |  |
| A25 | prod-checkout-01 | tagged seasonal_peak | PASS |  |
| B1 | staging-db-02 | cpu p99 < 5, stateful | PASS | 1.71 |
| B3 | dev-cache-13 | cpu p95 < 5, mem p99 > 70 | PASS | (2.8, 76.4) |
| B4 | dev-web-03 | weekend p95 < 5, overall p95 < 12, mem p95 <= 18.75 (fits 8 GB) | PASS | (1.2, 9.2, 13.9) |
| B5 | dev-etl-04 | 01-03 p95 >= 60 | PASS | 74.5 |
| B6 | dev-support-05 | night mean > 3x day mean | PASS | (27.1, 2.0) |
| B7 | staging-load-06 | weekend-day mean > 50, weekday p95 < 5 | PASS | (69.7, 2.2) |
| B9 | dev-misc-07 | < 40 consistently-quiet hours/week | PASS | 19 |
| B10 | staging-demo-10 | keep_running + no_schedule | PASS |  |
| C10 | vm-stopped-07 | stopped, no metrics | PASS |  |
| C11 | vm-maint-08 | metrics end 2026-10-17 | PASS | 27 |
| D1 | dev-test-12 | <= 3 days of data | PASS | 3 |
| D2 | staging-app-05 | resized B4->B3 on 2026-10-14 | PASS |  |
| D3 | prod-standby-01 | dr_standby tag + policy never | PASS |  |
| D4 | prod-nomon-13 | no metrics | PASS |  |
| D5 | vm-untagged-14 | env empty | PASS |  |
| D6 | dev-orphan-owner-15 | owner empty | PASS |  |
| D7 | dev-misnamed-16 | name dev-*, env prod | PASS |  |
| D8 | prod-legacy-plan-17 | plan not in pricing | PASS |  |
| D9 | vm-ghost-99 | metrics without inventory | PASS |  |
| D10 | prod-worker-05 | last-48h / prior mean >= 3.5 | PASS | 4.03 |
| E1 | prod-api-02 | contiguous gap of 72 slots (6 h) | PASS | 72 |
| E2 | dev-web-03 | duplicate timestamps present | PASS | 12 |
| E3 | fleet | >= 15 out-of-range CPU values | PASS | 30 |
| E4 | fleet | >= 2 resources with out-of-order rows | PASS | 2 |
| E5 | fleet | random missing share 0.003-0.02 | PASS | 0.005 |
| E6 | dev-flaky-18 | coverage 0.65-0.75 | PASS | 0.696 |
| E7 | staging-flaky-19 | coverage 0.85-0.92 | PASS | 0.876 |
| E8 | dev-api-16 | >= 500 rows of exact 0.0 on days 15-16 | PASS | 574 |
| E9 | prod-batch-20 | 01-04 coverage < 0.5 | PASS | 0.398 |
| E10 | fleet | irregular timestamps present | PASS | 286 |
| E11 | fleet | timestamps stored in UTC | PASS | UTC |
| G4 | dev-sandbox-17 | cpu > 90 after day 26, net_out x >= 8 | PASS | (97.8, 10.0) |
| G5 | 4 bulk VMs | disk slope ~0.8 %/day | PASS | [0.8, 0.8, 0.8, 0.8] |
| C6 | vol-growing-10 | used slope ~2 %/day | PASS | 2.0 |
| C3 | vol-idle-04 | zero IOPS all window | PASS | 0.0 |
| C1 | vol-orphan-11 | unattached since 2026-08-16 | PASS |  |
| C2 | vol-new-12 | unattached 2 days | PASS |  |
| C7 | ip-unused-03 | unassociated | PASS |  |
| C8 | ip-stopped-02 | on vm-stopped-07 | PASS |  |
| C9 | ip-allowlist-04 | allowlisted tag | PASS |  |
| G7 | growth team | 4 VMs created 2026-10-12 | PASS | 4 |
| CAL | fleet | share of VMs with mean CPU < 20% in 0.5-0.85 (Azure) | PASS | 0.765 |
| CAL | fleet | median p95/mean CPU in 1.5-5.0 (Azure) | PASS | 1.57 |
| CAL | fleet | median memory CV < median CPU CV (Bitbrains/Google) | PASS | (0.126, 0.371) |
| CAL | fleet | median CPU p95 < 50.0% (Google: usage << allocation) | PASS | 27.6 |
| BILL | fleet | month 6 / month 1 in 1.35-1.45 | PASS | 1.363 |
| SIZE | data/ | total <= 30 MB | PASS | 11.9 MB |
| COUNT | inventory | 117 VMs, 15 volumes, 8 IPs | PASS | {'vm': 117, 'volume': 15, 'ip': 8} |
