"""Run the engine: one selected candidate per component (see engine/selection.json).

Order: policy gates -> clean -> data gates -> non-compute -> peaks/vetoes (shrink-considered only) -> patterns
       -> candidates -> sizing -> service-group harmonisation -> actions -> risk -> cost -> finalise -> assemble
`window_days` < full window = backtest: decide as if 'now' were window_start + window_days."""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import evidence
from .components import (assemble, candidates, clean, cost, gates_data, gates_policy, noncompute, patterns, peaks,
                         risk, sizing, vetoes)
from .components.base import P, finding

COMPONENTS = {"clean": clean, "gates_data": gates_data, "gates_policy": gates_policy, "peaks": peaks,
              "noncompute": noncompute, "vetoes": vetoes, "patterns": patterns, "candidates": candidates,
              "sizing": sizing, "risk": risk, "cost": cost, "assemble": assemble}
ORDER = list(COMPONENTS)                     # checkpoint order CP1..CP12

_CLEAN_CACHE, _EV_CACHE = {}, {}
EV_KEYS = ["evidence.report_percentiles", "evidence.io_net_percentile", "evidence.trend_percentile", "percentiles.prod",
           "percentiles.nonprod", "peaks.rolling_slots", "peaks.peak_level", "sizing.second_peak_rank",
           "gates_data.day_min_coverage", "gates_data.anomaly_recent_hours", "gates_data.peak_hours_top",
           "gates_data.min_history_days", "patterns.quiet_recent_days", "vetoes.leak_drop", "candidates.offhour_cpu",
           "candidates.offhour_percentile", "clean.flatline_hours", "clean.interp_max_slots", "clean.pct_min"]


@dataclass
class Resource:
    id: str
    inv: dict
    type: str
    env: str
    state: str
    arr: dict = None
    dq: dict = None
    ev: dict = None
    vol: dict = None
    findings: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    actions: dict = field(default_factory=dict)
    schedule: dict = None
    sizing: dict = None
    underused: object = False
    shrink_considered: bool = False
    risk: dict = None
    cost: dict = None
    default_option: str = None
    verdict: str = None
    reason_code: str = None
    primary: dict = None
    shown: list = None
    veto: dict = None


class Ctx:
    def __init__(self, data, cfg, sel, window_days=None):
        self.data, self.cfg, self.sel = data, cfg, sel
        self.n_days = window_days or data.n_days
        self.n = self.n_days * cfg.t("slots_per_day")
        self.now = data.window_start + pd.Timedelta(days=self.n_days)
        self.axes = {k: v[:self.n] for k, v in data.axes.items()}
        self.inv_by_id = {r["resource_id"]: r for r in data.inventory.to_dict("records")}

    def ts_after_now(self, ts):
        return bool(ts) and pd.Timestamp(ts).tz_convert(self.now.tz) > self.now

    def comp(self, name):
        return COMPONENTS[name].CANDIDATES[self.sel[name]]["fn"]


def _cleaned(ctx):
    cfg = ctx.cfg
    key = (ctx.sel["clean"],) + tuple(cfg(k) for k in ("clean.flatline_hours", "clean.interp_max_slots", "clean.pct_min"))
    if key not in _CLEAN_CACHE:
        fn = ctx.comp("clean")
        n_full = ctx.data.n_days * cfg.t("slots_per_day")
        _CLEAN_CACHE[key] = {rid: fn(df, ctx, n_full) for rid, df in ctx.data.raw.items()}
    return key, _CLEAN_CACHE[key]


