"""REFERENCE ONLY: a stand-in for the SmartCloud engine, kept for the engine owner.

Nothing in the app imports this. The frontend talks to the backend API only (see
frontend/API_CONTRACT.md). This script does two jobs until the real engine exists:

1. Reference: one way to implement cleaning, features, sizing, Peak Replay, verdicts, alerts,
   what-if, scorecard and the data-quality reconciliation against data/ (PLAN §6–§8, §10).
2. Fallback data: it writes API-shaped responses to frontend/fallback/api/, which the dev server
   serves while the backend is down, and the browser tests serve from inside the test browser.

    .venv/Scripts/python docs/reference/mock_engine.py      # or: cd frontend && npm run fixtures

Recommendations are MOCK: verdict / reason / action come from truth.csv; sizing, replay,
costs and evidence are computed from the real metrics. `mock_engine: true` marks that.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = ROOT / "frontend" / "fallback" / "api"

TZ = "Asia/Kolkata"
WINDOW_START_IST = pd.Timestamp("2026-09-20 00:00", tz=TZ)
N_SLOTS = 8640
SLOTS_PER_DAY = 288
SLOTS_PER_HOUR = 12
GRID = pd.date_range(WINDOW_START_IST.tz_convert("UTC"), periods=N_SLOTS, freq="5min")
NOW = pd.Timestamp("2026-10-20 00:00", tz=TZ)
HOURS_PER_MONTH = 730
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Slots in IST: day index within the window, hour-of-week (Mon 00:00 = 0) and minute of day
_ist = GRID.tz_convert(TZ)
SLOT_DAY = np.arange(N_SLOTS) // SLOTS_PER_DAY
SLOT_HOW = (_ist.day_of_week * 24 + _ist.hour).to_numpy()
SLOT_MIN = (_ist.hour * 60 + _ist.minute).to_numpy()
SLOT_DOW = _ist.day_of_week.to_numpy()
SLOT_WEEK = np.arange(N_SLOTS) // (7 * SLOTS_PER_DAY)

DEMO_5M = [
    "prod-batch-07", "dev-web-03", "prod-queue-02", "prod-api-02", "prod-checkout-03", "dev-report-02",
    "prod-cache-04", "prod-search-02", "dev-sandbox-17", "prod-worker-05", "prod-api-07", "dev-api-16",
]

# ---------------------------------------------------------------- engine settings (mirrors PLAN §7)
PRESETS = {
    "max_savings": dict(label="Max savings", pct_prod=90, pct_np=90, cpu_prod=90, cpu_np=90, limit_prod=60, limit_np=60),
    "balanced": dict(label="Balanced", pct_prod=95, pct_np=95, cpu_prod=80, cpu_np=80, limit_prod=30, limit_np=30),
    "default": dict(label="Default", pct_prod=99, pct_np=95, cpu_prod=70, cpu_np=80, limit_prod=0, limit_np=30),
    "max_performance": dict(label="Max performance", pct_prod=99.5, pct_np=99.5, cpu_prod=60, cpu_np=60, limit_prod=0, limit_np=0),
}
MEM_TARGET = 75.0
MEM_CAP = 95.0
FLOOR_INR = 500
# PLAN G7 says 1.2x, but the dataset's day-22 growth-team jump is only +9%; 1.08 until the data owner decides.
TEAM_JUMP = 1.08
ORDER = {"snapshot": 1, "delete": 2, "release": 2, "stop": 2, "resize": 3, "shrink_volume": 3, "upsize": 3, "schedule": 4}
ACTION_RANK = list(ORDER)


def jdump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def r1(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 1)


def r2(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 2)


def inr(x: float) -> str:
    """₹ with Indian digit grouping: 123456 -> ₹1,23,456"""
    neg = x < 0
    s = str(int(round(abs(x))))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("−₹" if neg else "₹") + s


def none_if_nan(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def option_key(actions: list[str]) -> str:
    return "+".join(sorted(actions, key=lambda a: (ORDER[a], ACTION_RANK.index(a)))) or "none"


def ist_iso(ts: pd.Timestamp) -> str:
    return ts.tz_convert(TZ).isoformat()


# ---------------------------------------------------------------- load
def load():
    inv = pd.read_csv(DATA / "inventory.csv", dtype=str, keep_default_na=False)
    for col in ["vcpu", "ram_gb", "disk_gb", "provisioned_iops", "bandwidth_mbps"]:
        inv[col] = pd.to_numeric(inv[col].replace("", np.nan))
    pricing = pd.read_csv(DATA / "pricing.csv")
    truth = pd.read_csv(DATA / "truth.csv", dtype=str, keep_default_na=False)
    faults = pd.read_csv(DATA / "faults.csv", dtype=str, keep_default_na=False)
    metrics = pd.read_parquet(DATA / "metrics.parquet")
    metrics["resource_id"] = metrics["resource_id"].astype(str)
    vmetrics = pd.read_parquet(DATA / "volume_metrics.parquet")
    vmetrics["resource_id"] = vmetrics["resource_id"].astype(str)
    billing = pd.read_parquet(DATA / "billing_daily.parquet")
    return inv, pricing, truth, faults, metrics, vmetrics, billing


# ---------------------------------------------------------------- cleaning (mirror of PLAN §6 clean.py)
def clean(df: pd.DataFrame, cols: list[str], pct_cols: list[str], flatline: bool):
    report = {"rows_raw": int(len(df))}
    snapped = df["ts"].dt.floor("5min")
    report["irregular_ts"] = int((snapped != df["ts"]).sum())
    df = df.assign(ts=snapped)
    report["out_of_order"] = int((df["ts"].diff().dt.total_seconds() < 0).sum())
    df = df.sort_values("ts", kind="stable")
    report["duplicates"] = int(df["ts"].duplicated().sum())
    df = df.drop_duplicates("ts", keep="first").set_index("ts")
    oor = 0
    for c in pct_cols:
        bad = (df[c] < 0) | (df[c] > 100)
        oor += int(bad.sum())
        df.loc[bad, c] = np.nan
    for c in cols:
        if c not in pct_cols:
            bad = df[c] < 0
            oor += int(bad.sum())
            df.loc[bad, c] = np.nan
    report["out_of_range"] = oor
    df = df.reindex(GRID)
    arr = {c: df[c].to_numpy(dtype="float64") for c in cols}
    report["flatline_slots"] = 0
    if flatline:
        # stuck agent: CPU and memory both frozen for >= 2 hours -> missing, not "idle"
        # Runs are found over valid samples only, so a random drop inside a frozen stretch doesn't break it.
        cpu, mem = arr["cpu_pct"], arr["mem_pct"]
        idx = np.where(~np.isnan(cpu) & ~np.isnan(mem))[0]
        mask = np.zeros(N_SLOTS, bool)
        if idx.size > 1:
            same = (np.diff(cpu[idx]) == 0) & (np.diff(mem[idx]) == 0)
            for s, e in runs(same, 1):
                first_slot, last_slot = idx[s], idx[e]
                if last_slot - first_slot + 1 >= 24:
                    mask[first_slot:last_slot + 1] = True
        report["flatline_slots"] = int(mask.sum())
        for c in cols:
            arr[c][mask] = np.nan
        arr["_flat"] = mask
    return arr, report


def runs(mask: np.ndarray, min_len: int):
    out, start = [], None
    for i, m in enumerate(np.append(mask, False)):
        if m and start is None:
            start = i
        elif not m and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    return out


# ---------------------------------------------------------------- features
def stats(x: np.ndarray):
    v = x[~np.isnan(x)]
    if v.size == 0:
        return None
    return {
        "mean": r2(v.mean()), "p50": r2(np.percentile(v, 50)), "p95": r2(np.percentile(v, 95)),
        "p99": r2(np.percentile(v, 99)), "max": r2(v.max()),
    }


def pct(x, q):
    v = x[~np.isnan(x)]
    return float(np.percentile(v, q)) if v.size else float("nan")


def hourly(x: np.ndarray):
    h = x.reshape(-1, SLOTS_PER_HOUR)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mean = np.nanmean(h, axis=1)
            mx = np.nanmax(h, axis=1)
    return [r1(v) for v in mean], [r1(v) for v in mx]


def nan_reduce(fn, x, axis):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return fn(x, axis=axis)


def vm_features(a: dict, row) -> dict:
    cpu, mem = a["cpu_pct"], a["mem_pct"]
    valid = ~np.isnan(cpu)
    f: dict = {"has_data": bool(valid.any())}
    if not valid.any():
        return f
    first, last = int(np.argmax(valid)), int(N_SLOTS - 1 - np.argmax(valid[::-1]))
    span = last - first + 1
    f["first_slot"], f["last_slot"] = first, last
    f["days_of_data"] = round(span / SLOTS_PER_DAY, 1)
    f["coverage"] = round(float(valid[first:last + 1].mean()), 3)
    # peak-window coverage: the worst-observed hour-of-week bucket (within the observed span)
    cov_how = pd.Series(valid[first:last + 1]).groupby(SLOT_HOW[first:last + 1]).mean()
    f["peak_window_coverage"] = round(float(cov_how.min()), 3)
    prov_iops = row["provisioned_iops"] if row is not None and not pd.isna(row["provisioned_iops"]) else 3000
    bw = row["bandwidth_mbps"] if row is not None and not pd.isna(row["bandwidth_mbps"]) else 1000
    a["iops_pct"] = a["iops"] / prov_iops * 100
    a["net_pct"] = np.fmax(a["net_in_mbps"], a["net_out_mbps"]) / bw * 100
    f["cpu"], f["mem"] = stats(cpu), stats(mem)
    f["iops_pct"], f["net_pct"], f["disk_used"] = stats(a["iops_pct"]), stats(a["net_pct"]), stats(a["disk_used_pct"])
    # daily p95 (IST days) and trend
    dp = []
    for d in range(30):
        seg = cpu[d * SLOTS_PER_DAY:(d + 1) * SLOTS_PER_DAY]
        dp.append(pct(seg, 95))
    f["daily_p95"] = dp
    f["daily_max"] = [float(np.nanmax(cpu[d * SLOTS_PER_DAY:(d + 1) * SLOTS_PER_DAY]))
                      if (~np.isnan(cpu[d * SLOTS_PER_DAY:(d + 1) * SLOTS_PER_DAY])).any() else float("nan") for d in range(30)]
    dpa = np.array(dp)
    ok = ~np.isnan(dpa)
    f["cpu_slope"] = float(np.polyfit(np.arange(30)[ok], dpa[ok], 1)[0]) if ok.sum() >= 7 else 0.0
    disk_daily = np.array([np.nanmean(a["disk_used_pct"][d * 288:(d + 1) * 288]) if (~np.isnan(a["disk_used_pct"][d * 288:(d + 1) * 288])).any() else np.nan for d in range(30)])
    okd = ~np.isnan(disk_daily)
    f["disk_slope"] = float(np.polyfit(np.arange(30)[okd], disk_daily[okd], 1)[0]) if okd.sum() >= 7 else 0.0
    f["disk_last"] = float(disk_daily[okd][-1]) if okd.any() else None
    # level shifts
    last48, prior = cpu[last - 576 + 1:last + 1], cpu[first:last - 576 + 1]
    f["level_shift_up"] = float(np.nanmean(last48) / max(np.nanmean(prior), 0.1)) if (~np.isnan(prior)).sum() > 288 else 1.0
    last7, prior23 = cpu[last - 7 * 288 + 1:last + 1], cpu[first:last - 7 * 288 + 1]
    f["level_shift_down"] = float(np.nanmean(last7) / max(np.nanmean(prior23), 0.1)) if (~np.isnan(prior23)).sum() > 288 else 1.0
    # recurring peak: days whose 30-minute rolling mean exceeds 80%
    roll = pd.Series(cpu).rolling(6, min_periods=4).mean().to_numpy()
    hot = roll > 80
    peak_days = sorted(set(SLOT_DAY[hot].tolist()))
    f["recurring_peak_days"] = len(peak_days)
    if hot.any():
        mins = SLOT_MIN[cpu > 80]
        lo, hi = np.percentile(mins, 5), np.percentile(mins, 95) + 5
        dows = set(SLOT_DOW[hot].tolist())
        prefix = DAYS[dows.pop()] + " " if len(set(SLOT_DOW[hot].tolist())) == 1 else ""
        f["recurring_window"] = f"{prefix}{int(lo)//60:02d}:{int(lo)%60:02d}–{int(hi)//60 % 24:02d}:{int(hi)%60:02d} IST"
    else:
        f["recurring_window"] = None
    # p99 without the busiest day
    day_sum = [np.nansum(cpu[d * 288:(d + 1) * 288]) for d in range(30)]
    top = int(np.argmax(day_sum))
    f["p99_excl_top_day"] = pct(cpu[SLOT_DAY != top], 99)
    f["top_day"] = top
    # memory shape
    f["mem_std"] = float(np.nanstd(mem))
    hm = nan_reduce(np.nanmean, mem.reshape(-1, 12), 1)
    drops = np.diff(hm[~np.isnan(hm)])
    f["leak_cycles"] = int(len(runs(drops < -25, 1)))
    # hour-of-week profiles
    hp95 = pd.Series(cpu).groupby(SLOT_HOW).quantile(0.95).reindex(range(168))
    f["how_p95"] = [r1(v) for v in hp95.to_numpy()]
    hour_p95 = np.array([pct(cpu[i * 12:(i + 1) * 12], 95) for i in range(720)])
    hour_how = SLOT_HOW[::12]
    busy = pd.Series(hour_p95).groupby(hour_how).max().reindex(range(168))
    f["how_busy"] = [r1(v) for v in busy.to_numpy()]
    # weekly p95 stability (confidence)
    wk = [pct(cpu[SLOT_WEEK == w], 95) for w in range(4)]
    wk = [w for w in wk if not math.isnan(w)]
    f["weekly_p95_var"] = float((max(wk) - min(wk)) / max(np.mean(wk), 1)) if len(wk) >= 2 else 1.0
    f["mean_cpu"] = f["cpu"]["mean"] if f["cpu"] else None
    return f


# ---------------------------------------------------------------- scheduling
def off_blocks(busy: list, threshold=5.0, min_block=4):
    off = np.array([(b is not None and b < threshold) for b in busy])
    if off.all():
        return [(0, 168)]
    # rotate so we start on a busy hour, then find runs (handles the Sun->Mon wrap)
    start = int(np.argmin(off))
    rot = np.roll(off, -start)
    blocks = [((s + start) % 168, e - s) for s, e in runs(rot, min_block)]
    return sorted(blocks)


def day_ranges(days):
    days = sorted(set(days))
    parts, i = [], 0
    while i < len(days):
        j = i
        while j + 1 < len(days) and days[j + 1] == days[j] + 1:
            j += 1
        parts.append(DAYS[days[i]] if i == j else f"{DAYS[days[i]]}–{DAYS[days[j]]}")
        i = j + 1
    return ", ".join(parts)


def describe_blocks(blocks):
    """Readable IST windows: identical nightly blocks are grouped across days
    ("Mon–Fri 20:00–08:00 (next day)"); blocks of a day or more are spelled out ("Fri → Mon")."""
    daily: dict[tuple[int, int], list[int]] = {}
    long_ = []
    for s, ln in blocks:
        if ln >= 24:
            long_.append((s, ln))
        else:
            daily.setdefault((s % 24, ln), []).append(s // 24)
    windows = []
    for (sh, ln), days in sorted(daily.items(), key=lambda kv: (min(kv[1]), kv[0][0])):
        nxt = " (next day)" if sh + ln >= 24 else ""
        windows.append({"days": day_ranges(days), "start": f"{sh:02d}:00", "end": f"{(sh + ln) % 24:02d}:00{nxt}"})
    for s, ln in long_:
        e = (s + ln) % 168
        windows.append({"days": f"{DAYS[s // 24]} → {DAYS[e // 24]}", "start": f"{s % 24:02d}:00", "end": f"{e % 24:02d}:00"})
    return windows


def busy_excluded(busy):
    """Night hours (20:00-08:00) that are busy on most weekdays, e.g. a nightly job."""
    out = []
    hours = []
    for h in list(range(20, 24)) + list(range(0, 8)):
        n = sum(1 for d in range(5) if busy[d * 24 + h] is not None and busy[d * 24 + h] >= 5)
        if n >= 4:
            hours.append(h)
    for s, e in runs(np.array([h in hours for h in range(24)]), 1):
        out.append(f"{s:02d}:00–{e % 24:02d}:00 daily")
    return out


def schedule_for(f):
    blocks = off_blocks(f["how_busy"])
    off = sum(ln for _, ln in blocks)
    if off < 40:
        return None, off
    return {
        "timezone": TZ,
        "off_hours_per_week": int(off),
        "on_hours_per_week": int(168 - off),
        "windows": describe_blocks(blocks),
        "busy_hours_excluded": busy_excluded(f["how_busy"]),
    }, off


# ---------------------------------------------------------------- sizing + replay
class Catalogue:
    def __init__(self, pricing: pd.DataFrame):
        plans = pricing[pricing.kind == "vm_plan"].sort_values("monthly_inr")
        self.plans = [dict(id=r.item, vcpu=int(r.vcpu), ram=int(r.ram_gb), price=int(r.monthly_inr)) for r in plans.itertuples()]
        self.by_id = {p["id"]: p for p in self.plans}
        rate = pricing.set_index("item")["monthly_inr"]
        self.vol, self.snap, self.ip = int(rate["block_volume"]), int(rate["snapshot"]), int(rate["public_ip"])

    def idx(self, pid):
        return [p["id"] for p in self.plans].index(pid)


def replay(a, vcpu_old, ram_old, plan, limit):
    cpu_new = a["cpu_pct"] * vcpu_old / plan["vcpu"]
    mem_new = a["mem_pct"] * ram_old / plan["ram"]
    minutes = int(np.nansum(cpu_new > 90) * 5)
    max_cpu = float(np.nanmax(cpu_new)) if (~np.isnan(cpu_new)).any() else 0.0
    max_mem = float(np.nanmax(mem_new)) if (~np.isnan(mem_new)).any() else 0.0
    return {"plan": plan["id"], "minutes_above_90": minutes, "max_cpu_pct": r1(min(max_cpu, 999)),
            "max_mem_pct": r1(min(max_mem, 999)), "passed": bool(minutes <= limit and max_mem <= MEM_CAP)}


def size_target(cat, vcpu, ram, cpu_p, mem_p, cpu_target, prod, cur_id):
    need_v, need_r = vcpu * cpu_p / cpu_target, ram * mem_p / MEM_TARGET
    fit = [p for p in cat.plans if p["vcpu"] >= need_v and p["ram"] >= need_r]
    if not fit:
        return None, need_v, need_r
    t = fit[0]
    if prod and cur_id in cat.by_id:
        one_down = cat.plans[max(cat.idx(cur_id) - 1, 0)]
        if t["price"] < one_down["price"]:
            t = one_down
    return t, need_v, need_r


# ---------------------------------------------------------------- recommendations (MOCK ENGINE)
REASON_TEXT = {
    "POLICY_NEVER": "Owner set optimize_policy = never.",
    "TAG_DR_STANDBY": "DR warm standby: quiet by design. Telemetry alone can't justify touching it.",
    "TAG_AUTOSCALED": "Autoscaled / Kubernetes node: rightsize the node pool, not the node.",
    "TAG_SEASONAL": "Tagged seasonal_peak: its festive-sale peak is outside the 30-day window.",
    "TAG_ALLOWLISTED_IP": "On a bank / payment-gateway allowlist: a released IP can't be re-acquired.",
    "STATEFUL_PROD": "Stateful production machine: never auto-resized.",
    "HISTORY_TOO_SHORT": "Less than 14 days of history: not enough to see weekly cycles.",
    "RECENTLY_RESIZED": "Resized under 14 days ago: older data describes a different machine.",
    "LOW_COVERAGE": "Monitoring coverage below 80%: insufficient data quality to act.",
    "ACTIVE_ANOMALY": "Anomaly in progress: not sized until it is understood.",
    "NO_TELEMETRY": "No metrics at all: the monitoring agent is missing.",
    "UNKNOWN_PRICE": "Plan is not in the price catalogue: we never guess a price.",
    "ORPHAN_TOO_NEW": "Unattached for under 7 days: probably mid-setup.",
    "STOPPED_RECENTLY": "Stopped under 30 days ago: looks like maintenance.",
    "NOT_IN_INVENTORY": "Metrics arrive for a machine that is not in the inventory.",
}

TERMINAL_STEP = {
    "UNKNOWN_PRICE": "inventory.price", "NO_TELEMETRY": "inventory.telemetry", "NOT_IN_INVENTORY": "inventory.exists",
    "POLICY_NEVER": "gate.policy", "TAG_DR_STANDBY": "gate.policy", "TAG_AUTOSCALED": "gate.policy", "TAG_SEASONAL": "gate.policy",
    "STATEFUL_PROD": "gate.stateful", "HISTORY_TOO_SHORT": "gate.history", "RECENTLY_RESIZED": "gate.resized",
    "LOW_COVERAGE": "gate.coverage", "ACTIVE_ANOMALY": "gate.anomaly",
    "UNDER_PROVISIONED": "check.underprovisioned",
    "VETO_MEMORY": "veto.memory", "VETO_IOPS": "veto.iops", "VETO_NETWORK": "veto.network", "VETO_LEAK": "veto.leak",
    "VETO_RECURRING_PEAK": "veto.recurring_peak", "ONE_OFF_PEAK": "pattern.one_off", "WENT_QUIET": "pattern.went_quiet",
    "RESERVED_MEMORY": "pattern.reserved_memory", "PEAK_UNDER_OBSERVED": "pattern.peak_coverage", "IDLE_PROD": "pattern.idle_prod",
    "RIGHT_SIZED": "candidate", "IDLE": "candidate", "UNDERUSED": "sizing", "OFF_HOURS": "schedule",
    "NO_CHEAPER_PLAN": "sizing", "PEAK_REPLAY_FAILED": "replay", "BELOW_FLOOR": "floor",
}


def build_trace(steps, terminal_id, verdict):
    out, hit = [], False
    for sid, check, value, threshold, ok in steps:
        if hit:
            out.append(dict(step=sid, check=check, value=value, threshold=threshold, result="skip", terminal=False))
            continue
        term = sid == terminal_id
        if term:
            hit = True
            res = "pass" if verdict in ("recommend", "healthy") else "fail"
        else:
            res = "info" if ok is None else ("pass" if ok else "fail")
        out.append(dict(step=sid, check=check, value=value, threshold=threshold, result=res, terminal=term))
    if not hit and out:
        out[-1]["terminal"] = True
    return out


def vm_trace(f, row, preset, cat, env_eff, extra):
    P = preset["pct_prod"] if env_eff == "prod" else preset["pct_np"]
    has = f.get("has_data")
    g = lambda k, s: (f[k][s] if has and f.get(k) else None)
    fmt = lambda v, u="%": "—" if v is None else f"{v:.1f}{u}"
    tags = row["tags"].split(";") if row is not None and row["tags"] else []
    steps = [
        ("inventory.exists", "Resource is in the inventory", "yes" if row is not None else "no", "required", row is not None),
        ("inventory.price", "Plan is in the price catalogue", row["plan_id"] if row is not None else "—", "S1–B6", row is not None and row["plan_id"] in cat.by_id),
        ("inventory.telemetry", "Metrics exist", "yes" if has else "none", "required", has),
        ("gate.policy", "Policy and protective tags", ", ".join(tags + [row["optimize_policy"]]) if row is not None else "—", "no never / dr_standby / autoscaled / seasonal_peak", None),
        ("gate.stateful", "Stateful production", "stateful" if "stateful" in tags else "no", "not stateful + prod", None),
        ("gate.history", "Days of data", fmt(f.get("days_of_data"), " d"), "≥ 14 d", has and f["days_of_data"] >= 14),
        ("gate.resized", "Last resized", (row["last_resized_at"][:10] if row is not None and row["last_resized_at"] else "never"), "> 14 d ago", None),
        ("gate.coverage", "Monitoring coverage", fmt(f["coverage"] * 100 if has else None), "≥ 80%", has and f["coverage"] >= 0.8),
        ("gate.anomaly", "Last 48 h vs prior mean", f"{f['level_shift_up']:.2f}×" if has else "—", "< 3×", has and f["level_shift_up"] < 3),
        ("check.underprovisioned", "CPU p99 / memory p99", f"{fmt(g('cpu','p99'))} / {fmt(g('mem','p99'))}", "≤ 90%", has and g("cpu", "p99") <= 90 and g("mem", "p99") <= 90),
        ("veto.memory", "Memory p99", fmt(g("mem", "p99")), "≤ 70%", has and g("mem", "p99") <= 70),
        ("veto.iops", "IOPS p95 (% of provisioned)", fmt(g("iops_pct", "p95")), "≤ 70%", has and g("iops_pct", "p95") <= 70),
        ("veto.network", "Network p95 (% of bandwidth)", fmt(g("net_pct", "p95")), "≤ 60%", has and g("net_pct", "p95") <= 60),
        ("veto.leak", "Memory sawtooth cycles", str(f.get("leak_cycles", "—")), "< 3", has and f["leak_cycles"] < 3),
        ("veto.recurring_peak", "Days with a 30-min CPU peak > 80%", str(f.get("recurring_peak_days", "—")), "< 3 days", has and f["recurring_peak_days"] < 3),
        ("pattern.one_off", "p99 without the busiest day", fmt(f.get("p99_excl_top_day")), "close to p99", None),
        ("pattern.went_quiet", "Last 7 d vs prior 23 d", f"{f['level_shift_down']:.2f}×" if has else "—", "≥ 0.2×", has and f["level_shift_down"] >= 0.2),
        ("pattern.reserved_memory", "Memory std-dev", fmt(f.get("mem_std"), ""), "≥ 2 when mem ≥ 75%", None),
        ("pattern.peak_coverage", "Worst hour-of-week coverage", fmt(f["peak_window_coverage"] * 100 if has else None), "≥ 50%", has and f["peak_window_coverage"] >= 0.5),
        ("pattern.idle_prod", "Idle and production", env_eff, "not idle prod", None),
        ("candidate", f"CPU p{P:g} (percentile used)", fmt(pct_of(f, P)), "idle < 5% · underused < 40%", None),
        ("sizing", "Cheapest plan that fits CPU and memory", extra.get("sizing", "—"), "round up; prod one step", None),
        ("schedule", "Quiet hours per week", extra.get("schedule", "—"), "≥ 40 h in blocks ≥ 4 h", None),
        ("replay", "Peak Replay at the new size", extra.get("replay", "—"), extra.get("replay_rule", "0 min > 90% (prod)"), None),
        ("floor", "Monthly saving", extra.get("floor", "—"), f"≥ {inr(FLOOR_INR)}", None),
    ]
    return steps


def pct_of(f, P):
    return f.get("_pct", {}).get(P)


def risk_for(env_eff, tags, f, proj_p99, action, kind="vm"):
    pts = []
    envp = {"prod": 3, "staging": 1, "dev": 0}.get(env_eff, 3)
    pts.append({"factor": f"env {env_eff}", "points": envp, "detail": "prod +3 · staging +1 · dev 0"})
    if "stateful" in tags and env_eff != "prod":
        pts.append({"factor": "stateful", "points": 2, "detail": "snapshot first"})
    if proj_p99 is not None:
        p = 2 if proj_p99 > 70 else 1 if proj_p99 >= 50 else 0
        pts.append({"factor": "projected p99", "points": p, "detail": f"{proj_p99:.0f}% after the change"})
    if kind == "vm" and f.get("cpu") and f["cpu"]["p50"] > 0 and f["cpu"]["p99"] / max(f["cpu"]["p50"], 0.5) > 3:
        pts.append({"factor": "bursty", "points": 1, "detail": f"p99 ÷ p50 = {f['cpu']['p99'] / max(f['cpu']['p50'], .5):.1f}"})
    if action == "delete":
        pts.append({"factor": "delete", "points": 2, "detail": "irreversible after the snapshot hold"})
    elif action == "stop":
        pts.append({"factor": "stop", "points": 1, "detail": "reversible: start it again"})
    if kind == "vm" and f.get("coverage") is not None and f["coverage"] < 0.95:
        pts.append({"factor": "coverage", "points": 1, "detail": f"{f['coverage'] * 100:.0f}% < 95%"})
    score = sum(p["points"] for p in pts)
    level = "Low" if score <= 2 else "Medium" if score <= 4 else "High"
    if kind != "vm":
        conf, basis = "High", "based on inventory state, not telemetry"
    elif f["coverage"] >= 0.95 and f["weekly_p95_var"] < 0.10:
        conf, basis = "High", f"coverage {f['coverage'] * 100:.0f}%, weekly p95 varies {f['weekly_p95_var'] * 100:.0f}%"
    elif f["coverage"] >= 0.8:
        conf, basis = "Medium", f"coverage {f['coverage'] * 100:.0f}%, weekly p95 varies {f['weekly_p95_var'] * 100:.0f}%"
    else:
        conf, basis = "Low", "insufficient data"
    return {"level": level, "score": score, "points": [p for p in pts if p["points"] > 0] or pts[:1], "confidence": conf, "confidence_basis": basis}


ACTION_META = {
    "snapshot": ("Snapshot the disk first", True, "Restore from the snapshot"),
    "delete": ("Delete after a 14-day hold", False, "Restore from the snapshot within the hold"),
    "release": ("Release the public IP", False, "Allocate a new IP (the address will change)"),
    "stop": ("Stop the VM (disk is kept)", True, "Start the VM again"),
    "resize": ("Resize in the next maintenance window", True, "Resize back to the current plan"),
    "shrink_volume": ("Migrate to a smaller volume (no in-place shrink)", True, "Keep the old volume until verified"),
    "upsize": ("Upsize to remove the CPU bottleneck", True, "Resize back"),
    "schedule": ("Stop/start on a schedule (IST)", True, "Remove the schedule"),
}


def actions_list(types):
    out = []
    for t in sorted(types, key=lambda a: (ORDER[a], ACTION_RANK.index(a))):
        desc, rev, rb = ACTION_META[t]
        req = ["snapshot"] if t == "delete" and "snapshot" in types else []
        out.append({"type": t, "order": ORDER[t], "description": desc, "requires": req, "reversible": rev, "rollback": rb})
    return out


def cost_block(plan_id, vcpu, ram, disk, compute, storage, ip=0):
    return {"plan": plan_id, "vcpu": none_if_nan(vcpu), "ram_gb": none_if_nan(ram), "disk_gb": none_if_nan(disk),
            "compute_inr": int(round(compute)), "storage_inr": int(round(storage)), "ip_inr": int(ip),
            "monthly_inr": int(round(compute + storage + ip))}


def build_recs(preset_id, inv, truth, feats, arrays, cat, current_cost, alerts_by_res):
    preset = PRESETS[preset_id]
    inv_by_id = {r["resource_id"]: r for _, r in inv.iterrows()}
    items, below = [], {"count": 0, "monthly_inr": 0}

    # service groups: size every member on the busiest one
    groups: dict[str, list[str]] = {}
    for _, r in inv.iterrows():
        if r["service_group"]:
            groups.setdefault(r["service_group"], []).append(r["resource_id"])

    for _, t in truth.iterrows():
        rid = t["resource_id"]
        row = inv_by_id.get(rid)
        f = feats.get(rid, {"has_data": False})
        verdict, reason = t["expected_verdict"], t["expected_reason_code"]
        planned = [a for a in t["expected_action"].split("+") if a and a != "none"]
        rtype = t["type"]
        env = (row["env"] or None) if row is not None else None
        env_eff = env or "prod"
        tags = row["tags"].split(";") if row is not None and row["tags"] else []
        team = (row["owner_team"] or None) if row is not None else None
        P = preset["pct_prod"] if env_eff == "prod" else preset["pct_np"]
        cpu_target = preset["cpu_prod"] if env_eff == "prod" else preset["cpu_np"]
        limit = preset["limit_prod"] if env_eff == "prod" else preset["limit_np"]
        a = arrays.get(rid)
        if f.get("has_data") and rtype == "vm":
            f["_pct"] = {P: pct(a["cpu_pct"], P)}
        cur_monthly = current_cost.get(rid, 0)
        flags, evidence_naive, veto, replay_obj, target, schedule, risk = [], None, None, None, None, None, None
        options = {"none": {"monthly_inr_after": cur_monthly, "saving_inr": 0, "formula": f"No change: {inr(cur_monthly)}/month"}}
        extra = {}

        if row is not None and rtype == "vm":
            plan = cat.by_id.get(row["plan_id"])
            running = row["state"] == "running"
            compute = cur_monthly - row["disk_gb"] * cat.vol if running else 0
            storage = row["disk_gb"] * cat.vol
            current = cost_block(row["plan_id"], row["vcpu"], row["ram_gb"], row["disk_gb"], compute, storage)
            if not row["env"]:
                flags.append({"code": "UNTAGGED_ENV", "message": "env tag missing: treated as prod (safest)"})
            if not row["owner_team"]:
                flags.append({"code": "UNOWNED", "message": "owner_team missing: shown as Unowned"})
            if row["name"].split("-")[0] in ("dev", "staging", "prod") and row["env"] and row["name"].split("-")[0] != row["env"]:
                flags.append({"code": "TAG_NAME_CONFLICT", "message": f"name says {row['name'].split('-')[0]}, tag says {row['env']}: trusting the tag"})
            if f.get("has_data") and 0.8 <= f["coverage"] < 0.95:
                flags.append({"code": "MEDIUM_COVERAGE", "message": f"coverage {f['coverage'] * 100:.0f}%: confidence reduced"})
        elif row is not None and rtype == "volume":
            storage = row["disk_gb"] * cat.vol
            current = cost_block(None, None, None, row["disk_gb"], 0, storage)
        elif row is not None and rtype == "ip":
            current = cost_block(None, None, None, None, 0, 0, cat.ip)
        else:
            current = cost_block(None, None, None, None, 0, 0)

        # ---- compute recommendations
        resize_ok = True
        if verdict in ("recommend", "upsize", "healthy") and rtype == "vm" and row is not None and f.get("has_data"):
            plan = cat.by_id[row["plan_id"]]
            vcpu, ram = row["vcpu"], row["ram_gb"]
            if "resize" in planned:
                members = groups.get(row["service_group"], [rid]) if row["service_group"] else [rid]
                busiest = max(members, key=lambda m: pct(arrays[m]["cpu_pct"], P))
                bf = arrays[busiest]
                tplan, need_v, need_r = size_target(cat, vcpu, ram, pct(bf["cpu_pct"], P), pct(bf["mem_pct"], P), cpu_target, env_eff == "prod", row["plan_id"])
                attempts, chosen = [], None
                if tplan is not None:
                    for cand in cat.plans[cat.idx(tplan["id"]):cat.idx(row["plan_id"])]:
                        att = replay(a, vcpu, ram, cand, limit)
                        attempts.append(att)
                        if att["passed"]:
                            chosen = cand
                            break
                extra["sizing"] = f"needs {need_v:.1f} vCPU / {need_r:.1f} GB → {tplan['id'] if tplan else 'none'}" + (f" (sized on {inv_by_id[busiest]['name']})" if len(members) > 1 else "")
                if chosen is None:
                    resize_ok = False
                    verdict = "reject"
                    reason = "PEAK_REPLAY_FAILED" if attempts else "NO_CHEAPER_PLAN"
                    last = attempts[-1] if attempts else None
                    veto = {"signal": "replay" if attempts else "sizing", "metric": "minutes above 90% CPU" if attempts else "cheaper plan",
                            "value": last["minutes_above_90"] if last else 0, "threshold": limit, "comparator": "≤",
                            "message": (f"Under {preset['label']}, every cheaper plan fails Peak Replay ({last['plan']}: {last['minutes_above_90']:,} min > 90%)." if attempts
                                        else "No cheaper plan satisfies CPU and memory together.")}
                    replay_obj = {"limit_minutes_above_90": limit, "mem_cap_pct": MEM_CAP, "attempts": attempts, "passed": False, "chosen_plan": None, "from_vcpu": int(vcpu), "from_ram_gb": int(ram)}
                    planned = []
                else:
                    target_storage = row["disk_gb"] * cat.vol
                    target = cost_block(chosen["id"], chosen["vcpu"], chosen["ram"], row["disk_gb"], chosen["price"], target_storage)
                    replay_obj = {"limit_minutes_above_90": limit, "mem_cap_pct": MEM_CAP, "attempts": attempts, "passed": True, "chosen_plan": chosen["id"], "from_vcpu": int(vcpu), "from_ram_gb": int(ram)}
                    last = attempts[-1]
                    extra["replay"] = f"{chosen['id']}: {last['minutes_above_90']} min > 90%, max mem {last['max_mem_pct']}%"
                    extra["replay_rule"] = f"≤ {limit} min > 90%, mem ≤ {MEM_CAP:.0f}%"
            if "schedule" in planned or (verdict == "healthy" and reason == "BELOW_FLOOR"):
                sch, off = schedule_for(f)
                extra["schedule"] = f"{off} h/week quiet"
                if sch is None and "schedule" in planned:
                    planned = [p for p in planned if p != "schedule"]
                schedule = sch
            if "upsize" in planned:
                attempts, chosen = [], None
                for cand in cat.plans[cat.idx(row["plan_id"]) + 1:]:
                    att = replay(a, vcpu, ram, cand, 0)
                    attempts.append(att)
                    if att["passed"] and (pct(a["cpu_pct"], 99) * vcpu / cand["vcpu"]) < 70:
                        chosen = cand
                        break
                chosen = chosen or cat.plans[-1]
                target = cost_block(chosen["id"], chosen["vcpu"], chosen["ram"], row["disk_gb"], chosen["price"], row["disk_gb"] * cat.vol)
                replay_obj = {"limit_minutes_above_90": 0, "mem_cap_pct": MEM_CAP, "attempts": attempts, "passed": True, "chosen_plan": chosen["id"], "from_vcpu": int(vcpu), "from_ram_gb": int(ram)}

        # ---- options (cost after, per accepted action set: never additive)
        def add(keys, after, formula):
            after = int(round(after))
            options[option_key(keys)] = {"monthly_inr_after": after, "saving_inr": int(cur_monthly - after), "formula": formula}

        if row is not None and rtype == "vm":
            storage = row["disk_gb"] * cat.vol
            now = f"{inr(current['compute_inr'])} {row['plan_id']} + {inr(storage)} disk = {inr(cur_monthly)}"
            if target is not None and ("resize" in planned or "upsize" in planned):
                k = "resize" if "resize" in planned else "upsize"
                after = target["compute_inr"] + storage
                add([k], after, f"{now} → {inr(target['compute_inr'])} {target['plan']} + {inr(storage)} disk = {inr(after)}")
            if schedule is not None and ("schedule" in planned or reason == "BELOW_FLOOR"):
                on = schedule["on_hours_per_week"]
                comp = current["compute_inr"] * on / 168
                add(["schedule"], comp + storage, f"{now} → {inr(current['compute_inr'])} × {on}/168 h on + {inr(storage)} disk = {inr(round(comp) + storage)}")
                if target is not None and "resize" in planned:
                    comp2 = target["compute_inr"] * on / 168
                    add(["resize", "schedule"], comp2 + storage, f"{now} → {inr(target['compute_inr'])} {target['plan']} × {on}/168 h on + {inr(storage)} disk = {inr(round(comp2) + storage)}")
            if "stop" in planned:
                snap = 0
                if "snapshot" in planned:
                    used = row["disk_gb"] * (f["disk_used"]["mean"] if f.get("disk_used") else 50) / 100
                    snap = used * cat.snap
                    add(["snapshot", "stop"], storage + snap, f"{now} → {inr(storage)} disk kept + {inr(snap)} snapshot ({used:.0f} GB × ₹{cat.snap}) = {inr(storage + snap)}")
                else:
                    add(["stop"], storage, f"{now} → compute {inr(0)} while stopped + {inr(storage)} disk = {inr(storage)}")
            if "delete" in planned:  # stopped VM
                used = row["disk_gb"] * 0.6
                snap = used * cat.snap
                add(["snapshot", "delete"], snap, f"{inr(storage)} disk billed while stopped → {inr(snap)} snapshot ({used:.0f} GB × ₹{cat.snap}) after delete")
        elif row is not None and rtype == "volume":
            storage = row["disk_gb"] * cat.vol
            used_pct = f["disk_used"]["mean"] if f.get("disk_used") else 50
            used = row["disk_gb"] * used_pct / 100
            if "delete" in planned:
                snap = used * cat.snap
                add(["snapshot", "delete"], snap, f"{row['disk_gb']:.0f} GB × ₹{cat.vol} = {inr(storage)} → snapshot {used:.0f} GB × ₹{cat.snap} = {inr(snap)}")
            if "shrink_volume" in planned:
                new_gb = 100
                add(["shrink_volume"], new_gb * cat.vol, f"{row['disk_gb']:.0f} GB × ₹{cat.vol} = {inr(storage)} → {new_gb} GB × ₹{cat.vol} = {inr(new_gb * cat.vol)} ({used:.0f} GB used)")
        elif row is not None and rtype == "ip" and "release" in planned:
            add(["release"], 0, f"{inr(cat.ip)}/month public IP → {inr(0)}")

        # ---- below floor (compute changes only; orphan clean-up is always listed)
        best_key = max(options, key=lambda k: options[k]["saving_inr"])
        if verdict == "healthy" and reason == "BELOW_FLOOR":
            below["count"] += 1
            below["monthly_inr"] += max(options[best_key]["saving_inr"], 0)
            extra["floor"] = f"{inr(options[best_key]['saving_inr'])}/month"
            for k in list(options):
                if k != "none":
                    del options[k]
            schedule = None
        elif verdict == "recommend" and rtype == "vm" and planned and options[best_key]["saving_inr"] < FLOOR_INR and not ({"stop", "delete"} & set(planned)):
            verdict, reason = "healthy", "BELOW_FLOOR"
            below["count"] += 1
            below["monthly_inr"] += max(options[best_key]["saving_inr"], 0)
            options = {"none": options["none"]}
            planned, target, schedule = [], None, None
        else:
            extra["floor"] = f"{inr(options[best_key]['saving_inr'])}/month"

        if verdict in ("recommend", "upsize") and not [k for k in options if k != "none"]:
            verdict, reason, planned = "healthy", "RIGHT_SIZED", []

        default_option = option_key(planned) if verdict in ("recommend", "upsize") and option_key(planned) in options else "none"
        if verdict == "recommend" and default_option == "none":
            default_option = max(options, key=lambda k: options[k]["saving_inr"])

        # ---- evidence
        metrics_ev = None
        if f.get("has_data"):
            metrics_ev = {k: f.get(k) for k in ("cpu", "mem", "iops_pct", "net_pct", "disk_used")}
        elif rid in arrays and rtype == "volume":
            metrics_ev = {"cpu": None, "mem": None, "iops_pct": f.get("iops_pct"), "net_pct": None, "disk_used": f.get("disk_used")}
        rp = {"window_ist": f["recurring_window"], "days": f["recurring_peak_days"]} if f.get("has_data") and f.get("recurring_window") and f["recurring_peak_days"] >= 3 else None

        # naive tool: sizes on average CPU only (what an average-based tool would do)
        if verdict in ("reject", "flag") and rtype == "vm" and row is not None and f.get("has_data") and row["plan_id"] in cat.by_id:
            need_v = row["vcpu"] * f["cpu"]["mean"] / 80
            fit = [p for p in cat.plans if p["vcpu"] >= need_v]
            np_ = fit[0] if fit else None
            if np_ and np_["price"] < cat.by_id[row["plan_id"]]["price"]:
                att = replay(a, row["vcpu"], row["ram_gb"], np_, limit)
                evidence_naive = {"action": "resize", "target_plan": np_["id"], "saving_inr": int(cat.by_id[row["plan_id"]]["price"] - np_["price"]),
                                  "basis": f"average CPU {f['cpu']['mean']:.1f}%", "replay_minutes_above_90": att["minutes_above_90"]}
                if replay_obj is None:
                    replay_obj = {"limit_minutes_above_90": limit, "mem_cap_pct": MEM_CAP, "attempts": [att], "passed": False, "chosen_plan": None, "from_vcpu": int(row["vcpu"]), "from_ram_gb": int(row["ram_gb"])}
            else:
                evidence_naive = {"action": "stop" if f["cpu"]["mean"] < 5 else "none", "target_plan": None,
                                  "saving_inr": int(current["compute_inr"]) if f["cpu"]["mean"] < 5 else 0,
                                  "basis": f"average CPU {f['cpu']['mean']:.1f}%", "replay_minutes_above_90": None}
        elif verdict in ("reject", "flag") and rtype == "volume" and row is not None:
            evidence_naive = {"action": "shrink_volume", "target_plan": None, "saving_inr": int(row["disk_gb"] * cat.vol - 100 * cat.vol),
                              "basis": f"{f['disk_used']['mean']:.0f}% used today" if f.get("disk_used") else "low usage", "replay_minutes_above_90": None}

        # ---- veto + reason sentence
        g = lambda k, s: f[k][s] if f.get(k) else None
        reason_text = ""
        if verdict == "reject" and veto is None:
            if reason == "VETO_MEMORY":
                veto = {"signal": "memory", "metric": "mem p99", "value": g("mem", "p99"), "threshold": 70, "comparator": ">", "message": f"Memory-bound: memory p99 {g('mem','p99'):.1f}% > 70%. Shrinking RAM risks OOM crashes."}
            elif reason == "VETO_IOPS":
                veto = {"signal": "iops", "metric": "iops p95 % of provisioned", "value": g("iops_pct", "p95"), "threshold": 70, "comparator": ">", "message": f"Disk-bound: IOPS p95 is {g('iops_pct','p95'):.0f}% of provisioned (> 70%)."}
            elif reason == "VETO_NETWORK":
                veto = {"signal": "network", "metric": "net p95 % of bandwidth", "value": g("net_pct", "p95"), "threshold": 60, "comparator": ">", "message": f"Network is the workload: p95 {g('net_pct','p95'):.0f}% of bandwidth (> 60%) while CPU is {g('cpu','mean'):.1f}%."}
            elif reason == "VETO_LEAK":
                veto = {"signal": "leak", "metric": "sawtooth cycles", "value": f["leak_cycles"], "threshold": 3, "comparator": "≥", "message": f"Memory leak suspected: {f['leak_cycles']} climb-and-restart cycles in 30 days."}
            elif reason == "VETO_RECURRING_PEAK":
                nm = evidence_naive["replay_minutes_above_90"] if evidence_naive and evidence_naive.get("replay_minutes_above_90") is not None else None
                veto = {"signal": "recurring_peak", "metric": "days with a 30-min peak > 80%", "value": f["recurring_peak_days"], "threshold": 3, "comparator": "≥",
                        "message": f"Recurring peak at {f['recurring_window']} on {f['recurring_peak_days']} days" + (f"; an average-based resize spends {nm:,} min above 90% CPU in replay." if nm else ".")}
            elif reason == "PEAK_REPLAY_FAILED":
                nm = replay_obj["attempts"][-1] if replay_obj and replay_obj["attempts"] else None
                veto = {"signal": "replay", "metric": "minutes above 90% CPU", "value": nm["minutes_above_90"] if nm else 0, "threshold": limit, "comparator": ">",
                        "message": f"Peak Replay fails: on {nm['plan']} the last 30 days would spend {nm['minutes_above_90']:,} min above 90% CPU." if nm else "Peak Replay fails at every cheaper plan."}
            elif reason == "NO_CHEAPER_PLAN":
                need_r = row["ram_gb"] * g("mem", "p99") / MEM_TARGET
                veto = {"signal": "sizing", "metric": "RAM needed (GB)", "value": round(need_r, 1), "threshold": 16, "comparator": ">", "message": f"CPU could shrink, but memory needs {need_r:.1f} GB: no cheaper plan satisfies CPU and memory together."}
            elif reason == "VETO_GROWTH":
                days_to = (90 - (f.get("disk_last") or 0)) / max(f.get("disk_slope", 0.01), 0.01)
                veto = {"signal": "growth", "metric": "days until disk 90% full", "value": round(days_to), "threshold": 60, "comparator": "<", "message": f"Oversized today but growing {f.get('disk_slope', 0):.1f}%/day: full in about {days_to:.0f} days."}
            reason_text = veto["message"] if veto else ""
        if verdict == "exclude":
            reason_text = REASON_TEXT.get(reason, t["notes"])
        if verdict == "flag":
            msgs = {
                "ONE_OFF_PEAK": lambda: f"One event in 30 days: p99 {g('cpu','p99'):.0f}% falls to {f.get('p99_excl_top_day', 0):.0f}% without day {f.get('top_day', 0) + 1}. May be a month-end job; needs 90 days to tell.",
                "WENT_QUIET": lambda: f"Went quiet: last 7 days run at {f.get('level_shift_down', 0) * 100:.0f}% of the prior level. Confirm decommission with the owner.",
                "RESERVED_MEMORY": lambda: f"Memory flat at {g('mem','mean'):.0f}% (std {f.get('mem_std', 0):.1f}): reserved (JVM heap?), not proven used. Verify before cutting RAM.",
                "PEAK_UNDER_OBSERVED": lambda: f"Peak hours under-observed: worst hour-of-week coverage {f.get('peak_window_coverage', 0) * 100:.0f}%. Fix monitoring before sizing.",
                "IDLE_PROD": lambda: f"Idle production VM (CPU p99 {g('cpu','p99'):.1f}%): review with the owner, never auto-stop.",
                "IDLE_VOLUME_REVIEW": lambda: "Attached to a running VM but zero IOPS for 30 days: confirm it is unused.",
            }
            reason_text = msgs[reason]() if reason in msgs else t["notes"]
        if verdict == "healthy":
            if reason == "BELOW_FLOOR":
                reason_text = f"Best change saves under {inr(FLOOR_INR)}/month: not worth a human's attention."
            elif f.get("has_data") and rtype == "vm":
                reason_text = f"Right-sized: CPU p{P:g} {pct_of(f, P):.1f}%, memory p95 {g('mem','p95'):.0f}%."
                if f["mean_cpu"] is not None and f["mean_cpu"] < 20:
                    reason_text += f" Average CPU is only {f['mean_cpu']:.1f}%, but its peaks need the size."
            else:
                reason_text = "Healthy: in use as expected."
        if verdict == "recommend":
            if rtype == "vm" and f.get("has_data"):
                parts = [f"CPU p{P:g} {pct_of(f, P):.1f}% and memory p95 {g('mem','p95'):.0f}% over {f['days_of_data']:.0f} days."]
                if target is not None:
                    parts.append(f"{target['plan']} keeps replayed peaks at {replay_obj['attempts'][-1]['max_cpu_pct']:.0f}% CPU / {replay_obj['attempts'][-1]['max_mem_pct']:.0f}% memory.")
                if schedule is not None and "schedule" in planned:
                    parts.append(f"Quiet {schedule['off_hours_per_week']} h/week in IST.")
                if "stop" in planned:
                    parts.append("Idle for 30 days: stop it.")
                reason_text = " ".join(parts)
            else:
                reason_text = {
                    "ORPHAN_VOLUME": "Unattached for over 60 days: snapshot, then delete.",
                    "OVERSIZED_VOLUME": "500 GB volume with about 40 GB used: migrate to 100 GB.",
                    "UNUSED_IP": "Public IP allocated but never associated.",
                    "STOPPED_VM": "Stopped for 45 days: still paying for disk/IP.",
                }.get(reason, t["notes"])
        if verdict == "upsize":
            reason_text = f"Under-provisioned: CPU p99 {g('cpu','p99'):.0f}%. Upsize to {target['plan']} to clear the bottleneck (costs {inr(-options[option_key(['upsize'])]['saving_inr'])}/month)."

        # ---- risk (recommend + upsize only)
        if verdict in ("recommend", "upsize"):
            proj = None
            if target is not None and f.get("has_data") and target.get("vcpu"):
                proj = pct(a["cpu_pct"], 99) * row["vcpu"] / target["vcpu"]
            act = "delete" if "delete" in planned else "stop" if "stop" in planned else None
            risk = risk_for(env_eff if rtype == "vm" else (env or "prod"), tags, f, proj, act, "vm" if rtype == "vm" and f.get("has_data") else "other")

        # ---- trace
        if rtype == "vm":
            terminal = TERMINAL_STEP.get(reason, "candidate")
            if verdict == "recommend":
                terminal = "floor"
            steps = vm_trace(f, row, preset, cat, env_eff, extra)
            trace = build_trace(steps, terminal, verdict)
        else:
            trace = [
                {"step": "inventory.state", "check": "State", "value": row["state"] if row is not None else "—", "threshold": "—", "result": "info", "terminal": False},
                {"step": "noncompute.age", "check": "Unattached / unassociated since",
                 "value": (row["unattached_since"][:10] if row is not None and row["unattached_since"] else "—"), "threshold": "> 7 days", "result": "info", "terminal": False},
                {"step": "noncompute.tags", "check": "Protective tags", "value": ", ".join(tags) or "none", "threshold": "no allowlisted_ip", "result": "info", "terminal": False},
                {"step": "noncompute.decision", "check": reason, "value": extra.get("floor", "—"), "threshold": "—",
                 "result": "pass" if verdict in ("recommend", "healthy") else "fail", "terminal": True},
            ]

        formula = options[default_option]["formula"] if default_option in options else options["none"]["formula"]
        item = {
            "rec_id": f"REC-{rid}-{preset_id}",
            "resource": {
                "resource_id": rid, "name": t["name"], "type": rtype, "env": env, "team": team, "owner": team or "unowned",
                "region": row["region"] if row is not None else None, "purpose": (row["purpose"] or None) if row is not None else None,
                "service_group": (row["service_group"] or None) if row is not None else None,
                "members": [inv_by_id[m]["name"] for m in groups.get(row["service_group"], [])] if row is not None and row["service_group"] else [],
                "tags": tags, "state": row["state"] if row is not None else None, "plan_id": (row["plan_id"] or None) if row is not None else None,
            },
            "verdict": verdict,
            "reason_code": reason,
            "actions": actions_list(planned) if verdict in ("recommend", "upsize") else [],
            "default_option": default_option,
            "flags": flags,
            "current": current,
            "target": target if verdict in ("recommend", "upsize") else None,
            "schedule": schedule if verdict == "recommend" and "schedule" in planned else None,
            "options": options,
            "evidence": {
                "window_days": 30,
                "days_of_data": f.get("days_of_data", 0) if f.get("has_data") else 0,
                "coverage": f.get("coverage", 0) if f.get("has_data") else 0,
                "peak_window_coverage": f.get("peak_window_coverage"),
                "percentile_used": f"p{P:g}",
                "metrics": None if reason in ("NO_TELEMETRY", "HISTORY_TOO_SHORT") else metrics_ev,
                "recurring_peak": rp,
                "naive": evidence_naive if verdict in ("reject", "flag") else None,
            },
            "replay": replay_obj,
            "veto": veto if verdict == "reject" else None,
            "risk": risk,
            "reason": reason_text or t["notes"],
            "explanation_ai": None,
            "formula": formula,
            "trace": trace,
            "alert_ids": alerts_by_res.get(rid, []),
        }
        items.append(item)
    return items, below


# ---------------------------------------------------------------- alerts (MOCK ENGINE, real numbers)
def build_alerts(inv, feats, arrays, billing, name_of):
    alerts = []

    def add(type_, severity, rid, title, why, metric, value, threshold, window, first_seen, action, occurrences=1):
        alerts.append({
            "alert_id": f"ALT-{len(alerts) + 1:03d}", "type": type_, "severity": severity, "resource_id": rid, "name": name_of.get(rid, rid),
            "title": title, "why": why, "evidence": {"metric": metric, "value": value, "threshold": threshold, "window": window},
            "window": window, "first_seen": first_seen, "occurrences": occurrences, "suggested_action": action,
        })

    def slot_iso(i):
        return ist_iso(GRID[min(max(i, 0), N_SLOTS - 1)])

    by_name = {r["name"]: r["resource_id"] for _, r in inv.iterrows()}
    # G4 possible compromise
    rid = by_name["dev-sandbox-17"]
    a = arrays[rid]
    start = 26 * 288
    before = np.nanmean(a["net_out_mbps"][:start])
    after = np.nanmean(a["net_out_mbps"][start:])
    add("possible_compromise", "critical", rid, "Possible compromise: CPU pinned + outbound traffic surge",
        f"CPU averages {np.nanmean(a['cpu_pct'][start:]):.0f}% since 16 Oct (was {np.nanmean(a['cpu_pct'][:start]):.0f}%), and network out is {after / max(before, .01):.0f}× its normal level. Miner-like pattern on a dev sandbox.",
        "net_out_mbps", r1(after / max(before, .01)), 8, {"start": slot_iso(start), "end": slot_iso(N_SLOTS - 1)}, slot_iso(start),
        "Isolate the VM, rotate its credentials and inspect running processes.")
    # G3 level shift
    rid = by_name["prod-worker-05"]
    f = feats[rid]
    add("level_shift", "critical", rid, "Level shift: CPU 4× its normal level for 48 h",
        f"Mean CPU over the last 48 h is {f['level_shift_up']:.1f}× the prior 28 days. Excluded from sizing until understood.",
        "cpu_pct", r2(f["level_shift_up"]), 3, {"start": slot_iso(N_SLOTS - 576), "end": slot_iso(N_SLOTS - 1)}, slot_iso(N_SLOTS - 576),
        "Check recent deploys and queue depth with the owning team.")
    # G1 one-off spike vs same hour other weeks
    rid = by_name["prod-reports-02"]
    a = arrays[rid]
    hot = np.where(a["cpu_pct"] > 80)[0]
    if hot.size:
        add("spike", "warning", rid, "Unusual spike vs the same hours in other weeks",
            f"CPU held {np.nanmean(a['cpu_pct'][hot]):.0f}% for {hot.size * 5 / 60:.0f} h on {GRID[hot[0]].tz_convert(TZ):%d %b}; the same hours in other weeks sit near {np.nanmedian(a['cpu_pct']):.0f}%.",
            "cpu_pct", r1(np.nanmax(a["cpu_pct"])), "median + 4×MAD", {"start": slot_iso(hot[0]), "end": slot_iso(hot[-1])}, slot_iso(hot[0]),
            "Confirm whether this is a month-end job before the next one.")
    # G5 capacity: CPU trend
    rid = by_name["prod-api-04"]
    f = feats[rid]
    last = [v for v in f["daily_p95"] if not math.isnan(v)][-1]
    eta = (90 - last) / f["cpu_slope"] if f["cpu_slope"] > 0 else 999
    add("capacity", "critical" if eta < 7 else "warning", rid, f"CPU capacity: about {eta:.0f} days to 90%",
        f"Daily CPU p95 is rising {f['cpu_slope']:.2f} points/day (now {last:.0f}%). At this rate it reaches 90% around {(NOW + pd.Timedelta(days=eta)):%d %b}.",
        "cpu_p95_slope", r2(f["cpu_slope"]), "days to 90% < 30", {"start": slot_iso(0), "end": slot_iso(N_SLOTS - 1)}, slot_iso(14 * 288),
        "Plan an upsize or scale-out before the ETA.")
    # G5 capacity: disks (VMs with a filling disk, and the growing volume)
    for rid, f in feats.items():
        if rid.startswith("vm-") and f.get("has_data") and f.get("disk_slope", 0) > 0.5 and f.get("disk_last"):
            eta = (90 - f["disk_last"]) / f["disk_slope"]
            if eta < 60:
                add("capacity", "critical" if eta < 7 else "warning", rid, f"Disk filling: about {eta:.0f} days to 90%",
                    f"Disk used is rising {f['disk_slope']:.1f} points/day (now {f['disk_last']:.0f}%).",
                    "disk_used_pct", r2(f["disk_slope"]), "days to 90% < 60", {"start": slot_iso(0), "end": slot_iso(N_SLOTS - 1)}, slot_iso(14 * 288),
                    "Extend the volume or clean up logs before the ETA.")
    for rid, f in feats.items():
        if rid.startswith("vol-") and f.get("disk_slope", 0) > 1 and f.get("disk_last"):
            eta = (90 - f["disk_last"]) / f["disk_slope"]
            add("capacity", "critical" if eta < 7 else "warning", rid, f"Volume filling: about {eta:.0f} days to 90%",
                f"Used space is rising {f['disk_slope']:.1f} points/day (now {f['disk_last']:.0f}%). Do not shrink it.",
                "disk_used_pct", r2(f["disk_slope"]), "days to 90% < 60", {"start": slot_iso(0), "end": slot_iso(N_SLOTS - 1)}, slot_iso(14 * 288),
                "Extend before the ETA; cancel any shrink.")
    # G6 memory leak
    rid = by_name["prod-orders-08"]
    add("memory_leak", "warning", rid, "Memory leak suspected (sawtooth)",
        f"Memory climbs from about 40% to 85% and resets {feats[rid]['leak_cycles']} times in 30 days: a restart is hiding a leak.",
        "mem_pct", feats[rid]["leak_cycles"], "≥ 3 cycles", {"start": slot_iso(0), "end": slot_iso(N_SLOTS - 1)}, slot_iso(0),
        "Capture a heap dump before the next restart.")
    # G9 under-provisioned
    rid = by_name["prod-search-02"]
    add("under_provisioned", "warning", rid, "Under-provisioned: CPU p99 at 100%",
        f"CPU p99 is {feats[rid]['cpu']['p99']:.0f}% and p95 {feats[rid]['cpu']['p95']:.0f}%: requests are queueing at peak.",
        "cpu_p99", feats[rid]["cpu"]["p99"], 90, {"start": slot_iso(0), "end": slot_iso(N_SLOTS - 1)}, slot_iso(0), "Accept the upsize recommendation.")
    # G10 monitoring missing
    rid = by_name["prod-nomon-13"]
    add("monitoring_missing", "warning", rid, "Monitoring missing", "Production VM with no metrics at all for 30 days: we can't tell whether it's safe.",
        "rows", 0, "> 0", None, ist_iso(GRID[0]), "Install the monitoring agent.")
    # D9 stray series
    add("orphan_series", "info", "vm-9999", "Metrics for a machine not in the inventory",
        "vm-9999 (vm-ghost-99) reports metrics but has no inventory row: possibly an unbilled or untracked machine.",
        "rows", int((~np.isnan(arrays["vm-9999"]["cpu_pct"])).sum()) if "vm-9999" in arrays else 0, "inventory row", None, ist_iso(GRID[0]),
        "Find the owner and add it to the inventory, or shut it down.")
    # G7 team cost jump
    b = billing.copy()
    b["date"] = pd.to_datetime(b["date"])
    team_daily = b.groupby(["team", "date"]).cost_inr.sum().reset_index()
    for team, g in team_daily.groupby("team"):
        g = g.sort_values("date").set_index("date").cost_inr
        avg7 = g.rolling(7).mean().shift(1)
        jump = (g > TEAM_JUMP * avg7) & (g.index >= pd.Timestamp("2026-09-20"))
        if jump.any():
            d = jump[jump].index[0]
            new = b[(b.team == team) & (b.date == d)].resource_id.tolist()
            prev = set(b[(b.team == team) & (b.date == d - pd.Timedelta(days=1))].resource_id)
            new_names = [name_of.get(x, x) for x in new if x not in prev]
            add("team_cost_jump", "warning", None, f"Team cost jump: {team} +{(g[d] / avg7[d] - 1) * 100:.0f}% in a day",
                f"{team} spent {inr(g[d])} on {d:%d %b} vs a 7-day average of {inr(avg7[d])}. New resources: {', '.join(new_names) or 'none'}.",
                "team_daily_cost", int(g[d]), f"{TEAM_JUMP} × 7-day avg", None, f"{d:%Y-%m-%d}T00:00:00+05:30", "Confirm the new resources were planned.")
    order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda x: (order[x["severity"]], x["alert_id"]))
    return alerts



# ---------------------------------------------------------------- fixture selection
FIXTURE_METRICS = set(DEMO_5M) | {"vol-orphan-11", "vol-growing-10", "prod-gateway-03"}
FIXTURE_5M = {"prod-batch-07"}
# POST /api/whatif bodies the e2e tests send: {"env", "off": "HH:MM-HH:MM", "weekends"}
WHATIF_FIXTURES = [("dev", "20:00-08:00", True), ("dev", "22:00-06:00", False), ("staging", "20:00-08:00", True),
                   ("staging", "20:00-08:00", False), ("nonprod", "20:00-08:00", True)]


def whatif_key(env, off, weekends):
    return f"{env}_{off.replace(':', '').replace('-', '_')}_{int(bool(weekends))}"

# Cloud Carbon Footprint coefficients (PLAN §11.7)
CARBON = {"w_per_vcpu_min": 0.74, "w_per_vcpu_max": 3.5, "w_per_gb_ram": 0.392, "pue": 1.4, "kg_co2_per_kwh": 0.71,
          "source": "Cloud Carbon Footprint methodology; India grid factor from CEA"}

THRESHOLDS = [
    {"name": "Lookback", "value": "30 days", "why": "Above AWS Compute Optimizer's 14-day minimum; catches weekly cycles"},
    {"name": "Percentile", "value": "p99 prod, p95 non-prod", "why": "AWS default is p99.5; p99 is the conservative read"},
    {"name": "CPU target after resize", "value": "70% prod, 80% non-prod", "why": "≈ AWS 20–30% headroom"},
    {"name": "Memory target / hard cap", "value": "p99 ≤ 75%, no sample > 95%", "why": "Memory shortfalls crash (OOM); CPU shortfalls only slow"},
    {"name": "Peak Replay limit", "value": "0 min > 90% prod, ≤ 30 min/month non-prod", "why": "Hard safety gate over all 8,640 samples"},
    {"name": "Idle", "value": "CPU < 5%, net < 5 MB/h, IOPS p95 < 5", "why": "Industry consensus (Datadog, Azure Advisor)"},
    {"name": "Underused", "value": "CPU < 40% and memory < 50%", "why": "Leaves room after headroom"},
    {"name": "Vetoes", "value": "memory 70%, IOPS 70%, network 60%", "why": "Any one blocks shrinking"},
    {"name": "Minimum data", "value": "14 days; coverage ≥ 80%", "why": "AWS minimum + our quality gate"},
    {"name": "Orphan age", "value": "7 days", "why": "Avoids catching resources mid-setup"},
    {"name": "Stopped VM", "value": "> 30 days", "why": "Not a maintenance stop"},
    {"name": "Saving floor", "value": "₹500/month (compute changes)", "why": "Not worth human attention below this; orphan clean-up is always listed"},
    {"name": "Prod step", "value": "one plan down per change", "why": "Small, reversible moves"},
    {"name": "Comparisons", "value": "strict < / >", "why": "A value exactly on a threshold does not trigger it (staging-api-09)"},
]


# ---------------------------------------------------------------- what-if (POST /api/whatif)
WHATIF_BUSY_PCT = 5


def whatif_mask(start, end, weekends):
    out = []
    for i in range(168):
        d, h = divmod(i, 24)
        if weekends and d >= 5:
            out.append(True)
        elif start == end:
            out.append(False)
        else:
            out.append(start <= h < end if start < end else (h >= start or h < end))
    return out


def describe_hours(idx):
    per_day: dict[int, list[int]] = {}
    for i in idx:
        per_day.setdefault(i // 24, []).append(i % 24)
    by_range: dict[str, list[int]] = {}
    for d, hours in per_day.items():
        ranges, s0, prev = [], hours[0], hours[0]
        for h in hours[1:] + [-1]:
            if h != prev + 1:
                ranges.append(f"{s0:02d}:00–{(prev + 1) % 24:02d}:00")
                s0 = h
            prev = h
        by_range.setdefault(", ".join(ranges).replace("00:00–00:00", "all day"), []).append(d)
    parts = []
    for r, days in by_range.items():
        consecutive = all(days[i] == days[i - 1] + 1 for i in range(1, len(days)))
        label = DAYS[days[0]] if len(days) == 1 else (f"{DAYS[days[0]]}–{DAYS[days[-1]]}" if consecutive else ", ".join(DAYS[x] for x in days))
        parts.append(f"{label} {r}")
    return "; ".join(parts)


def run_whatif(vms, env, off_str, weekends):
    start, end = (int(x.split(":")[0]) for x in off_str.split("-"))
    mask = whatif_mask(start, end, weekends)
    off = sum(mask)
    rows = []
    for vm in vms:
        if not (vm["env"] in ("dev", "staging") if env == "nonprod" else vm["env"] == env):
            continue
        saving = round(vm["compute_inr"] * off / 168)
        base = {k: vm[k] for k in ("resource_id", "name", "env", "team", "plan_id")}
        if vm["optimize_policy"] == "no_schedule" or "keep_running" in vm["tags"]:
            rows.append({**base, "status": "excluded", "saving_inr": 0, "busy_off_hours": 0,
                         "note": "keep_running tag" if "keep_running" in vm["tags"] else "policy no_schedule"})
            continue
        busy = [i for i, o in enumerate(mask) if o and (vm["how_busy"][i] or 0) >= WHATIF_BUSY_PCT]
        if not busy:
            rows.append({**base, "status": "safe", "saving_inr": saving, "busy_off_hours": 0, "note": "quiet in every week of the window"})
        else:
            note = (f"busy around the clock: CPU ≥ {WHATIF_BUSY_PCT}% in {len(busy)} of {off} off hours" if len(busy) / max(off, 1) > 0.8
                    else f"busy {describe_hours(busy)}")
            rows.append({**base, "status": "disrupted", "saving_inr": saving, "busy_off_hours": len(busy), "note": note})
    order = {"disrupted": 0, "safe": 1, "excluded": 2}
    rows.sort(key=lambda r: (order[r["status"]], -r["saving_inr"]))
    return {
        "input": {"env": env, "off": off_str, "weekends": weekends},
        "off_hours_per_week": off,
        "rows": rows,
        "safe_saving_inr": sum(r["saving_inr"] for r in rows if r["status"] == "safe"),
        "blind_saving_inr": sum(r["saving_inr"] for r in rows if r["status"] != "excluded"),
        "disrupted": sum(r["status"] == "disrupted" for r in rows),
        "excluded": sum(r["status"] == "excluded" for r in rows),
    }


# ---------------------------------------------------------------- forecast + carbon (GET /api/forecast)
def holt_winters(y, m=7, alpha=0.3, beta=0.05, gamma=0.2, h=90):
    """Additive Holt-Winters with a weekly season; returns (forecast, residual std)."""
    y = list(y)
    level = float(np.mean(y[:m]))
    trend = float((np.mean(y[m:2 * m]) - np.mean(y[:m])) / m)
    season = [y[i] - level for i in range(m)]
    resid = []
    for t, v in enumerate(y):
        s_ = season[t % m]
        if t >= 2 * m:
            resid.append(v - (level + trend + s_))
        prev = level
        level = alpha * (v - s_) + (1 - alpha) * (level + trend)
        trend = beta * (level - prev) + (1 - beta) * trend
        season[t % m] = gamma * (v - level) + (1 - gamma) * s_
    fc = [level + (k + 1) * trend + season[(len(y) + k) % m] for k in range(h)]
    return fc, float(np.std(resid)) if resid else 0.0


def vm_kwh_month(vcpu, ram_gb, util_pct, on_fraction=1.0):
    c = CARBON
    w = vcpu * (c["w_per_vcpu_min"] + min(util_pct, 100) / 100 * (c["w_per_vcpu_max"] - c["w_per_vcpu_min"])) + ram_gb * c["w_per_gb_ram"]
    return w * c["pue"] * HOURS_PER_MONTH / 1000 * on_fraction


def carbon_by_option(item, feats):
    """kWh and kg CO2 saved per month for each option of a VM recommendation (volumes/IPs: 0)."""
    out = {}
    cur = item["current"]
    if item["resource"]["type"] != "vm" or not cur.get("vcpu") or item["resource"]["state"] != "running":
        return {k: {"kwh_month": 0.0, "kg_co2_month": 0.0} for k in item["options"]}
    f = feats.get(item["resource"]["resource_id"], {})
    util = (f.get("cpu") or {}).get("mean") or 10.0
    before = vm_kwh_month(cur["vcpu"], cur["ram_gb"], util)
    on = (item["schedule"] or {}).get("on_hours_per_week", 168) / 168
    tgt = item["target"]
    for k in item["options"]:
        acts = set(k.split("+")) if k != "none" else set()
        if acts & {"stop", "delete"}:
            after = 0.0
        else:
            vcpu, ram = (tgt["vcpu"], tgt["ram_gb"]) if tgt and acts & {"resize", "upsize"} else (cur["vcpu"], cur["ram_gb"])
            u = util * cur["vcpu"] / vcpu
            after = vm_kwh_month(vcpu, ram, u, on if "schedule" in acts else 1.0)
        kwh = round(before - after, 1)
        out[k] = {"kwh_month": kwh, "kg_co2_month": round(kwh * CARBON["kg_co2_per_kwh"], 1)}
    return out


# ---------------------------------------------------------------- scorecard (GET /api/scorecard)
CLEANUP_CODES = {"IDLE", "ORPHAN_VOLUME", "UNUSED_IP", "STOPPED_VM"}


def score(items, truth_rows):
    by_id = {i["resource"]["resource_id"]: i for i in items}
    correct, mismatches, arch, wrongly, found, expected = 0, [], {}, [], 0, 0
    for t in truth_rows:
        r = by_id.get(t["resource_id"])
        ok = bool(r) and r["verdict"] == t["expected_verdict"] and r["reason_code"] == t["expected_reason_code"]
        correct += ok
        if not ok:
            mismatches.append({"name": t["name"], "expected": f"{t['expected_verdict']}/{t['expected_reason_code']}",
                               "got": f"{r['verdict']}/{r['reason_code']}" if r else "missing"})
        a = arch.setdefault(t["archetype"], {"archetype": t["archetype"], "total": 0, "correct": 0, "labels": set()})
        a["total"] += 1
        a["correct"] += ok
        a["labels"].add((t["expected_verdict"], t["expected_reason_code"]))
        if r and t["expected_verdict"] in ("reject", "flag", "exclude") and r["verdict"] == "recommend":
            wrongly.append(t["name"])
        if t["expected_reason_code"] in CLEANUP_CODES:
            expected += 1
            found += bool(r) and r["verdict"] == "recommend"
    by_verdict = []
    for v in ["recommend", "reject", "flag", "exclude", "healthy", "upsize"]:
        exp = sum(t["expected_verdict"] == v for t in truth_rows)
        pred = sum(i["verdict"] == v for i in items)
        c = sum(t["expected_verdict"] == v and by_id.get(t["resource_id"], {}).get("verdict") == v for t in truth_rows)
        by_verdict.append({"verdict": v, "expected": exp, "predicted": pred, "correct": c,
                           "precision": c / pred if pred else 1.0, "recall": c / exp if exp else 1.0})
    unsafe = sum(1 for i in items if i["verdict"] == "recommend" and i["target"] and i["replay"] and not i["replay"]["passed"])
    return {
        "total": len(truth_rows), "correct": correct, "accuracy": correct / len(truth_rows) if truth_rows else 0.0,
        "by_verdict": by_verdict, "by_archetype": archetype_scores(arch, items, by_id, truth_rows),
        "unsafe_downsizes": unsafe + len(wrongly), "wrongly_shrunk": wrongly,
        "cleanup_recall": {"found": found, "expected": expected}, "mismatches": mismatches,
    }


def archetype_scores(arch, items, by_id, truth_rows):
    """recall = correct / archetype size.
    precision = correct / (correct + false positives), where a false positive is any resource the
    engine gave one of this archetype's expected (verdict, reason) labels while its truth label is not one of them."""
    truth_by_id = {t["resource_id"]: (t["expected_verdict"], t["expected_reason_code"]) for t in truth_rows}
    out = []
    for a in arch.values():
        labels = a["labels"]
        fp = sum(1 for i in items if (i["verdict"], i["reason_code"]) in labels and truth_by_id.get(i["resource"]["resource_id"]) not in labels)
        out.append({"archetype": a["archetype"], "total": a["total"], "correct": a["correct"],
                    "precision": a["correct"] / (a["correct"] + fp) if a["correct"] + fp else 1.0,
                    "recall": a["correct"] / a["total"] if a["total"] else 1.0})
    return sorted(out, key=lambda x: -x["total"])


