"""Cost model (PLAN_final.md B3): one rule used by billing totals, summaries and every option.

VM = plan price (0 while stopped, unless stopped_vm_billed) + boot disk_gb x ₹8.
Volume = disk_gb x ₹8. IP = ₹200 on its own row (never on the VM). Whole rupees throughout.
"""
import pandas as pd


def format_inr(amount):
    """Indian digit grouping: 657302 -> '₹6,57,302'."""
    n = int(round(amount))
    sign, s = ("-" if n < 0 else ""), str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return f"{sign}₹{s}"


def _num(x):
    return None if pd.isna(x) else int(x)


def current_cost(row, cfg):
    """The frozen §4.5 `current{}` block for one inventory row."""
    gb_rate = cfg.get("pricing.volume_inr_per_gb_month")
    kind = row["type"]
    disk = _num(row["disk_gb"])
    if kind == "ip":
        out = {"plan": None, "vcpu": None, "ram_gb": None, "disk_gb": None,
               "compute_inr": 0, "storage_inr": 0, "ip_inr": int(cfg.get("pricing.ip_inr_per_month"))}
    elif kind == "volume":
        out = {"plan": None, "vcpu": None, "ram_gb": None, "disk_gb": disk,
               "compute_inr": 0, "storage_inr": (disk or 0) * gb_rate, "ip_inr": 0}
    else:
        price = cfg.plan_price(row["plan_id"]) or 0
        stopped = row["state"] == "stopped" and not cfg.get("billing.stopped_vm_billed")
        out = {"plan": row["plan_id"] or None, "vcpu": _num(row["vcpu"]), "ram_gb": _num(row["ram_gb"]),
               "disk_gb": disk, "compute_inr": 0 if stopped else int(price),
               "storage_inr": (disk or 0) * gb_rate, "ip_inr": 0}
    out["monthly_inr"] = int(out["compute_inr"] + out["storage_inr"] + out["ip_inr"])
    return out


def daily_from_monthly(monthly, cfg):
    return monthly * 24 / cfg.get("billing.hours_per_month")


def scheduled_compute(compute_inr, on_hours_per_week):
    """Scheduling saves compute only: compute x on_hours / 168, rounded to ₹1 (F1, F6)."""
    return int(round(compute_inr * on_hours_per_week / 168))


def snapshot_cost(gb, cfg):
    return int(gb * cfg.get("pricing.snapshot_inr_per_gb_month"))


def option(current_monthly, monthly_after, formula=None):
    """A §4.5 options[key] entry. Whole rupees; saving = before - after."""
    after = int(round(monthly_after))
    before = int(current_monthly)
    return {"monthly_inr_after": after, "saving_inr": before - after,
            "formula": formula or f"{format_inr(before)} − {format_inr(after)} = {format_inr(before - after)}/month"}


def no_change_option(current_monthly):
    return option(current_monthly, current_monthly, f"{format_inr(current_monthly)}/month, no change")


def fleet_costs(ds, cfg):
    """One row per inventory resource with its current cost block flattened."""
    rows = []
    for _, r in ds.inventory.iterrows():
        c = current_cost(r, cfg)
        rows.append({"resource_id": r["resource_id"], "name": r["name"], "type": r["type"],
                     "env": r["env"], "team": r["owner"], "region": r["region"], **c})
    return pd.DataFrame(rows)


def breakdown(costs, by):
    """Current monthly cost per group; empty env -> 'untagged', empty team -> 'unowned'."""
    key = costs[by].replace("", "untagged" if by == "env" else "unowned")
    return {k: int(v) for k, v in costs.groupby(key)["monthly_inr"].sum().sort_index().items()}
