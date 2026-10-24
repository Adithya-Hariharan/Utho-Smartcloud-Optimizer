"""One pure function per endpoint: shapes the computed state into the frontend's types
(frontend/src/types/contract.ts, api.ts; PLAN_frontend_integration.md §4)."""
import math

import numpy as np
import pandas as pd

from ..engine.sizing import catalogue
from ..pipeline.clean import gap_runs

INVENTORY_FIELDS = ["resource_id", "name", "type", "region", "env", "owner_team", "purpose", "service_group",
                    "plan_id", "vcpu", "ram_gb", "disk_gb", "provisioned_iops", "bandwidth_mbps", "state",
                    "stopped_since", "created_at", "last_resized_at", "attached_to", "unattached_since",
                    "optimize_policy"]
METRIC_COLUMNS = {"cpu": "cpu_pct", "mem": "mem_pct", "disk_used": "disk_used_pct", "iops": "iops",
                  "net_in": "net_in_mbps", "net_out": "net_out_mbps"}
METRIC_ALIASES = {"disk": "disk_used"}
VOLUME_METRICS = {"iops", "disk_used"}
SLOTS_PER_HOUR = 12


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


def r1(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 1)


def r2(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 2)


def _plain(v):
    """Inventory cell -> JSON: '' / NaN / NaT -> null, timestamps -> ISO (IST), floats that are ints -> int."""
    if v is None or v is pd.NaT or (isinstance(v, float) and math.isnan(v)) or v == "":
        return None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if isinstance(v, (np.floating, float)):
        return int(v) if float(v).is_integer() else float(v)
    if isinstance(v, np.integer):
        return int(v)
    return v


def data_window(cfg):
    """IST window with an EXCLUSIVE end (2026-10-20T00:00+05:30), as the frontend expects."""
    w = cfg.raw["window"]
    end = pd.Timestamp(w["end"]) + pd.Timedelta(minutes=int(w["step_minutes"]))
    return {"start": pd.Timestamp(w["start"]).isoformat(), "end": end.isoformat(), "timezone": w["timezone"]}


def envelope(items, below, cfg, generated_at, preset):
    return {"schema_version": cfg.raw["schema_version"], "generated_at": generated_at, "preset": preset,
            "config_hash": cfg.hash, "mock_engine": False, "data_window": data_window(cfg), "items": items,
            "below_floor": below}


# ---- E1 / E2: resources ---------------------------------------------------------------------------

def _leaf(m):
    return None if m is None or m.get("p50") is None else {q: r2(m[q]) for q in ("mean", "p50", "p95", "p99", "max")}


def resource_row(st, rid):
    row = st.inv.loc[rid]
    f = st.features.get(rid) or {}
    out = {k: _plain(rid if k == "resource_id" else row[k]) for k in INVENTORY_FIELDS}
    out["tags"] = list(row["tags_list"])
    out["monthly_inr"] = int(st.monthly[rid])
    out["has_metrics"] = rid in st.cleaned.series
    stats = daily = dmax = None
    if row["type"] == "vm" and out["has_metrics"] and f.get("mean_cpu") is not None:
        m = f["metrics"]
        stats = {"cpu_p95": r2(m["cpu"]["p95"]), "cpu_p99": r2(m["cpu"]["p99"]), "cpu_mean": r2(m["cpu"]["mean"]),
                 "mem_p95": r2(m["mem"]["p95"]), "mem_p99": r2(m["mem"]["p99"]), "coverage": f["coverage"]}
        daily = [r1(v) for v in f["daily_p95"]["cpu"]]
        dmax = [r1(v) for v in f["daily_max"]]
    elif row["type"] == "volume" and out["has_metrics"]:
        stats = {"cpu_p95": None, "cpu_p99": None, "cpu_mean": None, "mem_p95": None, "mem_p99": None,
                 "coverage": f["coverage"]}
        daily = [r1(v) for v in f["daily_mean"]["disk_used"]]
    out.update(stats=stats, daily_p95=daily, daily_max=dmax)
    return out


def resources(st, region=None, env=None, team=None, type=None):
    out = []
    for rid, row in st.inv.iterrows():
        e, t = row["env"] or "untagged", row["owner_team"] or "unowned"
        if (region and row["region"] != region) or (env and e != env) or (team and t != team) or (type and row["type"] != type):
            continue
        out.append(resource_row(st, rid))
    return out


