"""Engine against truth.csv (every planted edge case is a test), the frontend text formats, the four presets
and the cost-math rules F1-F10 (plan sections 8, 14; PLAN_frontend_integration.md §2)."""
import ast
from pathlib import Path

import pytest

from backend.api.schemas import Recommendation
from backend.engine.decide import Engine
from backend.engine.params import enabled_presets
from backend.insights.scorecard import load_truth, scorecard

TRUTH = load_truth()
PRESETS = ["max_savings", "balanced", "default", "max_performance"]


@pytest.fixture(scope="module")
def runs(ds, cfg, cleaned, features):
    return {p: Engine(cfg, ds, cleaned, features, preset=p).run() for p in PRESETS}


@pytest.fixture(scope="module")
def run(runs):
    items, below = runs["default"]
    return {i["resource"]["name"]: i for i in items}, below


@pytest.fixture(scope="module")
def R(run):
    return lambda name: run[0][name]


@pytest.mark.parametrize("t", TRUTH.to_dict("records"), ids=lambda t: f"{t['edge_case_id'] or t['archetype']}:{t['name']}")
def test_truth(run, t):
    item = run[0].get(t["name"]) or next(i for i in run[0].values() if i["resource"]["resource_id"] == t["resource_id"])
    assert (item["verdict"], item["reason_code"]) == (t["expected_verdict"], t["expected_reason_code"]), item["reason"]
    assert item["default_option"] == t["expected_action"]


def test_scorecard(run):
    sc = scorecard(list(run[0].values()))
    assert sc["correct"] == sc["total"] == 141 and sc["unsafe_downsizes"] == 0 and not sc["mismatches"]
    assert sc["mock_engine"] is False and sc["preset"] == "default"
    assert {v["verdict"] for v in sc["by_verdict"]} == {"recommend", "reject", "flag", "exclude", "healthy", "upsize"}
    assert sc["cleanup_recall"]["found"] == sc["cleanup_recall"]["expected"] > 0
    assert not sc["wrongly_shrunk"]


def test_new_codes(R, run):
    assert (R("dev-tiny-15")["verdict"], R("dev-tiny-15")["reason_code"]) == ("healthy", "BELOW_FLOOR")
    assert R("dev-tiny-15")["options"].keys() == {"none"} and run[1]["count"] == 1
    assert (R("vm-maint-08")["verdict"], R("vm-maint-08")["reason_code"]) == ("exclude", "STOPPED_RECENTLY")


def test_stray_series_item(run):
    stray = run[0]["vm-9999"]                                       # name = id (the real name is only in truth.csv)
    assert (stray["verdict"], stray["reason_code"]) == ("exclude", "NOT_IN_INVENTORY")
    assert stray["resource"]["resource_id"] == "vm-9999" and stray["current"]["monthly_inr"] == 0
    assert stray["evidence"]["metrics"] is None and stray["trace"][-1]["step"] == "inventory.exists"


@pytest.mark.parametrize("preset", PRESETS)
def test_all_presets_valid(runs, preset):
    items, _ = runs[preset]
    assert len(items) == 141
    for item in items:
        Recommendation.model_validate(item)
        assert item["rec_id"].endswith(f"-{preset}")


def test_presets_enabled(cfg):
    assert enabled_presets(cfg) == PRESETS


@pytest.mark.parametrize("preset", PRESETS)
def test_replay_safety_every_preset(runs, preset):
    for item in runs[preset][0]:
        if "resize" in item["default_option"] and item["verdict"] == "recommend":
            r = item["replay"]
            assert r["passed"] and r["chosen_plan"] == item["target"]["plan"], item["resource"]["name"]
            chosen = next(a for a in r["attempts"] if a["plan"] == r["chosen_plan"])
            assert chosen["minutes_above_90"] <= r["limit_minutes_above_90"] and chosen["max_mem_pct"] <= 95


def test_preset_differences_cp13(runs):
    """cp13 needs, between default and max_performance, a retargeted, a dropped and an unchanged recommendation."""
    d = {i["resource"]["resource_id"]: i for i in runs["default"][0]}
    m = {i["resource"]["resource_id"]: i for i in runs["max_performance"][0]}
    rec = lambda i: i["verdict"] in ("recommend", "upsize")
    both = [r for r in d if rec(d[r]) and rec(m[r])]
    retargeted = [r for r in both if (d[r]["target"] or {}).get("plan") != (m[r]["target"] or {}).get("plan")]
    unchanged = [r for r in both if r not in retargeted and d[r]["default_option"] == m[r]["default_option"]]
    dropped = [r for r in d if rec(d[r]) and not rec(m[r])]
    assert retargeted and unchanged and dropped


