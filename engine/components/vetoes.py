"""CP6 - vetoes: any one non-CPU signal blocks shrinking. Evaluated for shrink-considered VMs only.
All that fire are recorded; assemble picks the most specific (leak > memory > IOPS > network > growth)."""
from ..evidence import days_to
from .base import P, finding, trace_only

C = "vetoes"


def _reserved(ctx, r):
    ev = r.ev
    return ev["mem_mean"] >= ctx.cfg("vetoes.reserved_mem_level") and ev["mem_std"] < ctx.cfg("vetoes.reserved_mem_std")


def _leak(ctx, r):
    """Checked on EVERY compute VM: a leaking VM's memory percentiles are an artefact of its restart cycle,
    so no sizing decision (down or up) is trustworthy until it is fixed."""
    ev, lim = r.ev, ctx.cfg("vetoes.leak_min_resets")
    return (finding(C, "VETO_LEAK", "reject", "memory sawtooth resets", ev["leak_resets"], lim,
                    message=f"{ev['leak_resets']} sharp memory drops: leak + restarts suspected")
            if ev["leak_resets"] >= lim else trace_only(C, "memory sawtooth resets", ev["leak_resets"], lim, True))


def _fixed(ctx, r, growth_needs_p):
    cfg, ev = ctx.cfg, r.ev
    out = [_leak(ctx, r)]
    if not r.shrink_considered:              # capacity vetoes only matter for VMs someone would shrink
        return out
    memp, lim = P(r, cfg, "mem"), cfg("vetoes.mem_p99")
    if _reserved(ctx, r):
        out.append(trace_only(C, "memory at sizing percentile (reserved heap -> pattern)", memp, lim, True))
    else:
        out.append(finding(C, "VETO_MEMORY", "reject", "memory at sizing percentile", memp, lim,
                           message=f"memory-bound: {memp:.0f}%") if memp > lim
                   else trace_only(C, "memory at sizing percentile", memp, lim, True))
    v, lim = ev["iops_pct_p95"], cfg("vetoes.iops_p95")
    out.append(finding(C, "VETO_IOPS", "reject", "IOPS p95 % of provisioned", v, lim, message="disk-bound")
               if v == v and v > lim else trace_only(C, "IOPS p95 % of provisioned", v, lim, True))
    v, lim = ev["net_pct_p95"], cfg("vetoes.net_p95")
    out.append(finding(C, "VETO_NETWORK", "reject", "network p95 % of bandwidth", v, lim,
                       message="network is the workload") if v == v and v > lim
               else trace_only(C, "network p95 % of bandwidth", v, lim, True))
    tr = ev["trend"]
    d85, lim = days_to(tr, cfg("vetoes.growth_target")), cfg("vetoes.growth_horizon_days")
    sig = (tr["p"] < cfg("vetoes.growth_pvalue")) if growth_needs_p else True
    out.append(finding(C, "VETO_GROWTH", "reject", "days until CPU reaches 85%", d85, lim,
                       message=f"growing {tr['slope']:.2f} points/day") if d85 < lim and sig
               else trace_only(C, "days until CPU reaches 85%", d85, lim, True))
    return out


def a_fixed(ctx, r):
    """PLAN.md 7 thresholds; growth from the raw slope."""
    r.findings += _fixed(ctx, r, growth_needs_p=False)


def b_fixed_sig(ctx, r):
    """a, but growth must also be statistically significant (p < 0.05)."""
    r.findings += _fixed(ctx, r, growth_needs_p=True)


def c_any70(ctx, r):
    """One rule: any of memory / IOPS / network above 70% vetoes (no leak or reserved-heap handling)."""
    cfg, ev = ctx.cfg, r.ev
    if not r.shrink_considered:
        return
    vals = {"VETO_MEMORY": P(r, cfg, "mem"), "VETO_IOPS": ev["iops_pct_p95"], "VETO_NETWORK": ev["net_pct_p95"]}
    lim = cfg("vetoes.mem_p99")
    for code, v in vals.items():
        if v == v and v > lim:
            r.findings.append(finding(C, code, "reject", f"{code} metric", v, lim))
        else:
            r.findings.append(trace_only(C, f"{code} metric", v, lim, True))


CANDIDATES = {
    "a_fixed": {"fn": a_fixed, "params": 7, "prior": 7, "desc": "leak >= 3 resets, memory > 70, IOPS > 70, network > 60, growth to 85% < 60 d"},
    "b_fixed_sig": {"fn": b_fixed_sig, "params": 8, "prior": 9, "desc": "a + growth only if the trend is significant (p < 0.05)"},
    "c_any70": {"fn": c_any70, "params": 1, "prior": 4, "desc": "any metric > 70% vetoes"},
}
