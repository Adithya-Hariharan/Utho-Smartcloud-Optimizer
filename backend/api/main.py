"""FastAPI app (PLAN_final.md B6). Everything is computed once at startup and served from memory.

Run from the repo root: uvicorn backend.api.main:app --port 8000
"""
import logging
import math
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, List, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config_loader import REPO_ROOT, get_config
from ..cost.model import breakdown, fleet_costs
from ..data_access import get_dataset
from ..engine import replay as rp
from ..engine.decide import run_engine
from ..engine.sizing import catalogue
from ..insights.alerts import compute_alerts
from ..insights.growth import bill_trend_6m, growth_waterfall
from ..insights.scorecard import scorecard
from ..pipeline.clean import clean_all, empty_report
from ..pipeline.features import compute_features
from .schemas import Alert, RecommendationEnvelope, Summary
from .stub import envelope, stub_items

log = logging.getLogger("smartcloud")

METRIC_COLUMNS = {"cpu": "cpu_pct", "mem": "mem_pct", "disk": "disk_used_pct", "iops": "iops",
                  "net_in": "net_in_mbps", "net_out": "net_out_mbps"}
VOLUME_METRICS = {"iops", "disk"}
SPARK_SLOTS = 144                                   # 12 h of 5-minute slots -> 60 points


def jsonable(x):
    """numpy / pandas / NaN -> plain JSON types."""
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return [jsonable(v) for v in x.tolist()]
    if isinstance(x, (pd.Timestamp, datetime)):
        return None if pd.isna(x) else x.isoformat()
    if isinstance(x, np.generic):
        x = x.item()
    if (isinstance(x, float) and math.isnan(x)) or x is pd.NaT or x is pd.NA:
        return None
    return x


class State:
    def __init__(self):
        cfg, ds = get_config(), get_dataset()
        self.cfg, self.ds = cfg, ds
        self.cleaned = clean_all(ds, cfg)
        self.features = compute_features(self.cleaned, ds, cfg)
        self.costs = fleet_costs(ds, cfg)
        self.alerts = [Alert.model_validate(a).model_dump() for a in compute_alerts(self.cleaned, self.features, ds, cfg)]
        self.generated_at = datetime.now(timezone.utc).isoformat()
        try:
            items, below = run_engine(cfg, ds, self.cleaned, self.features, self.alerts)
            self.engine_mode = "v1"
        except Exception:                                   # never leave the UI without data
            log.exception("engine failed at startup; serving stub recommendations")
            items, below = stub_items(ds, self.features, self.alerts, cfg), {"count": 0, "monthly_inr": 0}
            self.engine_mode = "stub"
        env = envelope(items, cfg, self.generated_at)
        env["below_floor"] = below
        self.recommendations = jsonable(RecommendationEnvelope.model_validate(env).model_dump())
        self.items = {i["resource"]["resource_id"]: i for i in self.recommendations["items"]}
        self.inv = ds.inventory.set_index("resource_id")
        self.summary = self._summary()
        self.scorecard = jsonable(scorecard(self.recommendations["items"])) if self.engine_mode == "v1" else None

    def _summary(self):
        trend = bill_trend_6m(self.ds.billing)
        before = int(self.costs["monthly_inr"].sum())
        items = self.recommendations["items"]
        chosen = lambda i: i["options"][i["default_option"]]
        # upsizes add cost: shown on their own "risk fixes" line, not netted into the headline (F4)
        after = sum(chosen(i)["monthly_inr_after"] if i["verdict"] != "upsize" else i["current"]["monthly_inr"]
                    for i in items)
        by_verdict = {}
        for i in items:
            by_verdict[i["verdict"]] = by_verdict.get(i["verdict"], 0) + 1
        s = {"monthly_before_inr": before, "potential_after_inr": int(after),
             "potential_saving_pct": round(100 * (before - after) / before, 1) if before else 0.0,
             "by_env": breakdown(self.costs, "env"), "by_team": breakdown(self.costs, "team"),
             "by_region": breakdown(self.costs, "region"),
             "counts": {"by_type": {k: int(v) for k, v in self.costs["type"].value_counts().sort_index().items()},
                        "by_verdict": dict(sorted(by_verdict.items())), "resources": int(len(self.costs)),
                        "upsize_extra_inr": int(sum(-chosen(i)["saving_inr"] for i in items if i["verdict"] == "upsize")),
                        "below_floor": self.recommendations["below_floor"], "engine": self.engine_mode},
             "bill_trend_6m": trend, "growth_waterfall": growth_waterfall(self.ds.billing, trend)}
        return Summary.model_validate(s).model_dump()


