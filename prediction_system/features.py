import numpy as np
import pandas as pd


class FeatureBuilder:
    """Leakage-safe features built only from information available at each timestamp."""
    WINDOWS = (3, 6, 12, 24, 48, 72, 168, 336, 720)

    def build(self, prices: pd.Series) -> pd.DataFrame:
        p = prices.astype(float)
        x = pd.DataFrame(index=p.index)
        logp = np.log(p.clip(lower=1e-12))
        r = logp.diff()
        for w in self.WINDOWS:
            x[f"ret_{w}"] = logp.diff(w)
            x[f"mean_{w}"] = r.rolling(w).mean()
            x[f"vol_{w}"] = r.rolling(w).std()
            x[f"z_{w}"] = (p - p.rolling(w).mean()) / (p.rolling(w).std() + 1e-12)
        x["hour"] = getattr(x.index, "hour", pd.Index([0] * len(x)))
        x["dow"] = getattr(x.index, "dayofweek", pd.Index([0] * len(x)))
        return x.replace([np.inf, -np.inf], np.nan)
