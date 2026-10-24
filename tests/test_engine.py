"""Engine against truth.csv (every planted edge case is a test) plus cost-math rules F1-F10 (plan sections 8, 14)."""
import pytest

from backend.api.schemas import Recommendation
from backend.engine.decide import Engine
from backend.insights.scorecard import CONTRACT_MAP, load_truth, scorecard

TRUTH = load_truth()                                             # D9 stray vm-9999 excluded: data-quality only


@pytest.fixture(scope="module")
def run(ds, cfg, cleaned, features):
    items, below = Engine(cfg, ds, cleaned, features).run()
    return {i["resource"]["name"]: i for i in items}, below


@pytest.fixture(scope="module")
def R(run):
    return lambda name: run[0][name]


@pytest.mark.parametrize("t", TRUTH.to_dict("records"), ids=lambda t: f"{t['edge_case_id'] or t['archetype']}:{t['name']}")
def test_truth(run, t):
    item = run[0][t["name"]]
    verdict, code = CONTRACT_MAP.get(t["expected_reason_code"], (t["expected_verdict"], t["expected_reason_code"]))
    assert (item["verdict"], item["reason_code"]) == (verdict, code), item["reason"]
    assert item["default_option"] == t["expected_action"]


def test_scorecard(run):
    sc = scorecard(list(run[0].values()))
    assert sc["matched"] == sc["total"] == 140 and sc["unsafe_downsizes"] == 0 and not sc["mismatches"]
    assert sc["by_verdict"]["recommend"]["precision"] == 1.0
    found, total = sc["waste_found"].split(" ")[0].split("/")
    assert found == total and int(total) >= 10


def test_contract_gap_cases(R, run):
    assert R("dev-tiny-15")["options"].keys() == {"none"} and run[1]["count"] >= 1
    assert any(fl["code"] == "STOPPED_RECENTLY" for fl in R("vm-maint-08")["flags"])


def test_all_items_validate(run):
    assert len(run[0]) == 140
    for item in run[0].values():
        Recommendation.model_validate(item)


def test_trace_has_one_terminal_step(run):
    for name, item in run[0].items():
        assert item["trace"], name
        assert sum(s["terminal"] for s in item["trace"]) == 1, name
        assert item["trace"][-1]["terminal"], name


# ---- sizing and replay (A-group) ---------------------------------------------------------------

def test_prod_one_step(R):
    assert R("prod-api-07")["target"]["plan"] == "B3"                 # A2: B2 fits, prod moves one step
    assert all(R(n)["target"]["plan"] == "B4" for n in ["prod-svc-46", "prod-svc-47", "prod-svc-48", "prod-svc-51"])


def test_round_up(R):
    assert R("staging-web-08")["target"]["plan"] == "B2"              # A20: needs ~3 vCPU -> 4


def test_service_group_same_target(R):
    plans = {R(n)["target"]["plan"] for n in ["prod-web-11a", "prod-web-11b", "prod-web-11c"]}
    assert plans == {"B2"}
    assert "busiest member prod-web-11b" in R("prod-web-11a")["trace"][-4]["check"] or \
        any("prod-web-11b" in s["check"] for s in R("prod-web-11a")["trace"])


def test_replay_never_lets_an_unsafe_resize_through(run):
    for name, item in run[0].items():
        if "resize" in item["default_option"]:
            r = item["replay"]
            assert r["passed"] and r["chosen_plan"] == item["target"]["plan"], name
            chosen = next(a for a in r["attempts"] if a["plan"] == r["chosen_plan"])
            assert chosen["minutes_above_90"] <= r["limit_minutes_above_90"] and chosen["max_mem_pct"] <= 95, name


def test_replay_failure_shows_minutes(R):
    rep = R("dev-report-02")
    assert rep["replay"]["attempts"][0]["plan"] == "B1" and rep["replay"]["attempts"][0]["minutes_above_90"] > 30
    assert rep["veto"]["signal"] == "replay"
    queue = R("prod-queue-02")
    assert queue["evidence"]["naive"]["action"] == "resize" and queue["replay"]["attempts"][0]["minutes_above_90"] > 0


def test_recurring_peak_evidence(R):
    batch = R("prod-batch-07")
    assert batch["evidence"]["recurring_peak"]["weeks"] >= 4
    assert batch["evidence"]["naive"]["would_save_inr"] > 0           # an average-based tool would cut it
    assert batch["veto"]["signal"] == "recurring_peak" and "daily 02:00" in batch["reason"]
    assert "Sun" in R("prod-billing-01")["reason"]


def test_upsize(R):
    up = R("prod-search-02")
    assert up["target"]["plan"] == "B3" and up["options"]["upsize"]["saving_inr"] < 0
    assert up["replay"]["passed"] and up["risk"] is not None


