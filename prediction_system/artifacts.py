from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
import json
import pickle


@dataclass(frozen=True)
class PersistedForecastModel:
    security_id: str
    horizon: str
    feature_names: tuple[str, ...]
    models: tuple[Any, ...]
    weights: tuple[float, ...]
    validation_mae: float
    confidence: float
    training_samples: int
    trained_at: str

    def predict_return(self, latest) -> float:
        values = [float(model.predict(latest)[0]) for model in self.models]
        return float(sum(weight * value for weight, value in zip(self.weights, values)))


class ForecastArtifactRepository(Protocol):
    def save(self, artifact: PersistedForecastModel) -> Path: ...
    def load(self, security_id: str, horizon: str) -> PersistedForecastModel: ...
    def exists(self, security_id: str, horizon: str) -> bool: ...


class PickleForecastArtifactRepository:
    """Filesystem persistence adapter. Training writes; serving only reads."""

    def __init__(self, root: str = "prediction_models"):
        self.root = Path(root)

    def _path(self, security_id: str, horizon: str) -> Path:
        return self.root / security_id / f"{horizon}.pkl"

    def save(self, artifact: PersistedForecastModel) -> Path:
        path = self._path(artifact.security_id, artifact.horizon)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        with temp.open("wb") as handle:
            pickle.dump(artifact, handle, protocol=pickle.HIGHEST_PROTOCOL)
        temp.replace(path)
        self._write_manifest_entry(artifact)
        return path

    def load(self, security_id: str, horizon: str) -> PersistedForecastModel:
        path = self._path(security_id, horizon)
        if not path.exists():
            raise FileNotFoundError(
                f"Persisted model not found for {security_id}/{horizon}. "
                "Run train_prediction_models.py first."
            )
        with path.open("rb") as handle:
            artifact = pickle.load(handle)
        if not isinstance(artifact, PersistedForecastModel):
            raise TypeError(f"Invalid prediction artifact: {path}")
        return artifact

    def exists(self, security_id: str, horizon: str) -> bool:
        return self._path(security_id, horizon).exists()

    def _write_manifest_entry(self, artifact: PersistedForecastModel) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        manifest_path = self.root / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        except Exception:
            manifest = {}
        key = f"{artifact.security_id}:{artifact.horizon}"
        manifest[key] = {
            "security_id": artifact.security_id,
            "horizon": artifact.horizon,
            "feature_count": len(artifact.feature_names),
            "training_samples": artifact.training_samples,
            "validation_mae": artifact.validation_mae,
            "confidence": artifact.confidence,
            "trained_at": artifact.trained_at,
        }
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
