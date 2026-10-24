"""Alerts and insights (PLAN.md 10 / schema 'Alert'): every alert explains why it fired, with the number and the
threshold. Robust statistics only (median, MAD, least squares), so each alert is explainable in one line.

Types: level_shift, possible_compromise, usage_spike, capacity_trend (cpu / memory / disk / volume),
memory_leak, under_provisioned, monitoring_missing, cost_increase, budget_overrun.
python -m engine.alerts  ->  data/alerts.json"""
import json

import numpy as np
import pandas as pd
from scipy import stats as sstats

from . import data as D
from .evidence import hour_of_week

SEVERITY = ["critical", "warning", "info"]


def _ts(ctx, slot):
    return (ctx.data.window_start + pd.Timedelta(minutes=int(slot) * ctx.cfg.t("slot_minutes"))).isoformat()


def _alert(type_, severity, rid, title, why, metric, value, threshold, window, first_seen, occurrences, action):
    return {"alert_id": None, "type": type_, "severity": severity, "resource_id": rid, "title": title, "why": why,
            "evidence": {"metric": metric, "value": value, "threshold": threshold, "window": window},
            "first_seen": first_seen, "occurrences": occurrences, "suggested_action": action}


def _daily_trend(x, cfg, agg):
    """Least-squares line through the last `trend_lookback_days` daily values -> (slope/day, p, last fitted)."""
    spd = cfg.t("slots_per_day")
    d = x.reshape(-1, spd)
    look = int(cfg("alerts.trend_lookback_days"))
    days, vals = [], []
    for i, row in enumerate(d[-look:]):
        row = row[np.isfinite(row)]
        if len(row):
            days.append(i)
            vals.append(agg(row))
    if len(days) < cfg.t("days_per_week"):                    # need at least a week of the fortnight
        return None
    res = sstats.linregress(days, vals)
    return res.slope, res.pvalue, res.intercept + res.slope * days[-1]


def _capacity(ctx, rid, name, x, metric, agg, env):
    cfg = ctx.cfg
    tr = _daily_trend(x, cfg, agg)
    if not tr:
        return None
    slope, p, last = tr
    level = cfg("alerts.capacity_level")
    if slope <= 0 or p >= cfg("alerts.trend_pvalue"):
        return None
    days = max((level - last) / slope, 0)
    if days >= cfg("alerts.trend_days_warning"):
        return None
    sev = "critical" if days < cfg("alerts.trend_days_critical") else "warning"
    return _alert("capacity_trend", sev, rid, f"{name}: {metric} reaches {level:.0f}% in ~{days:.0f} days",
                  f"{metric} grows {slope:.2f} points/day over the last {int(cfg('alerts.trend_lookback_days'))} days "
                  f"(p = {p:.3f}); now {last:.0f}%, {level:.0f}% in about {days:.0f} days",
                  metric, round(days, 1), cfg("alerts.trend_days_warning"), f"last {int(cfg('alerts.trend_lookback_days'))} days",
                  ctx.now.isoformat(), 1, "plan an upsize / cleanup before it fills" if metric != "cpu" else "plan an upsize")


def _spikes(ctx, r):
    """Robust z of the 30-min rolling LOG-RATIO to the same hour-of-week median.
    - log-ratio, because real day-to-day variation is multiplicative (fitted lognormal drift): a uniformly busier
      day is normal spread, a burst far above its own hour is not;
    - rolling the deviation (not the raw value), so a window straddling an hour boundary never compares a peak
      hour with a quiet one;
    - median / MAD, so the spike cannot inflate its own baseline."""
    cfg = ctx.cfg
    x = r.arr["cpu_pct"]
    w = int(cfg("peaks.rolling_slots"))
    how = hour_of_week(ctx, len(x))
    df = pd.DataFrame({"h": how, "x": x})
    med = df.groupby("h")["x"].median()
    base = df["h"].map(med).to_numpy()
    lr = np.log((x + 1) / (base + 1))                         # +1 point keeps an idle hour (0%) finite
    mad = pd.Series(np.abs(lr)).groupby(how).median()
    sigma = pd.Series(how).map(mad).to_numpy() * cfg("alerts.mad_to_sigma")
    dev = pd.Series(lr).rolling(w, min_periods=w).mean().to_numpy()
    sig = pd.Series(sigma).rolling(w, min_periods=w).mean().to_numpy()
    roll = pd.Series(x).rolling(w, min_periods=w).mean().to_numpy()
    z = dev / np.where(sig > 0, sig, np.nan)
    hit = np.nan_to_num((z > cfg("alerts.spike_mad_k")) & (roll > cfg("alerts.spike_min_level")), nan=0).astype(bool)
    if not hit.any():
        return None
    starts = np.flatnonzero(np.diff(np.concatenate([[0], hit.astype(int)])) == 1)
    i = int(np.nanargmax(np.where(hit, z, -np.inf)))
    normal = pd.Series(base).rolling(w, min_periods=w).mean().to_numpy()[i]
    return _alert("usage_spike", "warning" if r.env == "prod" else "info", r.id,
                  f"{r.inv['name']}: CPU {roll[i]:.0f}% vs a normal {normal:.0f}% at this hour",
                  f"30-min CPU {roll[i]:.0f}% at {pd.Timestamp(_ts(ctx, i)):%Y-%m-%d %H:%M}; the same hours of the week normally run at "
                  f"{normal:.0f}% (median); {z[i]:.1f} robust sigmas above normal on a log scale (threshold "
                  f"{cfg('alerts.spike_mad_k'):.0f}, sigma = {cfg('alerts.mad_to_sigma')} x MAD)",
                  "robust_z_log_ratio", round(float(z[i]), 1), cfg("alerts.spike_mad_k"), "30-min rolling",
                  _ts(ctx, starts[0]), int(len(starts)), "check what ran at that time; not a sizing signal on its own")


