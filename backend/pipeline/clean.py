"""Cleaner (PLAN_final.md B4): raw long metrics -> one NaN-padded 8,640-slot array per metric.

Steps, per resource: snap to grid -> stable sort -> de-duplicate -> range check -> flatline -> reindex.
Every step is counted in the per-resource data-quality report.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .grid import grid_from_config

VM_COLS = ["cpu_pct", "mem_pct", "disk_used_pct", "iops", "net_in_mbps", "net_out_mbps"]
VOLUME_COLS = ["iops", "disk_used_pct"]
PCT_COLS = {"cpu_pct", "mem_pct", "disk_used_pct"}


@dataclass
class CleanSeries:
    resource_id: str
    kind: str                       # "vm" | "volume"
    values: dict                    # column -> float64 array (n_slots), NaN = missing
    exists: np.ndarray              # bool (n_slots): the resource existed in that slot
    report: dict = field(default_factory=dict)

    @property
    def primary(self):
        """CPU for VMs, IOPS for volumes: the column coverage is measured on."""
        return self.values["cpu_pct" if self.kind == "vm" else "iops"]


@dataclass
class CleanResult:
    grid: object
    series: dict                    # resource_id -> CleanSeries (inventory resources with metrics)
    strays: list                    # metric resource_ids with no inventory row (D9)
    no_metrics: list                # inventory VMs with no metric rows


def existence_mask(inv_row, grid):
    """Slots in which a VM existed: from created_at (rounded up) to stopped_since (exclusive)."""
    mask = np.ones(grid.slots, dtype=bool)
    if inv_row["type"] != "vm":
        return mask                                  # volumes: full window (B9a, item 4)
    created = inv_row["created_at"]
    if pd.notna(created):
        first = int(np.ceil(grid.slot_of([created])[0]))
        mask[: max(0, min(first, grid.slots))] = False
    stopped = inv_row["stopped_since"]
    if pd.notna(stopped):
        last = int(np.ceil(grid.slot_of([stopped])[0]))
        mask[max(0, min(last, grid.slots)):] = False
    return mask


def _flatline(cpu, mem, min_run):
    """Runs of >= min_run consecutive valid samples where cpu AND mem both stay constant -> NaN in both.
    Missing slots do not break a run (only valid samples are compared)."""
    idx = np.flatnonzero(~np.isnan(cpu) & ~np.isnan(mem))
    if len(idx) < min_run:
        return 0
    same = (np.diff(cpu[idx]) == 0) & (np.diff(mem[idx]) == 0)
    nulled = 0
    i = 0
    n = len(same)
    while i < n:
        if not same[i]:
            i += 1
            continue
        j = i
        while j < n and same[j]:
            j += 1
        run = j - i + 1                              # samples idx[i]..idx[j]
        if run >= min_run:
            hit = idx[i:j + 1]
            cpu[hit] = np.nan
            mem[hit] = np.nan
            nulled += run
        i = j
    return nulled


def _longest_nan_run(arr, exists):
    gap = np.isnan(arr) & exists
    if not gap.any():
        return 0
    edges = np.diff(np.concatenate(([0], gap.astype(np.int8), [0])))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return int((ends - starts).max())


def peak_window_coverage(valid, exists, hour_of_week):
    """Minimum coverage across the 168 IST hour-of-week buckets, ignoring buckets with no existing slots."""
    have = np.bincount(hour_of_week[exists], minlength=168)
    got = np.bincount(hour_of_week[valid & exists], minlength=168)
    used = have > 0
    if not used.any():
        return 0.0
    return float((got[used] / have[used]).min())


def clean_resource(raw, resource_id, kind, exists, grid, flatline_slots=24):
    """raw: rows of one resource in file order (columns ts + metric columns)."""
    cols = VM_COLS if kind == "vm" else VOLUME_COLS
    pos = grid.slot_of(raw["ts"])
    slot = np.floor(pos + 1e-9).astype(np.int64)
    off_grid = np.abs(pos - slot) > 1e-9
    # rows that arrive earlier than a row already seen (a reversed block of 20 counts 19)
    reordered = int((pos < np.maximum.accumulate(pos)).sum()) if len(pos) else 0

    # stable sort by slot; within a slot the on-grid row wins, then original file order
    order = np.lexsort((np.arange(len(slot)), off_grid, slot))
    slot_s = slot[order]
    keep = np.ones(len(slot_s), dtype=bool)
    keep[1:] = slot_s[1:] != slot_s[:-1]
    inside = (slot_s >= 0) & (slot_s < grid.slots)
    rows = order[keep & inside]
    slots_kept = slot[rows]

    values, out_of_range = {}, 0
    for c in cols:
        v = raw[c].to_numpy(dtype="float64")[rows]
        bad = (v < 0) | ((v > 100) if c in PCT_COLS else np.zeros(len(v), dtype=bool))
        out_of_range += int(bad.sum())
        v = np.where(bad, np.nan, v)
        arr = np.full(grid.slots, np.nan)
        arr[slots_kept] = v
        arr[~exists] = np.nan
        values[c] = arr

    flat = _flatline(values["cpu_pct"], values["mem_pct"], flatline_slots) if kind == "vm" else 0
    s = CleanSeries(resource_id, kind, values, exists)
    valid = ~np.isnan(s.primary) & exists
    n_exist = int(exists.sum())
    s.report = {
        "resource_id": resource_id,
        "rows_in": int(len(raw)),
        "snapped": int(off_grid.sum()),
        "reordered": reordered,
        "duplicates_removed": int((~keep).sum()),
        "outside_window": int((keep & ~inside).sum()),
        "out_of_range_nulled": out_of_range,
        "flatline_nulled": int(flat),
        "coverage": round(float(valid.sum() / n_exist), 4) if n_exist else 0.0,
        "peak_window_coverage": round(peak_window_coverage(valid, exists, grid.hour_of_week), 4),
        "longest_gap_slots": _longest_nan_run(s.primary, exists),
    }
    return s


def empty_report(resource_id):
    return {"resource_id": resource_id, "rows_in": 0, "snapped": 0, "reordered": 0,
            "duplicates_removed": 0, "outside_window": 0, "out_of_range_nulled": 0, "flatline_nulled": 0,
            "coverage": 0.0, "peak_window_coverage": 0.0, "longest_gap_slots": 0}


def clean_all(ds, cfg):
    grid = grid_from_config(cfg)
    flat = int(cfg.get("thresholds.flatline_slots"))
    inv = ds.inventory.set_index("resource_id")
    series, strays = {}, []
    for kind, frame in (("vm", ds.metrics), ("volume", ds.volume_metrics)):
        for rid, raw in frame.groupby("resource_id", sort=True, observed=True):
            if rid not in inv.index:
                strays.append(rid)
                continue
            row = inv.loc[rid]
            series[rid] = clean_resource(raw, rid, kind, existence_mask(row, grid), grid, flat)
    vms = inv.index[inv["type"] == "vm"]
    no_metrics = sorted(r for r in vms if r not in series)
    return CleanResult(grid=grid, series=series, strays=sorted(strays), no_metrics=no_metrics)


def series_to_frame(s, grid):
    """Back to long format (existing slots only), e.g. to check idempotency."""
    df = pd.DataFrame({"ts": grid.ts_utc[s.exists]})
    for c, arr in s.values.items():
        df[c] = arr[s.exists]
    return df
