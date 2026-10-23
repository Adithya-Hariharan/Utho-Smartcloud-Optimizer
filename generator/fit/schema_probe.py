"""CP2: identify what each channel of each mirrored trace means, from evidence in the data.

python -m generator.fit.schema_probe   -> generator/fit/trace_schema.json

Each trace has a HYPOTHESIS (documented column order of the original trace) and a set of evidence
tests. A channel whose tests fail is written as "unknown" and is never used by the fitter.
"""
import json
from pathlib import Path

import numpy as np

from .traces import read_table

OUT = Path(__file__).resolve().parent / "trace_schema.json"
N_PROBE = 300


def _rows(key, n=N_PROBE):
    t = read_table(key)
    rng = np.random.default_rng(7)
    idx = np.sort(rng.choice(t.num_rows, min(n, t.num_rows), replace=False))
    out = []
    for i in idx:
        r = t.slice(int(i), 1).to_pylist()[0]
        tg = np.atleast_2d(np.asarray(r["target"], dtype=float))
        pf = r.get("past_feat_dynamic_real")
        pf = np.atleast_2d(np.asarray(pf, dtype=float)) if pf is not None else np.zeros((0, tg.shape[1]))
        out.append((r, tg, pf))
    return t, out


def _chan(rows, field, j):
    return [(tg if field == "target" else pf)[j] for _, tg, pf in rows]


def _stats(series):
    v = np.concatenate(series)
    v = v[np.isfinite(v)]
    within_cv = np.nanmedian([np.nanstd(s) / (abs(np.nanmean(s)) + 1e-9) for s in series])
    return {"min": float(v.min()), "p50": float(np.median(v)), "p99": float(np.percentile(v, 99)),
            "max": float(v.max()), "share_0_100": float(((v >= 0) & (v <= 100)).mean()),
            "share_0_1": float(((v >= 0) & (v <= 1)).mean()), "nonneg": float((v >= 0).mean()),
            "median_within_item_cv": float(within_cv), "nan_share": float(np.mean([np.isnan(s).mean() for s in series]))}


def _median_corr(a_series, b_series):
    cs = []
    for a, b in zip(a_series, b_series):
        m = np.isfinite(a) & np.isfinite(b)
        if m.sum() > 50 and np.std(a[m]) > 0 and np.std(b[m]) > 0:
            cs.append(np.corrcoef(a[m], b[m])[0, 1])
    return float(np.median(cs)) if cs else float("nan")


def _ratio_cv(a_series, b_series):
    cvs = []
    for a, b in zip(a_series, b_series):
        m = np.isfinite(a) & np.isfinite(b) & (b > 1)
        if m.sum() > 50:
            r = a[m] / b[m]
            cvs.append(np.std(r) / np.mean(r))
    return float(np.median(cvs)) if cvs else float("nan")


def probe_bitbrains(key):
    t, rows = _rows(key)
    tg0, tg1 = _chan(rows, "target", 0), _chan(rows, "target", 1)
    pf = [_chan(rows, "past", j) for j in range(5)]
    ch, stats = {}, {}
    for name, s in [("target[0]", tg0), ("target[1]", tg1)] + [(f"past_feat_dynamic_real[{j}]", pf[j]) for j in range(5)]:
        stats[name] = _stats(s)
    ratio_cv = _ratio_cv(tg0, tg1)
    if ratio_cv < 1e-3 and stats["target[0]"]["p99"] > 1000:
        ch["target[0]"] = {"meaning": "cpu_mhz", "unit": "MHz",
                           "evidence": f"target[0]/target[1] constant per VM (median CV {ratio_cv:.1e}) = CPU capacity"}
    if stats["target[1]"]["share_0_100"] >= 0.99 or stats["target[1]"]["p99"] <= 110:
        ch["target[1]"] = {"meaning": "cpu_pct", "unit": "%",
                           "evidence": f"p99 {stats['target[1]']['p99']:.1f}, {stats['target[1]']['share_0_100']:.3f} in [0,100]; "
                                       "proportional to MHz channel. Values slightly >100 exist in raw Bitbrains (clipped when fitting)"}
    s = stats["past_feat_dynamic_real[0]"]
    if s["p50"] > 1000 and s["median_within_item_cv"] > 0.01:
        ch["past_feat_dynamic_real[0]"] = {"meaning": "mem_kb", "unit": "KB",
                                           "evidence": f"KB-scale (p50 {s['p50']:.3g}), varies within VM (CV {s['median_within_item_cv']:.2f}) -> usage not provisioned"}
    pairs = {(a, b): _median_corr(pf[a], pf[b]) for a in range(1, 5) for b in range(a + 1, 5)}
    best = max(pairs, key=lambda k: pairs[k] if np.isfinite(pairs[k]) else -1)
    if best == (3, 4):
        names = {1: ("disk_read_kbps", "disk read"), 2: ("disk_write_kbps", "disk write"),
                 3: ("net_rx_kbps", "network received"), 4: ("net_tx_kbps", "network transmitted")}
        for j, (m, label) in names.items():
            ch[f"past_feat_dynamic_real[{j}]"] = {
                "meaning": m, "unit": "KB/s",
                "evidence": f"non-negative {stats[f'past_feat_dynamic_real[{j}]']['nonneg']:.3f}; original GWA-T-12 column order "
                            f"(mem usage, disk read, disk write, net rx, net tx); rx/tx are the most correlated pair "
                            f"(median r={pairs[(3, 4)]:.2f}) vs disk r/w {pairs[(1, 2)]:.2f}"}
    return {"items": t.num_rows, "freq": rows[0][0]["freq"], "start_example": str(rows[0][0]["start"]),
            "timestamps": "UTC; Bitbrains data centre local time = UTC+2 (CEST, Aug-Sep 2013)",
            "channels": ch, "stats": stats, "pair_corr_past": {f"{a}-{b}": v for (a, b), v in pairs.items()}}


