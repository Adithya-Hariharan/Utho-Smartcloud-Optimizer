"""Presentation of an engine outcome in the shape the frontend reads (PLAN_frontend_integration.md §2, §3).

Decisions are made in compute.py / noncompute.py; this module only shapes them: resource and evidence blocks,
the naive (average-based) cut, veto wording, trace strings, and the item for a metrics series with no inventory.
"""
import math

import numpy as np

from ..cost.model import format_inr
from . import replay as rp

LEAF = ("mean", "p50", "p95", "p99", "max")
TERMINAL_OK = {"recommend", "healthy"}
RESULT_MAP = {"pass": "pass", "fail": "fail", "info": "info", "skip": "skip", "healthy": "pass", "recommend": "pass",
              "flag": "fail", "below_floor": "fail", "reject": "fail", "upsize": "fail", "exclude": "fail",
              "match": "info", "kept": "info"}


def _null(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) or v == "" else v


def text(v):
    """Trace values and thresholds are always strings (the UI calls .match on them)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{round(v, 2):g}"
    return str(v)


def trace(steps, verdict):
    out = []
    for s in steps:
        res = RESULT_MAP.get(s["result"], "info")
        if s["terminal"]:
            res = "pass" if verdict in TERMINAL_OK else "fail"
        out.append({"step": s["step"], "check": s["check"], "value": text(s["value"]),
                    "threshold": text(s["threshold"]), "result": res, "terminal": bool(s["terminal"])})
    return out


def resource(row, member_names):
    return {"resource_id": row["resource_id"], "name": row["name"], "type": row["type"], "env": _null(row["env"]),
            "team": _null(row["owner_team"]), "owner": row["owner"], "region": _null(row["region"]),
            "purpose": _null(row["purpose"]), "service_group": _null(row["service_group"]), "members": member_names,
            "tags": list(row["tags_list"]), "state": _null(row["state"]), "plan_id": _null(row["plan_id"])}


def metrics(f, has_telemetry):
    """Each metric {mean, p50, p95, p99, max} or null when it has no data; the whole block null without telemetry."""
    if not has_telemetry:
        return None
    out = {}
    for k, m in f["metrics"].items():
        out[k] = None if m.get("p50") is None else {q: round(m[q], 2) for q in LEAF}
    return out


def recurring_peak(f):
    if not f.get("recurring_peak"):
        return None
    return {"window_ist": f.get("recurring_window") or "", "days": int(f["recurring_peak_days"])}


def naive_vm(e, row, f, cur, series, prod):
    """What an average-based tool would do (frontend reference, mock build_recs 742-756): size on mean CPU at a
    fixed 80% target, vCPU only. Returns (naive, replay attempt or None)."""
    mean = f.get("mean_cpu")
    basis = f"average CPU {mean:.1f}%"
    need = row["vcpu"] * mean / 80
    plan = next((p for p in e.cat if p.vcpu >= need), None)
    if plan is not None and plan.price < cur["compute_inr"]:
        att = rp.attempt(series.values["cpu_pct"], series.values["mem_pct"], row["vcpu"], row["ram_gb"], plan,
                         e.p.replay_limit(prod), e.p.mem_cap)
        return {"action": "resize", "target_plan": plan.plan_id, "saving_inr": int(cur["compute_inr"] - plan.price),
                "basis": basis, "replay_minutes_above_90": int(att["minutes_above_90"])}, att
    stop = mean < 5
    return {"action": "stop" if stop else "none", "target_plan": None,
            "saving_inr": int(cur["compute_inr"]) if stop else 0, "basis": basis, "replay_minutes_above_90": None}, None


def naive_volume(e, row, f):
    used = f["metrics"]["disk_used"]["mean"]
    rate = int(e.cfg.get("pricing.volume_inr_per_gb_month"))
    return {"action": "shrink_volume", "target_plan": None, "saving_inr": int(max(0, (row["disk_gb"] - 100) * rate)),
            "basis": f"{used:.0f}% used today" if used is not None else "low usage", "replay_minutes_above_90": None}


def veto(e, o, row, f, naive):
    """Frontend veto vocabulary (mock build_recs 761-787); kept.ts renders `${metric}: ${value} (rule ${cmp} ${thr})`."""
    v, m, code = o.veto or {}, f.get("metrics", {}), o.code
    t = lambda k: e.cfg.get(f"thresholds.{k}")
    g = lambda k, q: (m.get(k) or {}).get(q)
    msg = o.reason
    if code == "VETO_MEMORY":
        out = ("memory", "mem p99", g("mem", "p99"), t("veto_mem_p99_pct"), ">")
    elif code == "VETO_IOPS":
        out = ("iops", "iops p95 % of provisioned", g("iops_pct", "p95"), t("veto_iops_p95_pct"), ">")
    elif code == "VETO_NETWORK":
        out = ("network", "net p95 % of bandwidth", g("net_pct", "p95"), t("veto_net_p95_pct"), ">")
    elif code == "VETO_LEAK":
        out = ("leak", "sawtooth cycles", f["leak_score"], e.cfg.get("alerts.g6_leak_cycles"), "≥")
    elif code == "VETO_RECURRING_PEAK":
        out = ("recurring_peak", "days with a 30-min peak > 80%", f["recurring_peak_days"],
               t("recurring_peak_min_weeks"), "≥")
        if naive and naive.get("replay_minutes_above_90"):
            msg += (f" An average-based resize to {naive['target_plan']} spends "
                    f"{naive['replay_minutes_above_90']:,} min above 90% CPU in replay.")
    elif code == "PEAK_REPLAY_FAILED":
        out = ("replay", "minutes above 90% CPU", v.get("value", 0), v.get("threshold", 0), ">")
    elif code == "NO_CHEAPER_PLAN":
        out = ("sizing", "RAM needed (GB)", round(float(v.get("value", 0)), 1), v.get("threshold", 0), ">")
    elif code == "VETO_GROWTH":
        label = "days until disk 85% full" if row["type"] == "volume" else "days until CPU 85%"
        out = ("growth", label, round(float(v.get("value", 0))), t("growth_days_to_85"), "<")
    else:
        return None
    signal, metric, value, threshold, cmp = out
    return {"signal": signal, "metric": metric, "value": float(round(value, 2)) if value is not None else 0.0,
            "threshold": float(threshold), "comparator": cmp, "message": msg}


def replay_block(o, row):
    """Only present with at least one attempt; carries the current plan's size."""
    r = o.replay
    if not r or not r.get("attempts"):
        return None
    return {**r, "from_vcpu": int(row["vcpu"]), "from_ram_gb": int(row["ram_gb"])}


