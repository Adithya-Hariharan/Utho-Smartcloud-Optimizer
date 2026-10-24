"""FastAPI app. Everything is computed once at startup and served from memory; every response has the shape
the frontend reads (frontend/API_CONTRACT.md, PLAN_frontend_integration.md §4).

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
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from ..config_loader import REPO_ROOT, get_config
from ..cost.model import fleet_costs
from ..data_access import get_dataset
from ..engine.decide import run_engine
from ..engine.params import enabled_presets
from ..insights.alerts import compute_alerts
from ..insights.export import ExportError, export
from ..insights.forecast import forecast
from ..insights.whatif import WhatIfError, run_whatif
from ..insights.scorecard import scorecard
from ..pipeline.clean import clean_all
from ..pipeline.features import compute_features
from . import views
from .schemas import Alert, AlertsResponse, RecommendationEnvelope, Summary

log = logging.getLogger("smartcloud")


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
        self.monthly = self.costs.set_index("resource_id")["monthly_inr"].to_dict()
        self.inv = ds.inventory.set_index("resource_id")
        self.alerts = [Alert.model_validate(a).model_dump() for a in compute_alerts(self.cleaned, self.features, ds, cfg)]
        self.generated_at = datetime.now(timezone.utc).isoformat()
        self.engine_mode = "v1"
        # every preset is computed once; a failure stops startup (a UI on silently wrong data is worse)
        self.runs, self.by_id = {}, {}
        for preset in enabled_presets(cfg):
            items, below = run_engine(cfg, ds, self.cleaned, self.features, self.alerts, preset=preset)
            env = views.envelope(items, below, cfg, self.generated_at, preset)
            self.runs[preset] = jsonable(RecommendationEnvelope.model_validate(env).model_dump())
            self.by_id[preset] = {i["resource"]["resource_id"]: i for i in self.runs[preset]["items"]}
        self.recommendations = self.runs["default"]
        self.items = self.by_id["default"]
        self.summary = jsonable(Summary.model_validate(views.summary(self)).model_dump())
        self.scorecard = jsonable(scorecard(self.recommendations["items"]))
        self.forecasts = {}

@asynccontextmanager
async def lifespan(app):
    app.state.data = State()
    yield


app = FastAPI(title="SmartCloud Optimizer API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_config().raw["api"]["cors_origins"], allow_methods=["*"],
                   allow_headers=["*"], expose_headers=["X-Engine", "Content-Disposition"])


@app.exception_handler(views.NotFound)
def _not_found(request, exc):
    return JSONResponse(status_code=404, content={"detail": f"not found: {exc}"})


@app.exception_handler(views.BadRequest)
def _bad_request(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


def S(request: Request) -> State:
    return request.app.state.data


# ---- E1-E4: resources, metrics, replay ------------------------------------------------------------

@app.get("/api/resources")
def list_resources(request: Request, region: Optional[str] = None, env: Optional[str] = None,
                   team: Optional[str] = None, type: Optional[str] = None):
    return jsonable(views.resources(S(request), region, env, team, type))


@app.get("/api/resources/{resource_id}")
def get_resource(request: Request, resource_id: str):
    return jsonable(views.resource_detail(S(request), resource_id))


@app.get("/api/resources/{resource_id}/metrics")
def get_metrics(request: Request, resource_id: str, metric: str = "cpu", step: str = "1h"):
    return jsonable(views.metric_series(S(request), resource_id, metric, step))


@app.get("/api/resources/{resource_id}/replay")
def get_replay(request: Request, resource_id: str, preset: str = "default"):
    return jsonable(views.replay_series(S(request), resource_id, preset))


# ---- E5: recommendations ---------------------------------------------------------------------------

@app.get("/api/recommendations")
def get_recommendations(request: Request, preset: str = "default"):
    st = S(request)
    if preset not in st.runs:
        raise HTTPException(422, f"preset must be one of {list(st.runs)}")
    return JSONResponse(content=st.runs[preset], headers={"X-Engine": st.engine_mode})


# ---- summary, alerts, data quality, assumptions, scorecard ------------------------------------------

@app.get("/api/summary")
def get_summary(request: Request):
    return S(request).summary


@app.get("/api/alerts")
def get_alerts(request: Request):
    return jsonable(AlertsResponse.model_validate(views.alerts(S(request))).model_dump())


@app.get("/api/data-quality")
def get_data_quality(request: Request):
    return jsonable(views.data_quality(S(request)))


@app.get("/api/assumptions")
def get_assumptions(request: Request):
    return jsonable(views.assumptions(S(request)))


@app.get("/api/scorecard")
def get_scorecard(request: Request):
    return S(request).scorecard


# ---- E8 forecast, E12 what-if, E13 export ---------------------------------------------------------

class WhatIfRequest(BaseModel):
    env: str
    off: str
    weekends: bool


class ExportRequest(BaseModel):
    accepted: List[Any]
    format: str


@app.get("/api/forecast")
def get_forecast(request: Request, days: int = Query(90, ge=1, le=365)):
    st = S(request)
    if days not in st.forecasts:
        st.forecasts[days] = jsonable(forecast(st, days))
    return st.forecasts[days]


@app.post("/api/whatif")
def post_whatif(request: Request, body: WhatIfRequest):
    try:
        return jsonable(run_whatif(S(request), body.env, body.off, body.weekends))
    except WhatIfError as e:
        raise HTTPException(422, str(e))


@app.post("/api/export")
def post_export(request: Request, body: ExportRequest):
    try:
        text, filename, media = export(S(request), body.accepted, body.format)
    except ExportError as e:
        raise HTTPException(422, str(e))
    return Response(content=text.encode("utf-8"), media_type=f"{media}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
