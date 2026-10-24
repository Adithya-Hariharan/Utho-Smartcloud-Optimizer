"""Engine scorecard: engine verdicts vs truth.csv, per archetype and per verdict class, plus the plan's headline
lines ('found X/Y idle VMs, 0 unsafe downsizes'). python -m engine.scorecard -> data/scorecard.json"""
import json

from . import backtest as BT
from . import data as D
from .disputes import DISPUTES, active

GROUPS = {"IDLE": "idle VMs stopped", "OFF_HOURS": "schedulable VMs scheduled",
          "ORPHAN_VOLUME": "orphaned volumes cleaned", "UNUSED_IP": "unused IPs released",
          "STOPPED_VM": "long-stopped resources cleaned", "VETO_RECURRING_PEAK": "recurring peaks protected",
          "UNDERUSED": "underused VMs resized", "UNDER_PROVISIONED": "saturated VMs upsized"}


def _group(row):
    if row["archetype"] != "planted":
        return row["archetype"]
    return "planted " + (row["edge_case_id"][:1] or "?")


def build(env, data, cfg, sel):
    truth = D.load_truth()
    by = {i["resource"]["resource_id"]: i for i in env["items"]}
    rows = []
    for t in truth.to_dict("records"):
        i = by[t["resource_id"]]
        rows.append({**t, "verdict": i["verdict"], "reason_code": i["reason_code"],
                     "ok": (i["verdict"], i["reason_code"]) == (t["expected_verdict"], t["expected_reason_code"])})
    per_group = {}
    for r in rows:
        g = per_group.setdefault(_group(r), {"rows": 0, "correct": 0})
        g["rows"] += 1
        g["correct"] += r["ok"]
    for g in per_group.values():
        g["recall"] = round(g["correct"] / g["rows"], 3)
    classes = sorted({r["expected_verdict"] for r in rows} | {r["verdict"] for r in rows})
    per_class = {}
    for c in classes:
        pred = [r for r in rows if r["verdict"] == c]
        true = [r for r in rows if r["expected_verdict"] == c]
        tp = sum(1 for r in pred if r["expected_verdict"] == c)
        per_class[c] = {"predicted": len(pred), "expected": len(true), "true_positive": tp,
                        "precision": round(tp / len(pred), 3) if pred else None,
                        "recall": round(tp / len(true), 3) if true else None}
    found = {}
    for code, label in GROUPS.items():
        exp = [r for r in rows if r["expected_reason_code"] == code]
        if exp:
            found[label] = f"{sum(r['reason_code'] == code for r in exp)}/{len(exp)}"
    bt = BT.run(data, cfg, sel)
    found["unsafe downsizes (held-out week)"] = f"{bt['unsafe']}/{bt['evaluated']}"
    misses = [{"name": r["name"], "expected": f"{r['expected_verdict']} / {r['expected_reason_code']}",
               "engine": f"{r['verdict']} / {r['reason_code']}", "disputed": r["name"] in DISPUTES and active()}
              for r in rows if not r["ok"]]
    return {"rows": len(rows), "correct": sum(r["ok"] for r in rows),
            "accuracy": round(sum(r["ok"] for r in rows) / len(rows), 4), "disputes_active": active(),
            "headline": found, "per_group": dict(sorted(per_group.items())), "per_verdict": per_class, "misses": misses}


def main():
    from .run import build as run_build, selection
    from .config import Config
    env, ctx, res, _ = run_build(with_alerts=False)
    sc = build(env, ctx.data, Config(), selection())
    (D.DATA / "scorecard.json").write_text(json.dumps(sc, indent=1), encoding="utf-8")
    print(f"{sc['correct']}/{sc['rows']}", sc["headline"])


if __name__ == "__main__":
    main()
