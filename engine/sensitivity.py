"""Sensitivity of every decision threshold: verdict flips and headline-saving change when ONE number moves
by -25%, -10%, +10%, +25% (everything else fixed, final selection). Feeds the numbers ledger.

python -m engine.sensitivity   ->  engine/sensitivity.json"""
import json
from pathlib import Path

from . import data as D
from . import pipeline as PL
from .config import Config, numeric_keys
from .run import selection

OUT = Path(__file__).resolve().parent / "sensitivity.json"
DECISION_SECTIONS = ("percentiles", "clean", "gates_data", "gates_policy", "peaks", "noncompute", "vetoes", "patterns",
                     "candidates", "sizing", "risk", "cost", "evidence")
SKIP = {"risk.seed"}


def headline(res):
    before = saving = 0
    for r in res:
        if r.cost:
            before += r.cost["options"]["none"]["monthly_inr_after"]
            if r.verdict == "recommend" and r.default_option:
                saving += r.cost["options"][r.default_option]["saving_inr"]
    return before, saving


def main():
    cfg = Config()
    data = D.load(cfg)
    sel = selection()
    _, base = PL.run(data, cfg, sel)
    base_v = {r.id: (r.verdict, r.reason_code) for r in base}
    b_before, b_saving = headline(base)
    s = cfg("score.sensitivity_small")
    L = cfg("score.sensitivity_large")
    factors = [1 - L, 1 - s, 1 + s, 1 + L]
    out = {"base_saving_inr": b_saving, "base_bill_inr": b_before, "factors": factors, "keys": {}}
    for key in numeric_keys():
        if key.split(".")[0] not in DECISION_SECTIONS or key in SKIP or not isinstance(cfg(key), (int, float)):
            continue
        row = {}
        for f in factors:
            v = cfg(key) * f
            if "percentile" in key:
                v = min(v, 100)
            _, res = PL.run(data, cfg.with_overrides({key: v}), sel)
            flips = sum(base_v[r.id] != (r.verdict, r.reason_code) for r in res)
            _, sav = headline(res)
            row[f"{f:.2f}"] = {"flips": flips, "saving_change_pct": round((sav - b_saving) / b_saving * 100, 1)}
            PL.purge_evidence(cfg)
        out["keys"][key] = row
        print(key, row)
    OUT.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
