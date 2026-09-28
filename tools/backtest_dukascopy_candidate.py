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
from prediction_system.long_horizon_features import LongHorizonFeatureBuilder
from prediction_system.trainer import PredictionTrainingService

MAP = {"AUXLN":"gold", "AGXLN":"silver", "PTXLN":"platinum", "PDXLN":"palladium"}
MIN_CONTEXT_COVERAGE = 0.80
MIN_FEATURE_COVERAGE = 0.95


def load_candidate(root: Path, security_id: str) -> pd.DataFrame:
    path = root / f"{MAP[security_id]}_h1_usdkg.csv"
    df = pd.read_csv(path, parse_dates=["datetime"])
    idx = pd.DatetimeIndex(df["datetime"], name="datetime")
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    series = pd.Series(df["close"].astype(float).to_numpy(), index=idx, name="price")
    return series[~series.index.duplicated(keep="last")].sort_index().to_frame()


class CandidateRepository:
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


def _normalize_index(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, utc=True).tz_convert(None)
        out = out.sort_index()
        out = out[~out.index.duplicated(keep="last")]
    return out


def _filter_context(context: pd.DataFrame, target_index: pd.DatetimeIndex, frequency: str) -> tuple[pd.DataFrame, dict]:
    if context is None or context.empty:
        return pd.DataFrame(index=target_index), {}
    context = _normalize_index(context)
    probe_index = pd.DatetimeIndex(target_index.normalize().unique()) if frequency == "daily" else target_index
    kept, coverage = {}, {}
    for name in context.columns:
        s = context[name].astype(float).replace([np.inf, -np.inf], np.nan).dropna()
        if s.empty:
            coverage[name] = 0.0
            continue
        ratio = float(s.reindex(probe_index, method="ffill").notna().mean())
        coverage[name] = ratio
        if ratio >= MIN_CONTEXT_COVERAGE:
            kept[name] = s
    return (pd.concat(kept, axis=1, sort=False) if kept else pd.DataFrame()), coverage


def _warmup_rows(builder) -> int:
    if isinstance(builder, LongHorizonFeatureBuilder):
        return max(LongHorizonFeatureBuilder.HOURLY_WINDOWS)
    return max(FeatureBuilder.WINDOWS)


def _filter_features(features: pd.DataFrame, warmup_rows: int) -> tuple[pd.DataFrame, dict[str, float], list[str]]:
    clean = features.replace([np.inf, -np.inf], np.nan)
    probe = clean.iloc[min(warmup_rows, max(0, len(clean) - 1)):]
    coverage = {str(col): float(probe[col].notna().mean()) for col in clean.columns}
    kept = [col for col in clean.columns if coverage[str(col)] >= MIN_FEATURE_COVERAGE]
    dropped = [str(col) for col in clean.columns if col not in kept]
    return (clean[kept] if kept else pd.DataFrame(index=clean.index)), coverage, dropped


def _split_counts(n: int) -> tuple[int, int]:
    if n < 300:
        return 0, 0
    test_n = min(1000, max(50, int(n * 0.20)))
    train_n = n - test_n
    if train_n < 250:
        train_n, test_n = 250, n - 250
    return train_n, test_n


def evaluate(repo: CandidateRepository, security_id: str, horizon: str) -> dict:
    service = PredictionTrainingService(price_repository=repo)
    prices = service._series(repo.hourly(security_id))
    hourly_context, hourly_coverage = _filter_context(service._context_frame("hourly"), prices.index, "hourly")
    daily_context, daily_coverage = _filter_context(service._context_frame("daily"), prices.index, "daily")
    feature_builder = service.feature_policy.for_horizon(horizon)
    raw_features = feature_builder.build(prices, hourly_context=hourly_context, daily_context=daily_context)
    features, feature_coverage, dropped_features = _filter_features(raw_features, _warmup_rows(feature_builder))
    target = service.target_builder.build(prices, HORIZONS[horizon])
    dataset = features.join(target).dropna()
    train_n, test_n = _split_counts(len(dataset))
    trainer = service.trainer_policy.for_horizon(horizon)

    diagnostics = {
        "raw_price_rows": int(len(prices)), "feature_rows": int(len(raw_features)), "usable_rows": int(len(dataset)),
        "kept_feature_count": int(features.shape[1]), "dropped_feature_count": int(len(dropped_features)),
        "dropped_features": dropped_features, "hourly_context_assets": list(hourly_context.columns),
        "daily_context_assets": list(daily_context.columns), "hourly_context_coverage": hourly_coverage,
        "daily_context_coverage": daily_coverage, "minimum_context_coverage": MIN_CONTEXT_COVERAGE,
        "minimum_feature_coverage": MIN_FEATURE_COVERAGE,
        "minimum_feature_coverage_observed": float(min(feature_coverage.values())) if feature_coverage else 0.0,
        "target_mode": "time-aware-clock-hours", "trainer": type(trainer).__name__,
        "feature_builder": type(feature_builder).__name__,
    }
    if train_n == 0 or test_n < 50:
        return {"status": "insufficient_usable_rows", **diagnostics, "required_minimum": 300}

    X, y = dataset.drop(columns="target"), dataset["target"]
    Xtr, Xte, ytr, yte = X.iloc[:train_n], X.iloc[train_n:], y.iloc[:train_n], y.iloc[train_n:]
    artifact = trainer.train(security_id, horizon, Xtr, ytr)
    model_preds = np.vstack([model.predict(Xte[list(artifact.feature_names)]) for model in artifact.models])
    weights = np.asarray(artifact.weights, dtype=float).reshape(-1, 1)
    preds, actual = np.sum(model_preds * weights, axis=0), yte.to_numpy()
    return {
        "status": "ok", **diagnostics, "train_samples": int(train_n), "test_samples": int(test_n),
        "mae_log_return": float(np.mean(np.abs(preds - actual))),
        "rmse_log_return": float(math.sqrt(np.mean((preds - actual) ** 2))),
        "direction_accuracy": float(np.mean(np.sign(preds) == np.sign(actual))),
        "internal_validation_mae": float(artifact.validation_mae), "confidence": float(artifact.confidence),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--out", default="candidate_backtest.json")
    parser.add_argument("--metal", choices=tuple(MAP))
    parser.add_argument("--horizon", choices=tuple(HORIZONS))
    args = parser.parse_args()
    repo = CandidateRepository(Path(args.candidate_dir))
    selected_metals = [m for m in METALS if args.metal is None or m.security_id == args.metal]
    selected_horizons = [h for h in HORIZONS if args.horizon is None or h == args.horizon]
    report = {"dataset":"Dukascopy H1 USD/kg candidate", "architecture":"horizon-feature-and-trainer-policy-time-aware-target-no-production-overwrite", "selection":{"metal":args.metal,"horizon":args.horizon}, "results":{}}
    failures = completed = 0
    for metal in selected_metals:
        report["results"][metal.security_id] = {}
        for horizon in selected_horizons:
            print("BACKTEST", metal.security_id, horizon, flush=True)
            result = evaluate(repo, metal.security_id, horizon)
            report["results"][metal.security_id][horizon] = result
            print(json.dumps({"metal":metal.security_id,"horizon":horizon,**result}), flush=True)
            completed += 1
            failures += result.get("status") != "ok"
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"completed horizons={completed} insufficient={failures}")


if __name__ == "__main__":
    main()