# ---- scheduling (B-group) ---------------------------------------------------------------------

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def off_set(item):
    """Hours of week (Mon 00:00 = 0) covered by the schedule windows."""
    out = set()
    for w in item["schedule"]["windows"]:
        d0 = w["days"].split("→")[0]
        start = DAYS.index(d0) * 24 + int(w["start"][:2])
        h = start
        while True:
            out.add(h % 168)
            h += 1
            if h % 24 == int(w["end"][:2]) and ("→" not in w["days"] or DAYS[(h % 168) // 24] == w["days"].split("→")[1]):
                break
    return out


def hw(day, hour):
    return DAYS.index(day) * 24 + hour


def test_dev_web_03_resize_and_schedule(R):
    w = R("dev-web-03")
    assert w["target"]["plan"] == "B2" and w["schedule"]["off_hours_per_week"] >= 100
    assert set(w["options"]) == {"none", "resize", "schedule", "resize+schedule"}
    off = off_set(w)
    assert hw("Tue", 23) in off and hw("Sat", 14) in off and hw("Tue", 14) not in off
    assert len(off) == w["schedule"]["off_hours_per_week"]


def test_nightly_job_kept_on(R):
    etl = R("dev-etl-04")
    assert any("01:00-03:00" in b for b in etl["schedule"]["busy_hours_excluded"])
    off = off_set(etl)
    assert all(hw(d, h) not in off for d in DAYS for h in (1, 2))      # B5: job window stays on
    assert hw("Wed", 23) in off


def test_night_shift_gets_daytime_window(R):
    off = off_set(R("dev-support-05"))
    assert hw("Wed", 13) in off and hw("Wed", 23) not in off and hw("Wed", 2) not in off


def test_weekend_load_test_runs_weekends(R):
    off = off_set(R("staging-load-06"))
    assert hw("Tue", 12) in off and hw("Sat", 14) not in off and hw("Sun", 14) not in off


def test_no_schedule_for_prod_or_keep_running(run):
    for name, item in run[0].items():
        if item["schedule"] is not None:
            assert item["resource"]["env"] in ("dev", "staging"), name
    assert R_schedule_absent(run, "staging-demo-10")


def R_schedule_absent(run, name):
    return run[0][name]["schedule"] is None


def test_stopped_vm_billed_switch_suppresses_schedules(ds, cfg, cleaned, features):
    raw = dict(cfg.raw, billing=dict(cfg.raw["billing"], stopped_vm_billed={"value": True}))
    on = type(cfg)(raw=raw, hash="x")
    items, _ = Engine(on, ds, cleaned, features).run()
    assert all(i["schedule"] is None for i in items)


# ---- non-compute (C-group) --------------------------------------------------------------------

def test_orphan_volume_saving_minus_snapshot(R):
    o = R("vol-orphan-11")["options"]["snapshot+delete"]
    assert o["monthly_inr_after"] == 480 and o["saving_inr"] == 4000 - 480      # F3


def test_oversized_volume_target(R):
    assert R("vol-oversized-09")["options"]["shrink_volume"]["monthly_inr_after"] == 800


def test_ip_release(R):
    assert R("ip-unused-03")["options"]["release"]["saving_inr"] == 200


# ---- flags and confidence (D/E-groups) ------------------------------------------------------------

def codes(item):
    return {f["code"] for f in item["flags"]}


def test_inventory_flags(R):
    assert "UNTAGGED_ENV" in codes(R("vm-untagged-14")) and R("vm-untagged-14")["target"]["plan"] == "B2"
    assert "UNOWNED" in codes(R("dev-orphan-owner-15"))
    assert "TAG_NAME_CONFLICT" in codes(R("dev-misnamed-16"))
    flaky = R("staging-flaky-19")
    assert "MEDIUM_COVERAGE" in codes(flaky) and flaky["risk"]["confidence"] == "Medium"


def test_no_telemetry_metrics_null(R):
    assert R("prod-nomon-13")["evidence"]["metrics"] is None
    assert R("dev-test-12")["evidence"]["metrics"] is None


# ---- cost math (F-group) ------------------------------------------------------------------------

def test_f1_combined_not_additive(R):
    o = R("dev-web-03")["options"]
    assert o["resize+schedule"]["saving_inr"] < o["resize"]["saving_inr"] + o["schedule"]["saving_inr"]
    assert o["resize+schedule"]["saving_inr"] > max(o["resize"]["saving_inr"], o["schedule"]["saving_inr"])


def test_f5_whole_rupees_and_total_is_card_sum(run):
    before = after = 0
    for item in run[0].values():
        for o in item["options"].values():
            assert isinstance(o["monthly_inr_after"], int) and isinstance(o["saving_inr"], int)
            assert o["saving_inr"] == item["current"]["monthly_inr"] - o["monthly_inr_after"]
        before += item["current"]["monthly_inr"]
        after += item["options"][item["default_option"]]["monthly_inr_after"]
    savings = sum(i["options"][i["default_option"]]["saving_inr"] for i in run[0].values())
    assert before - after == savings


def test_f6_schedule_saves_compute_only(R):
    w = R("dev-web-03")
    on = w["schedule"]["on_hours_per_week"]
    expected = round(w["current"]["compute_inr"] * on / 168) + w["current"]["storage_inr"]
    assert w["options"]["schedule"]["monthly_inr_after"] == expected
    assert "disk" in w["options"]["schedule"]["formula"]


def test_f9_headline_in_band(run):
    items = run[0].values()
    before = sum(i["current"]["monthly_inr"] for i in items)
    saving = sum(i["options"][i["default_option"]]["saving_inr"] for i in items if i["verdict"] == "recommend")
    assert 0.15 <= saving / before <= 0.35, saving / before


def test_f10_group_saving_is_sum_of_members(R):
    total = sum(R(n)["options"]["resize"]["saving_inr"] for n in ["prod-web-11a", "prod-web-11b", "prod-web-11c"])
    assert total == 3 * (3978 - 2826)


def test_engine_never_reads_truth():
    import ast
    from pathlib import Path

    import backend.engine as pkg
    for path in Path(pkg.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        names = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
        assert not any("truth.csv" in s for s in strings if not s.startswith("Engine orchestrator")), path
        assert not any("truth" in n.lower() for n in names), path
