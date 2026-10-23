"""Entry point: python -m generator.build  (writes everything into data/)."""
import os
from pathlib import Path

import numpy as np
import pandas as pd

from . import quality
from .archetypes import bulk_vms
from .billing import billing_frame, tune_creation_dates
from .config import (INVENTORY_COLUMNS, IP_INR_PER_MONTH, PLANS, SNAPSHOT_INR_PER_GB, VOLUME_INR_PER_GB)
from .planted import planted_ips, planted_vms, planted_volumes, stray_series
from .signals import AX, rng_for

DATA = Path(os.environ.get("SCO_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
FIXTURE_NAMES = ["prod-batch-07", "dev-web-03", "vol-orphan-11"]


def assign_ids(vms, vols, ips, ghost):
    for i, s in enumerate(vms, 1):
        s["inv"]["resource_id"] = f"vm-{i:04d}"
    ghost["inv"]["resource_id"] = "vm-9999"
    for i, s in enumerate(vols, 1):
        s["inv"]["resource_id"] = f"vol-{i:04d}"
    for i, s in enumerate(ips, 1):
        s["inv"]["resource_id"] = f"ip-{i:04d}"


def resolve_attachments(vms, others):
    by_name = {s["inv"]["name"]: s["inv"] for s in vms}
    for s in others:
        inv = s["inv"]
        if not inv["attached_to"]:
            continue
        vm = by_name[inv["attached_to"]]          # KeyError = broken plan, fail loudly
        inv["attached_to"] = vm["resource_id"]
        inv["env"], inv["region"] = vm["env"], vm["region"]
        inv["owner_team"] = inv["owner_team"] or vm["owner_team"]
        inv["created_at"] = max(pd.Timestamp(inv["created_at"]), pd.Timestamp(vm["created_at"]))


def assign_bulk_faults(bulk):
    rng = rng_for("fault-assignment")
    eligible = [s for s in bulk if s["active"] == (0, AX.n)]
    picks = rng.choice(len(eligible), 12, replace=False)
    plan = ["out_of_range"] * 3 + ["out_of_order"] * 2 + ["reboot_gap"] * 6 + ["ts_jitter"]
    for idx, fault in zip(picks, plan):
        eligible[idx]["faults"].append(fault)


def vm_frame(s, fault_log):
    a, b = s["active"]
    slots = np.arange(a, b)
    df = pd.DataFrame({"slot": slots, "ts": AX.ts_utc[slots]})
    for col, arr in s["metrics"].items():
        df[col] = np.asarray(arr)[slots]
    rng = rng_for(s["inv"]["name"], "faults")
    inv = s["inv"]

    def run(name, fn):
        nonlocal df
        df, detail = fn(df, rng)
        fault_log.append({"resource_id": inv["resource_id"], "name": inv["name"], "fault": name,
                          "detail": detail})

    for name in quality.ORDER:
        if name == "duplicate_block":             # random monitoring drops happen before re-sends/reorders
            run("random_drops", quality.random_drops)
        if name in s["faults"]:
            run(name, quality.FAULTS[name])
    df = df.drop(columns="slot")
    df.insert(0, "resource_id", inv["resource_id"])
    return df


def volume_frame(s):
    rng = rng_for(s["inv"]["name"], "faults")
    df = pd.DataFrame({"resource_id": s["inv"]["resource_id"], "ts": AX.ts_utc,
                       "iops": s["metrics"]["iops"], "disk_used_pct": s["metrics"]["disk_used_pct"]})
    return quality.random_drops(df, rng)[0]


def finalize_metrics(frames, cols):
    df = pd.concat(frames, ignore_index=True)
    for c in cols:
        df[c] = df[c].round(2).astype("float32")
    df["resource_id"] = df["resource_id"].astype("category")
    return df


def inventory_frame(specs):
    rows = []
    for s in specs:
        inv = dict(s["inv"])
        inv["created_at"] = pd.Timestamp(inv["created_at"]).isoformat()
        rows.append(inv)
    return pd.DataFrame(rows)[INVENTORY_COLUMNS]


def truth_frame(specs):
    return pd.DataFrame([{"resource_id": s["inv"]["resource_id"], "name": s["inv"]["name"],
                          "type": s["inv"]["type"], **s["truth"]} for s in specs])


def pricing_frame():
    rows = [{"item": p, "kind": "vm_plan", "vcpu": v, "ram_gb": r, "bandwidth_mbps": bw,
             "monthly_inr": price, "unit": "per VM per month", "basis": basis}
            for p, (v, r, price, bw, basis) in PLANS.items()]
    rows += [
        {"item": "block_volume", "kind": "storage", "monthly_inr": VOLUME_INR_PER_GB, "unit": "per GB per month",
         "basis": "assumption (illustrative)"},
        {"item": "snapshot", "kind": "storage", "monthly_inr": SNAPSHOT_INR_PER_GB, "unit": "per GB per month",
         "basis": "assumption (illustrative)"},
        {"item": "public_ip", "kind": "network", "monthly_inr": IP_INR_PER_MONTH, "unit": "per IP per month",
         "basis": "assumption (illustrative)"},
    ]
    return pd.DataFrame(rows)


def main():
    DATA.mkdir(exist_ok=True)
    (DATA / "fixture").mkdir(exist_ok=True)

    planted, bulk = planted_vms(), bulk_vms()
    vms = planted + bulk
    vols, ips, ghost = planted_volumes(), planted_ips(), stray_series()
    assign_ids(vms, vols, ips, ghost)
    k_new = tune_creation_dates(vms)
    resolve_attachments(vms, vols + ips)
    assign_bulk_faults(bulk)

    inventory_specs = vms + vols + ips
    fault_log = []
    metric_cols = quality.METRIC_COLS
    vm_frames = [vm_frame(s, fault_log) for s in vms + [ghost] if s["metrics"] is not None]
    metrics = finalize_metrics(vm_frames, metric_cols)
    vol_metrics = finalize_metrics([volume_frame(s) for s in vols], ["iops", "disk_used_pct"])

    inventory = inventory_frame(inventory_specs)
    truth = truth_frame(inventory_specs + [ghost])
    billing = billing_frame(inventory_specs)
    pricing = pricing_frame()
    faults = pd.DataFrame(fault_log)

    inventory.to_csv(DATA / "inventory.csv", index=False)
    truth.to_csv(DATA / "truth.csv", index=False)
    pricing.to_csv(DATA / "pricing.csv", index=False)
    faults.to_csv(DATA / "faults.csv", index=False)
    metrics.to_parquet(DATA / "metrics.parquet", compression="zstd", index=False)
    vol_metrics.to_parquet(DATA / "volume_metrics.parquet", compression="zstd", index=False)
    billing.to_parquet(DATA / "billing_daily.parquet", compression="zstd", index=False)

    # 3-resource fixture so the engine/API/UI can start before the full dataset is trusted
    fx = inventory[inventory["name"].isin(FIXTURE_NAMES)]
    ids = set(fx["resource_id"])
    fx.to_csv(DATA / "fixture" / "inventory.csv", index=False)
    truth[truth["resource_id"].isin(ids)].to_csv(DATA / "fixture" / "truth.csv", index=False)
    pricing.to_csv(DATA / "fixture" / "pricing.csv", index=False)
    m = metrics[metrics["resource_id"].isin(ids)].copy()
    m["resource_id"] = m["resource_id"].astype(str)
    m.to_parquet(DATA / "fixture" / "metrics.parquet", compression="zstd", index=False)
    v = vol_metrics[vol_metrics["resource_id"].isin(ids)].copy()
    v["resource_id"] = v["resource_id"].astype(str)
    v.to_parquet(DATA / "fixture" / "volume_metrics.parquet", compression="zstd", index=False)

    counts = inventory["type"].value_counts().to_dict()
    print(f"inventory: {counts} | metrics rows: {len(metrics):,} | volume rows: {len(vol_metrics):,} | "
          f"billing rows: {len(billing):,} | faults: {len(faults)} | bulk VMs created in-window: {k_new}")


if __name__ == "__main__":
    main()
