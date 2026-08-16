from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from prediction_system.config import HORIZONS
from prediction_system.features import FeatureBuilder
from prediction_system.trainer import PredictionTrainingService
from tools.backtest_dukascopy_candidate import (
    CandidateRepository,
    _filter_context,
    _filter_features,
)


def evaluate_folded(repo: CandidateRepository, security_id: str, horizon: str, folds: int = 4, test_size: int = 500) -> dict:
    service = PredictionTrainingService(price_repository=repo, feature_builder=FeatureBuilder())
    prices = service._series(repo.hourly(security_id))
    hourly_context, _ = _filter_context(service._context_frame("hourly"), prices.index, "hourly")
    daily_context, _ = _filter_context(service._context_frame("daily"), prices.index, "daily")
    builder = service.feature_policy.for_horizon(horizon)
    raw_features = builder.build(prices, hourly_context=hourly_context, daily_context=daily_context)
    features, _, _ = _filter_features(raw_features)
    target = service.target_builder.build(prices, HORIZONS[horizon])
    dataset = features.join(target).dropna()
    trainer = service.trainer_policy.for_horizon(horizon)

    horizon_hours = int(HORIZONS[horizon])
    results = []
    n = len(dataset)
    for fold in range(folds):
        test_end = n - fold * test_size
        test_start_pos = test_end - test_size
        if test_start_pos <= 0:
            break
        test = dataset.iloc[test_start_pos:test_end]
        if test.empty:
            continue

        # Purge every training label whose target timestamp could overlap the test window.
        cutoff = test.index[0] - np.timedelta64(horizon_hours, "h")
        train = dataset.loc[dataset.index < cutoff]
        if len(train) < 500:
            continue

        Xtr, ytr = train.drop(columns="target"), train["target"]
        Xte, yte = test.drop(columns="target"), test["target"]
        artifact = trainer.train(security_id, horizon, Xtr, ytr)
        model_preds = np.vstack([model.predict(Xte[list(artifact.feature_names)]) for model in artifact.models])
        weights = np.asarray(artifact.weights, dtype=float).reshape(-1, 1)
        preds = np.sum(model_preds * weights, axis=0)
        actual = yte.to_numpy()
        results.append({
            "fold": fold + 1,
            "train_samples": int(len(train)),
            "test_samples": int(len(test)),
            "test_start": str(test.index[0]),
            "test_end": str(test.index[-1]),
            "mae_log_return": float(np.mean(np.abs(preds - actual))),
            "rmse_log_return": float(math.sqrt(np.mean((preds - actual) ** 2))),
            "direction_accuracy": float(np.mean(np.sign(preds) == np.sign(actual))),
        })

    if not results:
        return {"status": "insufficient_data", "metal": security_id, "horizon": horizon}

    direction = np.asarray([r["direction_accuracy"] for r in results])
    mae = np.asarray([r["mae_log_return"] for r in results])
    rmse = np.asarray([r["rmse_log_return"] for r in results])
    return {
        "status": "ok",
        "metal": security_id,
        "horizon": horizon,
        "validation": "purged-walk-forward",
        "purge_hours": horizon_hours,
        "feature_builder": type(builder).__name__,
        "trainer": type(trainer).__name__,
        "fold_count": len(results),
        "test_samples_total": int(sum(r["test_samples"] for r in results)),
        "direction_accuracy_mean": float(direction.mean()),
        "direction_accuracy_min": float(direction.min()),
        "direction_accuracy_std": float(direction.std()),
        "mae_mean": float(mae.mean()),
        "rmse_mean": float(rmse.mean()),
        "folds": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--metal", required=True, choices=("AUXLN", "AGXLN", "PTXLN", "PDXLN"))
    parser.add_argument("--horizon", required=True, choices=("1w", "1m"))
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--test-size", type=int, default=500)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    report = evaluate_folded(
        CandidateRepository(Path(args.candidate_dir)),
        args.metal,
        args.horizon,
        folds=args.folds,
        test_size=args.test_size,
    )
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
