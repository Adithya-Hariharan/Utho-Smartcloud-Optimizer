"""Checkpoint 2: cleaner (PLAN_final.md B4, B8.2)."""
import numpy as np
import pandas as pd
import pytest

from backend.pipeline.clean import VM_COLS, clean_resource, series_to_frame
from backend.pipeline.grid import grid_from_config


@pytest.fixture(scope="module")
def S(cleaned, name_to_id):
    return lambda name: cleaned.series[name_to_id[name]]


def faulted(ds, fault):
    return set(ds.faults.loc[ds.faults["fault"] == fault, "resource_id"])


# ---- unit tests on synthetic frames -------------------------------------------------------

@pytest.fixture(scope="module")
def grid(cfg):
    return grid_from_config(cfg)


def frame(grid, slots, **cols):
    ts = grid.ts_utc[np.asarray(slots)]
    df = pd.DataFrame({"ts": ts})
    for c in VM_COLS:
        df[c] = cols.get(c, np.full(len(slots), 10.0))
    return df


def test_snap_dedupe_on_grid_row_wins(grid):
    df = frame(grid, [0, 1, 2], cpu_pct=[1.0, 2.0, 3.0])
    jitter = frame(grid, [1], cpu_pct=[99.0])
    jitter["ts"] = jitter["ts"] + pd.Timedelta(minutes=3)       # 00:08 snaps onto slot 1
    raw = pd.concat([jitter, df], ignore_index=True)            # off-grid row comes first in file
    s = clean_resource(raw, "t", "vm", np.ones(grid.slots, bool), grid)
    assert s.values["cpu_pct"][:3].tolist() == [1.0, 2.0, 3.0]
    assert s.report["snapped"] == 1 and s.report["duplicates_removed"] == 1


def test_dedupe_keeps_first_in_file_order(grid):
    raw = pd.concat([frame(grid, [5], cpu_pct=[7.0]), frame(grid, [5], cpu_pct=[8.0])])
    s = clean_resource(raw, "t", "vm", np.ones(grid.slots, bool), grid)
    assert s.values["cpu_pct"][5] == 7.0


def test_range_check_and_missing_is_nan(grid):
    raw = frame(grid, [0, 1, 2], cpu_pct=[105.0, -2.0, 50.0], iops=[-1.0, 5.0, 5.0],
                net_in_mbps=[150.0, 0.0, 0.0])
    s = clean_resource(raw, "t", "vm", np.ones(grid.slots, bool), grid)
    v = s.values
    assert np.isnan(v["cpu_pct"][0]) and np.isnan(v["cpu_pct"][1]) and v["cpu_pct"][2] == 50.0
    assert np.isnan(v["iops"][0])
    assert v["net_in_mbps"][0] == 150.0                          # rates have no upper bound
    assert np.isnan(v["cpu_pct"][3])                             # never 0
    assert s.report["out_of_range_nulled"] == 3


def test_flatline_needs_cpu_and_mem_constant(grid):
    n = 40
    both = frame(grid, range(n), cpu_pct=np.zeros(n), mem_pct=np.full(n, 33.0))
    s = clean_resource(both, "t", "vm", np.ones(grid.slots, bool), grid)
    assert np.isnan(s.values["cpu_pct"][:n]).all() and s.report["flatline_nulled"] == n
    assert not np.isnan(s.values["iops"][:n]).any()               # other columns untouched

    cpu_only = frame(grid, range(n), cpu_pct=np.full(n, 40.0), mem_pct=np.arange(n, dtype=float))
    s = clean_resource(cpu_only, "t", "vm", np.ones(grid.slots, bool), grid)
    assert s.report["flatline_nulled"] == 0


def test_flatline_run_not_broken_by_missing_slots(grid):
    slots = [i for i in range(30) if i % 5 != 0]                  # 24 valid samples with holes
    raw = frame(grid, slots, cpu_pct=np.zeros(len(slots)), mem_pct=np.full(len(slots), 5.0))
    s = clean_resource(raw, "t", "vm", np.ones(grid.slots, bool), grid)
    assert s.report["flatline_nulled"] == 24


def test_short_flat_run_kept(grid):
    raw = frame(grid, range(23), cpu_pct=np.zeros(23), mem_pct=np.full(23, 5.0))
    s = clean_resource(raw, "t", "vm", np.ones(grid.slots, bool), grid)
    assert s.report["flatline_nulled"] == 0


