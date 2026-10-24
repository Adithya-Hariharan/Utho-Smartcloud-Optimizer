"""CP8 - candidate actions for compute VMs: idle (stop), underused (resize, sized by CP9), off-hours (schedule).
Candidates are bundles because the three sub-decisions share evidence; each bundle is one coherent logic."""
import numpy as np

from .base import P, finding, has_tag, is_prod, trace_only

C = "candidates"
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _idle(ctx, r, mode):
    cfg, ev = ctx.cfg, r.ev
    cpu_ok = P(r, cfg, "cpu") < cfg("candidates.idle_cpu")
    if mode == "cpu":
        return cpu_ok, f"CPU {P(r, cfg, 'cpu'):.1f}%"
    mem_ok = not (P(r, cfg, "mem") >= cfg("candidates.idle_mem"))
    if mode == "abs":
        net_ok = ev["net_mb_per_h"] < cfg("candidates.idle_net_mb_per_h")
        io_ok = ev["iops_p95"] < cfg("candidates.idle_iops_abs")
    else:
        net_ok = ev["net_pct_mean"] < cfg("candidates.idle_net_pct_bw")
        io_ok = ev["iops_pct_p95"] < cfg("candidates.idle_iops_pct")
    return cpu_ok and mem_ok and net_ok and io_ok, \
        f"CPU {P(r, cfg, 'cpu'):.1f}%, mem {P(r, cfg, 'mem'):.0f}%, net {ev['net_pct_mean']:.3f}% bw, IO {ev['iops_pct_p95']:.2f}%"


def _blocks(off, min_len):
    """Cyclic runs of True in the 168-hour week -> [(start_hour, length)]."""
    n = len(off)
    if off.all():
        return [(0, n)]
    if not off.any():
        return []
    start = int(np.flatnonzero(~off)[0])
    rot = np.roll(off, -start)
    out, i = [], 0
    while i < n:
        if rot[i]:
            j = i
            while j < n and rot[j]:
                j += 1
            if j - i >= min_len:
                out.append(((i + start) % n, j - i))
            i = j
        else:
            i += 1
    return out


def _windows(blocks, buffer_h, cfg):
    hpd = cfg.t("hours_per_day")
    wins = []
    for s, length in blocks:
        end = s + length - buffer_h
        e_day, e_h = int(end // hpd) % len(DAYS), end % hpd
        wins.append({"days": [DAYS[int(s // hpd) % len(DAYS)], DAYS[e_day]],
                     "start": f"{int(s % hpd):02d}:00",
                     "end": f"{int(e_h):02d}:{int(round((e_h % 1) * cfg.t('minutes_per_hour'))):02d}"})
    return wins


def _offhours(ctx, r, mode):
    cfg, ev = ctx.cfg, r.ev
    off = ev["off_hours"]
    hpd = cfg.t("hours_per_day")
    if mode == "template":
        s, e = cfg("candidates.template_off_start_h"), cfg("candidates.template_off_end_h")
        want = np.array([(d >= cfg.t("saturday_index")) or (h >= s or h < e)
                         for d in range(len(DAYS)) for h in range(hpd)])
        if (off | ~want).all():
            blocks = _blocks(want, 1)
            return sum(b[1] for b in blocks), _windows(blocks, 0, cfg), blocks
        return 0, [], []
    blocks = _blocks(off, int(cfg("candidates.offhours_min_block_h")))
    buf = cfg("candidates.wake_buffer_min") / cfg.t("minutes_per_hour") if mode == "buffer" else 0
    hours = sum(max(b[1] - buf, 0) for b in blocks)
    return hours, _windows(blocks, buf, cfg), blocks


def _run(ctx, r, idle_mode, off_mode, underused_mode):
    cfg = ctx.cfg
    idle, desc = _idle(ctx, r, idle_mode)
    if idle:
        if is_prod(r):
            r.findings.append(finding(C, "IDLE_PROD", "flag", "idle test", desc, "all below idle lines",
                                      message="idle production VM: review with owner, never auto-stop"))
        else:
            act = "snapshot+stop" if has_tag(r, "stateful") else "stop"
            r.actions[act] = {"reason": "idle"}
            r.findings.append(finding(C, "IDLE", "recommend", "idle test", desc, "all below idle lines",
                                      message="idle for 30 days: stop (snapshot first if stateful), delete after 14 days"))
        return
    r.findings.append(trace_only(C, "idle test", desc, "all below idle lines", True))
    cpuP, memP = P(r, cfg, "cpu"), P(r, cfg, "mem")
    if underused_mode == "replay":
        r.underused = "replay"
    else:
        r.underused = cpuP < cfg("candidates.underused_cpu") and memP < cfg("candidates.underused_mem")
        r.findings.append(trace_only(C, "underused (CPU P < 40 and mem P < 50)", f"{cpuP:.1f} / {memP:.1f}",
                                     f"{cfg('candidates.underused_cpu')} / {cfg('candidates.underused_mem')}", not r.underused))
    blocked = is_prod(r) or has_tag(r, "keep_running") or (r.inv.get("optimize_policy") or "") == "no_schedule"
    if blocked:
        return
    hours, wins, _ = _offhours(ctx, r, off_mode)
    lim = cfg("candidates.offhours_min_week_h")
    if hours >= lim:
        r.schedule = {"timezone": ctx.cfg.meta("timezone"), "off_hours_per_week": round(hours, 1),
                      "on_hours_per_week": round(cfg.t("hours_per_week") - hours, 1), "windows": wins,
                      "busy_hours_excluded": []}
        r.actions["schedule"] = {"off_hours": hours}
        r.findings.append(finding(C, "OFF_HOURS", "recommend", "consistently idle hours per week", hours, lim,
                                  message=f"off {hours:.0f} h/week in {len(wins)} window(s)"))
    else:
        r.findings.append(trace_only(C, "consistently idle hours per week", hours, lim, True))


def a_simple(ctx, r):
    """idle on CPU only; underused by percentile; fixed 'off 20:00-08:00 + weekends' template."""
    _run(ctx, r, "cpu", "template", "pct")


def b_plan7(ctx, r):
    """PLAN.md 7: idle on 4 metrics with absolute lines; underused by percentile; off-hours from the weekly profile."""
    _run(ctx, r, "abs", "profile", "pct")


def c_relative(ctx, r):
    """b with idle lines relative to the plan (bandwidth / provisioned IOPS) and a 30-min wake buffer."""
    _run(ctx, r, "rel", "buffer", "pct")


def d_relative_replay(ctx, r):
    """c, but 'underused' = sizing found a cheaper plan that passes replay (no 40% cliff)."""
    _run(ctx, r, "rel", "buffer", "replay")


CANDIDATES = {
    "a_simple": {"fn": a_simple, "params": 4, "prior": 4, "desc": "idle on CPU only; percentile underused; fixed 20:00-08:00 + weekend template"},
    "b_plan7": {"fn": b_plan7, "params": 8, "prior": 7, "desc": "4-metric idle with absolute lines; percentile underused; weekly-profile off-hours"},
    "c_relative": {"fn": c_relative, "params": 9, "prior": 8, "desc": "4-metric idle relative to plan size; percentile underused; profile + 30-min wake buffer"},
    "d_relative_replay": {"fn": d_relative_replay, "params": 8, "prior": 8, "desc": "c with underused decided by replay (no cliff)"},
}
