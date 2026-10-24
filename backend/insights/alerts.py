"""MVP alerts G1, G3, G4, G5, G6, G7, G9, G10 with G11 de-duplication (PLAN_final.md B5).

One alert per (resource, type); team alerts use resource_id "team:<name>". Hour-of-week and days are IST.
"""
import numpy as np
import pandas as pd

from ..pipeline.features import r_squared
from .growth import first_billed

SLOTS_PER_DAY = 288
SEVERITY_ORDER = {"Critical": 0, "Warning": 1, "Info": 2}


def _r(x, n=1):
    return None if x is None else round(float(x), n)


def _alert(type_, rid, severity, title, why, metric, value, threshold, window, first_seen, suggested,
           occurrences=1):
    return {"alert_id": f"ALR-{type_}-{rid}", "type": type_, "severity": severity, "resource_id": rid,
            "title": title, "why": why,
            "evidence": {"metric": metric, "value": value, "threshold": threshold, "window": window},
            "first_seen": first_seen, "occurrences": int(occurrences), "suggested_action": suggested}


def _runs(mask, min_len):
    """(start, end) of True runs of at least min_len consecutive slots."""
    edges = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    keep = (ends - starts) >= min_len
    return list(zip(starts[keep], ends[keep]))


class Ctx:
    def __init__(self, cleaned, features, ds, cfg):
        self.cleaned, self.features, self.ds, self.cfg = cleaned, features, ds, cfg
        self.grid = cleaned.grid
        self.inv = ds.inventory.set_index("resource_id")
        self.a = lambda k: cfg.get(f"alerts.{k}")

    def ts(self, slot):
        return self.grid.ts_local[int(slot)].isoformat()

    def day(self, d):
        return (self.grid.start + pd.Timedelta(days=int(d))).strftime("%Y-%m-%d")

    @property
    def window(self):
        return f"{self.day(0)}/{self.day(self.grid.slots // SLOTS_PER_DAY - 1)}"

    def is_prod(self, rid):
        return self.inv.loc[rid, "env"] == "prod"

    def name(self, rid):
        return self.inv.loc[rid, "name"]

    def vms(self):
        return [(rid, s) for rid, s in self.cleaned.series.items() if s.kind == "vm"]


# ---- G1: spike vs the same IST hour-of-week in the other weeks -------------------------------

def g1_spikes(ctx):
    k, floor = ctx.a("g1_mad_k"), ctx.a("g1_min_points_above_median")
    min_len, min_weeks = int(ctx.a("g1_min_consecutive_samples")), int(ctx.a("g1_min_other_weeks"))
    how = ctx.grid.hour_of_week
    week = np.arange(ctx.grid.slots) // (7 * SLOTS_PER_DAY)
    n_weeks = int(week.max()) + 1
    out = []
    for rid, s in ctx.vms():
        cpu = s.values["cpu_pct"]
        thresh = np.full(ctx.grid.slots, np.nan)
        for h in range(168):
            in_h = how == h
            for w in range(n_weeks):
                cur = in_h & (week == w)
                if not cur.any():
                    continue
                other = in_h & (week != w)
                v = cpu[other]
                ok = ~np.isnan(v)
                if len(np.unique(week[other][ok])) < min_weeks:
                    continue
                v = v[ok]
                med = np.median(v)
                mad = np.median(np.abs(v - med))
                thresh[cur] = max(med + k * mad, med + floor)
        hit = cpu > thresh                                    # NaN compares False
        runs = _runs(hit, min_len)
        if not runs:
            continue
        peak_run = max(runs, key=lambda r: np.nanmax(cpu[r[0]:r[1]]))
        a, b = peak_run
        peak_slot = a + int(np.nanargmax(cpu[a:b]))
        peak, base = float(cpu[peak_slot]), float(thresh[peak_slot])
        out.append(_alert(
            "G1", rid, "Warning", f"CPU spike on {ctx.name(rid)}",
            f"CPU reached {peak:.1f}% at {ctx.ts(peak_slot)}, above the usual level for that hour of the week "
            f"(threshold {base:.1f}%: median + {k}×MAD of the other weeks), for {(b - a) * 5} minutes.",
            "cpu_pct", _r(peak), _r(base), f"{ctx.ts(a)}/{ctx.ts(b - 1)}", ctx.ts(runs[0][0]),
            "Check what ran at that time; if it is a new recurring job, no action.", occurrences=len(runs)))
    return out


# ---- G3 level shift, G4 possible compromise ---------------------------------------------------

