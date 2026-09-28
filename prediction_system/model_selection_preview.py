from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class ModelSelectionPreviewResult:
    security_id: str
    metal: str
    horizon: str
    direction_accuracy_mean_pct: float
    direction_accuracy_min_pct: float
    direction_accuracy_std_pct: float
    fold_count: int
    hourly_long_wins: int
    daily_regime_wins: int
    hourly_long_rows: int
    daily_regime_rows: int


class ModelSelectionPreviewRepository:
    """Read-only preview of the latest validated nested-purged model-selection run.

    This component is deliberately isolated from production forecast artifacts. It exists
    only to expose experimental validation results without changing serving behavior.
    """

    RUN_ID = 31950050993
    COMMIT = "e11130b8f59c5fd55621be01c5740f67e1238790"
    ARCHITECTURE = "nested-purged-calendar-aligned-model-selection"

    _RESULTS = (
        ModelSelectionPreviewResult("AUXLN", "Gold", "1w", 49.23, 45.00, 3.40, 3, 2, 1, 1371, 912),
        ModelSelectionPreviewResult("AUXLN", "Gold", "1m", 53.52, 24.17, 22.10, 3, 3, 0, 1348, 912),
        ModelSelectionPreviewResult("AGXLN", "Silver", "1w", 40.97, 29.57, 11.47, 3, 3, 0, 1076, 744),
        ModelSelectionPreviewResult("AGXLN", "Silver", "1m", 43.19, 26.19, 14.17, 3, 2, 1, 1053, 744),
        ModelSelectionPreviewResult("PTXLN", "Platinum", "1w", 37.48, 36.70, 0.78, 2, 2, 0, 874, 739),
        ModelSelectionPreviewResult("PTXLN", "Platinum", "1m", 16.57, 14.78, 1.78, 2, 2, 0, 851, 739),
        ModelSelectionPreviewResult("PDXLN", "Palladium", "1w", 44.99, 39.13, 5.58, 3, 3, 0, 1105, 832),
        ModelSelectionPreviewResult("PDXLN", "Palladium", "1m", 31.28, 23.64, 5.44, 3, 2, 1, 1082, 832),
    )

    def load(self) -> dict:
        return {
            "status": "preview",
            "production_unchanged": True,
            "run_id": self.RUN_ID,
            "commit": self.COMMIT,
            "architecture": self.ARCHITECTURE,
            "warning": "Experimental backtest validation only; these metrics are not live price forecasts.",
            "results": [asdict(item) for item in self._RESULTS],
        }
