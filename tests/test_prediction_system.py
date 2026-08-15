import numpy as np
import pandas as pd
from prediction_system.features import FeatureBuilder


def test_features_are_past_only_and_finite_after_warmup():
    idx = pd.date_range("2025-01-01", periods=900, freq="h")
    prices = pd.Series(1000 + np.arange(900) * 0.1, index=idx)
    x = FeatureBuilder().build(prices)
    assert len(x) == len(prices)
    assert x.iloc[-1].dropna().shape[0] > 20
    assert np.isfinite(x.iloc[-1].dropna()).all()


def test_required_horizons_exist():
    from prediction_system.config import HORIZONS
    assert list(HORIZONS) == ["6h", "12h", "18h", "24h", "48h", "1w", "1m"]
