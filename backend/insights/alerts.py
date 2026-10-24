"""Alerts G1, G3, G4, G5, G6, G7, G9, G10, D9 with G11 de-duplication (PLAN_final.md B5).

Detection rules are ours; type words, `evidence.metric`, wording and windows follow the frontend's vocabulary
(PLAN_frontend_integration.md §4 E7: Alerts.tsx charts `evidence.metric` from METRIC_SERIES). One alert per
(resource, type); team alerts have resource_id null. Hour-of-week and days are IST.
"""
import numpy as np
import pandas as pd

from ..cost.model import format_inr
from ..pipeline.features import r_squared
from .growth import first_billed

SLOTS_PER_DAY = 288
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _r(x, n=1):
    return None if x is None else round(float(x), n)


def _alert(type_, key, rid, name, severity, title, why, metric, value, threshold, window, first_seen, suggested,
           occurrences=1):
    """window: (start ISO, end ISO) or None."""
    win = {"start": window[0], "end": window[1]} if window else None
    return {"alert_id": f"ALR-{type_}-{key}", "type": type_, "severity": severity, "resource_id": rid, "name": name,
            "title": title, "why": why,
            "evidence": {"metric": metric, "value": value, "threshold": threshold, "window": win},
            "window": win, "first_seen": first_seen, "occurrences": int(occurrences), "suggested_action": suggested}


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
        return self.grid.ts_local[int(min(max(slot, 0), self.grid.slots - 1))].isoformat()

    def end_ts(self):
        return (self.grid.ts_local[-1] + pd.Timedelta(minutes=5)).isoformat()

    def day(self, d):
        return (self.grid.start + pd.Timedelta(days=int(d))).strftime("%Y-%m-%d")

    @property
    def window(self):
        return (self.ts(0), self.end_ts())

    def is_prod(self, rid):
        return self.inv.loc[rid, "env"] == "prod"

    def name(self, rid):
        return self.inv.loc[rid, "name"]

    def vms(self):
        return [(rid, s) for rid, s in self.cleaned.series.items() if s.kind == "vm"]


