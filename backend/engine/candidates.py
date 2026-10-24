"""Off-hours scheduling (plan section 7, step 6): per-VM windows from the hour-of-week profile.

An hour-of-week is 'off' if CPU p95 < 5% in EVERY week that has data; runs are merged around the week,
blocks shorter than 4 h are dropped, and at least 40 off-hours/week are needed.
"""
import numpy as np

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _label(h):
    return DAYS[(h % 168) // 24], f"{h % 24:02d}:00"


def _runs(mask):
    """Circular runs of True over 168 hours as (start, length)."""
    if mask.all():
        return [(0, 168)]
    if not mask.any():
        return []
    shift = int(np.flatnonzero(~mask)[0])                 # start scanning just after an 'on' hour
    rolled = np.roll(mask, -shift)
    runs, i = [], 0
    while i < 168:
        if rolled[i]:
            j = i
            while j < 168 and rolled[j]:
                j += 1
            runs.append(((i + shift) % 168, j - i))
            i = j
        else:
            i += 1
    return runs


def off_hour_mask(how_by_week, threshold, min_weeks=2):
    off = np.zeros(168, dtype=bool)
    for h in range(168):
        vals = [w[h] for w in how_by_week if w[h] is not None]
        off[h] = len(vals) >= min_weeks and all(v < threshold for v in vals)
    return off


def window(start, length):
    """One continuous off block: 'Fri→Mon', '20:00', '08:00' = from Fri 20:00 to Mon 08:00 IST."""
    d0, t0 = _label(start)
    d1, t1 = _label(start + length)
    if length == 168:
        return {"days": "all week", "start": "00:00", "end": "00:00"}
    return {"days": d0 if d0 == d1 and length < 24 else f"{d0}→{d1}", "start": t0, "end": t1}


def schedule(how_by_week, threshold, min_block, min_total, tz):
    """§4.5 schedule block, or (None, why)."""
    off = off_hour_mask(how_by_week, threshold)
    runs = _runs(off)
    kept = [(s, n) for s, n in runs if n >= min_block]
    total = sum(n for _, n in kept)
    if total < min_total:
        return None, f"{total} usable off-hours/week (blocks ≥ {min_block} h) < {min_total}"
    keep = np.zeros(168, dtype=bool)
    for s, n in kept:
        keep[(s + np.arange(n)) % 168] = True
    gaps = [(s, n) for s, n in _runs(~keep) if n < min_block]   # short busy gaps the schedule keeps on
    sched = {"timezone": tz, "off_hours_per_week": float(total), "on_hours_per_week": float(168 - total),
             "windows": [window(s, n) for s, n in sorted(kept)],
             "busy_hours_excluded": [f"{_label(s)[0]} {_label(s)[1]}-{_label(s + n)[1]}" for s, n in sorted(gaps)]}
    return sched, f"{total} off-hours/week in {len(kept)} blocks"
