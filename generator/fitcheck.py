"""CP5: checks that were missing from validate.py.

FIT   - synthetic bulk fleet vs real-trace statistics in fitted_params.json. Statistics are measured
        with the SAME functions the fitter used (generator.fit.fit), so the comparison is like-for-like.
TRUTH - every bulk VM still satisfies the definition behind its expected verdict in truth.csv.
PROV  - every fitted value has a source and n; downloaded trace hashes still match.
INFO  - composition-dependent fleet statistics, reported (not pass/fail) next to the real values,
        because the archetype MIX is a scenario assumption, not something a trace can fit.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

from .config import FITTED, N_SLOTS, SLOTS_PER_DAY
from .fit.fit import linfit, log_resid_sd, vm_features
from .signals import AX

ROOT = Path(__file__).resolve().parent.parent
START_IST = np.datetime64("2026-09-20T00:00")
BULK = {"right_sized_prod", "steady_low", "bursty_daily", "batch_nightly", "office_hours_dev", "zombie", "memory_bound"}


def _grid(d, col):
    x = np.full(N_SLOTS, np.nan)
    s = d["slot"].to_numpy()
    ok = (s >= 0) & (s < N_SLOTS)
    x[s[ok]] = d[col].to_numpy(dtype=float)[ok]
    return x


def _iqr(key):
    if key.startswith("archetypes."):
        _, arch, stat = key.split(".")
        e = FITTED["archetypes"][arch][stat]
        return e["p25"], e["p75"], e["p50"]
    e = FITTED[key]
    return e["p25"], e["p75"], e["value"]


def _features(g, truth):
    rows = []
    for _, t in truth.iterrows():
        if t.archetype not in BULK or t.resource_id not in g:
            continue
        d = g[t.resource_id]
        if d["day"].nunique() < 25:                    # growth-team VMs created on day 22
            continue
        cpu, mem = _grid(d, "cpu_pct"), _grid(d, "mem_pct")
        f = vm_features(cpu, START_IST, 0)
        hod, weekend, day = f.pop("hod"), f.pop("weekend"), f.pop("day")
        from .fit.fit import lag1, residual
        f["archetype"], f["env"] = t.archetype, t.get("env", "")
        f["mem_phi"] = lag1(residual(mem, hod, weekend, day))
        f["mem_slope"], icpt = linfit(cpu, mem)
        f["mem_noise_sd"] = float(np.nanstd(mem - (icpt + f["mem_slope"] * cpu))) if np.isfinite(f["mem_slope"]) else np.nan
        f["mem_cv"] = float(np.nanstd(mem) / max(np.nanmean(mem), 0.1))
        f["mem_p"] = {}
        nin, nout = _grid(d, "net_in_mbps"), _grid(d, "net_out_mbps")
        f["net_out_in"] = float(np.nansum(nout) / np.nansum(nin)) if np.nansum(nin) > 0 else np.nan
        tot = nin + nout
        s1, s0 = linfit(cpu, tot)
        f["net_sigma"] = log_resid_sd(tot, s0 + s1 * cpu) if np.isfinite(s1) and s1 > 0 else np.nan
        io = _grid(d, "iops")
        s1, s0 = linfit(cpu, io)
        f["iops_sigma"] = log_resid_sd(io, s0 + s1 * cpu) if np.isfinite(s1) else np.nan
        x = np.nan_to_num(cpu, nan=np.nanmedian(cpu))
        med = np.median(x)
        mad = np.median(np.abs(x - med)) + 1e-6
        hi = (x > med + 4 * mad).astype(int)
        f["spikes_per_day"] = int((np.diff(np.concatenate([[0], hi])) == 1).sum()) / 30
        f["mem_p95"], f["mem_p99"] = float(np.nanpercentile(mem, 95)), float(np.nanpercentile(mem, 99))
        f["weekend_p95"] = float(np.nanpercentile(cpu[weekend], 95))
        rows.append(f)
    return rows


def _ks_weighted(syn, ref_by_arch, counts):
    """Two-sample KS between synthetic values and the real reference re-weighted to the synthetic archetype mix."""
    grid = np.unique(np.concatenate([syn] + [np.asarray(v) for v in ref_by_arch.values()]))
    F_syn = np.searchsorted(np.sort(syn), grid, side="right") / len(syn)
    tot = sum(counts.values())
    F_ref = sum(counts[a] / tot * np.searchsorted(np.sort(ref_by_arch[a]), grid, side="right") / len(ref_by_arch[a])
                for a in counts)
    d = float(np.max(np.abs(F_syn - F_ref)))
    m = min(len(v) for v in ref_by_arch.values())
    crit = 1.63 * np.sqrt(1 / len(syn) + 1 / m)          # alpha = 0.01
    return d, float(crit)


def run(check, g, inv, truth):
    if not FITTED:
        check("FIT", "fleet", "fitted_params.json present", False, "missing")
        return
    truth = truth.merge(inv[["resource_id", "env"]], on="resource_id", how="left")
    feats = _features(g, truth)
    active = [f for f in feats if f["mean"] >= 5]

    def med(rows, k):
        v = [r[k] for r in rows if r.get(k) is not None and np.isfinite(r[k])]
        return float(np.median(v)) if v else np.nan, len(v)

    usable = {a for a, v in FITTED["archetypes"].items() if v.get("usable")}
    checks = [
        ("ar1_phi_cpu", active, "phi", "CPU lag-1 autocorrelation (residual)"),
        ("mem_ar1_phi", active, "mem_phi", "memory lag-1 autocorrelation (residual)"),
        ("mem_coupling", feats, "mem_slope", "memory-on-CPU OLS slope"),
        ("mem_noise_sd_pct", feats, "mem_noise_sd", "memory residual sd (pct points)"),
        ("net_out_in_ratio", feats, "net_out_in", "net_out / net_in"),
        ("net_lognorm_sigma", active, "net_sigma", "network lognormal spread"),
        ("iops_lognorm_sigma", active, "iops_sigma", "disk IO lognormal spread"),
        ("archetypes.steady_low.drift_sd", [f for f in feats if f["archetype"] == "steady_low"], "drift_sd",
         "day-to-day drift sd, steady_low"),
        ("archetypes.bursty_daily.drift_sd", [f for f in feats if f["archetype"] == "bursty_daily"], "drift_sd",
         "day-to-day drift sd, bursty_daily"),
        ("archetypes.zombie.drift_sd", [f for f in feats if f["archetype"] == "zombie"], "drift_sd",
         "day-to-day drift sd, zombie"),
        ("weekend_factor_interactive", [f for f in feats if f["archetype"] == "right_sized_prod"], "weekend_factor",
         "weekend/weekday ratio (interactive VMs)"),
        ("archetypes.right_sized_prod.spikes_per_day", [f for f in feats if f["archetype"] == "right_sized_prod"],
         "spikes_per_day", "unscheduled spikes per day (p50 + 4 MAD), right-sized VMs"),
    ]
    for key, rows, stat, label in checks:
        if key.startswith("archetypes.") and key.split(".")[1] not in usable:
            v, n = med(rows, stat)
            check("INFO", key, f"{label}: archetype has < 30 real matches, not compared", True, f"{v:.3g} (n={n})")
            continue
        lo, hi, ref = _iqr(key)
        v, n = med(rows, stat)
        check("FIT", key, f"{label}: synthetic median in real IQR [{lo:.3g}, {hi:.3g}]",
              np.isfinite(v) and lo <= v <= hi, f"{v:.3g} (n={n}, real median {ref:.3g})")

    refs = FITTED["reference_p95_over_mean"]
    arch_ok = sorted(a for a, v in FITTED["archetypes"].items() if v.get("usable") and refs.get(a))
    sel = [f for f in feats if f["archetype"] in arch_ok]
    counts = {a: sum(1 for f in sel if f["archetype"] == a) for a in arch_ok}
    counts = {a: c for a, c in counts.items() if c}
    syn = np.array([f["p95"] / max(f["mean"], 0.5) for f in sel])
    d, crit = _ks_weighted(syn, {a: refs[a] for a in counts}, counts)
    check("FIT", "p95/mean", f"KS(synthetic, real re-weighted to mix {counts}) < {crit:.3f} (alpha 0.01)", d < crit,
          round(d, 3))

    cpu_cv, _ = med(feats, "cv")
    mem_cv, _ = med(feats, "mem_cv")
    cal = FITTED["calibration"]
    check("CAL", "fleet", "memory steadier than CPU (median CV), as in Alibaba "
          f"({cal['median_mem_cv']['alibaba']} vs {cal['median_cpu_cv']['alibaba']}) and Borg "
          f"({cal['median_mem_cv']['borg']} vs {cal['median_cpu_cv']['borg']})", mem_cv < cpu_cv,
          (round(mem_cv, 3), round(cpu_cv, 3)))

    # ------------------------------------------------ TRUTH: bulk VMs still match their expected verdicts
    for f in feats:
        a, prod = f["archetype"], f["env"] == "prod"
        P = f["p99"] if prod else f["p95"]
        memP = f["mem_p99"] if prod else f["mem_p95"]
        rule = {
            "right_sized_prod": (40 <= f["p99"] < 90, "40 <= p99 < 90 (not underused, not upsize)"),
            "steady_low": (P < 40 and memP < 50, "P < 40 and mem P < 50 (underused -> resize)"),
            "bursty_daily": (f["mean"] < 20 and f["p99"] >= 60, "mean < 20 and p99 >= 60 (looks idle, peaks)"),
            "batch_nightly": (f["mean"] < 20 and f["p99"] >= 60, "mean < 20 and p99 >= 60 (looks idle, peaks)"),
            "office_hours_dev": (f["weekend_p95"] < 5, "weekend p95 < 5 (schedulable)"),
            "zombie": (P < 5 and memP < 70, "P < 5 and mem P < 70 (idle)"),
            "memory_bound": (f["mem_p99"] > 70, "mem p99 > 70 (memory veto)"),
        }[a]
        check("TRUTH", a, rule[1], rule[0], (round(f["mean"], 1), round(f["p95"], 1), round(f["p99"], 1)))

    # ------------------------------------------------ PROV
    for k, e in FITTED.items():
        if isinstance(e, dict) and "value" in e:
            check("PROV", k, "has source, method and n_series", bool(e.get("source")) and bool(e.get("method"))
                  and e.get("n_series", 0) > 0, f"{e.get('source')} n={e.get('n_series')}")
    man = ROOT / "data" / "external" / "MANIFEST.json"
    if man.exists():
        mf = json.loads(man.read_text())
        same = all(FITTED["_provenance"].get(k, {}).get("sha256") == v["sha256"] for k, v in mf.items())
        check("PROV", "traces", "fitted_params provenance hashes == downloaded trace manifest", same, len(mf))
    else:
        check("PROV", "traces", "provenance hashes (skipped: data/external not downloaded in this clone)", True,
              "skipped")

    # ------------------------------------------------ INFO (composition-dependent, not pass/fail)
    rs, _ = med([f for f in feats if f["archetype"] == "right_sized_prod"], "drift_sd")
    check("INFO", "right_sized_prod", f"drift sd capped at 0.10 (real p50 "
          f"{FITTED['archetypes']['right_sized_prod']['drift_sd']['p50']}) to keep p99 < 90", True, round(rs, 3))
    share = float(np.mean([f["mean"] < 20 for f in feats]))
    check("INFO", "fleet", f"share mean CPU < 20%: real Azure {cal['share_mean_cpu_below_20']['azure']}, "
          f"Bitbrains {cal['share_mean_cpu_below_20']['bitbrains']} (depends on archetype mix)", True, round(share, 3))
    p95m, _ = med(feats, "p95")
    check("INFO", "fleet", f"median CPU p95: real Azure {cal['median_cpu_p95']['azure']}, Bitbrains "
          f"{cal['median_cpu_p95']['bitbrains']} (our fleet is deliberately busier)", True, round(p95m, 1))
