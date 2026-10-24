"""Build recommendation objects and the envelope exactly as PLAN.md 4.5 (schema v1.0) defines them."""
import numpy as np

from .components.cost import ORDER as APPLY_ORDER
from .evidence import pct
from .replay import budget_minutes

GROUPS = ["cleanup", "stop", "size", "schedule"]           # schema: 1 delete/release, 2 stop, 3 resize/shrink/upsize, 4 schedule
GROUP_OF = {"snapshot+delete": "cleanup", "release": "cleanup", "snapshot+stop": "stop", "stop": "stop",
            "shrink_volume": "size", "upsize": "size", "resize": "size", "schedule": "schedule"}


def _r(v, nd=1):
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        return None if not np.isfinite(v) else round(float(v), nd)
    return v


def _plan_block(ctx, r, plan, parts):
    p = ctx.data.plans.get(plan) if plan else None
    inv = r.inv or {}
    return {"plan": plan or None, "vcpu": p["vcpu"] if p else None, "ram_gb": p["ram"] if p else None,
            "disk_gb": float(inv["disk_gb"]) if inv.get("disk_gb") not in ("", None) else None,
            "compute_inr": round(parts["compute"]), "storage_inr": round(parts["storage"]), "ip_inr": round(parts["ip"]),
            "monthly_inr": round(sum(parts.values()))}


def _action(ctx, r, a):
    inv = r.inv
    plans = ctx.data.plans
    if a in ("resize", "upsize"):
        t = r.actions[a]["target"]
        cur = plans[inv["plan_id"]]
        desc = (f"{a.capitalize()} {inv['plan_id']} ({cur['vcpu']} vCPU/{cur['ram']:.0f} GB) -> "
                f"{t} ({plans[t]['vcpu']} vCPU/{plans[t]['ram']:.0f} GB)")
        return desc, ["maintenance_window"] if r.env == "prod" else [], True, f"Resize back to {inv['plan_id']}"
    if a == "schedule":
        w = "; ".join(f"{x['days'][0]} {x['start']} -> {x['days'][-1]} {x['end']}" for x in r.schedule["windows"])
        return f"Stop on schedule (IST): {w}", [], True, "Remove the schedule"
    if a == "stop":
        return "Stop the VM; delete after 14 days if nobody objects", [], True, "Start the VM"
    if a == "snapshot+stop":
        return "Snapshot the disk, then stop the VM", ["snapshot_first"], True, "Start the VM"
    if a == "snapshot+delete":
        return "Snapshot, then delete", ["snapshot_first"], True, "Restore from the snapshot"
    if a == "release":
        return "Release the public IP", [], False, "Allocate a new IP (the old address cannot be re-acquired)"
    if a == "shrink_volume":
        return f"Migrate to a {r.actions[a]['target_gb']:.0f} GB volume (no in-place shrink)", ["snapshot_first"], True, \
            "Keep the old volume until the new one is verified"
    return a, [], True, ""


def _evidence(ctx, r):
    if r.ev is None:
        return {"window_days": ctx.n_days, "days_of_data": 0, "coverage": None, "peak_window_coverage": None,
                "percentile_used": None, "metrics": None, "recurring_peak": None, "naive": None}
    ev, arr, cfg = r.ev, r.arr, ctx.cfg
    q = cfg.preset["percentile_prod"] if r.env == "prod" else cfg.preset["percentile_nonprod"]
    ps = cfg("evidence.report_percentiles")
    m = {"cpu": {"mean": _r(ev["mean"]), **{f"p{p}": _r(ev[f"p{p}"]) for p in ps}, "max": _r(ev["max"])},
         "mem": {"mean": _r(ev["mem_mean"]), **{f"p{p}": _r(ev[f"mem_p{p}"]) for p in ps}, "max": _r(ev["mem_max"])},
         "iops_pct": {"p95": _r(ev["iops_pct_p95"])}, "net_pct": {"p95": _r(ev["net_pct_p95"])},
         "disk_used": {"pct": _r(pct(arr["disk_used_pct"], cfg("evidence.io_net_percentile")))}}
    rec = {"days": ev["peak_days"], "second_day_peak": _r(ev["second_day_peak"]),
           "acf_24h": _r(ev["acf_day"], 2), "acf_168h": _r(ev["acf_week"], 2)} if ev["peak_days"] else None
    return {"window_days": ctx.n_days, "days_of_data": ev["days_of_data"], "coverage": _r(ev["coverage"], 3),
            "peak_window_coverage": _r(ev["peak_hours_coverage"], 3), "percentile_used": f"p{q}",
            "metrics": m, "recurring_peak": rec, "naive": (r.sizing or {}).get("naive")}


