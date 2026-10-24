"""Generate engine/REASONING.md from selection_log.json, config.yaml, sensitivity.json and disputes.py,
plus the hand-written explanations below. python -m engine.reasoning"""
import json
import re
from pathlib import Path

import yaml

from . import pipeline as PL
from .config import numeric_keys
from .disputes import DISPUTES
from .select import LOG, SEL

HERE = Path(__file__).resolve().parent
OUT = HERE / "REASONING.md"
CFG = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
CAT = {"M": "measured", "C": "cited default", "D": "derived", "S": "scenario choice", "J": "judgement"}

WHAT = {
    "clean": ("Decides what counts as an observation. Everything downstream depends on it: a gap read as 0% looks idle, "
              "a frozen agent looks idle, a duplicated window double-counts a busy hour.",
              "Candidates differ only in how aggressively they distrust the data: nothing extra (a), freeze detection on "
              "CPU only (b), on CPU **and** memory (c), and bridging short gaps (d)."),
    "gates_data": ("Decides whether there is enough trustworthy history to decide at all (exclude / data-flag).",
                   "All share history >= 14 d, no resize in the last 14 d, coverage >= 80 % and no 3x level shift. They "
                   "differ in how 'blind spots' are found: none (a), any hour-of-week bucket under-observed (b), or the "
                   "VM's *own* busiest hours under-observed (c). An effective-sample-size gate was considered and dropped "
                   "analytically: with one AR(1) coefficient per VM, ESS / ESS_full = n_obs / n_full = coverage, so it adds "
                   "nothing beyond the coverage gate."),
    "gates_policy": ("Applies human context before any metric: tags, policy, price list, stopped state, missing tags.",
                     "a uses only the stated tags/policy; b additionally guesses a missing env from the name prefix."),
    "peaks": ("For a VM an average-based tool would cut (mean < 20 % or CPU P < 40 %), decides whether it has a peak "
              "that *recurs* (reject VETO_RECURRING_PEAK).",
              "a = PLAN.md 7 (>= 4 days with a 30-min peak > 80 % AND p99 >= 80); b = the daily-peak count alone; "
              "c = periodicity: autocorrelation at a 24 h or 168 h lag >= 0.3 AND p99 >= 80. The difference matters for "
              "random bursts (prod-queue-02: peaks on 6 days but acf ~0, so not 'recurring') and for weekly jobs whose "
              "p99 is low (dev-report-02: acf_168h 0.95 but p99 24 %, which must be caught by replay instead)."),
    "noncompute": ("Volumes, public IPs and long-stopped VMs: unattached vs idle vs oversized vs stopped.",
                   "b adds a growth veto: never shrink or clean a volume that will be full within 30 days."),
    "vetoes": ("Non-CPU signals that block shrinking: leak, memory, IOPS, network, growth.",
               "a = PLAN.md 7 fixed thresholds with growth from the raw slope; b = growth only when the slope is "
               "statistically significant; c = one 'any metric > 70 %' rule without leak / reserved-heap handling."),
    "patterns": ("Situations a human must look at: one-off peak, went quiet, reserved memory.",
                 "They differ only in how a one-off peak is detected: p99 without the busiest day (a) or the 2nd-busiest "
                 "day's 30-min peak (b)."),
    "candidates": ("Proposes actions: idle -> stop, underused -> resize (sized at CP9), off-hours -> schedule.",
                   "Bundles, because the three share evidence: a = CPU-only idle + fixed 20:00-08:00 template; b = PLAN.md 7 "
                   "(4-metric idle with absolute lines, profile-based off-hours); c = 4-metric idle with lines relative to "
                   "plan size + 30-min wake buffer; d = c with 'underused' decided by replay instead of P < 40."),
    "sizing": ("Chooses the target plan and proves it safe (Peak Replay), or proves there is none; detects under-provisioning.",
               "a = percentile formula only; b = PLAN.md 7 formula then replay gate; c = cheapest plan whose replay passes "
               "(incl. the 2nd-busiest-day peak); d = c + CPU target by core count + forward replay under a significant trend."),
    "risk": ("Says how likely a recommended change is to hurt, and how sure we are.",
             "a = PLAN.md 7 points table; b = probability of a bad month from resampling the observed days (block "
             "bootstrap) then escalated for prod / stateful / stop; c = b's level with the points also listed."),
    "cost": ("Prices every combination of actions per resource (the schema's options) and applies the Rs 500 floor.",
             "a = sequential (each step priced on what the previous step left); b = additive (each saving against the "
             "original cost, summed)."),
    "assemble": ("Turns all findings into one verdict.",
                 "a = first-match ladder in stage order (later findings never shown); b = evidence board + published "
                 "precedence, every fired signal listed."),
}

