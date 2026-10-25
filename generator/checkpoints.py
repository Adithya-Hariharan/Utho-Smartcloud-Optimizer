"""Cumulative checkpoint verifier.

python -m generator.checkpoints --upto N
Runs verify_cp1 .. verify_cpN in order; stops at the first failing checkpoint (exit 1).
Every run is appended to data/external/checkpoint_log.json.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXTERNAL = DATA / "external"
FIT_DIR = ROOT / "generator" / "fit"
PARAMS = ROOT / "generator" / "fitted_params.json"


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(*args, **kw):
    return subprocess.run([sys.executable, "-m", *args], cwd=ROOT, capture_output=True, text=True, **kw)


# ------------------------------------------------------------------ CP1 acquire
def verify_cp1():
    import pyarrow as pa
    from .fit.download import SOURCES
    out = []
    mpath = EXTERNAL / "MANIFEST.json"
    out.append(("manifest exists", mpath.exists(), str(mpath.name)))
    if not mpath.exists():
        return out
    man = json.loads(mpath.read_text())
    for key in SOURCES:
        m = man.get(key)
        out.append((f"{key}: in manifest", m is not None, ""))
        if m is None:
            continue
        p = EXTERNAL / m["file"]
        out.append((f"{key}: size == HF API size", p.exists() and p.stat().st_size == m["expected_size"],
                    p.stat().st_size if p.exists() else "missing"))
        out.append((f"{key}: sha256 matches manifest", p.exists() and _sha(p) == m["sha256"], m["sha256"][:12]))
        try:
            with pa.memory_map(str(p)) as src:
                n = pa.ipc.open_stream(src).read_all().num_rows
            out.append((f"{key}: arrow readable", True, f"{n} items"))
            if key == "bitbrains_5T":
                out.append(("bitbrains_5T: 1,250 VMs", n == 1250, n))
        except Exception as e:  # noqa: BLE001
            out.append((f"{key}: arrow readable", False, repr(e)[:80]))
    return out


# ------------------------------------------------------------------ CP2 identify columns
REQUIRED_CHANNELS = {
    "bitbrains_5T": ["cpu_pct", "mem_kb", "net_rx_kbps", "net_tx_kbps", "disk_read_kbps", "disk_write_kbps"],
    "bitbrains_H": ["cpu_pct", "mem_kb"],
    "azure_2017": ["cpu_avg_pct", "cpu_min_pct", "cpu_max_pct"],
    "alibaba_2018": ["cpu_pct", "mem_pct"],
    "borg_2011": ["cpu_usage_norm", "mem_usage_norm"],
}
PCT = {"cpu_pct", "mem_pct", "cpu_avg_pct", "cpu_min_pct", "cpu_max_pct", "disk_io_pct"}


def verify_cp2():
    out = []
    p = FIT_DIR / "trace_schema.json"
    out.append(("trace_schema.json exists", p.exists(), ""))
    if not p.exists():
        return out
    sch = json.loads(p.read_text())
    for key, req in REQUIRED_CHANNELS.items():
        tr = sch.get(key)
        out.append((f"{key}: probed", tr is not None, ""))
        if tr is None:
            continue
        meanings = {v["meaning"]: (c, v) for c, v in tr["channels"].items()}
        for m in req:
            out.append((f"{key}: '{m}' identified with evidence", m in meanings and bool(meanings[m][1]["evidence"]),
                        meanings[m][0] if m in meanings else "missing"))
        for m, (c, v) in meanings.items():
            st = tr["stats"][c]
            if m in PCT:
                # raw Bitbrains CPU% legitimately exceeds 100 slightly (turbo); allow p99 <= 110, >=95% in [0,100]
                ok = st["min"] >= 0 and st["p99"] <= 110 and st["share_0_100"] >= (0.95 if key.startswith("bitbrains") else 0.99)
                out.append((f"{key}: {m} is a percentage", ok, f"p99 {st['p99']:.1f}, in[0,100] {st['share_0_100']:.3f}"))
            elif m.endswith("kbps") or m.endswith("_kb") or m.endswith("_norm") or m.startswith("net_") or m == "cpu_mhz":
                out.append((f"{key}: {m} non-negative", st["nonneg"] >= 0.99, round(st["nonneg"], 4)))
    return out


# ------------------------------------------------------------------ CP3 fitted parameters
REQUIRED_PARAMS = ["ar1_phi_cpu", "ar1_sigma_model", "drift_sd", "weekend_factor_interactive", "daily_amp_ratio",
                   "mem_ar1_phi", "mem_coupling", "net_out_in_ratio", "net_lognorm_sigma", "net_elasticity",
                   "iops_lognorm_sigma", "spike_rate_per_day", "missing_share_bitbrains", "archetypes", "calibration",
                   "reference_p95_over_mean", "_provenance"]
BOUNDS = {"ar1_phi_cpu": (0, 1), "mem_ar1_phi": (0, 1), "drift_sd": (0, 2), "weekend_factor_interactive": (0, 3),
          "daily_amp_ratio": (0, 10), "mem_coupling": (-1, 2), "net_out_in_ratio": (0, 20), "net_lognorm_sigma": (0, 5),
          "iops_lognorm_sigma": (0, 5), "spike_rate_per_day": (0, 288), "missing_share_bitbrains": (0, 1)}
CACHE = EXTERNAL / "cp_cache.json"


def _cache():
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def _fit_fingerprint():
    srcs = [ROOT / "generator" / "fit" / f for f in ("fit.py", "traces.py", "trace_schema.json")]
    h = hashlib.sha256()
    for s in srcs:
        h.update(s.read_bytes())
    h.update((EXTERNAL / "MANIFEST.json").read_bytes())
    return h.hexdigest()


def verify_cp3():
    out = []
    out.append(("fitted_params.json exists", PARAMS.exists(), ""))
    if not PARAMS.exists():
        return out
    P = json.loads(PARAMS.read_text())
    for k in REQUIRED_PARAMS:
        out.append((f"param '{k}' present", k in P, ""))
    for k, (lo, hi) in BOUNDS.items():
        v = P.get(k, {}).get("value", np.nan)
        out.append((f"{k} finite and within [{lo}, {hi}]", np.isfinite(v) and lo <= v <= hi, v))
    for k, v in P.items():
        if isinstance(v, dict) and "value" in v and "bitbrains" in v.get("source", ""):
            out.append((f"{k}: n_series >= 100 (primary source)", v.get("n_series", 0) >= 100, v.get("n_series")))
        if isinstance(v, dict) and "value" in v:
            out.append((f"{k}: has source + method", bool(v.get("source")) and bool(v.get("method")), ""))
    man = json.loads((EXTERNAL / "MANIFEST.json").read_text())
    out.append(("provenance hashes match manifest",
                all(P["_provenance"].get(k, {}).get("sha256") == m["sha256"] for k, m in man.items()), ""))
    # determinism: proven once per (code, inputs) fingerprint by re-running the fit into a temp file
    fp = _fit_fingerprint()
    cache = _cache()
    out_sha = _sha(PARAMS)
    if cache.get("cp3_fingerprint") == fp and cache.get("cp3_output_sha") == out_sha:
        out.append(("fit deterministic (proven for this code+input fingerprint)", True, fp[:12]))
    else:
        import os
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "fitted_params.json"
        r = _run("generator.fit.fit", env={**os.environ, "SCO_FIT_OUT": str(tmp)})
        same = r.returncode == 0 and tmp.exists() and _sha(tmp) == out_sha
        out.append(("fit deterministic (second run identical)", same, r.stderr[-200:] if r.returncode else ""))
        if same:
            cache.update({"cp3_fingerprint": fp, "cp3_output_sha": out_sha})
            CACHE.write_text(json.dumps(cache, indent=1))
    return out


# ------------------------------------------------------------------ CP4 generator wired, schemas unchanged
BASELINE = "1a92369"        # commit with the original dataset; output schemas must not change vs this
DATA_FILES = ["inventory.csv", "truth.csv", "pricing.csv", "faults.csv", "metrics.parquet", "volume_metrics.parquet",
              "billing_daily.parquet", "fixture/inventory.csv", "fixture/truth.csv", "fixture/pricing.csv",
              "fixture/metrics.parquet", "fixture/volume_metrics.parquet"]


def _schema_of(path_bytes, name):
    import io

    import pandas as pd
    import pyarrow.parquet as pq
    if name.endswith(".parquet"):
        sch = pq.read_schema(io.BytesIO(path_bytes))
        return [(f.name, str(f.type)) for f in sch]
    df = pd.read_csv(io.BytesIO(path_bytes), keep_default_na=False, nrows=5)
    return list(df.columns)


def _data_hash():
    h = hashlib.sha256()
    for f in DATA_FILES:
        h.update(_sha(DATA / f).encode())
    return h.hexdigest()


def verify_cp4():
    out = []
    import importlib

    from . import config, planted, signals
    importlib.reload(config)
    out.append(("config loads fitted_params.json", bool(config.FITTED), len(config.FITTED)))
    P = json.loads(PARAMS.read_text())
    out.append(("generator uses fitted phi outside pinned()", abs(signals._phi() - P["ar1_phi_cpu"]["value"]) < 1e-12,
                signals._phi()))
    with signals.pinned():
        out.append(("pinned() restores hand-set phi 0.8", signals._phi() == config.PINNED_PHI, signals._phi()))
    out.append(("generator uses fitted drift outside pinned()", abs(signals._drift_sd() - P["drift_sd"]["value"]) < 1e-12,
                signals._drift_sd()))
    inv_names = set()
    import pandas as pd
    inv_names = set(pd.read_csv(DATA / "inventory.csv", keep_default_na=False)["name"])
    for name, reason in planted.PINNED.items():
        out.append((f"pin '{name}' exists and has a reason", name in inv_names and len(reason) > 20, ""))
    # determinism: two builds, identical bytes
    r1 = _run("generator.build")
    h1 = _data_hash() if r1.returncode == 0 else "build1-failed"
    import os
    r2 = _run("generator.build", env={**os.environ, "PYTHONHASHSEED": "12345"})   # also rules out set/dict-order effects
    h2 = _data_hash() if r2.returncode == 0 else "build2-failed"
    out.append(("two builds byte-identical (second with a different PYTHONHASHSEED)", r1.returncode == 0 and h1 == h2,
                h1[:12]))
    # schemas vs baseline commit
    for f in DATA_FILES:
        g = subprocess.run(["git", "show", f"{BASELINE}:data/{f}"], cwd=ROOT, capture_output=True)
        if g.returncode != 0:
            out.append((f"schema {f}: baseline readable", False, g.stderr[:80]))
            continue
        same = _schema_of(g.stdout, f) == _schema_of((DATA / f).read_bytes(), f)
        out.append((f"schema {f} identical to {BASELINE}", same, ""))
    # original checks still pass
    v = _run("generator.validate")
    rep = (DATA / "validation_report.md").read_text(encoding="utf-8") if (DATA / "validation_report.md").exists() else ""
    base_rows = [l for l in rep.splitlines() if l.startswith("| ") and not l.startswith("| case")
                 and not any(l.startswith(f"| {k} ") for k in ("FIT", "TRUTH", "PROV", "INFO"))]
    fails = [l for l in base_rows if "**FAIL**" in l]
    out.append(("original validation checks all pass", len(base_rows) >= 72 and not fails,
                f"{len(base_rows) - len(fails)}/{len(base_rows)}"))
    return out


# ------------------------------------------------------------------ CP5 missing checks added and effective
def _report_rows(path):
    rep = path.read_text(encoding="utf-8") if path.exists() else ""
    return [l for l in rep.splitlines() if l.startswith("| ") and not l.startswith("| case")]


def verify_cp5():
    import os
    import shutil
    import tempfile
    out = []
    v = _run("generator.validate")
    rows = _report_rows(DATA / "validation_report.md")
    fails = [l for l in rows if "**FAIL**" in l]
    out.append(("validate: every check passes", v.returncode == 0 and not fails, f"{len(rows) - len(fails)}/{len(rows)}"))
    for k, need in (("FIT", 10), ("TRUTH", 50), ("PROV", 20), ("CAL", 1)):
        n = sum(1 for l in rows if l.startswith(f"| {k} "))
        out.append((f"report contains >= {need} {k} checks", n >= need, n))
    out.append(("no recalled-from-memory band left for missing share",
                any("within +/-20% of Bitbrains" in l for l in rows), ""))
    # negative test: a wrong phi must be caught
    tmp = Path(tempfile.mkdtemp())
    env = {**os.environ, "SCO_DATA_DIR": str(tmp), "SCO_PERTURB": "ar1_phi_cpu=0.1"}
    b = _run("generator.build", env=env)
    vv = _run("generator.validate", env=env)
    neg_rows = _report_rows(tmp / "validation_report.md")
    caught = any(l.startswith("| FIT | ar1_phi_cpu ") and "**FAIL**" in l for l in neg_rows)
    out.append(("negative test: perturbed phi=0.1 -> FIT ar1_phi_cpu FAILS", b.returncode == 0 and vv.returncode != 0 and caught,
                "caught" if caught else "NOT caught"))
    shutil.rmtree(tmp, ignore_errors=True)
    return out


# ------------------------------------------------------------------ CP6 docs match the data
def verify_cp6():
    out = []
    r = _run("generator.fit.report", "--check")
    out.append(("DATASET.md fitted block == regenerated from fitted_params.json + validation_report.md",
                r.returncode == 0, r.stdout.strip()))
    doc = (DATA / "DATASET.md").read_text(encoding="utf-8")
    out.append(("DATASET.md: no 'recalled from memory' left", "recalled from memory" not in doc, ""))
    return out


# ------------------------------------------------------------------ CP7 committed and pushed
def verify_cp7():
    out = []
    def git(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    out.append(("on branch b1_adi", git("rev-parse", "--abbrev-ref", "HEAD") == "b1_adi", ""))
    head = git("rev-parse", "HEAD")
    out.append(("HEAD is a new commit after the baseline", not head.startswith(BASELINE), head[:7]))
    dirty = [l for l in git("status", "--porcelain").splitlines() if l.strip()]
    out.append(("working tree clean (data/external ignored)", not dirty, dirty[:3]))
    remote = git("ls-remote", "--heads", "origin", "b1_adi").split("\t")[0]
    out.append(("origin/b1_adi == local HEAD", remote == head, remote[:7]))
    tracked = git("ls-files")
    out.append(("no external trace files committed", "data/external" not in tracked, ""))
    return out


CHECKPOINTS = [verify_cp1, verify_cp2, verify_cp3, verify_cp4, verify_cp5, verify_cp6, verify_cp7]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upto", type=int, required=True)
    upto = ap.parse_args().upto
    log_path = EXTERNAL / "checkpoint_log.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else []
    ok_all = True
    for i, fn in enumerate(CHECKPOINTS[:upto], 1):
        results = fn()
        ok = bool(results) and all(r[1] for r in results)
        print(f"\n=== CP{i} {'PASS' if ok else 'FAIL'}")
        for desc, good, val in results:
            print(f"  {'PASS' if good else 'FAIL'}  {desc}  {val}")
        log.append({"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "checkpoint": i,
                    "result": "PASS" if ok else "FAIL", "n_checks": len(results)})
        if not ok:
            ok_all = False
            break
    if upto > len(CHECKPOINTS):
        print(f"\nCP{len(CHECKPOINTS) + 1}..CP{upto} not implemented yet")
        ok_all = False
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=1))
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
