from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .features import FeatureBuilder
from .long_horizon_features import LongHorizonFeatureBuilder


class HorizonFeaturePolicy(Protocol):
    def for_horizon(self, horizon: str): ...


@dataclass(frozen=True)
class AdaptiveHorizonFeaturePolicy:
    """Selects the feature pipeline by forecast horizon."""

    short_horizon_builder: object
    long_horizon_builder: object

    @classmethod
    def default(cls) -> "AdaptiveHorizonFeaturePolicy":
        return cls(
            short_horizon_builder=FeatureBuilder(),
            long_horizon_builder=LongHorizonFeatureBuilder(),
        )

    def for_horizon(self, horizon: str):
        if horizon in {"1w", "1m"}:
            return self.long_horizon_builder
        return self.short_horizon_builder
