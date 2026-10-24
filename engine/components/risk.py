"""CP10 - risk and confidence for recommended changes.

a_points    PLAN.md 7 points table (prod +3, stateful +2, projected p99, bursty, delete/stop, coverage)
b_bootstrap probability of a bad month: resample the observed days (block bootstrap, whole days) and count
            how often the change would have hurt (overload minutes over budget / activity inside an off
            window / activity on a stopped VM). Level from the probability, escalated for prod/stateful/stop.
c_hybrid    b decides the level; the points are still listed so a human can see the contributing factors."""
import numpy as np

from ..replay import budget_minutes
from .base import has_tag, is_prod

C = "risk"
LEVELS = ["Low", "Medium", "High"]


def _points(ctx, r):
    cfg, ev = ctx.cfg, r.ev or {}
    pts = []
    if r.type == "vm":
        if is_prod(r):
            pts.append(("prod", cfg("risk.points_prod")))
        elif r.env == "staging":
            pts.append(("staging", cfg("risk.points_staging")))
        if has_tag(r, "stateful"):
            pts.append(("stateful", cfg("risk.points_stateful")))
        rp = (r.sizing or {}).get("replay")
        if rp and ("resize" in r.actions or "upsize" in r.actions):
            proj = rp["cpu_p"]
            if proj > cfg("risk.proj_high"):
                pts.append((f"projected p {proj:.0f} > {cfg('risk.proj_high')}", cfg("risk.points_proj_high")))
            elif proj > cfg("risk.proj_mid"):
                pts.append((f"projected p {proj:.0f} > {cfg('risk.proj_mid')}", cfg("risk.points_proj_mid")))
        if ev and ev.get("p50", 0) > 0 and ev["p99"] / ev["p50"] > cfg("risk.bursty_ratio"):
            pts.append(("bursty (p99/p50 > 3)", 1))
        if ev and ev.get("coverage", 1) < cfg("gates_data.medium_coverage"):
            pts.append(("coverage < 95%", 1))
    if any(a.endswith("delete") for a in r.actions):
        pts.append(("delete", cfg("risk.points_delete")))
    elif any(a.endswith("stop") for a in r.actions):
        pts.append(("stop", cfg("risk.points_stop")))
    return pts


def _level_from_points(ctx, total):
    if total <= ctx.cfg("risk.low_points_max"):
        return "Low"
    return "Medium" if total <= ctx.cfg("risk.medium_points_max") else "High"


def daily_events(ctx, r):
    """Per observed day: does the recommended change hurt? (minutes over budget-relevant threshold)."""
    cfg = ctx.cfg
    ev_days = []
    if r.type != "vm" or r.arr is None:
        return None, 0
    spd = cfg.t("slots_per_day")
    cpu = r.arr["cpu_pct"].reshape(-1, spd)
    if ("resize" in r.actions or "upsize" in r.actions) and r.sizing and r.sizing.get("replay"):
        ev_days.append(r.sizing["replay"]["per_day_overload"])
        budget = budget_minutes(r, cfg, cfg.t("days_per_month"))     # the monthly budget (bootstrap draws a month)
    else:
        budget = 0
    if "schedule" in r.actions and r.schedule:
        from ..evidence import hour_of_week
        off = r.ev["off_hours"][hour_of_week(ctx, r.ev["n_slots"])].reshape(-1, spd)
        act = np.nan_to_num((cpu > cfg("risk.schedule_active_cpu")) & off, nan=0)
        ev_days.append(act.sum(axis=1) * cfg.t("slot_minutes"))
    if any(a.endswith("stop") for a in r.actions):
        with np.errstate(all="ignore"):
            p = np.nanpercentile(cpu, cfg("candidates.offhour_percentile"), axis=1)
        ev_days.append(np.nan_to_num(p > cfg("candidates.idle_cpu"), nan=0) * cfg.t("minutes_per_hour"))
    if not ev_days:
        return None, 0
    return np.vstack(ev_days), budget


def probability(ctx, r):
    ev, budget = daily_events(ctx, r)
    if ev is None:
        return None
    cfg = ctx.cfg
    rng = np.random.default_rng(int(cfg("risk.seed")))
    n = ev.shape[1]
    draws = int(cfg("risk.bootstrap_draws"))
    idx = rng.integers(0, n, size=(draws, cfg.t("days_per_month")))
    monthly = ev[:, idx].sum(axis=-1)                        # (events, draws)
    bad = (monthly[0] > budget) if len(monthly) else np.zeros(draws, bool)
    for k in range(1, len(monthly)):
        bad |= monthly[k] > 0
    return float(bad.mean())


def _escalate(ctx, r, level):
    steps = int(is_prod(r)) + int(has_tag(r, "stateful")) + int(any(a.endswith(("stop", "delete")) for a in r.actions))
    return LEVELS[min(LEVELS.index(level) + steps, len(LEVELS) - 1)]


def _level_from_p(ctx, p):
    if p is None:
        return "Low"
    if p < ctx.cfg("risk.low_max"):
        return "Low"
    return "Medium" if p < ctx.cfg("risk.medium_max") else "High"


def _confidence(ctx, r):
    ev = r.ev or {}
    cov = ev.get("coverage", 1)
    if cov >= ctx.cfg("gates_data.medium_coverage") and ev.get("days_of_data", ctx.data.n_days) >= ctx.cfg("gates_data.min_history_days"):
        return "High", f"coverage {cov:.0%}, {ev.get('days_of_data', ctx.data.n_days)} days"
    return "Medium", f"coverage {cov:.0%}"


def _store(ctx, r, level, score, pts, p):
    conf, basis = _confidence(ctx, r)
    if p is None and not pts:
        pts = [("no running workload affected (volume / IP / stopped VM)", 0)]
    r.risk = {"level": level, "score": score, "probability": None if p is None else round(p, 4),
              "points": [{"factor": f, "points": v, "detail": f} for f, v in pts], "confidence": conf,
              "confidence_basis": basis}


def a_points(ctx, r):
    pts = _points(ctx, r)
    total = sum(v for _, v in pts)
    _store(ctx, r, _level_from_points(ctx, total), total, pts, None)


def b_bootstrap(ctx, r):
    p = probability(ctx, r)
    _store(ctx, r, _escalate(ctx, r, _level_from_p(ctx, p)), p, [], p)


def c_hybrid(ctx, r):
    p = probability(ctx, r)
    _store(ctx, r, _escalate(ctx, r, _level_from_p(ctx, p)), p, _points(ctx, r), p)


CANDIDATES = {
    "a_points": {"fn": a_points, "params": 12, "prior": 5, "desc": "PLAN.md 7 points table -> Low/Medium/High"},
    "b_bootstrap": {"fn": b_bootstrap, "params": 4, "prior": 8, "desc": "P(bad month) by resampling observed days; escalate for prod/stateful/stop"},
    "c_hybrid": {"fn": c_hybrid, "params": 16, "prior": 9, "desc": "b decides the level; points listed as contributing factors"},
}