def _vol_grid(ctx, df):
    step = pd.Timedelta(minutes=ctx.cfg.t("slot_minutes"))
    slot = ((df["ts"].dt.floor(step) - ctx.data.window_start.tz_convert("UTC")) // step).to_numpy()
    out = {}
    for c in ("iops", "disk_used_pct"):
        x = np.full(ctx.n, np.nan)
        ok = (slot >= 0) & (slot < ctx.n)
        x[slot[ok]] = df[c].to_numpy(dtype=float)[ok]
        out[c] = x
    return out


def _evidence(ctx, ckey, rid, arr, inv):
    k = (ckey, ctx.n_days, rid) + tuple(str(ctx.cfg(x)) for x in EV_KEYS)
    if k not in _EV_CACHE:
        _EV_CACHE[k] = evidence.measure(arr, ctx, inv or {})
    return _EV_CACHE[k]


def purge_evidence(cfg):
    """Drop evidence computed under perturbed configs (keeps memory flat during robustness scoring)."""
    base = tuple(str(cfg(x)) for x in EV_KEYS)
    for k in [k for k in _EV_CACHE if k[-len(EV_KEYS):] != base]:
        del _EV_CACHE[k]
    for k in [k for k in _CLEAN_CACHE if k[1:] != tuple(cfg(x) for x in ("clean.flatline_hours", "clean.interp_max_slots", "clean.pct_min"))]:
        del _CLEAN_CACHE[k]


def build_resources(ctx):
    ckey, cleaned = _cleaned(ctx)
    res = []
    for inv in ctx.data.inventory.to_dict("records"):
        state = inv.get("state") or ""
        if inv["type"] == "vm" and state == "stopped" and ctx.ts_after_now(inv.get("stopped_since")):
            state = "running"                      # backtest: not yet stopped at decision time
        r = Resource(inv["resource_id"], inv, inv["type"], inv.get("env") or "", state)
        if r.type == "vm" and r.id in cleaned:
            arr, dq = cleaned[r.id]
            r.arr = {c: v[:ctx.n] for c, v in arr.items()}       # read-only views (shared with the clean cache)
            r.dq = dq
            r.ev = _evidence(ctx, ckey, r.id, r.arr, inv)
        if r.type == "volume" and r.id in ctx.data.vol_raw:
            r.vol = _vol_grid(ctx, ctx.data.vol_raw[r.id])
        res.append(r)
    for rid in sorted(set(cleaned) - set(ctx.inv_by_id)):          # metrics without inventory
        arr, dq = cleaned[rid]
        r = Resource(rid, None, "vm", "", "running")
        r.arr = {c: v[:ctx.n] for c, v in arr.items()}
        r.dq = dq
        res.append(r)
    return res


def _excluded(r):
    return any(f["kind"] == "exclude" for f in r.findings)


def run(data, cfg, sel, window_days=None):
    ctx = Ctx(data, cfg, sel, window_days)
    res = build_resources(ctx)
    for r in res:
        if r.dq is not None:                      # data-quality report of CP1 (always part of the trace)
            for k in ("duplicates_dropped", "out_of_range", "flatline_slots", "interpolated_slots"):
                r.findings.append({"comp": "clean", "code": None, "kind": "info", "check": k, "value": r.dq.get(k, 0),
                                   "threshold": "reported", "result": "pass", "message": ""})
        ctx.comp("gates_policy")(ctx, r)
        if r.inv is None:
            continue
        compute = r.type == "vm" and r.state != "stopped" and r.arr is not None and r.inv["plan_id"] in data.plans
        if r.type == "vm" and r.state != "stopped" and r.arr is not None:
            ctx.comp("gates_data")(ctx, r)
        if r.type in ("volume", "ip") or (r.type == "vm" and r.state == "stopped"):
            ctx.comp("noncompute")(ctx, r)
        if not compute or not np.isfinite(r.ev["mean"]):
            continue
        r.shrink_considered = bool(r.ev["mean"] < cfg("peaks.looks_wasteful_mean")
                                   or P(r, cfg, "cpu") < cfg("candidates.underused_cpu"))
        if r.shrink_considered:
            ctx.comp("peaks")(ctx, r)
        ctx.comp("vetoes")(ctx, r)                # leak on every VM; capacity vetoes on shrink-considered only
        ctx.comp("patterns")(ctx, r)
        ctx.comp("candidates")(ctx, r)
        if not any(a.endswith("stop") for a in r.actions):     # an idle VM is stopped, not resized
            ctx.comp("sizing")(ctx, r)
    _harmonise_groups(ctx, res)
    for r in res:
        _resize_action(ctx, r)
        if r.actions:
            ctx.comp("risk")(ctx, r)
        if r.inv is not None:
            ctx.comp("cost")(ctx, r)
        _finalise(ctx, r)
        ctx.comp("assemble")(ctx, r)
    return ctx, res


def _harmonise_groups(ctx, res):
    """service_group members get the same (most conservative) target: size on the busiest member."""
    groups = {}
    for r in res:
        g = (r.inv or {}).get("service_group") or ""
        if g and r.sizing and r.sizing.get("kind") == "resize":
            groups.setdefault(g, []).append(r)
    plans = ctx.data.plans
    for g, members in groups.items():
        targets = [m.sizing["target"] for m in members]
        if any(t is None for t in targets):
            for m in members:
                m.sizing["target"] = None
                m.sizing["fail_code"] = m.sizing.get("fail_code") or "PEAK_REPLAY_FAILED"
            continue
        safest = max(targets, key=lambda p: plans[p]["price"])
        for m in members:
            m.sizing["target"] = safest
            m.sizing["group"] = {"name": g, "members": [x.id for x in members], "sized_on": safest}


def _resize_action(ctx, r):
    s = r.sizing
    if not s or s.get("kind") != "resize" or not s.get("target") or not r.underused:
        return
    if any(f["kind"] == "reject" for f in r.findings):          # every veto blocks shrinking
        return
    from .replay import replay
    r.actions["resize"] = {"target": s["target"]}
    s["replay"] = replay(ctx, r, s["target"])
    r.findings.append(finding("sizing", "UNDERUSED", "recommend", "cheapest plan passing replay",
                              s["target"], r.inv["plan_id"], message=f"resize {r.inv['plan_id']} -> {s['target']}"))


def _finalise(ctx, r):
    # A recurring peak forbids SHRINKING, not scheduling around it: if the only veto is the recurring peak and
    # an off-hours schedule exists (which by construction keeps the peak window on), the schedule stands.
    rejects = {f["code"] for f in r.findings if f["kind"] == "reject"}
    if "schedule" in r.actions and rejects == {"VETO_RECURRING_PEAK"}:
        for f in r.findings:
            if f["code"] == "VETO_RECURRING_PEAK":
                f["kind"] = "info"
                f["message"] += " (blocks resize only; the schedule keeps the peak window on)"
    below = any(f["code"] == "BELOW_FLOOR" for f in r.findings)
    if below:
        for f in r.findings:
            if f["kind"] == "recommend" and f["comp"] in ("candidates", "sizing"):
                f["kind"] = "info"
                f["message"] = (f["message"] + " (below Rs 500 floor)").strip()
        r.actions = {}
    decisive = [f for f in r.findings if f["kind"] != "info"]
    if r.shrink_considered and not any(f["kind"] in ("recommend", "upsize", "below_floor") for f in decisive) \
            and r.sizing and r.sizing.get("fail_code"):
        code = r.sizing["fail_code"]
        r.findings.append(finding("sizing", code, "soft_reject", "cheapest passing plan", "none",
                                  "a cheaper plan that passes", message=_soft_message(r, code)))
        decisive = True
    if not decisive:
        r.findings.append(finding("sizing", "RIGHT_SIZED", "healthy", "change needed", "no", "no", result=False))


def _soft_message(r, code):
    if code == "NO_CHEAPER_PLAN":
        return f"no cheaper plan satisfies CPU and memory together (needs {r.sizing['need_vcpu']:.1f} vCPU, {r.sizing['need_ram']:.1f} GB)"
    nv = r.sizing.get("naive")
    if nv:
        return (f"an average-based tool would move to {nv['target_plan']} (saves Rs {nv['saving_inr']:,}); "
                f"Peak Replay shows {nv['replay_minutes_above_90']} min above 90% there")
    att = (r.sizing.get("attempts") or [{}])[-1]
    return f"Peak Replay on {att.get('plan')} shows {att.get('minutes_above_90')} min above 90%"