@asynccontextmanager
async def lifespan(app):
    app.state.data = State()
    yield


app = FastAPI(title="SmartCloud Optimizer API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_config().raw["api"]["cors_origins"], allow_methods=["*"],
                   allow_headers=["*"], expose_headers=["X-Engine"])


def S(request: Request) -> State:
    return request.app.state.data


def _row(st, resource_id):
    if resource_id not in st.inv.index:
        raise HTTPException(404, f"unknown resource_id {resource_id}")
    return st.inv.loc[resource_id]


def not_available(detail):
    return JSONResponse(status_code=501, content={"detail": detail})


# ---- resources ---------------------------------------------------------------------------------

def _sparkline(st, rid):
    s = st.cleaned.series.get(rid)
    if s is None or s.kind != "vm":
        return None
    cpu = s.values["cpu_pct"].reshape(-1, SPARK_SLOTS)
    with np.errstate(all="ignore"):
        ok = ~np.isnan(cpu)
        means = np.where(ok.any(1), np.nansum(cpu, 1) / np.maximum(ok.sum(1), 1), np.nan)
    return [None if np.isnan(v) else round(float(v), 2) for v in means]


@app.get("/api/resources")
def list_resources(request: Request, region: Optional[str] = None, env: Optional[str] = None,
                   team: Optional[str] = None, type: Optional[str] = None):
    st = S(request)
    costs = st.costs.set_index("resource_id")
    out = []
    for rid, row in st.inv.iterrows():
        if (region is not None and row["region"] != region) or (env is not None and row["env"] != env) \
                or (team is not None and row["owner"] != team) or (type is not None and row["type"] != type):
            continue
        m = st.features[rid]["metrics"]
        out.append({"resource_id": rid, "name": row["name"], "type": row["type"], "region": row["region"],
                    "env": row["env"], "team": row["owner"], "state": row["state"], "plan_id": row["plan_id"],
                    "monthly_inr": int(costs.loc[rid, "monthly_inr"]), "cpu_p95": m["cpu"]["p95"],
                    "cpu_p99": m["cpu"]["p99"], "mem_p99": m["mem"]["p99"], "sparkline": _sparkline(st, rid)})
    return jsonable(out)


@app.get("/api/resources/{resource_id}")
def get_resource(request: Request, resource_id: str):
    st = S(request)
    row = _row(st, resource_id)
    inventory = {"resource_id": resource_id, **{k: row[k] for k in st.inv.columns if k != "tags_list"},
                 "tags": list(row["tags_list"])}
    s = st.cleaned.series.get(resource_id)
    item = st.items[resource_id]
    return jsonable({"inventory": inventory, "features": st.features[resource_id],
                     "data_quality": s.report if s else empty_report(resource_id), "trace": item["trace"],
                     "verdict": item["verdict"], "reason_code": item["reason_code"], "rec_id": item["rec_id"]})


@app.get("/api/resources/{resource_id}/metrics")
def get_metrics(request: Request, resource_id: str, metric: str = "cpu", step: str = "1h"):
    st = S(request)
    row = _row(st, resource_id)
    if metric not in METRIC_COLUMNS:
        raise HTTPException(422, f"metric must be one of {sorted(METRIC_COLUMNS)}")
    if row["type"] == "volume" and metric not in VOLUME_METRICS:
        raise HTTPException(422, f"volumes have only {sorted(VOLUME_METRICS)}")
    if step not in ("5m", "1h"):
        raise HTTPException(422, "step must be 5m or 1h")
    out = {"resource_id": resource_id, "metric": metric, "step": step, "ts": [], "mean": [], "max": []}
    s = st.cleaned.series.get(resource_id)
    if s is None:
        return out
    ts = st.cleaned.grid.ts_utc[s.exists]
    vals = s.values[METRIC_COLUMNS[metric]][s.exists]
    if step == "5m":
        out.update(ts=[t.isoformat() for t in ts], mean=vals, max=vals)
    else:
        df = pd.DataFrame({"v": vals}, index=ts)
        g = df.groupby(df.index.floor("h"))["v"]
        out.update(ts=[t.isoformat() for t in g.mean().index], mean=g.mean().to_numpy(), max=g.max().to_numpy())
    return jsonable(out)


