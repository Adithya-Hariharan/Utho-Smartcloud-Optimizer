"""Checkpoint 7: alerts and growth (PLAN_final.md B5, B8.7)."""
import pytest

from backend.api.schemas import Alert
from backend.insights.alerts import compute_alerts
from backend.insights.growth import bill_trend_6m, growth_waterfall


@pytest.fixture(scope="module")
def alerts(ds, cfg, cleaned, features):
    return compute_alerts(cleaned, features, ds, cfg)


@pytest.fixture(scope="module")
def fired(alerts, ds):
    names = dict(zip(ds.inventory.resource_id, ds.inventory.name))
    out = {}
    for a in alerts:
        out.setdefault(a["type"], set()).add(names.get(a["resource_id"], a["resource_id"]))
    return out


def test_all_alerts_validate_and_unique(alerts):
    for a in alerts:
        Alert.model_validate(a)
    keys = [(a["resource_id"], a["type"]) for a in alerts]
    assert len(keys) == len(set(keys))
    assert len({a["alert_id"] for a in alerts}) == len(alerts)


def test_sorted_by_severity_then_first_seen(alerts):
    order = {"Critical": 0, "Warning": 1, "Info": 2}
    keys = [(order[a["severity"]], a["first_seen"]) for a in alerts]
    assert keys == sorted(keys)


def test_g1_spike(fired):
    assert "prod-reports-02" in fired["G1"]
    assert "prod-batch-07" not in fired["G1"]                    # G2: usual-hour batch is not a spike


def test_g3_level_shift(fired, alerts):
    assert {"prod-worker-05", "dev-sandbox-17"} <= fired["G3"]
    sev = {a["resource_id"]: a["severity"] for a in alerts if a["type"] == "G3"}
    assert "Critical" in sev.values()                            # prod-worker-05 is prod


def test_g4_compromise_only_sandbox(fired, alerts):
    assert fired["G4"] == {"dev-sandbox-17"}
    assert all(a["severity"] == "Critical" for a in alerts if a["type"] == "G4")


def test_g5_capacity_exact_set(fired):
    # B9a.1 resolved: the R² check drops the weekend-only staging-load-06
    assert fired["G5"] == {"prod-api-04", "vol-growing-10",
                           "prod-web-31", "prod-api-32", "prod-search-33", "prod-checkout-34"}


def test_g6_leak_only_the_sawtooth(fired):
    # B9a.3 resolved: a memory drop together with a CPU drop (batch ending) is not a leak reset
    assert fired["G6"] == {"prod-orders-08"}


def test_g7_team_jump(alerts):
    g7 = {a["resource_id"]: a for a in alerts if a["type"] == "G7"}
    assert set(g7) == {"team:growth", "team:mobile"}
    assert g7["team:growth"]["first_seen"].startswith("2026-10-12")
    assert g7["team:mobile"]["first_seen"].startswith("2026-10-17")
    assert "dev-test-12" in g7["team:mobile"]["why"]


def test_g9_under_provisioned(fired):
    assert "prod-search-02" in fired["G9"]
    assert not {"prod-batch-07", "prod-billing-01", "prod-reports-02"} & fired["G9"]


def test_g10_monitoring_missing(fired):
    assert fired["G10"] == {"prod-nomon-13"}                     # vm-stopped-07 is stopped, not missing


def test_no_g8(fired):
    assert "G8" not in fired


def test_bill_trend_and_waterfall(ds):
    trend = bill_trend_6m(ds.billing)
    assert len(trend) == 6
    assert 1.35 <= trend[-1]["total_inr"] / trend[0]["total_inr"] <= 1.45
    steps = growth_waterfall(ds.billing, trend)
    assert sum(s["delta_inr"] for s in steps) == trend[-1]["total_inr"] - trend[0]["total_inr"]
    assert steps[-1]["group"] == "existing"
    assert all("/" in s["group"] for s in steps[:-1])
    assert len({s["group"] for s in steps}) == len(steps)
