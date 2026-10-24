"""Resource builders and the 7 bulk archetypes (62 VMs)."""
import numpy as np
import pandas as pd

from . import signals
from .config import (DEFAULT_PROVISIONED_IOPS, FITTED, LEGACY_PLANS, N_SLOTS, PLANS, REGION_WEIGHTS,
                     REGIONS, SLOTS_PER_DAY, TEAMS, TZ, fitted)
from .signals import AX, ar1, between, clip, daily, drift, noise_sigma, random_spikes, rng_for, steady, weekly

# Companion-metric coefficients. FIT = from real traces (see fitted_params.json);
# HAND = the original hand-set values, used only inside signals.pinned() for planted scenarios.
HAND = {"mem_coupling": 0.25, "mem_sd": 1.5, "mem_phi": 0.0, "iops_base": 2.0, "k_iops": 0.3, "iops_sigma": 0.3,
        "net_base": 0.5, "k_net": 0.15, "net_sigma": 0.35, "net_out_ratio": 0.6, "net_out_sigma": 0.2}
# Network ABSOLUTE scale is NOT fittable (Bitbrains has no link capacity). Assumption: a VM at 30% CPU
# uses a median 1% of its plan bandwidth. The intercept/slope ratio and the lognormal spread ARE fitted.
NET_MEDIAN_PCT_AT_30_CPU = 1.0


def _k_net():
    return NET_MEDIAN_PCT_AT_30_CPU / (max(fitted("net_base_over_k"), 0.0) + 30.0)


# Archetype-definition caps: real "right-sized" VMs often saturate (Bitbrains p99 median = 100%), which
# would turn a 'healthy' archetype into 'upsize'. Noise and drift are capped ONLY where the archetype
# definition needs it, and the cap is recorded here.
RIGHT_SIZED_P99_CEILING = 88.0
RIGHT_SIZED_DRIFT_CAP = 0.10


def arch_drift(name, default=None):
    """Day-to-day drift fitted on Bitbrains VMs of this archetype (falls back to the fleet value)."""
    a = FITTED.get("archetypes", {}).get(name, {})
    if a.get("usable") and "drift_sd" in a and a["drift_sd"].get("n", 0) >= 30:
        return a["drift_sd"]["p50"]
    return fitted("drift_sd") if default is None else default


def coeffs():
    if signals._DYN["pinned"]:
        return HAND
    return {"mem_coupling": fitted("mem_coupling"), "mem_sd": fitted("mem_noise_sd_pct"),
            "mem_phi": fitted("mem_ar1_phi"),
            "iops_base": max(fitted("iops_base_alibaba", 2.0), 0.0), "k_iops": max(fitted("iops_k_alibaba", 0.3), 0.0),
            "iops_sigma": fitted("iops_lognorm_sigma"),
            "net_base": max(fitted("net_base_over_k"), 0.0) * _k_net(), "k_net": _k_net(),
            "net_sigma": fitted("net_lognorm_sigma"), "net_out_ratio": fitted("net_out_in_ratio"),
            "net_out_sigma": HAND["net_out_sigma"]}

OLD_START = pd.Timestamp("2026-01-20", tz=TZ)
OLD_END = pd.Timestamp("2026-04-20", tz=TZ)


def plan_specs(plan):
    if plan in PLANS:
        vcpu, ram, price, bw, _ = PLANS[plan]
    else:
        vcpu, ram, price, bw = LEGACY_PLANS[plan]
    return vcpu, ram, price, bw


def random_date(rng, start, end):
    span = int((end - start) / pd.Timedelta("1h"))
    return start + pd.Timedelta(hours=int(rng.integers(0, span)))


def iso(ts):
    return "" if ts is None or ts == "" else pd.Timestamp(ts).isoformat()


def truth(archetype, edge_case="", verdict="", reason="", action="", notes=""):
    return {"archetype": archetype, "edge_case_id": edge_case, "expected_verdict": verdict,
            "expected_reason_code": reason, "expected_action": action, "notes": notes}


