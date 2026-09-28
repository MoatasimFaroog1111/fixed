from __future__ import annotations

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error

from .artifacts import PersistedForecastModel
from datetime import datetime, timezone


class DailyRegimeEnsembleTrainer:
    """Conservative ensemble for daily-sampled 1w/1m targets."""

    def __init__(self, random_state: int = 84):
        self.random_state = random_state

    def train(self, security_id: str, horizon: str, X, y) -> PersistedForecastModel:
        n = len(X)
        if n < 500:
            raise ValueError("At least 500 daily observations are required")
        validation_n = min(365, max(120, int(n * 0.20)))
        split = n - validation_n
        Xtr, Xv = X.iloc[:split], X.iloc[split:]
        ytr, yv = y.iloc[:split], y.iloc[split:]

        factories = (
            lambda: ExtraTreesRegressor(n_estimators=600, min_samples_leaf=8, max_features=0.55, n_jobs=-1, random_state=self.random_state),
            lambda: RandomForestRegressor(n_estimators=500, min_samples_leaf=10, max_features=0.50, n_jobs=-1, random_state=self.random_state + 1),
            lambda: HistGradientBoostingRegressor(max_iter=350, learning_rate=0.025, max_leaf_nodes=12, min_samples_leaf=20, l2_regularization=4.0, random_state=self.random_state + 2),
        )
        models, errors = [], []
        for factory in factories:
            model = factory()
            model.fit(Xtr, ytr)
            errors.append(max(mean_absolute_error(yv, model.predict(Xv)), 1e-8))
            model.fit(X, y)
            models.append(model)
        inverse = 1.0 / np.asarray(errors)
        weights = inverse / inverse.sum()
        validation_mae = float(np.dot(weights, errors))
        scale = float(np.nanstd(yv)) + 1e-8
        confidence = float(np.clip(1.0 - validation_mae / (2.0 * scale), 0.05, 0.99))
        return PersistedForecastModel(
            security_id=security_id, horizon=horizon,
            feature_names=tuple(str(c) for c in X.columns), models=tuple(models),
            weights=tuple(float(w) for w in weights), validation_mae=validation_mae,
            confidence=confidence, training_samples=int(n),
            trained_at=datetime.now(timezone.utc).isoformat(),
        )
