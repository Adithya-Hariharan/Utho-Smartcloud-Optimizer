"""Shared engine pieces: the decision trace, the outcome record, actions and cost options."""
import math
from dataclasses import dataclass, field

import numpy as np

from ..cost.model import format_inr, option

LEAF_KEYS = ("p50", "p95", "p99", "max")


def resource_block(row, members):
    """The frozen §4.5 resource{} block."""
    return {"resource_id": row["resource_id"], "name": row["name"], "type": row["type"], "env": row["env"],
            "team": row["owner"], "owner": row["owner"], "region": row["region"], "purpose": row["purpose"],
            "service_group": row["service_group"], "members": members, "tags": list(row["tags_list"])}


def group_members(inventory):
    """resource_id -> the other resource_ids sharing its non-empty service_group."""
    groups = inventory[inventory["service_group"] != ""].groupby("service_group")["resource_id"].apply(list)
    out = {}
    for ids in groups:
        for rid in ids:
            out[rid] = [x for x in ids if x != rid]
    return out


ACTION_ORDER = {"snapshot": 1, "delete": 1, "release": 1, "stop": 2, "resize": 3, "shrink_volume": 3,
                "upsize": 3, "schedule": 4}


class Trace(list):
    def add(self, step, check, value, threshold, result, terminal=False):
        self.append({"step": step, "check": check, "value": _plain(value), "threshold": _plain(threshold),
                     "result": result, "terminal": terminal})
        return result

    def terminal(self):
        """Mark the last check as the one that decided."""
        if self:
            self[-1]["terminal"] = True


def _plain(x):
    if isinstance(x, np.generic):
        x = x.item()
    if isinstance(x, float):
        return None if math.isnan(x) else round(x, 3)
    return x


@dataclass
class Outcome:
    verdict: str
    code: str
    reason: str
    actions: list = field(default_factory=list)
    target: dict = None
    schedule: dict = None
    options: dict = field(default_factory=dict)       # key -> (monthly_after, formula)
    default: str = "none"
    replay: dict = None
    veto: dict = None
    naive: dict = None
    recurring: dict = None
    risk: dict = None
    below_floor_saving: int = None
    flags: list = field(default_factory=list)


def action(type_, description, requires=(), reversible=True, rollback=None):
    return {"type": type_, "order": ACTION_ORDER[type_], "description": description, "requires": list(requires),
            "reversible": reversible, "rollback": rollback}


def key_of(types):
    """Option key: action types joined by '+' in apply order."""
    return "+".join(sorted(types, key=lambda t: (ACTION_ORDER[t], t)))


def veto(signal, metric, value, threshold, comparator, message):
    return {"signal": signal, "metric": metric, "value": round(float(value), 2), "threshold": float(threshold),
            "comparator": comparator, "message": message}


def build_options(current_monthly, opts):
    out = {"none": option(current_monthly, current_monthly, f"{format_inr(current_monthly)}/month, no change")}
    for k, (after, expr) in opts.items():
        after = int(round(after))
        saving = current_monthly - after
        verb = "saves" if saving >= 0 else "costs"
        out[k] = option(current_monthly, after,
                        f"{expr} = {format_inr(after)}/month; {verb} {format_inr(current_monthly)} − "
                        f"{format_inr(after)} = {format_inr(abs(saving)) if saving >= 0 else '-' + format_inr(-saving)}/month")
    return out


def days_since(ts, now):
    return None if ts is None or (isinstance(ts, float) and math.isnan(ts)) else (now - ts).total_seconds() / 86400


def used_gb(arr, disk_gb):
    """Median disk_used_pct x size, to the nearest GB; the full size when there is no telemetry."""
    if arr is None or not np.any(~np.isnan(arr)):
        return int(disk_gb)
    return max(1, int(round(disk_gb * float(np.nanmedian(arr)) / 100)))
