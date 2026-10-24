"""Checkpointed logic selection with dependency re-loops (coordinate ascent).

python -m engine.select --upto K

At checkpoint k (component ORDER[k-1]):
  1. score every candidate of k with the current choices for all other components; keep the best
     (ties -> fewer parameters)
  2. for every earlier component j < k: dependence test = does switching k to its runner-up change any
     verdict on the rows j decides? If yes, re-score j's candidates; switch j if a candidate beats the
     current one by >= switch_margin, then re-score k. Repeat up to max_passes.
Components after k keep their prior favourite (highest prior) until their own checkpoint.
Writes engine/selection.json (current choice) and engine/selection_log.json (every score + evidence)."""
import argparse
import json
from pathlib import Path

from . import data as D
from . import pipeline as PL
from .config import Config
from .score import Scorer

HERE = Path(__file__).resolve().parent
SEL, LOG = HERE / "selection.json", HERE / "selection_log.json"


def prior_selection():
    return {k: max(m.CANDIDATES, key=lambda c: (m.CANDIDATES[c]["prior"], -m.CANDIDATES[c]["params"]))
            for k, m in PL.COMPONENTS.items()}


def best(scores):
    return max(scores, key=lambda s: (s["total"], -s["params"]))


def _strip(s):
    return {k: v for k, v in s.items() if k != "verdicts"}


def score_all(sc, comp, sel):
    return [sc.score(comp, c, sel) for c in PL.COMPONENTS[comp].CANDIDATES]


def dependent(sc, j, k, sel, scores_k):
    """Does component j's decided rows change when k switches to its runner-up?"""
    ranked = sorted(scores_k, key=lambda s: (-s["total"], s["params"]))
    if len(ranked) == 1:
        return False, []
    a, b = ranked[0], ranked[1]
    _, res = sc.run(dict(sel, **{k: a["candidate"]}))
    rows = {r.id for r in sc._rows(j, res)} if j not in ("risk", "cost") else {r.id for r in res if r.actions}
    changed = [rid for rid in rows if a["verdicts"].get(rid) != b["verdicts"].get(rid)]
    return bool(changed), changed


def run_checkpoint(sc, cfg, k, sel, log):
    comp = PL.ORDER[k - 1]
    entry = {"checkpoint": k, "component": comp, "passes": []}
    scores = score_all(sc, comp, sel)
    sel[comp] = best(scores)["candidate"]
    entry["initial"] = [_strip(s) for s in scores]
    for p in range(int(cfg("score.max_passes"))):
        changed_any = False
        pass_log = {"pass": p + 1, "dependence": []}
        for j in PL.ORDER[:k - 1]:
            dep, rows = dependent(sc, j, comp, sel, scores)
            item = {"earlier": j, "depends_on_current": dep, "rows_changed": [sc.truth.loc[r, "name"] for r in rows][:12]}
            if dep:
                sj = score_all(sc, j, sel)
                cur = next(s for s in sj if s["candidate"] == sel[j])
                bj = best(sj)
                item["rescored"] = [{"candidate": s["candidate"], "total": s["total"]} for s in sj]
                if bj["candidate"] != sel[j] and bj["total"] >= cur["total"] + cfg("score.switch_margin"):
                    item["switched"] = {"from": sel[j], "to": bj["candidate"]}
                    sel[j] = bj["candidate"]
                    changed_any = True
            pass_log["dependence"].append(item)
        if changed_any:
            scores = score_all(sc, comp, sel)
            sel[comp] = best(scores)["candidate"]
            pass_log["rescored_current"] = [_strip(s) for s in scores]
        entry["passes"].append(pass_log)
        if not changed_any:
            break
    final = next(s for s in scores if s["candidate"] == sel[comp])
    entry["selected"] = sel[comp]
    entry["selected_total"] = final["total"]
    entry["accepted"] = final["total"] >= cfg("score.accept_min")
    entry["selection_after"] = dict(sel)
    log = [e for e in log if e["checkpoint"] != k] + [entry]
    return sel, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upto", type=int, required=True)
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    cfg = Config()
    data = D.load(cfg)
    sc = Scorer(data, cfg)
    sel = prior_selection() if a.fresh or not SEL.exists() else json.loads(SEL.read_text())
    log = [] if a.fresh or not LOG.exists() else json.loads(LOG.read_text())
    done = {e["checkpoint"] for e in log}
    for k in range(1, a.upto + 1):
        if k in done and not a.fresh:
            continue
        sel, log = run_checkpoint(sc, cfg, k, sel, log)
        e = log[-1]
        print(f"CP{k} {e['component']:<13} -> {e['selected']:<20} total {e['selected_total']:.2f} "
              f"{'ACCEPTED' if e['accepted'] else 'BELOW 7'} | " +
              ", ".join(f"{s['candidate']} {s['total']:.2f}" for s in e["initial"]) +
              "".join(f" | re-loop: {i['earlier']} {i['switched']}" for p in e["passes"] for i in p["dependence"] if "switched" in i))
        SEL.write_text(json.dumps(sel, indent=1, sort_keys=True))
        LOG.write_text(json.dumps(sorted(log, key=lambda e: e["checkpoint"]), indent=1, default=str))


if __name__ == "__main__":
    main()
