from __future__ import annotations

import numpy as np
import pandas as pd
from .artifacts import ForecastArtifactRepository, PickleForecastArtifactRepository
from .config import HORIZONS, METALS
from .data import PicklePriceRepository, PriceRepository
from .features import FeatureBuilder
from .model import HorizonTrainer, WalkForwardEnsembleTrainer


class PredictionTrainingService:
    """Offline application service. Owns training only; never used by web serving."""

    CONTEXT_IDS = tuple(m.security_id for m in METALS) + ("DXY",)

    def __init__(
        self,
        price_repository: PriceRepository | None = None,
        artifact_repository: ForecastArtifactRepository | None = None,
        feature_builder: FeatureBuilder | None = None,
        trainer: HorizonTrainer | None = None,
    ):
        self.price_repository = price_repository or PicklePriceRepository()
        self.artifact_repository = artifact_repository or PickleForecastArtifactRepository()
        self.feature_builder = feature_builder or FeatureBuilder()
        self.trainer = trainer or WalkForwardEnsembleTrainer()

    @staticmethod
    def _series(frame: pd.DataFrame) -> pd.Series:
        s = frame["price"].astype(float)
        index = pd.to_datetime(s.index, errors="coerce", utc=True)
        s.index = index.tz_convert(None)
        s = s[~s.index.isna()]
        return s.sort_index()[~s.index.duplicated(keep="last")]

    def _context_frame(self, frequency: str) -> pd.DataFrame:
        loader = self.price_repository.hourly if frequency == "hourly" else self.price_repository.daily
        columns = {}
        for security_id in self.CONTEXT_IDS:
            try:
                columns[security_id] = self._series(loader(security_id))
            except (FileNotFoundError, ValueError):
                continue
        return pd.concat(columns, axis=1, sort=False).sort_index() if columns else pd.DataFrame()

    def train_horizon(
        self,
        security_id: str,
        horizon: str,
        hourly_context: pd.DataFrame | None = None,
        daily_context: pd.DataFrame | None = None,
    ) -> dict:
        if horizon not in HORIZONS:
            raise ValueError(f"Unsupported horizon: {horizon}")
        hourly_context = hourly_context if hourly_context is not None else self._context_frame("hourly")
        daily_context = daily_context if daily_context is not None else self._context_frame("daily")
        prices = self._series(self.price_repository.hourly(security_id))
        features = self.feature_builder.build(
            prices,
            hourly_context=hourly_context,
            daily_context=daily_context,
        )
        steps = HORIZONS[horizon]
        target = np.log(prices.shift(-steps) / prices).rename("target")
        dataset = features.join(target).dropna()
        X = dataset.drop(columns="target")
        y = dataset["target"]
        artifact = self.trainer.train(security_id, horizon, X, y)
        path = self.artifact_repository.save(artifact)
        return {
            "security_id": security_id,
            "horizon": horizon,
            "path": str(path),
            "training_samples": artifact.training_samples,
            "feature_count": len(artifact.feature_names),
            "validation_mae": artifact.validation_mae,
            "confidence": artifact.confidence,
        }

    def train_metal(
        self,
        security_id: str,
        name: str,
        hourly_context: pd.DataFrame,
        daily_context: pd.DataFrame,
    ) -> dict:
        trained = [
            self.train_horizon(
                security_id,
                horizon,
                hourly_context=hourly_context,
                daily_context=daily_context,
            )
            for horizon in HORIZONS
        ]
        return {"metal": name, "security_id": security_id, "models": trained}

    def train_all(self) -> dict:
        hourly_context = self._context_frame("hourly")
        daily_context = self._context_frame("daily")
        results = [
            self.train_metal(
                metal.security_id,
                metal.name,
                hourly_context=hourly_context,
                daily_context=daily_context,
            )
            for metal in METALS
        ]
        return {
            "architecture": "train-once-persist-load-predict",
            "context_assets": list(hourly_context.columns),
            "metals": results,
        }
