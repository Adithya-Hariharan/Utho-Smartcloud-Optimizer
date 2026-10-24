"""Engine Scorecard: the engine's default-preset output scored against truth.csv (plan section 0, feature 3).

Only this module reads truth.csv; the engine never does. Scoring rules follow the frontend reference
(docs/reference/mock_engine.py score / archetype_scores) so the Assumptions page reads the same numbers.
"""
import pandas as pd

from ..config_loader import REPO_ROOT

VERDICTS = ["recommend", "reject", "flag", "exclude", "healthy", "upsize"]
CLEANUP_CODES = {"IDLE", "ORPHAN_VOLUME", "UNUSED_IP", "STOPPED_VM"}


def load_truth(path=REPO_ROOT / "data" / "truth.csv"):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def scorecard(items, truth=None, preset="default"):
    truth = load_truth() if truth is None else truth
    rows = truth.to_dict("records")
    by_id = {i["resource"]["resource_id"]: i for i in items}
    correct, mismatches, arch, wrongly, found, expected = 0, [], {}, [], 0, 0
    for t in rows:
        r = by_id.get(t["resource_id"])
        ok = bool(r) and r["verdict"] == t["expected_verdict"] and r["reason_code"] == t["expected_reason_code"]
        correct += ok
        if not ok:
            mismatches.append({"name": t["name"], "expected": f"{t['expected_verdict']}/{t['expected_reason_code']}",
                               "got": f"{r['verdict']}/{r['reason_code']}" if r else "missing"})
        a = arch.setdefault(t["archetype"], {"archetype": t["archetype"], "total": 0, "correct": 0, "labels": set()})
        a["total"] += 1
        a["correct"] += ok
        a["labels"].add((t["expected_verdict"], t["expected_reason_code"]))
        if r and t["expected_verdict"] in ("reject", "flag", "exclude") and r["verdict"] == "recommend":
            wrongly.append(t["name"])
        if t["expected_reason_code"] in CLEANUP_CODES:
            expected += 1
            found += bool(r) and r["verdict"] == "recommend"
    by_verdict = []
    for v in VERDICTS:
        exp = sum(t["expected_verdict"] == v for t in rows)
        pred = sum(i["verdict"] == v for i in items)
        c = sum(t["expected_verdict"] == v and by_id.get(t["resource_id"], {}).get("verdict") == v for t in rows)
        by_verdict.append({"verdict": v, "expected": exp, "predicted": pred, "correct": c,
                           "precision": c / pred if pred else 1.0, "recall": c / exp if exp else 1.0})
    truth_label = {t["resource_id"]: (t["expected_verdict"], t["expected_reason_code"]) for t in rows}
    by_archetype = []
    for a in arch.values():
        fp = sum(1 for i in items if (i["verdict"], i["reason_code"]) in a["labels"]
                 and truth_label.get(i["resource"]["resource_id"]) not in a["labels"])
        by_archetype.append({"archetype": a["archetype"], "total": a["total"], "correct": a["correct"],
                             "precision": a["correct"] / (a["correct"] + fp) if a["correct"] + fp else 1.0,
                             "recall": a["correct"] / a["total"] if a["total"] else 1.0})
    unsafe = sum(1 for i in items if i["verdict"] == "recommend" and i["target"] and i["replay"]
                 and not i["replay"]["passed"])
    return {
        "preset": preset, "mock_engine": False,
        "total": len(rows), "correct": correct, "accuracy": correct / len(rows) if rows else 0.0,
        "by_verdict": by_verdict, "by_archetype": sorted(by_archetype, key=lambda x: -x["total"]),
        "unsafe_downsizes": unsafe + len(wrongly), "wrongly_shrunk": wrongly,
        "cleanup_recall": {"found": found, "expected": expected}, "mismatches": mismatches,
    }