WHY_EXTRA = {
    "clean": "Flatline detection on CPU alone masks the rate-limited plateau of staging-api-09 (exactly 40.00 % for 8 h) "
             "and flips it; requiring CPU **and** memory to freeze avoids that. On this dataset the frozen agent "
             "(dev-api-16) does not change any verdict, so c and a tie and the simpler one is kept.",
    "gates_data": "Only the VM's own peak hours matter: a random 12 % gap (staging-flaky-19) leaves some hour-of-week "
                  "bucket thin and wrongly flags it under b, while the batch VM whose 01:00-04:00 window was missed on "
                  "18 nights (prod-batch-20) is caught by c but missed by a.",
    "peaks": "Periodicity is the only rule that separates *scheduled* peaks (batch, weekly billing, daily checkout: "
             "acf 0.9+) from *random* bursts (queue: acf ~0), which must fall through to replay.",
    "vetoes": "With contested rows included, the significance requirement matters: an unscheduled noisy slope on a batch "
              "VM is not growth.",
    "candidates": "Real network and disk IO are lognormal with spreads ~2.0 and ~1.06 (fitted), so absolute idle lines "
                  "(5 MB/h, 5 IOPS) declare every idle VM busy (b loses all zombies). Lines relative to plan size fix that.",
    "sizing": "Formula-only sizing is the only logic with an unsafe cut in the held-out week (dev-report-02's weekly job). "
              "The three replay-based logics agree on every verdict, so the one with fewest parameters is kept.",
    "risk": "The bootstrap probability ranks held-out overloads far better than the points table (AUC 0.97 vs 0.81); "
            "b and c produce the same levels, so the simpler b is kept and the points are not needed for the level.",
    "cost": "Additive savings exceed the bill for dev-web-03 (resize + schedule would cost less than zero).",
    "assemble": "The ladder stops at the first stage that fires, so it hides secondary signals and mis-orders "
                "went-quiet vs upsize; the precedence table shows everything.",
}

GLOBAL_DECISIONS = [
    ("Shrink-considered", "Capacity vetoes and the recurring-peak check run only for VMs an average-based tool would "
     "cut (mean < `peaks.looks_wasteful_mean` or CPU P < `candidates.underused_cpu`). A busy VM cannot be 'rejected' "
     "for a shrink nobody proposed."),
    ("Leak on every VM", "A leaking VM's memory percentiles are an artefact of its restart cycle, so neither a downsize "
     "nor an upsize is trustworthy until it is fixed."),
    ("Recurring peak blocks resize only", "A scheduled peak forbids shrinking, not scheduling around it; the off-hours "
     "map keeps the peak window on by construction (dev-etl-04's nightly job)."),
    ("Went quiet outranks upsize", "Recent behaviour invalidates older evidence, so it sits in the data-flag class."),
    ("NO_CHEAPER_PLAN vs PEAK_REPLAY_FAILED", "NO_CHEAPER_PLAN only when memory rules out every cheaper plan; when CPU "
     "is the limit the honest explanation is the replay of what an average-based tool would do."),
    ("Upsize only when busy on average", "A VM averaging under 20 % that touches 90 % is batchy, not starved."),
    ("Floor applies to compute changes", "Deleting or releasing a resource with no running workload has no blast "
     "radius, so the Rs 500 attention floor does not apply to it."),
    ("Service groups", "Members get the same target, sized on the busiest member; if any member cannot shrink, none do."),
    ("Linear CPU scaling", "Peak Replay assumes CPU % scales with vCPU count (stated assumption; headroom and the "
     "one-step prod rule absorb the error)."),
]


def _scores(e):
    last = e["initial"]
    for p in e["passes"]:
        if p.get("rescored_current"):
            last = p["rescored_current"]
    return last


