from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd

from .artifacts import PersistedForecastModel


class CandidateTrainer(Protocol):
    def train(self, security_id: str, horizon: str, X, y) -> PersistedForecastModel: ...


@dataclass(frozen=True)
class ModelCandidate:
    name: str
    dataset: pd.DataFrame
    trainer: CandidateTrainer


@dataclass(frozen=True)
class CandidateScore:
    name: str
    direction_accuracy: float
    normalized_mae: float
    score: float
    validation_samples: int


@dataclass(frozen=True)
class SelectionResult:
    winner: ModelCandidate
    scores: tuple[CandidateScore, ...]


class PurgedLongHorizonModelSelector:
    """Select a long-horizon architecture using only pre-test, purged validation data."""

    def __init__(self, validation_size: int = 120, min_fit_size: int = 500, mae_penalty: float = 0.10):
        self.validation_size = validation_size
        self.min_fit_size = min_fit_size
        self.mae_penalty = mae_penalty

    @staticmethod
    def _predict(artifact: PersistedForecastModel, X: pd.DataFrame) -> np.ndarray:
        model_preds = np.vstack([m.predict(X[list(artifact.feature_names)]) for m in artifact.models])
        weights = np.asarray(artifact.weights, dtype=float).reshape(-1, 1)
        return np.sum(model_preds * weights, axis=0)

    def _score_candidate(
        self,
        candidate: ModelCandidate,
        security_id: str,
        horizon: str,
        cutoff: pd.Timestamp,
        purge_days: int,
    ) -> CandidateScore | None:
        available = candidate.dataset.loc[candidate.dataset.index < cutoff].dropna()
        if len(available) < self.min_fit_size + self.validation_size:
            return None
        validation = available.iloc[-self.validation_size:]
        fit_cutoff = validation.index[0] - pd.Timedelta(days=purge_days)
        fit = available.loc[available.index < fit_cutoff]
        if len(fit) < self.min_fit_size:
            return None
        Xtr, ytr = fit.drop(columns="target"), fit["target"]
        Xv, yv = validation.drop(columns="target"), validation["target"]
        artifact = candidate.trainer.train(security_id, horizon, Xtr, ytr)
        preds = self._predict(artifact, Xv)
        actual = yv.to_numpy()
        direction = float(np.mean(np.sign(preds) == np.sign(actual)))
        mae = float(np.mean(np.abs(preds - actual)))
        scale = float(np.std(actual)) + 1e-8
        normalized_mae = mae / scale
        score = direction - self.mae_penalty * normalized_mae
        return CandidateScore(candidate.name, direction, normalized_mae, score, len(validation))

    def select(
        self,
        candidates: tuple[ModelCandidate, ...],
        security_id: str,
        horizon: str,
        outer_test_start: pd.Timestamp,
        purge_days: int,
    ) -> SelectionResult:
        scores = []
        for candidate in candidates:
            scored = self._score_candidate(candidate, security_id, horizon, outer_test_start, purge_days)
            if scored is not None:
                scores.append(scored)
        if not scores:
            raise ValueError("No model candidate has enough purged inner-validation history")
        scores.sort(key=lambda item: (item.score, item.direction_accuracy, -item.normalized_mae), reverse=True)
        winner_name = scores[0].name
        winner = next(candidate for candidate in candidates if candidate.name == winner_name)
        return SelectionResult(winner=winner, scores=tuple(scores))