def test_reorder_counted_and_sorted(grid):
    raw = frame(grid, [0, 3, 2, 1, 4], cpu_pct=[0.0, 3.0, 2.0, 1.0, 4.0])
    s = clean_resource(raw, "t", "vm", np.ones(grid.slots, bool), grid)
    assert s.values["cpu_pct"][:5].tolist() == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert s.report["reordered"] == 2


# ---- acceptance checks on the real dataset (B8.2) -----------------------------------------

def test_every_inventory_resource_accounted_for(cleaned, ds):
    inv = ds.inventory
    with_metrics = set(cleaned.series)
    assert with_metrics | set(cleaned.no_metrics) | set(inv.loc[inv.type == "ip", "resource_id"]) == set(inv.resource_id)
    assert cleaned.strays == ["vm-9999"]                          # vm-ghost-99 (D9)
    names = dict(zip(inv.resource_id, inv.name))
    assert {names[r] for r in cleaned.no_metrics} == {"prod-nomon-13", "vm-stopped-07"}


def test_e1_gap(S):
    assert S("prod-api-02").report["longest_gap_slots"] >= 72


def test_e2_duplicates_removed(S):
    assert S("dev-web-03").report["duplicates_removed"] >= 12


def test_only_dev_web_03_has_duplicates(cleaned, name_to_id):
    dup = {rid for rid, s in cleaned.series.items() if s.report["duplicates_removed"] > 0}
    assert dup == {name_to_id["dev-web-03"]}


def test_e3_out_of_range_nulled(cleaned, ds):
    for rid in faulted(ds, "out_of_range"):
        s = cleaned.series[rid]
        assert s.report["out_of_range_nulled"] >= 10
        cpu = s.values["cpu_pct"]
        assert np.nanmax(cpu) <= 100 and np.nanmin(cpu) >= 0


def test_e4_out_of_order_sorted(cleaned, ds):
    for rid in faulted(ds, "out_of_order"):
        assert cleaned.series[rid].report["reordered"] >= 19


def test_e8_flatline_only_dev_api_16(cleaned, S, name_to_id):
    s = S("dev-api-16")
    assert s.report["flatline_nulled"] >= 500
    day = np.arange(len(s.exists)) // 288
    assert np.isnan(s.values["cpu_pct"][(day == 15) | (day == 16)]).mean() > 0.95
    flat = {rid for rid, x in cleaned.series.items() if x.report["flatline_nulled"] > 0}
    assert flat == {name_to_id["dev-api-16"]}


def test_staging_api_09_plateau_survives(S):
    cpu = S("staging-api-09").values["cpu_pct"]
    assert S("staging-api-09").report["flatline_nulled"] == 0
    assert np.nanpercentile(cpu, 95) == pytest.approx(40.0, abs=1e-9)


def test_e10_snapped(cleaned, ds):
    for rid in faulted(ds, "ts_jitter"):
        s = cleaned.series[rid]
        assert s.report["snapped"] >= 280
        assert s.report["coverage"] > 0.98                         # snapped rows land in their own slots


def test_zero_rates_never_flatlined(S):
    assert np.nanmax(S("vol-idle-04").values["iops"]) == 0.0
    assert S("vol-idle-04").report["coverage"] > 0.98


def test_coverage_values(S):
    assert S("dev-flaky-18").report["coverage"] < 0.8
    assert 0.8 < S("staging-flaky-19").report["coverage"] < 0.95
    assert S("prod-batch-20").report["peak_window_coverage"] < 0.5


def test_existence_limits(S, ds, cfg, cleaned):
    grid = cleaned.grid
    inv = ds.inventory.set_index("name")
    s = S("dev-test-12")
    assert 2 * 288 <= s.exists.sum() <= 4 * 288
    assert S("vm-maint-08").exists[-288:].sum() == 0               # stopped 3 days ago
    assert S("prod-api-01").exists.all()
    # no raw row of any VM falls outside the slots in which it existed
    for rid, raw in ds.metrics.groupby("resource_id", observed=True):
        if rid in cleaned.series and cleaned.series[rid].kind == "vm":
            slots = np.floor(grid.slot_of(raw["ts"]) + 1e-9).astype(int)
            assert cleaned.series[rid].exists[slots].all(), rid


def test_idempotent(cleaned, grid, name_to_id):
    for name in ["dev-web-03", "dev-api-16", "prod-api-02", "staging-api-09"]:
        s = cleaned.series[name_to_id[name]]
        again = clean_resource(series_to_frame(s, grid), s.resource_id, s.kind, s.exists, grid)
        for c in s.values:
            np.testing.assert_array_equal(again.values[c], s.values[c])
