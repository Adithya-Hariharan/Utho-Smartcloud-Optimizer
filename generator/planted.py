"""Planted resources: one per edge case in PLAN.md section 8, each with a known right answer."""
import numpy as np
import pandas as pd

from .archetypes import make_ip, make_vm, make_volume, truth
from .config import N_SLOTS, SLOTS_PER_DAY, TZ
from .signals import AX, ar1, between, clip, daily, drift, pinned, random_spikes, rng_for, steady, weekly

# Planted resources that keep the ORIGINAL hand-set dynamics (phi 0.8, drift 0.05, hand companion
# coefficients). Each one is listed because the fitted dynamics break its edge-case target;
# reasons are in PIN_REASONS and in data/DATASET.md. Every other planted VM uses fitted dynamics.
PINNED = {
    "prod-api-01": "A1 needs p95 in 60-80; fitted noise (sigma ~17 at 40% CPU) pushes p95 to ~98",
    "prod-api-07": "A2 needs p99 ~31% for the B4->B3 example; fitted day drift (0.59) pushes p99 to ~65",
    "dev-report-02": "A5 needs p99 < 30 so that ONLY Peak Replay catches the weekly job; fitted drift lifts p99 to ~39",
    "prod-reports-02": "A6 needs p99-without-top-day < 40 to isolate the single event; fitted drift lifts it to ~53",
    "prod-cache-04": "A9 needs CPU p99 < 10 so memory is the only binding signal; fitted noise lifts it to ~15",
    "prod-gateway-03": "A14 needs CPU p99 < 10 so network is the only signal; fitted noise lifts it to ~10.5",
    "prod-ml-10": "A18 needs CPU p99 < 15 and mem p99 37.5-50; fitted noise lifts CPU p99 to ~25",
    "staging-web-08": "A20 needs p95 27-33 (exactly ~3 vCPU of 8); fitted drift lifts p95 to ~39",
}
PIN_REASONS = PINNED


def ts(s):
    return pd.Timestamp(s, tz=TZ)


def day_slot(day, hour=0.0):
    return int(day * SLOTS_PER_DAY + hour * 12)


def office(r, busy_level=38.0, busy_sd=6.0, idle=2.0, start=9, end=19):
    busy = ~AX.weekend & between(start, end)
    return np.where(busy, r.normal(busy_level, busy_sd, AX.n) * drift(r), idle + ar1(r, 0.5))


def idle_cpu(r, level=1.0, sd=0.3):
    return level + ar1(r, sd)


IDLE_IO = dict(iops_base=0.05, k_iops=0.0, net_base=0.0005, k_net=0.0)