def _cand_table(scores, selected):
    rows = ["| candidate | prior | correctness /4 | safety /3 | explain /2 | robust /1 | **total** | evidence |",
            "|---|---|---|---|---|---|---|---|"]
    for s in sorted(scores, key=lambda x: -x["total"]):
        c = s["evidence"]["correctness"]
        ev = []
        if "rows" in c:
            ev.append(f"{c['correct']}/{c['rows']} rows right")
            if c.get("contested_rows"):
                ev.append(f"{c['contested_rows']} contested")
        if "auc" in c:
            ev.append(f"AUC {c['auc']}")
        if "violations" in c:
            ev.append(f"invariant violations: {', '.join(c['violations']) or 'none'}")
        ev.append(f"{s['evidence']['safety']['unsafe']} unsafe / {s['evidence']['safety']['evaluated']}")
        ev.append(f"flip {s['evidence']['robustness'].get('flip_rate')}")
        name = f"**{s['candidate']}**" if s["candidate"] == selected else s["candidate"]
        rows.append(f"| {name} — {s['desc']} | {s['prior']} | {s['correctness']} | {s['safety']} | {s['explainability']} | "
                    f"{s['robustness']} | **{s['total']}** | {'; '.join(ev)} |")
    return rows


def _why(scores, selected):
    ranked = sorted(scores, key=lambda x: (-x["total"], x["params"]))
    win = next(s for s in ranked if s["candidate"] == selected)
    others = [s for s in ranked if s["candidate"] != selected]
    if not others:
        return "Only candidate."
    nxt = others[0]
    if abs(win["total"] - nxt["total"]) < 1e-9:
        return (f"Tie with `{nxt['candidate']}` at {win['total']}: the simpler logic wins "
                f"({win['params']} vs {nxt['params']} parameters).")
    parts = {k: win[k] - nxt[k] for k in ("correctness", "safety", "explainability", "robustness")}
    k = max(parts, key=lambda x: parts[x])
    return f"Beats `{nxt['candidate']}` by {win['total'] - nxt['total']:.2f}; the decisive part is {k} (+{parts[k]:.2f})."


def _sweep(log):
    sets = {"base 4/3/2/1": (4, 3, 2, 1), "equal 2.5 each": (2.5, 2.5, 2.5, 2.5), "3/3/3/1": (3, 3, 3, 1),
            "5/3/1/1": (5, 3, 1, 1), "4/4/1/1": (4, 4, 1, 1), "6/2/1/1": (6, 2, 1, 1)}
    base = (CFG["score"]["w_correct"]["value"], CFG["score"]["w_safety"]["value"], CFG["score"]["w_explain"]["value"],
            CFG["score"]["w_robust"]["value"])
    rows = ["| checkpoint | " + " | ".join(sets) + " |", "|---|" + "---|" * len(sets)]
    changes = 0
    for e in log:
        sc = _scores(e)
        cells = []
        for w in sets.values():
            def tot(s):
                return sum(s[k] / b * nw for k, b, nw in zip(("correctness", "safety", "explainability", "robustness"), base, w))
            win = max(sc, key=lambda s: (round(tot(s), 9), -s["params"]))["candidate"]
            changes += win != e["selected"]
            cells.append(win if win == e["selected"] else f"**{win}**")
        rows.append(f"| CP{e['checkpoint']} {e['component']} | " + " | ".join(cells) + " |")
    return rows, changes


def _where(key):
    sec, name = key.split(".", 1)
    hits = []
    for p in sorted(HERE.rglob("*.py")):
        if p.name in ("reasoning.py",):
            continue
        txt = p.read_text(encoding="utf-8")
        if f'"{key}"' in txt or (sec == "time_units" and re.search(rf'["\']{name}["\']', txt)):
            hits.append(p.relative_to(HERE.parent).as_posix())
    return ", ".join(hits) or "-"


def _ledger(sens):
    rows = ["| key | value | category | why | where used | sensitivity (-25% / -10% / +10% / +25%: flips, saving change) |",
            "|---|---|---|---|---|---|"]
    for key in numeric_keys():
        sec, name = key.split(".", 1)
        e = CFG[sec][name]
        if key in sens.get("keys", {}):
            r = sens["keys"][key]
            sv = " / ".join(f"{v['flips']}, {v['saving_change_pct']:+.1f}%" for v in r.values())
        elif sec == "time_units":
            sv = "definition (not a threshold)"
        elif sec in ("score", "backtest"):
            sv = "selection-level: see the weight sweep"
        elif sec == "alerts":
            sv = "alerts only: never changes a verdict or a saving"
        elif sec == "benchmark":
            sv = "benchmark size only"
        else:
            sv = "not perturbed (list / seed)"
        rows.append(f"| `{key}` | {e['value']} | {e['category']} ({CAT[e['category']]}) | {e['why']} | {_where(key)} | {sv} |")
    return rows