def test_presets_are_genuinely_different(runs):
    """Owner decision: presets also vary how wide the net of shrink candidates is (PLAN_frontend_integration §2.1)."""
    saving = lambda items: sum(i["options"][i["default_option"]]["saving_inr"] for i in items
                               if i["verdict"] == "recommend" and i["options"][i["default_option"]]["saving_inr"] > 0)
    s = {p: saving(runs[p][0]) for p in PRESETS}
    assert s["max_performance"] < s["default"] <= s["balanced"] <= s["max_savings"], s
    assert s["max_performance"] < 0.95 * s["default"]                       # clearly more cautious
    key = lambda i: (i["verdict"], i["reason_code"], i["default_option"], (i["target"] or {}).get("plan"))
    default = {i["resource"]["resource_id"]: key(i) for i in runs["default"][0]}
    for p in ("max_savings", "max_performance"):
        differs = sum(key(i) != default[i["resource"]["resource_id"]] for i in runs[p][0])
        assert differs > 3, (p, differs)
    # a wider net never makes a resize unsafe: every recommended resize in every preset passed Peak Replay
    for p in PRESETS:
        for i in runs[p][0]:
            if i["verdict"] == "recommend" and i["target"]:
                assert i["replay"]["passed"], (p, i["resource"]["name"])


def test_preset_wording_follows_the_limits(runs):
    trace = lambda p, name: next(i for i in runs[p][0] if i["resource"]["name"] == name)["trace"]
    gate = lambda p: next(s for s in trace(p, "prod-web-35") if s["step"] == "gate.looks_shrinkable")
    assert gate("default")["check"] == "mean CPU < 20% or CPU p99 < 40%"
    assert gate("max_savings")["check"] == "mean CPU < 30% or CPU p90 < 55%"
    assert gate("max_performance")["check"] == "mean CPU < 15% or CPU p99.5 < 30%"
    for p in PRESETS:                                          # no internal key leaks into any user-facing text
        for i in runs[p][0]:
            assert "p99_5" not in i["reason"] and all("p99_5" not in s["check"] + s["value"] for s in i["trace"])


def test_failed_resize_keeps_the_schedule(runs):
    """A resize that fails Peak Replay forbids resizing, not scheduling: Max savings (p90, 90% target) treats more
    dev VMs as underused, and must not lose their off-hours schedule because of it."""
    saving = lambda items: sum(i["options"][i["default_option"]]["saving_inr"] for i in items
                               if i["verdict"] == "recommend" and i["options"][i["default_option"]]["saving_inr"] > 0)
    assert saving(runs["max_savings"][0]) >= saving(runs["default"][0])
    ms = {i["resource"]["name"]: i for i in runs["max_savings"][0]}
    for name in ["dev-app-74", "dev-app-75", "dev-app-76", "dev-support-05", "dev-api-16"]:
        assert (ms[name]["verdict"], ms[name]["default_option"]) == ("recommend", "schedule"), name
    assert "Not resized" in ms["dev-app-76"]["reason"] or ms["dev-app-76"]["reason"]
    # a resize failure with no schedule to fall back on is still a reject (dev-report-02, staging-demo-10)
    assert ms["dev-report-02"]["reason_code"] == "PEAK_REPLAY_FAILED" and ms["staging-demo-10"]["verdict"] == "reject"


def test_trace_contract(run):
    for name, item in run[0].items():
        assert sum(s["terminal"] for s in item["trace"]) == 1, name
        assert item["trace"][-1]["terminal"], name
        for s in item["trace"]:
            assert isinstance(s["value"], str) and isinstance(s["threshold"], str), (name, s)
            assert s["result"] in ("pass", "fail", "info", "skip"), (name, s)


# ---- resource / evidence blocks ----------------------------------------------------------------

