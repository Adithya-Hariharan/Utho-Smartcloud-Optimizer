"""POST /api/whatif: "turn <env> off <HH:MM-HH:MM> (and weekends)": saving and the VMs it would disrupt.

Rules follow the frontend reference (docs/reference/mock_engine.py run_whatif). Candidates: VMs that are running,
have metrics and have a catalogue plan. An off hour is busy when the VM's CPU (max over weeks of the hourly p95,
IST hour-of-week) is at least `whatif.busy_cpu_pct`.
"""
import re

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ENVS = {"dev", "staging", "prod", "nonprod"}


class WhatIfError(ValueError):
    pass


def parse_off(off):
    m = re.fullmatch(r"(\d{2}):00-(\d{2}):00", off or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 23:
        raise WhatIfError("off must be 'HH:00-HH:00' (whole hours, IST)")
    return int(m.group(1)), int(m.group(2))


def off_mask(start, end, weekends):
    out = []
    for i in range(168):
        d, h = divmod(i, 24)
        if weekends and d >= 5:
            out.append(True)
        elif start == end:
            out.append(False)
        else:
            out.append(start <= h < end if start < end else (h >= start or h < end))
    return out


def describe_hours(idx):
    per_day = {}
    for i in idx:
        per_day.setdefault(i // 24, []).append(i % 24)
    by_range = {}
    for d, hours in per_day.items():
        ranges, s0, prev = [], hours[0], hours[0]
        for h in hours[1:] + [-1]:
            if h != prev + 1:
                ranges.append(f"{s0:02d}:00–{(prev + 1) % 24:02d}:00")
                s0 = h
            prev = h
        by_range.setdefault(", ".join(ranges).replace("00:00–00:00", "all day"), []).append(d)
    parts = []
    for r, days in by_range.items():
        consecutive = all(days[i] == days[i - 1] + 1 for i in range(1, len(days)))
        label = DAYS[days[0]] if len(days) == 1 else (
            f"{DAYS[days[0]]}–{DAYS[days[-1]]}" if consecutive else ", ".join(DAYS[x] for x in days))
        parts.append(f"{label} {r}")
    return "; ".join(parts)


def candidates(st):
    out = []
    for rid, row in st.inv.iterrows():
        f = st.features.get(rid) or {}
        if row["type"] == "vm" and row["state"] == "running" and rid in st.cleaned.series \
                and f.get("how_busy") is not None and row["plan_id"] in st.cfg.plans:
            out.append({"resource_id": rid, "name": row["name"], "env": row["env"] or "untagged",
                        "team": row["owner_team"] or "unowned", "plan_id": row["plan_id"],
                        "compute_inr": int(st.cfg.plans[row["plan_id"]]["monthly_inr"]),
                        "optimize_policy": row["optimize_policy"], "tags": list(row["tags_list"]),
                        "how_busy": f["how_busy"]})
    return out


def run_whatif(st, env, off, weekends):
    if env not in ENVS:
        raise WhatIfError(f"env must be one of {sorted(ENVS)}")
    start, end = parse_off(off)
    busy_pct = st.cfg.get("whatif.busy_cpu_pct")
    mask = off_mask(start, end, weekends)
    n_off = sum(mask)
    rows = []
    for vm in candidates(st):
        if not (vm["env"] in ("dev", "staging") if env == "nonprod" else vm["env"] == env):
            continue
        saving = round(vm["compute_inr"] * n_off / 168)
        base = {k: vm[k] for k in ("resource_id", "name", "env", "team", "plan_id")}
        if vm["optimize_policy"] == "no_schedule" or "keep_running" in vm["tags"]:
            rows.append({**base, "status": "excluded", "saving_inr": 0, "busy_off_hours": 0,
                         "note": "keep_running tag" if "keep_running" in vm["tags"] else "policy no_schedule"})
            continue
        busy = [i for i, o in enumerate(mask) if o and (vm["how_busy"][i] or 0) >= busy_pct]
        if not busy:
            rows.append({**base, "status": "safe", "saving_inr": saving, "busy_off_hours": 0,
                         "note": "quiet in every week of the window"})
        else:
            note = (f"busy around the clock: CPU ≥ {busy_pct}% in {len(busy)} of {n_off} off hours"
                    if len(busy) / max(n_off, 1) > 0.8 else f"busy {describe_hours(busy)}")
            rows.append({**base, "status": "disrupted", "saving_inr": saving, "busy_off_hours": len(busy), "note": note})
    order = {"disrupted": 0, "safe": 1, "excluded": 2}
    rows.sort(key=lambda r: (order[r["status"]], -r["saving_inr"]))
    return {"input": {"env": env, "off": off, "weekends": weekends}, "off_hours_per_week": n_off, "rows": rows,
            "safe_saving_inr": sum(r["saving_inr"] for r in rows if r["status"] == "safe"),
            "blind_saving_inr": sum(r["saving_inr"] for r in rows if r["status"] != "excluded"),
            "disrupted": sum(r["status"] == "disrupted" for r in rows),
            "excluded": sum(r["status"] == "excluded" for r in rows)}
