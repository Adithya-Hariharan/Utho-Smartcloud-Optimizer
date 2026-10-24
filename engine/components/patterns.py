"""CP7 - patterns that need a human: one-off peak, went quiet, reserved memory.
(PEAK_UNDER_OBSERVED comes from gates_data; IDLE_PROD from candidates.)"""
from .base import finding, trace_only

C = "patterns"


def _common(ctx, r):
    cfg, ev = ctx.cfg, r.ev
    out = []
    q, lim = ev["quiet_ratio"], cfg("patterns.quiet_ratio")
    fire = q == q and q < lim and ev["prior_mean"] >= cfg("patterns.quiet_prior_min_mean")
    # data_flag class: recent behaviour invalidates the older evidence, so it outranks even 'upsize'
    out.append(finding(C, "WENT_QUIET", "data_flag", "last-7-day mean / earlier mean", q, lim,
                       message="went quiet recently: confirm decommission") if fire
               else trace_only(C, "last-7-day mean / earlier mean", q, lim, True))
    fire = ev["mem_mean"] >= cfg("vetoes.reserved_mem_level") and ev["mem_std"] < cfg("vetoes.reserved_mem_std")
    out.append(finding(C, "RESERVED_MEMORY", "flag", "memory std at >= 75%", ev["mem_std"], cfg("vetoes.reserved_mem_std"),
                       message="memory flat and high: reserved heap? verify before cutting RAM") if fire
               else trace_only(C, "memory std at >= 75%", ev["mem_std"], cfg("vetoes.reserved_mem_std"), True))
    return out


def a_p99(ctx, r):
    """PLAN.md 7: one-off if p99 >= 80 but p99 without the busiest day < 40."""
    cfg, ev = ctx.cfg, r.ev
    fire = ev["p99"] >= cfg("patterns.oneoff_p99") and ev["p99_excl_top_day"] < cfg("patterns.oneoff_rest_max")
    r.findings.append(finding(C, "ONE_OFF_PEAK", "flag", "p99 without the busiest day", ev["p99_excl_top_day"],
                              cfg("patterns.oneoff_rest_max"), message="one event is not a pattern") if fire
                      else trace_only(C, "p99 without the busiest day", ev["p99_excl_top_day"], cfg("patterns.oneoff_rest_max"), True))
    r.findings += _common(ctx, r)


def b_daily(ctx, r):
    """Daily-peak profile: one-off if the busiest day peaks >= 80 but the 2nd busiest stays < 50."""
    cfg, ev = ctx.cfg, r.ev
    fire = ev["top_day_peak"] >= cfg("patterns.oneoff_p99") and ev["second_day_peak"] < cfg("patterns.oneoff_second_day_max")
    r.findings.append(finding(C, "ONE_OFF_PEAK", "flag", "2nd-busiest day peak", ev["second_day_peak"],
                              cfg("patterns.oneoff_second_day_max"), message="one event is not a pattern") if fire
                      else trace_only(C, "2nd-busiest day peak", ev["second_day_peak"], cfg("patterns.oneoff_second_day_max"), True))
    r.findings += _common(ctx, r)


CANDIDATES = {
    "a_p99": {"fn": a_p99, "params": 5, "prior": 7, "desc": "one-off via p99 without the top day; went quiet; reserved memory"},
    "b_daily": {"fn": b_daily, "params": 5, "prior": 8, "desc": "one-off via the daily-peak profile (2nd day < 50); went quiet; reserved memory"},
}
