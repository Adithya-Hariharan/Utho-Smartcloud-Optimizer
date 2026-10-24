"""Engine building blocks: params, sizing, Peak Replay, off-hours schedule, risk (plan section 7)."""
import numpy as np
import pytest

from backend.engine.candidates import off_hour_mask, schedule
from backend.engine.params import PresetNotEnabled, enabled_presets, params_for
from backend.engine.replay import attempt, search
from backend.engine.risk import risk
from backend.engine.sizing import catalogue, cheapest_fit, needs, size


@pytest.fixture(scope="module")
def cat(cfg):
    return catalogue(cfg)


def plan(cat, pid):
    return next(p for p in cat if p.plan_id == pid)


def test_params_four_presets(cfg):
    p = params_for(cfg)
    assert (p.pct(True), p.pct(False), p.cpu_target(True), p.replay_limit(True)) == (99, 95, 70, 0)
    assert p.pct_label(True) == "p99" and p.pct_label(False) == "p95"
    # default preset mirrors the threshold table
    assert p.pct_prod == cfg.get("thresholds.percentile_prod") and p.cpu_target_nonprod == cfg.get("thresholds.cpu_target_nonprod_pct")
    expected = {"max_savings": (90, 90, 90, 90, 60, 60), "balanced": (95, 95, 80, 80, 30, 30),
                "default": (99, 95, 70, 80, 0, 30), "max_performance": (99.5, 99.5, 60, 60, 0, 0)}
    assert enabled_presets(cfg) == list(expected)
    for name, vals in expected.items():
        q = params_for(cfg, name)
        assert (q.pct_prod, q.pct_nonprod, q.cpu_target_prod, q.cpu_target_nonprod, q.replay_limit_prod,
                q.replay_limit_nonprod) == vals
        assert (q.mem_target, q.mem_cap) == (75, 95)
    assert params_for(cfg, "max_performance").pct_label(True) == "p99.5"
    assert params_for(cfg, "max_performance").pct_key(True) == "p99_5"
    with pytest.raises(PresetNotEnabled):
        params_for(cfg, "nope")


def test_new_config_sections(cfg):
    c = cfg.raw["carbon"]
    assert c["placeholder"] is True and "PLACEHOLDER" in c["source"]
    assert (c["w_per_vcpu_min"], c["w_per_vcpu_max"], c["w_per_gb_ram"], c["pue"], c["kg_co2_per_kwh"]) == (0.74, 3.5, 0.392, 1.4, 0.71)
    assert cfg.get("forecast.alpha") == 0.3 and cfg.get("forecast.season_days") == 7
    assert cfg.get("whatif.busy_cpu_pct") == 5 and cfg.get("metrics.gap_min_slots") == 6
    assert cfg.get("thresholds.comparisons") == "strict < / >"
    names = [r["name"] for r in cfg.raw["assumptions_table"]]
    assert "Saving floor" in names and "Comparisons" in names


def test_catalogue_ordered_by_price(cat):
    assert [p.plan_id for p in cat] == ["S1", "B1", "B2", "B3", "B4", "B5", "B6"]


def test_round_up_between_plans(cat):
    v, r = needs(8, 32, 30.5, 15.1, 80, 75)                         # staging-web-08: needs ~3 vCPU
    assert cheapest_fit(cat, v, r).plan_id == "B2"                  # 4 vCPU, not 2


def test_memory_blocks_cheaper_plan(cat):
    v, r = needs(8, 32, 11.6, 44.9, 70, 75)                         # prod-ml-10
    assert cheapest_fit(cat, v, r).plan_id == "B4"


def test_prod_one_step(cat):
    target, note = size(cat, "B4", 3.5, 4, prod=True)
    assert target.plan_id == "B3" and "one-step" in note
    assert size(cat, "B4", 3.5, 4, prod=False)[0].plan_id == "B2"


def test_replay_scales_and_counts_minutes(cat):
    cpu = np.full(8640, 10.0)
    cpu[:12] = 60.0                                                 # one hour at 60%
    mem = np.full(8640, 20.0)
    a = attempt(cpu, mem, 4, 8, plan(cat, "B1"), 30, 95)            # halve vCPU: 120% for 60 min
    assert a["minutes_above_90"] == 60 and a["max_cpu_pct"] == 120.0 and a["max_mem_pct"] == 40.0
    assert not a["passed"]
    assert attempt(cpu, mem, 4, 8, plan(cat, "B1"), 60, 95)["passed"]


def test_replay_search_tries_bigger_cheaper_plans(cat):
    cpu = np.full(8640, 40.0)
    mem = np.full(8640, 10.0)
    block, chosen = search(cpu, mem, 8, 32, plan(cat, "B1"), cat, 6690, 0, 95)
    assert [a["plan"] for a in block["attempts"]] == ["B1", "B2"] and chosen.plan_id == "B2"
    block, chosen = search(np.full(8640, 95.0), mem, 4, 8, plan(cat, "B1"), cat, 2826, 0, 95)
    assert chosen is None and not block["passed"]                   # B2 is today's plan: never tried


def week(off_hours, busy=30.0, quiet=1.0):
    row = [busy] * 168
    for h in off_hours:
        row[h] = quiet
    return row


def test_schedule_office_hours():
    off = [h for h in range(168) if (h // 24 >= 5) or (h % 24 >= 20) or (h % 24 < 8)]
    sched, _ = schedule([week(off)] * 4, 5, 4, 40, "Asia/Kolkata")
    assert sched["off_hours_per_week"] == 108 and sched["on_hours_per_week"] == 60
    assert {"days": "Fri → Mon", "start": "20:00", "end": "08:00"} in sched["windows"]
    assert {"days": "Mon–Thu", "start": "20:00", "end": "08:00 (next day)"} in sched["windows"]


def test_schedule_keeps_nightly_job_on():
    off = [h for h in range(168) if (h % 24 >= 20) or (h % 24 < 8)]
    off = [h for h in off if h % 24 not in (1, 2)]                  # job 01:00-03:00
    sched, _ = schedule([week(off)] * 4, 5, 4, 40, "Asia/Kolkata")
    assert sched["busy_hours_excluded"] == ["01:00–03:00 daily"]
    assert {"days": "Mon–Sun", "start": "20:00", "end": "01:00 (next day)"} in sched["windows"]
    assert {"days": "Mon–Sun", "start": "03:00", "end": "08:00"} in sched["windows"]
    assert sched["off_hours_per_week"] == 70


def test_schedule_fragmented_rejected():
    off = [h for h in range(168) if h % 3 == 0]                     # 1-hour blocks
    sched, why = schedule([week(off)] * 4, 5, 4, 40, "Asia/Kolkata")
    assert sched is None and "< 40" in why


def test_off_hour_needs_every_week():
    w1, w2 = week([3]), week([])                                    # hour 3 quiet in one week only
    assert not off_hour_mask([w1, w2], 5)[3]
    assert off_hour_mask([w1, w1], 5)[3]


def test_risk_points_and_buckets():
    r = risk("prod", False, 75, 80, 10, ["resize"], 0.9, 0.05, 0.10)
    assert r["score"] == 3 + 2 + 1 + 1 and r["level"] == "High" and r["confidence"] == "Medium"
    r = risk("dev", False, 30, 20, 10, ["schedule"], 0.99, 0.05, 0.10)
    assert r["score"] == 0 and r["level"] == "Low" and r["confidence"] == "High"
    assert risk("staging", True, None, None, None, ["snapshot", "stop"], 0.99, None, 0.1)["score"] == 1 + 2 + 1
