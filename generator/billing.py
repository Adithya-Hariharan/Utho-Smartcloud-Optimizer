"""180-day daily cost history, and creation dates tuned so month 6 / month 1 ~ 1.40."""
import numpy as np
import pandas as pd

from .config import (BILLING_DAYS, HOURS_PER_MONTH, IP_INR_PER_MONTH, NOW, TARGET_GROWTH_RATIO, TZ,
                     VOLUME_INR_PER_GB)
from .archetypes import plan_specs, random_date
from .signals import rng_for

DATES = pd.date_range(NOW - pd.Timedelta(days=BILLING_DAYS), periods=BILLING_DAYS, freq="D")
DAILY = 24 / HOURS_PER_MONTH            # daily cost = monthly x 24/730

NEW_START = pd.Timestamp("2026-05-23", tz=TZ)
NEW_END = pd.Timestamp("2026-09-15", tz=TZ)
OLD_START = pd.Timestamp("2026-01-20", tz=TZ)
OLD_END = pd.Timestamp("2026-04-20", tz=TZ)


def _ts(v):
    return pd.Timestamp(v) if v not in ("", None) else None


def monthly_cost_series(inv, created_at):
    """Monthly-rate cost on each billing day (0 before creation)."""
    alive = DATES >= pd.Timestamp(created_at).normalize()
    if inv["type"] == "ip":
        cost = np.full(len(DATES), float(IP_INR_PER_MONTH))
    elif inv["type"] == "volume":
        cost = np.full(len(DATES), float(inv["disk_gb"]) * VOLUME_INR_PER_GB)
    else:
        compute = np.full(len(DATES), float(plan_specs(inv["plan_id"])[2]))
        resized = _ts(inv["last_resized_at"])
        if resized is not None and inv["previous_plan_id"]:
            compute[DATES < resized.normalize()] = plan_specs(inv["previous_plan_id"])[2]
        stopped = _ts(inv["stopped_since"])
        if stopped is not None:
            compute[DATES >= stopped.normalize()] = 0.0       # stopped_vm_billed = false
        cost = compute + float(inv["disk_gb"]) * VOLUME_INR_PER_GB
    return np.where(alive, cost, 0.0)


def _ratio(total):
    return total[-30:].sum() / total[:30].sum()


def tune_creation_dates(specs):
    """Bulk VMs get either an 'old' date (before the billing window) or a 'new' one inside it.
    Non-prod first (most growth is dev/staging), then prod; pick how many are new so the ratio ~ 1.40."""
    fixed = [s for s in specs if not s["auto_created"]]
    pool = [s for s in specs if s["auto_created"]]
    rng = rng_for("billing-tuner")
    nonprod = [s for s in pool if s["inv"]["env"] != "prod"]
    prod = [s for s in pool if s["inv"]["env"] == "prod"]
    rng.shuffle(nonprod)
    rng.shuffle(prod)
    pool = nonprod + prod

    for s in pool:
        r = rng_for(s["inv"]["name"], "created")
        s["_old"] = random_date(r, OLD_START, OLD_END)
        s["_new"] = random_date(r, NEW_START, NEW_END)

    base = sum(monthly_cost_series(s["inv"], s["inv"]["created_at"]) for s in fixed)
    old = [monthly_cost_series(s["inv"], s["_old"]) for s in pool]
    new = [monthly_cost_series(s["inv"], s["_new"]) for s in pool]

    best_k, best_err = 0, 1e9
    for k in range(len(pool) + 1):
        total = base + sum(new[:k], np.zeros(len(DATES))) + sum(old[k:], np.zeros(len(DATES)))
        err = abs(_ratio(total) - TARGET_GROWTH_RATIO)
        if err < best_err:
            best_k, best_err = k, err

    for i, s in enumerate(pool):
        s["inv"]["created_at"] = s["_new"] if i < best_k else s["_old"]
        del s["_old"], s["_new"]
    return best_k


def billing_frame(specs):
    rows = []
    for s in specs:
        inv = s["inv"]
        daily = monthly_cost_series(inv, inv["created_at"]) * DAILY
        alive = daily > 0
        rows.append(pd.DataFrame({
            "date": DATES[alive].date, "resource_id": inv["resource_id"], "name": inv["name"],
            "type": inv["type"], "team": inv["owner_team"], "env": inv["env"], "region": inv["region"],
            "cost_inr": np.round(daily[alive], 2),
        }))
    df = pd.concat(rows, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df
