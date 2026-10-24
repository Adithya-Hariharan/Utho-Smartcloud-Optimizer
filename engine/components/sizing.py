"""CP9 - sizing: pick the target plan (or prove there is none), and detect under-provisioning.

Runs for every compute VM that passed the gates. It records `r.sizing`; a resize ACTION is only created
when the candidates component marked the VM as underused (or in replay mode). For a shrink-considered VM
with no action at the end, the sizing result explains the refusal (soft reject)."""
import numpy as np

from ..replay import budget_minutes, passes, replay
from .base import P, finding, is_prod

C = "sizing"


def _target_cpu(ctx, r, plan, core_based):
    cfg = ctx.cfg
    base = cfg.preset["target_cpu_prod"] if is_prod(r) else cfg.preset["target_cpu_nonprod"]
    if not core_based:
        return base
    v = ctx.data.plans[plan]["vcpu"]
    t = (cfg("sizing.core_target_small") if v <= cfg("sizing.core_small_max") else
         cfg("sizing.core_target_medium") if v <= cfg("sizing.core_medium_max") else cfg("sizing.core_target_large"))
    return t if is_prod(r) else t + cfg("sizing.nonprod_target_bonus")


def _formula_plan(ctx, r, target_cpu):
    cfg, plans = ctx.cfg, ctx.data.plans
    cur = plans[r.inv["plan_id"]]
    need_v = cur["vcpu"] * P(r, cfg, "cpu") / target_cpu
    need_r = cur["ram"] * P(r, cfg, "mem") / cfg("sizing.target_mem")
    for p in ctx.data.plan_order:
        if plans[p]["vcpu"] >= need_v and plans[p]["ram"] >= need_r:
            return p, need_v, need_r
    return ctx.data.plan_order[-1], need_v, need_r


def _cheaper(ctx, r):
    order = ctx.data.plan_order
    cur = order.index(r.inv["plan_id"])
    lo = max(cur - int(ctx.cfg("sizing.prod_max_steps")), 0) if is_prod(r) else 0
    return order[lo:cur]                     # ascending price


def _growth(ctx, r):
    tr = r.ev["trend"]
    cfg = ctx.cfg
    if tr["p"] < cfg("sizing.trend_pvalue") and tr["slope"] > 0 and tr["last"] > 0:
        return (tr["last"] + tr["slope"] * cfg("sizing.forward_days")) / tr["last"]
    return 1


def _upsize(ctx, r, mode):
    cfg, ev = ctx.cfg, r.ev
    if not (ev["mean"] >= cfg("peaks.looks_wasteful_mean")):
        return False                          # a VM idle on average that touches 90% is batchy, not starved
    level = cfg("sizing.upsize_level")
    sig = ev["p99"] if mode in ("a", "b") else ev["second_day_peak"]
    if not (sig > level):
        return False
    order = ctx.data.plan_order
    bigger = order[order.index(r.inv["plan_id"]) + 1:]
    target = bigger[-1] if bigger else r.inv["plan_id"]
    for p in bigger:
        if mode == "a":
            fp, _, _ = _formula_plan(ctx, r, _target_cpu(ctx, r, p, False))
            if ctx.data.plans[p]["price"] >= ctx.data.plans[fp]["price"]:
                target = p
                break
        else:
            rp = replay(ctx, r, p)
            if passes(ctx, r, rp, _target_cpu(ctx, r, p, mode == "d"), use_second_peak=mode != "b"):
                target = p
                break
    r.sizing = {"kind": "upsize", "target": target, "replay": replay(ctx, r, target)}
    r.actions["upsize"] = {"target": target}
    r.findings.append(finding(C, "UNDER_PROVISIONED", "upsize", "CPU p99" if mode in ("a", "b") else "2nd-busiest day peak",
                              sig, level, message=f"saturated: upsize to {target}"))
    return True


