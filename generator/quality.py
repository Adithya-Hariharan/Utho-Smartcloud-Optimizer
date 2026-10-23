"""Data-quality fault injection (PLAN.md section 8, group E). Each function returns (df, detail)."""
import numpy as np
import pandas as pd

from .config import SLOTS_PER_DAY, TZ, fitted

METRIC_COLS = ["cpu_pct", "mem_pct", "disk_used_pct", "iops", "net_in_mbps", "net_out_mbps"]


def _ist(df):
    t = df["ts"].dt.tz_convert(TZ)
    return t, (t.dt.hour + t.dt.minute / 60).to_numpy()


def gap_6h(df, rng):
    t, h = _ist(df)
    m = (df["slot"] // SLOTS_PER_DAY == 12).to_numpy() & (h >= 10) & (h < 16)
    return df[~m], f"removed {m.sum()} rows: 2026-10-02 10:00-16:00 IST"


def duplicate_block(df, rng):
    t, h = _ist(df)
    m = (df["slot"] // SLOTS_PER_DAY == 9).to_numpy() & (h >= 14) & (h < 15)
    dup = df[m].copy()
    for c in METRIC_COLS:
        dup[c] = dup[c] * rng.normal(1, 0.02, len(dup))
    dup["_dup"] = 1
    out = pd.concat([df.assign(_dup=0), dup]).sort_values(["slot", "_dup"], kind="stable").drop(columns="_dup")
    return out, f"re-sent {m.sum()} rows (2026-09-29 14:00-15:00 IST) with slightly different values"


def out_of_range(df, rng):
    df = df.copy()
    idx = rng.choice(len(df), 10, replace=False)
    df.iloc[idx[:5], df.columns.get_loc("cpu_pct")] = rng.uniform(103, 110, 5)
    df.iloc[idx[5:], df.columns.get_loc("cpu_pct")] = rng.uniform(-3, -1, 5)
    return df, "5 CPU values in 103-110%, 5 in -3..-1%"


def out_of_order(df, rng):
    start = int(rng.integers(100, len(df) - 100))
    order = np.arange(len(df))
    order[start:start + 20] = order[start:start + 20][::-1]
    return df.iloc[order], f"20 rows reversed at row {start}"


def reboot_gap(df, rng):
    start = int(rng.integers(100, len(df) - 100))
    return df.drop(df.index[start:start + 4]), f"20-minute reboot gap at row {start}"


def _drop_hours(df, rng, share):
    hours = df["slot"].to_numpy() // 12
    uniq = np.unique(hours)
    gone = rng.choice(uniq, int(round(share * len(uniq))), replace=False)
    m = np.isin(hours, gone)
    return df[~m], f"removed {len(gone)} of {len(uniq)} hours ({m.mean():.0%} of rows)"


def missing_30(df, rng):
    return _drop_hours(df, rng, 0.30)


def missing_12(df, rng):
    return _drop_hours(df, rng, 0.12)


def flatline_48h(df, rng):
    df = df.copy()
    m = (df["slot"] // SLOTS_PER_DAY).isin([15, 16]).to_numpy()
    first = df.loc[m].iloc[0]
    df.loc[m, "cpu_pct"] = 0.0
    df.loc[m, "mem_pct"] = first["mem_pct"]
    df.loc[m, "disk_used_pct"] = first["disk_used_pct"]
    df.loc[m, ["iops", "net_in_mbps", "net_out_mbps"]] = 0.0
    return df, f"stuck agent: {m.sum()} rows of CPU 0.0 / constant memory (2026-10-05..06)"


def peak_gap(df, rng):
    t, h = _ist(df)
    nights = rng.choice(30, 18, replace=False)
    m = np.isin(df["slot"].to_numpy() // SLOTS_PER_DAY, nights) & (h >= 1) & (h < 4)
    return df[~m], f"01:00-04:00 missing on 18 of 30 nights ({m.sum()} rows)"


def ts_jitter(df, rng):
    df = df.copy()
    m = (df["slot"] // SLOTS_PER_DAY == 5).to_numpy()
    df.loc[m, "ts"] = df.loc[m, "ts"] + pd.Timedelta(minutes=3)
    return df, f"{m.sum()} timestamps offset +3 min on 2026-09-25 (e.g. 05:03)"


def random_drops(df, rng, share=None):
    """Monitoring gaps at the rate measured in the Bitbrains mirror (median NaN share per VM)."""
    share = fitted("missing_share_bitbrains") if share is None else share
    m = rng.random(len(df)) < share
    return df[~m], f"{m.sum()} random rows dropped"


FAULTS = {f.__name__: f for f in (gap_6h, duplicate_block, out_of_range, out_of_order, reboot_gap,
                                  missing_30, missing_12, flatline_48h, peak_gap, ts_jitter)}
# value faults first, then row removal, then reordering/timestamp faults
ORDER = ["flatline_48h", "out_of_range", "gap_6h", "missing_30", "missing_12", "peak_gap", "reboot_gap",
         "duplicate_block", "ts_jitter", "out_of_order"]
