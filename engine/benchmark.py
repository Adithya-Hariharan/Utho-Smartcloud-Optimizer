"""Scale benchmark: replicate the fleet to >= benchmark.target_vms VMs (new ids, same workloads) and time the full
engine (clean -> evidence -> decisions -> alerts). Nothing is written to data/; results -> engine/benchmark.json.
python -m engine.benchmark"""
import json
import math
import os
import platform
import time
from pathlib import Path

import pandas as pd

from . import alerts as AL
from . import data as D
from . import pipeline as PL
from .config import Config
from .run import selection

OUT = Path(__file__).resolve().parent / "benchmark.json"


def replicate(base, k):
    """k copies of every resource with suffixed ids; attachments are remapped inside each copy."""
    inv = base.inventory
    frames, raw, vol = [], {}, {}
    for c in range(k):
        sfx = "" if c == 0 else f"-r{c}"
        x = inv.copy()
        x["resource_id"] = x["resource_id"] + sfx
        x["name"] = x["name"] + sfx
        x["attached_to"] = x["attached_to"].where(x["attached_to"] == "", x["attached_to"] + sfx)
        frames.append(x)
        for rid, df in base.raw.items():
            raw[rid + sfx] = df
        for rid, df in base.vol_raw.items():
            vol[rid + sfx] = df
    d = D.Data(pd.concat(frames, ignore_index=True), base.plans, base.plan_order, base.prices, raw, vol,
               base.window_start, base.now, base.n_days)
    d.axes = base.axes
    return d


def _rss_mb(cfg):
    try:
        import psutil
        return round(psutil.Process(os.getpid()).memory_info().rss / cfg.t("bytes_per_mb"))
    except ImportError:
        return None


def main():
    cfg = Config()
    base = D.load(cfg)
    n_vms = int((base.inventory["type"] == "vm").sum())
    k = math.ceil(cfg("benchmark.target_vms") / n_vms)
    t0 = time.perf_counter()
    data = replicate(base, k)
    t_rep = time.perf_counter() - t0
    PL._CLEAN_CACHE.clear()
    PL._EV_CACHE.clear()
    sel = selection()
    ctx = PL.Ctx(data, cfg, sel)
    t0 = time.perf_counter()
    PL._cleaned(ctx)
    t_clean = time.perf_counter() - t0
    t0 = time.perf_counter()
    ctx, res = PL.run(data, cfg, sel)
    t_run = time.perf_counter() - t0
    t0 = time.perf_counter()
    alerts = AL.resource_alerts(ctx, res)
    t_alerts = time.perf_counter() - t0
    vms = sum(1 for r in res if r.type == "vm")
    out = {"vms": vms, "resources": len(res), "copies": k, "metric_rows": int(sum(len(v) for v in data.raw.values())),
           "seconds": {"replicate": round(t_rep, 2), "clean": round(t_clean, 2),
                       "evidence_and_decisions": round(t_run, 2), "alerts": round(t_alerts, 2),
                       "total": round(t_clean + t_run + t_alerts, 2)},
           "ms_per_vm": round((t_clean + t_run + t_alerts) / vms * cfg.t("ms_per_second"), 1), "alerts": len(alerts),
           "rss_mb": _rss_mb(cfg), "machine": {"python": platform.python_version(), "processor": platform.processor(),
                                            "system": platform.system()},
           "note": "single process, no parallelism; per-VM work is independent, so it parallelises across processes"}
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