def test_resource_block(R):
    r = R("vm-untagged-14")["resource"]
    assert r["env"] is None and r["service_group"] is None and r["state"] == "running" and r["plan_id"] == "B3"
    assert R("dev-orphan-owner-15")["resource"]["team"] is None and R("dev-orphan-owner-15")["resource"]["owner"] == "unowned"
    assert R("prod-web-11b")["resource"]["members"] == ["prod-web-11a", "prod-web-11b", "prod-web-11c"]
    assert R("prod-api-01")["resource"]["members"] == []


def test_evidence_block(R):
    e = R("prod-batch-07")["evidence"]
    assert e["percentile_used"] == "p99" and R("dev-web-03")["evidence"]["percentile_used"] == "p95"
    assert set(e["metrics"]["cpu"]) == {"mean", "p50", "p95", "p99", "max"}
    assert e["recurring_peak"] == {"window_ist": "02:00–02:40 IST", "days": 30}
    vol = R("vol-oversized-09")["evidence"]["metrics"]
    assert vol["cpu"] is None and vol["mem"] is None and vol["disk_used"] is not None
    assert R("ip-unused-03")["evidence"]["metrics"] is None                # no telemetry
    assert R("prod-nomon-13")["evidence"]["metrics"] is None
    assert R("dev-test-12")["evidence"]["metrics"] is None                 # HISTORY_TOO_SHORT


def test_naive_and_replay_on_rejects(R):
    b = R("prod-batch-07")
    n = b["evidence"]["naive"]
    assert n["action"] == "resize" and n["target_plan"] and n["saving_inr"] > 0 and n["replay_minutes_above_90"] > 0
    assert b["replay"]["attempts"][0]["plan"] == n["target_plan"] and b["replay"]["chosen_plan"] is None
    assert b["replay"]["from_vcpu"] == 6 and b["replay"]["from_ram_gb"] == 16
    assert R("prod-search-06")["evidence"]["naive"] is not None           # flags carry it too
    assert R("vol-growing-10")["evidence"]["naive"]["action"] == "shrink_volume"
    assert R("prod-api-01")["evidence"]["naive"] is None and R("prod-api-01")["replay"] is None


def test_veto_vocabulary(R):
    v = R("prod-batch-07")["veto"]
    assert (v["metric"], v["value"], v["threshold"], v["comparator"]) == ("days with a 30-min peak > 80%", 30.0, 3.0, "≥")
    assert R("prod-cache-04")["veto"]["metric"] == "mem p99" and R("prod-cache-04")["veto"]["comparator"] == ">"
    assert R("prod-ingest-09")["veto"]["metric"] == "iops p95 % of provisioned"
    assert R("prod-gateway-03")["veto"]["metric"] == "net p95 % of bandwidth"
    assert R("prod-orders-08")["veto"]["metric"] == "sawtooth cycles"
    assert R("dev-report-02")["veto"]["metric"] == "minutes above 90% CPU"
    assert R("prod-ml-10")["veto"]["metric"] == "RAM needed (GB)"
    assert R("vol-growing-10")["veto"]["metric"] == "days until disk 85% full"
    for name in ["prod-batch-07", "prod-cache-04"]:
        assert R(name)["reason"] == R(name)["veto"]["message"]


# ---- sizing, replay and text formats ----------------------------------------------------------

def test_prod_one_step(R, run, cfg):
    assert R("prod-api-07")["target"]["plan"] == "B3"
    order = [p for p, _ in sorted(cfg.plans.items(), key=lambda kv: kv[1]["monthly_inr"])]
    for name, item in run[0].items():
        if item["target"] and "resize" in item["default_option"] and item["resource"]["env"] in ("prod", None):
            assert order.index(item["current"]["plan"]) - order.index(item["target"]["plan"]) == 1, name


def test_round_up(R):
    assert R("staging-web-08")["target"]["plan"] == "B2"


def test_service_group_sized_on_busiest(R):
    assert {R(n)["target"]["plan"] for n in ["prod-web-11a", "prod-web-11b", "prod-web-11c"]} == {"B2"}
    sizing = next(s for s in R("prod-web-11a")["trace"] if s["step"] == "sizing")
    assert "sized on prod-web-11b" in sizing["value"]


def test_schedule_text(R):
    w = R("dev-web-03")["schedule"]
    assert w["off_hours_per_week"] == 118 and w["on_hours_per_week"] == 50
    assert w["windows"] == [{"days": "Mon–Thu", "start": "19:00", "end": "09:00 (next day)"},
                            {"days": "Fri → Mon", "start": "19:00", "end": "09:00"}]
    assert R("dev-etl-04")["schedule"]["busy_hours_excluded"] == ["01:00–03:00 daily"]