def resource_alerts(ctx, res):
    cfg = ctx.cfg
    out = []
    for r in res:
        if r.inv is None:
            continue
        name = r.inv["name"]
        codes = {f["code"] for f in r.findings}
        if "NO_TELEMETRY" in codes:
            out.append(_alert("monitoring_missing", "warning", r.id, f"{name}: no metrics", "the VM is running but "
                              "no monitoring data arrived in the whole window", "samples", 0, 1, "window",
                              ctx.now.isoformat(), 1, "install / fix the monitoring agent"))
        if r.type == "volume" and r.vol is not None:
            a = _capacity(ctx, r.id, name, r.vol["disk_used_pct"], "volume used %", np.mean, r.env)
            if a:
                out.append(a)
        if r.type != "vm" or r.arr is None or r.ev is None or r.state == "stopped":
            continue
        ev = r.ev
        ratio = cfg("gates_data.anomaly_ratio")
        if ev["shift_up"] == ev["shift_up"] and ev["shift_up"] > ratio:
            recent = int(cfg("gates_data.anomaly_recent_hours") * cfg.t("slots_per_hour"))
            nout = r.arr["net_out_mbps"]
            prior = np.nanmean(nout[:-recent])
            net_ratio = np.nanmean(nout[-recent:]) / prior if prior > 0 else np.nan
            if net_ratio == net_ratio and net_ratio > ratio:
                out.append(_alert("possible_compromise", "critical", r.id, f"{name}: CPU and outbound traffic jumped together",
                                  f"last {cfg('gates_data.anomaly_recent_hours'):.0f} h: CPU {ev['shift_up']:.1f}x and "
                                  f"network out {net_ratio:.1f}x their earlier level (threshold {ratio:.0f}x); a sustained "
                                  "CPU + egress jump on a quiet VM is the signature of crypto-mining or exfiltration",
                                  "cpu_x / net_out_x", f"{ev['shift_up']:.1f} / {net_ratio:.1f}", ratio,
                                  f"last {cfg('gates_data.anomaly_recent_hours'):.0f} h", _ts(ctx, len(nout) - recent), 1,
                                  "isolate and inspect the VM now; rotate credentials"))
            else:
                out.append(_alert("level_shift", "critical" if r.env == "prod" else "warning", r.id,
                                  f"{name}: CPU {ev['shift_up']:.1f}x its normal level",
                                  f"last {cfg('gates_data.anomaly_recent_hours'):.0f} h mean CPU is {ev['shift_up']:.1f}x the "
                                  f"earlier mean (threshold {ratio:.0f}x); sizing is suspended until it settles",
                                  "cpu_x", round(ev["shift_up"], 2), ratio, f"last {cfg('gates_data.anomaly_recent_hours'):.0f} h",
                                  _ts(ctx, r.ev["n_slots"] - recent), 1, "find the cause (deploy? traffic? incident?)"))
        if ev["leak_resets"] >= cfg("vetoes.leak_min_resets"):
            out.append(_alert("memory_leak", "warning", r.id, f"{name}: memory leak suspected",
                              f"{ev['leak_resets']} sharp memory drops (> {cfg('vetoes.leak_drop'):.0f} points) in the window: "
                              "memory climbs and the process restarts", "memory resets", ev["leak_resets"],
                              cfg("vetoes.leak_min_resets"), "window", ctx.now.isoformat(), ev["leak_resets"],
                              "fix the leak; until then no sizing change is trustworthy"))
        if r.verdict == "upsize":
            out.append(_alert("under_provisioned", "critical" if r.env == "prod" else "warning", r.id,
                              f"{name}: saturated, upsize recommended", r.primary["message"] + f" ({r.primary['check']} "
                              f"{r.primary['value']} > {r.primary['threshold']})", "cpu_pct", r.primary["value"],
                              r.primary["threshold"], "window", ctx.now.isoformat(), 1, "apply the upsize recommendation"))
        for metric, x, agg in (("cpu", r.arr["cpu_pct"], lambda v: np.percentile(v, cfg("evidence.trend_percentile"))),
                               ("memory", r.arr["mem_pct"], lambda v: np.percentile(v, cfg("evidence.trend_percentile"))),
                               ("disk used %", r.arr["disk_used_pct"], np.mean)):
            if "ACTIVE_ANOMALY" in codes and metric == "cpu":
                continue
            a = _capacity(ctx, r.id, name, x, metric, agg, r.env)
            if a:
                out.append(a)
        if "ACTIVE_ANOMALY" not in codes:
            a = _spikes(ctx, r)
            if a:
                out.append(a)
    return out


