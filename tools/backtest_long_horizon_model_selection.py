from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from prediction_system.daily_regime_features import DailyRegimeFeatureBuilder
from prediction_system.daily_regime_model import DailyRegimeEnsembleTrainer
from prediction_system.daily_targets import DailyLongHorizonTargetBuilder
from prediction_system.long_horizon_features import LongHorizonFeatureBuilder
from prediction_system.model import LongHorizonEnsembleTrainer
from prediction_system.model_selection import ModelCandidate, PurgedLongHorizonModelSelector
from prediction_system.trainer import PredictionTrainingService
from tools.backtest_dukascopy_candidate import CandidateRepository, _filter_context


def _predict(artifact, X: pd.DataFrame) -> np.ndarray:
    model_preds = np.vstack([m.predict(X[list(artifact.feature_names)]) for m in artifact.models])
    weights = np.asarray(artifact.weights, dtype=float).reshape(-1, 1)
    return np.sum(model_preds * weights, axis=0)


def _build_candidates(repo: CandidateRepository, security_id: str, horizon: str):
    service = PredictionTrainingService(price_repository=repo)
    prices = service._series(repo.hourly(security_id))
    hourly_context, _ = _filter_context(service._context_frame("hourly"), prices.index, "hourly")
    daily_context, coverage = _filter_context(service._context_frame("daily"), prices.index, "daily")
    target = DailyLongHorizonTargetBuilder().build(prices, horizon)

    hourly_features = LongHorizonFeatureBuilder().build(
        prices, hourly_context=hourly_context, daily_context=daily_context
    ).resample("1D").last()
    hourly_dataset = hourly_features.join(target).dropna()

    daily_features = DailyRegimeFeatureBuilder().build(prices, daily_context=daily_context)
    daily_dataset = daily_features.join(target).dropna()

    candidates = (
        ModelCandidate("hourly-long", hourly_dataset, LongHorizonEnsembleTrainer()),
        ModelCandidate("daily-regime", daily_dataset, DailyRegimeEnsembleTrainer()),
    )
    common_index = hourly_dataset.index.intersection(daily_dataset.index).sort_values()
    return candidates, common_index, coverage


def evaluate(repo: CandidateRepository, security_id: str, horizon: str, folds: int = 3, test_size: int = 120) -> dict:
    candidates, common_index, coverage = _build_candidates(repo, security_id, horizon)
    purge_days = DailyLongHorizonTargetBuilder.DAYS[horizon]
    selector = PurgedLongHorizonModelSelector(validation_size=90, min_fit_size=500, mae_penalty=0.10)
    results = []

    for fold in range(folds):
        test_end = len(common_index) - fold * test_size
        test_start = test_end - test_size
        if test_start <= 0:
            break
        test_index = common_index[test_start:test_end]
        if len(test_index) < 60:
            continue
        outer_test_start = test_index[0]
        try:
            selection = selector.select(candidates, security_id, horizon, outer_test_start, purge_days)
        except ValueError:
            continue

        winner = selection.winner
        cutoff = outer_test_start - pd.Timedelta(days=purge_days)
        train = winner.dataset.loc[winner.dataset.index < cutoff].dropna()
        test = winner.dataset.loc[winner.dataset.index.intersection(test_index)].dropna()
        if len(train) < 500 or len(test) < 60:
            continue
        Xtr, ytr = train.drop(columns="target"), train["target"]
        Xte, yte = test.drop(columns="target"), test["target"]
        artifact = winner.trainer.train(security_id, horizon, Xtr, ytr)
        preds = _predict(artifact, Xte)
        actual = yte.to_numpy()
        results.append({
            "fold": fold + 1,
            "winner": winner.name,
            "train_samples": int(len(train)),
            "test_samples": int(len(test)),
            "test_start": str(test.index[0]),
            "test_end": str(test.index[-1]),
            "direction_accuracy": float(np.mean(np.sign(preds) == np.sign(actual))),
            "mae_log_return": float(np.mean(np.abs(preds - actual))),
            "rmse_log_return": float(math.sqrt(np.mean((preds - actual) ** 2))),
            "selection_scores": [
                {
                    "candidate": s.name,
                    "direction_accuracy": s.direction_accuracy,
                    "normalized_mae": s.normalized_mae,
                    "score": s.score,
                    "validation_samples": s.validation_samples,
                }
                for s in selection.scores
            ],
        })

    if not results:
        return {
            "status": "insufficient_data",
            "metal": security_id,
            "horizon": horizon,
            "common_daily_rows": int(len(common_index)),
        }

    direction = np.asarray([r["direction_accuracy"] for r in results])
    winners = {name: sum(r["winner"] == name for r in results) for name in ("hourly-long", "daily-regime")}
    return {
        "status": "ok",
        "metal": security_id,
        "horizon": horizon,
        "architecture": "nested-purged-per-metal-model-selection",
        "purge_days": purge_days,
        "inner_validation_days": 90,
        "outer_test_days": test_size,
        "fold_count": len(results),
        "test_samples_total": int(sum(r["test_samples"] for r in results)),
        "direction_accuracy_mean": float(direction.mean()),
        "direction_accuracy_min": float(direction.min()),
        "direction_accuracy_std": float(direction.std()),
        "mae_mean": float(np.mean([r["mae_log_return"] for r in results])),
        "rmse_mean": float(np.mean([r["rmse_log_return"] for r in results])),
        "winner_counts": winners,
        "daily_context_coverage": coverage,
        "folds": results,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--candidate-dir", required=True)
    p.add_argument("--metal", required=True, choices=("AUXLN", "AGXLN", "PTXLN", "PDXLN"))
    p.add_argument("--horizon", required=True, choices=("1w", "1m"))
    p.add_argument("--folds", type=int, default=3)
    p.add_argument("--test-size", type=int, default=120)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    report = evaluate(CandidateRepository(Path(a.candidate_dir)), a.metal, a.horizon, a.folds, a.test_size)
    Path(a.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