def _resize(ctx, r, mode):
    plans = ctx.data.plans
    cur = r.inv["plan_id"]
    tcpu = _target_cpu(ctx, r, cur, False)
    fplan, need_v, need_r = _formula_plan(ctx, r, tcpu)
    formula_cheaper = plans[fplan]["price"] < plans[cur]["price"]
    allowed = _cheaper(ctx, r)
    mem_blocked = not any(plans[p]["ram"] >= need_r for p in ctx.data.plan_order
                          if plans[p]["price"] < plans[cur]["price"])
    attempts, chosen = [], None
    if mode == "a":
        if formula_cheaper:
            chosen = fplan if fplan in allowed else (allowed[0] if allowed else None)
    elif mode == "b":
        if formula_cheaper:
            start = fplan if fplan in allowed else (allowed[0] if allowed else None)
            if start:
                for p in allowed[allowed.index(start):]:
                    rp = replay(ctx, r, p)
                    ok = passes(ctx, r, rp, tcpu, use_second_peak=False)
                    attempts.append(_attempt(rp, ok))
                    if ok:
                        chosen = p
                        break
    else:
        g = _growth(ctx, r) if mode == "d" else 1
        for p in allowed:
            rp = replay(ctx, r, p, growth=g)
            ok = passes(ctx, r, rp, _target_cpu(ctx, r, p, mode == "d"))
            attempts.append(_attempt(rp, ok))
            if ok:
                chosen = p
                break
    r.sizing = {"kind": "resize", "formula_plan": fplan, "need_vcpu": need_v, "need_ram": need_r,
                "target": chosen, "attempts": attempts, "target_cpu": tcpu,
                "replay": replay(ctx, r, chosen) if chosen else None,
                "mem_blocked": mem_blocked,
                # NO_CHEAPER_PLAN only when MEMORY rules out every cheaper plan; when CPU is the limit the honest
                # explanation is the replay evidence (an average-based cut would overload)
                "fail_code": None if chosen else ("NO_CHEAPER_PLAN" if mem_blocked else "PEAK_REPLAY_FAILED"),
                "naive": _naive(ctx, r)}
    if attempts:
        worst = attempts[-1]
        r.findings.append({"comp": C, "code": None, "kind": "info", "check": f"Peak Replay on {worst['plan']}",
                           "value": worst["minutes_above_90"], "threshold": budget_minutes(r, ctx.cfg, r.ev["n_slots"] / ctx.cfg.t("slots_per_day")),
                           "result": "pass" if worst["passed"] else "fail", "message": ""})


def _naive(ctx, r):
    """What an average-based tool would do: size so the MEAN sits at our CPU target (schema evidence.naive)."""
    plans, cur = ctx.data.plans, r.inv["plan_id"]
    need = plans[cur]["vcpu"] * r.ev["mean"] / _target_cpu(ctx, r, cur, False)
    for p in ctx.data.plan_order:
        if plans[p]["vcpu"] >= need:
            if plans[p]["price"] < plans[cur]["price"]:
                rp = replay(ctx, r, p)
                return {"method": "mean CPU at the CPU target", "target_plan": p,
                        "saving_inr": round(plans[cur]["price"] - plans[p]["price"]),
                        "replay_minutes_above_90": round(rp["overload_minutes"])}
            return None
    return None


def _attempt(rp, ok):
    return {"plan": rp["plan"], "minutes_above_90": round(rp["overload_minutes"]), "max_cpu_pct": _r(rp["max_cpu_pct"]),
            "max_mem_pct": _r(rp["max_mem_pct"]), "passed": ok}


def _r(v):
    return None if v is None or not np.isfinite(v) else round(float(v), 1)


def _run(ctx, r, mode):
    if _upsize(ctx, r, mode):
        return
    _resize(ctx, r, mode)


def a_formula(ctx, r):
    """Percentile formula only (no replay)."""
    _run(ctx, r, "a")


def b_formula_replay(ctx, r):
    """PLAN.md 7: formula target, then Peak Replay; on failure try the next bigger cheaper plan."""
    _run(ctx, r, "b")


def c_replay_search(ctx, r):
    """Replay-driven: cheapest allowed plan whose replay passes (overload budget, memory cap/target, 2nd-day peak)."""
    _run(ctx, r, "c")


def d_replay_core(ctx, r):
    """c + CPU target by core count (Erlang-C rule of thumb) + forward replay under a significant trend."""
    _run(ctx, r, "d")


CANDIDATES = {
    "a_formula": {"fn": a_formula, "params": 3, "prior": 4, "desc": "percentile formula, round up, prod one step; no replay"},
    "b_formula_replay": {"fn": b_formula_replay, "params": 6, "prior": 7, "desc": "PLAN.md 7: formula then Peak Replay gate"},
    "c_replay_search": {"fn": c_replay_search, "params": 7, "prior": 8, "desc": "cheapest plan whose replay passes (incl. 2nd-busiest-day peak)"},
    "d_replay_core": {"fn": d_replay_core, "params": 12, "prior": 7, "desc": "c + core-count targets + forward replay under significant growth"},
}
