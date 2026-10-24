"""4-part confidence score (0-10) for one candidate logic of one component, everything else held fixed.

correctness  (0..w_correct)  agreement with truth.csv on the rows this component decides (Jaccard over
                             truth-owned U predicted-owned rows, so false positives also cost); risk uses
                             out-of-sample AUC, cost uses accounting invariants
safety       (0..w_safety)   backtest unsafe recommendations: 0 -> full, 1 -> safety_one_unsafe, more -> 0
explain      (0..w_explain)  share of this component's fired findings visible in the output with value,
                             threshold and result: >= 99% -> full, >= 50% -> half, else 0
robustness   (0..w_robust)   verdict flip rate when the component's thresholds move +/- perturb:
                             < flip_good -> full, < flip_ok -> half, else 0"""
import numpy as np

from common.stats import auc as _auc
from . import backtest as BT
from . import pipeline as PL
from .data import load_truth

OWN = {
    "gates_data": {"HISTORY_TOO_SHORT", "RECENTLY_RESIZED", "LOW_COVERAGE", "ACTIVE_ANOMALY", "PEAK_UNDER_OBSERVED"},
    "gates_policy": {"NOT_IN_INVENTORY", "UNKNOWN_PRICE", "NO_TELEMETRY", "TAG_DR_STANDBY", "TAG_AUTOSCALED",
                     "TAG_SEASONAL", "TAG_ALLOWLISTED_IP", "POLICY_NEVER", "STATEFUL_PROD", "STOPPED_RECENTLY"},
    "noncompute": {"STOPPED_VM", "ORPHAN_VOLUME", "ORPHAN_TOO_NEW", "IDLE_VOLUME_REVIEW", "OVERSIZED_VOLUME", "UNUSED_IP"},
    "peaks": {"VETO_RECURRING_PEAK"},
    "vetoes": {"VETO_LEAK", "VETO_MEMORY", "VETO_IOPS", "VETO_NETWORK"},
    "patterns": {"ONE_OFF_PEAK", "WENT_QUIET", "RESERVED_MEMORY"},
    "candidates": {"IDLE", "IDLE_PROD", "OFF_HOURS"},
    "sizing": {"UNDERUSED", "PEAK_REPLAY_FAILED", "NO_CHEAPER_PLAN", "UNDER_PROVISIONED"},
}


