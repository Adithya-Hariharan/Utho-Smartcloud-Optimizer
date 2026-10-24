"""Shared helpers for components: findings, environment, percentile choice, plan lookups."""
import numpy as np
import pandas as pd

# verdict classes, highest precedence first (assemble.b_precedence); data-quality flags outrank decisions
# because a decision on incomplete evidence is not a decision
PRECEDENCE = ["exclude", "data_flag", "upsize", "reject", "flag", "recommend", "below_floor", "soft_reject", "healthy"]
VERDICT_OF = {"exclude": "exclude", "data_flag": "flag", "upsize": "upsize", "reject": "reject", "flag": "flag",
              "recommend": "recommend", "below_floor": "healthy", "soft_reject": "reject", "healthy": "healthy"}
# within a class, the more specific signal wins (leak before memory, tag before policy, ...)
CODE_ORDER = [
    "NOT_IN_INVENTORY", "UNKNOWN_PRICE", "NO_TELEMETRY", "TAG_DR_STANDBY", "TAG_AUTOSCALED", "TAG_SEASONAL",
    "TAG_ALLOWLISTED_IP", "POLICY_NEVER", "STATEFUL_PROD", "STOPPED_RECENTLY", "HISTORY_TOO_SHORT", "RECENTLY_RESIZED",
    "LOW_COVERAGE", "ACTIVE_ANOMALY", "ORPHAN_TOO_NEW", "PEAK_UNDER_OBSERVED", "UNDER_PROVISIONED",
    "VETO_LEAK", "VETO_MEMORY", "VETO_IOPS", "VETO_NETWORK", "VETO_GROWTH", "VETO_RECURRING_PEAK",
    "ONE_OFF_PEAK", "WENT_QUIET", "RESERVED_MEMORY", "IDLE_PROD", "IDLE_VOLUME_REVIEW",
    "STOPPED_VM", "ORPHAN_VOLUME", "UNUSED_IP", "OVERSIZED_VOLUME", "IDLE", "UNDERUSED", "OFF_HOURS",
    "BELOW_FLOOR", "PEAK_REPLAY_FAILED", "NO_CHEAPER_PLAN", "RIGHT_SIZED",
]


def finding(comp, code, kind, check, value, threshold, result=True, message=""):
    return {"comp": comp, "code": code, "kind": kind, "check": check, "value": _clean(value),
            "threshold": _clean(threshold), "result": "fail" if result else "pass", "message": message}


def trace_only(comp, check, value, threshold, passed):
    """A check that ran and did not fire (shown in the trace, not a decision)."""
    return {"comp": comp, "code": None, "kind": "info", "check": check, "value": _clean(value),
            "threshold": _clean(threshold), "result": "pass" if passed else "fail", "message": ""}


def _clean(v):
    if isinstance(v, (np.floating, float)):
        return None if not np.isfinite(v) else round(float(v), 4)
    if isinstance(v, np.integer):
        return int(v)
    return v


def is_prod(r):
    return r.env == "prod"


def percentile_for(r, cfg):
    return cfg.preset["percentile_prod"] if is_prod(r) else cfg.preset["percentile_nonprod"]


def P(r, cfg, metric="cpu"):
    """CPU (or mem) at the environment's sizing percentile."""
    from ..evidence import pct
    q = percentile_for(r, cfg)
    x = r.arr["cpu_pct"] if metric == "cpu" else r.arr["mem_pct"]
    return pct(x, q)


def age_days(ts, now):
    if not ts:
        return np.inf
    return (now - pd.Timestamp(ts).tz_convert(now.tz)) / pd.Timedelta(days=1)


def has_tag(r, tag):
    return tag in (r.inv.get("tags") or "").split(";")
