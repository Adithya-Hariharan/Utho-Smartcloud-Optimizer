"""Checkpoint 4: cost model (PLAN_final.md B3, B8.4)."""
import pytest

from backend.cost.model import (breakdown, current_cost, daily_from_monthly, fleet_costs, format_inr,
                                no_change_option, option, scheduled_compute)


@pytest.fixture(scope="module")
def costs(ds, cfg):
    return fleet_costs(ds, cfg)


@pytest.fixture(scope="module")
def C(costs):
    by_name = costs.set_index("name")
    return lambda name: by_name.loc[name]


def test_format_inr():
    assert format_inr(657302) == "₹6,57,302"
    assert format_inr(123456789) == "₹12,34,56,789"
    assert format_inr(999) == "₹999"
    assert format_inr(-2712) == "-₹2,712"


def test_vm_cost_identity(C):
    c = C("prod-api-01")                                      # B4, 100 GB boot disk
    assert (c.compute_inr, c.storage_inr, c.ip_inr, c.monthly_inr) == (6690, 800, 0, 7490)


def test_stopped_vm_pays_disk_only(C):
    for name in ["vm-stopped-07", "vm-maint-08"]:
        c = C(name)
        assert c.compute_inr == 0 and c.monthly_inr == c.storage_inr


def test_stopped_vm_billed_switch(ds, cfg):
    row = ds.inventory.set_index("name").loc["vm-stopped-07"].copy()
    raw = dict(cfg.raw, billing=dict(cfg.raw["billing"], stopped_vm_billed={"value": True}))
    on = type(cfg)(raw=raw, hash="x")
    assert current_cost(row, on)["compute_inr"] == cfg.plan_price(row["plan_id"])


def test_volume_and_ip(C, ds, cfg):
    v = C("vol-oversized-09")
    assert (v.storage_inr, v.monthly_inr) == (4000, 4000)
    block = current_cost(ds.inventory.set_index("name").loc["vol-oversized-09"], cfg)
    assert block["plan"] is None and block["vcpu"] is None and block["disk_gb"] == 500
    ip = C("ip-unused-03")
    assert (ip.ip_inr, ip.storage_inr, ip.monthly_inr) == (200, 0, 200)


def test_legacy_plan_uses_billing_rate(C):
    assert C("prod-legacy-plan-17").compute_inr == 3500


def test_resized_vm_costs_current_plan(C):
    assert C("staging-app-05").compute_inr == 3978          # B3 after the resize


def test_every_figure_is_whole_rupees(costs):
    for c in ["compute_inr", "storage_inr", "ip_inr", "monthly_inr"]:
        assert costs[c].map(lambda x: float(x).is_integer()).all()
    assert (costs.monthly_inr == costs.compute_inr + costs.storage_inr + costs.ip_inr).all()


def test_sum_matches_last_billing_day(costs, ds, cfg):
    last = ds.billing[ds.billing["date"] == ds.billing["date"].max()].set_index("resource_id")["cost_inr"]
    per = costs.set_index("resource_id")["monthly_inr"]
    assert set(last.index) == set(per.index)
    expected = last * cfg.get("billing.hours_per_month") / 24
    assert (expected - per.loc[expected.index]).abs().max() <= 1
    assert abs(expected.sum() - per.sum()) <= len(per)


def test_daily_conversion(cfg):
    assert daily_from_monthly(730, cfg) == pytest.approx(24)


def test_options():
    o = option(6690, 3978)
    assert o == {"monthly_inr_after": 3978, "saving_inr": 2712, "formula": "₹6,690 − ₹3,978 = ₹2,712/month"}
    n = no_change_option(7490)
    assert n["saving_inr"] == 0 and n["formula"] == "₹7,490/month, no change"
    assert scheduled_compute(2826, 60) == 1009


def test_breakdowns(costs):
    env = breakdown(costs, "env")
    assert "untagged" in env and "" not in env
    team = breakdown(costs, "team")
    assert "unowned" in team
    assert sum(env.values()) == sum(team.values()) == int(costs.monthly_inr.sum())
