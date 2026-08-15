from datetime import datetime, timezone
import numpy as np
import pandas as pd
from .artifacts import ForecastArtifactRepository, PickleForecastArtifactRepository
from .config import METALS, HORIZONS
from .data import PicklePriceRepository, PriceRepository
from .features import FeatureBuilder
from .units import PriceUnitConverter


class PredictionService:
    """Online serving service: load persisted models and predict; never trains."""

    CONTEXT_IDS = tuple(m.security_id for m in METALS) + ("DXY",)
    DATA_SOURCE = "Yahoo Finance futures via yfinance"
    SOURCE_TICKERS = {
        "AUXLN": "GC=F",
        "AGXLN": "SI=F",
        "PTXLN": "PL=F",
        "PDXLN": "PA=F",
        "DXY": "DX-Y.NYB",
    }

    def __init__(
        self,
        repository: PriceRepository | None = None,
        artifact_repository: ForecastArtifactRepository | None = None,
        feature_builder: FeatureBuilder | None = None,
        unit_converter: PriceUnitConverter | None = None,
    ):
        self.repository = repository or PicklePriceRepository()
        self.artifact_repository = artifact_repository or PickleForecastArtifactRepository()
        self.features = feature_builder or FeatureBuilder()
        self.unit_converter = unit_converter or PriceUnitConverter()

    @staticmethod
    def _series(frame: pd.DataFrame) -> pd.Series:
        s = frame["price"].astype(float)
        index = pd.to_datetime(s.index, errors="coerce", utc=True)
        s.index = index.tz_convert(None)
        s = s[~s.index.isna()]
        return s.sort_index()[~s.index.duplicated(keep="last")]

    def _context_frame(self, frequency: str) -> pd.DataFrame:
        columns = {}
        loader = self.repository.hourly if frequency == "hourly" else self.repository.daily
        for security_id in self.CONTEXT_IDS:
            try:
                columns[security_id] = self._series(loader(security_id))
            except (FileNotFoundError, ValueError):
                continue
        return pd.concat(columns, axis=1, sort=False).sort_index() if columns else pd.DataFrame()

    def predict_metal(
        self,
        security_id: str,
        name: str,
        hourly_context: pd.DataFrame | None = None,
        daily_context: pd.DataFrame | None = None,
    ) -> dict:
        prices = self._series(self.repository.hourly(security_id))
        features = self.features.build(prices, hourly_context=hourly_context, daily_context=daily_context)
        current_source = float(prices.iloc[-1])
        current_kg = self.unit_converter.usd_per_troy_ounce_to_usd_per_kg(current_source)
        results = []

        for horizon, hours in HORIZONS.items():
            artifact = self.artifact_repository.load(security_id, horizon)
            missing = [column for column in artifact.feature_names if column not in features.columns]
            if missing:
                raise ValueError(f"Feature schema mismatch for {security_id}/{horizon}: {missing[:5]}")
            latest = features.loc[:, list(artifact.feature_names)].iloc[[-1]]
            if latest.isna().any(axis=None):
                raise ValueError(f"Latest features contain missing values for {security_id}/{horizon}")

            predicted_return = artifact.predict_return(latest)
            predicted_source = current_source * float(np.exp(predicted_return))
            predicted_kg = self.unit_converter.usd_per_troy_ounce_to_usd_per_kg(predicted_source)
            delta_kg = predicted_kg - current_kg
            results.append({
                "horizon": horizon,
                "hours": hours,
                "current_usd_per_kg": round(current_kg, 2),
                "predicted_usd_per_kg": round(predicted_kg, 2),
                "change_usd_per_kg": round(delta_kg, 2),
                "change_pct": round((predicted_source / current_source - 1.0) * 100, 3),
                "direction": "UP" if predicted_source > current_source else "DOWN" if predicted_source < current_source else "FLAT",
                "confidence": round(artifact.confidence, 3),
                "validation_mae_return": round(artifact.validation_mae, 6),
                "feature_count": len(artifact.feature_names),
                "training_samples": artifact.training_samples,
                "trained_at": artifact.trained_at,
            })

        return {
            "metal": name,
            "security_id": security_id,
            "source_ticker": self.SOURCE_TICKERS.get(security_id),
            "current_usd_per_kg": round(current_kg, 2),
            "forecasts": results,
        }

    def predict_all(self) -> dict:
        hourly_context = self._context_frame("hourly")
        daily_context = self._context_frame("daily")
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "unit": "USD/kg",
            "data_source": self.DATA_SOURCE,
            "source_unit": "USD/troy oz for metal futures",
            "conversion": "1 kg = 32.1507466 troy oz",
            "architecture": "train-once-persist-load-predict",
            "method": "persisted direct multi-horizon error-weighted walk-forward ensembles",
            "context_assets": list(hourly_context.columns),
            "source_tickers": dict(self.SOURCE_TICKERS),
            "metals": [
                self.predict_metal(
                    metal.security_id,
                    metal.name,
                    hourly_context=hourly_context,
                    daily_context=daily_context,
                )
                for metal in METALS
            ],
        }