def g3_level_shift(ctx):
    lim = ctx.a("g3_level_shift_ratio")
    start = ctx.grid.slots - 2 * SLOTS_PER_DAY
    out = []
    for rid, s in ctx.vms():
        r = ctx.features[rid].get("level_shift_up")
        if r is None or not r > lim:
            continue
        out.append(_alert(
            "G3", rid, "Critical" if ctx.is_prod(rid) else "Warning", f"Level shift on {ctx.name(rid)}",
            f"Mean CPU over the last 48 h is {r:.1f}× the mean of the prior 28 days (limit {lim}×).",
            "cpu_mean_last48h_over_prior", _r(r, 2), lim, f"{ctx.ts(start)}/{ctx.ts(ctx.grid.slots - 1)}",
            ctx.ts(start), "Investigate the change; sizing is paused until the level settles."))
    return out


def g4_compromise(ctx):
    cpu_lim, net_lim = ctx.a("g4_cpu_pct"), ctx.a("g4_net_out_ratio")
    day = ctx.grid.day
    last = int(day.max())
    out = []
    for rid, s in ctx.vms():
        cpu, net = s.values["cpu_pct"], s.values["net_out_mbps"]
        in_last = day == last
        if not np.any(~np.isnan(cpu[in_last])):
            continue
        cpu24 = float(np.nanmean(cpu[in_last]))
        net24 = float(np.nanmean(net[in_last])) if np.any(~np.isnan(net[in_last])) else np.nan
        prior = [np.nanmean(net[day == d]) for d in range(last - 28, last) if np.any(~np.isnan(net[day == d]))]
        if not prior or np.isnan(net24):
            continue
        base = float(np.median(prior))
        ratio = net24 / base if base > 0 else np.inf
        if cpu24 > cpu_lim and ratio >= net_lim:
            start = int(np.flatnonzero(in_last)[0])
            out.append(_alert(
                "G4", rid, "Critical", f"Possible compromise on {ctx.name(rid)}",
                f"CPU averaged {cpu24:.1f}% over the last 24 h and outbound network is {ratio:.1f}× its usual "
                f"daily level ({net24:.1f} vs {base:.1f} Mbps): a crypto-miner-like pattern.",
                "net_out_last24h_over_baseline", _r(ratio, 1), net_lim,
                f"{ctx.ts(start)}/{ctx.ts(ctx.grid.slots - 1)}", ctx.ts(start),
                "Isolate the VM and check running processes and credentials."))
    return out


# ---- G5 capacity trend -----------------------------------------------------------------------