def _vm(ctx, type_, rid, *args, **kw):
    return _alert(type_, rid, rid, ctx.name(rid), *args, **kw)


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
        a, b = max(runs, key=lambda r: np.nanmax(cpu[r[0]:r[1]]))
        peak_slot = a + int(np.nanargmax(cpu[a:b]))
        peak, base = float(cpu[peak_slot]), float(thresh[peak_slot])
        held = float(np.nanmean(cpu[a:b]))
        out.append(_vm(
            ctx, "spike", rid, "warning", "Unusual spike vs the same hours in other weeks",
            f"CPU held {held:.0f}% for {(b - a) * 5 / 60:.1f} h on {ctx.grid.ts_local[a]:%d %b} (peak {peak:.0f}%); "
            f"the same hours in other weeks stay under {base:.0f}% (median + {k}×MAD).",
            "cpu_pct", _r(peak), f"median + {k}×MAD", (ctx.ts(a), ctx.ts(b)), ctx.ts(runs[0][0]),
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
        out.append(_vm(
            ctx, "level_shift", rid, "critical" if ctx.is_prod(rid) else "warning",
            f"Level shift: CPU {r:.0f}× its normal level for 48 h",
            f"Mean CPU over the last 48 h is {r:.1f}× the prior 28 days. Excluded from sizing until understood.",
            "cpu_pct", _r(r, 2), lim, (ctx.ts(start), ctx.end_ts()), ctx.ts(start),
            "Check recent deploys and queue depth with the owning team."))
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
            # the surge window: from the first day whose mean CPU exceeds the limit, to the end
            hot_days = [d for d in range(last + 1) if np.nanmean(cpu[day == d]) > cpu_lim]
            start = int(np.flatnonzero(day == hot_days[0])[0]) if hot_days else int(np.flatnonzero(in_last)[0])
            env = ctx.inv.loc[rid, "env"] or "untagged"
            out.append(_vm(
                ctx, "possible_compromise", rid, "critical", "Possible compromise: CPU pinned + outbound traffic surge",
                f"CPU averages {cpu24:.0f}% over the last 24 h, and network out is {ratio:.0f}× its normal level "
                f"({net24:.1f} vs {base:.1f} Mbps). Miner-like pattern on a {env} VM.",
                "net_out_mbps", _r(ratio, 1), net_lim, (ctx.ts(start), ctx.end_ts()), ctx.ts(start),
                "Isolate the VM, rotate its credentials and inspect running processes."))
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
        eta_date = ctx.grid.start + pd.Timedelta(days=ctx.grid.slots // SLOTS_PER_DAY) + pd.Timedelta(days=eta)
        sev = "critical" if eta < crit else "warning"
        win = (ctx.ts(0), ctx.end_ts())
        first = f"{ctx.day(30 - fit_days)}T00:00:00+05:30"
        if metric == "cpu":
            out.append(_vm(
                ctx, "capacity", rid, sev, f"CPU capacity: about {eta:.0f} days to 90%",
                f"Daily CPU p95 is rising {slope:.2f} points/day (now {last:.0f}%). At this rate it reaches 90% "
                f"around {eta_date:%d %b}.",
                "cpu_p95_slope", _r(slope, 2), "days to 90% < 30", win, first, "Plan an upsize or scale-out before the ETA."))
        else:
            kind = "Volume filling" if ctx.inv.loc[rid, "type"] == "volume" else "Disk filling"
            out.append(_vm(
                ctx, "capacity", rid, sev, f"{kind}: about {eta:.0f} days to 90%",
                f"Disk used is rising {slope:.1f} points/day (now {last:.0f}%). At this rate it reaches 90% around "
                f"{eta_date:%d %b}." + (" Do not shrink it." if kind == "Volume filling" else ""),
                "disk_used_pct", _r(slope, 2), "days to 90% < 30", win, first,
                "Extend before the ETA; cancel any shrink." if kind == "Volume filling"
                else "Extend the volume or clean up logs before the ETA."))
    return out


# ---- G6 leak, G9 under-provisioned, G10 monitoring missing, D9 orphan series -------------------

def g6_leak(ctx):
    lim = ctx.a("g6_leak_cycles")
    out = []
    for rid, s in ctx.vms():
        n = ctx.features[rid].get("leak_score", 0)
        if n >= lim:
            lo, hi = ctx.features[rid]["metrics"]["mem"]["p50"], ctx.features[rid]["metrics"]["mem"]["max"]
            out.append(_vm(
                ctx, "memory_leak", rid, "warning", "Memory leak suspected (sawtooth)",
                f"Memory climbs from about {lo:.0f}% to {hi:.0f}% and resets {n} times in 30 days: a restart is "
                f"hiding a leak.",
                "mem_pct", n, "≥ 3 cycles", ctx.window, ctx.ts(0), "Capture a heap dump before the next restart."))
    return out


def g9_under_provisioned(ctx):
    lim = ctx.a("g9_share_above_90")
    out = []
    for rid, s in ctx.vms():
        share = ctx.features[rid].get("share_cpu_above_90")
        if share is not None and share >= lim:
            m = ctx.features[rid]["metrics"]["cpu"]
            out.append(_vm(
                ctx, "under_provisioned", rid, "warning", f"Under-provisioned: CPU p99 at {m['p99']:.0f}%",
                f"CPU p99 is {m['p99']:.0f}% and p95 {m['p95']:.0f}%; {share:.0%} of samples are above 90%: "
                f"requests are queueing at peak.",
                "cpu_p99", _r(m["p99"]), 90, ctx.window, ctx.ts(0), "Accept the upsize recommendation."))
    return out


def g10_monitoring_missing(ctx):
    out = []
    for rid in ctx.cleaned.no_metrics:
        if ctx.inv.loc[rid, "state"] != "running":
            continue
        env = ctx.inv.loc[rid, "env"] or "untagged"
        out.append(_vm(
            ctx, "monitoring_missing", rid, "warning", "Monitoring missing",
            f"{env.capitalize()} VM with no metrics at all for 30 days: we can't tell whether it's safe.",
            "rows", 0, "> 0", None, ctx.ts(0), "Install the monitoring agent."))
    return out


def d9_orphan_series(ctx):
    out = []
    for rid in ctx.cleaned.strays:
        s = ctx.cleaned.stray_series.get(rid)
        rows = int((~np.isnan(s.primary)).sum()) if s is not None else 0
        out.append(_alert(
            "orphan_series", rid, rid, rid, "info", "Metrics for a machine not in the inventory",
            f"{rid} reports metrics but has no inventory row: possibly an unbilled or untracked machine.",
            "rows", rows, "inventory row", None, ctx.ts(0), "Find the owner and add it to the inventory, or shut it down."))
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
                hits.append((d, daily.loc[d, team], prev7[d], new))
        if not hits:
            continue
        d, cost, avg, new = hits[0]
        listed = ", ".join(sorted(names[x] for x in new))
        out.append(_alert(
            "team_cost_jump", f"team-{team}", None, f"team {team}", "warning",
            f"Team cost jump: {team} +{(cost / avg - 1) * 100:.0f}% in a day",
            f"{team} spent {format_inr(cost)} on {d:%d %b} vs a 7-day average of {format_inr(avg)}. "
            f"New resources: {listed}.",
            "team_daily_cost", int(round(cost)), f"{lim} × 7-day avg", None, f"{d:%Y-%m-%d}T00:00:00+05:30",
            "Confirm the new resources were planned.", occurrences=len(hits)))
    return out


def compute_alerts(cleaned, features, ds, cfg):
    ctx = Ctx(cleaned, features, ds, cfg)
    g3, g4 = g3_level_shift(ctx), g4_compromise(ctx)
    step_change = {a["resource_id"] for a in g3 + g4}
    alerts = (g1_spikes(ctx) + g3 + g4 + g5_capacity(ctx, step_change) + g6_leak(ctx) + g7_team_jump(ctx)
              + g9_under_provisioned(ctx) + g10_monitoring_missing(ctx) + d9_orphan_series(ctx))
    unique = {}
    for a in alerts:                                    # G11: one alert per (resource, type)
        key = a["alert_id"]
        if key in unique:
            unique[key]["occurrences"] += a["occurrences"]
        else:
            unique[key] = a
    return sorted(unique.values(), key=lambda a: (SEVERITY_ORDER[a["severity"]], a["alert_id"]))
