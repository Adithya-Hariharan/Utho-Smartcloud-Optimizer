"""Engine orchestrator: one §4.5 recommendation per inventory row (plan sections 4.5, 7, 9).

The engine is pure: it reads the cleaned series, the features table, inventory and config, never truth.csv.
"""
import pandas as pd

from ..cost.model import current_cost, format_inr
from . import noncompute, present
from .common import Outcome, Trace, group_members
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
        return best[0], mem, f" (group {row['service_group']}, sized on {best[1]})"

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
        return Outcome("healthy", "BELOW_FLOOR",
                       f"Best change ({o.default}) saves only {format_inr(saving)}/month, under the "
                       f"{format_inr(self.t('saving_floor_inr'))} floor: not worth a human's attention.",
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

    def member_names(self, rid):
        """service_group members by name, including the resource itself (the UI groups when > 1)."""
        others = self.members.get(rid, [])
        if not others:
            return []
        return sorted(self.inv.loc[[rid] + others, "name"].tolist())

    def item(self, row, f, cur, o, flags, tr):
        rid = row["resource_id"]
        series = self.cleaned.series.get(rid)
        prod = self.is_prod(row)
        naive = None
        if o.verdict in ("reject", "flag"):
            if row["type"] == "vm" and series is not None and series.kind == "vm" and f.get("mean_cpu") is not None \
                    and row["plan_id"] in self.cfg.plans:
                naive, att = present.naive_vm(self, row, f, cur, series, prod)
                if att is not None and not (o.replay and o.replay.get("attempts")):
                    o.replay = {"limit_minutes_above_90": self.p.replay_limit(prod), "mem_cap_pct": self.p.mem_cap,
                                "attempts": [att], "passed": bool(att["passed"]), "chosen_plan": None}
            elif row["type"] == "volume" and f.get("metrics", {}).get("disk_used", {}).get("p50") is not None:
                naive = present.naive_volume(self, row, f)
        v = present.veto(self, o, row, f, naive) if o.verdict == "reject" else None
        reason = v["message"] if v else o.reason
        options = o.options or {"none": {"monthly_inr_after": cur["monthly_inr"], "saving_inr": 0,
                                         "formula": f"{format_inr(cur['monthly_inr'])}/month, no change"}}
        has_tel = series is not None and o.code not in METRICS_NULL
        return {
            "rec_id": f"REC-{rid}-{self.p.preset}",
            "resource": present.resource(row, self.member_names(rid)),
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
                         "percentile_used": self.p.pct_label(prod),
                         "metrics": present.metrics(f, has_tel),
                         "recurring_peak": present.recurring_peak(f) if row["type"] == "vm" else None,
                         "naive": naive},
            "replay": present.replay_block(o, row) if row["type"] == "vm" else None,
            "veto": v,
            "risk": o.risk if o.verdict in ("recommend", "upsize") else None,
            "reason": reason,
            "explanation_ai": None,
            "formula": options[o.default]["formula"],
            "trace": present.trace(tr, o.verdict),
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
        for rid in self.cleaned.strays:
            it = present.stray_item(rid, self.p.preset, int(self.cfg.raw["window"]["days"]),
                                    self.cleaned.stray_series.get(rid), self.p.pct_label(True))
            it["alert_ids"] = self.alert_ids.get(rid, [])
            items.append(it)
        return items, below


def run_engine(cfg, ds, cleaned, features, alerts=(), preset="default"):
    return Engine(cfg, ds, cleaned, features, alerts, preset).run()