# ---------------------------------------------------------------- data quality: injected vs detected
def dq_checks(dq):
    by = {r["name"]: r for r in dq["resources"]}
    faults = lambda f: [x for x in dq["faults"] if x["fault"] == f]
    names = lambda f: ", ".join(x["name"] for x in faults(f))
    t = dq["totals"]
    pct = lambda v: f"{(v or 0) * 100:.1f}%"
    api02, f18, f19, b20 = by.get("prod-api-02", {}), by.get("dev-flaky-18", {}), by.get("staging-flaky-19", {}), by.get("prod-batch-20", {})
    oor_expected = len(faults("out_of_range")) * 10
    return [
        {"id": "E1", "fault": "6-hour monitoring gap", "where": "prod-api-02", "injected": "72 rows", "detected": f"longest gap {api02.get('longest_gap_hours', 0)} h",
         "handling": "kept as missing, never 0; not called idle", "ok": api02.get("longest_gap_hours", 0) >= 6},
        {"id": "E2", "fault": "Duplicate timestamps (agent re-send)", "where": names("duplicate_block"), "injected": "12 rows", "detected": f"{t['duplicates']} removed",
         "handling": "de-duplicated, first kept", "ok": t["duplicates"] == 12},
        {"id": "E3", "fault": "CPU outside 0–100%", "where": names("out_of_range"), "injected": f"{oor_expected} values", "detected": f"{t['out_of_range']} dropped",
         "handling": "set to missing", "ok": t["out_of_range"] == oor_expected},
        {"id": "E4", "fault": "Rows out of order", "where": names("out_of_order"), "injected": f"{len(faults('out_of_order'))} blocks of 20",
         "detected": f"{t['out_of_order']} inversions", "handling": "sorted", "ok": t["out_of_order"] > 0},
        {"id": "E5", "fault": "Reboot gaps + random drops", "where": f"{len(faults('reboot_gap'))} VMs + all", "injected": f"{len(faults('reboot_gap'))} × 20 min, 0.5% drops",
         "detected": "tolerated", "handling": "coverage stays ≥ 95%", "ok": True},
        {"id": "E6", "fault": "Coverage ~70%", "where": "dev-flaky-18", "injected": "30% of hours", "detected": pct(f18.get("coverage")),
         "handling": "excluded: below the 80% gate", "ok": (f18.get("coverage") or 1) < 0.8},
        {"id": "E7", "fault": "Coverage ~88%", "where": "staging-flaky-19", "injected": "12% of hours", "detected": pct(f19.get("coverage")),
         "handling": "evaluated, confidence Medium", "ok": 0.8 <= (f19.get("coverage") or 0) < 0.95},
        {"id": "E8", "fault": "Stuck agent (0.0 for 48 h)", "where": names("flatline_48h"), "injected": "576 rows", "detected": f"{t['flatline_slots']} slots",
         "handling": "flatline → missing, so it never looks idle", "ok": t["flatline_slots"] >= 576},
        {"id": "E9", "fault": "Gap on the peak window", "where": "prod-batch-20", "injected": "01:00–04:00 on 18 nights",
         "detected": f"peak-hour coverage {(b20.get('peak_window_coverage') or 0) * 100:.0f}%", "handling": "flagged: peak hours under-observed",
         "ok": (b20.get("peak_window_coverage") or 1) < 0.5},
        {"id": "E10", "fault": "Irregular timestamps (05:03)", "where": names("ts_jitter"), "injected": "1 day offset +3 min",
         "detected": f"{t['irregular_ts']} snapped", "handling": "floored to the 5-minute grid", "ok": t["irregular_ts"] > 0},
        {"id": "D9", "fault": "Metrics without inventory", "where": ", ".join(x["name"] for x in dq["not_in_inventory"]), "injected": "1 series",
         "detected": f"{len(dq['not_in_inventory'])} found", "handling": "listed; never priced or sized", "ok": len(dq["not_in_inventory"]) == 1},
    ]


