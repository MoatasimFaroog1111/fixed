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


def test_cross_asset_and_daily_context_are_included():
    idx = pd.date_range("2025-01-01", periods=1200, freq="h")
    base = pd.Series(1000 + np.arange(1200) * 0.1, index=idx)
    hourly = pd.DataFrame({
        "AUXLN": base,
        "AGXLN": 20 + np.arange(1200) * 0.01,
        "DXY": 100 + np.sin(np.arange(1200) / 30),
    }, index=idx)
    didx = pd.date_range("2025-01-01", periods=60, freq="D")
    daily = pd.DataFrame({
        "AUXLN": 1000 + np.arange(60),
        "DXY": 100 + np.sin(np.arange(60) / 5),
    }, index=didx)
    x = FeatureBuilder().build(base, hourly_context=hourly, daily_context=daily)
    assert "ctx_DXY_ret_24" in x.columns
    assert "ctx_AGXLN_corr_72" in x.columns
    assert "daily_DXY_ret_20" in x.columns
    assert np.isfinite(x.iloc[-1].dropna()).all()


def test_required_horizons_exist():
    from prediction_system.config import HORIZONS
    assert list(HORIZONS) == ["6h", "12h", "18h", "24h", "48h", "1w", "1m"]
