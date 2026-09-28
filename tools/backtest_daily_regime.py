from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from prediction_system.daily_regime_features import DailyRegimeFeatureBuilder
from prediction_system.daily_regime_model import DailyRegimeEnsembleTrainer
from prediction_system.daily_targets import DailyLongHorizonTargetBuilder
from prediction_system.trainer import PredictionTrainingService
from tools.backtest_dukascopy_candidate import CandidateRepository, _filter_context


def evaluate(repo: CandidateRepository, security_id: str, horizon: str, folds: int = 4, test_size: int = 120, min_train_size: int = 500) -> dict:
    service = PredictionTrainingService(price_repository=repo)
    prices = service._series(repo.hourly(security_id))
    daily_context, coverage = _filter_context(service._context_frame("daily"), prices.index, "daily")
    builder = DailyRegimeFeatureBuilder()
    features = builder.build(prices, daily_context=daily_context)
    target = DailyLongHorizonTargetBuilder().build(prices, horizon)
    dataset = features.join(target).dropna()
    trainer = DailyRegimeEnsembleTrainer()
    purge_days = DailyLongHorizonTargetBuilder.DAYS[horizon]

    results, n = [], len(dataset)
    for fold in range(folds):
        test_end = n - fold * test_size
        test_start = test_end - test_size
        if test_start <= 0:
            break
        test = dataset.iloc[test_start:test_end]
        cutoff = test.index[0] - np.timedelta64(purge_days, "D")
        train = dataset.loc[dataset.index < cutoff]
        if len(train) < min_train_size or len(test) < 60:
            continue
        Xtr, ytr = train.drop(columns="target"), train["target"]
        Xte, yte = test.drop(columns="target"), test["target"]
        artifact = trainer.train(security_id, horizon, Xtr, ytr)
        model_preds = np.vstack([m.predict(Xte[list(artifact.feature_names)]) for m in artifact.models])
        preds = np.sum(model_preds * np.asarray(artifact.weights).reshape(-1, 1), axis=0)
        actual = yte.to_numpy()
        results.append({
            "fold": fold + 1, "train_samples": int(len(train)), "test_samples": int(len(test)),
            "test_start": str(test.index[0]), "test_end": str(test.index[-1]),
            "direction_accuracy": float(np.mean(np.sign(preds) == np.sign(actual))),
            "mae_log_return": float(np.mean(np.abs(preds - actual))),
            "rmse_log_return": float(math.sqrt(np.mean((preds - actual) ** 2))),
        })

    if not results:
        return {"status":"insufficient_data","metal":security_id,"horizon":horizon,"usable_daily_rows":int(n),"min_train_size":int(min_train_size)}
    direction = np.asarray([r["direction_accuracy"] for r in results])
    return {
        "status":"ok", "metal":security_id, "horizon":horizon,
        "architecture":"daily-regime-purged-walk-forward", "purge_days":purge_days,
        "feature_builder":type(builder).__name__, "trainer":type(trainer).__name__,
        "usable_daily_rows":int(n), "fold_count":len(results),
        "test_size":int(test_size), "min_train_size":int(min_train_size),
        "test_samples_total":int(sum(r["test_samples"] for r in results)),
        "direction_accuracy_mean":float(direction.mean()), "direction_accuracy_min":float(direction.min()),
        "direction_accuracy_std":float(direction.std()),
        "mae_mean":float(np.mean([r["mae_log_return"] for r in results])),
        "rmse_mean":float(np.mean([r["rmse_log_return"] for r in results])),
        "daily_context_coverage":coverage, "folds":results,
    }


def main():
    p=argparse.ArgumentParser(); p.add_argument("--candidate-dir",required=True); p.add_argument("--metal",required=True,choices=("AUXLN","AGXLN","PTXLN","PDXLN")); p.add_argument("--horizon",required=True,choices=("1w","1m")); p.add_argument("--folds",type=int,default=4); p.add_argument("--test-size",type=int,default=120); p.add_argument("--min-train-size",type=int,default=500); p.add_argument("--out",required=True); a=p.parse_args()
    report=evaluate(CandidateRepository(Path(a.candidate_dir)),a.metal,a.horizon,a.folds,a.test_size,a.min_train_size)
    Path(a.out).write_text(json.dumps(report,indent=2),encoding="utf-8"); print(json.dumps(report),flush=True)

if __name__ == "__main__": main()
