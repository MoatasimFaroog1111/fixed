from __future__ import annotations

import numpy as np
import pandas as pd


class DailyRegimeFeatureBuilder:
    """Leakage-safe daily feature component dedicated to 1w/1m forecasting."""

    WINDOWS = (3, 5, 10, 20, 40, 60, 120, 250)

    @staticmethod
    def _normalize(obj: pd.Series | pd.DataFrame):
        out = obj.copy()
        out.index = pd.to_datetime(out.index, utc=True).tz_convert(None)
        out = out.sort_index()
        return out[~out.index.duplicated(keep="last")]

    def build(self, prices: pd.Series, daily_context: pd.DataFrame | None = None) -> pd.DataFrame:
        hourly = self._normalize(prices.astype(float)).replace([np.inf, -np.inf], np.nan).dropna()
        # One observation per completed market day: prevents thousands of overlapping H1 labels.
        p = hourly.resample("1D").last().dropna()
        lp = np.log(p.clip(lower=1e-12))
        r = lp.diff()
        x = pd.DataFrame(index=p.index)

        for w in self.WINDOWS:
            mean = p.rolling(w).mean()
            std = p.rolling(w).std()
            x[f"ret_{w}d"] = lp.diff(w)
            x[f"vol_{w}d"] = r.rolling(w).std()
            x[f"z_{w}d"] = (p - mean) / (std + 1e-12)
            x[f"range_{w}d"] = (p.rolling(w).max() - p.rolling(w).min()) / (mean + 1e-12)

        x["trend_5_20"] = p.rolling(5).mean() / (p.rolling(20).mean() + 1e-12) - 1.0
        x["trend_20_60"] = p.rolling(20).mean() / (p.rolling(60).mean() + 1e-12) - 1.0
        x["trend_60_250"] = p.rolling(60).mean() / (p.rolling(250).mean() + 1e-12) - 1.0
        x["vol_regime_20_120"] = r.rolling(20).std() / (r.rolling(120).std() + 1e-12)
        x["positive_days_20"] = (r > 0).astype(float).rolling(20).mean()
        x["positive_days_60"] = (r > 0).astype(float).rolling(60).mean()

        if daily_context is not None and not daily_context.empty:
            context = self._normalize(daily_context).reindex(x.index).ffill()
            for name in context.columns:
                s = context[name].astype(float).replace([np.inf, -np.inf], np.nan)
                ls = np.log(s.clip(lower=1e-12))
                sr = ls.diff()
                for w in (5, 20, 60, 120):
                    x[f"ctx_{name}_ret_{w}d"] = ls.diff(w)
                    x[f"ctx_{name}_rel_{w}d"] = lp.diff(w) - ls.diff(w)
                x[f"ctx_{name}_corr_20"] = r.rolling(20).corr(sr)
                x[f"ctx_{name}_corr_60"] = r.rolling(60).corr(sr)

        x["dow_sin"] = np.sin(2 * np.pi * x.index.dayofweek / 7.0)
        x["dow_cos"] = np.cos(2 * np.pi * x.index.dayofweek / 7.0)
        x["month_sin"] = np.sin(2 * np.pi * (x.index.month - 1) / 12.0)
        x["month_cos"] = np.cos(2 * np.pi * (x.index.month - 1) / 12.0)
        return x.replace([np.inf, -np.inf], np.nan)
