"""CP5 - volumes, public IPs and long-stopped VMs (unattached vs idle vs oversized vs stopped)."""
import numpy as np

from common.stats import linfit
from .base import age_days, finding, trace_only

C = "noncompute"


def _vm_stopped_long(ctx, vm_id):
    vm = ctx.inv_by_id.get(vm_id)
    if vm is None or vm.get("state") != "stopped" or not vm.get("stopped_since"):
        return False
    if ctx.ts_after_now(vm.get("stopped_since")):
        return False
    return age_days(vm["stopped_since"], ctx.now) >= ctx.cfg("gates_policy.stopped_recent_days")


def _volume(ctx, r, growth):
    cfg, inv = ctx.cfg, r.inv
    out = []
    attached = inv.get("attached_to") or ""
    if not attached and ctx.ts_after_now(inv.get("unattached_since")):
        return [finding(C, "RIGHT_SIZED", "healthy", "attached at decision time", "yes", "yes", result=False)]
    if not attached:
        age = age_days(inv.get("unattached_since"), ctx.now)
        lim = cfg("noncompute.orphan_age_days")
        if age < lim:
            out.append(finding(C, "ORPHAN_TOO_NEW", "exclude", "days unattached", age, lim,
                               message="detached recently: may be mid-setup"))
        else:
            r.actions["snapshot+delete"] = {"reason": "unattached"}
            out.append(finding(C, "ORPHAN_VOLUME", "recommend", "days unattached", age, lim,
                               message=f"unattached for {age:.0f} days"))
        return out
    if _vm_stopped_long(ctx, attached):
        r.actions["snapshot+delete"] = {"reason": "attached to a long-stopped VM"}
        out.append(finding(C, "STOPPED_VM", "recommend", "attached VM stopped (days)",
                           age_days(ctx.inv_by_id[attached]["stopped_since"], ctx.now),
                           cfg("gates_policy.stopped_recent_days"), message="attached to a VM stopped for a month+"))
        return out
    used, iops = r.vol["disk_used_pct"], r.vol["iops"]
    day = np.arange(len(used)) / ctx.cfg.t("slots_per_day")
    if growth:
        slope, icpt = linfit(day, used)
        last = icpt + slope * day[-1] if np.isfinite(slope) else np.nan
        full = cfg("noncompute.full_level")
        dtf = (full - last) / slope if np.isfinite(slope) and slope > 0 else np.inf
        lim = cfg("noncompute.growth_days_to_full")
        out.append(finding(C, "VETO_GROWTH", "reject", "days until volume is full", max(dtf, 0), lim,
                           message=f"growing {slope:.2f}%/day") if dtf < lim
                   else trace_only(C, "days until volume is full", dtf, lim, True))
    if np.nanmax(iops) == 0:
        out.append(finding(C, "IDLE_VOLUME_REVIEW", "flag", "max IOPS over the window", 0, 0,
                           message="attached but no read/write activity: confirm with owner"))
    frac = np.nanmean(used) / 100
    lim = cfg("noncompute.oversized_used_max")
    if frac < lim:
        need = float(inv["disk_gb"]) * frac / cfg("noncompute.volume_target_used")
        sizes = [s for s in cfg("noncompute.volume_sizes") if s >= need]
        target = min(sizes) if sizes else float(inv["disk_gb"])
        if target < float(inv["disk_gb"]):
            r.actions["shrink_volume"] = {"target_gb": target}
            out.append(finding(C, "OVERSIZED_VOLUME", "recommend", "used fraction", frac, lim,
                               message=f"{frac:.0%} used: migrate to {target:.0f} GB (no in-place shrink)"))
    if not out:
        out.append(finding(C, "RIGHT_SIZED", "healthy", "used fraction", frac, lim, result=False))
    return out


def _ip(ctx, r):
    cfg, inv = ctx.cfg, r.inv
    attached = inv.get("attached_to") or ""
    if not attached:
        age = age_days(inv.get("unattached_since") or inv.get("created_at"), ctx.now)
        lim = cfg("noncompute.orphan_age_days")
        if age < lim:
            return [finding(C, "ORPHAN_TOO_NEW", "exclude", "days unassociated", age, lim)]
        r.actions["release"] = {"reason": "unassociated"}
        return [finding(C, "UNUSED_IP", "recommend", "days unassociated", age, lim,
                        message="allocated but not associated: you pay for not using it")]
    if _vm_stopped_long(ctx, attached):
        r.actions["release"] = {"reason": "VM stopped"}
        return [finding(C, "STOPPED_VM", "recommend", "attached VM stopped (days)",
                        age_days(ctx.inv_by_id[attached]["stopped_since"], ctx.now), cfg("gates_policy.stopped_recent_days"))]
    return [finding(C, "RIGHT_SIZED", "healthy", "associated with a running VM", "yes", "yes", result=False)]


def _stopped_vm(ctx, r):
    days = age_days(r.inv.get("stopped_since"), ctx.now)
    lim = ctx.cfg("gates_policy.stopped_recent_days")
    if days >= lim:
        r.actions["snapshot+delete"] = {"reason": "stopped for a month+"}
        return [finding(C, "STOPPED_VM", "recommend", "days stopped", days, lim,
                        message="stopped for a month+: disk and IP still billed")]
    return []


def _run(ctx, r, growth):
    if r.type == "volume":
        r.findings += _volume(ctx, r, growth)
    elif r.type == "ip":
        r.findings += _ip(ctx, r)
    elif r.type == "vm" and r.state == "stopped":
        r.findings += _stopped_vm(ctx, r)


def a_state(ctx, r):
    """state + 7-day age gate + zero IOPS + < 20% used."""
    _run(ctx, r, growth=False)


def b_state_growth(ctx, r):
    """a + never shrink/clean a volume projected to fill up within 30 days."""
    _run(ctx, r, growth=True)


CANDIDATES = {
    "a_state": {"fn": a_state, "params": 3, "prior": 9, "desc": "unattached > 7 d / attached-to-stopped / zero IOPS / < 20% used"},
    "b_state_growth": {"fn": b_state_growth, "params": 5, "prior": 8, "desc": "a + growth veto: reject if full within 30 days"},
}
