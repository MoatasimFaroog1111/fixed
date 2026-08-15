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
MIN_CONTEXT_COVERAGE = 0.80
MIN_FEATURE_COVERAGE = 0.95
FEATURE_WARMUP_ROWS = max(FeatureBuilder.WINDOWS)


def load_candidate(root: Path, security_id: str) -> pd.DataFrame:
    path = root / f"{MAP[security_id]}_h1_usdkg.csv"
    df = pd.read_csv(path, parse_dates=["datetime"])
    idx = pd.DatetimeIndex(df["datetime"], name="datetime")
    if idx.tz is not None:
        idx = idx.tz_convert(None)
    series = pd.Series(df["close"].astype(float).to_numpy(), index=idx, name="price")
    return series[~series.index.duplicated(keep="last")].sort_index().to_frame()


class CandidateRepository:
    """Candidate metals from Dukascopy; legacy data retained only for optional context."""
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
    """Keep only context assets with sufficient causal coverage over the candidate period."""
    if context is None or context.empty:
        return pd.DataFrame(index=target_index), {}

    context = _normalize_index(context)
    probe_index = pd.DatetimeIndex(target_index.normalize().unique()) if frequency == "daily" else target_index

    kept: dict[str, pd.Series] = {}
    coverage: dict[str, float] = {}
    for name in context.columns:
        s = context[name].astype(float).replace([np.inf, -np.inf], np.nan).dropna()
        if s.empty:
            coverage[name] = 0.0
            continue
        aligned = s.reindex(probe_index, method="ffill")
        ratio = float(aligned.notna().mean())
        coverage[name] = ratio
        if ratio >= MIN_CONTEXT_COVERAGE:
            kept[name] = s

    if not kept:
        return pd.DataFrame(), coverage
    return pd.concat(kept, axis=1, sort=False), coverage


def _filter_features(features: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float], list[str]]:
    """Remove derived columns that cannot support a stable time-series backtest.

    Coverage is measured after the expected rolling-feature warmup. This keeps the
    production FeatureBuilder untouched while preventing a single stale context
    feature from invalidating every candidate observation.
    """
    clean = features.replace([np.inf, -np.inf], np.nan)
    probe = clean.iloc[min(FEATURE_WARMUP_ROWS, max(0, len(clean) - 1)):]
    coverage = {str(col): float(probe[col].notna().mean()) for col in clean.columns}
    kept = [col for col in clean.columns if coverage[str(col)] >= MIN_FEATURE_COVERAGE]
    dropped = [str(col) for col in clean.columns if col not in kept]
    if not kept:
        return pd.DataFrame(index=clean.index), coverage, dropped
    return clean[kept], coverage, dropped


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
    raw_hourly_context = service._context_frame("hourly")
    raw_daily_context = service._context_frame("daily")
    hourly_context, hourly_coverage = _filter_context(raw_hourly_context, prices.index, "hourly")
    daily_context, daily_coverage = _filter_context(raw_daily_context, prices.index, "daily")

    raw_features = service.feature_builder.build(
        prices,
        hourly_context=hourly_context,
        daily_context=daily_context,
    )
    features, feature_coverage, dropped_features = _filter_features(raw_features)

    steps = HORIZONS[horizon]
    target = np.log(prices.shift(-steps) / prices).replace([np.inf, -np.inf], np.nan).rename("target")
    dataset = features.join(target).dropna()
    train_n, test_n = _split_counts(len(dataset))

    diagnostics = {
        "raw_price_rows": int(len(prices)),
        "feature_rows": int(len(raw_features)),
        "usable_rows": int(len(dataset)),
        "kept_feature_count": int(features.shape[1]),
        "dropped_feature_count": int(len(dropped_features)),
        "dropped_features": dropped_features,
        "hourly_context_assets": list(hourly_context.columns),
        "daily_context_assets": list(daily_context.columns),
        "hourly_context_coverage": hourly_coverage,
        "daily_context_coverage": daily_coverage,
        "minimum_context_coverage": MIN_CONTEXT_COVERAGE,
        "minimum_feature_coverage": MIN_FEATURE_COVERAGE,
        "minimum_feature_coverage_observed": float(min(feature_coverage.values())) if feature_coverage else 0.0,
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
        "architecture": "isolated-candidate-context-and-feature-coverage-filtered-no-production-overwrite",
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
