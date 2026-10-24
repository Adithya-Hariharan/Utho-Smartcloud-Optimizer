"""Checkpoint 5: Pydantic models of the frozen §4.5 schema + the stub item (PLAN_final.md B6, B8.5)."""
import copy

import pytest
from pydantic import ValidationError

from backend.api.schemas import Alert, Recommendation, RecommendationEnvelope, Summary
from backend.api.stub import envelope, stub_items

LEAF = {"p50": 4.1, "p95": 9.8, "p99": 12.0, "max": 20.0}
COST = {"plan": "B4", "vcpu": 8, "ram_gb": 32, "disk_gb": 100, "compute_inr": 6690, "storage_inr": 800,
        "ip_inr": 0, "monthly_inr": 7490}
RISK = {"level": "Low", "score": 1, "points": [{"factor": "env", "points": 0, "detail": "dev +0"}],
        "confidence": "High", "confidence_basis": "coverage 99%"}
VETO = {"signal": "memory", "metric": "mem_p99", "value": 85.0, "threshold": 70.0, "comparator": ">",
        "message": "memory-bound"}


def base_item(verdict, code, **over):
    item = {
        "rec_id": "REC-vm-0007-default",
        "resource": {"resource_id": "vm-0007", "name": "dev-web-03", "type": "vm", "env": "dev", "team": "growth",
                     "owner": "growth", "region": "mumbai", "purpose": "web", "service_group": "", "members": [],
                     "tags": []},
        "verdict": verdict, "reason_code": code, "actions": [], "default_option": "none", "flags": [],
        "current": COST, "target": None, "schedule": None,
        "options": {"none": {"monthly_inr_after": 7490, "saving_inr": 0, "formula": "₹7,490/month, no change"}},
        "evidence": {"window_days": 30, "days_of_data": 30, "coverage": 0.99, "peak_window_coverage": 0.95,
                     "percentile_used": 95, "metrics": {k: LEAF for k in ("cpu", "mem", "iops_pct", "net_pct", "disk_used")},
                     "recurring_peak": None, "naive": None},
        "replay": None, "veto": None, "risk": None, "reason": "r", "explanation_ai": None, "formula": "f",
        "trace": [{"step": "gate.history", "check": "days_of_data", "value": 30, "threshold": 14, "result": "pass",
                   "terminal": False}],
        "alert_ids": [],
    }
    item.update(over)
    return item


def one_per_verdict():
    rec = base_item("recommend", "UNDERUSED", risk=RISK, target=dict(COST, plan="B2", vcpu=4, ram_gb=8,
                    compute_inr=2826, monthly_inr=3626),
                    actions=[{"type": "resize", "order": 3, "description": "B4 -> B2", "requires": [],
                              "reversible": True, "rollback": "resize back to B4"}],
                    schedule={"timezone": "Asia/Kolkata", "off_hours_per_week": 108, "on_hours_per_week": 60,
                              "windows": [{"days": "Mon-Fri", "start": "20:00", "end": "08:00"}],
                              "busy_hours_excluded": []},
                    replay={"limit_minutes_above_90": 30, "mem_cap_pct": 95, "passed": True, "chosen_plan": "B2",
                            "attempts": [{"plan": "B2", "minutes_above_90": 0, "max_cpu_pct": 39, "max_mem_pct": 62,
                                          "passed": True}]})
    rec["options"]["resize"] = {"monthly_inr_after": 3626, "saving_inr": 3864, "formula": "x"}
    rec["default_option"] = "resize"
    rej = base_item("reject", "VETO_MEMORY", veto=VETO)
    rej["evidence"] = dict(rej["evidence"], naive={"action": "resize", "would_save_inr": 3000})
    return [rec, rej, base_item("flag", "WENT_QUIET"), base_item("healthy", "RIGHT_SIZED"),
            base_item("upsize", "UNDER_PROVISIONED", risk=RISK),
            base_item("exclude", "NO_TELEMETRY", evidence=dict(base_item("x", "y")["evidence"], metrics=None))]


@pytest.mark.parametrize("item", one_per_verdict(), ids=lambda i: i["verdict"])
def test_every_verdict_example_validates(item):
    Recommendation.model_validate(item)


@pytest.mark.parametrize("mutate,msg", [
    (lambda i: i.update(reason_code="IDLE"), "not valid for verdict"),
    (lambda i: i.update(options={}), "'none'"),
    (lambda i: i.update(veto=VETO), "veto"),
    (lambda i: i.update(risk=RISK), "risk"),
    (lambda i: i["evidence"].update(metrics=None), "metrics may be null"),
    (lambda i: i["evidence"].update(naive={"a": 1}), "naive"),
    (lambda i: i.update(default_option="resize"), "default_option"),
    (lambda i: i.update(extra_field=1), "extra"),
])
def test_presence_rules_enforced(mutate, msg):
    item = copy.deepcopy(base_item("healthy", "RIGHT_SIZED"))
    mutate(item)
    with pytest.raises(ValidationError, match=msg):
        Recommendation.model_validate(item)


def test_reject_needs_veto():
    with pytest.raises(ValidationError, match="veto"):
        Recommendation.model_validate(base_item("reject", "VETO_MEMORY"))


@pytest.fixture(scope="module")
def stub(ds, cfg, features):
    feats = features
    alerts = [{"alert_id": "ALR-G9-vm-0001", "resource_id": "vm-0001"}]
    return envelope(stub_items(ds, feats, alerts, cfg), cfg, "2026-10-20T00:00:00+05:30")


def test_stub_envelope_validates_for_all_140(stub):
    env = RecommendationEnvelope.model_validate(stub)
    assert len(env.items) == 140
    assert env.schema_version == "1.0" and env.preset == "default"
    assert {i.resource.type for i in env.items} == {"vm", "volume", "ip"}


def test_stub_item_contents(stub):
    by_name = {i["resource"]["name"]: i for i in stub["items"]}
    web = by_name["prod-web-11a"]
    assert len(web["resource"]["members"]) == 2
    assert by_name["vm-untagged-14"]["resource"]["env"] == ""
    assert by_name["dev-orphan-owner-15"]["resource"]["owner"] == "unowned"
    assert by_name["prod-api-01"]["alert_ids"] == ["ALR-G9-vm-0001"]
    nomon = by_name["prod-nomon-13"]["evidence"]
    assert nomon["metrics"]["cpu"]["p95"] is None and nomon["coverage"] == 0.0
    ip = by_name["ip-unused-03"]
    assert ip["current"]["monthly_inr"] == 200 and ip["options"]["none"]["monthly_inr_after"] == 200
    assert all(i["rec_id"] == f"REC-{i['resource']['resource_id']}-default" for i in stub["items"])


def test_alert_and_summary_models():
    Alert.model_validate({"alert_id": "ALR-G3-vm-0001", "type": "G3", "severity": "Critical", "resource_id": "vm-0001",
                          "title": "t", "why": "w", "evidence": {"metric": "cpu", "value": 4.0, "threshold": 3,
                                                                 "window": "48h"},
                          "first_seen": "2026-10-18T00:00:00+05:30", "occurrences": 1, "suggested_action": "s"})
    Summary.model_validate({"monthly_before_inr": 1, "potential_after_inr": 1, "potential_saving_pct": 0.0,
                            "by_env": {}, "by_team": {}, "by_region": {}, "counts": {}, "bill_trend_6m": [],
                            "growth_waterfall": []})
