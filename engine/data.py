"""Load the committed dataset. The decision pipeline only sees inventory, pricing and metrics;
truth.csv is loaded separately and used for SCORING only (engine/score.py)."""
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


@dataclass
class Data:
    inventory: pd.DataFrame
    plans: dict                 # plan_id -> dict(vcpu, ram, price, bw)
    plan_order: list            # plan ids sorted by price
    prices: dict                # block_volume / snapshot / public_ip per month
    raw: dict                   # resource_id -> DataFrame of VM metrics
    vol_raw: dict               # resource_id -> DataFrame of volume metrics
    window_start: pd.Timestamp
    now: pd.Timestamp
    n_days: int
    axes: dict = field(default_factory=dict)


def load(cfg):
    inv = pd.read_csv(DATA / "inventory.csv", keep_default_na=False)
    pricing = pd.read_csv(DATA / "pricing.csv", keep_default_na=False)
    plans = {}
    for _, r in pricing[pricing["kind"] == "vm_plan"].iterrows():
        plans[r["item"]] = {"vcpu": int(float(r["vcpu"])), "ram": float(r["ram_gb"]), "price": float(r["monthly_inr"]),
                            "bw": float(r["bandwidth_mbps"])}
    prices = {r["item"]: float(r["monthly_inr"]) for _, r in pricing[pricing["kind"] != "vm_plan"].iterrows()}
    order = sorted(plans, key=lambda p: plans[p]["price"])

    m = pd.read_parquet(DATA / "metrics.parquet")
    m["resource_id"] = m["resource_id"].astype(str)
    raw = {k: v.drop(columns="resource_id").reset_index(drop=True) for k, v in m.groupby("resource_id", sort=True)}
    vm = pd.read_parquet(DATA / "volume_metrics.parquet")
    vm["resource_id"] = vm["resource_id"].astype(str)
    vol_raw = {k: v.drop(columns="resource_id").reset_index(drop=True) for k, v in vm.groupby("resource_id", sort=True)}

    start = pd.Timestamp(cfg.meta("window_start")).tz_convert(cfg.meta("timezone"))
    now = pd.Timestamp(cfg.meta("now")).tz_convert(cfg.meta("timezone"))
    n_days = int((now - start) / pd.Timedelta(days=1))
    d = Data(inv, plans, order, prices, raw, vol_raw, start, now, n_days)
    d.axes = axes(cfg, start, n_days)
    return d


def axes(cfg, start, n_days):
    spd = cfg.t("slots_per_day")
    ts = pd.date_range(start, periods=n_days * spd, freq=f"{cfg.t('slot_minutes')}min")
    return {"hour": (np.arange(n_days * spd) % spd) // cfg.t("slots_per_hour"),
            "day": np.arange(n_days * spd) // spd,
            "dow": ts.dayofweek.to_numpy(),
            "weekend": ts.dayofweek.to_numpy() >= cfg.t("saturday_index"),
            "slot_of_week": ts.dayofweek.to_numpy() * spd + (np.arange(n_days * spd) % spd)}


def load_truth():
    return pd.read_csv(DATA / "truth.csv", keep_default_na=False)
