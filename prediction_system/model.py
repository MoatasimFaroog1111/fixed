from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
import numpy as np
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from .artifacts import PersistedForecastModel


@dataclass(frozen=True)
class Forecast:
    predicted_return: float
    validation_mae: float
    confidence: float


class HorizonTrainer(Protocol):
    def train(self, security_id: str, horizon: str, X, y) -> PersistedForecastModel: ...


class WalkForwardEnsembleTrainer:
    """Offline trainer with time-ordered validation and error-weighted ensemble."""

    def __init__(self, random_state: int = 42):
        self.random_state = random_state

    def _factories(self):
        return (
            lambda: ExtraTreesRegressor(
                n_estimators=350,
                min_samples_leaf=3,
                max_features=0.8,
                n_jobs=-1,
                random_state=self.random_state,
            ),
            lambda: RandomForestRegressor(
                n_estimators=300,
                min_samples_leaf=4,
                max_features=0.75,
                n_jobs=-1,
                random_state=self.random_state + 1,
            ),
            lambda: HistGradientBoostingRegressor(
                max_iter=300,
                learning_rate=0.035,
                l2_regularization=1.0,
                random_state=self.random_state + 2,
            ),
        )

    def train(self, security_id: str, horizon: str, X, y) -> PersistedForecastModel:
        n = len(X)
        if n < 250:
            raise ValueError("At least 250 usable observations are required")

        split = max(int(n * 0.8), n - 1000)
        Xtr, Xv = X.iloc[:split], X.iloc[split:]
        ytr, yv = y.iloc[:split], y.iloc[split:]

        models = []
        errors = []
        for factory in self._factories():
            model = factory()
            model.fit(Xtr, ytr)
            validation_predictions = model.predict(Xv)
            errors.append(max(mean_absolute_error(yv, validation_predictions), 1e-8))
            model.fit(X, y)
            models.append(model)

        inverse = 1.0 / np.asarray(errors)
        weights = inverse / inverse.sum()
        validation_mae = float(np.dot(weights, errors))
        scale = float(np.nanstd(yv)) + 1e-8
        confidence = float(np.clip(1.0 - validation_mae / (2.0 * scale), 0.05, 0.99))

        return PersistedForecastModel(
            security_id=security_id,
            horizon=horizon,
            feature_names=tuple(str(column) for column in X.columns),
            models=tuple(models),
            weights=tuple(float(value) for value in weights),
            validation_mae=validation_mae,
            confidence=confidence,
            training_samples=int(n),
            trained_at=datetime.now(timezone.utc).isoformat(),
        )
