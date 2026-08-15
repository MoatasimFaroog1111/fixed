from dataclasses import dataclass
from typing import Protocol
import numpy as np
from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error


@dataclass(frozen=True)
class Forecast:
    predicted_return: float
    validation_mae: float
    confidence: float


class HorizonRegressor(Protocol):
    def fit_predict(self, X, y, latest) -> Forecast: ...


class WalkForwardEnsemble:
    """Time-ordered validation and error-weighted ensemble; never shuffles future into past."""
    def __init__(self, random_state: int = 42):
        self.random_state = random_state

    def fit_predict(self, X, y, latest) -> Forecast:
        n = len(X)
        if n < 250:
            raise ValueError("At least 250 usable observations are required")
        split = max(int(n * 0.8), n - 1000)
        Xtr, Xv = X.iloc[:split], X.iloc[split:]
        ytr, yv = y.iloc[:split], y.iloc[split:]
        factories = (
            lambda: ExtraTreesRegressor(n_estimators=350, min_samples_leaf=3, max_features=0.8, n_jobs=-1, random_state=self.random_state),
            lambda: RandomForestRegressor(n_estimators=300, min_samples_leaf=4, max_features=0.75, n_jobs=-1, random_state=self.random_state + 1),
            lambda: HistGradientBoostingRegressor(max_iter=300, learning_rate=0.035, l2_regularization=1.0, random_state=self.random_state + 2),
        )
        predictions, errors = [], []
        for factory in factories:
            model = factory()
            model.fit(Xtr, ytr)
            pv = model.predict(Xv)
            errors.append(max(mean_absolute_error(yv, pv), 1e-8))
            model.fit(X, y)
            predictions.append(float(model.predict(latest)[0]))
        inv = 1.0 / np.asarray(errors)
        weights = inv / inv.sum()
        pred = float(np.dot(weights, predictions))
        mae = float(np.dot(weights, errors))
        scale = float(np.nanstd(yv)) + 1e-8
        confidence = float(np.clip(1.0 - mae / (2.0 * scale), 0.05, 0.99))
        return Forecast(pred, mae, confidence)
