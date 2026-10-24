"""Alerts, presets, scorecard, benchmark and the generated ASSUMPTIONS.md."""
import json

from engine import assumptions as AS
from engine import data as D
from engine import presets as PR
from engine.benchmark import OUT as BENCH
from engine.config import Config

ALERT_KEYS = ["alert_id", "type", "severity", "resource_id", "title", "why", "evidence", "first_seen", "occurrences",
              "suggested_action"]


def _alerts():
    return json.loads((D.DATA / "alerts.json").read_text(encoding="utf-8"))["items"]


def test_alert_objects_follow_schema():
    for a in _alerts():
        assert list(a) == ALERT_KEYS
        assert a["severity"] in ("critical", "warning", "info")
        assert set(a["evidence"]) == {"metric", "value", "threshold", "window"}
        assert a["why"]


def test_alert_ids_unique_and_linked():
    alerts = _alerts()
    ids = [a["alert_id"] for a in alerts]
    assert len(ids) == len(set(ids))
    rec = json.loads((D.DATA / "recommendations.json").read_text(encoding="utf-8"))
    owner = {a["alert_id"]: a["resource_id"] for a in alerts}
    for i in rec["items"]:
        for x in i["alert_ids"]:
            assert owner[x] == i["resource"]["resource_id"]


def test_planted_alerts_fire():
    names = {r["resource_id"]: r["name"] for r in D.load_truth().to_dict("records")}
    got = {(a["type"], names.get(a["resource_id"])) for a in _alerts()}
    for case in (("possible_compromise", "dev-sandbox-17"), ("level_shift", "prod-worker-05"),
                 ("memory_leak", "prod-orders-08"), ("monitoring_missing", "prod-nomon-13"),
                 ("usage_spike", "prod-reports-02"), ("capacity_trend", "vol-growing-10")):
        assert case in got, case
    assert ("usage_spike", "prod-batch-07") not in got          # a scheduled peak is not a spike


def test_presets_tradeoff():
    rep = json.loads(PR.OUT.read_text())
    sav = [rep[p]["saving_inr"] for p in PR.ORDER]
    assert sav == sorted(sav)
    assert rep["default"]["backtest_unsafe"] == 0 and rep["max_performance"]["backtest_unsafe"] == 0


def test_scorecard_present():
    sc = json.loads((D.DATA / "scorecard.json").read_text())
    assert sc["rows"] == len(D.load_truth())
    assert sc["headline"]["unsafe downsizes (held-out week)"].startswith("0/")


def test_benchmark_scale():
    b = json.loads(BENCH.read_text())
    assert b["vms"] >= Config()("benchmark.target_vms")


def test_assumptions_in_sync():
    assert AS.OUT.read_text(encoding="utf-8") == AS.build()