def _replay(ctx, r):
    s = r.sizing
    if not s:
        return None
    cfg = ctx.cfg
    rp = s.get("replay")
    return {"limit_minutes_above_90": round(budget_minutes(r, cfg, r.ev["n_slots"] / cfg.t("slots_per_day"))),
            "mem_cap_pct": cfg("sizing.mem_cap"), "attempts": s.get("attempts", []),
            "passed": bool(s.get("target")), "chosen_plan": s.get("target"),
            "projected": None if not rp else {"minutes_above_90": round(rp["overload_minutes"]),
                                                "max_cpu_pct": _r(rp["max_cpu_pct"]), "max_mem_pct": _r(rp["max_mem_pct"])}}


def build(ctx, r):
    cfg = ctx.cfg
    inv = r.inv or {"resource_id": r.id, "name": r.id, "type": r.type, "region": "", "owner_team": "", "purpose": "",
                    "service_group": "", "tags": "", "plan_id": "", "disk_gb": ""}
    tags = [t for t in (inv.get("tags") or "").split(";") if t]
    group = (r.sizing or {}).get("group")
    resource = {"resource_id": r.id, "name": inv["name"], "type": r.type, "env": r.env or "prod",
                "team": inv.get("owner_team") or "unowned", "owner": inv.get("owner_team") or "unowned",
                "region": inv.get("region"), "purpose": inv.get("purpose"),
                "service_group": inv.get("service_group") or None, "members": group["members"] if group else [],
                "tags": tags}
    acting = r.verdict in ("recommend", "upsize")
    acts = [a for a in APPLY_ORDER if a in r.actions] if acting else []
    actions = []
    for a in acts:
        desc, req, rev, rb = _action(ctx, r, a)
        actions.append({"type": a, "order": GROUPS.index(GROUP_OF[a]) + 1, "description": desc, "requires": req,
                        "reversible": rev, "rollback": rb})
    parts = r.cost["current"] if r.cost else {"compute": 0, "storage": 0, "ip": 0}
    current = _plan_block(ctx, r, inv.get("plan_id"), parts)
    tgt_plan = next((r.actions[a]["target"] for a in ("resize", "upsize") if a in r.actions), None) if acting else None
    target = None
    if tgt_plan:
        tp = dict(parts, compute=ctx.data.plans[tgt_plan]["price"])
        target = _plan_block(ctx, r, tgt_plan, tp)
    options = r.cost["options"] if r.cost else {"none": {"monthly_inr_after": 0, "saving_inr": 0, "formula": "no change"}}
    if not acting:
        options = {"none": options["none"]}
    default = r.default_option if acting else None
    p = r.primary
    return {
        "rec_id": f"REC-{r.id}-{cfg.preset_name}",
        "resource": resource,
        "verdict": r.verdict,
        "reason_code": r.reason_code,
        "actions": actions,
        "default_option": default,
        "flags": r.flags,
        "current": current,
        "target": target,
        "schedule": r.schedule if acting and "schedule" in r.actions else None,
        "options": options,
        "evidence": _evidence(ctx, r),
        "replay": _replay(ctx, r) if r.type == "vm" else None,
        "veto": r.veto if r.verdict == "reject" else None,
        "risk": r.risk if acting else None,
        "reason": p["message"] or f"{p['check']}: {p['value']} vs {p['threshold']}",
        "explanation_ai": None,
        "formula": options[default]["formula"] if default else "-",
        "trace": [{"step": f"{f['comp']}.{f['check']}", "check": f["check"], "value": f["value"],
                   "threshold": f["threshold"], "result": f["result"], "terminal": f is p} for f in (r.shown or [])],
        "alert_ids": [],
    }


def envelope(ctx, res):
    cfg = ctx.cfg
    items = [build(ctx, r) for r in res]
    below = [r for r in res if r.reason_code == "BELOW_FLOOR"]
    saved = sum(r.cost["options"][r.default_option]["saving_inr"] for r in below
                if r.cost and r.default_option in r.cost["options"])
    return {"schema_version": cfg.meta("schema_version"), "generated_at": cfg.meta("now"), "preset": cfg.preset_name,
            "config_hash": cfg.hash(),
            "data_window": {"start": str(ctx.data.window_start.date()), "end": str((ctx.now - _one_day()).date()),
                            "timezone": cfg.meta("timezone")},
            "items": items, "below_floor": {"count": len(below), "monthly_inr": saved}}


def _one_day():
    import pandas as pd
    return pd.Timedelta(days=1)
