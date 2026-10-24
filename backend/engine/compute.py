"""The VM decision pipeline (plan section 7, steps 0-9). First terminal verdict wins; strict < / >.

Order (each check appended to the trace):
  0 inventory validation   1 exclusion gates   3 under-provisioned   5a went quiet
  'looks shrinkable' gate (mean CPU < 20% or CPU P < 40%): otherwise healthy, vetoes are irrelevant
  4 vetoes + 5 patterns: leak > reserved memory > memory > IOPS > network > growth > peak under-observed
                         > recurring peak > one-off peak
  6 candidates (idle, underused, off-hours)   7 sizing   8 Peak Replay   9 floor
"""
import numpy as np

from ..cost.model import format_inr, scheduled_compute, snapshot_cost
from . import replay as rp
from .candidates import schedule as make_schedule
from .common import Outcome, action, build_options, days_since, key_of, used_gb, veto
from .sizing import index_of, needs, size

ENV_PREFIXES = ("prod", "staging", "dev")


def flags_for(row, coverage, min_cov):
    flags = []
    if row["env"] == "":
        flags.append({"code": "UNTAGGED_ENV", "message": "env tag missing: treated as prod (safest)."})
    if row["owner_team"] == "":
        flags.append({"code": "UNOWNED", "message": "owner missing: shown as 'unowned'."})
    prefix = row["name"].split("-")[0]
    if row["env"] and prefix in ENV_PREFIXES and prefix != row["env"]:
        flags.append({"code": "TAG_NAME_CONFLICT",
                      "message": f"name says {prefix}, tag says {row['env']}: the tag is trusted."})
    if min_cov <= coverage < 0.95:
        flags.append({"code": "MEDIUM_COVERAGE", "message": f"coverage {coverage:.0%}: confidence lowered."})
    return flags