def g5_capacity(ctx, skip):
    days_lim, crit = ctx.a("g5_days_to_90"), ctx.a("g5_critical_days")
    min_slope, fit_days, min_days = ctx.a("g5_min_slope"), int(ctx.a("g5_fit_days")), int(ctx.a("g5_min_days"))
    min_r2 = ctx.a("g5_min_r2")
    out = []
    for rid, f in ctx.features.items():
        if rid in skip or "daily_p95" not in f:
            continue
        best = None
        for metric, daily in f["daily_p95"].items():
            d = np.array([np.nan if x is None else x for x in daily])[-fit_days:]
            x = np.flatnonzero(~np.isnan(d))
            if len(x) < min_days:
                continue
            slope, icpt = np.polyfit(x, d[x], 1)
            if slope < min_slope or r_squared(x, d[x], slope, icpt) < min_r2:
                continue
            last = slope * x[-1] + icpt
            eta = max(0.0, (90 - last) / slope)
            if eta < days_lim and (best is None or eta < best[1]):
                best = (metric, eta, slope, last)
        if best is None:
            continue
        metric, eta, slope, last = best
        eta_date = (ctx.grid.start + pd.Timedelta(days=ctx.grid.slots // SLOTS_PER_DAY) + pd.Timedelta(days=eta))
        out.append(_alert(
            "G5", rid, "Critical" if eta < crit else "Warning", f"{metric} heading to 90% on {ctx.name(rid)}",
            f"Daily p95 {metric} is rising {slope:.2f} points/day over the last {fit_days} days and is at "
            f"{last:.1f}%; at this rate it reaches 90% in {eta:.0f} days (around {eta_date:%Y-%m-%d}).",
            f"{metric}_days_to_90", _r(eta), days_lim, f"{ctx.day(30 - fit_days)}/{ctx.day(29)}",
            f"{ctx.day(30 - fit_days)}T00:00:00+05:30", "Plan capacity before the ETA."))
    return out


# ---- G6 leak, G9 under-provisioned, G10 monitoring missing ------------------------------------

def g6_leak(ctx):
    lim = ctx.a("g6_leak_cycles")
    out = []
    for rid, s in ctx.vms():
        n = ctx.features[rid].get("leak_score", 0)
        if n >= lim:
            out.append(_alert(
                "G6", rid, "Warning", f"Memory leak suspected on {ctx.name(rid)}",
                f"Memory climbed and then dropped sharply {n} times in 30 days (sawtooth; limit {lim}).",
                "leak_score", n, lim, ctx.window, f"{ctx.day(0)}T00:00:00+05:30",
                "Check the service for a leak; restarts are hiding it."))
    return out


def g9_under_provisioned(ctx):
    lim = ctx.a("g9_share_above_90")
    out = []
    for rid, s in ctx.vms():
        share = ctx.features[rid].get("share_cpu_above_90")
        if share is not None and share >= lim:
            out.append(_alert(
                "G9", rid, "Warning", f"Under-provisioned: {ctx.name(rid)}",
                f"{share:.1%} of CPU samples are above 90% (limit {lim:.0%}); p99 is "
                f"{ctx.features[rid]['metrics']['cpu']['p99']:.1f}%.",
                "share_cpu_above_90", _r(share, 3), lim, ctx.window, f"{ctx.day(0)}T00:00:00+05:30",
                "Consider a larger plan."))
    return out


def g10_monitoring_missing(ctx):
    out = []
    for rid in ctx.cleaned.no_metrics:
        if ctx.inv.loc[rid, "state"] != "running":
            continue
        out.append(_alert(
            "G10", rid, "Warning", f"Monitoring missing on {ctx.name(rid)}",
            "The VM is running but sent no metrics in the 30-day window.",
            "metric_rows", 0, 1, ctx.window, f"{ctx.day(0)}T00:00:00+05:30",
            "Install or repair the monitoring agent."))
    return out


# ---- G7 team cost jump -------------------------------------------------------------------------

def g7_team_jump(ctx):
    lim = ctx.a("g7_jump_ratio")
    b = ctx.ds.billing.assign(team=ctx.ds.billing["team"].replace("", "unowned"))
    daily = b.groupby(["team", "date"])["cost_inr"].sum().unstack(0).sort_index().fillna(0.0)
    first = first_billed(b)
    team_of = b.drop_duplicates("resource_id").set_index("resource_id")["team"]
    names = b.drop_duplicates("resource_id").set_index("resource_id")["name"]
    start = pd.Timestamp(ctx.day(0))
    end = pd.Timestamp(ctx.day(ctx.grid.slots // SLOTS_PER_DAY - 1))
    out = []
    for team in daily.columns:
        prev7 = daily[team].shift(1).rolling(7, min_periods=7).mean()
        hits = []
        for d in daily.index[(daily.index >= start) & (daily.index <= end)]:
            new = [r for r, t in first.items() if t == d and team_of.get(r) == team]
            if new and prev7[d] > 0 and daily.loc[d, team] > lim * prev7[d]:
                hits.append((d, daily.loc[d, team] / prev7[d], new))
        if not hits:
            continue
        d, r, new = hits[0]
        listed = ", ".join(sorted(names[x] for x in new))
        out.append(_alert(
            "G7", f"team:{team}", "Warning", f"Cost jump for team {team}",
            f"Team {team}'s daily cost on {d:%Y-%m-%d} was ₹{daily.loc[d, team]:,.0f}, {r:.2f}× its previous "
            f"7-day mean, after new resources started billing: {listed}.",
            "team_daily_cost_over_prev7", _r(r, 3), lim, f"{d:%Y-%m-%d}", f"{d:%Y-%m-%d}T00:00:00+05:30",
            "Confirm the new resources are expected and owned.", occurrences=len(hits)))
    return out


def compute_alerts(cleaned, features, ds, cfg):
    ctx = Ctx(cleaned, features, ds, cfg)
    g3, g4 = g3_level_shift(ctx), g4_compromise(ctx)
    step_change = {a["resource_id"] for a in g3 + g4}
    alerts = (g1_spikes(ctx) + g3 + g4 + g5_capacity(ctx, step_change) + g6_leak(ctx) + g7_team_jump(ctx)
              + g9_under_provisioned(ctx) + g10_monitoring_missing(ctx))
    unique = {}
    for a in alerts:                                    # G11: one alert per (resource, type)
        key = (a["resource_id"], a["type"])
        if key in unique:
            unique[key]["occurrences"] += a["occurrences"]
        else:
            unique[key] = a
    return sorted(unique.values(), key=lambda a: (SEVERITY_ORDER[a["severity"]], a["first_seen"], a["alert_id"]))
