import math

import numpy as np
import pandas as pd

from prediction_system.targets import TimeAwareHorizonTargetBuilder


def test_target_uses_elapsed_clock_time_not_row_count():
    idx = pd.to_datetime([
        "2026-01-02 20:00:00",  # Friday
        "2026-01-02 21:00:00",
        "2026-01-04 22:00:00",  # Sunday reopen
        "2026-01-04 23:00:00",
    ])
    prices = pd.Series([100.0, 101.0, 110.0, 111.0], index=idx)
    target = TimeAwareHorizonTargetBuilder(max_lag_hours=72).build(prices, 24)

    # 24h after Friday 21:00 is Saturday 21:00; first available quote is Sunday 22:00.
    assert math.isclose(target.loc[pd.Timestamp("2026-01-02 21:00:00")], math.log(110.0 / 101.0))


def test_target_rejects_quote_beyond_tolerance():
    idx = pd.to_datetime([
        "2026-01-01 00:00:00",
        "2026-01-10 00:00:00",
    ])
    prices = pd.Series([100.0, 120.0], index=idx)
    target = TimeAwareHorizonTargetBuilder(max_lag_hours=72).build(prices, 24)
    assert np.isnan(target.iloc[0])


def test_regular_hourly_series_matches_expected_horizon():
    idx = pd.date_range("2026-01-01", periods=20, freq="h")
    prices = pd.Series(np.arange(100.0, 120.0), index=idx)
    target = TimeAwareHorizonTargetBuilder().build(prices, 6)
    assert math.isclose(target.iloc[0], math.log(106.0 / 100.0))
    assert target.iloc[-6:].isna().all()