def cost_alerts(ctx):
    cfg = ctx.cfg
    bill = D.load_billing()
    bill["date"] = pd.to_datetime(bill["date"])
    team = bill.groupby(["team", "date"])["cost_inr"].sum().unstack(0).sort_index().fillna(0)
    inv = ctx.data.inventory
    out = []
    win = int(cfg("alerts.cost_window_days"))
    look = int(cfg("alerts.cost_lookback_days"))
    for t in team.columns:
        if not t:
            continue
        s = team[t]
        trail = s.shift(1).rolling(win).mean()
        ratio = (s / trail)[-look:]
        step = (s != s.shift(1))[-look:]                 # alert on the provisioning step, not the days after it
        for day, rv in ratio[(ratio > cfg("alerts.cost_jump_ratio")) & step].items():
            created = inv[(inv["owner_team"] == t) & inv["created_at"].str.startswith(str(day.date()))]
            out.append(_alert("cost_increase", "warning", None, f"team {t}: daily cost +{(rv - 1):.0%} on {day.date()}",
                              f"Rs {s[day] - trail[day]:,.0f}/day above its 7-day average (x{rv:.2f}, threshold "
                              f"x{cfg('alerts.cost_jump_ratio')}); {len(created)} resource(s) created by {t} that day"
                              + (f": {', '.join(created['name'].head(5))}" if len(created) else ""),
                              f"team_daily_cost:{t}", round(float(rv), 3), cfg("alerts.cost_jump_ratio"),
                              f"7 days before {day.date()}", day.isoformat(), 1, "confirm the new resources are intended"))
        base = s.iloc[:int(cfg("alerts.budget_base_days"))]
        days_month = cfg.t("hours_per_month") / cfg.t("hours_per_day")
        budget = base.mean() * days_month * cfg("alerts.budget_multiplier")
        last = s.index[-1]
        month = s[(s.index.month == last.month) & (s.index.year == last.year)]
        days_left = pd.Period(last, "M").days_in_month - last.day
        forecast = month.sum() + s.iloc[-int(cfg("alerts.runrate_days")):].mean() * days_left
        if forecast > budget:
            over = forecast / budget - 1
            out.append(_alert("budget_overrun", "critical" if over > cfg("alerts.budget_critical_over") else "warning",
                              None, f"team {t}: month-end forecast {over:.0%} over budget",
                              f"forecast Rs {forecast:,.0f} (spent Rs {month.sum():,.0f} + Rs {s.iloc[-int(cfg('alerts.runrate_days')):].mean():,.0f}/day "
                              f"x {days_left} days) vs budget Rs {budget:,.0f} (= {cfg('alerts.budget_multiplier')} x first-quarter "
                              "monthly spend)", f"team_month_forecast:{t}", round(float(forecast)), round(float(budget)),
                              f"{last.strftime('%Y-%m')}", ctx.now.isoformat(), 1, "review this team's recommendations first"))
    return out


def build(ctx, res):
    items = resource_alerts(ctx, res) + cost_alerts(ctx)
    items.sort(key=lambda a: (SEVERITY.index(a["severity"]), a["type"], a["resource_id"] or "", a["title"]))
    for i, a in enumerate(items, 1):
        a["alert_id"] = f"ALT-{i:04d}"
    return items


def envelope(ctx, items):
    counts = {}
    for a in items:
        counts[a["severity"]] = counts.get(a["severity"], 0) + 1
    return {"schema_version": ctx.cfg.meta("schema_version"), "generated_at": ctx.cfg.meta("now"),
            "counts": counts, "items": items}


def main():
    from .run import build as run_build
    env, ctx, res, alerts = run_build(with_alerts=True)
    (D.DATA / "alerts.json").write_text(json.dumps(envelope(ctx, alerts), indent=1, default=str), encoding="utf-8")
    print(len(alerts), "alerts")


if __name__ == "__main__":
    main()
