"""Resource builders and the 7 bulk archetypes (62 VMs)."""
import numpy as np
import pandas as pd

from .config import (DEFAULT_PROVISIONED_IOPS, LEGACY_PLANS, N_SLOTS, PLANS, REGION_WEIGHTS,
                     REGIONS, SLOTS_PER_DAY, TEAMS, TZ)
from .signals import AX, ar1, between, clip, daily, drift, rng_for, steady

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
            mem=None, mem_base=20.0, mem_coupling=0.25, mem_sd=1.5,
            iops_pct=None, iops_base=2.0, k_iops=0.3,
            net_pct=None, net_base=0.5, k_net=0.15, net_out=None,
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
        cpu = clip(cpu)
        if mem is None:
            mem = mem_base + mem_coupling * cpu + rng.normal(0, mem_sd, n)
        mem = clip(mem)
        if iops_pct is None:
            iops_pct = (iops_base + k_iops * cpu) * rng.lognormal(0, 0.3, n)
        iops = prov_iops * clip(iops_pct) / 100
        if net_pct is None:
            net_pct = (net_base + k_net * cpu) * rng.lognormal(0, 0.35, n)
        net_in = bw * clip(net_pct) / 100
        if net_out is None:
            net_out = net_in * 0.6 * rng.lognormal(0, 0.2, n)
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


def bulk_vms():
    specs = []
    counter = {"n": 30}

    def nm(env, service):
        counter["n"] += 1
        return f"{env}-{service}-{counter['n']}"

    def pick(rng, items):
        return items[int(rng.integers(0, len(items)))]

    # right_sized_prod (15): Azure "interactive" class; 4 of them have a disk filling up
    for i in range(15):
        name = nm("prod", ["web", "api", "search", "checkout"][i % 4])
        r = rng_for(name)
        cpu = steady(r, r.uniform(20, 30), r.uniform(20, 35), weekend=0.8, sigma=3.0)
        filling = i < 4
        specs.append(make_vm(
            name, env="prod", team=pick(r, TEAMS), plan=pick(r, ["B2", "B3", "B4"]), purpose="web",
            cpu=cpu, rng=r, mem_base=r.uniform(30, 50),
            disk_start=r.uniform(60, 65) if filling else None, disk_slope=0.8 if filling else 0.0,
            auto_created=True,
            t=truth("right_sized_prod", "A1-bulk" if not filling else "G5-disk", "healthy", "RIGHT_SIZED",
                    "none", "disk filling 0.8%/day -> capacity alert" if filling else "")))

    # steady_low (12): over-provisioned, flat and low (Google 2011: usage far below allocation)
    envs = ["prod"] * 6 + ["staging"] * 3 + ["dev"] * 3
    for env in envs:
        name = nm(env, "svc")
        r = rng_for(name)
        cpu = steady(r, r.uniform(5, 10), r.uniform(2, 4), weekend=0.9, sigma=1.5)
        specs.append(make_vm(
            name, env=env, team=pick(r, TEAMS), plan=pick(r, ["B3", "B4", "B5"]), purpose="api",
            cpu=cpu, rng=r, mem_base=r.uniform(6, 14), auto_created=True,
            t=truth("steady_low", "A2-bulk", "recommend", "UNDERUSED", "resize",
                    "prod: max one plan step down" if env == "prod" else "")))

    # bursty_daily (7): low base, short daily peak 09:30-10:15 (trap for average-based tools)
    for env in ["prod"] * 5 + ["staging"] * 2:
        name = nm(env, "burst")
        r = rng_for(name)
        cpu = steady(r, 10, 3, weekend=0.9, sigma=2.0)
        peak = between(9.5, 10.25)
        cpu[peak] = r.uniform(75, 90, peak.sum())
        specs.append(make_vm(
            name, env=env, team=pick(r, TEAMS), plan=pick(r, ["B2", "B3"]), purpose="api",
            cpu=cpu, rng=r, mem_base=r.uniform(15, 30), auto_created=True,
            t=truth("bursty_daily", "A7-bulk", "reject", "VETO_RECURRING_PEAK", "none",
                    "daily 09:30-10:15 peak at 75-90%")))

    # batch_nightly (5): Azure "delay-insensitive" class, idle except 01:00-03:00
    for env in ["prod", "prod", "prod", "staging", "dev"]:
        name = nm(env, "batch")
        r = rng_for(name)
        cpu = 3 + ar1(r, 0.6)
        win = between(1, 3)
        cpu[win] = r.uniform(85, 95, win.sum())
        specs.append(make_vm(
            name, env=env, team=pick(r, TEAMS), plan=pick(r, ["B2", "B3"]), purpose="batch",
            cpu=cpu, rng=r, mem_base=r.uniform(15, 30), auto_created=True,
            t=truth("batch_nightly", "A3-bulk", "reject", "VETO_RECURRING_PEAK", "none",
                    "never schedule off over 01:00-03:00")))

    # office_hours_dev (15): weekdays 09-19 busy, else ~2%. 4 growth-team VMs created on day 22
    for i, env in enumerate(["dev"] * 11 + ["staging"] * 4):
        name = nm(env, "app")
        r = rng_for(name)
        busy = ~AX.weekend & between(9, 19)
        cpu = np.where(busy, r.normal(38, 8, AX.n) * drift(r), r.normal(2, 0.7, AX.n))
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
        cpu = 1.5 + ar1(r, 0.4)
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
        mem = r.uniform(80, 85) + r.normal(0, 1.2, AX.n)
        specs.append(make_vm(
            name, env="prod", team=pick(r, TEAMS), plan=pick(r, ["B3", "B4"]), purpose="cache",
            cpu=cpu, rng=r, mem=mem, auto_created=True,
            t=truth("memory_bound", "A9-bulk", "reject", "VETO_MEMORY", "none", "")))

    return specs
