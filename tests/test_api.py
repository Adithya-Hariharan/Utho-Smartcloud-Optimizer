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
    assert vm["stats"]["cpu_p95"] > 60 and vm["monthly_inr"] == 7490 and vm["has_metrics"]
    vol = next(i for i in items if i["type"] == "volume")
    assert vol["stats"]["cpu_p95"] is None and vol["daily_max"] is None
    assert len(client.get("/api/resources", params={"type": "ip"}).json()) == 8
    dev_mumbai = client.get("/api/resources", params={"env": "dev", "region": "mumbai"}).json()
    assert dev_mumbai and all(i["env"] == "dev" and i["region"] == "mumbai" for i in dev_mumbai)
    assert all(i["owner_team"] == "growth" for i in client.get("/api/resources", params={"team": "growth"}).json())


def test_resource_detail(client, ids):
    r = client.get(f"/api/resources/{ids['prod-batch-07']}")
    assert r.status_code == 200
    body = r.json()
    assert body["trace"] and body["trace"][-1]["terminal"] and body["trace"][-1]["step"].startswith("veto.recurring_peak")
    assert body["resource"]["name"] == "prod-batch-07"
    assert 88 <= body["features"]["cpu"]["p99"] <= 95 and body["features"]["recurring_window"] == "02:00–02:40 IST"
    assert body["dq"]["coverage"] > 0.9 and body["dq"]["name"] == "prod-batch-07"
    assert client.get(f"/api/resources/{ids['ip-unused-03']}").json()["features"] is None
    assert client.get("/api/resources/vm-ghost").status_code == 404
    assert client.get("/api/resources/vm-9999").status_code == 404        # stray: not an inventory resource


def test_metrics_hourly_and_gap_is_null(client, ids):
    rid = ids["prod-api-02"]
    body = client.get(f"/api/resources/{rid}/metrics", params={"metric": "cpu", "step": "5m"}).json()
    assert len(body["mean"]) == 8640 and body["start"] == "2026-09-19T18:30:00+00:00"
    run = best = 0
    for v in body["mean"]:
        run = run + 1 if v is None else 0
        best = max(best, run)
    assert best >= 72                                                      # E1 gap is null, not 0
    hourly = client.get(f"/api/resources/{rid}/metrics").json()           # default step=1h
    assert hourly["step_seconds"] == 3600 and len(hourly["mean"]) == 720
    assert all(m is None or x is None or x >= m for m, x in zip(hourly["mean"], hourly["max"]))


def test_metrics_validation_and_no_telemetry(client, ids):
    vol = ids["vol-growing-10"]
    assert client.get(f"/api/resources/{vol}/metrics", params={"metric": "disk_used"}).status_code == 200
    assert client.get(f"/api/resources/{vol}/metrics", params={"metric": "cpu"}).status_code == 422
    assert client.get(f"/api/resources/{ids['prod-api-01']}/metrics", params={"metric": "x"}).status_code == 422
    assert client.get(f"/api/resources/{ids['prod-api-01']}/metrics", params={"step": "2h"}).status_code == 422
    empty = client.get(f"/api/resources/{ids['prod-nomon-13']}/metrics").json()
    assert empty["mean"] == [] and empty["max"] == [] and empty["gaps"] == []
    assert client.get("/api/resources/nope/metrics").status_code == 404


def test_recommendations_from_engine(client):
    r = client.get("/api/recommendations", params={"preset": "default"})
    assert r.status_code == 200 and r.headers["x-engine"] == "v1"
    env = RecommendationEnvelope.model_validate(r.json())
    assert len(env.items) == 141 and env.mock_engine is False               # 140 inventory rows + the stray series
    verdicts = {i.verdict for i in env.items}
    assert verdicts == {"recommend", "reject", "flag", "exclude", "healthy", "upsize"}
    assert env.below_floor.count >= 1 and env.below_floor.monthly_inr > 0
    assert all(i.trace for i in env.items)
    for preset in ("max_savings", "balanced", "max_performance"):
        p = client.get("/api/recommendations", params={"preset": preset})
        assert p.status_code == 200 and p.json()["preset"] == preset and len(p.json()["items"]) == 141
    assert client.get("/api/recommendations", params={"preset": "nope"}).status_code == 422