def make_vm(name, *, env, team, plan, purpose, cpu, rng, region=None,
            mem=None, mem_base=20.0, mem_coupling=None, mem_sd=None,
            iops_pct=None, iops_base=None, k_iops=None,
            net_pct=None, net_base=None, k_net=None, net_out=None,
            disk_start=None, disk_slope=0.0, disk_gb=None, prov_iops=DEFAULT_PROVISIONED_IOPS,
            tags=(), policy="default", service_group="", created_at=None, state="running",
            stopped_since=None, last_resized_at=None, previous_plan_id="", owner_team=None,
            active=(0, N_SLOTS), has_metrics=True, auto_created=False, faults=(), t=None):
    vcpu, ram, _, bw = plan_specs(plan)
    n = AX.n
    region = region or rng.choice(REGIONS, p=REGION_WEIGHTS)
    disk_gb = disk_gb or int(rng.choice([50, 80, 100, 150, 200]))
    if created_at is None and not auto_created:
        created_at = random_date(rng, OLD_START, OLD_END)

    metrics = None
    if has_metrics:
        c = coeffs()
        mem_coupling = c["mem_coupling"] if mem_coupling is None else mem_coupling
        mem_sd = c["mem_sd"] if mem_sd is None else mem_sd
        iops_base = c["iops_base"] if iops_base is None else iops_base
        k_iops = c["k_iops"] if k_iops is None else k_iops
        net_base = c["net_base"] if net_base is None else net_base
        k_net = c["k_net"] if k_net is None else k_net
        cpu = clip(cpu)
        if mem is None:
            noise = ar1(rng, mem_sd, phi=c["mem_phi"]) if c["mem_phi"] > 0 else rng.normal(0, mem_sd, n)
            mem = mem_base + mem_coupling * cpu + noise
        mem = clip(mem)
        if iops_pct is None:
            iops_pct = (iops_base + k_iops * cpu) * rng.lognormal(0, c["iops_sigma"], n)
        iops = prov_iops * clip(iops_pct) / 100
        if net_pct is None:
            net_pct = (net_base + k_net * cpu) * rng.lognormal(0, c["net_sigma"], n)
        net_in = bw * clip(net_pct) / 100
        if net_out is None:
            net_out = net_in * c["net_out_ratio"] * rng.lognormal(0, c["net_out_sigma"], n)
        start = disk_start if disk_start is not None else rng.uniform(20, 60)
        disk = clip(start + disk_slope * AX.day_frac + rng.normal(0, 0.05, n))
        metrics = {"cpu_pct": cpu, "mem_pct": mem, "disk_used_pct": disk, "iops": iops,
                   "net_in_mbps": net_in, "net_out_mbps": net_out}

    inv = {
        "name": name, "type": "vm", "region": region, "env": env,
        "owner_team": team if owner_team is None else owner_team, "purpose": purpose,
        "service_group": service_group, "plan_id": plan, "previous_plan_id": previous_plan_id,
        "vcpu": vcpu, "ram_gb": ram, "disk_gb": disk_gb, "provisioned_iops": prov_iops,
        "bandwidth_mbps": bw, "state": state, "stopped_since": iso(stopped_since),
        "created_at": created_at, "last_resized_at": iso(last_resized_at), "attached_to": "",
        "unattached_since": "", "optimize_policy": policy, "tags": ";".join(tags),
    }
    return {"inv": inv, "metrics": metrics, "active": active, "faults": list(faults),
            "truth": t or truth("planted"), "auto_created": auto_created, "team": team}


def make_volume(name, *, env, team, size_gb, attached_to="", unattached_since=None, created_at=None,
                region=None, used_pct=30.0, used_slope=0.0, iops_pct=None, tags=(), t=None):
    rng = rng_for(name)
    region = region or rng.choice(REGIONS, p=REGION_WEIGHTS)
    if created_at is None:
        created_at = random_date(rng, OLD_START, OLD_END)
    n = AX.n
    if iops_pct is None:
        iops_pct = np.zeros(n)
    used = clip(used_pct + used_slope * AX.day_frac + rng.normal(0, 0.03, n))
    metrics = {"iops": DEFAULT_PROVISIONED_IOPS * clip(iops_pct) / 100, "disk_used_pct": used}
    inv = {
        "name": name, "type": "volume", "region": region, "env": env, "owner_team": team,
        "purpose": "storage", "service_group": "", "plan_id": "", "previous_plan_id": "",
        "vcpu": "", "ram_gb": "", "disk_gb": size_gb, "provisioned_iops": DEFAULT_PROVISIONED_IOPS,
        "bandwidth_mbps": "", "state": "attached" if attached_to else "unattached", "stopped_since": "",
        "created_at": created_at, "last_resized_at": "", "attached_to": attached_to,
        "unattached_since": iso(unattached_since), "optimize_policy": "default", "tags": ";".join(tags),
    }
    return {"inv": inv, "metrics": metrics, "active": (0, N_SLOTS), "faults": [],
            "truth": t or truth("planted"), "auto_created": False, "team": team}


