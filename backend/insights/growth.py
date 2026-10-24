"""Bill trend and growth waterfall from billing_daily (summary.bill_trend_6m and summary.growth_waterfall,
in the frontend's shape: frontend/src/types/api.ts Summary)."""
import numpy as np
import pandas as pd

BLOCK_DAYS = 30


def first_billed(billing):
    """resource_id -> first date with a non-zero cost."""
    return billing[billing["cost_inr"] > 0].groupby("resource_id")["date"].min()


def _labelled(billing):
    return billing.assign(env=billing["env"].replace("", "untagged"), team=billing["team"].replace("", "unowned"))


def bill_trend(billing):
    """{dates[180], total[], by_env{k: []}, by_team{k: []}}: daily billed cost."""
    b = _labelled(billing)
    dates = sorted(b["date"].unique())

    def series(col):
        piv = b.pivot_table(index="date", columns=col, values="cost_inr", aggfunc="sum").reindex(dates).fillna(0.0)
        return {str(k): [round(float(v), 2) for v in piv[k].to_numpy()] for k in piv.columns}

    total = b.groupby("date")["cost_inr"].sum().reindex(dates).to_numpy()
    return {"dates": [f"{pd.Timestamp(d):%Y-%m-%d}" for d in dates], "total": [round(float(v), 2) for v in total],
            "by_env": series("env"), "by_team": series("team")}


def growth_waterfall(billing, inventory, monthly):
    """First 30 billed days -> last 30, by env, team and age (new vs existing). Each breakdown sums to the delta
    and is sorted by delta, largest first."""
    b = _labelled(billing)
    start, end = b["date"].min(), b["date"].max()
    first = b[b["date"] < start + pd.Timedelta(days=BLOCK_DAYS)]
    last = b[b["date"] > end - pd.Timedelta(days=BLOCK_DAYS)]
    tz = inventory["created_at"].dt.tz
    cutoff = (start + pd.Timedelta(days=BLOCK_DAYS)).tz_localize(tz)
    new = inventory[inventory["created_at"] >= cutoff]
    b = b.assign(age=np.where(b["resource_id"].isin(set(new["resource_id"])), "new resources", "existing resources"))
    first = b[b["date"] < start + pd.Timedelta(days=BLOCK_DAYS)]
    last = b[b["date"] > end - pd.Timedelta(days=BLOCK_DAYS)]

    def deltas(col):
        f, l_ = first.groupby(col)["cost_inr"].sum(), last.groupby(col)["cost_inr"].sum()
        rows = [{"key": str(k), "first30_inr": int(round(f.get(k, 0))), "last30_inr": int(round(l_.get(k, 0)))}
                for k in sorted(set(f.index) | set(l_.index))]
        for r in rows:
            r["delta_inr"] = r["last30_inr"] - r["first30_inr"]
        return sorted(rows, key=lambda r: -r["delta_inr"])

    return {
        "first30": {"start": f"{start:%Y-%m-%d}", "total_inr": int(round(first["cost_inr"].sum()))},
        "last30": {"end": f"{end:%Y-%m-%d}", "total_inr": int(round(last["cost_inr"].sum()))},
        "growth_ratio": round(float(last["cost_inr"].sum() / first["cost_inr"].sum()), 4),
        "by_env": deltas("env"), "by_team": deltas("team"), "by_age": deltas("age"),
        "new_resources": [{"resource_id": r.resource_id, "name": r.name, "team": r.owner_team or "unowned",
                           "env": r.env or "untagged", "type": r.type, "created_at": r.created_at.isoformat(),
                           "monthly_inr": int(monthly.get(r.resource_id, 0))} for r in new.itertuples()],
    }
