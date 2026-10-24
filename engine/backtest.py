"""Out-of-sample safety: decide on days 0..split-1, then replay the recommendations on the held-out days.

A recommendation is UNSAFE if, on the held-out days:
  resize/upsize  the target plan's replayed CPU exceeds the overload line for longer than the budget, or memory > cap
  stop           the VM was active (any day's CPU p95 above the idle line)
  schedule       real activity (CPU above risk.schedule_active_cpu) fell inside an off window
Resources whose held-out days contain an incident (a level shift > anomaly ratio vs the decision window), or that
were resized/stopped/created during the held-out days, are excluded: an alert supersedes any recommendation."""
import numpy as np

from . import pipeline as PL
from .replay import budget_minutes


def _test_arrays(ctx_full_clean, rid, split_slots):
    arr, _ = ctx_full_clean[rid]
    return {k: v[split_slots:] for k, v in arr.items()}, {k: v[:split_slots] for k, v in arr.items()}


def run(data, cfg, sel):
    split = int(cfg("backtest.split_day"))
    ctx, res = PL.run(data, cfg, sel, window_days=split)
    _, cleaned = PL._cleaned(ctx)
    spd = cfg.t("slots_per_day")
    split_slots = split * spd
    test_days = data.n_days - split
    out = {"unsafe": 0, "evaluated": 0, "excluded": [], "details": []}
    for r in res:
        if r.verdict not in ("recommend", "upsize") or r.type != "vm" or r.id not in cleaned:
            continue
        test, train = _test_arrays(cleaned, r.id, split_slots)
        inc = np.nanmean(test["cpu_pct"].reshape(-1, spd), axis=1)
        base = np.nanmean(train["cpu_pct"])
        changed = any(ctx.ts_after_now(r.inv.get(k)) for k in ("last_resized_at", "stopped_since", "created_at"))
        if changed or (base > 0 and np.nanmax(inc) > cfg("gates_data.anomaly_ratio") * base):
            out["excluded"].append(r.id)
            continue
        out["evaluated"] += 1
        bad = []
        for act in r.actions:
            if act in ("resize", "upsize"):
                cur, tgt = data.plans[r.inv["plan_id"]], data.plans[r.actions[act]["target"]]
                cpu_new = test["cpu_pct"] * cur["vcpu"] / tgt["vcpu"]
                over = np.nansum(cpu_new > cfg("sizing.overload_level")) * cfg.t("slot_minutes")
                mem_new = test["mem_pct"] * cur["ram"] / tgt["ram"]
                if over > budget_minutes(r, cfg, test_days) or np.nanmax(mem_new) > cfg("sizing.mem_cap"):
                    bad.append(f"{act}: {over:.0f} min > 90% on {r.actions[act]['target']}")
            elif act.endswith("stop"):
                with np.errstate(all="ignore"):
                    p = np.nanpercentile(test["cpu_pct"].reshape(-1, spd), cfg("candidates.offhour_percentile"), axis=1)
                if np.nanmax(p) > cfg("candidates.idle_cpu"):
                    bad.append(f"stop: active in held-out week (day p95 {np.nanmax(p):.0f}%)")
            elif act == "schedule":
                how = data.axes["slot_of_week"][split_slots:] // cfg.t("slots_per_hour")
                off = r.ev["off_hours"][how]
                active = np.nansum((test["cpu_pct"] > cfg("risk.schedule_active_cpu")) & off)
                if active > 0:
                    bad.append(f"schedule: {active} active samples inside off windows")
        if bad:
            out["unsafe"] += 1
            out["details"].append({"resource_id": r.id, "name": r.inv["name"], "problems": bad})
    return out
