"""Download persisted prediction models from the public GitHub release when absent."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import requests

REPO = os.getenv("PREDICTION_MODEL_REPO", "MoatasimFaroog1111/fixed")
TAG = os.getenv("PREDICTION_MODEL_RELEASE", "prediction-models-v1")
MODEL_ROOT = Path(os.getenv("PREDICTION_MODEL_DIR", "prediction_models"))
METALS = ("AUXLN", "AGXLN", "PTXLN", "PDXLN")
HORIZONS = ("6h", "12h", "18h", "24h", "48h", "1w", "1m")


def expected_models() -> list[tuple[str, str, Path]]:
    return [
        (metal, horizon, MODEL_ROOT / metal / f"{horizon}.pkl")
        for metal in METALS
        for horizon in HORIZONS
    ]


def models_ready() -> bool:
    return all(path.is_file() and path.stat().st_size > 0 for _, _, path in expected_models())


def _release_assets() -> dict[str, str]:
    url = f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    payload = response.json()
    return {asset["name"]: asset["browser_download_url"] for asset in payload.get("assets", [])}


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=(30, 900)) as response:
        response.raise_for_status()
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    tmp.write(chunk)
    tmp_path.replace(destination)


def ensure_models() -> None:
    if models_ready():
        print("Prediction models already present; bootstrap skipped.")
        return

    assets = _release_assets()
    missing_assets: list[str] = []
    for metal, horizon, destination in expected_models():
        if destination.is_file() and destination.stat().st_size > 0:
            continue
        asset_name = f"{metal}-{horizon}.pkl"
        asset_url = assets.get(asset_name)
        if not asset_url:
            missing_assets.append(asset_name)
            continue
        print(f"Downloading {asset_name} -> {destination}")
        _download(asset_url, destination)

    if missing_assets:
        raise RuntimeError("Missing release model assets: " + ", ".join(missing_assets))
    if not models_ready():
        raise RuntimeError("Prediction model bootstrap finished but the model set is incomplete")


if __name__ == "__main__":
    ensure_models()
