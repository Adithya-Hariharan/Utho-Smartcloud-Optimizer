"""Signal building blocks. All arrays are aligned to the 8,640-slot window (IST)."""
import zlib

import numpy as np
import pandas as pd
from scipy.signal import lfilter

from .config import N_SLOTS, SEED, SLOTS_PER_DAY, STEP, WINDOW_START


class _Axis:
    def __init__(self):
        ts = pd.date_range(WINDOW_START, periods=N_SLOTS, freq=STEP)
        self.ts_ist = ts
        self.ts_utc = ts.tz_convert("UTC")
        self.hour = (ts.hour + ts.minute / 60).to_numpy(dtype=float)
        self.dow = ts.dayofweek.to_numpy()            # 0 = Monday, 6 = Sunday
        self.weekend = self.dow >= 5
        self.day = np.arange(N_SLOTS) // SLOTS_PER_DAY
        self.day_frac = np.arange(N_SLOTS) / SLOTS_PER_DAY
        self.n = N_SLOTS


AX = _Axis()


def rng_for(name, salt=""):
    """Per-resource generator: a resource's data does not change if the fleet list is reordered."""
    return np.random.default_rng([SEED, zlib.crc32(f"{name}|{salt}".encode())])


def clip(x, lo=0.0, hi=100.0):
    return np.clip(x, lo, hi)


def between(start_h, end_h):
    """Mask of slots whose IST hour is in [start_h, end_h); wraps past midnight."""
    h = AX.hour
    if start_h <= end_h:
        return (h >= start_h) & (h < end_h)
    return (h >= start_h) | (h < end_h)


def daily(start=8.0, end=20.0):
    """Business-hours bump: 0 outside [start, end], sine peak at the midpoint (14:00 by default)."""
    x = (AX.hour - start) / (end - start)
    return np.where((x > 0) & (x < 1), np.sin(np.pi * x), 0.0)


def weekly(weekend_factor):
    return np.where(AX.weekend, weekend_factor, 1.0)


def drift(rng, sd=0.05):
    """One multiplier per day so no two days are identical."""
    return rng.normal(1.0, sd, AX.day.max() + 1)[AX.day]


def ar1(rng, sigma, phi=0.8):
    """Autocorrelated noise with stationary std = sigma."""
    eps = rng.normal(0.0, sigma * np.sqrt(1 - phi ** 2), AX.n)
    return lfilter([1.0], [1.0, -phi], eps)


def steady(rng, base, amp, weekend=0.85, sigma=2.0, start=8.0, end=20.0):
    """Interactive workload: base + daily bump, weekend dip, daily drift, AR(1) noise."""
    return (base + amp * daily(start, end) * weekly(weekend)) * drift(rng) + ar1(rng, sigma)


def random_spikes(rng, per_day, dur_slots=(2, 6), amp=(70.0, 85.0)):
    """Unscheduled spikes at Poisson-random times (Azure: most spikes are not seasonal)."""
    out = np.zeros(AX.n)
    k = rng.poisson(per_day * AX.n / SLOTS_PER_DAY)
    for s in rng.integers(0, AX.n, k):
        d = int(rng.integers(dur_slots[0], dur_slots[1] + 1))
        out[s:s + d] = np.maximum(out[s:s + d], rng.uniform(*amp))
    return out
