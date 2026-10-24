"""Checkpoint 6: API (PLAN_final.md B6, B8.6), via FastAPI TestClient."""
import time

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api.schemas import Alert, RecommendationEnvelope, Summary
from backend.config_loader import REPO_ROOT


@pytest.fixture(scope="module")
def client():
    t0 = time.perf_counter()
    with TestClient(app) as c:
        c.startup_seconds = time.perf_counter() - t0
        yield c


@pytest.fixture(scope="module")
def ids(ds):
    return dict(zip(ds.inventory.name, ds.inventory.resource_id))


def test_startup_under_30s(client):
    assert client.startup_seconds < 30


def test_docs_served(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_cors_exposes_engine_header(client):
    r = client.get("/api/recommendations", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "x-engine" in r.headers["access-control-expose-headers"].lower()


def test_resources_list_and_filters(client):
    r = client.get("/api/resources")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 140
    vm = next(i for i in items if i["name"] == "prod-api-01")
    assert len(vm["sparkline"]) == 60 and vm["cpu_p95"] > 60 and vm["monthly_inr"] == 7490
    vol = next(i for i in items if i["type"] == "volume")
    assert vol["cpu_p95"] is None and vol["sparkline"] is None
    assert len(client.get("/api/resources", params={"type": "ip"}).json()) == 8
    dev_mumbai = client.get("/api/resources", params={"env": "dev", "region": "mumbai"}).json()
    assert dev_mumbai and all(i["env"] == "dev" and i["region"] == "mumbai" for i in dev_mumbai)
    assert all(i["team"] == "growth" for i in client.get("/api/resources", params={"team": "growth"}).json())


def test_resource_detail(client, ids):
    r = client.get(f"/api/resources/{ids['prod-batch-07']}")
    assert r.status_code == 200
    body = r.json()
    assert body["trace"] and body["trace"][-1]["terminal"] and body["trace"][-1]["step"] == "veto.recurring_peak"
    assert (body["verdict"], body["reason_code"]) == ("reject", "VETO_RECURRING_PEAK")
    assert body["inventory"]["name"] == "prod-batch-07"
    assert 88 <= body["features"]["metrics"]["cpu"]["p99"] <= 95
    assert body["data_quality"]["coverage"] > 0.9
    assert client.get("/api/resources/vm-ghost").status_code == 404
    assert client.get("/api/resources/vm-9999").status_code == 404        # stray: data-quality only


def test_metrics_hourly_and_gap_is_null(client, ids):
    rid = ids["prod-api-02"]
    r = client.get(f"/api/resources/{rid}/metrics", params={"metric": "cpu", "step": "5m"})
    body = r.json()
    assert r.status_code == 200 and len(body["ts"]) == 8640 == len(body["mean"])
    assert body["ts"][0] == "2026-09-19T18:30:00+00:00"
    nulls = [v is None for v in body["mean"]]
    run = best = 0
    for n in nulls:
        run = run + 1 if n else 0
        best = max(best, run)
    assert best >= 72                                                      # E1 gap is null, not 0
    hourly = client.get(f"/api/resources/{rid}/metrics").json()           # default step=1h
    assert hourly["step"] == "1h" and 720 <= len(hourly["ts"]) <= 721
    assert all(m is None or x is None or x >= m for m, x in zip(hourly["mean"], hourly["max"]))


def test_metrics_validation_and_no_telemetry(client, ids):
    vol = ids["vol-growing-10"]
    assert client.get(f"/api/resources/{vol}/metrics", params={"metric": "disk"}).status_code == 200
    assert client.get(f"/api/resources/{vol}/metrics", params={"metric": "cpu"}).status_code == 422
    assert client.get(f"/api/resources/{ids['prod-api-01']}/metrics", params={"metric": "x"}).status_code == 422
    assert client.get(f"/api/resources/{ids['prod-api-01']}/metrics", params={"step": "2h"}).status_code == 422
    empty = client.get(f"/api/resources/{ids['prod-nomon-13']}/metrics").json()
    assert empty["ts"] == [] and empty["mean"] == [] and empty["max"] == []
    assert client.get("/api/resources/nope/metrics").status_code == 404


def test_recommendations_from_engine(client):
    r = client.get("/api/recommendations", params={"preset": "default"})
    assert r.status_code == 200 and r.headers["x-engine"] == "v1"
    env = RecommendationEnvelope.model_validate(r.json())
    assert len(env.items) == 140
    verdicts = {i.verdict for i in env.items}
    assert verdicts == {"recommend", "reject", "flag", "exclude", "healthy", "upsize"}
    assert env.below_floor.count >= 1 and env.below_floor.monthly_inr > 0
    assert all(i.trace for i in env.items)
    assert client.get("/api/recommendations", params={"preset": "balanced"}).status_code == 501


def test_replay_endpoint(client, ids):
    r = client.get(f"/api/resources/{ids['dev-report-02']}/replay")
    body = r.json()
    assert r.status_code == 200 and body["replay_plan"] == "B1" and not body["passed"]
    assert len(body["ts"]) == len(body["projected_cpu"]) == 8640
    assert max(v for v in body["projected_cpu"] if v is not None) > 150     # weekly job doubled on half the vCPU
    ok = client.get(f"/api/resources/{ids['dev-web-03']}/replay", params={"step": "1h"}).json()
    assert ok["passed"] and ok["replay_plan"] == "B2" and len(ok["ts"]) <= 721
    assert client.get(f"/api/resources/{ids['prod-api-01']}/replay").status_code == 404   # healthy: no replay
    assert client.get("/api/resources/nope/replay").status_code == 404


def test_scorecard_endpoint(client):
    sc = client.get("/api/scorecard").json()
    assert sc["matched"] == sc["total"] == 140 and sc["unsafe_downsizes"] == 0


def test_alert_ids_linked(client):
    items = client.get("/api/recommendations").json()["items"]
    alerts = {a["alert_id"]: a for a in client.get("/api/alerts").json()}
    linked = [(i["resource"]["resource_id"], a) for i in items for a in i["alert_ids"]]
    assert linked and all(alerts[a]["resource_id"] == rid for rid, a in linked)


def test_summary(client):
    s = Summary.model_validate(client.get("/api/summary").json())
    assert s.monthly_before_inr == 657302
    assert 15 <= s.potential_saving_pct <= 35                              # F9 plausibility band
    items = client.get("/api/recommendations").json()["items"]
    after = sum(i["options"][i["default_option"]]["monthly_inr_after"] if i["verdict"] != "upsize"
                else i["current"]["monthly_inr"] for i in items)
    assert s.potential_after_inr == after                                 # headline = sum of the cards
    assert s.counts["upsize_extra_inr"] > 0 and s.counts["engine"] == "v1"
    assert sum(s.by_env.values()) == sum(s.by_team.values()) == sum(s.by_region.values()) == 657302
    assert s.counts["by_type"] == {"ip": 8, "vm": 117, "volume": 15}
    assert len(s.bill_trend_6m) == 6
    assert sum(w.delta_inr for w in s.growth_waterfall) == s.bill_trend_6m[-1].total_inr - s.bill_trend_6m[0].total_inr


def test_alerts_endpoint(client):
    body = client.get("/api/alerts").json()
    assert body and all(Alert.model_validate(a) for a in body)
    assert body[0]["severity"] == "Critical"


def test_data_quality(client, ids):
    body = client.get("/api/data-quality").json()
    assert len(body["resources"]) == 140
    assert body["strays"] == ["vm-9999"]
    assert set(body["no_metrics"]) == {ids["prod-nomon-13"], ids["vm-stopped-07"]}
    web = next(r for r in body["resources"] if r["resource_id"] == ids["dev-web-03"])
    assert web["duplicates_removed"] >= 12


def test_assumptions(client, cfg):
    body = client.get("/api/assumptions").json()
    assert body["config_hash"] == cfg.hash
    assert body["config"]["pricing"]["plans"]["B4"]["monthly_inr"] == 6690
    assert body["dataset_notes"] == (REPO_ROOT / "data" / "DATASET.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("method,path,payload,detail", [
    ("get", "/api/forecast?days=90", None, "not in MVP"),
    ("post", "/api/whatif", {"env": "dev", "off": "20:00-08:00", "weekends": True}, "not in MVP"),
    ("post", "/api/export", {"accepted": [], "format": "csv"}, "not in MVP"),
])
def test_not_in_mvp_endpoints(client, method, path, payload, detail):
    r = client.get(path) if method == "get" else client.post(path, json=payload)
    assert r.status_code == 501 and r.json() == {"detail": detail}


def test_bad_bodies_rejected(client):
    assert client.post("/api/whatif", json={"env": "dev"}).status_code == 422