def probe_generic(key, hypotheses):
    """hypotheses: {channel: (meaning, unit, test_name)} tests: pct100 | frac1 | nonneg | cpu_bounds"""
    t, rows = _rows(key)
    nt = rows[0][1].shape[0]
    npf = rows[0][2].shape[0]
    stats, ch = {}, {}
    series = {}
    for j in range(nt):
        series[f"target[{j}]"] = _chan(rows, "target", j)
    for j in range(npf):
        series[f"past_feat_dynamic_real[{j}]"] = _chan(rows, "past", j)
    for name, s in series.items():
        stats[name] = _stats(s)
    for name, (meaning, unit, test, why) in hypotheses.items():
        if name not in stats:
            continue
        s = stats[name]
        ok = {"pct100": s["share_0_100"] >= 0.99 and s["p99"] > 1.0,
              "frac1": s["share_0_1"] >= 0.99,
              "nonneg": s["nonneg"] >= 0.99}[test]
        extra = ""
        if meaning.startswith("cpu_min") or meaning.startswith("cpu_max"):
            base = series["target[0]"]
            other = series[name]
            rel = np.nanmedian([np.nanmean(o <= b + 1e-6) if "min" in meaning else np.nanmean(o >= b - 1e-6)
                                for o, b in zip(other, base)])
            ok = ok and rel >= 0.99
            extra = f"; {'<=' if 'min' in meaning else '>='} avg in {rel:.3f} of samples"
        if ok:
            ch[name] = {"meaning": meaning, "unit": unit,
                        "evidence": f"{test} test passed (p50 {s['p50']:.3g}, p99 {s['p99']:.3g}, "
                                    f"in[0,100] {s['share_0_100']:.3f}){extra}; {why}"}
    return {"items": t.num_rows, "freq": rows[0][0]["freq"], "start_example": str(rows[0][0]["start"]),
            "channels": ch, "stats": stats}


AZURE = {
    "target[0]": ("cpu_avg_pct", "%", "pct100", "CloudOps-TSF: target = average CPU utilisation"),
    "past_feat_dynamic_real[0]": ("cpu_min_pct", "%", "pct100", "covariate: min CPU in interval"),
    "past_feat_dynamic_real[1]": ("cpu_max_pct", "%", "pct100", "covariate: max CPU in interval"),
}
ALIBABA = {   # mirror holds container_usage (1,728 x 5-min = 6 days per container)
    "target[0]": ("cpu_pct", "% of container limit", "pct100", "container_usage.cpu_util_percent"),
    "target[1]": ("mem_pct", "% of container limit", "pct100", "container_usage.mem_util_percent"),
    "past_feat_dynamic_real[0]": ("cpi", "cycles/instr", "nonneg", "container_usage.cpi (typical 0.5-4)"),
    "past_feat_dynamic_real[3]": ("net_in", "normalised", "nonneg", "container_usage.net_in"),
    "past_feat_dynamic_real[4]": ("net_out", "normalised", "nonneg", "container_usage.net_out"),
    "past_feat_dynamic_real[5]": ("disk_io_pct", "%", "pct100", "container_usage.disk_io_percent"),
}
BORG = {
    "target[0]": ("cpu_usage_norm", "aggregated CPU rate, scale unknown (0-154)", "nonneg", "task usage: CPU rate; only scale-free stats (CV) are used"),
    "target[1]": ("mem_usage_norm", "fraction of largest machine", "nonneg", "task usage: canonical memory usage (normalised)"),
}


def main():
    out = {}
    for key in ("bitbrains_5T", "bitbrains_H"):
        out[key] = probe_bitbrains(key)
    out["azure_2017"] = probe_generic("azure_2017", AZURE)
    out["alibaba_2018"] = probe_generic("alibaba_2018", ALIBABA)
    t, rows = _rows("alibaba_2018")
    r34 = _median_corr(_chan(rows, "past", 3), _chan(rows, "past", 4))
    if r34 < 0.8:      # net_in / net_out must move together; otherwise do not trust the ordering
        for c in ("past_feat_dynamic_real[3]", "past_feat_dynamic_real[4]"):
            out["alibaba_2018"]["channels"].pop(c, None)
    else:
        for c in ("past_feat_dynamic_real[3]", "past_feat_dynamic_real[4]"):
            out["alibaba_2018"]["channels"][c]["evidence"] += f"; net_in/net_out median corr {r34:.3f}"
    out["alibaba_2018"]["note"] = ("container-level (not machine-level) usage; mem% is relative to the container "
                                   "limit (median ~96%), so only CPU-memory coupling and noise are used, not levels")
    out["borg_2011"] = probe_generic("borg_2011", BORG)
    OUT.write_text(json.dumps(out, indent=1))
    for k, v in out.items():
        print(k, v["items"], v["freq"], {c: d["meaning"] for c, d in v["channels"].items()})


if __name__ == "__main__":
    main()
