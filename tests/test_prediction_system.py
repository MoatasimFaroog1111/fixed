import inspect
import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from prediction_system.artifacts import PersistedForecastModel, PickleForecastArtifactRepository
from prediction_system.features import FeatureBuilder
from prediction_system.service import PredictionService
from prediction_system.units import PriceUnitConverter, TROY_OUNCES_PER_KILOGRAM


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


def test_usd_per_troy_ounce_is_converted_to_usd_per_kg():
    converter = PriceUnitConverter()
    assert converter.usd_per_troy_ounce_to_usd_per_kg(1.0) == TROY_OUNCES_PER_KILOGRAM
    assert round(converter.usd_per_troy_ounce_to_usd_per_kg(4696.18), 2) == 150993.67


def test_persisted_artifact_round_trip(tmp_path):
    X = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0]})
    y = np.array([0.01, 0.02, 0.03])
    model = DummyRegressor(strategy="mean").fit(X, y)
    artifact = PersistedForecastModel(
        security_id="AUXLN",
        horizon="6h",
        feature_names=("a", "b"),
        models=(model,),
        weights=(1.0,),
        validation_mae=0.01,
        confidence=0.8,
        training_samples=3,
        trained_at="2026-08-15T00:00:00+00:00",
    )
    repository = PickleForecastArtifactRepository(str(tmp_path))
    repository.save(artifact)
    loaded = repository.load("AUXLN", "6h")
    assert loaded.feature_names == ("a", "b")
    assert np.isfinite(loaded.predict_return(X.iloc[[-1]]))


def test_online_service_has_no_training_dependency():
    source = inspect.getsource(PredictionService)
    assert ".fit(" not in source
    assert "WalkForwardEnsembleTrainer" not in source
    assert "PredictionTrainingService" not in source
