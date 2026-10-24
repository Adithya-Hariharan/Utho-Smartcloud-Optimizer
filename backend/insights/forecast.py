"""GET /api/forecast: 90-day bill forecast (Holt-Winters, weekly season) + carbon estimate per option.

Carbon uses PLACEHOLDER coefficients from config.yaml `carbon` (published CCF / CEA averages, not measured from
this dataset; see PLAN_frontend_integration.md §10). Formulas follow the frontend reference
(docs/reference/mock_engine.py vm_kwh_month / carbon_by_option).
"""
import math

import numpy as np
import pandas as pd


def holt_winters(y, m, alpha, beta, gamma, h):
    """Additive Holt-Winters with season length m; returns (forecast, residual std)."""
    y = list(y)
    level = float(np.mean(y[:m]))
    trend = float((np.mean(y[m:2 * m]) - np.mean(y[:m])) / m)
    season = [y[i] - level for i in range(m)]
    resid = []
    for t, v in enumerate(y):
        s_ = season[t % m]
        if t >= 2 * m:
            resid.append(v - (level + trend + s_))
        prev = level
        level = alpha * (v - s_) + (1 - alpha) * (level + trend)
        trend = beta * (level - prev) + (1 - beta) * trend
        season[t % m] = gamma * (v - level) + (1 - gamma) * s_
    return [level + (k + 1) * trend + season[(len(y) + k) % m] for k in range(h)], (float(np.std(resid)) if resid else 0.0)


def vm_kwh_month(c, vcpu, ram_gb, util_pct, hours_per_month, on_fraction=1.0):
    w = vcpu * (c["w_per_vcpu_min"] + min(util_pct, 100) / 100 * (c["w_per_vcpu_max"] - c["w_per_vcpu_min"])) \
        + ram_gb * c["w_per_gb_ram"]
    return w * c["pue"] * hours_per_month / 1000 * on_fraction


def carbon_by_option(item, util, c, hpm):
    """kWh and kg CO2 saved per month for each option, in the item's option order (volumes / IPs: 0)."""
    cur = item["current"]
    if item["resource"]["type"] != "vm" or not cur.get("vcpu") or item["resource"]["state"] != "running":
        return {k: {"kwh_month": 0.0, "kg_co2_month": 0.0} for k in item["options"]}
    before = vm_kwh_month(c, cur["vcpu"], cur["ram_gb"], util, hpm)
    on = (item["schedule"] or {}).get("on_hours_per_week", 168) / 168
    tgt = item["target"]
    out = {}
    for k in item["options"]:
        acts = set(k.split("+")) if k != "none" else set()
        if acts & {"stop", "delete"}:
            after = 0.0
        else:
            vcpu, ram = (tgt["vcpu"], tgt["ram_gb"]) if tgt and acts & {"resize", "upsize"} else (cur["vcpu"], cur["ram_gb"])
            after = vm_kwh_month(c, vcpu, ram, util * cur["vcpu"] / vcpu, hpm, on if "schedule" in acts else 1.0)
        kwh = round(before - after, 1)
        out[k] = {"kwh_month": kwh, "kg_co2_month": round(kwh * c["kg_co2_per_kwh"], 1)}
    return out


def forecast(st, days=90):
    cfg = st.cfg
    g = lambda k: cfg.get(f"forecast.{k}")
    b = st.ds.billing
    dates = sorted(b["date"].unique())
    daily = b.groupby("date")["cost_inr"].sum().reindex(dates).to_numpy()
    fc, sd = holt_winters(daily, int(g("season_days")), g("alpha"), g("beta"), g("gamma"), days)
    last = pd.Timestamp(dates[-1])
    hist = int(g("history_days"))
    c = cfg.raw["carbon"]
    hpm = cfg.get("billing.hours_per_month")
    util = lambda rid: (st.features.get(rid) or {}).get("mean_cpu") or c["default_util_pct"]
    by_option = {}
    for preset, items in st.by_id.items():
        for it in items.values():
            if it["verdict"] in ("recommend", "upsize"):
                by_option[it["rec_id"]] = carbon_by_option(it, util(it["resource"]["resource_id"]), c, hpm)
    fleet = sum(vm_kwh_month(c, r["vcpu"], r["ram_gb"], util(rid), hpm) for rid, r in st.inv.iterrows()
                if r["type"] == "vm" and r["state"] == "running" and not math.isnan(r["vcpu"]))
    pot = sum(by_option[i["rec_id"]][i["default_option"]]["kwh_month"] for i in st.by_id["default"].values()
              if i["verdict"] == "recommend")
    return {
        "days": days,
        "method": "Holt-Winters additive, weekly season, fitted on 180 days of daily cost",
        "monthly_now_inr": int(sum(st.monthly[r] for r in st.inv.index)),
        "history": {"dates": [f"{pd.Timestamp(d):%Y-%m-%d}" for d in dates[-hist:]],
                    "total": [round(float(v), 2) for v in daily[-hist:]]},
        "forecast": {"dates": [f"{last + pd.Timedelta(days=k + 1):%Y-%m-%d}" for k in range(days)],
                     "baseline": [round(v, 2) for v in fc],
                     "lower": [round(v - 1.96 * sd * math.sqrt(k + 1), 2) for k, v in enumerate(fc)],
                     "upper": [round(v + 1.96 * sd * math.sqrt(k + 1), 2) for k, v in enumerate(fc)]},
        "carbon": {"coefficients": {k: c[k] for k in ("w_per_vcpu_min", "w_per_vcpu_max", "w_per_gb_ram", "pue",
                                                      "kg_co2_per_kwh", "source")},
                   "fleet_kwh_month": round(fleet, 1), "fleet_kg_co2_month": round(fleet * c["kg_co2_per_kwh"], 1),
                   "potential_kwh_month": round(pot, 1), "potential_kg_co2_month": round(pot * c["kg_co2_per_kwh"], 1),
                   "by_option": by_option},
    }