def planted_vms():
    S = []

    def add(name, cpu_fn, **kw):
        def build():
            r = rng_for(name)
            cpu = cpu_fn(r) if cpu_fn else np.zeros(AX.n)
            for key in ("mem", "iops_pct", "net_pct", "net_out"):
                if callable(kw.get(key)):
                    kw[key] = kw[key](r, clip(cpu))
            return make_vm(name, cpu=cpu, rng=r, **kw)
        if name in PINNED:
            with pinned():
                S.append(build())
        else:
            S.append(build())

    # ---------------- A. Workload shape and peak behaviour
    add("prod-api-01", lambda r: steady(r, 30, 45, 0.85, 3.0),
        env="prod", team="platform", region="mumbai", plan="B4", purpose="api", mem_base=45,
        t=truth("planted", "A1", "healthy", "RIGHT_SIZED", "none", "p95 ~70%: must be left alone"))

    add("prod-api-07", lambda r: steady(r, 12, 15, 0.85, 2.0),
        env="prod", team="payments", region="bangalore", plan="B4", purpose="api", mem_base=9,
        t=truth("planted", "A2", "recommend", "UNDERUSED", "resize",
                "CPU p99 ~31%, mem ~15%: formula says B2, prod one-step rule gives B4->B3"))

    def batch07(r):
        cpu = steady(r, 5.5, 0, sigma=1.0)
        w = between(2, 2 + 40 / 60)
        cpu[w] = r.uniform(90, 94, w.sum())
        return cpu
    add("prod-batch-07", batch07, env="prod", team="data", region="noida", plan="B3", purpose="batch",
        mem_base=22, t=truth("planted", "A3", "reject", "VETO_RECURRING_PEAK", "none",
                             "mean ~8%, p99 ~92% in a 40-min window at 02:00 every night"))

    def billing01(r):
        cpu = steady(r, 4, 0, sigma=1.0)
        w = (AX.dow == 6) & between(9, 12)
        cpu[w] = r.uniform(88, 92, w.sum())
        return cpu
    add("prod-billing-01", billing01, env="prod", team="payments", region="mumbai", plan="B3",
        purpose="batch", mem_base=20,
        t=truth("planted", "A4", "reject", "VETO_RECURRING_PEAK", "none",
                "idle 6 days, 90% every Sunday 09:00-12:00 (5 Sundays in window)"))

    def report02(r):
        cpu = steady(r, 9, 12, 0.5, 1.5)
        w = (AX.dow == 2) & between(15, 16)
        cpu[w] = r.uniform(94, 97, w.sum())
        return cpu
    add("dev-report-02", report02, env="dev", team="data", region="bangalore", plan="B2", purpose="report",
        mem_base=15, t=truth("planted", "A5", "reject", "PEAK_REPLAY_FAILED", "none",
                             "p99 ~22% misses a weekly 1-hour job at 95% (Wed 15:00); replay on B1 fails"))

    def reports02(r):
        cpu = steady(r, 12, 10, 0.85, 2.0)
        w = (AX.day == 11) & between(8, 16)
        cpu[w] = r.uniform(93, 97, w.sum())
        return cpu
    add("prod-reports-02", reports02, env="prod", team="data", region="mumbai", plan="B3", purpose="report",
        mem_base=25, t=truth("planted", "A6", "flag", "ONE_OFF_PEAK", "none",
                             "single 8-hour 95% spike on 2026-10-01; p99 without that day is low"))

    def checkout03(r):
        cpu = steady(r, 11, 0, sigma=2.0)
        w = between(10, 11)
        cpu[w] = r.uniform(84, 89, w.sum())
        return cpu
    add("prod-checkout-03", checkout03, env="prod", team="payments", region="mumbai", plan="B2",
        purpose="checkout", mem_base=25,
        t=truth("planted", "A7", "reject", "VETO_RECURRING_PEAK", "none",
                "average ~14%, p99 ~86% at 10:00 daily"))

    add("prod-queue-02", lambda r: np.maximum(steady(r, 10, 0, sigma=2.0), random_spikes(r, 4)),
        env="prod", team="platform", region="bangalore", plan="B2", purpose="queue", mem_base=25,
        t=truth("planted", "A8", "reject", "PEAK_REPLAY_FAILED", "none",
                "unscheduled spikes 10->80% several times a day (no schedule)"))

    add("prod-cache-04", lambda r: steady(r, 4, 2, 0.9, 0.8),
        env="prod", team="platform", region="mumbai", plan="B4", purpose="cache",
        mem=lambda r, c: 83 + 0.1 * c + r.normal(0, 1.2, AX.n),
        t=truth("planted", "A9", "reject", "VETO_MEMORY", "none", "CPU ~5%, memory p99 ~85%"))

    add("prod-search-06", lambda r: steady(r, 10, 15, 0.85, 2.0),
        env="prod", team="search", region="bangalore", plan="B4", purpose="search",
        mem=lambda r, c: 78 + r.normal(0, 0.5, AX.n),
        t=truth("planted", "A10", "flag", "RESERVED_MEMORY", "none",
                "memory flat at 78% (JVM heap reserved), std < 1"))

    def sawtooth(r, c):
        phase = ((AX.day_frac + 1.5) % 7.5) / 7.5
        return 40 + 45 * phase + r.normal(0, 0.8, AX.n)
    add("prod-orders-08", lambda r: steady(r, 15, 20, 0.85, 2.0),
        env="prod", team="payments", region="noida", plan="B3", purpose="api", mem=sawtooth,
        t=truth("planted", "A11", "reject", "VETO_LEAK", "none",
                "memory climbs 40->85% over 7.5 days then drops (restart): 4 cycles; leak check runs before memory veto"))

    add("prod-db-01", lambda r: steady(r, 9, 8, 0.85, 1.5),
        env="prod", team="payments", region="mumbai", plan="B4", purpose="db", mem_base=60,
        prov_iops=6000, tags=("stateful",),
        iops_pct=lambda r, c: 72 + 22 * daily() * weekly(0.9) + r.normal(0, 3, AX.n),
        t=truth("planted", "A12", "exclude", "STATEFUL_PROD", "none", "CPU ~12%, IOPS saturated; stateful"))

    add("prod-ingest-09", lambda r: steady(r, 12, 8, 0.9, 2.0),
        env="prod", team="data", region="bangalore", plan="B3", purpose="ingest", mem_base=25,
        iops_pct=lambda r, c: 70 + 20 * daily() + r.normal(0, 3, AX.n),
        t=truth("planted", "A13", "reject", "VETO_IOPS", "none", "stateless but disk-bound: IOPS p95 ~90%"))

    add("prod-gateway-03", lambda r: steady(r, 3.5, 2, 0.9, 0.8),
        env="prod", team="platform", region="mumbai", plan="B2", purpose="gateway", mem_base=20,
        net_pct=lambda r, c: 60 + 18 * daily() * weekly(0.9) + r.normal(0, 3, AX.n),
        t=truth("planted", "A14", "reject", "VETO_NETWORK", "none", "CPU ~4% but network p95 > 60% of bandwidth"))

    def growth04(r):
        level = 20 + 45 * AX.day_frac / 30
        return level * (0.75 + 0.35 * daily()) * drift(r) + ar1(r, 2.0)
    add("prod-api-04", growth04, env="prod", team="growth", region="bangalore", plan="B3", purpose="api",
        mem_base=30, t=truth("planted", "A15", "healthy", "RIGHT_SIZED", "none",
                             "CPU climbs 20->65% over 30 days: capacity-trend alert expected"))

    add("prod-search-02", lambda r: steady(r, 72, 25, 0.9, 3.0),
        env="prod", team="search", region="mumbai", plan="B2", purpose="search", mem_base=40,
        t=truth("planted", "A16", "upsize", "UNDER_PROVISIONED", "upsize", "CPU p99 > 90%"))

    def legacy06(r):
        cpu = steady(r, 35, 25, 0.85, 2.0)
        quiet = AX.day >= 22
        cpu[quiet] = (1.5 + ar1(r, 0.4))[quiet]
        return cpu
    add("prod-legacy-06", legacy06, env="prod", team="platform", region="noida", plan="B3",
        purpose="api", mem=lambda r, c: np.where(AX.day >= 22, 12, 45) + 0.2 * c + r.normal(0, 1, AX.n),
        t=truth("planted", "A17", "flag", "WENT_QUIET", "none", "busy until 2026-10-12, near zero for the last 8 days"))

    add("prod-ml-10", lambda r: steady(r, 7, 3, 0.9, 1.0),
        env="prod", team="data", region="bangalore", plan="B4", purpose="ml",
        mem=lambda r, c: 40 + 0.25 * c + r.normal(0, 1.2, AX.n),
        t=truth("planted", "A18", "reject", "NO_CHEAPER_PLAN", "none",
                "CPU ~8% but memory p99 ~45% of 32 GB needs > 16 GB: no cheaper plan fits both"))

    add("dev-tiny-14", lambda r: idle_cpu(r, 2, 0.5),
        env="dev", team="mobile", region="noida", plan="S1", purpose="test", mem_base=15, mem_coupling=0,
        **IDLE_IO, t=truth("planted", "A19", "recommend", "IDLE", "stop",
                           "already the smallest plan: stop, never resize"))

    add("staging-web-08", lambda r: steady(r, 12, 19, 0.85, 1.5),
        env="staging", team="growth", region="mumbai", plan="B4", purpose="web", mem_base=8, mem_coupling=0.2,
        t=truth("planted", "A20", "recommend", "UNDERUSED", "resize",
                "needs ~3 vCPU: catalogue has 2 or 4, round UP to B2 (4 vCPU)"))

    def ratelimited(r):
        cpu = np.minimum(12 + ar1(r, 2.0), 30)
        cpu[~AX.weekend & between(10, 18)] = 40.0
        return cpu
    add("staging-api-09", ratelimited, env="staging", team="search", region="bangalore", plan="B3",
        purpose="api", mem_base=20, mem_coupling=0.1,
        t=truth("planted", "A21", "healthy", "RIGHT_SIZED", "none",
                "rate-limited at exactly 40.00% in business hours: p95 = 40.0 is NOT < 40"))

    add("dev-tiny-15", lambda r: office(r, 30, 6, 1.5),
        env="dev", team="mobile", region="mumbai", plan="S1", purpose="web", mem_base=20,
        t=truth("planted", "A22", "healthy", "BELOW_FLOOR", "none",
                "schedule would save ~Rs 495/month (< Rs 500 floor); S1 cannot shrink"))

    for suffix, base, amp in (("a", 8, 12), ("b", 10, 16), ("c", 8, 11)):
        add(f"prod-web-11{suffix}", lambda r, b=base, a=amp: steady(r, b, a, 0.85, 1.5),
            env="prod", team="growth", region="mumbai", plan="B3", purpose="web", mem_base=12,
            service_group="web-frontend",
            t=truth("planted", "A23", "recommend", "UNDERUSED", "resize",
                    "one group recommendation, sized on the busiest member (11b)"))

    for i in (1, 2, 3):
        add(f"prod-k8s-node-{i}", lambda r: steady(r, 15, 20, 0.85, 3.0),
            env="prod", team="platform", region="bangalore", plan="B4", purpose="k8s-node", mem_base=35,
            tags=("autoscaled",), t=truth("planted", "A24", "exclude", "TAG_AUTOSCALED", "none",
                                          "rightsize the node pool, not the node"))

    add("prod-checkout-01", lambda r: steady(r, 8, 10, 0.85, 1.5),
        env="prod", team="payments", region="mumbai", plan="B4", purpose="checkout", mem_base=15,
        tags=("seasonal_peak",), t=truth("planted", "A25", "exclude", "TAG_SEASONAL", "none",
                                         "looks oversized in a quiet month; festive-sale peak is outside the window"))

    # ---------------- B. Idle and scheduling
    add("staging-db-02", lambda r: idle_cpu(r, 1.0, 0.3),
        env="staging", team="data", region="noida", plan="B3", purpose="db", mem_base=18, mem_coupling=0,
        tags=("stateful",), **IDLE_IO,
        t=truth("planted", "B1", "recommend", "IDLE", "snapshot+stop",
                "1% for 30 days; stateful non-prod: snapshot first, delete after 14 days"))

    add("prod-old-12", lambda r: idle_cpu(r, 1.2, 0.3),
        env="prod", team="growth", region="mumbai", plan="B2", purpose="web", mem_base=12, mem_coupling=0,
        **IDLE_IO, t=truth("planted", "B2", "flag", "IDLE_PROD", "none", "idle prod: review with owner"))

    add("dev-cache-13", lambda r: idle_cpu(r, 2.0, 0.5),
        env="dev", team="search", region="bangalore", plan="B3", purpose="cache",
        mem=lambda r, c: 74 + r.normal(0, 1, AX.n),
        t=truth("planted", "B3", "reject", "VETO_MEMORY", "none", "CPU 2% but memory-resident at 74%: not idle"))

    def web03(r):
        busy = ~AX.weekend & between(9, 19)
        return np.where(busy, 5 + 4 * daily(9, 19) + ar1(r, 1.0), 0.8 + ar1(r, 0.25))
    add("dev-web-03", web03, env="dev", team="growth", region="mumbai", plan="B4", purpose="web",
        mem_base=11, mem_sd=1.0, faults=("duplicate_block",),
        t=truth("planted", "B4/E2", "recommend", "UNDERUSED", "resize+schedule",
                "B4->B2 plus off Mon-Fri 20:00-08:00 and weekends; combined, not additive"))

    def etl04(r):
        cpu = office(r, 38, 6, 2.0)
        w = between(1, 3)
        cpu[w] = r.uniform(65, 75, w.sum())
        return cpu
    add("dev-etl-04", etl04, env="dev", team="data", region="noida", plan="B2", purpose="etl", mem_base=20,
        t=truth("planted", "B5", "recommend", "OFF_HOURS", "schedule",
                "nightly job 01:00-03:00: off-window must exclude it"))

    def support05(r):
        busy = ~AX.weekend & between(22, 6)
        return np.where(busy, r.normal(38, 6, AX.n), 2 + ar1(r, 0.5))
    add("dev-support-05", support05, env="dev", team="mobile", region="bangalore", plan="B2",
        purpose="support", mem_base=20,
        t=truth("planted", "B6", "recommend", "OFF_HOURS", "schedule",
                "night-shift team busy 22:00-06:00: window must be daytime"))

    def load06(r):
        busy = AX.weekend & between(10, 18)
        return np.where(busy, r.uniform(60, 80, AX.n), 1.5 + ar1(r, 0.4))
    add("staging-load-06", load06, env="staging", team="platform", region="mumbai", plan="B3",
        purpose="loadtest", mem_base=20,
        t=truth("planted", "B7", "recommend", "OFF_HOURS", "schedule", "weekend-only load tests: weekdays off"))

    add("dev-misc-07", lambda r: np.maximum(3 + ar1(r, 0.6),
                                            random_spikes(r, 9.6, (3, 3), (25.0, 35.0))),
        env="dev", team="growth", region="noida", plan="B2", purpose="misc", mem_base=20,
        t=truth("planted", "B9", "recommend", "UNDERUSED", "resize",
                "activity scattered across all hours: off-hours fragmented, so no schedule"))

    add("staging-demo-10", lambda r: office(r, 35, 6, 2.0),
        env="staging", team="growth", region="mumbai", plan="B2", purpose="demo", mem_base=20,
        tags=("keep_running",), policy="no_schedule",
        t=truth("planted", "B10", "healthy", "RIGHT_SIZED", "none",
                "office-hours shape but keep_running tag: never scheduled"))

    # ---------------- C. Stopped VMs
    add("vm-stopped-07", None, env="dev", team="data", region="noida", plan="B3", purpose="web",
        disk_gb=100, state="stopped", stopped_since=ts("2026-09-05 18:00"), has_metrics=False,
        t=truth("planted", "C10", "recommend", "STOPPED_VM", "snapshot+delete",
                "stopped 45 days; disk + IP still billed"))

    add("vm-maint-08", lambda r: steady(r, 20, 20, 0.85, 2.0),
        env="staging", team="platform", region="bangalore", plan="B2", purpose="web",
        state="stopped", stopped_since=ts("2026-10-17 09:00"), active=(0, day_slot(27, 9)),
        t=truth("planted", "C11", "exclude", "STOPPED_RECENTLY", "none", "stopped 3 days ago: maintenance"))

    # ---------------- D. Lifecycle and inventory
    add("dev-test-12", lambda r: steady(r, 10, 10, 0.85, 2.0),
        env="dev", team="mobile", region="mumbai", plan="B2", purpose="test",
        created_at=ts("2026-10-17 10:00"), active=(day_slot(27, 10), N_SLOTS),
        t=truth("planted", "D1", "exclude", "HISTORY_TOO_SHORT", "none", "created 3 days ago"))

    def app05(r):
        cpu = steady(r, 15, 15, 0.85, 2.0)
        after = AX.day >= 24
        cpu[after] *= 8 / 6                              # same load on fewer vCPUs
        return cpu
    add("staging-app-05", app05, env="staging", team="search", region="bangalore", plan="B3",
        previous_plan_id="B4", last_resized_at=ts("2026-10-14 08:00"), purpose="app", mem_base=15,
        t=truth("planted", "D2", "exclude", "RECENTLY_RESIZED", "none",
                "resized B4->B3 6 days ago; older data describes a different machine"))

    add("prod-standby-01", lambda r: idle_cpu(r, 0.8, 0.2),
        env="prod", team="platform", region="bangalore", plan="B4", purpose="standby", mem_base=10,
        mem_coupling=0, iops_base=0.5, k_iops=0, net_base=0.2, k_net=0,
        tags=("dr_standby",), policy="never",
        t=truth("planted", "D3", "exclude", "TAG_DR_STANDBY", "none", "DR warm standby: only the tag saves it"))

    add("prod-nomon-13", None, env="prod", team="search", region="mumbai", plan="B2", purpose="api",
        has_metrics=False, t=truth("planted", "D4", "exclude", "NO_TELEMETRY", "none",
                                   "monitoring agent missing: no metrics at all"))

    add("vm-untagged-14", lambda r: steady(r, 6, 3, 0.9, 1.5),
        env="", team="platform", region="noida", plan="B3", purpose="api", mem_base=10,
        t=truth("planted", "D5", "recommend", "UNDERUSED", "resize",
                "env tag missing: treated as prod (one step) + UNTAGGED_ENV flag"))

    add("dev-orphan-owner-15", lambda r: steady(r, 6, 3, 0.9, 1.5),
        env="dev", team="growth", owner_team="", region="mumbai", plan="B3", purpose="api", mem_base=10,
        t=truth("planted", "D6", "recommend", "UNDERUSED", "resize", "owner missing: UNOWNED flag"))

    add("dev-misnamed-16", lambda r: steady(r, 6, 3, 0.9, 1.5),
        env="prod", team="mobile", region="bangalore", plan="B3", purpose="api", mem_base=10,
        t=truth("planted", "D7", "recommend", "UNDERUSED", "resize",
                "name says dev, tag says prod: trust tag (one step) + TAG_NAME_CONFLICT flag"))

    add("prod-legacy-plan-17", lambda r: steady(r, 6, 3, 0.9, 1.5),
        env="prod", team="data", region="noida", plan="L-OLD-4", purpose="api", mem_base=10,
        t=truth("planted", "D8", "exclude", "UNKNOWN_PRICE", "none",
                "plan L-OLD-4 not in catalogue (billed at Rs 3,500): never guess a price"))

    def worker05(r):
        cpu = steady(r, 14, 10, 0.85, 2.0)
        cpu[AX.day >= 28] *= 4
        return cpu
    add("prod-worker-05", worker05, env="prod", team="data", region="mumbai", plan="B3", purpose="worker",
        mem_base=30, t=truth("planted", "D10/G3", "exclude", "ACTIVE_ANOMALY", "none",
                             "4x sustained CPU jump from 2026-10-18: anomaly alert, not sized"))

    # ---------------- E. Data quality
    add("prod-api-02", lambda r: steady(r, 25, 30, 0.85, 3.0),
        env="prod", team="platform", region="mumbai", plan="B3", purpose="api", mem_base=40,
        faults=("gap_6h",), t=truth("planted", "E1", "healthy", "RIGHT_SIZED", "none",
                                    "6-hour gap on 2026-10-02 10:00-16:00 must be NaN, not idle"))

    add("dev-flaky-18", lambda r: steady(r, 7, 3, 0.9, 1.5),
        env="dev", team="mobile", region="noida", plan="B2", purpose="api", mem_base=12,
        faults=("missing_30",), t=truth("planted", "E6", "exclude", "LOW_COVERAGE", "none", "~70% coverage"))

    add("staging-flaky-19", lambda r: steady(r, 6, 3, 0.9, 1.5),
        env="staging", team="growth", region="bangalore", plan="B3", purpose="api", mem_base=10,
        faults=("missing_12",), t=truth("planted", "E7", "recommend", "UNDERUSED", "resize",
                                        "~88% coverage: allowed, confidence Medium, MEDIUM_COVERAGE flag"))

    add("dev-api-16", lambda r: office(r, 35, 6, 2.0),
        env="dev", team="search", region="mumbai", plan="B2", purpose="api", mem_base=18,
        faults=("flatline_48h",), t=truth("planted", "E8", "recommend", "OFF_HOURS", "schedule",
                                          "stuck agent reports 0.0 for 48h (days 15-16): treat as missing"))

    add("prod-batch-20", batch07, env="prod", team="data", region="bangalore", plan="B3", purpose="batch",
        mem_base=22, faults=("peak_gap",),
        t=truth("planted", "E9", "flag", "PEAK_UNDER_OBSERVED", "none",
                "02:00 batch, but 01:00-04:00 missing on 18 of 30 nights"))

    # ---------------- G. Alerts
    def sandbox(r):
        cpu = idle_cpu(r, 2.0, 0.5)
        hit = AX.day >= 26
        cpu[hit] = r.uniform(96, 99.5, hit.sum())
        return cpu

    def sandbox_net_out(r, c):
        base = 1000 * 0.004 * r.lognormal(0, 0.3, AX.n)       # ~4 Mbps
        return np.where(AX.day >= 26, base * 10, base)
    add("dev-sandbox-17", sandbox, env="dev", team="growth", region="noida", plan="B2", purpose="sandbox",
        mem_base=20, net_base=0.5, k_net=0.0, net_out=sandbox_net_out,
        t=truth("planted", "G4", "exclude", "ACTIVE_ANOMALY", "none",
                "CPU 98% + 10x network out from 2026-10-16: critical 'possible compromise'"))

    return S