def make_ip(name, *, env, team, attached_to="", unattached_since=None, created_at=None, region=None,
            tags=(), t=None):
    rng = rng_for(name)
    region = region or rng.choice(REGIONS, p=REGION_WEIGHTS)
    if created_at is None:
        created_at = random_date(rng, OLD_START, OLD_END)
    inv = {
        "name": name, "type": "ip", "region": region, "env": env, "owner_team": team,
        "purpose": "public_ip", "service_group": "", "plan_id": "", "previous_plan_id": "",
        "vcpu": "", "ram_gb": "", "disk_gb": "", "provisioned_iops": "", "bandwidth_mbps": "",
        "state": "associated" if attached_to else "unassociated", "stopped_since": "",
        "created_at": created_at, "last_resized_at": "", "attached_to": attached_to,
        "unattached_since": iso(unattached_since), "optimize_policy": "default", "tags": ";".join(tags),
    }
    return {"inv": inv, "metrics": None, "active": (0, N_SLOTS), "faults": [],
            "truth": t or truth("planted"), "auto_created": False, "team": team}


# ---------------------------------------------------------------- bulk archetypes

GROWTH_DAY = 22   # 2026-10-12: growth team launches 4 new dev VMs (team cost-jump alert, short history)


def arch_range(name, stat, clip_lo, clip_hi, fallback):
    """Fitted p10..p90 of `stat` for archetype `name` (real VMs classified with the same rules),
    intersected with [clip_lo, clip_hi] so the truth label stays valid. Falls back to the hand-set
    range when fewer than 30 real VMs matched (flagged in fitted_params.json)."""
    a = FITTED.get("archetypes", {}).get(name, {})
    if not a.get("usable") or stat not in a:
        return fallback
    lo, hi = max(a[stat]["p10"], clip_lo), min(a[stat]["p90"], clip_hi)
    return (lo, hi) if lo < hi else fallback


def sample_real(r, name, keep):
    """Resample one real VM's parameter tuple for archetype `name` (Bitbrains/Azure members), keeping only
    tuples that satisfy `keep` (the archetype definition behind its truth label). None if unavailable."""
    rows = [x for x in FITTED.get("archetypes", {}).get(name, {}).get("samples", []) if keep(x)]
    return rows[int(r.integers(0, len(rows)))] if rows else None


def resampled_cpu(r, name, row, fallback_wk, drift_cap=None, sigma_cap=None):
    """steady() driven by a real VM's (trough, peak, sigma, drift, weekend factor). Azure tuples carry no
    drift/weekend (timestamps not day-aligned): those fall back to the archetype's Bitbrains median."""
    sigma = row["sigma"] if sigma_cap is None else min(row["sigma"], sigma_cap)
    d = row["drift_sd"] if row["drift_sd"] is not None else arch_drift(name)
    d = d if drift_cap is None else min(d, drift_cap)
    wk = row["weekend_factor"] if row["weekend_factor"] is not None else fallback_wk
    return steady(r, row["trough"], row["peak"] - row["trough"], weekend=1.0, sigma=max(sigma, 0.05),
                  drift_sd=d) * weekly(wk)