@app.get("/api/resources/{resource_id}/replay")
def get_replay(request: Request, resource_id: str, step: str = "5m"):
    """Actual vs projected CPU / memory at the replayed plan (Peak Replay chart)."""
    st = S(request)
    row = _row(st, resource_id)
    item = st.items[resource_id]
    replay, s = item["replay"], st.cleaned.series.get(resource_id)
    if not replay or not replay["attempts"] or s is None:
        raise HTTPException(404, f"no replay for {resource_id} (verdict {item['verdict']}/{item['reason_code']})")
    if step not in ("5m", "1h"):
        raise HTTPException(422, "step must be 5m or 1h")
    plan_id = replay["chosen_plan"] or replay["attempts"][-1]["plan"]
    plan = next(p for p in catalogue(st.cfg) if p.plan_id == plan_id)
    cpu, mem = s.values["cpu_pct"][s.exists], s.values["mem_pct"][s.exists]
    cpu_new, mem_new = rp.project(cpu, mem, row["vcpu"], row["ram_gb"], plan)
    ts = st.cleaned.grid.ts_utc[s.exists]
    series = {"actual_cpu": cpu, "projected_cpu": cpu_new, "actual_mem": mem, "projected_mem": mem_new}
    if step == "1h":                                        # hourly max keeps the peaks visible
        df = pd.DataFrame(series, index=ts)
        g = df.groupby(df.index.floor("h")).max()
        ts, series = g.index, {k: g[k].to_numpy() for k in series}
    attempt = next(a for a in replay["attempts"] if a["plan"] == plan_id)
    return jsonable({"resource_id": resource_id, "current_plan": row["plan_id"], "replay_plan": plan_id,
                     "passed": attempt["passed"], "minutes_above_90": attempt["minutes_above_90"],
                     "limit_minutes_above_90": replay["limit_minutes_above_90"], "mem_cap_pct": replay["mem_cap_pct"],
                     "threshold_pct": 90, "step": step, "ts": [t.isoformat() for t in ts], **series})


# ---- recommendations, summary, alerts ------------------------------------------------------------

@app.get("/api/recommendations")
def get_recommendations(request: Request, preset: str = "default"):
    if preset != "default":
        return not_available(f"preset '{preset}' not in MVP (only 'default' is enabled)")
    st = S(request)
    return JSONResponse(content=st.recommendations, headers={"X-Engine": st.engine_mode})


@app.get("/api/summary")
def get_summary(request: Request):
    return S(request).summary


@app.get("/api/alerts")
def get_alerts(request: Request):
    return S(request).alerts


@app.get("/api/data-quality")
def get_data_quality(request: Request):
    st = S(request)
    reports = [st.cleaned.series[rid].report if rid in st.cleaned.series else empty_report(rid)
               for rid in st.inv.index]
    return jsonable({"resources": reports, "strays": st.cleaned.strays, "no_metrics": st.cleaned.no_metrics})


@app.get("/api/assumptions")
def get_assumptions(request: Request):
    st = S(request)
    notes = (REPO_ROOT / "data" / "DATASET.md").read_text(encoding="utf-8")
    return jsonable({"config_hash": st.cfg.hash, "config": st.cfg.raw, "dataset_notes": notes})


# ---- not in the MVP (paths and bodies kept per §10) ----------------------------------------------

class WhatIfRequest(BaseModel):
    env: str
    off: str
    weekends: bool


class ExportRequest(BaseModel):
    accepted: List[Any]
    format: str


@app.get("/api/forecast")
def get_forecast(days: int = Query(90)):
    return not_available("not in MVP")


@app.post("/api/whatif")
def post_whatif(body: WhatIfRequest):
    return not_available("not in MVP")


@app.post("/api/export")
def post_export(body: ExportRequest):
    return not_available("not in MVP")


@app.get("/api/scorecard")
def get_scorecard(request: Request):
    st = S(request)
    return st.scorecard if st.scorecard is not None else not_available("engine not available")
