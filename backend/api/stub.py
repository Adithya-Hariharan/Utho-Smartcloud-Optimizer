"""Stub recommendations (PLAN_final.md B6): one valid §4.5 item per inventory row with no decision.

Kept as the fallback the API serves if the engine fails at startup, so the UI never loses its data.
"""
from ..cost.model import current_cost, no_change_option
from ..engine.common import LEAF_KEYS, group_members, resource_block

STUB_REASON = "Engine not enabled; no decision computed."


def evidence_block(f, window_days):
    return {"window_days": window_days, "days_of_data": f["days_of_data"], "coverage": f["coverage"],
            "peak_window_coverage": f["peak_window_coverage"], "percentile_used": None,
            "metrics": {k: {q: m[q] for q in LEAF_KEYS} for k, m in f["metrics"].items()},
            "recurring_peak": None, "naive": None}


def stub_item(row, f, members, alert_ids, cfg, preset="default"):
    current = current_cost(row, cfg)
    none = no_change_option(current["monthly_inr"])
    return {
        "rec_id": f"REC-{row['resource_id']}-{preset}",
        "resource": resource_block(row, members),
        "verdict": "healthy",
        "reason_code": "RIGHT_SIZED",
        "actions": [],
        "default_option": "none",
        "flags": [],
        "current": current,
        "target": None,
        "schedule": None,
        "options": {"none": none},
        "evidence": evidence_block(f, int(cfg.raw["window"]["days"])),
        "replay": None,
        "veto": None,
        "risk": None,
        "reason": STUB_REASON,
        "explanation_ai": None,
        "formula": none["formula"],
        "trace": [],
        "alert_ids": alert_ids,
    }


def stub_items(ds, features, alerts, cfg, preset="default"):
    members = group_members(ds.inventory)
    by_resource = {}
    for a in alerts:
        by_resource.setdefault(a["resource_id"], []).append(a["alert_id"])
    return [stub_item(row, features[row["resource_id"]], members.get(row["resource_id"], []),
                      by_resource.get(row["resource_id"], []), cfg, preset)
            for _, row in ds.inventory.iterrows()]


def envelope(items, cfg, generated_at, preset="default"):
    w = cfg.raw["window"]
    return {"schema_version": cfg.raw["schema_version"], "generated_at": generated_at, "preset": preset,
            "config_hash": cfg.hash, "data_window": {"start": w["start"], "end": w["end"], "timezone": w["timezone"]},
            "items": items, "below_floor": {"count": 0, "monthly_inr": 0}}
