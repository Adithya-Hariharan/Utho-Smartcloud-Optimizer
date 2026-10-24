"""Recommendation schema v1.0 as extended for the frontend (PLAN_frontend_integration.md §2.13, §3):
every presence rule is enforced, on real engine items."""
import copy

import pytest
from pydantic import ValidationError

from backend.api.schemas import Recommendation, RecommendationEnvelope
from backend.api.views import envelope
from backend.engine.decide import Engine


@pytest.fixture(scope="module")
def items(ds, cfg, cleaned, features):
    return {i["resource"]["name"]: i for i in Engine(cfg, ds, cleaned, features).run()[0]}


def test_every_verdict_validates(items):
    seen = {}
    for i in items.values():
        Recommendation.model_validate(i)
        seen.setdefault(i["verdict"], i["reason_code"])
    assert set(seen) == {"recommend", "reject", "flag", "exclude", "healthy", "upsize"}


def test_envelope(items, cfg):
    env = envelope(list(items.values()), {"count": 1, "monthly_inr": 495}, cfg, "2026-10-20T00:00:00+05:30", "default")
    e = RecommendationEnvelope.model_validate(env)
    assert e.mock_engine is False and e.data_window.end == "2026-10-20T00:00:00+05:30"
    assert e.data_window.start == "2026-09-20T00:00:00+05:30"


@pytest.mark.parametrize("name,mutate,msg", [
    ("prod-api-01", lambda i: i.update(reason_code="IDLE"), "not valid for verdict"),
    ("prod-api-01", lambda i: i.update(options={}), "'none'"),
    ("prod-api-01", lambda i: i.update(default_option="resize"), "default_option"),
    ("prod-api-01", lambda i: i.update(veto={"signal": "x", "metric": "x", "value": 1, "threshold": 1,
                                             "comparator": ">", "message": "x"}), "veto"),
    ("prod-batch-07", lambda i: i.update(veto=None), "veto"),
    ("prod-api-01", lambda i: i["evidence"].update(naive={"action": "none", "target_plan": None, "saving_inr": 0,
                                                          "basis": "x", "replay_minutes_above_90": None}), "naive"),
    ("dev-web-03", lambda i: i.update(risk=None), "risk"),
    ("prod-api-01", lambda i: i.update(risk=copy.deepcopy(i["risk"]) or {"level": "Low", "score": 0, "points": [],
                                       "confidence": "High", "confidence_basis": "x"}), "risk"),
    ("prod-nomon-13", lambda i: i["evidence"].update(metrics={"cpu": None, "mem": None, "iops_pct": None,
                                                              "net_pct": None, "disk_used": None}), "must be null"),
    ("prod-batch-07", lambda i: i["replay"].update(attempts=[]), "at least one attempt"),
    ("prod-api-01", lambda i: i["trace"].__setitem__(0, dict(i["trace"][0], terminal=True)), "exactly one"),
    ("prod-api-01", lambda i: i["trace"].__setitem__(0, dict(i["trace"][0], value=3)), "string"),
    ("prod-api-01", lambda i: i["trace"].__setitem__(0, dict(i["trace"][0], result="match")), "result"),
    ("prod-api-01", lambda i: i["evidence"].update(percentile_used=99.0), "percentile_used"),
    ("prod-api-01", lambda i: i.update(extra_field=1), "extra"),
])
def test_presence_rules(items, name, mutate, msg):
    item = copy.deepcopy(items[name])
    mutate(item)
    with pytest.raises(ValidationError, match=msg):
        Recommendation.model_validate(item)