# ---------------------------------------------------------------- main
def main():
    inv, pricing, truth, faults, metrics, vmetrics, billing = load()
    cat = Catalogue(pricing)
    # clear the contents, not the folder itself (Windows refuses while a shell or editor has it open)
    if OUT.exists():
        for child in OUT.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
    for d in ("metrics", "recommendations", "replay", "whatif", "resources"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    metric_docs: dict[str, dict] = {}

    name_of = dict(zip(truth.resource_id, truth.name))
    inv_by_id = {r["resource_id"]: r for _, r in inv.iterrows()}

    # current monthly cost per resource: the last billed day x 730/24 (authoritative), rounded to ₹1
    b = billing.copy()
    b["date"] = pd.to_datetime(b["date"])
    lastday = b[b.date == b.date.max()].set_index("resource_id").cost_inr
    current_cost = {rid: int(round(v * HOURS_PER_MONTH / 24)) for rid, v in lastday.items()}
    for rid in inv.resource_id:
        current_cost.setdefault(rid, 0)
    # sanity: catalogue VMs bill as plan + disk
    for rid, r in inv_by_id.items():
        if r["type"] == "vm" and r["state"] == "running" and r["plan_id"] in cat.by_id:
            expect = cat.by_id[r["plan_id"]]["price"] + r["disk_gb"] * cat.vol
            assert abs(expect - current_cost[rid]) <= 1, (rid, expect, current_cost[rid])

    # ---- clean + features + metrics files
    arrays, feats, dq = {}, {}, []
    vm_cols = ["cpu_pct", "mem_pct", "disk_used_pct", "iops", "net_in_mbps", "net_out_mbps"]
    for rid, df in metrics.groupby("resource_id", observed=True):
        a, rep = clean(df[["ts"] + vm_cols].copy(), vm_cols, ["cpu_pct", "mem_pct", "disk_used_pct"], flatline=True)
        flat = a.pop("_flat")
        row = inv_by_id.get(rid)
        f = vm_features(a, row)
        arrays[rid], feats[rid] = a, f
        gaps = []
        if f["has_data"]:
            miss = np.isnan(a["cpu_pct"]) & ~flat
            miss[: f["first_slot"]] = False
            miss[f["last_slot"] + 1:] = False
            for s, e in runs(miss, 6):
                gaps.append({"start": ist_iso(GRID[s]), "end": ist_iso(GRID[e - 1] + pd.Timedelta(minutes=5)), "kind": "missing", "hours": round((e - s) / 12, 1)})
            for s, e in runs(flat, 24):
                gaps.append({"start": ist_iso(GRID[s]), "end": ist_iso(GRID[e - 1] + pd.Timedelta(minutes=5)), "kind": "flatline", "hours": round((e - s) / 12, 1)})
        series = {}
        for key, col in [("cpu", "cpu_pct"), ("mem", "mem_pct"), ("disk_used", "disk_used_pct"), ("iops", "iops"), ("net_in", "net_in_mbps"), ("net_out", "net_out_mbps")]:
            m, x = hourly(a[col])
            series[key] = {"mean": m, "max": x}
        metric_docs[rid] = {"series": series, "gaps": gaps}
        longest = max([g["hours"] for g in gaps if g["kind"] == "missing"], default=0)
        dq.append({"resource_id": rid, "name": name_of.get(rid, rid), "type": "vm", "in_inventory": row is not None, **rep,
                   "expected_slots": (f["last_slot"] - f["first_slot"] + 1) if f["has_data"] else 0,
                   "coverage": f.get("coverage"), "peak_window_coverage": f.get("peak_window_coverage"),
                   "days_of_data": f.get("days_of_data"), "longest_gap_hours": longest,
                   "gaps": len([g for g in gaps if g["kind"] == "missing"])})

    for rid, df in vmetrics.groupby("resource_id", observed=True):
        a, rep = clean(df[["ts", "iops", "disk_used_pct"]].copy(), ["iops", "disk_used_pct"], ["disk_used_pct"], flatline=False)
        a.pop("_flat", None)
        row = inv_by_id[rid]
        iops_pct = a["iops"] / row["provisioned_iops"] * 100
        dd = np.array([np.nanmean(a["disk_used_pct"][d * 288:(d + 1) * 288]) for d in range(30)])
        ok = ~np.isnan(dd)
        f = {"has_data": False, "iops_pct": stats(iops_pct), "disk_used": stats(a["disk_used_pct"]),
             "disk_slope": float(np.polyfit(np.arange(30)[ok], dd[ok], 1)[0]), "disk_last": float(dd[ok][-1]),
             "daily": [r1(v) for v in dd], "coverage": round(float((~np.isnan(a["disk_used_pct"])).mean()), 3)}
        arrays[rid], feats[rid] = a, f
        series = {}
        for key, col in [("iops", "iops"), ("disk_used", "disk_used_pct")]:
            m, x = hourly(a[col])
            series[key] = {"mean": m, "max": x}
        metric_docs[rid] = {"series": series, "gaps": []}
        dq.append({"resource_id": rid, "name": name_of.get(rid, rid), "type": "volume", "in_inventory": True, **rep,
                   "expected_slots": N_SLOTS, "coverage": f["coverage"], "peak_window_coverage": None, "days_of_data": 30.0,
                   "longest_gap_hours": 0, "gaps": 0, "flatline_slots": 0})

    # ---- alerts, then recommendations (which link alert ids)
    alerts = build_alerts(inv, feats, arrays, billing, name_of)
    alerts_by_res: dict[str, list[str]] = {}
    for al in alerts:
        if al["resource_id"]:
            alerts_by_res.setdefault(al["resource_id"], []).append(al["alert_id"])
    jdump(OUT / "alerts.json", {"mock_engine": True, "items": alerts})

    window = {"start": ist_iso(GRID[0]), "end": ist_iso(GRID[-1] + pd.Timedelta(minutes=5)), "timezone": TZ}
    cfg_hash = hashlib.sha256(json.dumps(PRESETS, sort_keys=True).encode()).hexdigest()[:12]
    recs_by_preset = {}
    for pid in PRESETS:
        items, below = build_recs(pid, inv, truth, feats, arrays, cat, current_cost, alerts_by_res)
        recs_by_preset[pid] = items
        jdump(OUT / "recommendations" / f"{pid}.json", {
            "schema_version": "1.0", "generated_at": NOW.isoformat(),
            "preset": pid, "config_hash": cfg_hash, "mock_engine": True, "data_window": window, "items": items, "below_floor": below})
        # GET /api/resources/{id}/replay?preset=  (server-side projection, hourly max)
        for it in items:
            rp = it["replay"]
            if not rp or it["resource"]["type"] != "vm" or it["resource"]["resource_id"] not in metric_docs:
                continue
            to_plan = rp["chosen_plan"] or (it["evidence"]["naive"] or {}).get("target_plan") or (rp["attempts"][-1]["plan"] if rp["attempts"] else None)
            if not to_plan or to_plan not in cat.by_id:
                continue
            to_vcpu = cat.by_id[to_plan]["vcpu"]
            actual = metric_docs[it["resource"]["resource_id"]]["series"]["cpu"]["max"]
            ratio = rp["from_vcpu"] / to_vcpu
            jdump(OUT / "replay" / pid / f"{it['resource']['resource_id']}.json", {
                "resource_id": it["resource"]["resource_id"], "preset": pid, "from_plan": it["current"]["plan"], "to_plan": to_plan,
                "from_vcpu": rp["from_vcpu"], "to_vcpu": to_vcpu, "step_seconds": 3600, "start": GRID[0].isoformat(),
                "actual_cpu": actual, "projected_cpu": [None if v is None else round(v * ratio, 1) for v in actual],
                "limit_minutes_above_90": rp["limit_minutes_above_90"], "mem_cap_pct": rp["mem_cap_pct"],
                "attempts": rp["attempts"], "passed": rp["passed"],
            })

    # ---- resources (fleet table)
    resources = []
    for _, r in inv.iterrows():
        rid = r["resource_id"]
        f = feats.get(rid)
        st, daily, dmax = None, None, None
        if f and r["type"] == "vm" and f.get("has_data"):
            st = {"cpu_p95": f["cpu"]["p95"], "cpu_p99": f["cpu"]["p99"], "cpu_mean": f["cpu"]["mean"], "mem_p95": f["mem"]["p95"], "mem_p99": f["mem"]["p99"], "coverage": f["coverage"]}
            daily = [r1(v) for v in f["daily_p95"]]
            dmax = [r1(v) for v in f["daily_max"]]
        elif f and r["type"] == "volume":
            st = {"cpu_p95": None, "cpu_p99": None, "cpu_mean": None, "mem_p95": None, "mem_p99": None, "coverage": f["coverage"]}
            daily = f["daily"]
        resources.append({
            **{k: (none_if_nan(r[k]) if not isinstance(r[k], str) else (r[k] or None)) for k in
               ["resource_id", "name", "type", "region", "env", "owner_team", "purpose", "service_group", "plan_id", "vcpu", "ram_gb", "disk_gb",
                "provisioned_iops", "bandwidth_mbps", "state", "stopped_since", "created_at", "last_resized_at", "attached_to", "unattached_since", "optimize_policy"]},
            "tags": r["tags"].split(";") if r["tags"] else [],
            "monthly_inr": current_cost.get(rid, 0),
            "has_metrics": rid in arrays,
            "stats": st,
            "daily_p95": daily,
            "daily_max": dmax,
        })
    jdump(OUT / "resources.json", resources)

    # GET /api/resources/{id}: inventory + features + trace (default preset) + data-quality report
    rec_default = {i["resource"]["resource_id"]: i for i in recs_by_preset["default"]}
    dq_by_id = {d["resource_id"]: d for d in dq}
    feature_keys = ["cpu", "mem", "iops_pct", "net_pct", "disk_used", "coverage", "peak_window_coverage", "days_of_data", "cpu_slope", "disk_slope",
                    "level_shift_up", "level_shift_down", "recurring_peak_days", "recurring_window", "p99_excl_top_day", "mem_std", "leak_cycles", "how_p95"]
    for row_doc in resources:
        rid = row_doc["resource_id"]
        f = feats.get(rid) or {}
        features = {k: (None if isinstance(f.get(k), float) and math.isnan(f[k]) else f.get(k)) for k in feature_keys} if f else None
        jdump(OUT / "resources" / f"{rid}.json", {"resource": row_doc, "features": features,
                                                  "trace": rec_default[rid]["trace"] if rid in rec_default else [], "dq": dq_by_id.get(rid)})

    # GET /api/resources/{id}/metrics?metric=&step=1h|5m: only the resources the e2e tests open
    # (keeps fixtures small). A test that opens another resource fails with "missing API fixture".
    wanted = {r for r, n in name_of.items() if n in FIXTURE_METRICS} | {al["resource_id"] for al in alerts if al["resource_id"]}
    for rid in sorted(wanted):
        if rid not in metric_docs or rid not in inv_by_id:
            continue
        doc = metric_docs[rid]
        for metric, sr in doc["series"].items():
            jdump(OUT / "metrics" / rid / f"{metric}_1h.json", {"resource_id": rid, "metric": metric, "step_seconds": 3600, "start": GRID[0].isoformat(),
                                                                 "mean": sr["mean"], "max": sr["max"], "gaps": doc["gaps"]})
        if name_of.get(rid) in FIXTURE_5M:
            for metric, col in [("cpu", "cpu_pct"), ("mem", "mem_pct"), ("disk_used", "disk_used_pct"), ("iops", "iops"), ("net_in", "net_in_mbps"), ("net_out", "net_out_mbps")]:
                vals = [r1(v) for v in arrays[rid][col]]
                jdump(OUT / "metrics" / rid / f"{metric}_5m.json", {"resource_id": rid, "metric": metric, "step_seconds": 300, "start": GRID[0].isoformat(),
                                                                     "mean": vals, "max": vals, "gaps": doc["gaps"]})

    # ---- billing
    b["env"] = b["env"].fillna("").replace("", "untagged")
    b["team"] = b["team"].fillna("").replace("", "unowned")
    dates = sorted(b.date.unique())
    day_index = {d: i for i, d in enumerate(dates)}

    def by(col):
        out = {}
        for k, g in b.groupby(col):
            arr = [0.0] * len(dates)
            for d, v in g.groupby("date").cost_inr.sum().items():
                arr[day_index[d]] = round(float(v), 2)
            out[str(k)] = arr
        return out

    first = b[b.date < b.date.min() + pd.Timedelta(days=30)]
    last30 = b[b.date > b.date.max() - pd.Timedelta(days=30)]

    def agg(df):
        return {"total": int(round(df.cost_inr.sum())),
                **{f"by_{c}": {str(k): int(round(v)) for k, v in df.groupby(c).cost_inr.sum().items()} for c in ["team", "env", "type", "region"]}}

    created = inv.assign(created=pd.to_datetime(inv.created_at, utc=True).dt.tz_convert(TZ))
    first_end = (b.date.min() + pd.Timedelta(days=30)).tz_localize(TZ)
    new_res = created[created.created >= first_end]
    new_ids = set(new_res.resource_id)
    run_rate = int(sum(current_cost[r] for r in inv.resource_id))

    # potential (Default preset): every recommendation's default option accepted
    def potential_after(rec):
        o = rec["options"][rec["default_option"]]
        return o["monthly_inr_after"] if rec["verdict"] == "recommend" and o["saving_inr"] > 0 else rec["current"]["monthly_inr"]
    pot_after = {i["resource"]["resource_id"]: potential_after(i) for i in recs_by_preset["default"]}
    potential_after_inr = int(sum(pot_after.values()))
    inv_env = {r.resource_id: (r.env or "untagged") for r in inv.itertuples()}
    inv_team = {r.resource_id: (r.owner_team or "unowned") for r in inv.itertuples()}
    inv_region = {r.resource_id: r.region for r in inv.itertuples()}

    def split(keyf):
        out = {}
        for rid in inv.resource_id:
            k = keyf[rid]
            d = out.setdefault(k, {"monthly_before_inr": 0, "potential_after_inr": 0})
            d["monthly_before_inr"] += current_cost[rid]
            d["potential_after_inr"] += pot_after.get(rid, current_cost[rid])
        return out

    def deltas(col):
        f_ = b[b.date < b.date.min() + pd.Timedelta(days=30)].groupby(col).cost_inr.sum()
        l_ = b[b.date > b.date.max() - pd.Timedelta(days=30)].groupby(col).cost_inr.sum()
        keys = sorted(set(f_.index) | set(l_.index))
        rows = [{"key": str(k), "first30_inr": int(round(f_.get(k, 0))), "last30_inr": int(round(l_.get(k, 0)))} for k in keys]
        for r in rows:
            r["delta_inr"] = r["last30_inr"] - r["first30_inr"]
        return sorted(rows, key=lambda r: -r["delta_inr"])

    b["age"] = np.where(b.resource_id.isin(new_ids), "new resources", "existing resources")
    verdict_counts = {}
    for i in recs_by_preset["default"]:
        verdict_counts[i["verdict"]] = verdict_counts.get(i["verdict"], 0) + 1
    counts_ = inv.type.value_counts().to_dict()
    jdump(OUT / "summary.json", {
        "monthly_before_inr": run_rate,
        "potential_after_inr": potential_after_inr,
        "potential_saving_pct": round((run_rate - potential_after_inr) / run_rate * 100, 2),
        "by_env": split(inv_env), "by_team": split(inv_team), "by_region": split(inv_region),
        "counts": {"vm": int(counts_.get("vm", 0)), "volume": int(counts_.get("volume", 0)), "ip": int(counts_.get("ip", 0)), "verdicts": verdict_counts},
        "bill_trend_6m": {
            "dates": [f"{pd.Timestamp(d):%Y-%m-%d}" for d in dates],
            "total": [round(float(v), 2) for v in b.groupby("date").cost_inr.sum().reindex(dates).to_numpy()],
            "by_env": by("env"), "by_team": by("team"),
        },
        "growth_waterfall": {
            "first30": {"start": f"{dates[0]:%Y-%m-%d}", "total_inr": int(round(first.cost_inr.sum()))},
            "last30": {"end": f"{dates[-1]:%Y-%m-%d}", "total_inr": int(round(last30.cost_inr.sum()))},
            "growth_ratio": round(last30.cost_inr.sum() / first.cost_inr.sum(), 4),
            "by_env": deltas("env"), "by_team": deltas("team"), "by_age": deltas("age"),
            "new_resources": [{"resource_id": r.resource_id, "name": r.name, "team": r.owner_team or "unowned", "env": r.env or "untagged",
                               "type": r.type, "created_at": r.created_at, "monthly_inr": current_cost.get(r.resource_id, 0)} for r in new_res.itertuples()],
        },
    })

    # ---- GET /api/forecast?days=90 (Holt-Winters, weekly season) + carbon per option
    daily_total = b.groupby("date").cost_inr.sum().reindex(dates).to_numpy()
    fc, sd = holt_winters(daily_total, h=90)
    fc_dates = [f"{pd.Timestamp(dates[-1]) + pd.Timedelta(days=k + 1):%Y-%m-%d}" for k in range(90)]
    by_option = {}
    for pid, items in recs_by_preset.items():
        for it in items:
            if it["verdict"] in ("recommend", "upsize"):
                by_option[it["rec_id"]] = carbon_by_option(it, feats)
    fleet_kwh = sum(vm_kwh_month(r.vcpu, r.ram_gb, (feats.get(r.resource_id, {}).get("cpu") or {}).get("mean") or 10.0)
                    for r in inv.itertuples() if r.type == "vm" and r.state == "running" and not math.isnan(r.vcpu))
    pot_kwh = sum(by_option[i["rec_id"]][i["default_option"]]["kwh_month"] for i in recs_by_preset["default"] if i["verdict"] == "recommend")
    jdump(OUT / "forecast_90.json", {
        "days": 90,
        "method": "Holt-Winters additive, weekly season, fitted on 180 days of daily cost",
        "monthly_now_inr": run_rate,
        "history": {"dates": [f"{pd.Timestamp(d):%Y-%m-%d}" for d in dates[-60:]], "total": [round(float(v), 2) for v in daily_total[-60:]]},
        "forecast": {"dates": fc_dates, "baseline": [round(v, 2) for v in fc],
                     "lower": [round(v - 1.96 * sd * math.sqrt(k + 1), 2) for k, v in enumerate(fc)],
                     "upper": [round(v + 1.96 * sd * math.sqrt(k + 1), 2) for k, v in enumerate(fc)]},
        "carbon": {"coefficients": CARBON, "fleet_kwh_month": round(fleet_kwh, 1), "fleet_kg_co2_month": round(fleet_kwh * CARBON["kg_co2_per_kwh"], 1),
                   "potential_kwh_month": round(pot_kwh, 1), "potential_kg_co2_month": round(pot_kwh * CARBON["kg_co2_per_kwh"], 1),
                   "by_option": by_option},
    })

    # ---- POST /api/whatif: responses for the inputs the e2e tests send
    wi_vms = []
    for _, r in inv.iterrows():
        f = feats.get(r["resource_id"])
        if r["type"] == "vm" and r["state"] == "running" and f and f.get("has_data") and r["plan_id"] in cat.by_id:
            wi_vms.append({"resource_id": r["resource_id"], "name": r["name"], "env": r["env"] or "untagged", "team": r["owner_team"] or "unowned",
                           "plan_id": r["plan_id"], "compute_inr": cat.by_id[r["plan_id"]]["price"], "optimize_policy": r["optimize_policy"],
                           "tags": r["tags"].split(";") if r["tags"] else [], "how_busy": f["how_busy"]})
    for env_, off_, wk in WHATIF_FIXTURES:
        jdump(OUT / "whatif" / f"{whatif_key(env_, off_, wk)}.json", run_whatif(wi_vms, env_, off_, wk))

    # ---- GET /api/data-quality (with the injected-vs-detected reconciliation)
    fault_counts = faults.groupby("fault").size().to_dict()
    metric_ids = set(arrays)
    dq_doc = {
        "resources": dq,
        "faults": [{"resource_id": r.resource_id, "name": r.name, "fault": r.fault, "detail": r.detail} for r in faults.itertuples()],
        "fault_counts": {k: int(v) for k, v in fault_counts.items()},
        "not_in_inventory": [{"resource_id": x, "name": name_of.get(x, x)} for x in sorted(metric_ids - set(inv.resource_id))],
        "no_metrics": [{"resource_id": r.resource_id, "name": r.name, "state": r.state} for r in inv.itertuples()
                       if r.type in ("vm", "volume") and r.resource_id not in metric_ids],
        "totals": {k: int(sum(d.get(k, 0) or 0 for d in dq)) for k in ["rows_raw", "duplicates", "out_of_range", "out_of_order", "irregular_ts", "flatline_slots"]},
    }
    dq_doc["totals"]["metric_rows"] = int(len(metrics))
    dq_doc["checks"] = dq_checks(dq_doc)
    jdump(OUT / "data-quality.json", dq_doc)

    # ---- GET /api/scorecard  (Default preset vs truth.csv; the engine itself never reads truth)
    truth_rows = [{k: r[k] for k in ["resource_id", "name", "type", "archetype", "edge_case_id", "expected_verdict", "expected_reason_code", "expected_action"]}
                  for _, r in truth.iterrows()]
    jdump(OUT / "scorecard.json", {"preset": "default", "mock_engine": True, **score(recs_by_preset["default"], truth_rows)})

    # ---- GET /api/assumptions (config: prices, thresholds, switches, presets, data window)
    counts = inv.type.value_counts().to_dict()
    jdump(OUT / "assumptions.json", {
        "data_window": window,
        "billing_window": {"start": f"{dates[0]:%Y-%m-%d}", "end": f"{dates[-1]:%Y-%m-%d}"},
        "counts": {"vm": int(counts.get("vm", 0)), "volume": int(counts.get("volume", 0)), "ip": int(counts.get("ip", 0)), "metric_rows": int(len(metrics))},
        "pricing": [{"item": r.item, "kind": r.kind, "vcpu": none_if_nan(r.vcpu), "ram_gb": none_if_nan(r.ram_gb), "bandwidth_mbps": none_if_nan(r.bandwidth_mbps),
                     "monthly_inr": int(r.monthly_inr), "unit": r.unit, "basis": r.basis} for r in pricing.itertuples()],
        "thresholds": THRESHOLDS,
        "switches": [
            {"name": "stopped_vm_billed", "value": False, "why": "Compute is free while stopped; disk and IP still bill. Confirm with Utho."},
            {"name": "hours_per_month", "value": 730, "why": "Monthly price ÷ 730 = hourly"},
            {"name": "gst", "value": "excluded", "why": "Prices are ex-GST"},
        ],
        "presets": [{"id": k, "label": v["label"], "percentile": f"p{v['pct_prod']:g} prod / p{v['pct_np']:g} non-prod",
                     "cpu_target": f"{v['cpu_prod']}% / {v['cpu_np']}%", "replay_limit": f"{v['limit_prod']} / {v['limit_np']} min"} for k, v in PRESETS.items()],
    })
    size = sum(p.stat().st_size for p in OUT.rglob("*.json"))
    print(f"exported {len(list(OUT.rglob('*.json')))} files, {size / 1e6:.1f} MB -> {OUT}")


if __name__ == "__main__":
    main()
