"""CP2 - data-sufficiency gates: enough history, a stable machine, enough coverage, no incident in progress."""
from .base import age_days, finding, trace_only

C = "gates_data"


def _common(ctx, r):
    cfg, ev = ctx.cfg, r.ev
    out = []
    lim = cfg("gates_data.min_history_days")
    days = ev["days_of_data"]
    out.append(finding(C, "HISTORY_TOO_SHORT", "exclude", "days of data", days, lim,
                       message="percentiles on under 14 days are unreliable") if days < lim
               else trace_only(C, "days of data", days, lim, True))
    resized = r.inv.get("last_resized_at") or ""
    if resized:
        age = age_days(resized, ctx.now)
        lim_r = cfg("gates_data.recent_resize_days")
        if 0 <= age < lim_r:
            out.append(finding(C, "RECENTLY_RESIZED", "exclude", "days since resize", age, lim_r,
                               message="older data describes a different machine"))
    cov, lim_c = ev["coverage"], cfg("gates_data.min_coverage")
    out.append(finding(C, "LOW_COVERAGE", "exclude", "coverage", cov, lim_c, message="insufficient data quality")
               if cov < lim_c else trace_only(C, "coverage", cov, lim_c, True))
    if lim_c <= cov < cfg("gates_data.medium_coverage"):
        r.flags.append({"code": "MEDIUM_COVERAGE", "message": f"coverage {cov:.0%}: evaluated with lower confidence"})
    shift, lim_s = ev["shift_up"], cfg("gates_data.anomaly_ratio")
    if shift == shift and shift > lim_s:
        out.append(finding(C, "ACTIVE_ANOMALY", "exclude", "last 48 h mean / earlier mean", shift, lim_s,
                           message="incident in progress: never size on an anomaly"))
    else:
        out.append(trace_only(C, "last 48 h mean / earlier mean", shift, lim_s, True))
    return out


def a_basic(ctx, r):
    """history + recent resize + coverage + anomaly."""
    r.findings += _common(ctx, r)


def b_min_bucket(ctx, r):
    """a + flag if ANY hour-of-week bucket is under-observed."""
    r.findings += _common(ctx, r)
    v, lim = r.ev["min_bucket_coverage"], ctx.cfg("gates_data.bucket_coverage_min")
    r.findings.append(finding(C, "PEAK_UNDER_OBSERVED", "data_flag", "min hour-of-week coverage", v, lim,
                              message="some hours of the week were barely observed") if v < lim
                      else trace_only(C, "min hour-of-week coverage", v, lim, True))


def c_peak_hours(ctx, r):
    """a + flag if the VM's own busiest hours were under-observed."""
    r.findings += _common(ctx, r)
    v, lim = r.ev["peak_hours_coverage"], ctx.cfg("gates_data.peak_coverage_min")
    r.findings.append(finding(C, "PEAK_UNDER_OBSERVED", "data_flag", f"coverage of peak hours {r.ev['peak_hours']}",
                              v, lim, message="the peak window itself was mostly unobserved") if v < lim
                      else trace_only(C, f"coverage of peak hours {r.ev['peak_hours']}", v, lim, True))


CANDIDATES = {
    "a_basic": {"fn": a_basic, "params": 4, "prior": 7, "desc": "history >= 14 d, no resize < 14 d, coverage >= 80%, no 3x level shift"},
    "b_min_bucket": {"fn": b_min_bucket, "params": 5, "prior": 7, "desc": "a + flag if any hour-of-week bucket < 50% observed"},
    "c_peak_hours": {"fn": c_peak_hours, "params": 6, "prior": 9, "desc": "a + flag if the VM's two busiest hours are < 50% observed"},
}
