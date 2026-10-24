"""Cumulative engine checkpoints: python -m engine.checkpoints --upto K  (re-verifies 1..K every time).

Each checkpoint verifies (1) the selection record for that component (selected, scored >= accept_min,
consistent with selection.json, score reproducible) and (2) concrete behaviour on named resources."""
import argparse
import json
import sys

from . import backtest as BT
from . import data as D
from . import output
from . import pipeline as PL
from .config import Config
from .score import Scorer
from .select import LOG, SEL

SCHEMA_KEYS = ["rec_id", "resource", "verdict", "reason_code", "actions", "default_option", "flags", "current", "target",
               "schedule", "options", "evidence", "replay", "veto", "risk", "reason", "explanation_ai", "formula",
               "trace", "alert_ids"]


class State:
    def __init__(self):
        self.cfg = Config()
        self.data = D.load(self.cfg)
        self.sel = json.loads(SEL.read_text())
        self.log = {e["checkpoint"]: e for e in json.loads(LOG.read_text())}
        self.ctx, self.res = PL.run(self.data, self.cfg, self.sel)
        self.by = {(r.inv or {}).get("name", r.id): r for r in self.res}
        self.by_id_name = {r.id: (r.inv or {}).get("name", r.id) for r in self.res}
        self.scorer = Scorer(self.data, self.cfg)

    def code(self, name):
        return self.by[name].reason_code


def _selection_checks(st, k):
    comp = PL.ORDER[k - 1]
    e = st.log.get(k)
    out = [(f"CP{k} selection logged for '{comp}'", e is not None, "")]
    if e is None:
        return out
    out.append((f"selected logic scored >= {st.cfg('score.accept_min')}", e["accepted"], e["selected_total"]))
    final = st.sel[comp]
    switched_later = [p for later in st.log.values() if later["checkpoint"] > k for p in later["passes"]
                      for i in p["dependence"] if i.get("switched") and i["earlier"] == comp]
    out.append(("selection.json agrees with the log (or a later re-loop switched it)",
                final == e["selected"] or bool(switched_later), final))
    s = st.scorer.score(comp, final, st.sel)
    out.append(("score reproducible from scratch (>= accept_min with the final selection)",
                s["total"] >= st.cfg("score.accept_min"), s["total"]))
    return out


def _expect(st, pairs):
    return [(f"{n} -> {c}", st.code(n) == c, st.code(n)) for n, c in pairs]


def cp1(st):
    r = st.by["prod-api-02"]
    import numpy as np
    nan = ~np.isfinite(r.arr["cpu_pct"])
    run = max((len(x) for x in "".join("1" if v else "0" for v in nan).split("0")), default=0)
    out = [("6-hour gap kept as NaN (prod-api-02)", run >= 72, run),
           ("duplicates dropped (dev-web-03)", st.by["dev-web-03"].dq["duplicates_dropped"] >= 10,
            st.by["dev-web-03"].dq["duplicates_dropped"]),
           ("impossible values masked (fleet)", sum(r.dq["out_of_range"] for r in st.res if r.dq) > 0, ""),
           ("rate-limited plateau not masked (staging-api-09 p95 == 40)", st.by["staging-api-09"].ev["p95"] == 40.0,
            st.by["staging-api-09"].ev["p95"])]
    return out


def cp2(st):
    out = _expect(st, [("dev-test-12", "HISTORY_TOO_SHORT"), ("staging-app-05", "RECENTLY_RESIZED"),
                       ("dev-flaky-18", "LOW_COVERAGE"), ("prod-worker-05", "ACTIVE_ANOMALY"),
                       ("dev-sandbox-17", "ACTIVE_ANOMALY"), ("prod-batch-20", "PEAK_UNDER_OBSERVED")])
    f = [x["code"] for x in st.by["staging-flaky-19"].flags]
    out.append(("staging-flaky-19 evaluated with MEDIUM_COVERAGE flag", "MEDIUM_COVERAGE" in f and st.by["staging-flaky-19"].verdict != "exclude", f))
    return out


def cp3(st):
    out = _expect(st, [("prod-standby-01", "TAG_DR_STANDBY"), ("prod-k8s-node-1", "TAG_AUTOSCALED"),
                       ("prod-checkout-01", "TAG_SEASONAL"), ("ip-allowlist-04", "TAG_ALLOWLISTED_IP"),
                       ("prod-db-01", "STATEFUL_PROD"), ("prod-legacy-plan-17", "UNKNOWN_PRICE"),
                       ("prod-nomon-13", "NO_TELEMETRY"), ("vm-maint-08", "STOPPED_RECENTLY"),
                       ("vm-9999", "NOT_IN_INVENTORY")])
    for n, flag in (("vm-untagged-14", "UNTAGGED_ENV"), ("dev-orphan-owner-15", "UNOWNED"), ("dev-misnamed-16", "TAG_NAME_CONFLICT")):
        out.append((f"{n} flagged {flag}", flag in [x["code"] for x in st.by[n].flags], ""))
    return out


