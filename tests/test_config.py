"""Checkpoint 1: config.yaml, loader and data access (PLAN_final.md B8.1)."""
import pandas as pd

from backend.config_loader import CONFIG_PATH, config_hash, load_config


def test_config_hash_stable_across_loads(cfg):
    again = load_config(CONFIG_PATH)
    assert again.hash == cfg.hash == config_hash(again.raw)
    assert len(cfg.hash) == 64


def test_hash_changes_when_config_changes(cfg):
    changed = dict(cfg.raw, schema_version="9.9")
    assert config_hash(changed) != cfg.hash


def test_plan_prices_match_pricing_csv(cfg, ds):
    plans = ds.pricing[ds.pricing["kind"] == "vm_plan"].set_index("item")
    assert set(plans.index) == set(cfg.plans)
    for pid, p in cfg.plans.items():
        row = plans.loc[pid]
        assert int(row["monthly_inr"]) == p["monthly_inr"]
        assert int(row["vcpu"]) == p["vcpu"]
        assert int(row["ram_gb"]) == p["ram_gb"]
        assert int(row["bandwidth_mbps"]) == p["bandwidth_mbps"]


def test_storage_and_ip_rates_match_pricing_csv(cfg, ds):
    rates = ds.pricing.set_index("item")["monthly_inr"]
    assert rates["block_volume"] == cfg.get("pricing.volume_inr_per_gb_month")
    assert rates["snapshot"] == cfg.get("pricing.snapshot_inr_per_gb_month")
    assert rates["public_ip"] == cfg.get("pricing.ip_inr_per_month")


def test_window_and_now(cfg):
    assert cfg.window_start == pd.Timestamp("2026-09-20 00:00", tz="Asia/Kolkata")
    assert cfg.window_end == pd.Timestamp("2026-10-19 23:55", tz="Asia/Kolkata")
    assert cfg.now == pd.Timestamp("2026-10-20 00:00", tz="Asia/Kolkata")
    assert cfg.slots == 8640
    assert cfg.get("billing.hours_per_month") == 730
    assert cfg.get("billing.stopped_vm_billed") is False


def test_plan_price_includes_billing_only_legacy(cfg):
    assert cfg.plan_price("B3") == 3978
    assert cfg.plan_price("L-OLD-4") == 3500
    assert cfg.plan_price("NOPE") is None
    assert "L-OLD-4" not in cfg.plans


def test_inventory_counts_and_types(ds):
    counts = ds.inventory["type"].value_counts().to_dict()
    assert counts == {"vm": 117, "volume": 15, "ip": 8}
    assert ds.inventory["resource_id"].is_unique


def test_inventory_parsing(ds, name_to_id):
    inv = ds.inventory.set_index("name")
    assert str(inv["created_at"].dt.tz) == "Asia/Kolkata"
    assert inv.loc["vm-untagged-14", "env"] == ""
    assert inv.loc["dev-orphan-owner-15", "owner"] == "unowned"
    assert "dr_standby" in inv.loc["prod-standby-01", "tags_list"]
    assert all(isinstance(t, list) for t in inv["tags_list"])
    assert pd.isna(inv.loc["prod-api-01", "stopped_since"])
    assert "previous_plan_id" in ds.inventory.columns


def test_metrics_frames(ds):
    assert ds.metrics["resource_id"].map(type).eq(str).all()
    assert str(ds.metrics["ts"].dt.tz) == "UTC"
    assert list(ds.volume_metrics.columns) == ["resource_id", "ts", "iops", "disk_used_pct"]
    assert ds.billing["date"].nunique() == 180