def _presets_line():
    p = HERE / "presets_report.json"
    if not p.exists():
        return "**Presets**: not run yet (`python -m engine.presets`)."
    rep = json.loads(p.read_text())
    sav = [v["saving_pct"] for v in rep.values()]
    unsafe = sum(v["backtest_unsafe"] for v in rep.values())
    return (f"**Presets** (`engine/presets_report.json`): savings move only {min(sav)}% -> {max(sav)}% from max-performance "
            "to max-savings because Peak Replay, the memory caps, the recurring-peak veto and the one-step prod rule are "
            f"preset-independent; {unsafe} unsafe changes across all presets in the held-out week.")


def main():
    log = json.loads(LOG.read_text())
    sel = json.loads(SEL.read_text())
    sens_p = HERE / "sensitivity.json"
    sens = json.loads(sens_p.read_text()) if sens_p.exists() else {}
    L = ["# Engine reasoning", "",
         "Every logic choice and every number in the engine, with the evidence behind it. Generated by "
         "`python -m engine.reasoning` from `selection_log.json`, `config.yaml`, `sensitivity.json` and `disputes.py`; "
         "the hand-written explanations live in `engine/reasoning.py`.", "",
         "## 1. How a logic was chosen", "",
         "Each engine component (12 checkpoints, in dependency order) has 2-4 candidate logics. At checkpoint *k* every "
         "candidate of component *k* is scored with all other components fixed, the best is kept, and then every earlier "
         "component *j* is re-checked: if switching *k* to its runner-up changes any verdict *j* decides, *j*'s candidates "
         "are re-scored and *j* switches if another candidate now wins by at least "
         f"`score.switch_margin` = {CFG['score']['switch_margin']['value']} (coordinate ascent, at most "
         f"`score.max_passes` = {CFG['score']['max_passes']['value']} passes).", "",
         "**Confidence score (0-10) = correctness + safety + explainability + robustness**", "",
         "| part | weight | measured as | why this weight |", "|---|---|---|---|",
         f"| correctness | `score.w_correct` = {CFG['score']['w_correct']['value']} | share of the rows this component decides that match truth.csv (verdict + reason). Rows = the codes it owns **plus every row on which its candidates disagree** (contested rows), so false positives and side effects count. Risk: out-of-sample AUC, (AUC - `score.auc_chance`) / (1 - `score.auc_chance`). Cost: accounting invariants. | {CFG['score']['w_correct']['why']} |",
         f"| safety | `score.w_safety` = {CFG['score']['w_safety']['value']} | backtest: decide on days 0-{CFG['backtest']['split_day']['value'] - 1}, replay the recommendations on the held-out week; 0 unsafe = full, 1 unsafe = `score.safety_one_unsafe` = {CFG['score']['safety_one_unsafe']['value']}, more = 0 | {CFG['score']['w_safety']['why']} |",
         f"| explainability | `score.w_explain` = {CFG['score']['w_explain']['value']} | share of this component's fired findings visible in the output with value, threshold and result: >= `score.explain_full` -> full, >= `score.explain_half` -> x `score.partial` | {CFG['score']['w_explain']['why']} |",
         f"| robustness | `score.w_robust` = {CFG['score']['w_robust']['value']} | verdict flip rate when every threshold of the component moves +/- `score.perturb`: < `score.flip_good` -> full, < `score.flip_ok` -> x `score.partial` | {CFG['score']['w_robust']['why']} |", "",
         f"- **Acceptance bar** `score.accept_min` = {CFG['score']['accept_min']['value']}: {CFG['score']['accept_min']['why']}",
         f"- **Switching margin** `score.switch_margin` = {CFG['score']['switch_margin']['value']}: {CFG['score']['switch_margin']['why']}",
         "- **Tie-break:** fewer parameters wins (a simpler logic that is equally right is easier to explain and to trust).",
         "- **Bias guard:** truth.csv was written alongside the original plan, so correctness is also logged on bulk "
         "(real-trace-resampled) rows only, and safety and robustness do not use truth.csv at all. Where the data "
         "contradicts a label, the label is listed as a dispute (section 5) instead of bending the logic to it.", "",
         "## 2. Final selection", "", "| CP | component | selected logic | total |", "|---|---|---|---|"]
    for e in log:
        L.append(f"| {e['checkpoint']} | {e['component']} | `{sel[e['component']]}` | {e['selected_total']} |")
    L += ["", "### Engine-wide design decisions (apply to every candidate)", ""]
    L += [f"- **{t}.** {d}" for t, d in GLOBAL_DECISIONS]
    L += ["", "## 3. Checkpoints", ""]
    for e in log:
        comp = e["component"]
        what, cands = WHAT[comp]
        sc = _scores(e)
        L += [f"### CP{e['checkpoint']} - {comp}", "", f"**What it decides.** {what}", "", f"**Candidates.** {cands}", ""]
        L += _cand_table(sc, sel[comp])
        L += ["", f"**Why `{sel[comp]}`.** {_why(sc, sel[comp])} {WHY_EXTRA.get(comp, '')}", ""]
        deps = [i for p in e["passes"] for i in p["dependence"]]
        dep_true = [i for i in deps if i["depends_on_current"]]
        if not deps:
            L.append("**Dependence.** First checkpoint: nothing earlier to re-check.")
        elif not dep_true:
            L.append(f"**Dependence.** Re-checked {', '.join(sorted({i['earlier'] for i in deps}))}: none of their "
                     "verdicts change when this component switches logic, so no re-scoring was needed.")
        else:
            txt = []
            for i in dep_true:
                s = f"`{i['earlier']}` (rows that change: {', '.join(i['rows_changed'][:5])})"
                if i.get("rescored"):
                    s += " re-scored: " + ", ".join(f"{x['candidate']} {x['total']}" for x in i["rescored"])
                s += f" -> switched {i['switched']['from']} -> {i['switched']['to']}" if i.get("switched") else " -> kept"
                txt.append(s)
            L.append("**Dependence.** " + "; ".join(txt) + ".")
        L.append("")
    sweep, changes = _sweep(log)
    L += ["## 4. Do the score weights decide the outcome?", "",
          "Each candidate's four sub-scores are re-weighted with alternative weight sets (bold = a different winner than "
          "the base weights).", ""] + sweep + ["",
          f"{'No selection changes under any alternative weighting: the choices are not an artefact of 4/3/2/1.' if changes == 0 else f'{changes} cell(s) change winner: those choices depend on the weighting and are judgement calls, stated as such.'}", ""]
    L += ["## 5. Label disputes (truth.csv rows the selected engine disagreed with)", "",
          "Found on the dataset of commit 7b73730. **Resolved on the data branch (b1_adi)**: five planted VMs pinned, "
          "right-sized resampling kept busy on average, three contradictory labels corrected. The disputes therefore apply "
          "only to that dataset (identified by its fingerprint in `engine/disputes.py`): there they are `xfail(strict=True)` "
          "tests; on the corrected dataset every truth row must match, and the engine (same selected logic) gets 141/141. "
          "Re-running the whole checkpointed selection on the corrected data picks the same logic for all 12 "
          "components (on the data it was found on the comparison is section 8; on the merged main branch the selection "
          "log above IS the corrected-data run).", "",
          "| resource | label said | engine said | evidence and reasoning |", "|---|---|---|---|"]
    for n, d in DISPUTES.items():
        L.append(f"| {n} | {d['label']} | {d['engine']} | {d['summary']} |")
    L += ["", "## 6. Alerts, presets, scorecard, benchmark", "",
          "**Alerts** (`engine/alerts.py`, `data/alerts.json`). Every alert states the number, the threshold and why.",
          "- *Usage spike*: robust z of the 30-min rolling **log-ratio** to the same hour-of-week median, sigma = "
          "`alerts.mad_to_sigma` x MAD. Three decisions, each fixing a measured false-alarm source: (1) rolling the "
          "*deviation* instead of the raw value stopped windows straddling an hour boundary from comparing a peak hour with "
          "a quiet one (prod-billing-01 at 12:00 was '77% vs 3%'); (2) scaling MAD to sigma makes 4 a real 4-sigma "
          "threshold (plain 4 x MAD is ~2.7 sigma); (3) the log scale treats the fitted multiplicative day-to-day drift "
          "(Bitbrains sd 0.59) as normal spread. During development spike alerts fell 56 -> 36 -> 11 on the first dataset, the strongest being the planted "
          "one-off (prod-reports-02, z 15) and the random bursts (prod-queue-02).",
          "- *Cost increase*: alerts on the provisioning **step** only (the day cost changes), not on the following days "
          "while the 7-day average catches up. Threshold x1.1 is measured: billing is flat on 87% of team-days and the "
          "steps in the window are +12.9% / +12.7% (new VMs) vs +2.4% / -1.7% / -3.4%; the plan's x1.2 missed both "
          "new-VM events.",
          "- *Capacity trend* (CPU p95, memory p95, disk, volumes): significant least-squares slope over the last 14 days "
          "reaching 90% within 30 days (critical within 7). *Level shift* / *possible compromise* (CPU and egress both "
          "> 3x). *Memory leak*, *under-provisioned*, *monitoring missing*, *budget overrun* (forecast = spent + 7-day "
          "run-rate x days left vs 1.25 x first-quarter spend).", "",
          _presets_line(), "",
          "**Scorecard** (`data/scorecard.json`) and **benchmark** (`engine/benchmark.json`): summarised in ASSUMPTIONS.md.", "",
          "## 7. Numbers ledger", "",
          "Every number the engine uses. Categories: M measured, C cited default, D derived, S scenario, J judgement. "
          "Sensitivity = verdicts that flip and headline-saving change when only that number moves. Large swings at "
          "+/-25% on a percentile or coverage mark a boundary, not fragility: a percentile x 1.1 hits 100 (the single "
          "worst sample) and min_coverage x 1.25 = 1.0 (no missing sample allowed at all).", ""]
    L += _ledger(sens)
    corr = HERE / "selection_log_corrected_data.json"
    if corr.exists():
        cl = {e["checkpoint"]: e for e in json.loads(corr.read_text())}
        L += ["", "## 8. Selection re-run on the corrected dataset", "",
              "The full checkpointed selection was re-run on the data branch's corrected dataset (engine code combined "
              "with it in a temporary worktree, nothing committed): `engine/selection_log_corrected_data.json`.", "",
              "| CP | component | selected (this dataset) | total | selected (corrected dataset) | total |", "|---|---|---|---|---|---|"]
        same = True
        for e in log:
            c = cl.get(e["checkpoint"], {})
            same &= c.get("selected") == e["selected"]
            L.append(f"| {e['checkpoint']} | {e['component']} | `{e['selected']}` | {e['selected_total']} | "
                     f"`{c.get('selected')}` | {c.get('selected_total')} |")
        L += ["", "**Identical selection on both datasets**: the chosen logic does not depend on the disputed labels."
              if same else "**The selection differs on the corrected dataset**: see the rows above."]
    L += ["", "### Presets", "", "Presets change only the sizing percentile, CPU target and replay budget (AWS Compute "
          "Optimizer exposes the same trade-off as 'maximum savings' ... 'maximum performance').", "",
          "| preset | percentile prod / non-prod | CPU target prod / non-prod | replay budget prod / non-prod (min/month) |",
          "|---|---|---|---|"]
    for p, v in CFG["presets"].items():
        L.append(f"| {p} | {v['percentile_prod']} / {v['percentile_nonprod']} | {v['target_cpu_prod']} / {v['target_cpu_nonprod']} | "
                 f"{v['budget_prod']} / {v['budget_nonprod']} |")
    L += ["", "### Numbers that are not thresholds", "",
          "- `0`, `1`, `100` and the `time_units` (5-minute slots, 288 per day, ...) are definitions, not choices.",
          "- `prior` and `params` inside each component's `CANDIDATES` table are my pre-measurement judgement and the "
          "tie-break count; they never change a verdict.",
          "- Rounding precision in output (`round(x, 1)`) is display, not a decision.",
          "- `engine/checkpoints.py` states expected values on purpose (it is verification, like a test).", ""]
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", OUT.name, len(L), "lines")


if __name__ == "__main__":
    main()
