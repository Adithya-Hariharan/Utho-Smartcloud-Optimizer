"""CP1 - clean raw 5-minute metrics into fixed-grid arrays (NaN = not observed, never 0).

Every candidate returns (arrays, dq) where arrays has cpu, mem, disk, iops, net_in, net_out on the
full window grid and dq is the data-quality report used by later components and the trace.
"""
import numpy as np
import pandas as pd

METRICS = ["cpu_pct", "mem_pct", "disk_used_pct", "iops", "net_in_mbps", "net_out_mbps"]
PCT = ["cpu_pct", "mem_pct", "disk_used_pct"]


def _grid(df, ctx, n_slots):
    cfg = ctx.cfg
    step = pd.Timedelta(minutes=cfg.t("slot_minutes"))
    ts = df["ts"].dt.floor(step)
    slot = ((ts - ctx.data.window_start.tz_convert("UTC")) // step).to_numpy()
    d = df.assign(slot=slot).sort_values("slot", kind="stable")
    n_raw = len(d)
    d = d.drop_duplicates("slot", keep="first")
    dq = {"duplicates_dropped": int(n_raw - len(d)), "out_of_range": 0, "flatline_slots": 0, "interpolated_slots": 0}
    d = d[(d["slot"] >= 0) & (d["slot"] < n_slots)]
    arr = {}
    for c in METRICS:
        x = np.full(n_slots, np.nan)
        x[d["slot"].to_numpy()] = d[c].to_numpy(dtype=float)
        if c in PCT:
            bad = (x < cfg("clean.pct_min")) | (x > 100)
        else:
            bad = x < cfg("clean.pct_min")
        dq["out_of_range"] += int(np.nansum(bad))
        x[bad] = np.nan
        arr[c] = x
    return arr, dq


def _runs(mask):
    """(start, length) of True runs."""
    m = np.concatenate([[False], mask, [False]]).astype(int)
    d = np.diff(m)
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return zip(starts, ends - starts)


def _flatline(arr, cfg, cols):
    """Mask runs where every metric in `cols` repeats the exact same value for >= flatline_hours."""
    min_len = int(cfg("clean.flatline_hours") * cfg.t("slots_per_hour"))
    same = np.ones(len(arr["cpu_pct"]) - 1, dtype=bool)
    for c in cols:
        x = arr[c]
        same &= (x[1:] == x[:-1]) & np.isfinite(x[1:])
    masked = 0
    for s, n in _runs(same):
        if n + 1 >= min_len:
            for c in METRICS:
                arr[c][s:s + n + 1] = np.nan
            masked += n + 1
    return masked


def _interp(arr, cfg):
    k = int(cfg("clean.interp_max_slots"))
    filled = 0
    for c in METRICS:
        x = arr[c]
        nan = ~np.isfinite(x)
        for s, n in _runs(nan):
            if n <= k and s > 0 and s + n < len(x):
                x[s:s + n] = np.linspace(x[s - 1], x[s + n], n + 1 + 1)[1:-1]
                filled += n if c == "cpu_pct" else 0
    return filled


def a_basic(df, ctx, n_slots):
    """Snap to grid, de-duplicate, out-of-range -> NaN."""
    return _grid(df, ctx, n_slots)


def b_flat_cpu(df, ctx, n_slots):
    """a + mask CPU-only flatlines (naive stuck-agent detector)."""
    arr, dq = _grid(df, ctx, n_slots)
    dq["flatline_slots"] = _flatline(arr, ctx.cfg, ["cpu_pct"])
    return arr, dq


def c_flat_all(df, ctx, n_slots):
    """a + mask flatlines only when CPU AND memory are both frozen (a real stuck agent freezes everything)."""
    arr, dq = _grid(df, ctx, n_slots)
    dq["flatline_slots"] = _flatline(arr, ctx.cfg, ["cpu_pct", "mem_pct"])
    return arr, dq


def d_flat_all_interp(df, ctx, n_slots):
    """c + linearly bridge gaps of <= 15 min (coverage is measured before bridging)."""
    arr, dq = c_flat_all(df, ctx, n_slots)
    dq["coverage_before_interp"] = float(np.isfinite(arr["cpu_pct"]).mean())
    dq["interpolated_slots"] = _interp(arr, ctx.cfg)
    return arr, dq


CANDIDATES = {
    "a_basic": {"fn": a_basic, "params": 1, "prior": 6, "desc": "snap to grid + de-duplicate + out-of-range -> NaN"},
    "b_flat_cpu": {"fn": b_flat_cpu, "params": 2, "prior": 7, "desc": "a + mask CPU-only flatlines >= 2 h"},
    "c_flat_all": {"fn": c_flat_all, "params": 2, "prior": 8, "desc": "a + mask flatlines where CPU and memory are both frozen >= 2 h"},
    "d_flat_all_interp": {"fn": d_flat_all_interp, "params": 3, "prior": 6, "desc": "c + bridge gaps <= 15 min by interpolation"},
}
