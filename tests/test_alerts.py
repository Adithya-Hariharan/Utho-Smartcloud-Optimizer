"""Alerts and growth (PLAN_final.md B5, B8.7) in the frontend's vocabulary (PLAN_frontend_integration.md E6, E7)."""
import pytest

from backend.api.schemas import Alert
from backend.insights.alerts import compute_alerts
from backend.insights.growth import bill_trend, growth_waterfall

CHART_METRICS = {"cpu_pct", "cpu_p95_slope", "cpu_p99", "mem_pct", "disk_used_pct", "net_out_mbps"}  # Alerts.tsx


@pytest.fixture(scope="module")
def alerts(ds, cfg, cleaned, features):
    return compute_alerts(cleaned, features, ds, cfg)


@pytest.fixture(scope="module")
def fired(alerts):
    out = {}
    for a in alerts:
        out.setdefault(a["type"], set()).add(a["name"])
    return out


def test_all_alerts_validate_and_unique(alerts):
    for a in alerts:
        Alert.model_validate(a)
        assert ":" not in a["alert_id"]
    assert len({a["alert_id"] for a in alerts}) == len(alerts)
    assert len({(a["resource_id"] or a["name"], a["type"]) for a in alerts}) == len(alerts)


def test_sorted_critical_first(alerts):
    order = {"critical": 0, "warning": 1, "info": 2}
    keys = [(order[a["severity"]], a["alert_id"]) for a in alerts]
    assert keys == sorted(keys) and alerts[0]["severity"] == "critical"


def test_chart_metrics(alerts):
    for a in alerts:
        if a["type"] not in ("monitoring_missing", "orphan_series", "team_cost_jump"):
            assert a["evidence"]["metric"] in CHART_METRICS, a
            assert a["window"] and a["window"]["start"] < a["window"]["end"], a


def test_spike(fired):
    assert "prod-reports-02" in fired["spike"]
    assert "prod-batch-07" not in fired["spike"]                     # G2: usual-hour batch is not a spike


def test_level_shift(fired, alerts):
    assert {"prod-worker-05", "dev-sandbox-17"} <= fired["level_shift"]
    worker = next(a for a in alerts if a["type"] == "level_shift" and a["name"] == "prod-worker-05")
    assert worker["severity"] == "critical"


def test_compromise_only_sandbox(fired, alerts):
    assert fired["possible_compromise"] == {"dev-sandbox-17"}
    a = next(a for a in alerts if a["type"] == "possible_compromise")
    assert a["severity"] == "critical" and "network out is" in a["why"] and a["evidence"]["metric"] == "net_out_mbps"


def test_capacity_exact_set(fired, alerts):
    assert fired["capacity"] == {"prod-api-04", "vol-growing-10", "prod-web-31", "prod-api-32", "prod-search-33",
                                 "prod-checkout-34"}
    api04 = next(a for a in alerts if a["type"] == "capacity" and a["name"] == "prod-api-04")
    assert "days to 90%" in api04["title"] and api04["evidence"]["metric"] == "cpu_p95_slope"
    vol = next(a for a in alerts if a["name"] == "vol-growing-10")
    assert vol["title"].startswith("Volume filling") and vol["evidence"]["metric"] == "disk_used_pct"


def test_memory_leak(fired):
    assert fired["memory_leak"] == {"prod-orders-08"}


def test_team_cost_jump(alerts):
    g7 = {a["name"]: a for a in alerts if a["type"] == "team_cost_jump"}
    assert set(g7) == {"team growth", "team mobile"}
    assert all(a["resource_id"] is None and a["window"] is None for a in g7.values())
    assert g7["team growth"]["first_seen"].startswith("2026-10-12")
    assert g7["team mobile"]["first_seen"].startswith("2026-10-17")
    assert "New resources:" in g7["team mobile"]["why"] and "dev-test-12" in g7["team mobile"]["why"]


def test_under_provisioned(fired):
    assert "prod-search-02" in fired["under_provisioned"]
    assert not {"prod-batch-07", "prod-billing-01", "prod-reports-02"} & fired["under_provisioned"]


def test_monitoring_missing_and_orphan(fired, alerts):
    assert fired["monitoring_missing"] == {"prod-nomon-13"}
    orphan = [a for a in alerts if a["type"] == "orphan_series"]
    assert len(orphan) == 1 and orphan[0]["resource_id"] == "vm-9999" and orphan[0]["name"] == "vm-9999"
    assert orphan[0]["severity"] == "info"


def test_bill_trend_and_waterfall(ds, cleaned):
    t = bill_trend(ds.billing)
    assert len(t["dates"]) == len(t["total"]) == 180
    assert set(t["by_env"]) == {"dev", "prod", "staging", "untagged"}
    for d in range(180):
        assert sum(v[d] for v in t["by_env"].values()) == pytest.approx(t["total"][d], abs=0.05)
    monthly = {r: 0 for r in ds.inventory["resource_id"]}
    w = growth_waterfall(ds.billing, ds.inventory, monthly)
    delta = w["last30"]["total_inr"] - w["first30"]["total_inr"]
    for k in ("by_env", "by_team", "by_age"):
        assert abs(sum(r["delta_inr"] for r in w[k]) - delta) <= len(w[k])          # rule 8 (rounding per row)
        assert [r["delta_inr"] for r in w[k]] == sorted((r["delta_inr"] for r in w[k]), reverse=True)
    assert 1.35 <= w["growth_ratio"] <= 1.45
    assert {r["key"] for r in w["by_age"]} == {"new resources", "existing resources"}