def cp4(st):
    return _expect(st, [("prod-batch-07", "VETO_RECURRING_PEAK"), ("prod-billing-01", "VETO_RECURRING_PEAK"),
                        ("prod-checkout-03", "VETO_RECURRING_PEAK")]) + \
        [("prod-queue-02 (random bursts) is NOT called recurring", st.code("prod-queue-02") != "VETO_RECURRING_PEAK", st.code("prod-queue-02"))]


def cp5(st):
    t = D.load_truth().set_index("name")
    rows = [r for r in st.res if r.type in ("volume", "ip") or (r.inv and r.inv.get("state") == "stopped")]
    return [(f"{(r.inv or {}).get('name')} -> {t.loc[r.inv['name'], 'expected_reason_code']}",
             r.reason_code == t.loc[r.inv["name"], "expected_reason_code"], r.reason_code) for r in rows]


def cp6(st):
    return _expect(st, [("prod-cache-04", "VETO_MEMORY"), ("prod-ingest-09", "VETO_IOPS"),
                        ("prod-gateway-03", "VETO_NETWORK"), ("prod-orders-08", "VETO_LEAK"), ("dev-cache-13", "VETO_MEMORY")])


def cp7(st):
    return _expect(st, [("prod-reports-02", "ONE_OFF_PEAK"), ("prod-legacy-06", "WENT_QUIET"), ("prod-search-06", "RESERVED_MEMORY")])


def cp8(st):
    out = _expect(st, [("staging-db-02", "IDLE"), ("dev-tiny-14", "IDLE"), ("prod-old-12", "IDLE_PROD"),
                       ("dev-etl-04", "OFF_HOURS"), ("dev-support-05", "OFF_HOURS"), ("staging-load-06", "OFF_HOURS")])
    etl = st.by["dev-etl-04"].ev["off_hours"]
    out.append(("dev-etl-04 schedule keeps the 01:00-03:00 job on", not any(etl[d * 24 + h] for d in range(7) for h in (1, 2)), ""))
    out.append(("dev-misc-07 (fragmented) gets no schedule", "schedule" not in st.by["dev-misc-07"].actions, ""))
    return out


def cp9(st):
    out = _expect(st, [("prod-ml-10", "NO_CHEAPER_PLAN"), ("dev-report-02", "PEAK_REPLAY_FAILED"),
                       ("prod-search-02", "UNDER_PROVISIONED"), ("dev-web-03", "UNDERUSED")])
    for n, plan in (("prod-api-07", "B3"), ("staging-web-08", "B2"), ("dev-web-03", "B2")):
        got = st.by[n].actions.get("resize", {}).get("target")
        out.append((f"{n} resized to {plan}", got == plan, got))
    out.append(("dev-web-03 also scheduled", "schedule" in st.by["dev-web-03"].actions, ""))
    return out


def cp10(st):
    recs = [r for r in st.res if r.verdict in ("recommend", "upsize")]
    out = [("every recommendation has a risk level", all(r.risk and r.risk["level"] in ("Low", "Medium", "High") for r in recs), len(recs))]
    auc = st.scorer.risk_auc(st.sel)
    out.append(("risk ranks held-out overloads well (AUC >= 0.9)", auc >= 0.9, round(auc, 3)))
    return out


def cp11(st):
    c, d = st.scorer.cost_invariants(st.res)
    out = [("cost invariants hold for every resource", not d["violations"], d["violations"][:5])]
    o = st.by["dev-web-03"].cost["options"]
    out.append(("dev-web-03 combined < each single option (sequential, not additive)",
                o["resize+schedule"]["monthly_inr_after"] < min(o["resize"]["monthly_inr_after"], o["schedule"]["monthly_inr_after"]),
                {k: v["monthly_inr_after"] for k, v in o.items()}))
    out.append(("dev-tiny-15 below the Rs 500 floor", st.code("dev-tiny-15") == "BELOW_FLOOR", st.code("dev-tiny-15")))
    return out


def cp12(st):
    env = output.envelope(st.ctx, st.res)
    out = [("every object has all schema keys", all(set(SCHEMA_KEYS) <= set(i) for i in env["items"]), len(env["items"]))]
    out.append(("veto present exactly on rejects", all((i["veto"] is not None) == (i["verdict"] == "reject") for i in env["items"]), ""))
    out.append(("risk present exactly on recommend/upsize", all((i["risk"] is not None) == (i["verdict"] in ("recommend", "upsize")) for i in env["items"]), ""))
    out.append(("options always include 'none'", all("none" in i["options"] for i in env["items"]), ""))
    a = json.dumps(env, default=str, sort_keys=True)
    ctx2, res2 = PL.run(st.data, st.cfg, st.sel)
    b = json.dumps(output.envelope(ctx2, res2), default=str, sort_keys=True)
    out.append(("two runs give byte-identical JSON", a == b, len(a)))
    bt = BT.run(st.data, st.cfg, st.sel)
    out.append(("backtest: 0 unsafe recommendations", bt["unsafe"] == 0, f"{bt['unsafe']} of {bt['evaluated']}"))
    before = sum(i["options"]["none"]["monthly_inr_after"] for i in env["items"])
    saving = sum(i["options"][i["default_option"]]["saving_inr"] for i in env["items"] if i["verdict"] == "recommend")
    out.append(("headline saving within 15-35% of the bill", 0.15 <= saving / before <= 0.35, f"{saving / before:.1%}"))
    return out


