"""Reads data/*.csv|parquet once and returns typed frames (PLAN_final.md B2)."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .config_loader import REPO_ROOT

DATA_DIR = REPO_ROOT / "data"

TIME_COLUMNS = ["stopped_since", "created_at", "last_resized_at", "unattached_since"]
NUMERIC_COLUMNS = ["vcpu", "ram_gb", "disk_gb", "provisioned_iops", "bandwidth_mbps"]
TEXT_COLUMNS = ["resource_id", "name", "type", "region", "env", "owner_team", "purpose",
                "service_group", "plan_id", "previous_plan_id", "state", "attached_to",
                "optimize_policy", "tags"]


@dataclass(frozen=True)
class Dataset:
    inventory: pd.DataFrame        # one row per resource; text columns are "" when empty
    metrics: pd.DataFrame          # VMs, raw (uncleaned), ts UTC, resource_id str
    volume_metrics: pd.DataFrame   # volumes, raw, ts UTC
    billing: pd.DataFrame          # daily cost per resource, date = IST calendar day
    pricing: pd.DataFrame
    faults: pd.DataFrame


def parse_tags(value):
    return [t for t in str(value).split(";") if t] if value else []


def load_inventory(path):
    inv = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in TEXT_COLUMNS:
        inv[c] = inv[c].astype(object)
    for c in NUMERIC_COLUMNS:
        inv[c] = pd.to_numeric(inv[c].replace("", None), errors="coerce")
    for c in TIME_COLUMNS:
        # stored as IST ISO strings with +05:30; empty -> NaT
        inv[c] = pd.to_datetime(inv[c].replace("", None), utc=True).dt.tz_convert("Asia/Kolkata")
    inv["tags_list"] = inv["tags"].map(parse_tags)
    inv["owner"] = inv["owner_team"].where(inv["owner_team"] != "", "unowned")
    return inv


def _read_metrics(path):
    df = pd.read_parquet(path)
    df["resource_id"] = df["resource_id"].astype(str).astype(object)
    return df


def load_dataset(data_dir=DATA_DIR):
    data_dir = Path(data_dir)
    billing = pd.read_parquet(data_dir / "billing_daily.parquet")
    for c in ["resource_id", "name", "type", "team", "env", "region"]:
        billing[c] = billing[c].fillna("").astype(str).astype(object)
    return Dataset(
        inventory=load_inventory(data_dir / "inventory.csv"),
        metrics=_read_metrics(data_dir / "metrics.parquet"),
        volume_metrics=_read_metrics(data_dir / "volume_metrics.parquet"),
        billing=billing,
        pricing=pd.read_csv(data_dir / "pricing.csv"),
        faults=pd.read_csv(data_dir / "faults.csv", dtype=str, keep_default_na=False),
    )


@lru_cache(maxsize=1)
def get_dataset():
    return load_dataset()
