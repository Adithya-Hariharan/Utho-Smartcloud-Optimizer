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


def day_ranges(days):
    """[0, 1, 2, 4] -> 'Mon–Wed, Fri'."""
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
    """Readable IST windows (frontend reference describe_blocks): identical blocks shorter than a day are grouped
    across days ('Mon–Thu', '19:00', '09:00 (next day)'); blocks of a day or more read 'Fri → Mon'."""
    if blocks == [(0, 168)]:
        return [{"days": "Mon → Mon", "start": "00:00", "end": "00:00"}]
    daily, long_ = {}, []
    for s, n in blocks:
        if n >= 24:
            long_.append((s, n))
        else:
            daily.setdefault((s % 24, n), []).append(s // 24)
    windows = []
    for (sh, n), days in sorted(daily.items(), key=lambda kv: (min(kv[1]), kv[0][0])):
        nxt = " (next day)" if sh + n >= 24 else ""
        windows.append({"days": day_ranges(days), "start": f"{sh:02d}:00", "end": f"{(sh + n) % 24:02d}:00{nxt}"})
    for s, n in long_:
        e = (s + n) % 168
        windows.append({"days": f"{DAYS[s // 24]} → {DAYS[e // 24]}", "start": f"{s % 24:02d}:00", "end": f"{e % 24:02d}:00"})
    return windows


def busy_profile(how_by_week):
    """Per hour-of-week: the highest weekly p95 (None when no week has data)."""
    out = []
    for h in range(168):
        vals = [w[h] for w in how_by_week if w[h] is not None]
        out.append(max(vals) if vals else None)
    return out


def busy_excluded(busy, threshold):
    """Night hours (20:00-08:00) busy on at least 4 of 5 weekdays, e.g. a nightly job: '01:00–03:00 daily'."""
    hours = [h for h in list(range(20, 24)) + list(range(0, 8))
             if sum(1 for d in range(5) if busy[d * 24 + h] is not None and busy[d * 24 + h] >= threshold) >= 4]
    mask = np.array([h in hours for h in range(24)])
    out, h = [], 0
    while h < 24:
        if mask[h]:
            j = h
            while j < 24 and mask[j]:
                j += 1
            out.append(f"{h:02d}:00–{j % 24:02d}:00 daily")
            h = j
        else:
            h += 1
    return out


def schedule(how_by_week, threshold, min_block, min_total, tz):
    """§4.5 schedule block, or (None, why)."""
    off = off_hour_mask(how_by_week, threshold)
    kept = sorted((s, n) for s, n in _runs(off) if n >= min_block)
    total = int(sum(n for _, n in kept))
    if total < min_total:
        return None, f"{total} usable off-hours/week (blocks ≥ {min_block} h) < {min_total}"
    sched = {"timezone": tz, "off_hours_per_week": total, "on_hours_per_week": 168 - total,
             "windows": describe_blocks(kept),
             "busy_hours_excluded": busy_excluded(busy_profile(how_by_week), threshold)}
    return sched, f"{total} off-hours/week in {len(kept)} blocks"
