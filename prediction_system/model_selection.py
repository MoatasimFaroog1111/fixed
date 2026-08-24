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
    validation_start: str
    validation_end: str


@dataclass(frozen=True)
class SelectionResult:
    winner: ModelCandidate
    scores: tuple[CandidateScore, ...]


class PurgedLongHorizonModelSelector:
    """Select architectures on the same calendar window while preserving each candidate's own sampling."""

    def __init__(
        self,
        validation_days: int = 120,
        min_fit_size: int = 500,
        min_validation_samples: int = 60,
        mae_penalty: float = 0.10,
    ):
        self.validation_days = validation_days
        self.min_fit_size = min_fit_size
        self.min_validation_samples = min_validation_samples
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
        outer_test_start: pd.Timestamp,
        purge_days: int,
    ) -> CandidateScore | None:
        validation_end = pd.Timestamp(outer_test_start)
        validation_start = validation_end - pd.Timedelta(days=self.validation_days)
        data = candidate.dataset.dropna().sort_index()
        validation = data.loc[(data.index >= validation_start) & (data.index < validation_end)]
        if len(validation) < self.min_validation_samples:
            return None

        fit_cutoff = validation_start - pd.Timedelta(days=purge_days)
        fit = data.loc[data.index < fit_cutoff]
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
        return CandidateScore(
            name=candidate.name,
            direction_accuracy=direction,
            normalized_mae=normalized_mae,
            score=score,
            validation_samples=int(len(validation)),
            validation_start=str(validation.index[0]),
            validation_end=str(validation.index[-1]),
        )

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
            raise ValueError("No model candidate has enough data in the shared purged calendar validation window")
        scores.sort(key=lambda item: (item.score, item.direction_accuracy, -item.normalized_mae), reverse=True)
        winner_name = scores[0].name
        winner = next(candidate for candidate in candidates if candidate.name == winner_name)
        return SelectionResult(winner=winner, scores=tuple(scores))
