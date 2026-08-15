from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from prediction_system.config import HORIZONS, METALS
from prediction_system.data import PicklePriceRepository
from prediction_system.features import FeatureBuilder
from prediction_system.model import WalkForwardEnsembleTrainer
from prediction_system.trainer import PredictionTrainingService

MAP = {"AUXLN":"gold", "AGXLN":"silver", "PTXLN":"platinum", "PDXLN":"palladium"}


def load_candidate(root: Path, security_id: str) -> pd.DataFrame:
    path = root / f"{MAP[security_id]}_h1_usdkg.csv"
    df = pd.read_csv(path, parse_dates=["datetime"])
    idx = pd.DatetimeIndex(df["datetime"], name="datetime")
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    series = pd.Series(df["close"].astype(float).to_numpy(), index=idx, name="price")
    return series[~series.index.duplicated(keep="last")].sort_index().to_frame()


class CandidateRepository:
    """Candidate metals from Dukascopy; legacy data retained only for DXY context."""
    def __init__(self, candidate_root: Path, legacy_root: str = "data"):
        self.candidate_root = candidate_root
        self.legacy = PicklePriceRepository(legacy_root)

    def hourly(self, security_id: str) -> pd.DataFrame:
        if security_id in MAP:
            return load_candidate(self.candidate_root, security_id)
        return self.legacy.hourly(security_id)

    def daily(self, security_id: str) -> pd.DataFrame:
        if security_id in MAP:
            return self.hourly(security_id).resample("1D").last().dropna()
        return self.legacy.daily(security_id)


def _split_counts(n: int) -> tuple[int, int]:
    """Time-ordered holdout with trainer minimum preserved."""
    if n < 300:
        return 0, 0
    test_n = min(1000, max(50, int(n * 0.20)))
    train_n = n - test_n
    if train_n < 250:
        train_n = 250
        test_n = n - train_n
    return train_n, test_n


def evaluate(repo: CandidateRepository, security_id: str, horizon: str) -> dict:
    service = PredictionTrainingService(
        price_repository=repo,
        feature_builder=FeatureBuilder(),
        trainer=WalkForwardEnsembleTrainer(),
    )
    prices = service._series(repo.hourly(security_id))
    hourly_context = service._context_frame("hourly")
    daily_context = service._context_frame("daily")
    features = service.feature_builder.build(
        prices,
        hourly_context=hourly_context,
        daily_context=daily_context,
    )

    steps = HORIZONS[horizon]
    target = np.log(prices.shift(-steps) / prices).rename("target")
    dataset = features.join(target).dropna()
    train_n, test_n = _split_counts(len(dataset))

    diagnostics = {
        "raw_price_rows": int(len(prices)),
        "feature_rows": int(len(features)),
        "usable_rows": int(len(dataset)),
        "hourly_context_assets": list(hourly_context.columns),
        "daily_context_assets": list(daily_context.columns),
    }

    if train_n == 0 or test_n < 50:
        return {
            "status": "insufficient_usable_rows",
            **diagnostics,
            "required_minimum": 300,
        }

    X = dataset.drop(columns="target")
    y = dataset["target"]
    Xtr, Xte = X.iloc[:train_n], X.iloc[train_n:]
    ytr, yte = y.iloc[:train_n], y.iloc[train_n:]

    artifact = service.trainer.train(security_id, horizon, Xtr, ytr)
    model_preds = np.vstack([
        model.predict(Xte[list(artifact.feature_names)])
        for model in artifact.models
    ])
    weights = np.asarray(artifact.weights, dtype=float).reshape(-1, 1)
    preds = np.sum(model_preds * weights, axis=0)
    actual = yte.to_numpy()

    mae = float(np.mean(np.abs(preds - actual)))
    rmse = float(math.sqrt(np.mean((preds - actual) ** 2)))
    direction = float(np.mean(np.sign(preds) == np.sign(actual)))

    return {
        "status": "ok",
        **diagnostics,
        "train_samples": int(train_n),
        "test_samples": int(test_n),
        "mae_log_return": mae,
        "rmse_log_return": rmse,
        "direction_accuracy": direction,
        "internal_validation_mae": float(artifact.validation_mae),
        "confidence": float(artifact.confidence),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--out", default="candidate_backtest.json")
    args = parser.parse_args()

    repo = CandidateRepository(Path(args.candidate_dir))
    report = {
        "dataset": "Dukascopy H1 USD/kg candidate",
        "architecture": "isolated-candidate-no-production-overwrite",
        "results": {},
    }

    failures = 0
    for metal in METALS:
        report["results"][metal.security_id] = {}
        for horizon in HORIZONS:
            print("BACKTEST", metal.security_id, horizon, flush=True)
            result = evaluate(repo, metal.security_id, horizon)
            report["results"][metal.security_id][horizon] = result
            print(json.dumps({"metal": metal.security_id, "horizon": horizon, **result}), flush=True)
            if result.get("status") != "ok":
                failures += 1

    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"completed horizons={len(METALS) * len(HORIZONS)} insufficient={failures}")


if __name__ == "__main__":
    main()