def stray_item(rid, preset, window_days, series, pct_label):
    """A metrics series with no inventory row: never priced or sized (D9)."""
    days = int(len(np.unique(np.flatnonzero(~np.isnan(series.primary)) // 288))) if series is not None else 0
    none = {"monthly_inr_after": 0, "saving_inr": 0, "formula": f"{format_inr(0)}/month, no change"}
    return {
        "rec_id": f"REC-{rid}-{preset}",
        "resource": {"resource_id": rid, "name": rid, "type": "vm", "env": None, "team": None, "owner": "unowned",
                     "region": None, "purpose": None, "service_group": None, "members": [], "tags": [],
                     "state": None, "plan_id": None},
        "verdict": "exclude", "reason_code": "NOT_IN_INVENTORY", "actions": [], "default_option": "none", "flags": [],
        "current": {"plan": None, "vcpu": None, "ram_gb": None, "disk_gb": None, "compute_inr": 0, "storage_inr": 0,
                    "ip_inr": 0, "monthly_inr": 0},
        "target": None, "schedule": None, "options": {"none": none},
        "evidence": {"window_days": window_days, "days_of_data": days,
                     "coverage": series.report["coverage"] if series is not None else 0.0,
                     "peak_window_coverage": series.report["peak_window_coverage"] if series is not None else 0.0,
                     "percentile_used": pct_label, "metrics": None, "recurring_peak": None, "naive": None},
        "replay": None, "veto": None, "risk": None,
        "reason": "Metrics arrive for a machine that is not in the inventory: it is listed, never priced or sized.",
        "explanation_ai": None, "formula": none["formula"],
        "trace": [{"step": "inventory.exists", "check": "Resource is in the inventory", "value": "no",
                   "threshold": "required", "result": "fail", "terminal": True}],
        "alert_ids": [],
    }
