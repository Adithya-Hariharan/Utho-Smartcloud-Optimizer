"""Engine orchestrator: one §4.5 recommendation per inventory row (plan sections 4.5, 7, 9).

The engine is pure: it reads the cleaned series, the features table, inventory and config, never truth.csv.
"""
import pandas as pd

from ..cost.model import current_cost, format_inr
from . import noncompute
from .common import LEAF_KEYS, Outcome, Trace, group_members, resource_block
from .compute import evaluate_vm, flags_for
from .params import params_for
from .risk import risk, weekly_variation
from .sizing import catalogue

METRICS_NULL = {"NO_TELEMETRY", "HISTORY_TOO_SHORT"}


class Engine:
    def __init__(self, cfg, ds, cleaned, features, alerts=(), preset="default"):
        self.cfg, self.ds, self.cleaned, self.features = cfg, ds, cleaned, features
        self.p = params_for(cfg, preset)
        self.cat = catalogue(cfg)
        self.now = cfg.now
        self.inv = ds.inventory.set_index("resource_id")
        self.members = group_members(ds.inventory)
        self.alert_ids = {}
        for a in alerts:
            self.alert_ids.setdefault(a["resource_id"], []).append(a["alert_id"])

    # ---- helpers used by the step modules ---------------------------------------------------------
    def t(self, key):
        return self.cfg.get(f"thresholds.{key}")

    @staticmethod
    def is_prod(row):
        return row["env"] in ("prod", "")                  # untagged is treated as prod (safest)

    def day_label(self, d):
        return (self.cleaned.grid.start.normalize() + pd.Timedelta(days=int(d))).strftime("%Y-%m-%d")

    def target_block(self, plan, cur):
        return {"plan": plan.plan_id, "vcpu": plan.vcpu, "ram_gb": plan.ram_gb, "disk_gb": cur["disk_gb"],
                "compute_inr": plan.price, "storage_inr": cur["storage_inr"], "ip_inr": cur["ip_inr"],
                "monthly_inr": plan.price + cur["storage_inr"] + cur["ip_inr"]}

    def group_percentiles(self, row, key, cpu_p, mem_p):
        """service_group: size on the busiest member, same target for all."""
        others = self.members.get(row["resource_id"], [])
        if not others:
            return cpu_p, mem_p, ""
        best = (cpu_p, row["name"])
        mem = mem_p
        for rid in others:
            m = self.features[rid]["metrics"]
            if m["cpu"][key] is not None and m["cpu"][key] > best[0]:
                best = (m["cpu"][key], self.inv.loc[rid, "name"])
            if m["mem"][key] is not None:
                mem = max(mem, m["mem"][key])
        return best[0], mem, f" (group {row['service_group']}, busiest member {best[1]})"

    def risk(self, row, f, projected_p99, action_types):
        env = row["env"] or "prod"
        m = f["metrics"]["cpu"]
        s = self.cleaned.series.get(row["resource_id"])
        wv = weekly_variation(s.values["cpu_pct"]) if s is not None and s.kind == "vm" else None
        return risk(env, "stateful" in row["tags_list"], projected_p99, m["p99"], m["p50"], action_types,
                    f["coverage"], wv, self.t("confidence_week_variation"))

    def floor(self, o, cur, tr):
        saving = o.options[o.default]["saving_inr"]
        if tr.add("step9.floor", "saving ≥ ₹500/month", saving, self.t("saving_floor_inr"),
                  "pass" if saving >= self.t("saving_floor_inr") else "below_floor", terminal=True) == "pass":
            return o
        return Outcome("healthy", "RIGHT_SIZED",
                       f"Best option ({o.default}) would save only {format_inr(saving)}/month, below the "
                       f"{format_inr(self.t('saving_floor_inr'))} floor: counted in 'below floor', not listed.",
                       below_floor_saving=int(saving))

    # ---- one resource ----------------------------------------------------------------------------
    def evaluate(self, rid):
        row = self.inv.loc[rid].copy()
        row["resource_id"] = rid
        f = self.features[rid]
        cur = current_cost(row, self.cfg)
        tr = Trace()
        tr.add("inventory.type", "resource type", row["type"], None, "info")
        flags = []
        if row["type"] == "volume":
            o = noncompute.volume(self, rid, row, f, cur, tr)
        elif row["type"] == "ip":
            o = noncompute.ip(self, rid, row, cur, tr)
        elif row["state"] == "stopped":
            o = noncompute.stopped_vm(self, rid, row, cur, tr)
        else:
            flags = flags_for(row, f["coverage"], self.t("min_coverage"))
            o = evaluate_vm(self, rid, row, f, cur, tr)
        if o.verdict in ("recommend", "upsize") and o.risk is None:
            o.risk = self._noncompute_risk(row, f, o)
        return self.item(row, f, cur, o, flags + o.flags, tr), o

    def _noncompute_risk(self, row, f, o):
        types = [a["type"] for a in o.actions]
        env = row["env"] or "prod"
        r = risk(env, False, None, None, None, types, 1.0, 0.0, self.t("confidence_week_variation"))
        r["confidence_basis"] = "decided from inventory state (attachment, age)"
        return r

    def item(self, row, f, cur, o, flags, tr):
        rid = row["resource_id"]
        is_vm_eval = row["type"] == "vm" and row["state"] == "running"
        metrics = None if o.code in METRICS_NULL else {
            k: {q: m[q] for q in LEAF_KEYS + ("p90", "p99_5") if q in m} for k, m in f["metrics"].items()}
        options = o.options or {"none": {"monthly_inr_after": cur["monthly_inr"], "saving_inr": 0,
                                         "formula": f"{format_inr(cur['monthly_inr'])}/month, no change"}}
        return {
            "rec_id": f"REC-{rid}-{self.p.preset}",
            "resource": resource_block(row, self.members.get(rid, [])),
            "verdict": o.verdict,
            "reason_code": o.code,
            "actions": o.actions,
            "default_option": o.default,
            "flags": flags,
            "current": cur,
            "target": o.target,
            "schedule": o.schedule,
            "options": options,
            "evidence": {"window_days": int(self.cfg.raw["window"]["days"]), "days_of_data": f["days_of_data"],
                         "coverage": f["coverage"], "peak_window_coverage": f["peak_window_coverage"],
                         "percentile_used": self.p.pct(self.is_prod(row)) if is_vm_eval else None,
                         "metrics": metrics, "recurring_peak": o.recurring,
                         "naive": o.naive if o.verdict == "reject" else None},
            "replay": o.replay,
            "veto": o.veto if o.verdict == "reject" else None,
            "risk": o.risk if o.verdict in ("recommend", "upsize") else None,
            "reason": o.reason,
            "explanation_ai": None,
            "formula": options[o.default]["formula"],
            "trace": list(tr),
            "alert_ids": self.alert_ids.get(rid, []),
        }

    def run(self):
        items, below = [], {"count": 0, "monthly_inr": 0}
        for rid in self.inv.index:
            item, o = self.evaluate(rid)
            if o.below_floor_saving is not None:
                below["count"] += 1
                below["monthly_inr"] += o.below_floor_saving
            items.append(item)
        return items, below


def run_engine(cfg, ds, cleaned, features, alerts=(), preset="default"):
    return Engine(cfg, ds, cleaned, features, alerts, preset).run()
