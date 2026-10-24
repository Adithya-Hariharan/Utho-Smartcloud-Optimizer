"""Run every preset and record the cost/risk trade-off it buys. python -m engine.presets -> engine/presets_report.json
Expectation (tested): saving rises max_performance <= default <= balanced <= max_savings, and the two conservative
presets make no unsafe recommendation in the held-out week. Max savings is ALLOWED to be unsafe: that is its trade-off,
and the report says how unsafe."""
import json
from pathlib import Path

from . import backtest as BT
from . import data as D
from . import pipeline as PL
from .config import Config
from .run import selection

OUT = Path(__file__).resolve().parent / "presets_report.json"
ORDER = ["max_performance", "default", "balanced", "max_savings"]


def run_all():
    out = {}
    data = D.load(Config())
    sel = selection()
    for p in ORDER:
        cfg = Config(p)
        _, res = PL.run(data, cfg, sel)
        before = sum(r.cost["options"]["none"]["monthly_inr_after"] for r in res if r.cost)
        saving = sum(r.cost["options"][r.default_option]["saving_inr"] for r in res
                     if r.verdict == "recommend" and r.default_option)
        counts, risk = {}, {}
        for r in res:
            counts[r.verdict] = counts.get(r.verdict, 0) + 1
            if r.risk and r.verdict in ("recommend", "upsize"):
                risk[r.risk["level"]] = risk.get(r.risk["level"], 0) + 1
        bt = BT.run(data, cfg, sel)
        out[p] = {**cfg.preset, "saving_inr": saving, "bill_inr": before, "saving_pct": round(saving / before * 100, 1),
                  "verdicts": counts, "risk_levels": risk, "backtest_unsafe": bt["unsafe"],
                  "backtest_evaluated": bt["evaluated"], "unsafe_examples": [d["name"] for d in bt["details"]][:5]}
    return out


def main():
    out = run_all()
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for p, v in out.items():
        print(f"{p:16s} saving Rs {v['saving_inr']:>8,} ({v['saving_pct']}%)  unsafe {v['backtest_unsafe']}/{v['backtest_evaluated']}  risk {v['risk_levels']}")


if __name__ == "__main__":
    main()
