# Validation report

178 / 178 checks passed.

Monthly run-rate (last day x 730/24): Rs 619,490

| case | resource | check | result | value |
|---|---|---|---|---|
| A1 | prod-api-01 | cpu p95 60-80 | PASS | 73.2 |
| A2 | prod-api-07 | cpu p99 25-35, mem p99 < 25 | PASS | (30.4, 18.2) |
| A3 | prod-batch-07 | mean 6-10, p99 88-95 | PASS | (7.7, 92.5) |
| A4 | prod-billing-01 | p99 >= 85 (Sunday peak), mean < 10 | PASS | (6.2, 90.1) |
| A5 | dev-report-02 | p99 < 30 but max >= 90 (p99 misses weekly job) | PASS | (23.6, 97.0) |
| A6 | prod-reports-02 | p99 >= 85, p99 without top day < 40 | PASS | (93.2, 25.1) |
| A7 | prod-checkout-03 | mean 11-17, p99 >= 80 | PASS | (11.7, 87.7) |
| A8 | prod-queue-02 | mean < 20, p99 >= 70 | PASS | (14.7, 81.7) |
| A9 | prod-cache-04 | cpu p99 < 10, mem p99 >= 80 | PASS | (7.3, 86.4) |
| A10 | prod-search-06 | mem mean >= 75, std < 2 | PASS | (78.0, 0.5) |
| A11 | prod-orders-08 | >= 3 sawtooth resets (mem drop > 25 pts) | PASS | 4 |
| A12 | prod-db-01 | iops p95 >= 70% of provisioned | PASS | 94.2 |
| A13 | prod-ingest-09 | iops p95 >= 70% of provisioned | PASS | 90.8 |
| A14 | prod-gateway-03 | cpu p99 < 10, net p95 >= 60% bw | PASS | (6.7, 78.7) |
| A15 | prod-api-04 | daily p95 slope > 1 %/day | PASS | 1.38 |
| A16 | prod-search-02 | cpu p99 > 90 | PASS | 100.0 |
| A17 | prod-legacy-06 | last-7d / prior mean < 0.2 | PASS | 0.031 |
| A18 | prod-ml-10 | cpu p99 < 15, mem p99 in 37.5-50 | PASS | (11.5, 44.9) |
| A19 | dev-tiny-14 | S1 and cpu p95 < 5 | PASS | 2.82 |
| A20 | staging-web-08 | cpu p95 27-33 (needs ~3 vCPU of 8) | PASS | 30.5 |
| A21 | staging-api-09 | cpu p95 == 40.0 exactly | PASS | 40.0 |
| A23 | prod-web-11a/b/c | 3 members share service_group | PASS | 3 |
| A24 | prod-k8s-node-* | 3 nodes tagged autoscaled | PASS |  |
| A25 | prod-checkout-01 | tagged seasonal_peak | PASS |  |
| B1 | staging-db-02 | cpu p99 < 5, stateful | PASS | 1.72 |
| B3 | dev-cache-13 | cpu p95 < 5, mem p99 > 70 | PASS | (2.8, 76.4) |
| B4 | dev-web-03 | weekend p95 < 5, overall p95 < 12, mem p95 <= 18.75 (fits 8 GB) | PASS | (1.2, 9.2, 12.7) |
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
| D10 | prod-worker-05 | last-48h / prior mean >= 3.5 | PASS | 4.24 |
| E1 | prod-api-02 | contiguous gap of 72 slots (6 h) | PASS | 72 |
| E2 | dev-web-03 | duplicate timestamps present | PASS | 12 |
| E3 | fleet | >= 15 out-of-range CPU values | PASS | 30 |
| E4 | fleet | >= 2 resources with out-of-order rows | PASS | 2 |
| E5 | fleet | random missing share within +/-20% of Bitbrains (0.0027) | PASS | 0.0027 |
| E6 | dev-flaky-18 | coverage 0.65-0.75 | PASS | 0.698 |
| E7 | staging-flaky-19 | coverage 0.85-0.92 | PASS | 0.878 |
| E8 | dev-api-16 | >= 500 rows of exact 0.0 on days 15-16 | PASS | 574 |
| E9 | prod-batch-20 | 01-04 coverage < 0.5 | PASS | 0.4 |
| E10 | fleet | irregular timestamps present | PASS | 288 |
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
| CAL | fleet | share of VMs with mean CPU < 20% in 0.5-0.85 (Azure) | PASS | 0.809 |
| CAL | fleet | median p95/mean CPU in 1.5-5.0 (Azure) | PASS | 2.26 |
| CAL | fleet | median memory CV < median CPU CV (Bitbrains/Google) | PASS | (0.156, 0.65) |
| CAL | fleet | median CPU p95 < 50.0% (Google: usage << allocation) | PASS | 40.6 |
| FIT | ar1_phi_cpu | CPU lag-1 autocorrelation (residual): synthetic median in real IQR [0.771, 0.959] | PASS | 0.898 (n=52, real median 0.905) |
| FIT | mem_ar1_phi | memory lag-1 autocorrelation (residual): synthetic median in real IQR [0.578, 0.873] | PASS | 0.784 (n=52, real median 0.792) |
| FIT | mem_coupling | memory-on-CPU OLS slope: synthetic median in real IQR [-0.125, 0.391] | PASS | 0.0297 (n=58, real median 0.0287) |
| FIT | mem_noise_sd_pct | memory residual sd (pct points): synthetic median in real IQR [1.25, 6.77] | PASS | 3.1 (n=58, real median 3.12) |
| FIT | net_out_in_ratio | net_out / net_in: synthetic median in real IQR [0.0267, 1.01] | PASS | 0.263 (n=58, real median 0.258) |
| FIT | net_lognorm_sigma | network lognormal spread: synthetic median in real IQR [1.43, 2.18] | PASS | 1.98 (n=52, real median 1.99) |
| FIT | iops_lognorm_sigma | disk IO lognormal spread: synthetic median in real IQR [0.977, 2.13] | PASS | 1.05 (n=52, real median 1.06) |
| FIT | archetypes.steady_low.drift_sd | day-to-day drift sd, steady_low: synthetic median in real IQR [0.0839, 0.305] | PASS | 0.2 (n=12, real median 0.191) |
| INFO | archetypes.bursty_daily.drift_sd | day-to-day drift sd, bursty_daily: archetype has < 30 real matches, not compared | PASS | 0.329 (n=7) |
| FIT | archetypes.zombie.drift_sd | day-to-day drift sd, zombie: synthetic median in real IQR [0.0493, 0.223] | PASS | 0.194 (n=5, real median 0.111) |
| FIT | weekend_factor_interactive | weekend/weekday ratio (interactive VMs): synthetic median in real IQR [0.718, 0.934] | PASS | 0.827 (n=15, real median 0.814) |
| FIT | archetypes.right_sized_prod.spikes_per_day | unscheduled spikes per day (p50 + 4 MAD), right-sized VMs: synthetic median in real IQR [1.68, 10.9] | PASS | 4.6 (n=15, real median 4.07) |
| FIT | p95/mean | KS(synthetic, real re-weighted to mix {'right_sized_prod': 15, 'steady_low': 12, 'zombie': 5}) < 0.309 (alpha 0.01) | PASS | 0.23 |
| CAL | fleet | memory steadier than CPU (median CV), as in Alibaba (0.045 vs 0.2572) and Borg (0.112 vs 0.3831) | PASS | (0.158, 0.685) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (32.8, 62.6, 88.0) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (27.9, 65.1, 88.0) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (26.3, 62.6, 88.0) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (19.3, 38.8, 64.1) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (22.2, 38.9, 54.8) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (22.1, 36.0, 52.7) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (25.3, 60.1, 88.0) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (37.3, 56.5, 79.9) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (33.1, 55.8, 72.6) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (29.0, 62.7, 88.0) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (23.0, 42.2, 65.1) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (43.4, 62.6, 88.0) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (39.1, 61.5, 84.0) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (46.0, 63.8, 84.0) |
| TRUTH | right_sized_prod | 40 <= p99 < 90 (not underused, not upsize) | PASS | (47.5, 65.5, 86.0) |
| TRUTH | steady_low | P < 40 and mem P < 50 (underused -> resize) | PASS | (6.0, 12.0, 14.7) |
| TRUTH | steady_low | P < 40 and mem P < 50 (underused -> resize) | PASS | (9.2, 19.1, 23.0) |
| TRUTH | steady_low | P < 40 and mem P < 50 (underused -> resize) | PASS | (10.4, 19.6, 23.4) |
| TRUTH | steady_low | P < 40 and mem P < 50 (underused -> resize) | PASS | (5.2, 11.1, 13.9) |
| TRUTH | steady_low | P < 40 and mem P < 50 (underused -> resize) | PASS | (5.3, 10.5, 12.8) |
| TRUTH | steady_low | P < 40 and mem P < 50 (underused -> resize) | PASS | (8.7, 12.2, 14.3) |
| TRUTH | steady_low | P < 40 and mem P < 50 (underused -> resize) | PASS | (7.0, 9.4, 10.4) |
| TRUTH | steady_low | P < 40 and mem P < 50 (underused -> resize) | PASS | (4.8, 7.8, 8.8) |
| TRUTH | steady_low | P < 40 and mem P < 50 (underused -> resize) | PASS | (7.6, 10.8, 12.2) |
| TRUTH | steady_low | P < 40 and mem P < 50 (underused -> resize) | PASS | (5.0, 12.3, 16.0) |
| TRUTH | steady_low | P < 40 and mem P < 50 (underused -> resize) | PASS | (5.8, 11.6, 13.8) |
| TRUTH | steady_low | P < 40 and mem P < 50 (underused -> resize) | PASS | (7.3, 11.1, 12.8) |
| TRUTH | bursty_daily | mean < 20 and p99 >= 60 (looks idle, peaks) | PASS | (17.7, 79.1, 89.2) |
| TRUTH | bursty_daily | mean < 20 and p99 >= 60 (looks idle, peaks) | PASS | (16.8, 78.0, 88.0) |
| TRUTH | bursty_daily | mean < 20 and p99 >= 60 (looks idle, peaks) | PASS | (15.3, 77.6, 88.0) |
| TRUTH | bursty_daily | mean < 20 and p99 >= 60 (looks idle, peaks) | PASS | (14.6, 77.7, 88.3) |
| TRUTH | bursty_daily | mean < 20 and p99 >= 60 (looks idle, peaks) | PASS | (15.7, 78.6, 89.2) |
| TRUTH | bursty_daily | mean < 20 and p99 >= 60 (looks idle, peaks) | PASS | (17.1, 78.8, 87.6) |
| TRUTH | bursty_daily | mean < 20 and p99 >= 60 (looks idle, peaks) | PASS | (15.8, 77.4, 85.8) |
| TRUTH | batch_nightly | mean < 20 and p99 >= 60 (looks idle, peaks) | PASS | (10.1, 88.2, 92.3) |
| TRUTH | batch_nightly | mean < 20 and p99 >= 60 (looks idle, peaks) | PASS | (10.2, 87.3, 91.7) |
| TRUTH | batch_nightly | mean < 20 and p99 >= 60 (looks idle, peaks) | PASS | (10.2, 88.2, 92.4) |
| TRUTH | batch_nightly | mean < 20 and p99 >= 60 (looks idle, peaks) | PASS | (10.1, 87.8, 92.2) |
| TRUTH | batch_nightly | mean < 20 and p99 >= 60 (looks idle, peaks) | PASS | (10.2, 88.2, 93.6) |
| TRUTH | office_hours_dev | weekend p95 < 5 (schedulable) | PASS | (12.7, 66.0, 89.9) |
| TRUTH | office_hours_dev | weekend p95 < 5 (schedulable) | PASS | (11.9, 57.8, 86.3) |
| TRUTH | office_hours_dev | weekend p95 < 5 (schedulable) | PASS | (11.8, 53.4, 100.0) |
| TRUTH | office_hours_dev | weekend p95 < 5 (schedulable) | PASS | (12.7, 61.3, 85.2) |
| TRUTH | office_hours_dev | weekend p95 < 5 (schedulable) | PASS | (12.8, 64.7, 100.0) |
| TRUTH | office_hours_dev | weekend p95 < 5 (schedulable) | PASS | (12.9, 57.1, 81.1) |
| TRUTH | office_hours_dev | weekend p95 < 5 (schedulable) | PASS | (13.3, 59.4, 93.5) |
| TRUTH | office_hours_dev | weekend p95 < 5 (schedulable) | PASS | (12.9, 54.9, 93.1) |
| TRUTH | office_hours_dev | weekend p95 < 5 (schedulable) | PASS | (12.5, 63.1, 84.7) |
| TRUTH | office_hours_dev | weekend p95 < 5 (schedulable) | PASS | (13.5, 66.3, 100.0) |
| TRUTH | office_hours_dev | weekend p95 < 5 (schedulable) | PASS | (12.3, 58.2, 84.3) |
| TRUTH | zombie | P < 5 and mem P < 70 (idle) | PASS | (1.3, 2.8, 3.4) |
| TRUTH | zombie | P < 5 and mem P < 70 (idle) | PASS | (1.5, 1.7, 1.8) |
| TRUTH | zombie | P < 5 and mem P < 70 (idle) | PASS | (0.7, 1.0, 1.1) |
| TRUTH | zombie | P < 5 and mem P < 70 (idle) | PASS | (0.9, 2.1, 2.7) |
| TRUTH | zombie | P < 5 and mem P < 70 (idle) | PASS | (0.6, 1.6, 2.1) |
| TRUTH | memory_bound | mem p99 > 70 (memory veto) | PASS | (9.6, 19.5, 25.1) |
| TRUTH | memory_bound | mem p99 > 70 (memory veto) | PASS | (9.3, 22.4, 28.3) |
| TRUTH | memory_bound | mem p99 > 70 (memory veto) | PASS | (8.9, 20.4, 28.0) |
| PROV | ar1_phi_cpu | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=285 |
| PROV | ar1_phi_cpu_azure | has source, method and n_series | PASS | azure_vm_2017 n=1471 |
| PROV | cpu_cv_active | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=285 |
| PROV | daily_amp_ratio | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=285 |
| PROV | disk_base_over_k | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=231 |
| PROV | disk_elasticity | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=285 |
| PROV | drift_sd | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=285 |
| PROV | iops_base_alibaba | has source, method and n_series | PASS | alibaba_2018 n=5819 |
| PROV | iops_k_alibaba | has source, method and n_series | PASS | alibaba_2018 n=5819 |
| PROV | iops_lognorm_sigma | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=231 |
| PROV | mem_ar1_phi | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=284 |
| PROV | mem_base_alibaba | has source, method and n_series | PASS | alibaba_2018 n=5841 |
| PROV | mem_coupling | has source, method and n_series | PASS | alibaba_2018 n=5841 |
| PROV | mem_cv_active | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=284 |
| PROV | mem_noise_sd_pct | has source, method and n_series | PASS | alibaba_2018 n=5841 |
| PROV | mem_resid_rel_sd | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=284 |
| PROV | missing_share_alibaba | has source, method and n_series | PASS | alibaba_2018 n=5841 |
| PROV | missing_share_bitbrains | has source, method and n_series | PASS | bitbrains_fastStorage_2013 n=882 |
| PROV | net_base_over_k | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=277 |
| PROV | net_cpu_corr | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=277 |
| PROV | net_elasticity | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=285 |
| PROV | net_lognorm_sigma | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=277 |
| PROV | net_out_in_ratio | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=281 |
| PROV | peak_hour_local | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=218 |
| PROV | share_vms_mean_below_0p5 | has source, method and n_series | PASS | bitbrains_fastStorage_2013 n=1250 |
| PROV | spike_height_ratio | has source, method and n_series | PASS | azure_vm_2017 n=1452 |
| PROV | spike_len_slots | has source, method and n_series | PASS | azure_vm_2017 n=1452 |
| PROV | spike_rate_per_day | has source, method and n_series | PASS | azure_vm_2017 n=1471 |
| PROV | weekend_factor_all | has source, method and n_series | PASS | bitbrains_fastStorage_2013 n=881 |
| PROV | weekend_factor_interactive | has source, method and n_series | PASS | bitbrains_fastStorage_2013 (active VMs, mean CPU >= 5%) n=218 |
| PROV | traces | fitted_params provenance hashes == downloaded trace manifest | PASS | 5 |
| INFO | right_sized_prod | drift sd capped at 0.10 (real p50 0.6145) to keep p99 < 90 | PASS | 0.124 |
| INFO | fleet | share mean CPU < 20%: real Azure 0.9123, Bitbrains 0.8175 (depends on archetype mix) | PASS | 0.759 |
| INFO | fleet | median CPU p95: real Azure 7.2657, Bitbrains 2.9604 (our fleet is deliberately busier) | PASS | 57.4 |
| BILL | fleet | month 6 / month 1 in 1.35-1.45 | PASS | 1.383 |
| SIZE | data/ | total <= 30 MB | PASS | 13.1 MB |
| COUNT | inventory | 117 VMs, 15 volumes, 8 IPs | PASS | {'vm': 117, 'volume': 15, 'ip': 8} |
