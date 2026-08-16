from __future__ import annotations

import numpy as np
import pandas as pd


class DailyLongHorizonTargetBuilder:
    """Build non-hourly forward log-return targets from completed daily closes."""

    DAYS = {"1w": 7, "1m": 30}

    def build(self, prices: pd.Series, horizon: str) -> pd.Series:
        if horizon not in self.DAYS:
            raise ValueError(f"Unsupported daily horizon: {horizon}")
        p = prices.astype(float).replace([np.inf, -np.inf], np.nan).dropna().copy()
        p.index = pd.to_datetime(p.index, utc=True).tz_convert(None)
        p = p.sort_index()[~p.index.duplicated(keep="last")].resample("1D").last().dropna()
        days = self.DAYS[horizon]
        target = np.log(p.shift(-days) / p)
        target.name = "target"
        return target
