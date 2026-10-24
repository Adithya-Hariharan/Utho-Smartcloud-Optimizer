"""Step 2: volumes, IPs and stopped VMs (plan section 8 group C). Snapshot cost is subtracted."""
import math

import numpy as np
import pandas as pd

from ..cost.model import format_inr, snapshot_cost
from .common import Outcome, action, build_options, days_since, used_gb, veto


def _stopped_long(e, vm_id):
    """The VM is stopped for longer than the stopped-VM gate."""
    if not vm_id or vm_id not in e.inv.index:
        return False, None
    vm = e.inv.loc[vm_id]
    age = days_since(vm["stopped_since"], e.now) if vm["state"] == "stopped" and pd.notna(vm["stopped_since"]) else None
    return (age is not None and age > e.t("stopped_vm_days")), age


def stopped_vm(e, rid, row, cur, tr):
    age = days_since(row["stopped_since"], e.now)
    if tr.add("noncompute.stopped_age", "days stopped > 30", round(age, 1), e.t("stopped_vm_days"),
              "pass" if age > e.t("stopped_vm_days") else "fail") == "fail":
        tr.terminal()
        # §4.5 has no exclude code for a recent stop; healthy + flag (see PLAN_final.md B10)
        return Outcome("healthy", "RIGHT_SIZED",
                       f"Stopped {age:.0f} days ago: treated as a maintenance stop, nothing to do yet.",
                       flags=[{"code": "STOPPED_RECENTLY", "message": f"Stopped {age:.0f} days ago (maintenance); "
                               f"re-check after {e.t('stopped_vm_days'):.0f} days."}])
    s = e.cleaned.series.get(rid)
    gb = used_gb(s.values["disk_used_pct"] if s else None, row["disk_gb"])
    snap = snapshot_cost(gb, e.cfg)
    o = Outcome("recommend", "STOPPED_VM",
                f"Stopped for {age:.0f} days; compute is not billed but the {int(row['disk_gb'])} GB disk still "
                f"costs {format_inr(cur['storage_inr'])}/month. Snapshot ({gb} GB, {format_inr(snap)}) and delete.",
                actions=[action("snapshot", f"Snapshot the {gb} GB disk", reversible=True, rollback="delete the snapshot"),
                         action("delete", "Delete the VM and its boot disk", requires=["snapshot"], reversible=False,
                                rollback="restore from the snapshot")],
                default="snapshot+delete")
    o.options = build_options(cur["monthly_inr"], {"snapshot+delete": (snap, f"snapshot {gb} GB × ₹4")})
    tr.terminal()
    return o


