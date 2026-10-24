"""Measurements computed once per VM from the cleaned arrays (the 'evidence board').
Components decide; this module only measures. Every number comes from the config."""
import numpy as np
import pandas as pd
from scipy import stats as sstats

from common.stats import lag1  # noqa: F401  (shared maths with the generator/fitter)


def pct(x, q):
    x = x[np.isfinite(x)]
    return float(np.percentile(x, q)) if len(x) else np.nan


def nanmean(x):
    x = x[np.isfinite(x)]
    return float(x.mean()) if len(x) else np.nan


def by_day(x, cfg):
    return x.reshape(-1, cfg.t("slots_per_day"))


def daily_peaks(x, cfg):
    """Per-day maximum of the 30-minute rolling mean (NaN-safe: a window needs all its samples)."""
    w = int(cfg("peaks.rolling_slots"))
    roll = pd.Series(x).rolling(w, min_periods=w).mean().to_numpy()
    d = by_day(roll, cfg)
    with np.errstate(all="ignore"):
        out = np.array([np.nanmax(r) if np.isfinite(r).any() else np.nan for r in d])
    return out


def kth_largest(v, k):
    v = np.sort(v[np.isfinite(v)])[::-1]
    return float(v[k - 1]) if len(v) >= k else (float(v[-1]) if len(v) else np.nan)


def trend(x, cfg):
    """Linear trend of daily p95 CPU: slope (points/day), p-value, last fitted value."""
    d = by_day(x, cfg)
    days, p95 = [], []
    for i, r in enumerate(d):
        if np.isfinite(r).sum() > 0:
            days.append(i)
            p95.append(np.percentile(r[np.isfinite(r)], cfg("evidence.trend_percentile")))
    if len(days) < cfg("gates_data.min_history_days"):
        return {"slope": 0, "p": 1, "last": np.nan}
    res = sstats.linregress(days, p95)
    last = res.intercept + res.slope * days[-1]
    return {"slope": float(res.slope), "p": float(res.pvalue), "last": float(last)}


def days_to(tr, level):
    if tr["slope"] <= 0 or not np.isfinite(tr["last"]):
        return np.inf
    return max((level - tr["last"]) / tr["slope"], 0.0)