def bulk_vms():
    specs = []
    counter = {"n": 30}

    def nm(env, service):
        counter["n"] += 1
        return f"{env}-{service}-{counter['n']}"

    def pick(rng, items):
        return items[int(rng.integers(0, len(items)))]

    wk_inter = fitted("weekend_factor_interactive")
    wk_all = fitted("weekend_factor_all", wk_inter)

    # right_sized_prod (15): trough/peak fitted from real interactive VMs; 4 of them have a disk filling up.
    # Clip: peak <= 80 keeps p99 < 90 (healthy, not upsize); trough >= 15 keeps p99 >= 40 (not underused).
    for i in range(15):
        name = nm("prod", ["web", "api", "search", "checkout"][i % 4])
        r = rng_for(name)
        # mean >= 22 keeps the synthetic VM busy on average (>= 20%, so it never 'looks wasteful'), as the
        # 'right-sized / healthy' label requires; found by the engine (prod-checkout-34 resampled to 19.3%)
        row = sample_real(r, "right_sized_prod",
                          lambda x: x["trough"] >= 15 and x["peak"] <= 65 and x["peak"] - x["trough"] >= 10
                          and x["mean"] >= 22)
        if row:
            base, peak = row["trough"], row["peak"]
            cpu = resampled_cpu(r, "right_sized_prod", row, wk_inter, drift_cap=RIGHT_SIZED_DRIFT_CAP,
                                sigma_cap=(RIGHT_SIZED_P99_CEILING - peak) / 2.5)
        else:
            base = r.uniform(20, 30)
            peak = base + r.uniform(20, 35)
            cpu = steady(r, base, peak - base, weekend=1.0, sigma=min(noise_sigma((base + peak) / 2),
                         (RIGHT_SIZED_P99_CEILING - peak) / 2.5), drift_sd=RIGHT_SIZED_DRIFT_CAP) * weekly(wk_inter)
        # unscheduled 1-slot spikes: rate and height (in MADs above the median) fitted on Azure VMs
        # classified as right-sized; capped below the archetype's p99 ceiling
        sp = FITTED["archetypes"]["right_sized_prod"]
        med = float(np.median(cpu))
        mad = float(np.median(np.abs(cpu - med)))
        k = r.poisson(sp["spikes_per_day"]["p50"] * AX.n / SLOTS_PER_DAY)
        at = r.integers(0, AX.n, k)
        cpu[at] = np.maximum(cpu[at], np.minimum(med + r.uniform(sp["spike_excess_mad"]["p25"],
                                                                 sp["spike_excess_mad"]["p75"], k) * mad,
                                                 RIGHT_SIZED_P99_CEILING))
        filling = i < 4
        specs.append(make_vm(
            name, env="prod", team=pick(r, TEAMS), plan=pick(r, ["B2", "B3", "B4"]), purpose="web",
            cpu=cpu, rng=r, mem_base=r.uniform(30, 50),
            disk_start=r.uniform(60, 65) if filling else None, disk_slope=0.8 if filling else 0.0,
            auto_created=True,
            t=truth("right_sized_prod", "A1-bulk" if not filling else "G5-disk", "healthy", "RIGHT_SIZED",
                    "none", "disk filling 0.8%/day -> capacity alert" if filling else "")))

    # steady_low (12): flat and low; level fitted. Clip <= 11 keeps p95 < 40 after noise (resize).
    envs = ["prod"] * 6 + ["staging"] * 3 + ["dev"] * 3
    for env in envs:
        name = nm(env, "svc")
        r = rng_for(name)
        # p95 >= 6 keeps it out of 'idle' territory so its truth (resize) holds
        row = sample_real(r, "steady_low", lambda x: x["p95"] >= 6 and x["mean"] <= 11)
        if row:
            cpu = resampled_cpu(r, "steady_low", row, wk_all)
        else:
            cpu = steady(r, r.uniform(5, 10), r.uniform(1, 3), weekend=wk_all, drift_sd=arch_drift("steady_low"))
        specs.append(make_vm(
            name, env=env, team=pick(r, TEAMS), plan=pick(r, ["B3", "B4", "B5"]), purpose="api",
            cpu=cpu, rng=r, mem_base=r.uniform(6, 14), auto_created=True,
            t=truth("steady_low", "A2-bulk", "recommend", "UNDERUSED", "resize",
                    "prod: max one plan step down" if env == "prod" else "")))

    # bursty_daily (7): low base + daily peak 09:00-10:30 (scenario). Base, peak height, drift fitted.
    for env in ["prod"] * 5 + ["staging"] * 2:
        name = nm(env, "burst")
        r = rng_for(name)
        base = r.uniform(*arch_range("bursty_daily", "mean", 5, 12, (8, 12)))
        lo, hi = arch_range("bursty_daily", "p99", 65, 92, (75, 90))
        cpu = steady(r, base, 3, weekend=0.9, drift_sd=arch_drift("bursty_daily"))
        # 90-minute window: real bursty VMs spend > 5% of time at peak (p95/mean median 4.6), so p95 sits in the peak
        peak = between(9.0, 10.5)
        day_peak = r.uniform(lo, hi, AX.day.max() + 1)[AX.day]       # one peak height per day
        cpu[peak] = clip(day_peak + ar1(r, 3.0), 0, 100)[peak]          # fitted AR structure, not white noise
        specs.append(make_vm(
            name, env=env, team=pick(r, TEAMS), plan=pick(r, ["B2", "B3"]), purpose="api",
            cpu=cpu, rng=r, mem_base=r.uniform(15, 30), auto_created=True,
            t=truth("bursty_daily", "A7-bulk", "reject", "VETO_RECURRING_PEAK", "none",
                    "daily 09:00-10:30 peak")))

    # batch_nightly (5): Azure "delay-insensitive" class, idle except 01:00-03:00
    for env in ["prod", "prod", "prod", "staging", "dev"]:
        name = nm(env, "batch")
        r = rng_for(name)
        cpu = 3 + ar1(r, 0.6)
        win = between(1, 3)
        night = r.uniform(85, 93, AX.day.max() + 1)[AX.day]
        cpu[win] = clip(night + ar1(r, 2.0), 0, 100)[win]
        specs.append(make_vm(
            name, env=env, team=pick(r, TEAMS), plan=pick(r, ["B2", "B3"]), purpose="batch",
            cpu=cpu, rng=r, mem_base=r.uniform(15, 30), auto_created=True,
            t=truth("batch_nightly", "A3-bulk", "reject", "VETO_RECURRING_PEAK", "none",
                    "never schedule off over 01:00-03:00") if env == "prod" else
            truth("batch_nightly", "B5-bulk", "recommend", "OFF_HOURS", "schedule",
                  "non-prod: the nightly peak blocks shrinking, not scheduling; off-window keeps 01:00-03:00 on "
                  "(same case as dev-etl-04)")))

    # office_hours_dev (15): weekdays 09-19 busy, else ~2%. 4 growth-team VMs created on day 22
    for i, env in enumerate(["dev"] * 11 + ["staging"] * 4):
        name = nm(env, "app")
        r = rng_for(name)
        busy = ~AX.weekend & between(9, 19)
        cpu = np.where(busy, 38 * drift(r) + ar1(r, 8.0), 2 + ar1(r, 0.7))
        is_growth = i < 4
        if is_growth:
            created = pd.Timestamp("2026-10-12 11:00", tz=TZ)
            specs.append(make_vm(
                name, env=env, team="growth", plan="B2", purpose="web", cpu=cpu, rng=r,
                mem_base=r.uniform(15, 25), created_at=created,
                active=(GROWTH_DAY * SLOTS_PER_DAY + 132, AX.n),
                t=truth("office_hours_dev", "D1-bulk/G7", "exclude", "HISTORY_TOO_SHORT", "none",
                        "created 2026-10-12 by growth team; drives team cost-jump alert")))
        else:
            specs.append(make_vm(
                name, env=env, team=pick(r, TEAMS), plan=pick(r, ["B1", "B2", "B3"]), purpose="web",
                cpu=cpu, rng=r, mem_base=r.uniform(15, 25), auto_created=True,
                t=truth("office_hours_dev", "B4-bulk", "recommend", "OFF_HOURS", "schedule",
                        "idle weeknights and weekends")))

    # zombie (5): ~1.5% CPU, no network, no IO
    for env in ["dev", "dev", "dev", "staging", "staging"]:
        name = nm(env, "old")
        r = rng_for(name)
        # margin below the idle line (P < 5): low p95, low profile peak, drift within the real zombie IQR
        zd = FITTED.get("archetypes", {}).get("zombie", {}).get("drift_sd", {"p25": 0.0, "p75": 0.25})
        row = sample_real(r, "zombie", lambda x: x["p95"] < 3.5 and x["peak"] < 3.0
                          and (x["drift_sd"] is None or zd["p25"] <= x["drift_sd"] <= zd["p75"]))
        if row:
            cpu = resampled_cpu(r, "zombie", row, wk_all)
        else:
            level = r.uniform(1.0, 2.0)
            cpu = level * drift(r, arch_drift("zombie")) + ar1(r, noise_sigma(level))
        specs.append(make_vm(
            name, env=env, team=pick(r, TEAMS), plan=pick(r, ["S1", "B1", "B2"]), purpose="web",
            cpu=cpu, rng=r, mem_base=r.uniform(8, 15), mem_coupling=0.0,
            iops_base=0.05, k_iops=0.0, net_base=0.0005, k_net=0.0, auto_created=True,
            t=truth("zombie", "B12-bulk", "recommend", "IDLE", "stop", "")))

    # memory_bound (3): CPU ~10%, memory 80-88% (Alibaba: memory stays high when CPU is low)
    for _ in range(3):
        name = nm("prod", "mem")
        r = rng_for(name)
        cpu = steady(r, 8, 5, weekend=0.9, sigma=1.5)
        mlo, mhi = (80, 85)
        mb = FITTED.get("archetypes", {}).get("memory_bound", {})
        if mb.get("usable") and mb.get("mem_mean"):
            mlo, mhi = max(mb["mem_mean"]["p10"], 75), min(mb["mem_mean"]["p90"], 90)
            mlo, mhi = (mlo, mhi) if mlo < mhi else (80, 85)
        mem = r.uniform(mlo, mhi) + ar1(r, fitted("mem_noise_sd_pct"), phi=fitted("mem_ar1_phi"))
        specs.append(make_vm(
            name, env="prod", team=pick(r, TEAMS), plan=pick(r, ["B3", "B4"]), purpose="cache",
            cpu=cpu, rng=r, mem=mem, auto_created=True,
            t=truth("memory_bound", "A9-bulk", "reject", "VETO_MEMORY", "none", "")))

    return specs
