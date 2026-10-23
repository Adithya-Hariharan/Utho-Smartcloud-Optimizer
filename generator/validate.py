"""python -m generator.validate : proves every planted case, fault and calibration target is present.
Writes data/validation_report.md and exits non-zero on any failure."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CALIBRATION, N_SLOTS, SLOTS_PER_DAY, TZ, WINDOW_START

DATA = Path(__file__).resolve().parent.parent / "data"
PCT = ["cpu_pct", "mem_pct", "disk_used_pct"]


def light_clean(df):
    """Only what is needed to measure: snap, sort, dedupe, impossible values -> NaN."""
    df = df.copy()
    df["resource_id"] = df["resource_id"].astype(str)
    df["ts"] = df["ts"].dt.floor("5min")
    df = df.sort_values(["resource_id", "ts"]).drop_duplicates(["resource_id", "ts"], keep="first")
    for c in PCT:
        df.loc[(df[c] < 0) | (df[c] > 100), c] = np.nan
    df["slot"] = ((df["ts"] - WINDOW_START.tz_convert("UTC")) / pd.Timedelta("5min")).astype(int)
    ist = df["ts"].dt.tz_convert(TZ)
    df["hour"] = ist.dt.hour + ist.dt.minute / 60
    df["dow"] = ist.dt.dayofweek
    df["day"] = df["slot"] // SLOTS_PER_DAY
    return df


def main():
    inv = pd.read_csv(DATA / "inventory.csv", keep_default_na=False)
    raw = pd.read_parquet(DATA / "metrics.parquet")
    vol = pd.read_parquet(DATA / "volume_metrics.parquet")
    bill = pd.read_parquet(DATA / "billing_daily.parquet")
    truth = pd.read_csv(DATA / "truth.csv", keep_default_na=False)
    m = light_clean(raw)
    rid = dict(zip(inv["name"], inv["resource_id"]))
    g = {k: v for k, v in m.groupby("resource_id")}
    results = []

    def check(case, name, desc, ok, value):
        results.append((case, name, desc, bool(ok), value))

    def s(name):
        return g[rid[name]]

    def q(x, p):
        return float(np.nanpercentile(x, p))

    # ---------------- planted workload shapes
    d = s("prod-api-01"); check("A1", "prod-api-01", "cpu p95 60-80", 60 <= q(d.cpu_pct, 95) <= 80, round(q(d.cpu_pct, 95), 1))
    d = s("prod-api-07"); check("A2", "prod-api-07", "cpu p99 25-35, mem p99 < 25",
                                25 <= q(d.cpu_pct, 99) <= 35 and q(d.mem_pct, 99) < 25,
                                (round(q(d.cpu_pct, 99), 1), round(q(d.mem_pct, 99), 1)))
    d = s("prod-batch-07"); check("A3", "prod-batch-07", "mean 6-10, p99 88-95",
                                  6 <= d.cpu_pct.mean() <= 10 and 88 <= q(d.cpu_pct, 99) <= 95,
                                  (round(d.cpu_pct.mean(), 1), round(q(d.cpu_pct, 99), 1)))
    d = s("prod-billing-01"); check("A4", "prod-billing-01", "p99 >= 85 (Sunday peak), mean < 10",
                                    q(d.cpu_pct, 99) >= 85 and d.cpu_pct.mean() < 10,
                                    (round(d.cpu_pct.mean(), 1), round(q(d.cpu_pct, 99), 1)))
    d = s("dev-report-02"); check("A5", "dev-report-02", "p99 < 30 but max >= 90 (p99 misses weekly job)",
                                  q(d.cpu_pct, 99) < 30 and d.cpu_pct.max() >= 90,
                                  (round(q(d.cpu_pct, 99), 1), round(d.cpu_pct.max(), 1)))
    d = s("prod-reports-02")
    top = d.groupby("day").cpu_pct.max().idxmax()
    check("A6", "prod-reports-02", "p99 >= 85, p99 without top day < 40",
          q(d.cpu_pct, 99) >= 85 and q(d[d.day != top].cpu_pct, 99) < 40,
          (round(q(d.cpu_pct, 99), 1), round(q(d[d.day != top].cpu_pct, 99), 1)))
    d = s("prod-checkout-03"); check("A7", "prod-checkout-03", "mean 11-17, p99 >= 80",
                                     11 <= d.cpu_pct.mean() <= 17 and q(d.cpu_pct, 99) >= 80,
                                     (round(d.cpu_pct.mean(), 1), round(q(d.cpu_pct, 99), 1)))
    d = s("prod-queue-02"); check("A8", "prod-queue-02", "mean < 20, p99 >= 70",
                                  d.cpu_pct.mean() < 20 and q(d.cpu_pct, 99) >= 70,
                                  (round(d.cpu_pct.mean(), 1), round(q(d.cpu_pct, 99), 1)))
    d = s("prod-cache-04"); check("A9", "prod-cache-04", "cpu p99 < 10, mem p99 >= 80",
                                  q(d.cpu_pct, 99) < 10 and q(d.mem_pct, 99) >= 80,
                                  (round(q(d.cpu_pct, 99), 1), round(q(d.mem_pct, 99), 1)))
    d = s("prod-search-06"); check("A10", "prod-search-06", "mem mean >= 75, std < 2",
                                   d.mem_pct.mean() >= 75 and d.mem_pct.std() < 2,
                                   (round(d.mem_pct.mean(), 1), round(d.mem_pct.std(), 2)))
    d = s("prod-orders-08")
    drops = int((d.mem_pct.diff() < -25).sum())
    check("A11", "prod-orders-08", ">= 3 sawtooth resets (mem drop > 25 pts)", drops >= 3, drops)
    for case, name in (("A12", "prod-db-01"), ("A13", "prod-ingest-09")):
        d = s(name); prov = inv.set_index("name").loc[name, "provisioned_iops"]
        v = q(d.iops / float(prov) * 100, 95)
        check(case, name, "iops p95 >= 70% of provisioned", v >= 70, round(v, 1))
    d = s("prod-gateway-03"); bw = float(inv.set_index("name").loc["prod-gateway-03", "bandwidth_mbps"])
    v = q(d.net_in_mbps / bw * 100, 95)
    check("A14", "prod-gateway-03", "cpu p99 < 10, net p95 >= 60% bw", q(d.cpu_pct, 99) < 10 and v >= 60,
          (round(q(d.cpu_pct, 99), 1), round(v, 1)))
    d = s("prod-api-04"); dp = d.groupby("day").cpu_pct.quantile(0.95)
    slope = float(np.polyfit(dp.index, dp.values, 1)[0])
    check("A15", "prod-api-04", "daily p95 slope > 1 %/day", slope > 1, round(slope, 2))
    d = s("prod-search-02"); check("A16", "prod-search-02", "cpu p99 > 90", q(d.cpu_pct, 99) > 90, round(q(d.cpu_pct, 99), 1))
    d = s("prod-legacy-06"); r = d[d.day >= 23].cpu_pct.mean() / d[d.day < 22].cpu_pct.mean()
    check("A17", "prod-legacy-06", "last-7d / prior mean < 0.2", r < 0.2, round(float(r), 3))
    d = s("prod-ml-10"); check("A18", "prod-ml-10", "cpu p99 < 15, mem p99 in 37.5-50",
                               q(d.cpu_pct, 99) < 15 and 37.5 < q(d.mem_pct, 99) < 50,
                               (round(q(d.cpu_pct, 99), 1), round(q(d.mem_pct, 99), 1)))
    d = s("dev-tiny-14"); check("A19", "dev-tiny-14", "S1 and cpu p95 < 5",
                                inv.set_index("name").loc["dev-tiny-14", "plan_id"] == "S1" and q(d.cpu_pct, 95) < 5,
                                round(q(d.cpu_pct, 95), 2))
    d = s("staging-web-08"); check("A20", "staging-web-08", "cpu p95 27-33 (needs ~3 vCPU of 8)",
                                   27 <= q(d.cpu_pct, 95) <= 33, round(q(d.cpu_pct, 95), 1))
    d = s("staging-api-09"); check("A21", "staging-api-09", "cpu p95 == 40.0 exactly",
                                   q(d.cpu_pct, 95) == 40.0, q(d.cpu_pct, 95))
    grp = inv[inv.service_group == "web-frontend"]
    check("A23", "prod-web-11a/b/c", "3 members share service_group", len(grp) == 3, len(grp))
    tags = inv.set_index("name")["tags"]
    check("A24", "prod-k8s-node-*", "3 nodes tagged autoscaled",
          sum("autoscaled" in tags[f"prod-k8s-node-{i}"] for i in (1, 2, 3)) == 3, "")
    check("A25", "prod-checkout-01", "tagged seasonal_peak", "seasonal_peak" in tags["prod-checkout-01"], "")

    # ---------------- idle and scheduling
    d = s("staging-db-02"); check("B1", "staging-db-02", "cpu p99 < 5, stateful", q(d.cpu_pct, 99) < 5 and "stateful" in tags["staging-db-02"], round(q(d.cpu_pct, 99), 2))
    d = s("dev-cache-13"); check("B3", "dev-cache-13", "cpu p95 < 5, mem p99 > 70", q(d.cpu_pct, 95) < 5 and q(d.mem_pct, 99) > 70,
                                 (round(q(d.cpu_pct, 95), 1), round(q(d.mem_pct, 99), 1)))
    d = s("dev-web-03"); wk = d[d.dow >= 5]
    check("B4", "dev-web-03", "weekend p95 < 5, overall p95 < 12, mem p95 <= 18.75 (fits 8 GB)",
          q(wk.cpu_pct, 95) < 5 and q(d.cpu_pct, 95) < 12 and q(d.mem_pct, 95) <= 18.75,
          (round(q(wk.cpu_pct, 95), 1), round(q(d.cpu_pct, 95), 1), round(q(d.mem_pct, 95), 1)))
    d = s("dev-etl-04"); n = d[(d.hour >= 1) & (d.hour < 3)]
    check("B5", "dev-etl-04", "01-03 p95 >= 60", q(n.cpu_pct, 95) >= 60, round(q(n.cpu_pct, 95), 1))
    d = s("dev-support-05"); night = (d.hour >= 22) | (d.hour < 6)
    check("B6", "dev-support-05", "night mean > 3x day mean", d[night].cpu_pct.mean() > 3 * d[~night].cpu_pct.mean(),
          (round(d[night].cpu_pct.mean(), 1), round(d[~night].cpu_pct.mean(), 1)))
    d = s("staging-load-06"); we = d[(d.dow >= 5) & (d.hour >= 10) & (d.hour < 18)]
    check("B7", "staging-load-06", "weekend-day mean > 50, weekday p95 < 5",
          we.cpu_pct.mean() > 50 and q(d[d.dow < 5].cpu_pct, 95) < 5,
          (round(we.cpu_pct.mean(), 1), round(q(d[d.dow < 5].cpu_pct, 95), 1)))
    d = s("dev-misc-07")
    how = d.assign(wk=d.day // 7, hw=d.dow * 24 + d.hour.astype(int))
    off = how.groupby(["hw", "wk"]).cpu_pct.quantile(0.95).groupby("hw").max() < 5
    check("B9", "dev-misc-07", "< 40 consistently-quiet hours/week", off.sum() < 40, int(off.sum()))
    check("B10", "staging-demo-10", "keep_running + no_schedule",
          "keep_running" in tags["staging-demo-10"] and inv.set_index("name").loc["staging-demo-10", "optimize_policy"] == "no_schedule", "")

    # ---------------- stopped, lifecycle, inventory
    ids_with_metrics = set(m.resource_id)
    check("C10", "vm-stopped-07", "stopped, no metrics", rid["vm-stopped-07"] not in ids_with_metrics, "")
    d = s("vm-maint-08"); check("C11", "vm-maint-08", "metrics end 2026-10-17", d.day.max() == 27, int(d.day.max()))
    d = s("dev-test-12"); check("D1", "dev-test-12", "<= 3 days of data", d.day.nunique() <= 3, d.day.nunique())
    i5 = inv.set_index("name").loc["staging-app-05"]
    check("D2", "staging-app-05", "resized B4->B3 on 2026-10-14", i5.previous_plan_id == "B4" and i5.last_resized_at.startswith("2026-10-14"), "")
    check("D3", "prod-standby-01", "dr_standby tag + policy never",
          "dr_standby" in tags["prod-standby-01"] and inv.set_index("name").loc["prod-standby-01", "optimize_policy"] == "never", "")
    check("D4", "prod-nomon-13", "no metrics", rid["prod-nomon-13"] not in ids_with_metrics, "")
    check("D5", "vm-untagged-14", "env empty", inv.set_index("name").loc["vm-untagged-14", "env"] == "", "")
    check("D6", "dev-orphan-owner-15", "owner empty", inv.set_index("name").loc["dev-orphan-owner-15", "owner_team"] == "", "")
    check("D7", "dev-misnamed-16", "name dev-*, env prod", inv.set_index("name").loc["dev-misnamed-16", "env"] == "prod", "")
    check("D8", "prod-legacy-plan-17", "plan not in pricing",
          inv.set_index("name").loc["prod-legacy-plan-17", "plan_id"] not in set(pd.read_csv(DATA / "pricing.csv")["item"]), "")
    check("D9", "vm-ghost-99", "metrics without inventory", "vm-9999" in ids_with_metrics and "vm-9999" not in set(inv.resource_id), "")
    d = s("prod-worker-05"); r = d[d.day >= 28].cpu_pct.mean() / d[d.day < 28].cpu_pct.mean()
    check("D10", "prod-worker-05", "last-48h / prior mean >= 3.5", r >= 3.5, round(float(r), 2))

    # ---------------- data-quality faults (measured on RAW data)
    rawg = {k: v for k, v in raw.assign(resource_id=raw.resource_id.astype(str)).groupby("resource_id")}
    d = s("prod-api-02")
    missing = np.array(sorted(set(range(N_SLOTS)) - set(d.slot)))
    run = int(pd.Series(missing).groupby((np.diff(missing, prepend=-2) != 1).cumsum()).size().max()) if len(missing) else 0
    check("E1", "prod-api-02", "contiguous gap of 72 slots (6 h)", run >= 72, run)
    r3 = rawg[rid["dev-web-03"]]
    dups = int(r3.ts.duplicated().sum())
    check("E2", "dev-web-03", "duplicate timestamps present", dups >= 10, dups)
    oor = int(((raw.cpu_pct > 100) | (raw.cpu_pct < 0)).sum())
    check("E3", "fleet", ">= 15 out-of-range CPU values", oor >= 15, oor)
    ooo = sum(int((v.ts.diff().dt.total_seconds() < 0).any()) for v in rawg.values())
    check("E4", "fleet", ">= 2 resources with out-of-order rows", ooo >= 2, ooo)
    full = [k for k, v in g.items() if v.day.min() == 0 and v.day.max() == 29 and k not in
            {rid[n] for n in ("dev-flaky-18", "staging-flaky-19", "prod-batch-20", "prod-api-02")}]
    share_missing = 1 - np.mean([len(g[k]) / N_SLOTS for k in full])
    lo, hi = CALIBRATION["random_missing_share"]
    check("E5", "fleet", f"random missing share {lo}-{hi}", lo <= share_missing <= hi, round(share_missing, 4))
    cov18 = len(s("dev-flaky-18")) / N_SLOTS; cov19 = len(s("staging-flaky-19")) / N_SLOTS
    check("E6", "dev-flaky-18", "coverage 0.65-0.75", 0.65 <= cov18 <= 0.75, round(cov18, 3))
    check("E7", "staging-flaky-19", "coverage 0.85-0.92", 0.85 <= cov19 <= 0.92, round(cov19, 3))
    d = s("dev-api-16"); flat = int(((d.day.isin([15, 16])) & (d.cpu_pct == 0)).sum())
    check("E8", "dev-api-16", ">= 500 rows of exact 0.0 on days 15-16", flat >= 500, flat)
    d = s("prod-batch-20"); pk = d[(d.hour >= 1) & (d.hour < 4)]
    cov = len(pk) / (30 * 36)
    check("E9", "prod-batch-20", "01-04 coverage < 0.5", cov < 0.5, round(cov, 3))
    jit = int((raw.ts.dt.minute % 5 != 0).sum())
    check("E10", "fleet", "irregular timestamps present", jit > 0, jit)
    check("E11", "fleet", "timestamps stored in UTC", str(raw.ts.dt.tz) == "UTC", str(raw.ts.dt.tz))

    # ---------------- alerts inputs
    d = s("dev-sandbox-17"); before, after = d[d.day < 26], d[d.day >= 26]
    ratio = after.net_out_mbps.mean() / before.net_out_mbps.mean()
    check("G4", "dev-sandbox-17", "cpu > 90 after day 26, net_out x >= 8",
          after.cpu_pct.mean() > 90 and ratio >= 8, (round(after.cpu_pct.mean(), 1), round(ratio, 1)))
    filling = truth[truth.edge_case_id == "G5-disk"].resource_id
    slopes = [np.polyfit(g[x].slot / SLOTS_PER_DAY, g[x].disk_used_pct, 1)[0] for x in filling]
    check("G5", "4 bulk VMs", "disk slope ~0.8 %/day", len(slopes) == 4 and all(0.7 < x < 0.9 for x in slopes),
          [round(x, 2) for x in slopes])
    vg = vol[vol.resource_id.astype(str) == rid["vol-growing-10"]]
    vs = np.polyfit((vg.ts - vg.ts.min()).dt.total_seconds() / 86400, vg.disk_used_pct, 1)[0]
    check("C6", "vol-growing-10", "used slope ~2 %/day", 1.8 < vs < 2.2, round(vs, 2))
    vi = vol[vol.resource_id.astype(str) == rid["vol-idle-04"]]
    check("C3", "vol-idle-04", "zero IOPS all window", float(vi.iops.max()) == 0.0, float(vi.iops.max()))
    vinv = inv.set_index("name")
    check("C1", "vol-orphan-11", "unattached since 2026-08-16", vinv.loc["vol-orphan-11", "attached_to"] == "" and vinv.loc["vol-orphan-11", "unattached_since"].startswith("2026-08-16"), "")
    check("C2", "vol-new-12", "unattached 2 days", vinv.loc["vol-new-12", "unattached_since"].startswith("2026-10-18"), "")
    check("C7", "ip-unused-03", "unassociated", vinv.loc["ip-unused-03", "attached_to"] == "", "")
    check("C8", "ip-stopped-02", "on vm-stopped-07", vinv.loc["ip-stopped-02", "attached_to"] == rid["vm-stopped-07"], "")
    check("C9", "ip-allowlist-04", "allowlisted tag", "allowlisted_ip" in vinv.loc["ip-allowlist-04", "tags"], "")
    newbies = inv[inv.created_at.str.startswith("2026-10-12")]
    check("G7", "growth team", "4 VMs created 2026-10-12", len(newbies) == 4 and set(newbies.owner_team) == {"growth"}, len(newbies))

    # ---------------- fleet calibration
    vms = [k for k in g if k in set(inv[inv.type == "vm"].resource_id)]
    stats = pd.DataFrame({k: {"mean": g[k].cpu_pct.mean(), "p95": q(g[k].cpu_pct, 95),
                              "cpu_cv": g[k].cpu_pct.std() / max(g[k].cpu_pct.mean(), 1e-6),
                              "mem_cv": g[k].mem_pct.std() / max(g[k].mem_pct.mean(), 1e-6)} for k in vms}).T
    share = float((stats["mean"] < 20).mean()); lo, hi = CALIBRATION["share_mean_cpu_below_20"]
    check("CAL", "fleet", f"share of VMs with mean CPU < 20% in {lo}-{hi} (Azure)", lo <= share <= hi, round(share, 3))
    ratio = float((stats.p95 / stats["mean"].clip(lower=0.5)).median()); lo, hi = CALIBRATION["median_p95_over_mean_cpu"]
    check("CAL", "fleet", f"median p95/mean CPU in {lo}-{hi} (Azure)", lo <= ratio <= hi, round(ratio, 2))
    check("CAL", "fleet", "median memory CV < median CPU CV (Bitbrains/Google)",
          stats.mem_cv.median() < stats.cpu_cv.median(), (round(stats.mem_cv.median(), 3), round(stats.cpu_cv.median(), 3)))
    check("CAL", "fleet", f"median CPU p95 < {CALIBRATION['median_cpu_p95_below']}% (Google: usage << allocation)",
          stats.p95.median() < CALIBRATION["median_cpu_p95_below"], round(stats.p95.median(), 1))

    # ---------------- billing and size
    daily = bill.groupby("date").cost_inr.sum().sort_index()
    growth = daily.iloc[-30:].sum() / daily.iloc[:30].sum()
    check("BILL", "fleet", "month 6 / month 1 in 1.35-1.45", 1.35 <= growth <= 1.45, round(growth, 3))
    size_mb = sum(f.stat().st_size for f in DATA.rglob("*") if f.is_file()) / 1e6
    check("SIZE", "data/", "total <= 30 MB", size_mb <= 30, f"{size_mb:.1f} MB")
    check("COUNT", "inventory", "117 VMs, 15 volumes, 8 IPs",
          inv.type.value_counts().to_dict() == {"vm": 117, "volume": 15, "ip": 8}, inv.type.value_counts().to_dict())

    # ---------------- report
    rep = pd.DataFrame(results, columns=["case", "resource", "check", "pass", "value"])
    lines = ["# Validation report", "", f"{rep['pass'].sum()} / {len(rep)} checks passed.", "",
             f"Monthly run-rate (last day x 730/24): Rs {daily.iloc[-1] * 730 / 24:,.0f}", "",
             "| case | resource | check | result | value |", "|---|---|---|---|---|"]
    lines += [f"| {r.case} | {r.resource} | {r.check} | {'PASS' if r['pass'] else '**FAIL**'} | {r.value} |"
              for _, r in rep.iterrows()]
    (DATA / "validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for _, r in rep.iterrows():
        print(f"{'PASS' if r['pass'] else 'FAIL'}  {r.case:<5} {r.resource:<20} {r.check:<60} {r.value}")
    print(f"\n{rep['pass'].sum()}/{len(rep)} passed")
    sys.exit(0 if rep["pass"].all() else 1)


if __name__ == "__main__":
    main()
