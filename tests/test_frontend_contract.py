"""The backend serves exactly the shapes the frontend reads (PLAN_frontend_integration.md DoD and §7).

Shape check: every field (merged over all list items and all fixtures of a kind) that the frontend's fixture
files have must exist in the live response with a compatible JSON type. Fixtures: frontend/fallback/api/**.
"""
import json
from collections import defaultdict

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.config_loader import REPO_ROOT

FX = REPO_ROOT / "frontend" / "fallback" / "api"
DYNAMIC = (".by_env", ".by_team", ".by_region", ".options", ".by_option", ".fault_counts", ".verdicts", ".counts")


def _kind(v):
    return ("null" if v is None else "bool" if isinstance(v, bool) else "num" if isinstance(v, (int, float))
            else "str" if isinstance(v, str) else "list" if isinstance(v, list) else "obj")


def _collect(v, path, shapes):
    shapes[path].add(_kind(v))
    if isinstance(v, dict):
        collapse = any(path.endswith(d) for d in DYNAMIC) or path.endswith(".by_option.*")
        for k, x in v.items():
            _collect(x, f"{path}.{'*' if collapse else k}", shapes)
    elif isinstance(v, list):
        for x in v:
            _collect(x, f"{path}[]", shapes)


def shape_gaps(fe_docs, be_docs):
    fs, bs = defaultdict(set), defaultdict(set)
    for d in fe_docs:
        _collect(d, "$", fs)
    for d in be_docs:
        _collect(d, "$", bs)
    missing, types = [], []
    # a list that is empty in every backend response has no items to compare (e.g. scorecard.mismatches = [])
    empty = [p for p in bs if bs[p] == {"list"} and f"{p}[]" not in bs]
    for p in sorted(fs):
        if any(p.startswith(m + ".") or p.startswith(m + "[") for m in missing + empty):
            continue
        if p not in bs:
            missing.append(p)
            continue
        f, b = fs[p] - {"null"}, bs[p] - {"null"}
        if f and b and not (f & b):
            types.append(f"{p}: frontend {sorted(f)} vs backend {sorted(b)}")
    return missing, types


