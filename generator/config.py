"""Every constant the generator uses. Prices are ILLUSTRATIVE (see DATASET.md)."""
import pandas as pd

SEED = 42
TZ = "Asia/Kolkata"

# 30-day metrics window, 5-minute samples
WINDOW_START = pd.Timestamp("2026-09-20 00:00", tz=TZ)   # a Sunday
STEP = "5min"
SLOTS_PER_DAY = 288
WINDOW_DAYS = 30
N_SLOTS = WINDOW_DAYS * SLOTS_PER_DAY                   # 8,640
NOW = pd.Timestamp("2026-10-20 00:00", tz=TZ)

# Billing history
BILLING_DAYS = 180
HOURS_PER_MONTH = 730
TARGET_GROWTH_RATIO = 1.40                               # month 6 / month 1

# Plan catalogue: plan_id -> (vcpu, ram_gb, monthly_inr, bandwidth_mbps, basis)
PLANS = {
    "S1": (1, 2, 705, 250, "assumption: half of B1"),
    "B1": (2, 4, 1410, 500, "modelled on Utho Basic 1 public listing (illustrative)"),
    "B2": (4, 8, 2826, 1000, "modelled on Utho Basic 2 public listing (illustrative)"),
    "B3": (6, 16, 3978, 1000, "modelled on Utho Basic 3 public listing (illustrative)"),
    "B4": (8, 32, 6690, 2000, "modelled on Utho Basic 4 public listing (illustrative)"),
    "B5": (16, 64, 13000, 2000, "assumption: fills the gap between B4 and B6"),
    "B6": (24, 96, 25962, 4000, "modelled on Utho Basic 6 public listing (illustrative)"),
}
# Billed by the provider but NOT in the catalogue (edge case D8: price unknown to the engine)
LEGACY_PLANS = {"L-OLD-4": (4, 16, 3500, 1000)}

VOLUME_INR_PER_GB = 8
SNAPSHOT_INR_PER_GB = 4
IP_INR_PER_MONTH = 200

REGIONS = ["mumbai", "bangalore", "noida"]
REGION_WEIGHTS = [0.40, 0.35, 0.25]
TEAMS = ["payments", "search", "platform", "data", "growth", "mobile"]

DEFAULT_PROVISIONED_IOPS = 3000

INVENTORY_COLUMNS = [
    "resource_id", "name", "type", "region", "env", "owner_team", "purpose", "service_group",
    "plan_id", "previous_plan_id", "vcpu", "ram_gb", "disk_gb", "provisioned_iops", "bandwidth_mbps",
    "state", "stopped_since", "created_at", "last_resized_at", "attached_to", "unattached_since",
    "optimize_policy", "tags",
]

# Fleet-level calibration targets (approximate, from published trace studies; see DATASET.md)
CALIBRATION = {
    "share_mean_cpu_below_20": (0.50, 0.85),   # Azure: most VMs have low average CPU
    "median_p95_over_mean_cpu": (1.5, 5.0),    # Azure: p95 well above mean
    "mem_cv_below_cpu_cv": True,               # Bitbrains / Google: memory steadier than CPU
    "median_cpu_p95_below": 50.0,              # Google 2011: usage far below allocation
    "random_missing_share": (0.003, 0.02),     # IBM trace study: gaps are common
}