def features_flat(st, rid):
    f = st.features.get(rid)
    if not f or rid not in st.cleaned.series:
        return None
    m = f["metrics"]
    trend = f.get("trend", {})
    get = lambda k: f.get(k)
    return {
        "cpu": _leaf(m.get("cpu")), "mem": _leaf(m.get("mem")), "iops_pct": _leaf(m.get("iops_pct")),
        "net_pct": _leaf(m.get("net_pct")), "disk_used": _leaf(m.get("disk_used")),
        "coverage": f["coverage"], "peak_window_coverage": f["peak_window_coverage"] if f["kind"] == "vm" else None,
        "days_of_data": f["days_of_data"],
        "cpu_slope": r2((trend.get("cpu") or {}).get("slope")),
        "disk_slope": r2((trend.get("disk_used") or {}).get("slope")),
        "level_shift_up": r2(get("level_shift_up")), "level_shift_down": r2(get("level_shift_down")),
        "recurring_peak_days": get("recurring_peak_days"), "recurring_window": get("recurring_window"),
        "p99_excl_top_day": r2(get("p99_excl_top_day")), "mem_std": r2(get("mem_std")),
        "leak_cycles": get("leak_score"), "how_p95": [r1(v) for v in f["how_p95"]] if f.get("how_p95") else None,
    }


def resource_detail(st, rid):
    if rid not in st.inv.index:
        raise NotFound(rid)
    item = st.by_id["default"][rid]
    return {"resource": resource_row(st, rid), "features": features_flat(st, rid), "trace": item["trace"],
            "dq": dq_row(st, rid)}


# ---- E3: metrics ------------------------------------------------------------------------------

def _hourly(arr):
    h = arr.reshape(-1, SLOTS_PER_HOUR)
    ok = ~np.isnan(h)
    any_ = ok.any(axis=1)
    with np.errstate(all="ignore"):
        mean = np.where(any_, np.nansum(h, axis=1) / np.maximum(ok.sum(axis=1), 1), np.nan)
        mx = np.where(any_, np.nanmax(np.where(ok, h, -np.inf), axis=1), np.nan)
    return [r1(v) for v in mean], [r1(v) for v in mx]


def gaps(st, s):
    g = st.cleaned.grid
    ts = g.ts_local
    out = []
    for a, b, kind in gap_runs(s, int(st.cfg.get("metrics.gap_min_slots"))):
        out.append({"start": ts[a].isoformat(), "end": (ts[b - 1] + pd.Timedelta(minutes=5)).isoformat(),
                    "kind": kind, "hours": round((b - a) / SLOTS_PER_HOUR, 1)})
    return out


def metric_series(st, rid, metric="cpu", step="1h"):
    if rid not in st.inv.index:
        raise NotFound(rid)
    metric = METRIC_ALIASES.get(metric, metric)
    if metric not in METRIC_COLUMNS:
        raise BadRequest(f"metric must be one of {sorted(METRIC_COLUMNS)}")
    if step not in ("1h", "5m"):
        raise BadRequest("step must be 1h or 5m")
    row = st.inv.loc[rid]
    if row["type"] == "volume" and metric not in VOLUME_METRICS:
        raise BadRequest(f"volumes have only {sorted(VOLUME_METRICS)}")
    out = {"resource_id": rid, "metric": metric, "step_seconds": 3600 if step == "1h" else 300,
           "start": st.cleaned.grid.ts_utc[0].isoformat(), "mean": [], "max": [], "gaps": []}
    s = st.cleaned.series.get(rid)
    if s is None:
        return out
    arr = s.values[METRIC_COLUMNS[metric]]
    if step == "1h":
        out["mean"], out["max"] = _hourly(arr)
    else:
        vals = [r1(v) for v in arr]
        out["mean"], out["max"] = vals, list(vals)
    out["gaps"] = gaps(st, s) if s.kind == "vm" else []
    return out


# ---- E4: replay -------------------------------------------------------------------------------