def fixture(rel):
    return json.loads((FX / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def assert_shape(fe_docs, be_docs):
    missing, types = shape_gaps(fe_docs, be_docs)
    assert not missing and not types, {"missing": missing, "type": types}


# ---- E1-E4 ------------------------------------------------------------------------------------

def test_e1_resources_shape(client):
    assert_shape([fixture("resources.json")], [client.get("/api/resources").json()])


def test_e2_resource_detail_shape(client):
    ids = sorted(p.stem for p in (FX / "resources").glob("*.json"))
    fe = [fixture(f"resources/{i}.json") for i in ids]
    be = []
    for i in ids:
        r = client.get(f"/api/resources/{i}")
        assert r.status_code == 200, i
        be.append(r.json())
    assert_shape(fe, be)


def test_e3_metrics_shape(client):
    fe, be = [], []
    for p in sorted((FX / "metrics").rglob("*.json")):
        metric, step = p.stem.rsplit("_", 1)
        r = client.get(f"/api/resources/{p.parent.name}/metrics", params={"metric": metric, "step": step})
        assert r.status_code == 200, p
        fe.append(json.loads(p.read_text(encoding="utf-8")))
        be.append(r.json())
    assert_shape(fe, be)


def test_e4_replay_shape(client):
    fe, be = [], []
    for preset in ("max_savings", "balanced", "default", "max_performance"):
        recs = client.get("/api/recommendations", params={"preset": preset}).json()["items"]
        for i in recs:
            if i["replay"]:
                r = client.get(f"/api/resources/{i['resource']['resource_id']}/replay", params={"preset": preset})
                assert r.status_code == 200, (preset, i["resource"]["name"])     # rule 6: replay block -> 200
                be.append(r.json())
        fe += [json.loads(p.read_text(encoding="utf-8")) for p in (FX / "replay" / preset).glob("*.json")]
    assert be and fe
    assert_shape(fe, be)


def test_e5_recommendations_shape(client):
    for preset in ("max_savings", "balanced", "default", "max_performance"):
        assert_shape([fixture(f"recommendations/{preset}.json")],
                     [client.get("/api/recommendations", params={"preset": preset}).json()])


# ---- contract rules ------------------------------------------------------------------------------

def test_rule1_missing_is_null(client):
    api02 = client.get("/api/resources/vm-0050/metrics", params={"metric": "cpu", "step": "5m"}).json()
    assert api02["mean"].count(None) >= 72                                  # E1 gap is null, not 0
    assert any(g["kind"] == "missing" and g["hours"] >= 6 for g in api02["gaps"])
    a16 = client.get("/api/resources/vm-0053/metrics", params={"metric": "cpu"}).json()
    assert any(g["kind"] == "flatline" and g["hours"] == 48.0 for g in a16["gaps"])


def test_rule6_has_metrics_gating(client):
    rows = client.get("/api/resources").json()
    for r in rows:
        metric = "disk_used" if r["type"] == "volume" else "cpu"
        m = client.get(f"/api/resources/{r['resource_id']}/metrics", params={"metric": metric}).json()
        assert bool(m["mean"]) == r["has_metrics"], r["name"]
    assert client.get("/api/resources/nope").status_code == 404
    assert client.get("/api/resources/nope/metrics").status_code == 404
    assert client.get("/api/resources/vm-0001/replay").status_code == 404    # healthy: no replay block


def test_rule7_untagged_unowned_filters(client):
    untagged = client.get("/api/resources", params={"env": "untagged"}).json()
    unowned = client.get("/api/resources", params={"team": "unowned"}).json()
    assert [r["name"] for r in untagged] == ["vm-untagged-14"]
    assert "dev-orphan-owner-15" in [r["name"] for r in unowned]


def test_metric_names_and_steps(client):
    for metric in ("cpu", "mem", "disk_used", "iops", "net_in", "net_out", "disk"):
        r = client.get("/api/resources/vm-0003/metrics", params={"metric": metric})
        assert r.status_code == 200 and len(r.json()["mean"]) == 720, metric
    five = client.get("/api/resources/vm-0003/metrics", params={"step": "5m"}).json()
    assert five["step_seconds"] == 300 and len(five["mean"]) == 8640
    assert five["start"] == "2026-09-19T18:30:00+00:00"
    assert client.get("/api/resources/vol-0015/metrics", params={"metric": "cpu"}).status_code == 422
    assert client.get("/api/resources/vm-0003/metrics", params={"step": "2h"}).status_code == 422


def test_resource_rows(client):
    rows = {r["name"]: r for r in client.get("/api/resources").json()}
    assert len(rows) == 140                                               # the stray is not an inventory row
    b = rows["prod-batch-07"]
    assert b["has_metrics"] and len(b["daily_p95"]) == 30 and len(b["daily_max"]) == 30 and b["stats"]["cpu_p99"] > 85
    v = rows["vol-growing-10"]
    assert v["stats"]["cpu_p95"] is None and len(v["daily_p95"]) == 30 and v["daily_max"] is None
    assert rows["ip-unused-03"]["stats"] is None and rows["ip-unused-03"]["has_metrics"] is False
    assert rows["vm-untagged-14"]["env"] is None and rows["prod-api-01"]["service_group"] is None
    assert rows["prod-db-01"]["tags"] == ["stateful"]


def test_replay_series(client):
    r = client.get("/api/resources/vm-0033/replay", params={"preset": "default"}).json()      # dev-web-03
    assert (r["from_plan"], r["to_plan"], r["from_vcpu"], r["to_vcpu"]) == ("B4", "B2", 8, 4)
    assert len(r["actual_cpu"]) == 720 and r["step_seconds"] == 3600 and r["passed"]
    k = next(i for i, v in enumerate(r["actual_cpu"]) if v)
    assert r["projected_cpu"][k] == pytest.approx(r["actual_cpu"][k] * 2, abs=0.11)
    batch = client.get("/api/resources/vm-0003/replay").json()                                # naive cut replay
    assert batch["passed"] is False and batch["to_plan"] == batch["attempts"][0]["plan"]
    assert client.get("/api/resources/vm-0033/replay", params={"preset": "nope"}).status_code == 422


# ---- E6, E7 --------------------------------------------------------------------------------------

def test_e6_summary_shape(client):
    assert_shape([fixture("summary.json")], [client.get("/api/summary").json()])


def test_e7_alerts_shape(client):
    assert_shape([fixture("alerts.json")], [client.get("/api/alerts").json()])


def test_rule3_one_run_rate(client):
    recs = client.get("/api/recommendations").json()["items"]
    rows = client.get("/api/resources").json()
    s = client.get("/api/summary").json()
    assert sum(i["current"]["monthly_inr"] for i in recs) == sum(r["monthly_inr"] for r in rows) == s["monthly_before_inr"]


def test_rule8_waterfall_sums(client):
    w = client.get("/api/summary").json()["growth_waterfall"]
    delta = w["last30"]["total_inr"] - w["first30"]["total_inr"]
    for k in ("by_env", "by_team", "by_age"):
        assert abs(sum(r["delta_inr"] for r in w[k]) - delta) <= len(w[k]), k


# ---- E9, E10, E11 --------------------------------------------------------------------------------

def test_e9_scorecard_shape(client):
    assert_shape([fixture("scorecard.json")], [client.get("/api/scorecard").json()])


def test_e10_data_quality_shape(client):
    assert_shape([fixture("data-quality.json")], [client.get("/api/data-quality").json()])


def test_e11_assumptions_shape(client):
    assert_shape([fixture("assumptions.json")], [client.get("/api/assumptions").json()])


# ---- E8, E12, E13 --------------------------------------------------------------------------------

def test_e8_forecast_shape_and_rule9(client):
    f = client.get("/api/forecast", params={"days": 90}).json()
    assert_shape([fixture("forecast_90.json")], [f])
    by = f["carbon"]["by_option"]
    for preset in ("max_savings", "balanced", "default", "max_performance"):
        for i in client.get("/api/recommendations", params={"preset": preset}).json()["items"]:
            if i["verdict"] in ("recommend", "upsize"):
                assert list(by[i["rec_id"]]) == list(i["options"]), i["rec_id"]        # same keys, same order


@pytest.mark.parametrize("name", [p.stem for p in sorted((FX / "whatif").glob("*.json"))])
def test_e12_whatif_shape(client, name):
    fe = fixture(f"whatif/{name}.json")
    be = client.post("/api/whatif", json=fe["input"]).json()
    assert_shape([fe], [be])
    assert be["off_hours_per_week"] == fe["off_hours_per_week"]
