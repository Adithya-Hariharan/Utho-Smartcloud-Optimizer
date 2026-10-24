"""Bill trend and growth waterfall from billing_daily (PLAN_final.md B5, B6 /summary)."""
import numpy as np
import pandas as pd

BLOCK_DAYS = 30


def first_billed(billing):
    """resource_id -> first date with a non-zero cost."""
    return billing[billing["cost_inr"] > 0].groupby("resource_id")["date"].min()


def bill_trend_6m(billing):
    dates = np.sort(billing["date"].unique())
    daily = billing.groupby("date")["cost_inr"].sum().reindex(dates)
    out = []
    for i in range(len(dates) // BLOCK_DAYS):
        block = dates[i * BLOCK_DAYS:(i + 1) * BLOCK_DAYS]
        a, b = pd.Timestamp(block[0]), pd.Timestamp(block[-1])
        out.append({"label": f"M{i + 1} ({a:%d %b}–{b:%d %b})", "total_inr": int(round(daily.loc[block].sum()))})
    return out


def growth_waterfall(billing, trend):
    """Month 6 minus month 1: one step per env/team pair of resources first billed after month 1,
    plus an 'existing resources' remainder. Steps sum exactly to the trend's M6 - M1."""
    dates = np.sort(billing["date"].unique())
    m1, m6 = dates[:BLOCK_DAYS], dates[-BLOCK_DAYS:]
    first = first_billed(billing)
    new_ids = set(first[first > m1[-1]].index)
    b = billing.assign(env=billing["env"].replace("", "untagged"), team=billing["team"].replace("", "unowned"))
    new = b[b["resource_id"].isin(new_ids)]
    steps = []
    for (env, team), g in new.groupby(["env", "team"], sort=True):
        delta = g.loc[g["date"].isin(m6), "cost_inr"].sum() - g.loc[g["date"].isin(m1), "cost_inr"].sum()
        steps.append({"label": f"New {env} resources ({team})", "group": f"{env}/{team}",
                      "delta_inr": int(round(delta))})
    total = trend[-1]["total_inr"] - trend[0]["total_inr"]
    steps.append({"label": "Existing resources", "group": "existing",
                  "delta_inr": int(total - sum(s["delta_inr"] for s in steps))})
    return steps
