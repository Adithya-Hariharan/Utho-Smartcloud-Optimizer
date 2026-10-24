"""Statistics shared by the data generator/fitter and the engine (identical maths on both sides)."""
import numpy as np

SLOTS_DAY = 288


def lag1(x):
    a, b = x[:-1], x[1:]
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 100 or np.std(a[m]) == 0 or np.std(b[m]) == 0:
        return np.nan
    return float(np.corrcoef(a[m], b[m])[0, 1])


def residual(x, hod, weekend, day):
    """Remove weekday/weekend hour-of-day profile and the day-level offset -> within-day noise."""
    r = x.copy()
    for w in (False, True):
        sel = weekend == w
        if sel.sum() == 0:
            continue
        prof = np.full(SLOTS_DAY, np.nan)
        for h in range(SLOTS_DAY):
            v = x[sel & (hod == h)]
            prof[h] = np.nanmean(v) if np.isfinite(v).any() else np.nan
        r[sel] = x[sel] - prof[hod[sel]]
    for d in np.unique(day):
        sel = day == d
        if np.isfinite(r[sel]).any():
            r[sel] -= np.nanmean(r[sel])
    return r


def time_index(start, n, offset_h=0):
    t = start + np.timedelta64(offset_h, "h") + np.arange(n) * np.timedelta64(5, "m")
    days = t.astype("datetime64[D]")
    hod = ((t - days).astype("timedelta64[m]").astype(int) // 5)
    dow = (days.astype(int) + 3) % 7          # 1970-01-01 was a Thursday -> Monday = 0
    return hod, dow >= 5, (days - days[0]).astype(int), dow



def linfit(x, y):
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 100 or np.std(x[m]) == 0:
        return np.nan, np.nan
    slope, icpt = np.polyfit(x[m], y[m], 1)
    return float(slope), float(icpt)


def log_resid_sd(y, fit):
    m = np.isfinite(y) & np.isfinite(fit) & (y > 0) & (fit > 0)
    return float(np.std(np.log(y[m] / fit[m]))) if m.sum() > 100 else np.nan


def auc(scores, labels):
    """Area under the ROC curve via average ranks (ties share a rank). 0.5 = random ranking."""
    labels = np.asarray(labels, dtype=bool)
    scores = np.asarray(scores, dtype=float)
    pos = labels.sum()
    if pos == 0 or pos == len(labels):
        return 0.5
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores))
    s = scores[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[j + 1] == s[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[labels].sum() - pos * (pos + 1) / 2) / (pos * (len(labels) - pos)))