def test_replay_endpoint(client, ids):
    body = client.get(f"/api/resources/{ids['dev-report-02']}/replay").json()
    assert body["to_plan"] == "B1" and not body["passed"] and len(body["projected_cpu"]) == 720
    assert max(v for v in body["projected_cpu"] if v is not None) > 150     # weekly job doubled on half the vCPU
    ok = client.get(f"/api/resources/{ids['dev-web-03']}/replay", params={"preset": "default"}).json()
    assert ok["passed"] and ok["to_plan"] == "B2"
    assert client.get(f"/api/resources/{ids['prod-api-01']}/replay").status_code == 404   # healthy: no replay
    assert client.get("/api/resources/nope/replay").status_code == 404


def test_scorecard_endpoint(client):
    sc = client.get("/api/scorecard").json()
    assert sc["correct"] == sc["total"] == 141 and sc["unsafe_downsizes"] == 0 and sc["mock_engine"] is False


def test_alert_ids_linked(client):
    items = client.get("/api/recommendations").json()["items"]
    alerts = {a["alert_id"]: a for a in client.get("/api/alerts").json()["items"]}
    linked = [(i["resource"]["resource_id"], a) for i in items for a in i["alert_ids"]]
    assert linked and all(alerts[a]["resource_id"] == rid for rid, a in linked)
    with_rid = {a["alert_id"] for a in alerts.values() if a["resource_id"]}
    assert with_rid == {a for _, a in linked}                                # every resource alert is linked


def test_summary(client, ds, cfg):
    s = Summary.model_validate(client.get("/api/summary").json())
    last = ds.billing[ds.billing["date"] == ds.billing["date"].max()]["cost_inr"].sum()
    run_rate = last * cfg.get("billing.hours_per_month") / 24          # the bill's own monthly run-rate
    assert abs(s.monthly_before_inr - run_rate) <= 140                   # ± ₹1 per resource (B3)
    assert 15 <= s.potential_saving_pct <= 35                              # F9 plausibility band
    items = client.get("/api/recommendations").json()["items"]
    after = sum(i["options"][i["default_option"]]["monthly_inr_after"]
                if i["verdict"] == "recommend" and i["options"][i["default_option"]]["saving_inr"] > 0
                else i["current"]["monthly_inr"] for i in items)
    assert s.potential_after_inr == after                                 # headline = sum of the cards
    pct = round((s.monthly_before_inr - s.potential_after_inr) / s.monthly_before_inr * 100, 2)
    assert s.potential_saving_pct == pct
    for split in (s.by_env, s.by_team, s.by_region):
        assert sum(v.monthly_before_inr for v in split.values()) == s.monthly_before_inr
        assert sum(v.potential_after_inr for v in split.values()) == s.potential_after_inr
    assert "untagged" in s.by_env and "unowned" in s.by_team
    assert (s.counts.vm, s.counts.volume, s.counts.ip) == (117, 15, 8) and sum(s.counts.verdicts.values()) == 141
    assert len(s.bill_trend_6m.dates) == 180
    w = s.growth_waterfall
    assert w.by_team[0].delta_inr == max(r.delta_inr for r in w.by_team)


def test_alerts_endpoint(client):
    body = client.get("/api/alerts").json()
    assert body["mock_engine"] is False and body["items"]
    assert all(Alert.model_validate(a) for a in body["items"])
    assert body["items"][0]["severity"] == "critical"


def test_data_quality(client, ids):
    body = client.get("/api/data-quality").json()
    assert len(body["resources"]) == 115 + 15 + 1                            # VMs + volumes with rows + the stray
    assert [r["name"] for r in body["not_in_inventory"]] == ["vm-9999"]
    assert {r["name"] for r in body["no_metrics"]} == {"prod-nomon-13", "vm-stopped-07"}
    web = next(r for r in body["resources"] if r["resource_id"] == ids["dev-web-03"])
    assert web["duplicates"] >= 12
    t = body["totals"]
    assert (t["duplicates"], t["out_of_range"], t["irregular_ts"], t["flatline_slots"]) == (12, 30, 288, 576)
    assert all(c["ok"] for c in body["checks"]), [c for c in body["checks"] if not c["ok"]]
    assert [c["id"] for c in body["checks"]] == ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "E10", "D9"]
    stray = next(r for r in body["resources"] if r["resource_id"] == "vm-9999")
    assert stray["in_inventory"] is False and stray["name"] == "vm-9999"


