"""CP11 - cost options per resource (schema 4.5 `options`) and the Rs 500 floor.

Apply order is fixed: snapshot/delete/release -> stop -> resize/shrink/upsize -> schedule.
a_sequential  each later saving is computed on what is left after the earlier step (never double counts)
b_additive    each saving computed against the original cost and summed (the naive way; double counts)"""
import numpy as np

from .base import finding

C = "cost"
ORDER = ["snapshot+delete", "release", "snapshot+stop", "stop", "shrink_volume", "upsize", "resize", "schedule"]
COMPUTE_ACTIONS = {"snapshot+stop", "stop", "upsize", "resize", "schedule"}   # floor applies to these only


def _parts(ctx, r):
    """Current monthly cost split into compute / storage / ip."""
    pr = ctx.data.prices
    inv = r.inv
    if r.type == "ip":
        return {"compute": 0, "storage": 0, "ip": pr["public_ip"]}
    if r.type == "volume":
        return {"compute": 0, "storage": float(inv["disk_gb"]) * pr["block_volume"], "ip": 0}
    plan = ctx.data.plans.get(inv["plan_id"])
    compute = plan["price"] if plan and r.state != "stopped" else 0
    return {"compute": compute, "storage": float(inv["disk_gb"] or 0) * pr["block_volume"], "ip": 0}


def _used_gb(r):
    if r.type == "volume" and r.vol is not None:
        return float(r.inv["disk_gb"]) * np.nanmean(r.vol["disk_used_pct"]) / 100
    if r.type == "vm" and r.arr is not None and np.isfinite(r.arr["disk_used_pct"]).any():
        return float(r.inv["disk_gb"]) * np.nanmean(r.arr["disk_used_pct"]) / 100
    return float(r.inv.get("disk_gb") or 0)            # unknown usage: snapshot the whole disk (conservative)


def _apply(ctx, r, action, parts):
    """Monthly cost after applying `action` to the CURRENT parts (sequential model)."""
    pr, p = ctx.data.prices, dict(parts)
    hpw = ctx.cfg.t("hours_per_week")
    if action == "snapshot+delete":
        return {"compute": 0, "storage": _used_gb(r) * pr["snapshot"], "ip": 0}
    if action == "release":
        p["ip"] = 0
    elif action == "stop":
        p["compute"] = 0
    elif action == "snapshot+stop":
        p["compute"] = 0
        p["storage"] += _used_gb(r) * pr["snapshot"]
    elif action == "shrink_volume":
        p["storage"] = r.actions["shrink_volume"]["target_gb"] * pr["block_volume"]
    elif action in ("resize", "upsize"):
        p["compute"] = ctx.data.plans[r.actions[action]["target"]]["price"]
    elif action == "schedule":
        p["compute"] = p["compute"] * (hpw - r.actions["schedule"]["off_hours"]) / hpw
    return p


def _combos(actions):
    acts = [a for a in ORDER if a in actions]
    out = [()]
    for a in acts:
        out += [c + (a,) for c in out]
    return [c for c in out if c]


def _fmt(x):
    return f"Rs {x:,.0f}"


def _build(ctx, r, additive):
    base = _parts(ctx, r)
    cur = sum(base.values())
    opts = {"none": {"monthly_inr_after": round(cur), "saving_inr": 0, "formula": "no change"}}
    singles = {a: sum(_apply(ctx, r, a, base).values()) for a in r.actions}
    for combo in _combos(r.actions):
        if additive:
            after = cur - sum(cur - singles[a] for a in combo)
        else:
            p = base
            for a in combo:
                p = _apply(ctx, r, a, p)
            after = sum(p.values())
        key = "+".join(combo)
        opts[key] = {"monthly_inr_after": round(after), "saving_inr": round(cur) - round(after),
                     "formula": f"{_fmt(cur)} - {_fmt(after)} = {_fmt(cur - after)}/month"}
    r.cost = {"current": base, "current_total": cur, "options": opts}
    if r.actions:
        default = "+".join(a for a in ORDER if a in r.actions)
        r.default_option = default
        saving = opts[default]["saving_inr"]
        compute_only = all(a in COMPUTE_ACTIONS for a in r.actions) and "upsize" not in r.actions
        floor = ctx.cfg("cost.floor_inr")
        if compute_only and saving < floor:
            r.findings.append(finding(C, "BELOW_FLOOR", "below_floor", "monthly saving", saving, floor,
                                      message="correct but not worth a human's attention"))


def a_sequential(ctx, r):
    _build(ctx, r, additive=False)


def b_additive(ctx, r):
    _build(ctx, r, additive=True)


CANDIDATES = {
    "a_sequential": {"fn": a_sequential, "params": 1, "prior": 9, "desc": "sequential cost per action set (no double counting)"},
    "b_additive": {"fn": b_additive, "params": 1, "prior": 2, "desc": "sum of single savings vs the original cost (double counts)"},
}