def test_formula_templates(R):
    o = R("dev-web-03")["options"]
    assert o["resize+schedule"]["formula"] == ("₹6,690 B4 + ₹1,600 disk = ₹8,290 → ₹2,826 B2 × 50/168 h on + "
                                               "₹1,600 disk = ₹2,441")
    assert "× 50/168 h on" in o["schedule"]["formula"]
    assert o["resize"]["formula"].endswith("→ ₹2,826 B2 + ₹1,600 disk = ₹4,426")
    assert R("vol-orphan-11")["options"]["snapshot+delete"]["formula"] == "500 GB × ₹8 = ₹4,000 → snapshot 120 GB × ₹4 = ₹480"
    assert R("ip-unused-03")["options"]["release"]["formula"] == "₹200/month public IP → ₹0"
    assert R("dev-web-03")["formula"] == o["resize+schedule"]["formula"]


def test_recurring_peak_keeps_schedule_for_nonprod(R):
    for n in ["staging-batch-68", "dev-batch-69"]:
        assert (R(n)["verdict"], R(n)["reason_code"], R(n)["default_option"]) == ("recommend", "OFF_HOURS", "schedule")
        assert "01:00" in " ".join(R(n)["schedule"]["busy_hours_excluded"]) or R(n)["schedule"]["windows"]


def test_upsize(R):
    up = R("prod-search-02")
    assert up["target"]["plan"] == "B3" and up["options"]["upsize"]["saving_inr"] < 0 and up["replay"]["passed"]


def test_stopped_vm_billed_switch_suppresses_schedules(ds, cfg, cleaned, features):
    raw = dict(cfg.raw, billing=dict(cfg.raw["billing"], stopped_vm_billed={"value": True}))
    items, _ = Engine(type(cfg)(raw=raw, hash="x"), ds, cleaned, features).run()
    assert all(i["schedule"] is None for i in items)


def test_inventory_flags(R):
    codes = lambda n: {f["code"] for f in R(n)["flags"]}
    assert "UNTAGGED_ENV" in codes("vm-untagged-14") and R("vm-untagged-14")["target"]["plan"] == "B2"
    assert "UNOWNED" in codes("dev-orphan-owner-15")
    assert "TAG_NAME_CONFLICT" in codes("dev-misnamed-16")
    assert "MEDIUM_COVERAGE" in codes("staging-flaky-19") and R("staging-flaky-19")["risk"]["confidence"] == "Medium"


def test_actions_have_rollback(run):
    for item in run[0].values():
        assert all(isinstance(a["rollback"], str) and a["rollback"] for a in item["actions"])


# ---- cost math (F-group) ------------------------------------------------------------------------

def test_f1_combined_not_additive(R):
    o = R("dev-web-03")["options"]
    assert max(o["resize"]["saving_inr"], o["schedule"]["saving_inr"]) < o["resize+schedule"]["saving_inr"] \
        < o["resize"]["saving_inr"] + o["schedule"]["saving_inr"]


@pytest.mark.parametrize("preset", PRESETS)
def test_f5_whole_rupees(runs, preset):
    for item in runs[preset][0]:
        for o in item["options"].values():
            assert isinstance(o["monthly_inr_after"], int) and o["saving_inr"] == item["current"]["monthly_inr"] - o["monthly_inr_after"]
        assert item["options"]["none"]["monthly_inr_after"] == item["current"]["monthly_inr"]


def test_f9_headline_in_band(run):
    items = run[0].values()
    before = sum(i["current"]["monthly_inr"] for i in items)
    saving = sum(i["options"][i["default_option"]]["saving_inr"] for i in items if i["verdict"] == "recommend")
    assert 0.15 <= saving / before <= 0.35


def test_f10_group_saving_is_sum_of_members(R):
    assert sum(R(n)["options"]["resize"]["saving_inr"] for n in ["prod-web-11a", "prod-web-11b", "prod-web-11c"]) \
        == 3 * (3978 - 2826)


def test_engine_never_reads_truth():
    import backend.engine as pkg
    for path in Path(pkg.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        names = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
        assert not any("truth.csv" in s for s in strings if not s.startswith("Engine orchestrator")), path
        assert not any("truth" in n.lower() for n in names), path
