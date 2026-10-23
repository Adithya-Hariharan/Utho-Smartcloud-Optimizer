"""Signal building blocks. All arrays are aligned to the 8,640-slot window (IST)."""
import contextlib
import zlib

import numpy as np
import pandas as pd
from scipy.signal import lfilter

from .config import (FITTED, N_SLOTS, PINNED_DRIFT_SD, PINNED_PHI, SEED, SLOTS_PER_DAY, STEP, WINDOW_START,
                     fitted)

# Active dynamics. Defaults are FITTED (Bitbrains); `pinned()` switches to the hand-set values for
# planted scenarios whose edge-case targets need them.
_DYN = {"pinned": False}


@contextlib.contextmanager
def pinned():
    old = _DYN["pinned"]
    _DYN["pinned"] = True
    try:
        yield
    finally:
        _DYN["pinned"] = old


def _phi():
    return PINNED_PHI if _DYN["pinned"] else fitted("ar1_phi_cpu")


def _drift_sd():
    return PINNED_DRIFT_SD if _DYN["pinned"] else fitted("drift_sd")


def noise_sigma(level):
    """Fitted heteroscedastic noise: sigma = a * level^b (Bitbrains), bounded to a sane range."""
    m = FITTED["ar1_sigma_model"]
    return float(np.clip(m["a"] * max(level, 0.5) ** m["b"], 0.3, 15.0))


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


def drift(rng, sd=None):
    """One multiplier per day so no two days are identical (sd fitted: Bitbrains day-to-day variation).
    Lognormal so a large sd can never produce a negative multiplier."""
    sd = _drift_sd() if sd is None else sd
    s = np.sqrt(np.log(1 + sd ** 2))
    return rng.lognormal(-s ** 2 / 2, s, AX.day.max() + 1)[AX.day]


def ar1(rng, sigma, phi=None):
    """Autocorrelated noise with stationary std = sigma (phi fitted: Bitbrains lag-1 autocorrelation)."""
    phi = _phi() if phi is None else phi
    eps = rng.normal(0.0, sigma * np.sqrt(1 - phi ** 2), AX.n)
    return lfilter([1.0], [1.0, -phi], eps)


def steady(rng, base, amp, weekend=0.85, sigma=None, start=8.0, end=20.0, drift_sd=None):
    """Interactive workload: base + daily bump, weekend dip, daily drift, AR(1) noise.
    sigma=None / drift_sd=None use the fitted values."""
    sigma = noise_sigma(base + amp / 2) if sigma is None else sigma
    return (base + amp * daily(start, end) * weekly(weekend)) * drift(rng, drift_sd) + ar1(rng, sigma)


def random_spikes(rng, per_day, dur_slots=(2, 6), amp=(70.0, 85.0)):
    """Unscheduled spikes at Poisson-random times (Azure: most spikes are not seasonal)."""
    out = np.zeros(AX.n)
    k = rng.poisson(per_day * AX.n / SLOTS_PER_DAY)
    for s in rng.integers(0, AX.n, k):
        d = int(rng.integers(dur_slots[0], dur_slots[1] + 1))
        out[s:s + d] = np.maximum(out[s:s + d], rng.uniform(*amp))
    return out
