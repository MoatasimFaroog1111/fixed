from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from prediction_system.artifacts import PickleForecastArtifactRepository
from prediction_system.config import HORIZONS, METALS
from prediction_system.data import PicklePriceRepository
from prediction_system.features import FeatureBuilder
from prediction_system.model import WalkForwardEnsembleTrainer
from prediction_system.trainer import PredictionTrainingService

MAP = {"AUXLN":"gold", "AGXLN":"silver", "PTXLN":"platinum", "PDXLN":"palladium"}


def load_candidate(root: Path, security_id: str) -> pd.DataFrame:
    p = root / f"{MAP[security_id]}_h1_usdkg.csv"
    df = pd.read_csv(p, parse_dates=["datetime"])
    s = pd.Series(df["close"].astype(float).to_numpy(), index=pd.DatetimeIndex(df["datetime"], name="datetime"), name="price")
    s.index = s.index.tz_convert(None) if s.index.tz is not None else s.index
    return s.to_frame()


class CandidateRepository:
    def __init__(self, candidate_root: Path, legacy_root: str="data"):
        self.candidate_root = candidate_root
        self.legacy = PicklePriceRepository(legacy_root)
    def hourly(self, security_id: str) -> pd.DataFrame:
        if security_id in MAP:
            return load_candidate(self.candidate_root, security_id)
        return self.legacy.hourly(security_id)
    def daily(self, security_id: str) -> pd.DataFrame:
        if security_id in MAP:
            h = self.hourly(security_id)
            return h.resample("1D").last().dropna()
        return self.legacy.daily(security_id)


def evaluate(repo, security_id: str, horizon: str) -> dict:
    service = PredictionTrainingService(price_repository=repo, feature_builder=FeatureBuilder(), trainer=WalkForwardEnsembleTrainer())
    prices = service._series(repo.hourly(security_id))
    features = service.feature_builder.build(prices, hourly_context=service._context_frame("hourly"), daily_context=service._context_frame("daily"))
    steps = HORIZONS[horizon]
    target = np.log(prices.shift(-steps) / prices).rename("target")
    ds = features.join(target).dropna()
    X, y = ds.drop(columns="target"), ds["target"]
    split = max(250, int(len(ds)*0.8))
    split = min(split, len(ds)-100)
    Xtr, Xte, ytr, yte = X.iloc[:split], X.iloc[split:], y.iloc[:split], y.iloc[split:]
    artifact = service.trainer.train(security_id, horizon, Xtr, ytr)
    preds = np.mean([m.predict(Xte[artifact.feature_names]) for m in artifact.models], axis=0)
    mae = float(np.mean(np.abs(preds-yte.to_numpy())))
    rmse = float(math.sqrt(np.mean((preds-yte.to_numpy())**2)))
    direction = float(np.mean(np.sign(preds)==np.sign(yte.to_numpy())))
    return {"samples":len(ds), "test_samples":len(yte), "mae_log_return":mae, "rmse_log_return":rmse, "direction_accuracy":direction}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--candidate-dir", required=True); ap.add_argument("--out", default="candidate_backtest.json"); args=ap.parse_args()
    repo=CandidateRepository(Path(args.candidate_dir))
    report={"dataset":"Dukascopy H1 USD/kg candidate", "architecture":"isolated-candidate-no-production-overwrite", "results":{}}
    for metal in METALS:
        report["results"][metal.security_id]={}
        for horizon in HORIZONS:
            print("BACKTEST", metal.security_id, horizon, flush=True)
            report["results"][metal.security_id][horizon]=evaluate(repo, metal.security_id, horizon)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

if __name__=="__main__": main()
