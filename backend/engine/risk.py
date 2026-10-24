"""Risk points and confidence (plan section 7). Every card lists which points fired."""
import numpy as np

ENV_POINTS = {"prod": 3, "staging": 1, "dev": 0}


def risk(env, stateful, projected_p99, p99, p50, action_types, coverage, weekly_variation, week_limit):
    pts = [{"factor": "env", "points": ENV_POINTS.get(env, 3), "detail": f"{env} +{ENV_POINTS.get(env, 3)}"}]
    if stateful and env != "prod":
        pts.append({"factor": "stateful", "points": 2, "detail": "stateful non-prod +2"})
    if projected_p99 is not None:
        if projected_p99 > 70:
            pts.append({"factor": "projected_p99", "points": 2, "detail": f"projected p99 {projected_p99:.0f}% > 70 +2"})
        elif projected_p99 >= 50:
            pts.append({"factor": "projected_p99", "points": 1, "detail": f"projected p99 {projected_p99:.0f}% 50-70 +1"})
    if p99 is not None and p50 and p99 / p50 > 3:
        pts.append({"factor": "bursty", "points": 1, "detail": f"p99/p50 = {p99 / p50:.1f} > 3 +1"})
    if "delete" in action_types:
        pts.append({"factor": "action", "points": 2, "detail": "delete +2"})
    elif "stop" in action_types:
        pts.append({"factor": "action", "points": 1, "detail": "stop +1"})
    if coverage < 0.95:
        pts.append({"factor": "coverage", "points": 1, "detail": f"coverage {coverage:.0%} < 95% +1"})
    score = sum(p["points"] for p in pts)
    level = "Low" if score <= 2 else "Medium" if score <= 4 else "High"
    if coverage >= 0.95 and weekly_variation is not None and weekly_variation < week_limit:
        conf, basis = "High", f"coverage {coverage:.0%}, weekly p95 varies {weekly_variation:.0%}"
    elif coverage >= 0.8:
        conf = "Medium"
        basis = (f"coverage {coverage:.0%}" + (f", weekly p95 varies {weekly_variation:.0%}"
                                                if weekly_variation is not None else ""))
    else:
        conf, basis = "Low", f"coverage {coverage:.0%}: insufficient data"
    return {"level": level, "score": int(score), "points": pts, "confidence": conf, "confidence_basis": basis}


def weekly_variation(cpu, slots_per_week=2016):
    """(max - min) / mean of the p95 CPU of each full week."""
    weeks = [cpu[i:i + slots_per_week] for i in range(0, len(cpu) - slots_per_week + 1, slots_per_week)]
    p = [np.nanpercentile(w, 95) for w in weeks if np.any(~np.isnan(w))]
    if len(p) < 2 or np.mean(p) == 0:
        return None
    return float((max(p) - min(p)) / np.mean(p))