def test_assumptions(client, cfg):
    body = client.get("/api/assumptions").json()
    names = [t["name"] for t in body["thresholds"]]
    assert "Saving floor" in names and "Comparisons" in names
    floor = next(t for t in body["thresholds"] if t["name"] == "Saving floor")
    assert floor["value"] == "₹500/month (compute changes)"
    assert next(t for t in body["thresholds"] if t["name"] == "Comparisons")["value"] == "strict < / >"
    assert {p["id"] for p in body["presets"]} == {"max_savings", "balanced", "default", "max_performance"}
    assert next(p for p in body["pricing"] if p["item"] == "B4")["monthly_inr"] == 6690
    assert body["data_window"]["end"] == "2026-10-20T00:00:00+05:30" and body["counts"]["vm"] == 117
    assert any(s["name"] == "carbon_coefficients" and s["value"] == "placeholder" for s in body["switches"])


def test_whatif(client):
    r = client.post("/api/whatif", json={"env": "dev", "off": "20:00-08:00", "weekends": True}).json()
    assert r["off_hours_per_week"] == 108 and r["input"]["env"] == "dev"
    rows = {x["name"]: x for x in r["rows"]}
    assert rows["dev-etl-04"]["status"] == "disrupted" and "01:00–03:00" in rows["dev-etl-04"]["note"]
    assert "vm-maint-08" not in rows                                       # stopped: not a candidate
    assert r["blind_saving_inr"] >= r["safe_saving_inr"] > 0
    order = {"disrupted": 0, "safe": 1, "excluded": 2}
    assert [order[x["status"]] for x in r["rows"]] == sorted(order[x["status"]] for x in r["rows"])
    stg = client.post("/api/whatif", json={"env": "staging", "off": "20:00-08:00", "weekends": True}).json()
    assert {x["name"]: x["status"] for x in stg["rows"]}["staging-demo-10"] == "excluded"
    assert client.post("/api/whatif", json={"env": "dev", "off": "8pm-8am", "weekends": True}).status_code == 422
    assert client.post("/api/whatif", json={"env": "qa", "off": "20:00-08:00", "weekends": True}).status_code == 422
    assert client.post("/api/whatif", json={"env": "dev"}).status_code == 422


@pytest.mark.parametrize("fmt,filename", [("csv", "smartcloud-accepted.csv"), ("md", "smartcloud-accepted.md"),
                                          ("sh", "apply.sh"), ("tf", "smartcloud-plan.tf")])
def test_export(client, fmt, filename):
    rec = next(i for i in client.get("/api/recommendations").json()["items"] if i["resource"]["name"] == "dev-web-03")
    r = client.post("/api/export", json={"accepted": [{"rec_id": rec["rec_id"], "option_key": "resize+schedule"}],
                                         "format": fmt})
    assert r.status_code == 200
    assert r.headers["content-disposition"] == f'attachment; filename="{filename}"'
    body = r.text
    if fmt in ("sh", "tf"):
        assert f"{rec['rec_id']} resize+schedule" in body                 # cp05:74
    if fmt == "csv":
        assert body.splitlines()[0].startswith("resource_id,name,env") and "dev-web-03" in body
    if fmt == "md":
        assert "Resize B4 → B2 + schedule" in body


def test_export_errors(client):
    assert client.post("/api/export", json={"accepted": [{"rec_id": "REC-nope-default", "option_key": "none"}],
                                            "format": "csv"}).status_code == 422
    assert client.post("/api/export", json={"accepted": [{"rec_id": "REC-vm-0033-default", "option_key": "fly"}],
                                            "format": "csv"}).status_code == 422
    assert client.post("/api/export", json={"accepted": [], "format": "pdf"}).status_code == 422
    bal = client.post("/api/export", json={"accepted": [{"rec_id": "REC-vm-0033-balanced", "option_key": "none"}],
                                           "format": "csv"})
    assert bal.status_code == 200                                         # rec_id resolved in its own preset


def test_forecast(client):
    f = client.get("/api/forecast", params={"days": 90}).json()
    assert f["days"] == 90 and len(f["forecast"]["dates"]) == len(f["forecast"]["baseline"]) == 90
    assert len(f["history"]["dates"]) == 60 and f["forecast"]["dates"][0] == "2026-10-20"
    assert all(lo <= b <= hi for lo, b, hi in zip(f["forecast"]["lower"], f["forecast"]["baseline"], f["forecast"]["upper"]))
    c = f["carbon"]
    assert "PLACEHOLDER" in c["coefficients"]["source"] and c["fleet_kwh_month"] > c["potential_kwh_month"] > 0
    assert client.get("/api/forecast", params={"days": 7}).json()["days"] == 7
    assert client.get("/api/forecast", params={"days": 0}).status_code == 422


def test_bad_bodies_rejected(client):
    assert client.post("/api/whatif", json={"env": "dev"}).status_code == 422
