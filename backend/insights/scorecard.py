"""Engine Scorecard: the engine's output scored against truth.csv (plan section 0, feature 3).

Only this module reads truth.csv; the engine never does.
"""
import pandas as pd

from ..config_loader import REPO_ROOT

# truth.csv codes that the frozen §4.5 enum does not have -> what the engine emits (PLAN_final.md B10)
CONTRACT_MAP = {"BELOW_FLOOR": ("healthy", "RIGHT_SIZED"), "STOPPED_RECENTLY": ("healthy", "RIGHT_SIZED")}


def load_truth(path=REPO_ROOT / "data" / "truth.csv"):
    t = pd.read_csv(path, dtype=str, keep_default_na=False)
    return t[t["resource_id"] != "vm-9999"]


def expected(row):
    v, c = CONTRACT_MAP.get(row["expected_reason_code"], (row["expected_verdict"], row["expected_reason_code"]))
    return v, c, row["expected_action"]


def scorecard(items, truth=None):
    truth = load_truth() if truth is None else truth
    by_id = {i["resource"]["resource_id"]: i for i in items}
    rows = []
    for _, t in truth.iterrows():
        i = by_id[t["resource_id"]]
        v, c, a = expected(t)
        rows.append({"resource_id": t["resource_id"], "name": t["name"], "archetype": t["archetype"],
                     "edge_case_id": t["edge_case_id"], "expected": f"{v}/{c}/{a}",
                     "got": f"{i['verdict']}/{i['reason_code']}/{i['default_option']}",
                     "exp_verdict": v, "got_verdict": i["verdict"],
                     "ok": (i["verdict"], i["reason_code"], i["default_option"]) == (v, c, a)})
    df = pd.DataFrame(rows)
    verdicts = {}
    for v in sorted(set(df.exp_verdict) | set(df.got_verdict)):
        tp = int(((df.exp_verdict == v) & (df.got_verdict == v)).sum())
        pred, sup = int((df.got_verdict == v).sum()), int((df.exp_verdict == v).sum())
        verdicts[v] = {"support": sup, "predicted": pred, "precision": round(tp / pred, 3) if pred else None,
                       "recall": round(tp / sup, 3) if sup else None}
    unsafe = [i["resource"]["name"] for i in items
              if i["target"] and i["verdict"] == "recommend" and not (i["replay"] and i["replay"]["passed"])]
    idle_like = df[df.expected.str.contains("IDLE|ORPHAN_VOLUME|UNUSED_IP|STOPPED_VM")]
    return {
        "total": int(len(df)), "matched": int(df.ok.sum()), "accuracy": round(float(df.ok.mean()), 4),
        "unsafe_downsizes": len(unsafe), "unsafe_resources": unsafe,
        "waste_found": f"{int(idle_like.ok.sum())}/{len(idle_like)} idle, orphan and stopped resources found",
        "by_verdict": verdicts,
        "by_archetype": {a: {"n": int(len(g)), "matched": int(g.ok.sum())} for a, g in df.groupby("archetype")},
        "mismatches": df.loc[~df.ok, ["name", "edge_case_id", "expected", "got"]].to_dict("records"),
        "contract_mapped": [{"truth_code": k, "emitted": "/".join(v)} for k, v in CONTRACT_MAP.items()],
    }
