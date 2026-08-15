import numpy as np
import pandas as pd


class FeatureBuilder:
    """Leakage-safe target, cross-asset and daily-regime feature component."""
    WINDOWS = (3, 6, 12, 24, 48, 72, 168, 336, 720)
    CONTEXT_WINDOWS = (6, 24, 72, 168)

    @staticmethod
    def _clean(series: pd.Series) -> pd.Series:
        return series.astype(float).replace([np.inf, -np.inf], np.nan)

    def build(
        self,
        prices: pd.Series,
        hourly_context: pd.DataFrame | None = None,
        daily_context: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        p = self._clean(prices)
        x = pd.DataFrame(index=p.index)
        logp = np.log(p.clip(lower=1e-12))
        r = logp.diff()

        for w in self.WINDOWS:
            x[f"ret_{w}"] = logp.diff(w)
            x[f"mean_{w}"] = r.rolling(w).mean()
            x[f"vol_{w}"] = r.rolling(w).std()
            x[f"z_{w}"] = (p - p.rolling(w).mean()) / (p.rolling(w).std() + 1e-12)

        if hourly_context is not None and not hourly_context.empty:
            context = hourly_context.reindex(x.index).ffill()
            for name in context.columns:
                s = self._clean(context[name])
                ls = np.log(s.clip(lower=1e-12))
                sr = ls.diff()
                for w in self.CONTEXT_WINDOWS:
                    x[f"ctx_{name}_ret_{w}"] = ls.diff(w)
                    x[f"ctx_{name}_vol_{w}"] = sr.rolling(w).std()
                x[f"ctx_{name}_corr_72"] = r.rolling(72).corr(sr)

        if daily_context is not None and not daily_context.empty:
            daily = daily_context.sort_index()
            for name in daily.columns:
                ds = self._clean(daily[name])
                dlog = np.log(ds.clip(lower=1e-12))
                dr = dlog.diff()
                daily_feats = pd.DataFrame(index=daily.index)
                daily_feats[f"daily_{name}_ret_1"] = dlog.diff(1)
                daily_feats[f"daily_{name}_ret_5"] = dlog.diff(5)
                daily_feats[f"daily_{name}_ret_20"] = dlog.diff(20)
                daily_feats[f"daily_{name}_vol_20"] = dr.rolling(20).std()
                daily_feats = daily_feats.reindex(x.index, method="ffill")
                x = x.join(daily_feats)

        if isinstance(x.index, pd.DatetimeIndex):
            x["hour_sin"] = np.sin(2 * np.pi * x.index.hour / 24.0)
            x["hour_cos"] = np.cos(2 * np.pi * x.index.hour / 24.0)
            x["dow_sin"] = np.sin(2 * np.pi * x.index.dayofweek / 7.0)
            x["dow_cos"] = np.cos(2 * np.pi * x.index.dayofweek / 7.0)

        return x.replace([np.inf, -np.inf], np.nan)