def replay_series(st, rid, preset="default"):
    if preset not in st.runs:
        raise BadRequest(f"preset must be one of {list(st.runs)}")
    if rid not in st.inv.index:
        raise NotFound(rid)
    item = st.by_id[preset][rid]
    rp = item["replay"]
    s = st.cleaned.series.get(rid)
    if not rp or s is None or s.kind != "vm":
        raise NotFound(f"no replay for {rid} ({item['verdict']}/{item['reason_code']})")
    # the plan the attempts were replayed on (the naive cut when that is the only attempt), so chart and
    # attempts always describe the same machine
    naive = item["evidence"]["naive"] or {}
    to_plan = rp["chosen_plan"] or rp["attempts"][-1]["plan"] or naive.get("target_plan")
    plan = next(p for p in catalogue(st.cfg) if p.plan_id == to_plan)
    _, actual = _hourly(s.values["cpu_pct"])
    ratio = rp["from_vcpu"] / plan.vcpu
    return {"resource_id": rid, "preset": preset, "from_plan": item["current"]["plan"], "to_plan": to_plan,
            "from_vcpu": rp["from_vcpu"], "to_vcpu": plan.vcpu, "step_seconds": 3600,
            "start": st.cleaned.grid.ts_utc[0].isoformat(), "actual_cpu": actual,
            "projected_cpu": [None if v is None else round(v * ratio, 1) for v in actual],
            "limit_minutes_above_90": rp["limit_minutes_above_90"], "mem_cap_pct": rp["mem_cap_pct"],
            "attempts": rp["attempts"], "passed": rp["passed"]}


# ---- E6 summary / E7 alerts -------------------------------------------------------------------

def potential_after(item):
    """Every default-preset recommendation accepted: its default option if it is a recommend that saves money."""
    o = item["options"][item["default_option"]]
    return o["monthly_inr_after"] if item["verdict"] == "recommend" and o["saving_inr"] > 0 else item["current"]["monthly_inr"]


def summary(st):
    from ..insights.growth import bill_trend, growth_waterfall
    items = st.by_id["default"]
    before = int(sum(st.monthly[r] for r in st.inv.index))
    after = int(sum(potential_after(items[r]) for r in st.inv.index))

    def split(key):
        out = {}
        for rid, row in st.inv.iterrows():
            k = key(row)
            d = out.setdefault(k, {"monthly_before_inr": 0, "potential_after_inr": 0})
            d["monthly_before_inr"] += int(st.monthly[rid])
            d["potential_after_inr"] += int(potential_after(items[rid]))
        return dict(sorted(out.items()))

    verdicts = {}
    for i in items.values():
        verdicts[i["verdict"]] = verdicts.get(i["verdict"], 0) + 1
    types = st.inv["type"].value_counts().to_dict()
    return {"monthly_before_inr": before, "potential_after_inr": after,
            "potential_saving_pct": round((before - after) / before * 100, 2) if before else 0.0,
            "by_env": split(lambda r: r["env"] or "untagged"), "by_team": split(lambda r: r["owner_team"] or "unowned"),
            "by_region": split(lambda r: r["region"]),
            "counts": {"vm": int(types.get("vm", 0)), "volume": int(types.get("volume", 0)), "ip": int(types.get("ip", 0)),
                       "verdicts": dict(sorted(verdicts.items()))},
            "bill_trend_6m": bill_trend(st.ds.billing),
            "growth_waterfall": growth_waterfall(st.ds.billing, st.ds.inventory, st.monthly)}


def alerts(st):
    return {"mock_engine": False, "items": st.alerts}


# ---- E10 data quality -------------------------------------------------------------------------

def _first_int(text, default=0):
    import re
    m = re.search(r"(\d+)", text or "")
    return int(m.group(1)) if m else default


def _sum_ints(text):
    import re
    # "5 CPU values in 103-110%, 5 in -3..-1%" -> 10
    return sum(int(x) for x in re.findall(r"\b(\d+) (?:CPU values )?in\b", text or ""))


