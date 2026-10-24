"""The 5-minute window grid: slot <-> timestamp, IST day and hour-of-week per slot."""
from dataclasses import dataclass
from functools import cached_property

import numpy as np
import pandas as pd

STEP = pd.Timedelta(minutes=5)


@dataclass(frozen=True)
class Grid:
    start: pd.Timestamp          # IST
    slots: int
    tz: str

    @cached_property
    def ts_utc(self):
        return pd.date_range(self.start, periods=self.slots, freq=STEP).tz_convert("UTC")

    @cached_property
    def ts_local(self):
        return pd.date_range(self.start, periods=self.slots, freq=STEP)

    @cached_property
    def day(self):
        """IST calendar-day index 0..29 of every slot."""
        return np.arange(self.slots) // 288

    @cached_property
    def hour_of_week(self):
        """0..167, Monday 00:00 IST = 0."""
        t = self.ts_local
        return (t.day_of_week * 24 + t.hour).to_numpy()

    @cached_property
    def is_weekend(self):
        return self.ts_local.day_of_week.to_numpy() >= 5

    def slot_of(self, ts):
        """Fractional slot position of timestamps (any tz)."""
        delta = pd.DatetimeIndex(ts) - self.start
        return np.asarray(delta / STEP, dtype="float64")


def grid_from_config(cfg):
    return Grid(start=cfg.window_start, slots=cfg.slots, tz=cfg.tz)
