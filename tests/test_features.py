"""Checkpoint 3: features (PLAN_final.md B4, B8.3)."""
import time

import numpy as np
import pytest

from backend.pipeline.clean import clean_all
from backend.pipeline.features import compute_features, leak_score, pct_summary, trend


@pytest.fixture(scope="module")
def built(ds, cfg):
    t0 = time.perf_counter()
    cleaned = clean_all(ds, cfg)
    feats = compute_features(cleaned, ds, cfg)
    return cleaned, feats, time.perf_counter() - t0


@pytest.fixture(scope="module")
def F(built, name_to_id):
    return lambda name: built[1][name_to_id[name]]


# ---- units ---------------------------------------------------------------------------------

def test_pct_summary_linear_and_nan_excluded():
    s = pct_summary(np.array([1.0, 2.0, 3.0, 4.0, np.nan]))
    assert s["p50"] == 2.5 and s["max"] == 4.0
    assert pct_summary(np.array([np.nan]))["p95"] is None


def test_trend_days_to_limit():
    t = trend(np.array([10.0, 11.0, 12.0, np.nan, 14.0]))
    assert t["slope"] == pytest.approx(1.0)
    assert t["days_to_90"] == pytest.approx(76.0)
    assert trend(np.array([5.0, 4.0, 3.0]))["days_to_90"] is None     # slope <= 0
    assert trend(np.array([95.0, 96.0]))["days_to_90"] == 0.0         # already past
    assert trend(np.array([5.0]))["slope"] is None


def test_leak_score_counts_big_drops_across_gaps():
    mem = np.array([30, 50, 70, np.nan, 20, 40, 60, 80, 30, 31], dtype=float)
    assert leak_score(mem, 25) == 2


def test_leak_score_ignores_drop_with_cpu_drop():
    mem = np.array([30, 70, 30, 70, 30], dtype=float)
    cpu = np.array([10, 90, 5, 10, 10], dtype=float)                 # first drop is a batch ending
    assert leak_score(mem, 25, cpu, 20) == 1


def test_trend_r2():
    assert trend(np.array([1.0, 2.0, 3.0]))["r2"] == pytest.approx(1.0)
    assert trend(np.array([0.0, 10.0, 0.0, 10.0, 0.0, 10.0]))["r2"] < 0.5


def test_recurring_peak(F):
    assert F("prod-batch-07")["recurring_peak"]["weeks"] >= 4
    assert F("prod-billing-01")["recurring_peak"]["labels"][0].startswith("Sun")
    assert F("prod-burst-58")["recurring_peak"] is not None
    assert F("prod-queue-02")["recurring_peak"] is None              # random bursts are not scheduled
    assert F("prod-reports-02")["recurring_peak"] is None            # one day only


def test_peak_hours_coverage(F):
    assert F("prod-batch-20")["peak_hours_coverage"] < 0.5           # E9: gap lands on the batch
    assert F("staging-flaky-19")["peak_hours_coverage"] is None      # no peak hours to miss
    assert F("prod-batch-07")["peak_hours_coverage"] > 0.9


def test_leak_feature_no_batch_false_positive(F):
    assert F("prod-orders-08")["leak_score"] >= 3
    for name in ["prod-batch-07", "prod-batch-65", "staging-batch-68", "dev-batch-69"]:
        assert F(name)["leak_score"] < 3, name


# ---- every resource has features --------------------------------------------------------

def test_all_140_resources(built, ds):
    feats = built[1]
    assert set(feats) == set(ds.inventory["resource_id"])
    ip = next(f for f in feats.values() if f["kind"] == "ip")
    assert ip["days_of_data"] == 0 and ip["coverage"] == 0.0 and ip["metrics"]["cpu"]["p95"] is None


def test_runtime_under_30s(built):
    assert built[2] < 30


# ---- acceptance checks (B8.3) --------------------------------------------------------------

def test_prod_batch_07(F):
    f = F("prod-batch-07")
    assert 6 <= f["mean_cpu"] <= 10
    assert 88 <= f["metrics"]["cpu"]["p99"] <= 95
    assert f["recurring_peak_days"] >= 25


def test_prod_cache_04_memory(F):
    assert F("prod-cache-04")["metrics"]["mem"]["p99"] >= 80


def test_dev_web_03_weekend(built, name_to_id):
    cleaned = built[0]
    cpu = cleaned.series[name_to_id["dev-web-03"]].values["cpu_pct"]
    weekend = cpu[cleaned.grid.is_weekend]
    assert np.nanpercentile(weekend, 95) < 5


def test_prod_api_04_trend(F):
    t = F("prod-api-04")["trend"]["cpu"]
    assert t["slope"] > 1 and t["days_to_85"] is not None


def test_level_shifts(F):
    assert F("prod-worker-05")["level_shift_up"] >= 3.5
    assert F("prod-legacy-06")["level_shift_down"] < 0.2
    assert F("prod-api-01")["level_shift_up"] < 1.5


def test_leak_and_flat_memory(F):
    assert F("prod-orders-08")["leak_score"] >= 3
    assert F("prod-search-06")["mem_flatness"] < 2 and F("prod-search-06")["mean_mem"] >= 75


def test_coverage_features(F):
    assert F("dev-flaky-18")["coverage"] < 0.8
    assert F("dev-test-12")["days_of_data"] <= 4
    assert F("prod-api-01")["days_of_data"] == 30


def test_iops_and_network_units(F):
    assert F("prod-ingest-09")["metrics"]["iops_pct"]["p95"] >= 70
    assert F("prod-gateway-03")["metrics"]["net_pct"]["p95"] >= 60
    assert F("vol-idle-04")["iops_p95"] == 0.0


def test_single_spike_excluded_by_top_day(F):
    f = F("prod-reports-02")
    assert f["metrics"]["cpu"]["p99"] >= 85 and f["p99_excl_top_day"] < 40


def test_how_profile_shape(F):
    f = F("dev-etl-04")
    assert len(f["how_p95"]) == 168 and len(f["how_p95_by_week"]) == 5
    # Monday 02:00 IST bucket (index 2) is busy for the nightly job
    assert f["how_p95"][2] >= 50


def test_volume_trend(F):
    assert F("vol-growing-10")["trend"]["disk_used"]["slope"] == pytest.approx(2.0, abs=0.2)
