from datetime import datetime, timezone
import numpy as np
import pandas as pd
from .config import METALS, HORIZONS
from .data import PicklePriceRepository, PriceRepository
from .features import FeatureBuilder
from .model import WalkForwardEnsemble


class PredictionService:
    """Application service: orchestrates data, features and independent horizon models."""
    CONTEXT_IDS = tuple(m.security_id for m in METALS) + ("DXY",)

    def __init__(self, repository: PriceRepository | None = None):
        self.repository = repository or PicklePriceRepository()
        self.features = FeatureBuilder()

    @staticmethod
    def _series(frame: pd.DataFrame) -> pd.Series:
        s = frame["price"].astype(float)
        idx = pd.to_datetime(s.index, errors="coerce", utc=True)
        valid = ~idx.isna()
        s = s[valid].copy()
        s.index = idx[valid].tz_convert(None)
        return s.sort_index()[~s.index.duplicated(keep="last")]

    def _context_frame(self, frequency: str) -> pd.DataFrame:
        columns = {}
        loader = self.repository.hourly if frequency == "hourly" else self.repository.daily
        for security_id in self.CONTEXT_IDS:
            try:
                columns[security_id] = self._series(loader(security_id))
            except (FileNotFoundError, ValueError):
                continue
        if not columns:
            return pd.DataFrame()
        return pd.concat(columns, axis=1, sort=False).sort_index()

    def predict_metal(
        self,
        security_id: str,
        name: str,
        hourly_context: pd.DataFrame | None = None,
        daily_context: pd.DataFrame | None = None,
    ) -> dict:
        prices = self._series(self.repository.hourly(security_id))
        X = self.features.build(prices, hourly_context=hourly_context, daily_context=daily_context)
        current = float(prices.iloc[-1])
        results = []

        for label, steps in HORIZONS.items():
            target = np.log(prices.shift(-steps) / prices)
            dataset = X.join(target.rename("target")).dropna()
            latest = X.iloc[[-1]].dropna(axis=1)
            cols = dataset.drop(columns="target").columns.intersection(latest.columns)
            train = dataset[cols].dropna()
            y = dataset.loc[train.index, "target"]

            if len(train) < 250:
                results.append({"horizon": label, "status": "insufficient_data"})
                continue

            forecast = WalkForwardEnsemble().fit_predict(train, y, latest[cols])
            predicted = current * float(np.exp(forecast.predicted_return))
            results.append({
                "horizon": label,
                "hours": steps,
                "current_usd_per_kg": round(current, 4),
                "predicted_usd_per_kg": round(predicted, 4),
                "change_pct": round((predicted / current - 1.0) * 100, 3),
                "direction": "UP" if predicted > current else "DOWN" if predicted < current else "FLAT",
                "confidence": round(forecast.confidence, 3),
                "validation_mae_return": round(forecast.validation_mae, 6),
                "feature_count": int(len(cols)),
                "training_samples": int(len(train)),
            })

        return {"metal": name, "security_id": security_id, "forecasts": results}

    def predict_all(self) -> dict:
        hourly_context = self._context_frame("hourly")
        daily_context = self._context_frame("daily")
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "unit": "USD/kg",
            "method": "direct multi-horizon error-weighted walk-forward ensemble with cross-asset and daily-regime context",
            "context_assets": list(hourly_context.columns),
            "metals": [
                self.predict_metal(
                    m.security_id,
                    m.name,
                    hourly_context=hourly_context,
                    daily_context=daily_context,
                )
                for m in METALS
            ],
        }