def volume(e, rid, row, f, cur, tr):
    s = e.cleaned.series.get(rid)
    disk = s.values["disk_used_pct"] if s else None
    gb_rate = e.cfg.get("pricing.volume_inr_per_gb_month")
    size = int(row["disk_gb"])

    if not row["attached_to"]:
        age = days_since(row["unattached_since"], e.now)
        if tr.add("noncompute.orphan_age", "days unattached ≥ 7", round(age, 1), e.t("orphan_age_days"),
                  "pass" if age >= e.t("orphan_age_days") else "fail") == "fail":
            tr.terminal()
            return Outcome("exclude", "ORPHAN_TOO_NEW",
                           f"Unattached for only {age:.0f} days (< {e.t('orphan_age_days'):.0f}): may be mid-setup.")
        gb = used_gb(disk, size)
        snap = snapshot_cost(gb, e.cfg)
        o = Outcome("recommend", "ORPHAN_VOLUME",
                    f"Unattached for {age:.0f} days, costing {format_inr(cur['monthly_inr'])}/month. Snapshot the "
                    f"{gb} GB in use ({format_inr(snap)}/month) and delete.",
                    actions=[action("snapshot", f"Snapshot {gb} GB", rollback="delete the snapshot"),
                             action("delete", "Delete the volume", requires=["snapshot"], reversible=False,
                                    rollback="restore from the snapshot")],
                    default="snapshot+delete")
        o.options = build_options(cur["monthly_inr"], {"snapshot+delete": (snap, f"snapshot {gb} GB × ₹4")})
        tr.add("noncompute.decision", "orphan volume", round(age, 1), e.t("orphan_age_days"), "recommend", True)
        return o

    long_stop, age = _stopped_long(e, row["attached_to"])
    if long_stop:
        gb = used_gb(disk, size)
        snap = snapshot_cost(gb, e.cfg)
        o = Outcome("recommend", "STOPPED_VM",
                    f"Attached to {e.inv.loc[row['attached_to'], 'name']}, stopped {age:.0f} days. Snapshot {gb} GB "
                    f"({format_inr(snap)}) and delete together with the VM.",
                    actions=[action("snapshot", f"Snapshot {gb} GB", rollback="delete the snapshot"),
                             action("delete", "Delete the volume with its VM", requires=["snapshot"], reversible=False,
                                    rollback="restore from the snapshot")],
                    default="snapshot+delete")
        o.options = build_options(cur["monthly_inr"], {"snapshot+delete": (snap, f"snapshot {gb} GB × ₹4")})
        tr.add("noncompute.decision", "attached VM stopped > 30 d", round(age, 1), e.t("stopped_vm_days"), "recommend", True)
        return o

    t = f.get("trend", {}).get("disk_used", {})
    slope, r2, d85 = t.get("slope"), t.get("r2"), t.get("days_to_85")
    growing = (slope is not None and slope >= e.t("growth_min_slope") and r2 is not None and r2 >= e.t("growth_min_r2")
               and d85 is not None and d85 < e.t("growth_days_to_85"))
    if tr.add("veto.growth", "disk days_to_85 < 60 (slope ≥ 0.3, R² ≥ 0.5)", d85, e.t("growth_days_to_85"),
              "fail" if growing else "pass") == "fail":
        mean_used = float(np.nanmean(disk))
        naive_gb = _target_gb(e, size * mean_used / 100)
        o = Outcome("reject", "VETO_GROWTH",
                    f"Disk use is rising {slope:.2f} points/day (R² {r2:.2f}) and reaches 85% in {d85:.0f} days: "
                    f"shrinking now would need a migration back.",
                    veto=veto("growth", "disk_days_to_85", d85, e.t("growth_days_to_85"), "<",
                              "growing toward capacity"),
                    naive={"basis": "mean disk use", "mean_used_pct": round(mean_used, 1), "action": "shrink_volume",
                           "target_gb": naive_gb, "would_save_inr": max(0, (size - naive_gb) * gb_rate)})
        tr.terminal()
        return o

    iops_p95 = f.get("iops_p95")
    if tr.add("pattern.idle_volume", "IOPS p95 < 5 on an attached volume", iops_p95, e.t("idle_iops_p95"),
              "flag" if iops_p95 is not None and iops_p95 < e.t("idle_iops_p95") else "pass") == "flag":
        tr.terminal()
        return Outcome("flag", "IDLE_VOLUME_REVIEW",
                       f"Attached to {e.inv.loc[row['attached_to'], 'name']} but IOPS p95 is {iops_p95:.0f} for 30 days: "
                       f"review with the owner before detaching.")

    used_p99 = f["metrics"]["disk_used"]["p99"]
    if used_p99 is not None and used_p99 < e.t("volume_oversized_used_pct"):
        target = _target_gb(e, size * float(np.nanmax(disk)) / 100)
        if target < size:
            after = target * gb_rate
            o = Outcome("recommend", "OVERSIZED_VOLUME",
                        f"{size} GB volume uses at most {np.nanmax(disk):.0f}% ({size * np.nanmax(disk) / 100:.0f} GB). "
                        f"Migrate to a {target} GB volume (no in-place shrink).",
                        actions=[action("shrink_volume", f"Migrate data to a new {target} GB volume, then delete the "
                                        f"{size} GB one", rollback="keep the old volume until verified")],
                        default="shrink_volume")
            o.options = build_options(cur["monthly_inr"], {"shrink_volume": (after, f"{target} GB × ₹{gb_rate}")})
            tr.add("noncompute.oversized", "disk used p99 < 30%", used_p99, e.t("volume_oversized_used_pct"),
                   "recommend", True)
            return o
    tr.add("noncompute.healthy", "volume in use and sized", used_p99, e.t("volume_oversized_used_pct"), "healthy", True)
    return Outcome("healthy", "RIGHT_SIZED", "Attached, in use and not oversized.")


def _target_gb(e, used):
    step = e.t("volume_size_step_gb")
    return int(max(step, math.ceil(used / (e.t("volume_target_used_pct") / 100) / step) * step))


def ip(e, rid, row, cur, tr):
    if "allowlisted_ip" in row["tags_list"]:
        tr.add("gate.tag", "tag allowlisted_ip", True, "absent", "exclude", True)
        return Outcome("exclude", "TAG_ALLOWLISTED_IP",
                       "On a bank / payment-gateway allowlist: the same IP cannot be re-acquired once released.")
    if not row["attached_to"]:
        age = days_since(row["unattached_since"], e.now) or days_since(row["created_at"], e.now)
        if tr.add("noncompute.orphan_age", "days unassociated ≥ 7", round(age, 1), e.t("orphan_age_days"),
                  "pass" if age >= e.t("orphan_age_days") else "fail") == "fail":
            tr.terminal()
            return Outcome("exclude", "ORPHAN_TOO_NEW", f"Unassociated for only {age:.0f} days.")
        o = Outcome("recommend", "UNUSED_IP", f"Allocated but not associated for {age:.0f} days.",
                    actions=[action("release", "Release the IP", reversible=False,
                                    rollback="allocate a new IP (the address changes)")], default="release")
        o.options = build_options(cur["monthly_inr"], {"release": (0, "released IP = ₹0")})
        tr.terminal()
        return o
    long_stop, age = _stopped_long(e, row["attached_to"])
    if long_stop:
        o = Outcome("recommend", "STOPPED_VM",
                    f"Associated with {e.inv.loc[row['attached_to'], 'name']}, stopped {age:.0f} days: release with the VM.",
                    actions=[action("release", "Release the IP with its stopped VM", reversible=False,
                                    rollback="allocate a new IP (the address changes)")], default="release")
        o.options = build_options(cur["monthly_inr"], {"release": (0, "released IP = ₹0")})
        tr.add("noncompute.decision", "attached VM stopped > 30 d", round(age, 1), e.t("stopped_vm_days"), "recommend", True)
        return o
    tr.add("noncompute.healthy", "associated with a running VM", row["attached_to"], None, "healthy", True)
    return Outcome("healthy", "RIGHT_SIZED", "Associated with a running VM.")