def stray_series():
    """D9: metrics for a VM that is not in the inventory."""
    r = rng_for("vm-ghost-99")
    return make_vm("vm-ghost-99", cpu=steady(r, 8, 4, 0.9, 1.5), rng=r, env="dev", team="data",
                   plan="B2", purpose="api",
                   t=truth("planted", "D9", "exclude", "NOT_IN_INVENTORY", "none",
                           "metrics exist but no inventory row"))


def planted_volumes():
    """Data volumes. Healthy ones attach to bulk prod VMs; team/env/region copied from the VM at build."""
    V = []
    for i, vm in enumerate(["prod-web-35", "prod-api-36", "prod-search-37", "prod-checkout-38",
                            "prod-web-39", "prod-api-40", "prod-search-41", "prod-checkout-42", "prod-web-43"]):
        name = f"vol-data-{i + 21}"
        r = rng_for(name)
        V.append(make_volume(name, env="prod", team="", size_gb=int(r.choice([100, 200, 250])),
                             attached_to=vm, used_pct=r.uniform(40, 70),
                             iops_pct=5 + 25 * daily() * weekly(0.8) * r.lognormal(0, 0.3, AX.n),
                             t=truth("healthy_volume", "", "healthy", "RIGHT_SIZED", "none")))

    V.append(make_volume("vol-orphan-11", env="dev", team="data", region="noida", size_gb=500,
                         created_at=ts("2026-01-08 12:00"), unattached_since=ts("2026-08-16 15:00"),
                         used_pct=24,
                         t=truth("planted", "C1", "recommend", "ORPHAN_VOLUME", "snapshot+delete",
                                 "unattached 65 days; 120 GB used -> snapshot Rs 480")))
    V.append(make_volume("vol-new-12", env="dev", team="mobile", region="mumbai", size_gb=100,
                         created_at=ts("2026-10-10 10:00"), unattached_since=ts("2026-10-18 10:00"),
                         used_pct=5,
                         t=truth("planted", "C2", "exclude", "ORPHAN_TOO_NEW", "none",
                                 "unattached 2 days: under the 7-day gate")))
    V.append(make_volume("vol-idle-04", env="prod", team="", size_gb=200, attached_to="prod-api-44",
                         used_pct=35,
                         t=truth("planted", "C3", "flag", "IDLE_VOLUME_REVIEW", "none",
                                 "attached to a running VM, zero IOPS for 30 days")))
    V.append(make_volume("vol-stopped-07", env="dev", team="", size_gb=200, attached_to="vm-stopped-07",
                         used_pct=45,
                         t=truth("planted", "C4", "recommend", "STOPPED_VM", "snapshot+delete",
                                 "attached to a VM stopped 45 days")))
    r = rng_for("vol-oversized-09")
    V.append(make_volume("vol-oversized-09", env="prod", team="", size_gb=500, attached_to="prod-search-45",
                         used_pct=8, iops_pct=3 + 5 * daily() * r.lognormal(0, 0.3, AX.n),
                         t=truth("planted", "C5", "recommend", "OVERSIZED_VOLUME", "shrink_volume",
                                 "500 GB, 40 GB used: migrate to 100 GB (no in-place shrink)")))
    r = rng_for("vol-growing-10")
    V.append(make_volume("vol-growing-10", env="prod", team="", size_gb=500, attached_to="prod-api-01",
                         used_pct=30, used_slope=2.0,
                         iops_pct=8 + 15 * daily() * r.lognormal(0, 0.3, AX.n),
                         t=truth("planted", "C6", "reject", "VETO_GROWTH", "none",
                                 "oversized today but growing 2%/day -> disk alert")))
    return V


