"""Peak Replay (plan section 7, step 8): replay all 8,640 samples at the new size.

cpu_new(t) = cpu(t) x vcpu_old / vcpu_new ; mem_new(t) = mem(t) x ram_old / ram_new
pass if minutes(cpu_new > 90%) <= limit AND max(mem_new) <= mem cap.
"""
import numpy as np

STEP_MINUTES = 5


def project(cpu, mem, vcpu_old, ram_old, plan):
    return cpu * vcpu_old / plan.vcpu, mem * ram_old / plan.ram_gb


def attempt(cpu, mem, vcpu_old, ram_old, plan, limit_minutes, mem_cap):
    c, m = project(cpu, mem, vcpu_old, ram_old, plan)
    minutes = int(np.nansum(c > 90)) * STEP_MINUTES
    max_cpu = float(np.nanmax(c)) if np.any(~np.isnan(c)) else 0.0
    max_mem = float(np.nanmax(m)) if np.any(~np.isnan(m)) else 0.0
    return {"plan": plan.plan_id, "minutes_above_90": minutes, "max_cpu_pct": round(max_cpu, 1),
            "max_mem_pct": round(max_mem, 1), "passed": bool(minutes <= limit_minutes and max_mem <= mem_cap)}


def search(cpu, mem, vcpu_old, ram_old, start, cat, current_price, limit_minutes, mem_cap):
    """Try the target, then each bigger plan that is still cheaper than today. Returns the §4.5 replay block."""
    attempts, chosen = [], None
    for plan in [p for p in cat if p.price >= start.price and p.price < current_price]:
        a = attempt(cpu, mem, vcpu_old, ram_old, plan, limit_minutes, mem_cap)
        attempts.append(a)
        if a["passed"]:
            chosen = plan
            break
    return {"limit_minutes_above_90": limit_minutes, "mem_cap_pct": mem_cap, "attempts": attempts,
            "passed": chosen is not None, "chosen_plan": chosen.plan_id if chosen else None}, chosen


def projected_p99(cpu, vcpu_old, plan):
    c = cpu * vcpu_old / plan.vcpu
    return float(np.nanpercentile(c, 99)) if np.any(~np.isnan(c)) else None