def cp13(st):
    """Engine extras: alerts, presets, scorecard, benchmark, generated documents."""
    from . import alerts as AL
    from . import assumptions as AS
    from . import presets as PR
    from . import scorecard as SC
    from .run import build as run_build
    env, ctx, res, alerts = run_build()
    byname = {}
    for a in alerts:
        byname.setdefault(a["type"], set()).add((st.by_id_name.get(a["resource_id"]) or a["title"]))
    out = [("every alert explains itself (why + evidence + threshold)",
            all(a["why"] and a["evidence"]["threshold"] is not None for a in alerts), len(alerts))]
    for t, n in (("possible_compromise", "dev-sandbox-17"), ("level_shift", "prod-worker-05"),
                 ("memory_leak", "prod-orders-08"), ("monitoring_missing", "prod-nomon-13"),
                 ("capacity_trend", "vol-growing-10"), ("usage_spike", "prod-reports-02")):
        out.append((f"{t} alert on {n}", n in byname.get(t, set()), ""))
    disk = [n for n in byname.get("capacity_trend", set()) if n in ("prod-web-31", "prod-api-32", "prod-search-33", "prod-checkout-34")]
    out.append(("disk-filling VMs alerted (>= 3 of 4)", len(disk) >= 3, disk))
    out.append(("no spike alert for scheduled peaks (prod-batch-07, prod-billing-01)",
                not ({"prod-batch-07", "prod-billing-01"} & byname.get("usage_spike", set())), ""))
    out.append(("cost increase alert for the growth team's new VMs",
                any("growth" in a["title"] for a in alerts if a["type"] == "cost_increase"), ""))
    ids = {a["alert_id"]: a["resource_id"] for a in alerts}
    out.append(("recommendation alert_ids point at alerts for the same resource",
                all(ids.get(x) == i["resource"]["resource_id"] for i in env["items"] for x in i["alert_ids"]), ""))
    pr = PR.run_all()
    sav = [pr[p]["saving_inr"] for p in PR.ORDER]
    out.append(("preset savings non-decreasing max_performance -> max_savings", sav == sorted(sav), sav))
    out.append(("conservative presets: 0 unsafe in the held-out week",
                pr["default"]["backtest_unsafe"] == 0 and pr["max_performance"]["backtest_unsafe"] == 0, ""))
    stored = json.loads(PR.OUT.read_text()) if PR.OUT.exists() else None
    out.append(("presets_report.json is current", stored == json.loads(json.dumps(pr)), ""))
    sc = SC.build(env, st.data, st.cfg, st.sel)
    stored = json.loads((D.DATA / "scorecard.json").read_text()) if (D.DATA / "scorecard.json").exists() else None
    out.append(("scorecard.json is current", stored == json.loads(json.dumps(sc)), f"{sc['correct']}/{sc['rows']}"))
    from .benchmark import OUT as BOUT
    b = json.loads(BOUT.read_text()) if BOUT.exists() else {}
    out.append((f"benchmark covers >= {st.cfg('benchmark.target_vms')} VMs", b.get("vms", 0) >= st.cfg("benchmark.target_vms"),
                f"{b.get('vms')} VMs in {b.get('seconds', {}).get('total')} s"))
    out.append(("ASSUMPTIONS.md matches its inputs", AS.build() == AS.OUT.read_text(encoding="utf-8") if AS.OUT.exists() else False, ""))
    stored_alerts = json.loads((D.DATA / "alerts.json").read_text()) if (D.DATA / "alerts.json").exists() else None
    out.append(("alerts.json is current", stored_alerts == json.loads(json.dumps(AL.envelope(ctx, alerts), default=str)), ""))
    return out


CHECKS = [cp1, cp2, cp3, cp4, cp5, cp6, cp7, cp8, cp9, cp10, cp11, cp12, cp13]
NAMES = PL.ORDER + ["extras"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upto", type=int, required=True)
    upto = ap.parse_args().upto
    st = State()
    ok_all = True
    for k in range(1, upto + 1):
        rows = (_selection_checks(st, k) if k <= len(PL.ORDER) else []) + CHECKS[k - 1](st)
        ok = all(r[1] for r in rows)
        print(f"\n=== CP{k} {NAMES[k - 1]} {'PASS' if ok else 'FAIL'}")
        for d, good, v in rows:
            print(f"  {'PASS' if good else 'FAIL'}  {d}  {v}")
        if not ok:
            ok_all = False
            break
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
