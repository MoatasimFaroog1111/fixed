from __future__ import annotations

import numpy as np
import pandas as pd


class LongHorizonFeatureBuilder:
    """Leakage-safe multi-timeframe features dedicated to 1w/1m forecasts."""

    DAILY_WINDOWS = (3, 5, 10, 20, 40, 60, 120)
    HOURLY_WINDOWS = (24, 72, 168, 336, 720, 1440)

    @staticmethod
    def _clean(series: pd.Series) -> pd.Series:
        return series.astype(float).replace([np.inf, -np.inf], np.nan)

    @staticmethod
    def _normalize(obj: pd.Series | pd.DataFrame):
        out = obj.copy()
        if isinstance(out.index, pd.DatetimeIndex):
            out.index = pd.to_datetime(out.index, utc=True).tz_convert(None)
            out = out.sort_index()
            out = out[~out.index.duplicated(keep="last")]
        return out

    def build(self, prices: pd.Series, hourly_context: pd.DataFrame | None = None, daily_context: pd.DataFrame | None = None) -> pd.DataFrame:
        p = self._clean(self._normalize(prices))
        x = pd.DataFrame(index=p.index)
        lp = np.log(p.clip(lower=1e-12))
        hr = lp.diff()

        # Long hourly trend/momentum/regime features.
        for w in self.HOURLY_WINDOWS:
            rolling = p.rolling(w)
            x[f"lh_ret_{w}"] = lp.diff(w)
            x[f"lh_vol_{w}"] = hr.rolling(w).std()
            x[f"lh_z_{w}"] = (p - rolling.mean()) / (rolling.std() + 1e-12)
            x[f"lh_range_{w}"] = (rolling.max() - rolling.min()) / (rolling.mean() + 1e-12)

        x["trend_168_720"] = p.rolling(168).mean() / (p.rolling(720).mean() + 1e-12) - 1.0
        x["trend_336_1440"] = p.rolling(336).mean() / (p.rolling(1440).mean() + 1e-12) - 1.0
        x["vol_ratio_168_720"] = hr.rolling(168).std() / (hr.rolling(720).std() + 1e-12)

        # Daily target-asset regime. Only completed historical daily closes are propagated.
        daily_price = p.resample("1D").last().dropna()
        dlp = np.log(daily_price.clip(lower=1e-12))
        dr = dlp.diff()
        df = pd.DataFrame(index=daily_price.index)
        for w in self.DAILY_WINDOWS:
            df[f"d_ret_{w}"] = dlp.diff(w)
            df[f"d_vol_{w}"] = dr.rolling(w).std()
            df[f"d_z_{w}"] = (daily_price - daily_price.rolling(w).mean()) / (daily_price.rolling(w).std() + 1e-12)
        df["d_trend_20_60"] = daily_price.rolling(20).mean() / (daily_price.rolling(60).mean() + 1e-12) - 1.0
        df["d_trend_60_120"] = daily_price.rolling(60).mean() / (daily_price.rolling(120).mean() + 1e-12) - 1.0
        x = x.join(df.reindex(x.index, method="ffill"))

        # Cross-metal/DXY relative strength and slow correlation regimes.
        if hourly_context is not None and not hourly_context.empty:
            context = self._normalize(hourly_context).reindex(x.index).ffill()
            for name in context.columns:
                s = self._clean(context[name])
                ls = np.log(s.clip(lower=1e-12))
                sr = ls.diff()
                for w in (168, 336, 720):
                    x[f"lh_ctx_{name}_ret_{w}"] = ls.diff(w)
                    x[f"lh_ctx_{name}_rel_{w}"] = lp.diff(w) - ls.diff(w)
                x[f"lh_ctx_{name}_corr_168"] = hr.rolling(168).corr(sr)
                x[f"lh_ctx_{name}_corr_720"] = hr.rolling(720).corr(sr)

        if daily_context is not None and not daily_context.empty:
            daily = self._normalize(daily_context)
            for name in daily.columns:
                s = self._clean(daily[name])
                ls = np.log(s.clip(lower=1e-12))
                feats = pd.DataFrame(index=s.index)
                for w in (5, 20, 60):
                    feats[f"lh_daily_ctx_{name}_ret_{w}"] = ls.diff(w)
                x = x.join(feats.reindex(x.index, method="ffill"))

        if isinstance(x.index, pd.DatetimeIndex):
            x["lh_dow_sin"] = np.sin(2 * np.pi * x.index.dayofweek / 7.0)
            x["lh_dow_cos"] = np.cos(2 * np.pi * x.index.dayofweek / 7.0)
            x["lh_month_sin"] = np.sin(2 * np.pi * (x.index.month - 1) / 12.0)
            x["lh_month_cos"] = np.cos(2 * np.pi * (x.index.month - 1) / 12.0)

        return x.replace([np.inf, -np.inf], np.nan)
