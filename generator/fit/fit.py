"""CP3: fit generator parameters from real traces -> generator/fitted_params.json

python -m generator.fit.fit

Every value records {value, p25, p75, n_series, source, method}. Only channels identified in
trace_schema.json are used. Seeded subsampling keeps the output deterministic.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

from .traces import EXTERNAL, items

import os

OUT = Path(os.environ.get("SCO_FIT_OUT", Path(__file__).resolve().parents[1] / "fitted_params.json"))
SEED = 42
SLOTS_DAY = 288
BITBRAINS_UTC_OFFSET_H = 2          # CEST


def entry(values, source, method, value=None):
    v = np.asarray([x for x in values if np.isfinite(x)], dtype=float)
    return {"value": round(float(np.median(v) if value is None else value), 6),
            "p25": round(float(np.percentile(v, 25)), 6), "p75": round(float(np.percentile(v, 75)), 6),
            "p10": round(float(np.percentile(v, 10)), 6), "p90": round(float(np.percentile(v, 90)), 6),
            "n_series": int(len(v)), "source": source, "method": method}


# ------------------------------------------------------------------ per-series helpers
def lag1(x):
    a, b = x[:-1], x[1:]
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 100 or np.std(a[m]) == 0 or np.std(b[m]) == 0:
        return np.nan
    return float(np.corrcoef(a[m], b[m])[0, 1])


def residual(x, hod, weekend, day):
    """Remove weekday/weekend hour-of-day profile and the day-level offset -> within-day noise."""
    r = x.copy()
    for w in (False, True):
        sel = weekend == w
        if sel.sum() == 0:
            continue
        prof = np.full(SLOTS_DAY, np.nan)
        for h in range(SLOTS_DAY):
            v = x[sel & (hod == h)]
            prof[h] = np.nanmean(v) if np.isfinite(v).any() else np.nan
        r[sel] = x[sel] - prof[hod[sel]]
    for d in np.unique(day):
        sel = day == d
        if np.isfinite(r[sel]).any():
            r[sel] -= np.nanmean(r[sel])
    return r


def time_index(start, n, offset_h=0):
    t = start + np.timedelta64(offset_h, "h") + np.arange(n) * np.timedelta64(5, "m")
    days = t.astype("datetime64[D]")
    hod = ((t - days).astype("timedelta64[m]").astype(int) // 5)
    dow = (days.astype(int) + 3) % 7          # 1970-01-01 was a Thursday -> Monday = 0
    return hod, dow >= 5, (days - days[0]).astype(int), dow


def hourly_profile(x, hod, weekend):
    sel = ~weekend
    return np.array([np.nanmean(x[sel & (hod // 12 == h)]) for h in range(24)])


def linfit(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 100 or np.std(x[m]) == 0:
        return np.nan, np.nan
    slope, icpt = np.polyfit(x[m], y[m], 1)
    return float(slope), float(icpt)


def log_resid_sd(y, fit):
    m = np.isfinite(y) & np.isfinite(fit) & (y > 0) & (fit > 0)
    return float(np.std(np.log(y[m] / fit[m]))) if m.sum() > 100 else np.nan


# ------------------------------------------------------------------ archetype classifier (shared)
def classify(f):
    """Rules on per-VM features -> one of our 7 bulk archetypes or None."""
    mean, p95, p99, amp, idle, wkf, top2 = (f["mean"], f["p95"], f["p99"], f["amp_ratio"], f["idle_share"],
                                            f["weekend_factor"], f["top2h_share"])
    if mean < 2.5 and p95 < 5:
        return "zombie"
    daily_peaks = f.get("peak_days_share", 0) >= 0.6       # our batch/bursty archetypes peak (almost) every day
    if idle > 0.6 and p99 > 50 and top2 > 0.35 and daily_peaks:
        return "batch_nightly"
    if mean < 20 and p99 > 60 and daily_peaks:
        return "bursty_daily"
    if amp > 1.0 and np.isfinite(wkf) and wkf < 0.5:
        return "office_hours_dev"
    if mean < 12 and p95 / max(mean, 0.1) < 2.0:
        return "steady_low"
    if 20 <= mean <= 60 and amp > 0.3:
        return "right_sized_prod"
    return None


def vm_features(cpu, start, offset_h):
    n = len(cpu)
    hod, weekend, day, dow = time_index(start, n, offset_h)
    prof = hourly_profile(cpu, hod, weekend)
    mean = float(np.nanmean(cpu))
    wd, we = np.nanmean(cpu[~weekend]), np.nanmean(cpu[weekend]) if weekend.any() else np.nan
    daily_tot = np.nansum(prof) if np.isfinite(prof).any() else np.nan
    srt = np.sort(prof[np.isfinite(prof)])[::-1]
    res = residual(cpu, hod, weekend, day)
    day_means = np.array([np.nanmean(cpu[day == d]) for d in np.unique(day)[1:-1]])   # drop partial days
    day_types = np.array([weekend[day == d][0] for d in np.unique(day)[1:-1]])
    ratios = []
    for w in (False, True):
        dm = day_means[day_types == w]
        if len(dm) > 2 and np.nanmean(dm) > 0:
            ratios.extend(dm / np.nanmean(dm))
    return {
        "mean": mean, "p50": float(np.nanpercentile(cpu, 50)), "p95": float(np.nanpercentile(cpu, 95)),
        "p99": float(np.nanpercentile(cpu, 99)),
        "amp_ratio": float((np.nanmax(prof) - np.nanmin(prof)) / max(mean, 0.1)),
        "trough": float(np.nanmin(prof)), "peak": float(np.nanmax(prof)),
        "peak_hour": int(np.nanargmax(prof)) if np.isfinite(prof).any() else -1,
        "idle_share": float(np.nanmean(cpu < 5)),
        "weekend_factor": float(we / wd) if wd and np.isfinite(we) and wd > 0.5 else np.nan,
        "top2h_share": float(srt[:2].sum() / daily_tot) if daily_tot and daily_tot > 0 else np.nan,
        "phi": lag1(res), "sigma": float(np.nanstd(res)),
        "drift_sd": float(np.nanstd(ratios)) if len(ratios) > 5 else np.nan,
        "cv": float(np.nanstd(cpu) / max(mean, 0.1)), "nan_share": float(np.isnan(cpu).mean()),
        "peak_days_share": float(np.mean([np.nanmax(cpu[day == d]) > 60 for d in np.unique(day)
                                          if np.isfinite(cpu[day == d]).any()])),
        "hod": hod, "weekend": weekend, "day": day,
    }


# ------------------------------------------------------------------ per-trace fitting
def fit_bitbrains():
    feats = []
    for it in items("bitbrains_5T"):
        c = it["channels"]
        cpu = np.clip(c["cpu_pct"], 0, 100)
        if np.isnan(cpu).mean() > 0.5 or np.nanmean(cpu) < 0.5:
            continue
        f = vm_features(cpu, it["start"], BITBRAINS_UTC_OFFSET_H)
        mem = c.get("mem_kb")
        if mem is not None and np.nanmean(mem) > 0:
            mres = residual(mem, f["hod"], f["weekend"], f["day"])
            f["mem_cv"] = float(np.nanstd(mem) / np.nanmean(mem))
            f["mem_phi"] = lag1(mres)
            f["mem_resid_rel_sd"] = float(np.nanstd(mres) / np.nanmean(mem))
        for kind, a, b in (("net", "net_rx_kbps", "net_tx_kbps"), ("disk", "disk_read_kbps", "disk_write_kbps")):
            if a in c and b in c:
                tot = c[a] + c[b]
                s1, s0 = linfit(cpu, tot)
                if np.isfinite(s1) and s1 > 0:
                    f[f"{kind}_base_over_k"] = s0 / s1          # intercept in CPU-% units (scale-free)
                    f[f"{kind}_lognorm_sigma"] = log_resid_sd(tot, s0 + s1 * cpu)
                    f[f"{kind}_corr"] = float(np.corrcoef(np.nan_to_num(cpu), np.nan_to_num(tot))[0, 1])
                lc, lt = np.log(cpu + 0.5), np.log(tot + 1e-3)
                el, _ = linfit(lc, lt)
                f[f"{kind}_elasticity"] = el                    # d log(throughput) / d log(cpu)
                if kind == "net" and np.nansum(c[a]) > 0:
                    f["net_out_in"] = float(np.nansum(c[b]) / np.nansum(c[a]))
        for k in ("hod", "weekend", "day"):
            f.pop(k)
        feats.append(f)
    return feats


def fit_azure(rng, n=2000):
    feats = []
    for it in items("azure_2017", rng=rng, sample=n):
        cpu = it["channels"].get("cpu_avg_pct")
        if cpu is None or len(cpu) < 7 * SLOTS_DAY or np.isnan(cpu).mean() > 0.5 or np.nanmean(cpu) < 0.5:
            continue
        f = vm_features(np.clip(cpu, 0, 100), it["start"], 0)
        # unscheduled spikes: excursions above p50 + 4*MAD lasting >= 1 slot, per day
        x = np.clip(cpu, 0, 100)
        med = np.nanmedian(x)
        mad = np.nanmedian(np.abs(x - med)) + 1e-6
        hi = np.nan_to_num(x > med + 4 * mad)
        starts = np.flatnonzero(np.diff(np.concatenate([[0], hi.astype(int)])) == 1)
        ends = np.flatnonzero(np.diff(np.concatenate([hi.astype(int), [0]])) == -1)
        # Azure V1 timestamps are relative: weekday/time-of-day alignment is unknown, so drop
        # every feature that depends on it (amplitude ratio is shift-invariant and kept)
        f["weekend_factor"], f["peak_hour"], f["drift_sd"] = np.nan, -1, np.nan
        f["spikes_per_day"] = len(starts) / (len(x) / SLOTS_DAY)
        f["spike_len_slots"] = float(np.median(ends - starts + 1)) if len(starts) else np.nan
        peaks = [np.nanmax(x[a:b + 1]) for a, b in zip(starts, ends)]
        f["spike_height_ratio"] = float(np.median(peaks) / max(med, 0.5)) if peaks else np.nan
        f["spike_excess_mad"] = float(np.median((np.array(peaks) - med) / mad)) if peaks else np.nan
        for k in ("hod", "weekend", "day"):
            f.pop(k)
        feats.append(f)
    return feats


def fit_alibaba():
    feats = []
    for it in items("alibaba_2018"):
        c = it["channels"]
        if "cpu_pct" not in c or "mem_pct" not in c:
            continue
        cpu, mem = np.clip(c["cpu_pct"], 0, 100), np.clip(c["mem_pct"], 0, 100)
        if np.isnan(cpu).mean() > 0.5:
            continue
        slope, icpt = linfit(cpu, mem)
        f = {"mean": float(np.nanmean(cpu)), "p95": float(np.nanpercentile(cpu, 95)),
             "mem_mean": float(np.nanmean(mem)), "mem_slope": slope, "mem_icpt": icpt,
             "mem_cv": float(np.nanstd(mem) / max(np.nanmean(mem), 0.1)),
             "cpu_cv": float(np.nanstd(cpu) / max(np.nanmean(cpu), 0.1)),
             "mem_phi": lag1(mem - np.nanmean(mem)), "cpu_phi": lag1(cpu - np.nanmean(cpu)),
             "mem_noise_sd_pct": float(np.nanstd(mem - (icpt + slope * cpu))) if np.isfinite(slope) else np.nan,
             "nan_share": float(np.isnan(cpu).mean())}
        if "disk_io_pct" in c:
            s1, s0 = linfit(cpu, c["disk_io_pct"])
            f["iops_k"], f["iops_base"] = s1, s0
            f["iops_lognorm_sigma"] = log_resid_sd(c["disk_io_pct"], s0 + s1 * cpu) if np.isfinite(s1) else np.nan
        if "net_in" in c and "net_out" in c and np.nansum(c["net_in"]) > 0:
            f["net_out_in"] = float(np.nansum(c["net_out"]) / np.nansum(c["net_in"]))
        feats.append(f)
    return feats


def fit_borg(rng, n=3000):
    feats = []
    for it in items("borg_2011", rng=rng, sample=n):
        c = it["channels"]
        if "cpu_usage_norm" not in c or "mem_usage_norm" not in c:
            continue
        cpu, mem = c["cpu_usage_norm"], c["mem_usage_norm"]
        if np.nanmean(cpu) <= 0 or np.nanmean(mem) <= 0 or np.isfinite(cpu).sum() < 100:
            continue
        feats.append({"cpu_cv": float(np.nanstd(cpu) / np.nanmean(cpu)),
                      "mem_cv": float(np.nanstd(mem) / np.nanmean(mem))})
    return feats


def col(feats, k):
    return [f[k] for f in feats if k in f and f[k] is not None and np.isfinite(f[k])]


# ------------------------------------------------------------------ main
def main():
    rng = np.random.default_rng(SEED)
    bb = fit_bitbrains()
    az = fit_azure(rng)
    al = fit_alibaba()
    bo = fit_borg(rng)
    B, A, L, G = "bitbrains_fastStorage_2013", "azure_vm_2017", "alibaba_2018", "borg_2011"

    act = [f for f in bb if f["mean"] >= 5]             # active VMs: dynamics are meaningless on ~0% series
    A_ = f"{B} (active VMs, mean CPU >= 5%)"
    P = {}
    P["ar1_phi_cpu"] = entry(col(act, "phi"), A_, "lag-1 autocorr of CPU residual after removing weekday/weekend hour-of-day profile and day offset")
    P["ar1_phi_cpu_azure"] = entry(col(az, "phi"), A, "same method on Azure avg CPU (cross-check)")
    # sigma = a * mean^b (noise grows with level)
    m = np.array([f["mean"] for f in bb if np.isfinite(f["sigma"]) and f["sigma"] > 0 and f["mean"] > 0.5])
    s = np.array([f["sigma"] for f in bb if np.isfinite(f["sigma"]) and f["sigma"] > 0 and f["mean"] > 0.5])
    b, loga = np.polyfit(np.log(m), np.log(s), 1)
    P["ar1_sigma_model"] = {"a": round(float(np.exp(loga)), 6), "b": round(float(b), 6), "n_series": int(len(m)),
                            "source": B, "method": "log-log regression of residual std on mean CPU: sigma = a * mean^b"}
    P["drift_sd"] = entry(col(act, "drift_sd"), A_, "std of day mean / mean of same day-type (weekday or weekend)")
    inter = [f for f in act if f["amp_ratio"] > 0.5]
    P["weekend_factor_interactive"] = entry(col(inter, "weekend_factor"), A_, "weekend mean / weekday mean, VMs with daily amplitude ratio > 0.5")
    P["weekend_factor_all"] = entry(col(bb, "weekend_factor"), B, "weekend mean / weekday mean, all VMs")
    P["daily_amp_ratio"] = entry(col(act, "amp_ratio"), A_, "(max - min) of weekday hourly profile / mean")
    P["peak_hour_local"] = entry([f["peak_hour"] for f in inter if f["peak_hour"] >= 0], A_,
                                 "hour of weekday profile maximum, local time (UTC+2), interactive VMs")
    P["mem_ar1_phi"] = entry(col(act, "mem_phi"), A_, "lag-1 autocorr of memory residual (same method as CPU)")
    P["mem_resid_rel_sd"] = entry(col(act, "mem_resid_rel_sd"), A_, "std of memory residual / mean memory")
    P["mem_coupling"] = entry(col(al, "mem_slope"), L, "per-machine OLS slope of mem% on cpu%")
    P["mem_base_alibaba"] = entry(col(al, "mem_icpt"), L, "per-machine OLS intercept of mem% on cpu%")
    P["net_base_over_k"] = entry(col(act, "net_base_over_k"), A_, "OLS (rx+tx) = c0 + c1*cpu%; c0/c1 in CPU-% units")
    P["net_lognorm_sigma"] = entry(col(act, "net_lognorm_sigma"), A_, "std of log(actual / OLS fit), network")
    P["net_cpu_corr"] = entry(col(act, "net_corr"), A_, "corr(cpu%, rx+tx)")
    P["net_out_in_ratio"] = entry(col(act, "net_out_in"), A_, "sum(tx) / sum(rx) per VM")
    P["net_elasticity"] = entry(col(act, "net_elasticity"), A_, "OLS slope of log(rx+tx) on log(cpu%+0.5)")
    P["disk_elasticity"] = entry(col(act, "disk_elasticity"), A_, "OLS slope of log(read+write) on log(cpu%+0.5)")
    P["mem_cv_active"] = entry(col(act, "mem_cv"), A_, "std/mean of memory usage per VM")
    P["cpu_cv_active"] = entry(col(act, "cv"), A_, "std/mean of CPU per VM")
    P["share_vms_mean_below_0p5"] = {"value": round(1 - len(bb) / 1250, 4), "source": B,
                                     "method": "share of the 1,250 VMs dropped as ~0% CPU (zombie-like)", "n_series": 1250}
    P["disk_base_over_k"] = entry(col(act, "disk_base_over_k"), A_, "OLS (read+write) = c0 + c1*cpu%; c0/c1")
    P["iops_lognorm_sigma"] = entry(col(act, "disk_lognorm_sigma"), A_, "std of log(actual / OLS fit), disk throughput")
    if col(al, "iops_k"):
        P["iops_k_alibaba"] = entry(col(al, "iops_k"), L, "per-machine OLS slope of disk_io% on cpu%")
        P["iops_base_alibaba"] = entry(col(al, "iops_base"), L, "per-machine OLS intercept of disk_io% on cpu%")
    P["spike_rate_per_day"] = entry(col(az, "spikes_per_day"), A, "excursions above p50 + 4*MAD per day")
    P["spike_height_ratio"] = entry(col(az, "spike_height_ratio"), A, "median spike peak / series median")
    P["mem_noise_sd_pct"] = entry(col(al, "mem_noise_sd_pct"), L, "std of mem% residual after OLS on cpu% (percentage points)")
    P["spike_len_slots"] = entry(col(az, "spike_len_slots"), A, "median spike length in 5-min slots")
    P["missing_share_bitbrains"] = entry(col(bb, "nan_share"), B, "NaN share per VM in the mirror")
    P["missing_share_alibaba"] = entry(col(al, "nan_share"), L, "NaN share per machine in the mirror")

    # archetype ranges from real VMs classified with the same rules on Bitbrains + Azure
    pool = bb + az
    arch = {}
    for name in ("right_sized_prod", "steady_low", "bursty_daily", "batch_nightly", "office_hours_dev", "zombie"):
        members = [f for f in pool if classify(f) == name]
        arch[name] = {"n_series": len(members), "source": f"{B} + {A}",
                      "usable": len(members) >= 30}
        if members:
            for k in ("mean", "trough", "peak", "p95", "p99", "amp_ratio", "weekend_factor", "phi",
                      "spikes_per_day", "spike_excess_mad", "drift_sd"):
                v = col(members, k)
                if v:
                    arch[name][k] = {q: round(float(np.percentile(v, int(q[1:]))), 4)
                                     for q in ("p10", "p25", "p50", "p75", "p90")}
                    arch[name][k]["n"] = len(v)
            if len(members) >= 30:
                # empirical parameter tuples of real VMs, resampled by the generator (keeps correlations)
                keys = ("trough", "peak", "mean", "p95", "sigma", "weekend_factor", "drift_sd")
                arch[name]["samples"] = [{k: (round(float(m[k]), 4) if np.isfinite(m[k]) else None) for k in keys}
                                         for m in members]
    arch["memory_bound"] = {"n_series": 0, "source": L, "usable": False,
                            "note": "Alibaba mem% is relative to the container limit (median ~96%), not VM RAM; "
                                    "no public VM trace here has memory % -> memory_bound level stays an assumption"}
    P["archetypes"] = arch

    # calibration targets measured on the real traces
    vm_pool = bb + az
    P["calibration"] = {
        "share_mean_cpu_below_20": {"bitbrains": round(float(np.mean([f["mean"] < 20 for f in bb])), 4),
                                    "azure": round(float(np.mean([f["mean"] < 20 for f in az])), 4)},
        "median_p95_over_mean": {"bitbrains": round(float(np.median([f["p95"] / max(f["mean"], 0.5) for f in bb])), 4),
                                 "azure": round(float(np.median([f["p95"] / max(f["mean"], 0.5) for f in az])), 4)},
        "median_cpu_p95": {"bitbrains": round(float(np.median(col(bb, "p95"))), 4),
                           "azure": round(float(np.median(col(az, "p95"))), 4)},
        "median_cpu_cv": {"bitbrains": round(float(np.median(col(bb, "cv"))), 4),
                          "alibaba": round(float(np.median(col(al, "cpu_cv"))), 4),
                          "borg": round(float(np.median(col(bo, "cpu_cv"))), 4) if bo else None},
        "median_mem_cv": {"bitbrains": round(float(np.median(col(bb, "mem_cv"))), 4),
                          "alibaba": round(float(np.median(col(al, "mem_cv"))), 4),
                          "borg": round(float(np.median(col(bo, "mem_cv"))), 4) if bo else None},
        "n": {"bitbrains": len(bb), "azure": len(az), "alibaba": len(al), "borg": len(bo)},
    }
    # reference distribution for the KS check (p95/mean of real VMs that classify into our archetypes)
    P["reference_p95_over_mean"] = {name: sorted(round(f["p95"] / max(f["mean"], 0.5), 4)
                                                 for f in vm_pool if classify(f) == name)
                                    for name in arch if name != "memory_bound"}
    manifest = json.loads((EXTERNAL / "MANIFEST.json").read_text())
    P["_provenance"] = {k: {"sha256": v["sha256"], "url": v["url"]} for k, v in manifest.items()}
    P["_seed"] = SEED

    text = json.dumps(P, indent=1, sort_keys=True)
    OUT.write_text(text)
    print("wrote", OUT.name, "sha256", hashlib.sha256(text.encode()).hexdigest()[:16])
    for k, v in P.items():
        if isinstance(v, dict) and "p25" in v:
            print(f"{k:32s} {v['value']:>12.4f}  IQR [{v['p25']:.4f}, {v['p75']:.4f}]  n={v['n_series']}")
    print("archetype n:", {k: v["n_series"] for k, v in arch.items()})
    print("calibration:", json.dumps(P["calibration"]))


if __name__ == "__main__":
    main()
