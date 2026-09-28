from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np
import pandas as pd


class HorizonTargetBuilder(ABC):
    """Port for building leakage-safe future-return targets from a price series."""

    @abstractmethod
    def build(self, prices: pd.Series, horizon_hours: int) -> pd.Series:
        """Return log-return targets aligned to the source timestamps."""
        raise NotImplementedError


class TimeAwareHorizonTargetBuilder(HorizonTargetBuilder):
    """Build targets by elapsed clock time, not by number of observed rows.

    The first quote at or after ``timestamp + horizon`` is selected. A bounded
    tolerance permits normal market closures/weekends without silently mapping a
    target to a quote many days later after a data outage.
    """

    def __init__(self, max_lag_hours: int = 72):
        if max_lag_hours < 0:
            raise ValueError("max_lag_hours must be non-negative")
        self.max_lag = pd.Timedelta(hours=max_lag_hours)

    @staticmethod
    def _normalize(prices: pd.Series) -> pd.Series:
        s = prices.astype(float).replace([np.inf, -np.inf], np.nan).dropna().copy()
        if not isinstance(s.index, pd.DatetimeIndex):
            s.index = pd.to_datetime(s.index, errors="coerce", utc=True)
        else:
            s.index = pd.to_datetime(s.index, errors="coerce", utc=True)
        s = s[~s.index.isna()]
        s.index = s.index.tz_convert(None)
        return s.sort_index()[~s.index.duplicated(keep="last")]

    def build(self, prices: pd.Series, horizon_hours: int) -> pd.Series:
        if horizon_hours <= 0:
            raise ValueError("horizon_hours must be positive")

        p = self._normalize(prices)
        if p.empty:
            return pd.Series(dtype=float, name="target")

        index = p.index
        desired = index + pd.Timedelta(hours=int(horizon_hours))
        positions = index.searchsorted(desired, side="left")
        valid_position = positions < len(index)

        future_values = np.full(len(index), np.nan, dtype=float)
        actual_times = np.full(len(index), np.datetime64("NaT"), dtype="datetime64[ns]")
        valid_rows = np.flatnonzero(valid_position)
        valid_positions = positions[valid_position]
        future_values[valid_rows] = p.to_numpy(dtype=float)[valid_positions]
        actual_times[valid_rows] = index.to_numpy(dtype="datetime64[ns]")[valid_positions]

        actual_index = pd.DatetimeIndex(actual_times)
        lag = actual_index - desired
        within_tolerance = valid_position & (lag >= pd.Timedelta(0)) & (lag <= self.max_lag)
        future_values[~within_tolerance] = np.nan

        current = p.to_numpy(dtype=float)
        positive = (current > 0) & (future_values > 0)
        target_values = np.full(len(index), np.nan, dtype=float)
        target_values[positive] = np.log(future_values[positive] / current[positive])
        return pd.Series(target_values, index=index, name="target")