class Scorer:
    def __init__(self, data, cfg):
        self.data, self.cfg = data, cfg
        self.truth = load_truth().set_index("resource_id")
        self.cache = {}

    # ------------------------------------------------------------------ helpers
    def run(self, sel, cfg=None):
        return PL.run(self.data, cfg or self.cfg, sel)

    def outcomes(self, sel):
        key = tuple(sorted(sel.items()))
        if key not in self.cache:
            self.cache[key] = self.run(sel)[1]
        return self.cache[key]

    def contested(self, comp, sel):
        """Rows on which the candidates of `comp` disagree. Scoring every candidate on these too means a
        component is judged on everything it changes, not only on the reason codes it emits."""
        outs = [{r.id: (r.verdict, r.reason_code) for r in self.outcomes(dict(sel, **{comp: c}))}
                for c in PL.COMPONENTS[comp].CANDIDATES]
        return frozenset(rid for rid in outs[0] if len({o[rid] for o in outs}) > 1)

    def _rows(self, comp, res, contested=frozenset()):
        t = self.truth
        if comp in ("clean", "assemble"):
            return list(res)
        if comp == "noncompute":
            own = OWN["noncompute"]
            return [r for r in res if r.type in ("volume", "ip") or t.loc[r.id, "expected_reason_code"] in own
                    or r.reason_code in own or r.id in contested]
        own = OWN[comp]
        return [r for r in res if t.loc[r.id, "expected_reason_code"] in own or r.reason_code in own
                or r.id in contested]

    def _match(self, r):
        t = self.truth.loc[r.id]
        return r.verdict == t["expected_verdict"] and r.reason_code == t["expected_reason_code"]

    # ------------------------------------------------------------------ parts
    def correctness(self, comp, sel, res, contested=frozenset()):
        if comp == "risk":
            auc = self.risk_auc(sel)
            ch = self.cfg("score.auc_chance")
            return max(0, (auc - ch) / (1 - ch)), {"auc": round(auc, 3)}
        if comp == "cost":
            return self.cost_invariants(res)
        rows = self._rows(comp, res, contested)
        ok = sum(self._match(r) for r in rows)
        bulk = [r for r in rows if self.truth.loc[r.id, "archetype"] != "planted"]
        detail = {"rows": len(rows), "correct": ok, "contested_rows": len(contested), "bulk_rows": len(bulk), "bulk_correct": sum(self._match(r) for r in bulk),
                  "misses": [self.truth.loc[r.id, "name"] for r in rows if not self._match(r)]}
        return (ok / len(rows) if rows else 1.0), detail

    def cost_invariants(self, res):
        n = ok = 0
        bad = []
        for r in res:
            if not r.cost or len(r.cost["options"]) <= 1:
                continue
            n += 1
            o = r.cost["options"]
            cur = o["none"]["monthly_inr_after"]
            good = all(v["monthly_inr_after"] >= 0 for v in o.values())
            singles = {k: v["monthly_inr_after"] for k, v in o.items() if "+" not in k.replace("snapshot+", "")}
            for k, v in o.items():
                parts = [p for p in k.replace("snapshot+", "snapshot_").split("+")]
                if len(parts) > 1:
                    good &= all(v["monthly_inr_after"] <= singles.get(p.replace("snapshot_", "snapshot+"), cur) + 1 for p in parts)
                good &= v["saving_inr"] <= cur
            ok += good
            if not good:
                bad.append(self.truth.loc[r.id, "name"])
        floor_rows = [r for r in res if self.truth.loc[r.id, "expected_reason_code"] == "BELOW_FLOOR" or r.reason_code == "BELOW_FLOOR"]
        fok = sum(self._match(r) for r in floor_rows)
        total = (ok + fok) / max(n + len(floor_rows), 1)
        return total, {"resources_with_options": n, "invariants_ok": ok, "violations": bad,
                       "floor_rows": len(floor_rows), "floor_ok": fok}

    def safety(self, sel):
        bt = BT.run(self.data, self.cfg, sel)
        w = self.cfg("score.w_safety")
        pts = w if bt["unsafe"] == 0 else (self.cfg("score.safety_one_unsafe") if bt["unsafe"] == 1 else 0)
        return pts, {"unsafe": bt["unsafe"], "evaluated": bt["evaluated"], "details": bt["details"]}

    def explainability(self, comp, res):
        w = self.cfg("score.w_explain")
        if comp == "risk":
            recs = [r for r in res if r.risk]
            good = sum(1 for r in recs if r.risk["points"] or r.risk["probability"] is not None)
            share = good / len(recs) if recs else 1.0
        elif comp == "cost":
            opts = [o for r in res if r.cost for o in r.cost["options"].values()]
            share = sum(1 for o in opts if o.get("formula")) / len(opts) if opts else 1.0
        else:
            fired = shown = 0
            for r in res:
                vis = {id(f) for f in (r.shown or [])}
                for f in r.findings:
                    if f["comp"] == comp and (f["kind"] != "info" or comp == "clean"):
                        fired += 1
                        if id(f) in vis and f.get("threshold") is not None and f.get("result"):
                            shown += 1
            share = shown / fired if fired else 1.0
        cfg = self.cfg
        pts = w if share >= cfg("score.explain_full") else (w * cfg("score.partial") if share >= cfg("score.explain_half") else 0)
        return pts, {"visible_share": round(share, 3)}

    def robustness(self, comp, sel, res):
        w = self.cfg("score.w_robust")
        if comp == "assemble":
            return w, {"flip_rate": 0.0, "note": "no thresholds"}
        base = {r.id: (r.verdict, r.reason_code, (r.risk or {}).get("level")) for r in res}
        rates = []
        for f in (1 - self.cfg("score.perturb"), 1 + self.cfg("score.perturb")):
            _, res2 = self.run(sel, self.cfg.perturbed(comp, f))
            flips = sum(base[r.id] != (r.verdict, r.reason_code, (r.risk or {}).get("level")) for r in res2)
            rates.append(flips / len(res2))
        PL.purge_evidence(self.cfg)
        rate = float(np.mean(rates))
        pts = w if rate < self.cfg("score.flip_good") else (w * self.cfg("score.partial") if rate < self.cfg("score.flip_ok") else 0)
        return pts, {"flip_rate": round(rate, 4)}

    # ------------------------------------------------------------------ risk AUC (out of sample)
    def risk_auc(self, sel):
        """Rank aggressive 1- and 2-step downsizes by predicted risk (decided on the first `split` days)
        and check the ranking against what actually happened on the held-out days."""
        from .components import risk as RK
        from .replay import budget_minutes, replay
        cfg, data = self.cfg, self.data
        split = int(cfg("backtest.split_day"))
        ctx, res = PL.run(data, cfg, sel, window_days=split)
        _, cleaned = PL._cleaned(ctx)
        fn = PL.COMPONENTS["risk"].CANDIDATES[sel["risk"]]["fn"]
        scores, labels = [], []
        spd = cfg.t("slots_per_day")
        for r in res:
            if r.type != "vm" or r.arr is None or r.inv is None or r.inv["plan_id"] not in data.plans \
                    or any(f["kind"] == "exclude" for f in r.findings):
                continue
            order = data.plan_order
            i = order.index(r.inv["plan_id"])
            test = cleaned[r.id][0]["cpu_pct"][split * spd:]
            for step in cfg("score.auc_steps"):
                if i - step < 0:
                    continue
                tgt = order[i - step]
                saved = (r.actions, r.sizing, r.risk)
                r.actions = {"resize": {"target": tgt}}
                r.sizing = {"kind": "resize", "target": tgt, "replay": replay(ctx, r, tgt)}
                fn(ctx, r)
                s = r.risk["probability"] if r.risk["probability"] is not None else r.risk["score"]
                cur, t = data.plans[r.inv["plan_id"]], data.plans[tgt]
                over = np.nansum(test * cur["vcpu"] / t["vcpu"] > cfg("sizing.overload_level")) * cfg.t("slot_minutes")
                labels.append(over > budget_minutes(r, cfg, data.n_days - split))
                scores.append(float(s))
                r.actions, r.sizing, r.risk = saved
        return _auc(np.array(scores), np.array(labels))

    # ------------------------------------------------------------------ total
    def score(self, comp, cand, sel):
        contested = self.contested(comp, sel) if comp not in ("risk", "cost") else frozenset()
        sel = dict(sel, **{comp: cand})
        key = ("score", comp, tuple(sorted(sel.items())))
        if key in self.cache:
            return self.cache[key]
        res = self.outcomes(sel)
        c, cd = self.correctness(comp, sel, res, contested)
        s, sd = self.safety(sel)
        e, ed = self.explainability(comp, res)
        rb, rd = self.robustness(comp, sel, res)
        total = c * self.cfg("score.w_correct") + s + e + rb
        out = {"candidate": cand, "total": round(total, 3), "correctness": round(c * self.cfg("score.w_correct"), 3),
               "safety": s, "explainability": e, "robustness": rb,
               "evidence": {"correctness": cd, "safety": {k: v for k, v in sd.items() if k != "details"},
                            "unsafe_details": sd["details"], "explainability": ed, "robustness": rd},
               "params": PL.COMPONENTS[comp].CANDIDATES[cand]["params"],
               "prior": PL.COMPONENTS[comp].CANDIDATES[cand]["prior"],
               "desc": PL.COMPONENTS[comp].CANDIDATES[cand]["desc"],
               "verdicts": {r.id: (r.verdict, r.reason_code) for r in res}}
        self.cache[key] = out
        return out
