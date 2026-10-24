"""Per-resource features (PLAN_final.md B4 / plan section 6). Units are fixed here:
cpu/mem/disk in %, iops_pct = iops / provisioned_iops x 100, net_pct = max(in, out) / bandwidth x 100.
"""
import numpy as np
import pandas as pd

PCTS = {"p50": 50, "p90": 90, "p95": 95, "p99": 99, "p99_5": 99.5}
SLOTS_PER_DAY = 288


def _f(x):
    x = float(x)
    return None if np.isnan(x) else x


def pct_summary(arr):
    """p50..p99.5 and max with linear interpolation over non-NaN values; all None when empty."""
    v = arr[~np.isnan(arr)]
    if not len(v):
        return {**{k: None for k in PCTS}, "max": None}
    out = {k: float(np.percentile(v, p)) for k, p in PCTS.items()}
    out["max"] = float(v.max())
    return out


def _nanmean(arr):
    return _f(np.nanmean(arr)) if np.any(~np.isnan(arr)) else None


def grouped_quantile(arr, key, q, n_keys):
    """Quantile (linear) of non-NaN values per integer key 0..n_keys-1; NaN where a key has no data."""
    out = np.full(n_keys, np.nan)
    ok = ~np.isnan(arr)
    if ok.any():
        g = pd.Series(arr[ok]).groupby(key[ok]).quantile(q)
        out[g.index.to_numpy()] = g.to_numpy()
    return out


def daily_p95(arr, day, n_days):
    return grouped_quantile(arr, day, 0.95, n_days)


def r_squared(x, y, slope, icpt):
    resid = y - (slope * x + icpt)
    total = ((y - y.mean()) ** 2).sum()
    return float(1 - (resid ** 2).sum() / total) if total > 0 else 0.0


def trend(daily, limits=(85, 90)):
    """Least-squares slope (points/day) over days with data; days to each limit from the last fitted value."""
    x = np.flatnonzero(~np.isnan(daily))
    if len(x) < 2:
        return {"slope": None, "r2": None, **{f"days_to_{l}": None for l in limits}, "fit_days": int(len(x))}
    slope, icpt = np.polyfit(x, daily[x], 1)
    last = slope * x[-1] + icpt
    out = {"slope": float(slope), "r2": r_squared(x, daily[x], slope, icpt), "fit_days": int(len(x))}
    for l in limits:
        out[f"days_to_{l}"] = float(max(0.0, (l - last) / slope)) if slope > 0 else None
    return out


def leak_score(mem, drop, cpu=None, cpu_drop=None):
    """Drops of more than `drop` points between consecutive valid samples (generator/validate.py A11).
    With `cpu`, a memory drop that coincides with a CPU drop of more than `cpu_drop` points (a batch job
    ending) is not a leak reset (B9a.3)."""
    ok = ~np.isnan(mem) if cpu is None else ~np.isnan(mem) & ~np.isnan(cpu)
    v = mem[ok]
    if len(v) < 2:
        return 0
    resets = np.diff(v) < -drop
    if cpu is not None:
        resets &= ~(np.diff(cpu[ok]) < -cpu_drop)
    return int(resets.sum())


def rolling30(cpu):
    return pd.Series(cpu).rolling(6, min_periods=6).mean().to_numpy()


def recurring_peak_days(cpu, day, n_days, level):
    hit = rolling30(cpu) > level
    return int(len(np.unique(day[hit]))) if hit.any() else 0


def recurring_peak(cpu, grid, level, min_weeks):
    """IST hour-of-week buckets whose 30-minute rolling mean CPU exceeds `level` in >= min_weeks
    different weeks: a scheduled peak (nightly batch, Sunday billing), not a random burst."""
    hit = rolling30(cpu) > level
    if not hit.any():
        return None
    week = np.arange(grid.slots) // (7 * SLOTS_PER_DAY)
    how = grid.hour_of_week[hit]
    pairs = np.unique(np.stack([how, week[hit]]), axis=1)
    counts = np.bincount(pairs[0], minlength=168)
    buckets = np.flatnonzero(counts >= min_weeks)
    if not len(buckets):
        return None
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {"level_pct": level, "min_weeks": min_weeks, "buckets": [int(b) for b in buckets],
            "labels": [f"{names[b // 24]} {b % 24:02d}:00" for b in buckets],
            "weeks": int(counts[buckets].max()), "days": int(len(np.unique(grid.day[hit])))}


def peak_hours_coverage(cpu, exists, grid, level):
    """Coverage of the IST hours of day whose p95 CPU >= level (the workload's peak window);
    None when the resource has no such hours. A gap that lands on the peak is what matters (E9)."""
    hour = grid.ts_local.hour.to_numpy()
    p95 = grouped_quantile(cpu, hour, 0.95, 24)
    peak = np.flatnonzero(p95 >= level)
    if not len(peak):
        return None
    in_peak = np.isin(hour, peak) & exists
    return float((~np.isnan(cpu[in_peak])).sum() / in_peak.sum())


def p99_excl_top_day(cpu, day, n_days):
    daily_p99 = grouped_quantile(cpu, day, 0.99, n_days)
    if np.all(np.isnan(daily_p99)):
        return None, None
    top = int(np.nanargmax(daily_p99))
    rest = cpu[day != top]
    rest = rest[~np.isnan(rest)]
    return (float(np.percentile(rest, 99)) if len(rest) else None), top


def ratio(a, b):
    return None if a is None or b is None or b == 0 else a / b


def how_profile(cpu, grid):
    """168-cell p95 CPU profile overall and per week (week = 7-day block from the window start)."""
    how = grid.hour_of_week
    week = np.arange(grid.slots) // (7 * SLOTS_PER_DAY)
    n_weeks = int(week.max()) + 1
    overall = grouped_quantile(cpu, how, 0.95, 168)
    by_week = grouped_quantile(cpu, week * 168 + how, 0.95, n_weeks * 168).reshape(n_weeks, 168)
    return [_f(x) for x in overall], [[_f(x) for x in row] for row in by_week]


