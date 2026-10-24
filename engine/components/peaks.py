"""CP4 - peak characterisation: does this 'looks wasteful' VM have a peak that recurs?
Only evaluated for shrink-considered VMs (an average-based tool would cut them)."""
from .base import finding, trace_only

C = "peaks"


def a_p99_days(ctx, r):
    """PLAN.md 7: >= 4 days with a 30-min peak above 80% AND p99 >= 80."""
    cfg, ev = ctx.cfg, r.ev
    days, p99 = ev["peak_days"], ev["p99"]
    fire = days >= cfg("peaks.recurring_min_days") and p99 >= cfg("peaks.p99_min")
    r.findings.append(finding(C, "VETO_RECURRING_PEAK", "reject", "days with a 30-min peak > 80% (p99)",
                              f"{days} d (p99 {p99:.0f})", f">= {cfg('peaks.recurring_min_days')} d and p99 >= {cfg('peaks.p99_min')}",
                              message=f"recurring peak on {days} days, p99 {p99:.0f}%") if fire
                      else trace_only(C, "days with a 30-min peak > 80% (p99)", days, cfg("peaks.recurring_min_days"), True))


def b_daily_peaks(ctx, r):
    """Daily-peak profile only: >= 4 days whose 30-min peak exceeds 80%."""
    cfg, ev = ctx.cfg, r.ev
    days = ev["peak_days"]
    fire = days >= cfg("peaks.recurring_min_days")
    r.findings.append(finding(C, "VETO_RECURRING_PEAK", "reject", "days with a 30-min peak > 80%", days,
                              cfg("peaks.recurring_min_days"), message=f"recurring peak on {days} days") if fire
                      else trace_only(C, "days with a 30-min peak > 80%", days, cfg("peaks.recurring_min_days"), True))


def c_periodicity(ctx, r):
    """Periodicity: autocorrelation at a 24 h or 168 h lag >= 0.3 AND p99 >= 80."""
    cfg, ev = ctx.cfg, r.ev
    acf = max(x for x in (ev["acf_day"], ev["acf_week"], -1) if x == x)
    fire = acf >= cfg("peaks.autocorr_min") and ev["p99"] >= cfg("peaks.p99_min")
    r.findings.append(finding(C, "VETO_RECURRING_PEAK", "reject", "autocorrelation at 24 h / 168 h", acf,
                              cfg("peaks.autocorr_min"), message=f"periodic load (acf {acf:.2f}), p99 {ev['p99']:.0f}%")
                      if fire else trace_only(C, "autocorrelation at 24 h / 168 h", acf, cfg("peaks.autocorr_min"), True))


CANDIDATES = {
    "a_p99_days": {"fn": a_p99_days, "params": 3, "prior": 6, "desc": "PLAN.md 7: >= 4 peak days AND p99 >= 80"},
    "b_daily_peaks": {"fn": b_daily_peaks, "params": 2, "prior": 8, "desc": ">= 4 days with a 30-min peak above 80%"},
    "c_periodicity": {"fn": c_periodicity, "params": 2, "prior": 6, "desc": "autocorrelation at 24 h/168 h >= 0.3 AND p99 >= 80"},
}