def dq_checks(doc):
    """Injected (generator fault log) vs detected (cleaning step), per E-case (frontend reference dq_checks)."""
    by = {r["name"]: r for r in doc["resources"]}
    faults = lambda k: [x for x in doc["faults"] if x["fault"] == k]
    names = lambda k: ", ".join(x["name"] for x in faults(k))
    t = doc["totals"]
    pct = lambda v: f"{(v or 0) * 100:.1f}%"
    api02, f18, f19, b20 = (by.get(n, {}) for n in ("prod-api-02", "dev-flaky-18", "staging-flaky-19", "prod-batch-20"))
    dup_in = sum(_first_int(x["detail"].replace("re-sent", "")) for x in faults("duplicate_block"))
    oor_in = sum(_sum_ints(x["detail"]) for x in faults("out_of_range"))
    flat_in = sum(_first_int(x["detail"].split(":")[-1]) for x in faults("flatline_48h"))
    gap_rows = sum(_first_int(x["detail"]) for x in faults("gap_6h"))
    return [
        {"id": "E1", "fault": "6-hour monitoring gap", "where": names("gap_6h"), "injected": f"{gap_rows} rows",
         "detected": f"longest gap {api02.get('longest_gap_hours', 0)} h",
         "handling": "kept as missing, never 0; not called idle", "ok": api02.get("longest_gap_hours", 0) >= 6},
        {"id": "E2", "fault": "Duplicate timestamps (agent re-send)", "where": names("duplicate_block"),
         "injected": f"{dup_in} rows", "detected": f"{t['duplicates']} removed", "handling": "de-duplicated, first kept",
         "ok": t["duplicates"] == dup_in},
        {"id": "E3", "fault": "CPU outside 0–100%", "where": names("out_of_range"), "injected": f"{oor_in} values",
         "detected": f"{t['out_of_range']} dropped", "handling": "set to missing", "ok": t["out_of_range"] == oor_in},
        {"id": "E4", "fault": "Rows out of order", "where": names("out_of_order"),
         "injected": f"{len(faults('out_of_order'))} blocks of 20", "detected": f"{t['out_of_order']} inversions",
         "handling": "sorted", "ok": t["out_of_order"] > 0},
        {"id": "E5", "fault": "Reboot gaps + random drops", "where": f"{len(faults('reboot_gap'))} VMs + all",
         "injected": f"{len(faults('reboot_gap'))} × 20 min, 0.5% drops", "detected": "tolerated",
         "handling": "coverage stays ≥ 95%", "ok": True},
        {"id": "E6", "fault": "Coverage ~70%", "where": names("missing_30"), "injected": "30% of hours",
         "detected": pct(f18.get("coverage")), "handling": "excluded: below the 80% gate",
         "ok": (f18.get("coverage") or 1) < 0.8},
        {"id": "E7", "fault": "Coverage ~88%", "where": names("missing_12"), "injected": "12% of hours",
         "detected": pct(f19.get("coverage")), "handling": "evaluated, confidence Medium",
         "ok": 0.8 <= (f19.get("coverage") or 0) < 0.95},
        {"id": "E8", "fault": "Stuck agent (0.0 for 48 h)", "where": names("flatline_48h"), "injected": f"{flat_in} rows",
         "detected": f"{t['flatline_slots']} slots", "handling": "flatline → missing, so it never looks idle",
         "ok": t["flatline_slots"] >= flat_in},
        {"id": "E9", "fault": "Gap on the peak window", "where": names("peak_gap"),
         "injected": (faults("peak_gap")[0]["detail"].split(" (")[0] if faults("peak_gap") else "—"),
         "detected": f"peak-hour coverage {(b20.get('peak_window_coverage') or 0) * 100:.0f}%",
         "handling": "flagged: peak hours under-observed", "ok": (b20.get("peak_window_coverage") or 1) < 0.5},
        {"id": "E10", "fault": "Irregular timestamps (05:03)", "where": names("ts_jitter"), "injected": "1 day offset +3 min",
         "detected": f"{t['irregular_ts']} snapped", "handling": "floored to the 5-minute grid", "ok": t["irregular_ts"] > 0},
        {"id": "D9", "fault": "Metrics without inventory", "where": ", ".join(x["name"] for x in doc["not_in_inventory"]),
         "injected": "1 series", "detected": f"{len(doc['not_in_inventory'])} found",
         "handling": "listed; never priced or sized", "ok": len(doc["not_in_inventory"]) == 1},
    ]


def data_quality(st):
    rows = [dq_row(st, rid) for rid in st.inv.index if rid in st.cleaned.series]
    rows += [dq_row(st, rid) for rid in st.cleaned.strays]
    faults = [{"resource_id": r.resource_id, "name": r.name, "fault": r.fault, "detail": r.detail}
              for r in st.ds.faults.itertuples()]
    counts = st.ds.faults.groupby("fault").size().to_dict()
    no_metrics = [{"resource_id": rid, "name": r["name"], "state": r["state"]} for rid, r in st.inv.iterrows()
                  if r["type"] in ("vm", "volume") and rid not in st.cleaned.series]
    totals = {k: int(sum(d[k] for d in rows)) for k in
              ("rows_raw", "duplicates", "out_of_range", "out_of_order", "irregular_ts", "flatline_slots")}
    totals["metric_rows"] = int(len(st.ds.metrics))
    doc = {"resources": rows, "faults": faults, "fault_counts": {k: int(v) for k, v in counts.items()},
           "not_in_inventory": [{"resource_id": rid, "name": rid} for rid in st.cleaned.strays],
           "no_metrics": no_metrics, "totals": totals}
    doc["checks"] = dq_checks(doc)
    return doc