def planted_ips():
    P = [make_ip(f"ip-pub-{i + 21}", env="prod", team="", attached_to=vm,
                 t=truth("healthy_ip", "", "healthy", "RIGHT_SIZED", "none"))
         for i, vm in enumerate(["prod-api-01", "prod-gateway-03", "prod-checkout-03",
                                 "prod-web-35", "prod-api-36"])]
    P.append(make_ip("ip-unused-03", env="dev", team="growth", region="mumbai",
                     created_at=ts("2026-07-01 12:00"), unattached_since=ts("2026-07-01 12:00"),
                     t=truth("planted", "C7", "recommend", "UNUSED_IP", "release", "allocated, never associated")))
    P.append(make_ip("ip-stopped-02", env="dev", team="", attached_to="vm-stopped-07",
                     t=truth("planted", "C8", "recommend", "STOPPED_VM", "release",
                             "associated with a VM stopped 45 days")))
    P.append(make_ip("ip-allowlist-04", env="prod", team="payments", region="mumbai",
                     unattached_since=ts("2026-09-01 10:00"), tags=("allowlisted_ip",),
                     t=truth("planted", "C9", "exclude", "TAG_ALLOWLISTED_IP", "none",
                             "on a bank/payment-gateway allowlist: cannot be re-acquired")))
    return P