def measure(arr, ctx, inv):
    cfg = ctx.cfg
    ax = ctx.axes
    cpu, mem = arr["cpu_pct"], arr["mem_pct"]
    n = len(cpu)
    spd = cfg.t("slots_per_day")
    obs = np.isfinite(cpu)
    day_cov = by_day(obs.astype(float), cfg).mean(axis=1)
    ev = {"n_slots": n, "coverage": float(obs.mean()),
          "days_of_data": int((day_cov >= cfg("gates_data.day_min_coverage")).sum()),
          "mean": nanmean(cpu), "mem_mean": nanmean(mem)}
    for q in list(cfg("evidence.report_percentiles")) + [cfg("percentiles.prod"), cfg("percentiles.nonprod")]:
        ev[f"p{q}"] = pct(cpu, q)
        ev[f"mem_p{q}"] = pct(mem, q)
    ev["max"] = float(np.nanmax(cpu)) if obs.any() else np.nan
    ev["mem_max"] = float(np.nanmax(mem)) if np.isfinite(mem).any() else np.nan
    ev["mem_std"] = float(np.nanstd(mem)) if np.isfinite(mem).any() else np.nan

    prov = float(inv.get("provisioned_iops") or 0) or np.nan
    bw = float(inv.get("bandwidth_mbps") or 0) or np.nan
    net = np.fmax(arr["net_in_mbps"], arr["net_out_mbps"])
    q = cfg("evidence.io_net_percentile")
    ev["iops_pct_p95"] = pct(arr["iops"] / prov * 100, q)
    ev["net_pct_p95"] = pct(net / bw * 100, q)
    ev["net_mb_per_h"] = nanmean(arr["net_in_mbps"] + arr["net_out_mbps"]) * cfg.t("mbps_to_mb_per_hour")
    ev["net_pct_mean"] = nanmean((arr["net_in_mbps"] + arr["net_out_mbps"]) / bw * 100)
    ev["iops_p95"] = pct(arr["iops"], q)

    # daily-peak profile
    ev["daily_peaks"] = daily_peaks(cpu, cfg)
    ev["mem_daily_peaks"] = daily_peaks(mem, cfg)
    ev["peak_days"] = int(np.nansum(ev["daily_peaks"] > cfg("peaks.peak_level")))
    ev["top_day_peak"] = kth_largest(ev["daily_peaks"], 1)
    ev["second_day_peak"] = kth_largest(ev["daily_peaks"], int(cfg("sizing.second_peak_rank")))
    dp = ev["daily_peaks"]
    top_day = int(np.nanargmax(dp)) if np.isfinite(dp).any() else -1
    rest = cpu.copy()
    if top_day >= 0:
        rest[top_day * spd:(top_day + 1) * spd] = np.nan
    ev["p99_excl_top_day"] = pct(rest, cfg("percentiles.prod"))
    ev["top_day"] = top_day

    # periodicity (candidate c of peaks)
    filled = np.where(obs, cpu, ev["mean"] if np.isfinite(ev["mean"]) else 0)
    ev["acf_day"] = _acf(filled, spd)
    ev["acf_week"] = _acf(filled, spd * cfg.t("days_per_week"))

    # trend, shifts, memory shape
    ev["trend"] = trend(cpu, cfg)
    recent = int(cfg("gates_data.anomaly_recent_hours") * cfg.t("slots_per_hour"))
    ev["shift_up"] = _ratio(nanmean(cpu[-recent:]), nanmean(cpu[:-recent]))
    qd = int(cfg("patterns.quiet_recent_days") * spd)
    ev["quiet_ratio"] = _ratio(nanmean(cpu[-qd:]), nanmean(cpu[:-qd]))
    ev["prior_mean"] = nanmean(cpu[:-qd])
    fm = mem[np.isfinite(mem)]
    ev["leak_resets"] = int((np.diff(fm) < -cfg("vetoes.leak_drop")).sum()) if len(fm) > 1 else 0

    # coverage of the busiest hours, and of every hour-of-week bucket
    hp = np.array([pct(cpu[ax["hour"][:n] == h], q) for h in range(cfg.t("hours_per_day"))])
    top = np.argsort(np.nan_to_num(hp, nan=-1))[::-1][:int(cfg("gates_data.peak_hours_top"))]
    in_top = np.isin(ax["hour"][:n], top)
    ev["peak_hours"] = sorted(int(h) for h in top)
    ev["peak_hours_coverage"] = float(obs[in_top].mean()) if in_top.any() else np.nan
    bucket = ax["dow"][:n] * cfg.t("hours_per_day") + ax["hour"][:n]
    cov_b = pd.Series(obs).groupby(bucket).mean()
    ev["min_bucket_coverage"] = float(cov_b.min())

    # off-hours map: hour-of-week h is 'off' if CPU p95 < offhour_cpu in EVERY observed week
    week = ax["day"][:n] // cfg.t("days_per_week")
    df = pd.DataFrame({"b": bucket, "w": week, "x": cpu})
    p = df.dropna().groupby(["b", "w"])["x"].quantile(cfg("candidates.offhour_percentile") / 100).unstack()
    off = (p < cfg("candidates.offhour_cpu")).where(p.notna()).all(axis=1) & p.notna().any(axis=1)
    ev["off_hours"] = np.array([bool(off.get(b, False)) for b in range(cfg.t("hours_per_week"))])
    return ev


def hour_of_week(ctx, n):
    ax = ctx.axes
    return ax["dow"][:n] * ctx.cfg.t("hours_per_day") + ax["hour"][:n]


def _acf(x, lag):
    if len(x) <= lag:
        return np.nan
    a, b = x[:-lag], x[lag:]
    if np.std(a) == 0 or np.std(b) == 0:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def _ratio(a, b):
    if not np.isfinite(a) or not np.isfinite(b) or b <= 0:
        return np.nan
    return a / b