def vm_features(s, inv_row, grid, cfg):
    v = s.values
    day = grid.day
    n_days = int(day.max()) + 1
    cpu, mem = v["cpu_pct"], v["mem_pct"]
    prov = inv_row["provisioned_iops"]
    bw = inv_row["bandwidth_mbps"]
    iops_pct = v["iops"] / prov * 100 if prov and prov > 0 else np.full(grid.slots, np.nan)
    net_pct = np.fmax(v["net_in_mbps"], v["net_out_mbps"]) / bw * 100 if bw and bw > 0 else np.full(grid.slots, np.nan)
    net_total = v["net_in_mbps"] + v["net_out_mbps"]

    daily = {k: daily_p95(v[c], day, n_days)
             for k, c in (("cpu", "cpu_pct"), ("mem", "mem_pct"), ("disk_used", "disk_used_pct"))}
    last48 = slice(grid.slots - 2 * SLOTS_PER_DAY, grid.slots)
    last7 = slice(grid.slots - 7 * SLOTS_PER_DAY, grid.slots)
    excl, top_day = p99_excl_top_day(cpu, day, n_days)
    overall, by_week = how_profile(cpu, grid)
    valid_cpu = cpu[~np.isnan(cpu)]

    return {
        "resource_id": s.resource_id,
        "kind": "vm",
        "metrics": {"cpu": pct_summary(cpu), "mem": pct_summary(mem), "iops_pct": pct_summary(iops_pct),
                    "net_pct": pct_summary(net_pct), "disk_used": pct_summary(v["disk_used_pct"])},
        "mean_cpu": _nanmean(cpu),
        "mean_mem": _nanmean(mem),
        "mem_flatness": _f(np.nanstd(mem)) if np.any(~np.isnan(mem)) else None,
        "net_total_mean_mbps": _nanmean(net_total),
        "net_pct_mean": _nanmean(net_total / bw * 100) if bw and bw > 0 else None,
        "share_cpu_above_90": float((valid_cpu > 90).mean()) if len(valid_cpu) else None,
        "recurring_peak_days": recurring_peak_days(cpu, day, n_days, cfg.get("thresholds.recurring_peak_pct")),
        "p99_excl_top_day": excl,
        "top_day": top_day,
        "trend": {k: trend(d) for k, d in daily.items()},
        "daily_p95": {k: [_f(x) for x in d] for k, d in daily.items()},
        "level_shift_up": ratio(_nanmean(cpu[last48]), _nanmean(cpu[: last48.start])),
        "level_shift_down": ratio(_nanmean(cpu[last7]), _nanmean(cpu[: last7.start])),
        "leak_score": leak_score(mem, cfg.get("thresholds.leak_drop_pct_points"), cpu,
                                 cfg.get("thresholds.leak_cpu_drop_pct_points")),
        "recurring_peak": recurring_peak(cpu, grid, cfg.get("thresholds.recurring_peak_pct"),
                                         int(cfg.get("thresholds.recurring_peak_min_weeks"))),
        "peak_hours_coverage": peak_hours_coverage(cpu, s.exists, grid, cfg.get("thresholds.peak_hour_p95_pct")),
        "mem_std": _f(np.nanstd(mem)) if np.any(~np.isnan(mem)) else None,
        "how_p95": overall,
        "how_p95_by_week": by_week,
        **_coverage(s, day),
    }


def volume_features(s, inv_row, grid, cfg):
    v = s.values
    day = grid.day
    n_days = int(day.max()) + 1
    prov = inv_row["provisioned_iops"]
    iops_pct = v["iops"] / prov * 100 if prov and prov > 0 else np.full(grid.slots, np.nan)
    daily = daily_p95(v["disk_used_pct"], day, n_days)
    return {
        "resource_id": s.resource_id,
        "kind": "volume",
        "metrics": {"cpu": pct_summary(np.full(1, np.nan)), "mem": pct_summary(np.full(1, np.nan)),
                    "iops_pct": pct_summary(iops_pct), "net_pct": pct_summary(np.full(1, np.nan)),
                    "disk_used": pct_summary(v["disk_used_pct"])},
        "iops_p95": pct_summary(v["iops"])["p95"],
        "trend": {"disk_used": trend(daily)},
        "daily_p95": {"disk_used": [_f(x) for x in daily]},
        **_coverage(s, day),
    }


def _coverage(s, day):
    valid = ~np.isnan(s.primary) & s.exists
    return {"days_of_data": int(len(np.unique(day[valid]))),
            "coverage": s.report["coverage"],
            "peak_window_coverage": s.report["peak_window_coverage"]}


def empty_features(resource_id, kind):
    """Resources without telemetry (IPs, no-metric VMs): B6 defaults."""
    none = pct_summary(np.full(1, np.nan))
    return {"resource_id": resource_id, "kind": kind,
            "metrics": {k: dict(none) for k in ("cpu", "mem", "iops_pct", "net_pct", "disk_used")},
            "days_of_data": 0, "coverage": 0.0, "peak_window_coverage": 0.0}


def compute_features(cleaned, ds, cfg):
    inv = ds.inventory.set_index("resource_id")
    out = {}
    for rid, row in inv.iterrows():
        s = cleaned.series.get(rid)
        if s is None:
            out[rid] = empty_features(rid, row["type"])
        elif s.kind == "vm":
            out[rid] = vm_features(s, row, cleaned.grid, cfg)
        else:
            out[rid] = volume_features(s, row, cleaned.grid, cfg)
    return out