def peak_when(buckets):
    """Hour-of-week buckets -> 'daily 02:00' / 'Sun 09:00, Sun 10:00'."""
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    by_hour = {}
    for b in buckets:
        by_hour.setdefault(b % 24, set()).add(b // 24)
    parts = [f"daily {h:02d}:00" if len(d) == 7 else ", ".join(f"{days[x]} {h:02d}:00" for x in sorted(d))
             for h, d in sorted(by_hour.items())]
    return ", ".join(parts[:3]) + ("…" if len(parts) > 3 else "")


def naive_cut(e, row, f, cur):
    """What an average-based tool would do: size on mean CPU only, ignoring memory and peaks."""
    mean = f.get("mean_cpu") or 0.0
    need = row["vcpu"] * mean / e.p.cpu_target(e.is_prod(row))
    plan = next((p for p in e.cat if p.vcpu >= need), e.cat[-1])
    if plan.price >= cur["compute_inr"]:
        return {"basis": "mean CPU", "mean_cpu_pct": round(mean, 1), "action": "none", "plan": row["plan_id"],
                "would_save_inr": 0}
    return {"basis": "mean CPU", "mean_cpu_pct": round(mean, 1), "action": "resize", "plan": plan.plan_id,
            "would_save_inr": int(cur["compute_inr"] - plan.price)}


def evaluate_vm(e, rid, row, f, cur, tr):
    prod = e.is_prod(row)
    plan_known = row["plan_id"] in e.cfg.plans

    # ---- step 0: inventory validation ----------------------------------------------------------
    if tr.add("gate.price", "plan in catalogue", row["plan_id"], "catalogue", "pass" if plan_known else "fail") == "fail":
        tr.terminal()
        return Outcome("exclude", "UNKNOWN_PRICE",
                       f"Plan {row['plan_id']} is not in the price catalogue: we never guess a price.")
    has_metrics = rid in e.cleaned.series
    if tr.add("gate.telemetry", "metric rows present", has_metrics, True, "pass" if has_metrics else "fail") == "fail":
        tr.terminal()
        return Outcome("exclude", "NO_TELEMETRY", "No metrics in 30 days: the monitoring agent is missing.")

    # ---- step 1: exclusion gates -----------------------------------------------------------------
    tags = row["tags_list"]
    for tag, code, why in (("dr_standby", "TAG_DR_STANDBY", "DR warm standby: telemetry alone is insufficient."),
                           ("autoscaled", "TAG_AUTOSCALED", "Autoscaled / K8s node: rightsize the node pool, not the node."),
                           ("seasonal_peak", "TAG_SEASONAL", "Seasonal peak outside the 30-day window (festive sale).")):
        if tr.add(f"gate.tag.{tag}", f"tag {tag}", tag in tags, "absent", "fail" if tag in tags else "pass") == "fail":
            tr.terminal()
            return Outcome("exclude", code, why)
    if tr.add("gate.policy", "optimize_policy", row["optimize_policy"], "≠ never",
              "fail" if row["optimize_policy"] == "never" else "pass") == "fail":
        tr.terminal()
        return Outcome("exclude", "POLICY_NEVER", "optimize_policy = never.")
    stateful_prod = "stateful" in tags and prod
    if tr.add("gate.stateful_prod", "stateful AND prod", stateful_prod, False, "fail" if stateful_prod else "pass") == "fail":
        tr.terminal()
        m = f["metrics"]
        return Outcome("exclude", "STATEFUL_PROD",
                       f"Stateful prod VM: never resized automatically (IOPS p95 {m['iops_pct']['p95']:.0f}% of "
                       f"provisioned, CPU p99 {m['cpu']['p99']:.0f}%).")
    days = f["days_of_data"]
    if tr.add("gate.history", "days_of_data ≥ 14", days, e.t("min_days_of_data"),
              "fail" if days < e.t("min_days_of_data") else "pass") == "fail":
        tr.terminal()
        return Outcome("exclude", "HISTORY_TOO_SHORT", f"Only {days} days of data (< {e.t('min_days_of_data'):.0f}).")
    resized = days_since(row["last_resized_at"], e.now)
    recent = resized is not None and resized < e.t("min_days_of_data")
    if tr.add("gate.recently_resized", "days since resize ≥ 14", None if resized is None else round(resized, 1),
              e.t("min_days_of_data"), "fail" if recent else "pass") == "fail":
        tr.terminal()
        return Outcome("exclude", "RECENTLY_RESIZED",
                       f"Resized {resized:.0f} days ago ({row['previous_plan_id']} → {row['plan_id']}): older data "
                       f"describes a different machine.")
    cov = f["coverage"]
    if tr.add("gate.coverage", "coverage ≥ 80%", cov, e.t("min_coverage"),
              "fail" if cov < e.t("min_coverage") else "pass") == "fail":
        tr.terminal()
        return Outcome("exclude", "LOW_COVERAGE", f"Coverage {cov:.0%} (< 80%): insufficient data quality.")
    shift = f.get("level_shift_up")
    anomaly = shift is not None and shift > e.cfg.get("alerts.g3_level_shift_ratio")
    if tr.add("gate.anomaly", "level_shift_up ≤ 3", shift, e.cfg.get("alerts.g3_level_shift_ratio"),
              "fail" if anomaly else "pass") == "fail":
        tr.terminal()
        return Outcome("exclude", "ACTIVE_ANOMALY",
                       f"CPU over the last 48 h is {shift:.1f}× the prior 28 days: anomaly in progress, not sized.")

    m = f["metrics"]
    key = e.p.pct_key(prod)
    cpu_p, mem_p = m["cpu"][key], m["mem"][key]
    s = e.cleaned.series[rid]
    cpu, mem = s.values["cpu_pct"], s.values["mem_pct"]

    mean = f["mean_cpu"]
    naive = naive_cut(e, row, f, cur)

    def reject(code, v, reason, recurring=None, replay=None):
        tr.terminal()
        return Outcome("reject", code, reason, veto=v, naive=naive, recurring=recurring, replay=replay)

    # ---- step 5a: went quiet (decommission review), regardless of averages ------------------------
    down = f.get("level_shift_down")
    if tr.add("pattern.went_quiet", "last 7 d / prior 23 d ≥ 0.2", down, e.t("went_quiet_ratio"),
              "flag" if down is not None and down < e.t("went_quiet_ratio") else "pass") == "flag":
        tr.terminal()
        return Outcome("flag", "WENT_QUIET",
                       f"CPU in the last 7 days is {down:.0%} of the prior 23 days: confirm decommission with the owner.")

    # ---- step 4 (leak, on every VM): a leaking VM's memory is an artefact of its restarts -----------
    leak = f["leak_score"]
    if tr.add("veto.leak", "leak_score < 3", leak, e.cfg.get("alerts.g6_leak_cycles"),
              "fail" if leak >= e.cfg.get("alerts.g6_leak_cycles") else "pass") == "fail":
        return reject("VETO_LEAK", veto("leak", "leak_score", leak, e.cfg.get("alerts.g6_leak_cycles"), ">=",
                                        "memory leak suspected"),
                      f"Memory climbs and resets {leak} times in 30 days (sawtooth): a leak, not spare RAM. "
                      f"No sizing decision is trustworthy until it is fixed.")

    # ---- step 3: under-provisioned (CPU p99 > 90 on a VM that is busy on average) -----------------
    p99 = m["cpu"]["p99"]
    under = p99 > e.t("upsize_cpu_p99_pct") and mean >= e.t("upsize_min_mean_cpu_pct")
    if tr.add("step3.under_provisioned", "CPU p99 ≤ 90 or mean CPU < 20 (batchy, not starved)", round(p99, 1),
              e.t("upsize_cpu_p99_pct"), "fail" if under else "pass") == "fail":
        return upsize(e, rid, row, f, cur, cpu, mem, prod, tr)

    # ---- looks shrinkable? -----------------------------------------------------------------------
    shrinkable = mean < e.t("shrinkable_mean_cpu_pct") or cpu_p < e.t("underused_cpu_pct")
    if tr.add("gate.looks_shrinkable", f"mean CPU < 20% or CPU {key} < 40%", round(mean, 1), e.t("shrinkable_mean_cpu_pct"),
              "pass" if shrinkable else "healthy") == "healthy":
        tr.terminal()
        return Outcome("healthy", "RIGHT_SIZED",
                       f"CPU mean {mean:.0f}% / {key} {cpu_p:.0f}%, memory {key} {mem_p:.0f}%: busy enough, keep as is.")

    # ---- step 4 + 5: capacity vetoes and patterns (shrink candidates only) -------------------------
    std, mean_mem = f["mem_std"], f["mean_mem"]
    reserved = mean_mem >= e.t("reserved_mem_min_pct") and std < e.t("reserved_mem_max_std")
    if tr.add("pattern.reserved_memory", "memory flat ≥ 75% with std < 0.75", round(std, 2), e.t("reserved_mem_max_std"),
              "flag" if reserved else "pass") == "flag":
        tr.terminal()
        return Outcome("flag", "RESERVED_MEMORY",
                       f"Memory is flat at {mean_mem:.0f}% (std {std:.2f}): reserved (JVM heap?), not proven used. "
                       f"Verify before any RAM cut.", naive=None)
    for metric, thr_key, code, signal, msg in (
            ("mem", "veto_mem_p99_pct", "VETO_MEMORY", "memory", "memory-bound"),
            ("iops_pct", "veto_iops_p95_pct", "VETO_IOPS", "iops", "disk-bound"),
            ("net_pct", "veto_net_p95_pct", "VETO_NETWORK", "network", "network is the workload")):
        q = "p99" if metric == "mem" else "p95"
        val, thr = m[metric][q], e.t(thr_key)
        if tr.add(f"veto.{signal}", f"{metric} {q} ≤ {thr:.0f}", val, thr,
                  "fail" if val is not None and val > thr else "pass") == "fail":
            return reject(code, veto(signal, f"{metric}_{q}", val, thr, ">", msg),
                          f"{metric} {q} is {val:.0f}% (> {thr:.0f}%): {msg}. CPU mean {mean:.0f}% looks idle, "
                          f"but shrinking would starve {signal}.")
    t = f["trend"]["cpu"]
    growing = (t["slope"] is not None and t["slope"] >= e.t("growth_min_slope") and (t["r2"] or 0) >= e.t("growth_min_r2")
               and t["days_to_85"] is not None and t["days_to_85"] < e.t("growth_days_to_85"))
    if tr.add("veto.growth", "CPU days_to_85 ≥ 60", t["days_to_85"], e.t("growth_days_to_85"),
              "fail" if growing else "pass") == "fail":
        return reject("VETO_GROWTH", veto("growth", "cpu_days_to_85", t["days_to_85"], e.t("growth_days_to_85"), "<",
                                          "growing toward capacity"),
                      f"CPU p95 rises {t['slope']:.2f} points/day and reaches 85% in {t['days_to_85']:.0f} days.")
    phc = f["peak_hours_coverage"]
    under_obs = phc is not None and phc < e.t("peak_window_min_coverage")
    if tr.add("pattern.peak_under_observed", "peak-hours coverage ≥ 50%", phc, e.t("peak_window_min_coverage"),
              "flag" if under_obs else "pass") == "flag":
        tr.terminal()
        return Outcome("flag", "PEAK_UNDER_OBSERVED",
                       f"Only {phc:.0%} of the peak hours were observed: the busiest window is under-observed, so "
                       f"no sizing until it is monitored.")
    rec = f["recurring_peak"]
    if tr.add("veto.recurring_peak", "no recurring peak with CPU p99 ≥ 80", p99, e.t("recurring_peak_pct"),
              "fail" if rec and p99 >= e.t("recurring_peak_pct") else "pass") == "fail":
        when = peak_when(rec["buckets"])
        kept = Outcome("reject", "VETO_RECURRING_PEAK",
                       f"Mean CPU {mean:.0f}% but p99 {p99:.0f}%: a peak recurs at {when} IST in {rec['weeks']} weeks. "
                       f"An average-based tool would cut this; we keep it.",
                       veto=veto("recurring_peak", "cpu_p99", p99, e.t("recurring_peak_pct"), ">=",
                                 f"recurring peak at {when} IST"), naive=naive, recurring=rec)
        # A recurring peak forbids SHRINKING, not scheduling around it: a non-prod VM still gets its off-hours
        # schedule, which by construction keeps the peak window on (same rule as engine/pipeline.py _finalise).
        return candidates(e, rid, row, f, cur, cpu, mem, prod, key, cpu_p, mem_p, naive, tr,
                          resize_blocked=kept, peak_note=f"the recurring peak at {when} IST blocks resizing only")
    excl = f["p99_excl_top_day"]
    if tr.add("pattern.one_off_peak", "p99 ≥ 80 but < 40 without the busiest day", excl, e.t("one_off_excl_max_pct"),
              "flag" if p99 >= e.t("one_off_p99_pct") and excl is not None and excl < e.t("one_off_excl_max_pct")
              else "pass") == "flag":
        tr.terminal()
        return Outcome("flag", "ONE_OFF_PEAK",
                       f"CPU p99 {p99:.0f}% comes from one day ({e.day_label(f['top_day'])}); without it p99 is {excl:.0f}%. "
                       f"One event is not a pattern: may be a month-end job, needs 90 days.")

    return candidates(e, rid, row, f, cur, cpu, mem, prod, key, cpu_p, mem_p, naive, tr)


def upsize(e, rid, row, f, cur, cpu, mem, prod, tr):
    m = f["metrics"]
    need_v, need_r = needs(row["vcpu"], row["ram_gb"], min(m["cpu"]["p99"], 100), m["mem"]["p99"],
                           e.p.cpu_target(prod), e.p.mem_target)
    bigger = [p for p in e.cat if p.price > cur["compute_inr"]]
    fit = next((p for p in bigger if p.vcpu >= need_v and p.ram_gb >= need_r), bigger[-1] if bigger else None)
    if fit is None:
        tr.terminal()
        return Outcome("healthy", "RIGHT_SIZED", "Already the largest plan.")
    a = rp.attempt(cpu, mem, row["vcpu"], row["ram_gb"], fit, e.p.replay_limit(prod), e.p.mem_cap)
    replay = {"limit_minutes_above_90": e.p.replay_limit(prod), "mem_cap_pct": e.p.mem_cap, "attempts": [a],
              "passed": a["passed"], "chosen_plan": fit.plan_id}
    after = fit.price + cur["storage_inr"]
    o = Outcome("upsize", "UNDER_PROVISIONED",
                f"{f['share_cpu_above_90']:.0%} of CPU samples are above 90% (p99 {m['cpu']['p99']:.0f}%). "
                f"{row['plan_id']} → {fit.plan_id} brings the replayed peak to {a['max_cpu_pct']:.0f}%.",
                actions=[action("upsize", f"Resize {row['plan_id']} → {fit.plan_id} in a maintenance window",
                                rollback=f"resize back to {row['plan_id']}")],
                target=e.target_block(fit, cur), default="upsize", replay=replay)
    o.options = build_options(cur["monthly_inr"], {"upsize": (after, f"{format_inr(fit.price)} {fit.plan_id} + "
                                                                     f"{format_inr(cur['storage_inr'])} disk")})
    o.risk = e.risk(row, f, rp.projected_p99(cpu, row["vcpu"], fit), ["upsize"])
    tr.add("step3.decision", "upsize target", fit.plan_id, f"≥ {need_v:.1f} vCPU", "upsize", True)
    return o


def refusal(e, row, f, cur, cpu, mem, prod, key, cpu_p, mem_p, naive, tr):
    """A shrink candidate that ended with no action: say why it was kept (engine/pipeline.py _finalise, main).
    Formula sizing on P; if a cheaper plan passes Peak Replay the VM is simply healthy (not underused).
    Otherwise NO_CHEAPER_PLAN when MEMORY rules out every cheaper plan, else PEAK_REPLAY_FAILED with replay evidence."""
    compute = cur["compute_inr"]
    limit = e.p.replay_limit(prod)
    need_v, need_r = needs(row["vcpu"], row["ram_gb"], cpu_p, mem_p, e.p.cpu_target(prod), e.p.mem_target)
    plan, _ = size(e.cat, row["plan_id"], need_v, need_r, prod)
    tr.add("step7.sizing", f"need {need_v:.2f} vCPU, {need_r:.2f} GB", plan.plan_id if plan else None, row["plan_id"],
           "pass" if plan and plan.price < compute else "fail")
    if plan is not None and plan.price < compute:
        replay, chosen = rp.search(cpu, mem, row["vcpu"], row["ram_gb"], plan, e.cat, compute, limit, e.p.mem_cap)
        tr.add("step8.peak_replay", "minutes CPU > 90% at the new size", replay["attempts"][-1]["minutes_above_90"],
               limit, "pass" if chosen else "fail", terminal=True)
        if chosen is not None:
            return Outcome("healthy", "RIGHT_SIZED",
                           f"CPU {key} {cpu_p:.0f}%, memory {key} {mem_p:.0f}%: not underused (CPU {key} ≥ 40 or memory "
                           f"{key} ≥ 50), and {chosen.plan_id} would pass replay only with no headroom to spare: keep as is.")
        worst = replay["attempts"][0]
        return Outcome("reject", "PEAK_REPLAY_FAILED",
                       f"Sized on {key} {cpu_p:.0f}% the target is {plan.plan_id}, but replaying 30 days shows "
                       f"{worst['minutes_above_90']} min above 90% (limit {limit:.0f}): checked and kept.",
                       veto=veto("replay", "minutes_above_90", worst["minutes_above_90"], limit, ">",
                                 f"replay shows {worst['minutes_above_90']} min > 90%"), naive=naive, replay=replay)
    cheaper = [p for p in e.cat if p.price < compute]
    if not any(p.ram_gb >= need_r for p in cheaper):
        tr.add("step7.memory_blocks", "a cheaper plan has enough RAM", need_r, max((p.ram_gb for p in cheaper), default=0),
               "fail", terminal=True)
        return Outcome("reject", "NO_CHEAPER_PLAN",
                       f"CPU {key} is {cpu_p:.0f}% but memory {key} {mem_p:.0f}% of {row['ram_gb']:.0f} GB needs "
                       f"{need_r:.1f} GB: no cheaper plan satisfies CPU and memory together.",
                       veto=veto("sizing", "needed_ram_gb", need_r, max((p.ram_gb for p in cheaper), default=0), ">",
                                 "no cheaper plan satisfies CPU and memory together"), naive=naive)
    # CPU is the limit: replay what an average-based tool would do (or the next plan down) as the evidence
    probe_id = naive["plan"] if naive["action"] == "resize" else cheaper[-1].plan_id
    probe = next(p for p in e.cat if p.plan_id == probe_id)
    a = rp.attempt(cpu, mem, row["vcpu"], row["ram_gb"], probe, limit, e.p.mem_cap)
    replay = {"limit_minutes_above_90": limit, "mem_cap_pct": e.p.mem_cap, "attempts": [a], "passed": a["passed"],
              "chosen_plan": None}
    tr.add("step8.peak_replay_naive", f"naive cut to {probe_id} (mean CPU)", a["minutes_above_90"], limit,
           "pass" if a["passed"] else "fail", terminal=True)
    return Outcome("reject", "PEAK_REPLAY_FAILED",
                   f"Mean CPU {f['mean_cpu']:.0f}% looks wasteful, but CPU {key} is {cpu_p:.0f}% (p99 "
                   f"{f['metrics']['cpu']['p99']:.0f}%): an average-based tool would move to {probe_id}, and replaying "
                   f"30 days there shows {a['minutes_above_90']} min above 90%. The peaks need the headroom.",
                   veto=veto("replay", "minutes_above_90", a["minutes_above_90"], limit, ">",
                             f"replay shows {a['minutes_above_90']} min > 90%"), naive=naive, replay=replay)


def candidates(e, rid, row, f, cur, cpu, mem, prod, key, cpu_p, mem_p, naive, tr, resize_blocked=None, peak_note=None):
    """Idle, underused (sizing + replay) and off-hours. With `resize_blocked` (a recurring-peak reject) only the
    schedule is considered: if there is one it stands, otherwise the reject is returned."""
    m = f["metrics"]
    t = e.t
    compute, storage = cur["compute_inr"], cur["storage_inr"]
    target, replay, size_note, underused = None, None, None, False
    smallest = index_of(e.cat, row["plan_id"]) == 0

    # ---- IDLE (lines relative to the plan: network % of bandwidth, IOPS % of provisioned) ----------
    net_pct = f["net_pct_mean"]
    iops_pct = m["iops_pct"]["p95"]
    idle = (resize_blocked is None and cpu_p < t("idle_cpu_pct") and mem_p < t("veto_mem_p99_pct")
            and net_pct is not None and net_pct < t("idle_net_pct_bw")
            and iops_pct is not None and iops_pct < t("idle_iops_pct"))
    tr.add("candidate.idle", f"CPU {key} < 5, mem < 70, net < 0.1% bw, IOPS p95 < 1%", round(cpu_p, 2),
           t("idle_cpu_pct"), "match" if idle else "no")
    if idle and prod:
        tr.terminal()
        return Outcome("flag", "IDLE_PROD",
                       f"Idle prod VM (CPU {key} {cpu_p:.1f}%, network {net_pct:.3f}% of bandwidth, IOPS p95 "
                       f"{iops_pct:.2f}% of provisioned): review with the owner, never auto-stopped.")
    if idle:
        stateful = "stateful" in row["tags_list"]
        acts, opts = [], {}
        if stateful:
            gb = used_gb(e.cleaned.series[rid].values["disk_used_pct"], row["disk_gb"])
            snap = snapshot_cost(gb, e.cfg)
            acts.append(action("snapshot", f"Snapshot the {gb} GB disk first (stateful)", rollback="delete the snapshot"))
            acts.append(action("stop", "Stop the VM; delete after 14 days if nobody objects", requires=["snapshot"],
                               rollback="start the VM"))
            opts["snapshot+stop"] = (storage + snap, f"₹0 compute + {format_inr(storage)} disk + {format_inr(snap)} snapshot")
        else:
            acts.append(action("stop", "Stop the VM; snapshot and delete after 14 days if nobody objects",
                               rollback="start the VM"))
            opts["stop"] = (storage, f"₹0 compute + {format_inr(storage)} disk")
        default = key_of([a["type"] for a in acts])
        o = Outcome("recommend", "IDLE",
                    f"Idle for 30 days: CPU {key} {cpu_p:.1f}%, network {net_pct:.3f}% of bandwidth, IOPS p95 "
                    f"{iops_pct:.2f}% of provisioned."
                    + (" Already the smallest plan: stop, never resize." if index_of(e.cat, row["plan_id"]) == 0 else ""),
                    actions=acts, default=default)
        o.options = build_options(cur["monthly_inr"], opts)
        o.risk = e.risk(row, f, None, [a["type"] for a in acts])
        return e.floor(o, cur, tr)

    # ---- UNDERUSED -> sizing + replay --------------------------------------------------------------
    if resize_blocked is None:
        underused = cpu_p < t("underused_cpu_pct") and mem_p < t("underused_mem_pct")
        tr.add("candidate.underused", f"CPU {key} < 40 and mem {key} < 50", round(cpu_p, 2), t("underused_cpu_pct"),
               "match" if underused else "no")
    if underused and not smallest:
        cp, mp, basis = e.group_percentiles(row, key, cpu_p, mem_p)
        need_v, need_r = needs(row["vcpu"], row["ram_gb"], cp, mp, e.p.cpu_target(prod), e.p.mem_target)
        plan, size_note = size(e.cat, row["plan_id"], need_v, need_r, prod)
        if plan is None or plan.price >= compute:
            return refusal(e, row, f, cur, cpu, mem, prod, key, cpu_p, mem_p, naive, tr)
        tr.add("step7.sizing", f"need {need_v:.2f} vCPU, {need_r:.2f} GB{basis}", plan.plan_id, row["plan_id"], "pass")
        replay, chosen = rp.search(cpu, mem, row["vcpu"], row["ram_gb"], plan, e.cat, compute,
                                   e.p.replay_limit(prod), e.p.mem_cap)
        tr.add("step8.peak_replay", "minutes CPU > 90% at the new size", replay["attempts"][-1]["minutes_above_90"],
               e.p.replay_limit(prod), "pass" if chosen else "fail")
        if chosen is None:
            worst = replay["attempts"][0]
            tr.terminal()
            return Outcome("reject", "PEAK_REPLAY_FAILED",
                           f"Sized on {key} {cpu_p:.0f}% the target is {plan.plan_id}, but replaying 30 days at that size "
                           f"shows {worst['minutes_above_90']} min above 90% (limit {e.p.replay_limit(prod):.0f}): checked and kept.",
                           veto=veto("replay", "minutes_above_90", worst["minutes_above_90"], e.p.replay_limit(prod), ">",
                                     f"replay shows {worst['minutes_above_90']} min > 90%"), naive=naive, replay=replay)
        target = chosen

    # ---- OFF-HOURS ---------------------------------------------------------------------------------
    sched, why = None, "prod is never scheduled"
    if not prod:
        if row["optimize_policy"] == "no_schedule" or "keep_running" in row["tags_list"]:
            why = "policy no_schedule / keep_running tag"
        elif e.cfg.get("billing.stopped_vm_billed"):
            why = "stopped_vm_billed: stopping saves nothing"
        else:
            sched, why = make_schedule(f["how_p95_by_week"], t("off_hour_cpu_p95_pct"), t("off_block_min_hours"),
                                       t("off_min_hours_per_week"), e.cfg.tz)
    tr.add("candidate.off_hours", "≥ 40 off-hours/week in blocks ≥ 4 h", sched["off_hours_per_week"] if sched else None,
           t("off_min_hours_per_week"), "match" if sched else f"no ({why})")

    if target is None and sched is None:
        if resize_blocked is not None:
            tr.add("veto.recurring_peak.decision", "no off-hours schedule around the peak", None, None, "reject", True)
            return resize_blocked
        if underused and smallest:
            tr.terminal()
            return Outcome("healthy", "RIGHT_SIZED",
                           f"Already the smallest plan ({row['plan_id']}) and no usable off-hours: nothing to change.")
        return refusal(e, row, f, cur, cpu, mem, prod, key, cpu_p, mem_p, naive, tr)

    acts, opts = [], {}
    if target is not None:
        acts.append(action("resize", f"Resize {row['plan_id']} → {target.plan_id}" +
                           (" in a maintenance window" if prod else ""), rollback=f"resize back to {row['plan_id']}"))
        opts["resize"] = (target.price + storage, f"{format_inr(target.price)} {target.plan_id} + {format_inr(storage)} disk")
    if sched is not None:
        on = sched["on_hours_per_week"]
        acts.append(action("schedule", "Stop/start on the windows: " +
                           "; ".join(f"{w['days']} {w['start']}-{w['end']}" for w in sched["windows"]) + " IST",
                           rollback="remove the schedule"))
        opts["schedule"] = (scheduled_compute(compute, on) + storage,
                            f"{format_inr(compute)} × {on:.0f}/168 + {format_inr(storage)} disk")
        if target is not None:
            opts["resize+schedule"] = (scheduled_compute(target.price, on) + storage,
                                       f"{format_inr(target.price)} {target.plan_id} × {on:.0f}/168 + {format_inr(storage)} disk")
    default = key_of([a["type"] for a in acts])
    code = "UNDERUSED" if target is not None else "OFF_HOURS"
    parts = []
    if target is not None:
        best = replay["attempts"][-1]
        parts.append(f"CPU {key} {cpu_p:.0f}%, memory {key} {mem_p:.0f}% over 30 days; {size_note}. Replayed at "
                     f"{target.plan_id} the peak is {best['max_cpu_pct']:.0f}% CPU, {best['minutes_above_90']} min > 90%.")
    if sched is not None:
        parts.append(f"Quiet {sched['off_hours_per_week']:.0f} h/week (CPU p95 < 5% every week)" +
                     (f"; busy hours kept on: {', '.join(sched['busy_hours_excluded'][:3])}" if sched["busy_hours_excluded"] else "") + ".")
    if peak_note:
        parts.append(f"Not resized: {peak_note}; the schedule keeps that window on.")
    o = Outcome("recommend", code, " ".join(parts), actions=acts, default=default, schedule=sched, replay=replay,
                target=e.target_block(target, cur) if target is not None else None)
    o.options = build_options(cur["monthly_inr"], opts)
    o.risk = e.risk(row, f, rp.projected_p99(cpu, row["vcpu"], target) if target is not None else None,
                    [a["type"] for a in acts])
    return e.floor(o, cur, tr)
