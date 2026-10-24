"""Peak Replay: re-run every observed 5-minute sample on a different plan.
cpu_new(t) = cpu(t) x vcpu_old / vcpu_new  (linear scaling: stated assumption)
mem_new(t) = used_GB(t) / ram_new = mem(t) x ram_old / ram_new"""
import numpy as np

from .evidence import kth_largest, pct


def budget_minutes(r, cfg, n_days):
    per_month = cfg.preset["budget_prod"] if r.env == "prod" else cfg.preset["budget_nonprod"]
    return per_month * n_days / cfg.t("days_per_month")


def replay(ctx, r, target, cpu=None, growth=1):
    cfg = ctx.cfg
    cur, tgt = ctx.data.plans[r.inv["plan_id"]], ctx.data.plans[target]
    cpu = r.arr["cpu_pct"] if cpu is None else cpu
    k = cur["vcpu"] / tgt["vcpu"]
    cpu_new = cpu * k * growth
    mem_new = r.arr["mem_pct"] * cur["ram"] / tgt["ram"]
    over = np.nan_to_num(cpu_new > cfg("sizing.overload_level"), nan=0).astype(float)
    per_day = over.reshape(-1, cfg.t("slots_per_day")).sum(axis=1) * cfg.t("slot_minutes")
    q = cfg.preset["percentile_prod"] if r.env == "prod" else cfg.preset["percentile_nonprod"]
    return {"plan": target, "ratio": k, "overload_minutes": float(per_day.sum()), "per_day_overload": per_day,
            "max_cpu_pct": float(np.nanmax(cpu_new)) if np.isfinite(cpu_new).any() else np.nan,
            "max_mem_pct": float(np.nanmax(mem_new)) if np.isfinite(mem_new).any() else np.nan,
            "mem_p": pct(mem_new, q), "cpu_p": pct(cpu_new, q),
            "second_day_peak": kth_largest(r.ev["daily_peaks"] * k * growth, int(cfg("sizing.second_peak_rank")))}


def passes(ctx, r, rp, target_cpu, use_second_peak=True):
    cfg = ctx.cfg
    ok = (rp["overload_minutes"] <= budget_minutes(r, cfg, r.ev["n_slots"] / cfg.t("slots_per_day"))
          and not (rp["max_mem_pct"] > cfg("sizing.mem_cap"))
          and not (rp["mem_p"] > cfg("sizing.target_mem")))
    if use_second_peak:
        ok = ok and not (rp["second_day_peak"] > target_cpu)
    return bool(ok)