# ---- E11 assumptions ----------------------------------------------------------------------------

def _fill(template, cfg):
    import re

    def sub(m):
        v = cfg.get(m.group(1))
        return format(v, m.group(2)[1:]) if m.group(2) else str(v)
    return re.sub(r"\{([\w.]+)(:[^}]*)?\}", sub, template)


def assumptions(st):
    cfg, ds = st.cfg, st.ds
    dates = sorted(ds.billing["date"].unique())
    pricing = [{"item": r.item, "kind": r.kind, "vcpu": _plain(r.vcpu), "ram_gb": _plain(r.ram_gb),
                "bandwidth_mbps": _plain(r.bandwidth_mbps), "monthly_inr": int(r.monthly_inr), "unit": r.unit,
                "basis": r.basis} for r in ds.pricing.itertuples()]
    thresholds = []
    for row in cfg.raw["assumptions_table"]:
        why = row.get("why") or cfg.raw[row["why_from"].split(".")[0]][row["why_from"].split(".")[1]]["why"]
        thresholds.append({"name": row["name"], "value": _fill(row["value"], cfg), "why": why})
    carbon = cfg.raw["carbon"]
    switches = [
        {"name": "stopped_vm_billed", "value": cfg.get("billing.stopped_vm_billed"), "why": cfg.raw["billing"]["stopped_vm_billed"]["why"]},
        {"name": "hours_per_month", "value": cfg.get("billing.hours_per_month"), "why": "Monthly price ÷ 730 = hourly"},
        {"name": "gst", "value": "excluded", "why": "Prices are ex-GST"},
        {"name": "carbon_coefficients", "value": "placeholder" if carbon["placeholder"] else "measured",
         "why": carbon["source"]},
    ]
    presets = [{"id": k, "label": v["label"], "percentile": f"p{v['pct_prod']:g} prod / p{v['pct_nonprod']:g} non-prod",
                "cpu_target": f"{v['cpu_target_prod']}% / {v['cpu_target_nonprod']}%",
                "replay_limit": f"{v['replay_limit_prod']} / {v['replay_limit_nonprod']} min"}
               for k, v in cfg.raw["presets"].items() if v.get("enabled")]
    types = st.inv["type"].value_counts().to_dict()
    return {"data_window": data_window(cfg),
            "billing_window": {"start": f"{pd.Timestamp(dates[0]):%Y-%m-%d}", "end": f"{pd.Timestamp(dates[-1]):%Y-%m-%d}"},
            "counts": {"vm": int(types.get("vm", 0)), "volume": int(types.get("volume", 0)), "ip": int(types.get("ip", 0)),
                       "metric_rows": int(len(ds.metrics))},
            "pricing": pricing, "thresholds": thresholds, "switches": switches, "presets": presets}


# ---- data-quality row (E10, also embedded in E2) ----------------------------------------------

def dq_row(st, rid):
    s = st.cleaned.series.get(rid) or st.cleaned.stray_series.get(rid)
    if s is None:
        return None
    rep = s.report
    in_inv = rid in st.inv.index
    f = st.features.get(rid) or {}
    return {"resource_id": rid, "name": st.inv.loc[rid, "name"] if in_inv else rid, "type": s.kind,
            "in_inventory": in_inv, "rows_raw": rep["rows_in"], "irregular_ts": rep["snapped"],
            "out_of_order": rep["reordered"], "duplicates": rep["duplicates_removed"],
            "out_of_range": rep["out_of_range_nulled"], "flatline_slots": rep["flatline_slots"],
            "expected_slots": rep["expected_slots"], "coverage": rep["coverage"],
            "peak_window_coverage": rep["peak_window_coverage"] if s.kind == "vm" else None,
            "days_of_data": f.get("days_of_data", int(len(np.unique(np.flatnonzero(~np.isnan(s.primary)) // 288)))),
            "longest_gap_hours": round(rep["longest_gap_slots"] / SLOTS_PER_HOUR, 1), "gaps": rep["gaps"]}
