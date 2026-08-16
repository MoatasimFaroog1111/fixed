from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .model import HorizonTrainer, LongHorizonEnsembleTrainer, WalkForwardEnsembleTrainer


class HorizonTrainerPolicy(Protocol):
    def for_horizon(self, horizon: str) -> HorizonTrainer: ...


@dataclass(frozen=True)
class AdaptiveHorizonTrainerPolicy:
    """Selects a trainer by forecast horizon without coupling the training service to model details."""

    short_horizon_trainer: HorizonTrainer
    long_horizon_trainer: HorizonTrainer

    @classmethod
    def default(cls) -> "AdaptiveHorizonTrainerPolicy":
        return cls(
            short_horizon_trainer=WalkForwardEnsembleTrainer(),
            long_horizon_trainer=LongHorizonEnsembleTrainer(),
        )

    def for_horizon(self, horizon: str) -> HorizonTrainer:
        if horizon in {"1w", "1m"}:
            return self.long_horizon_trainer
        return self.short_horizon_trainer
