from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json


class JsonForecastSnapshotRepository:
    """Persist the latest complete forecast response for instant web serving."""

    def __init__(self, path: str = "prediction_runtime/latest_forecast.json"):
        self.path = Path(path)

    def save(self, payload: dict) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        enriched = dict(payload)
        enriched["snapshot_saved_at"] = datetime.now(timezone.utc).isoformat()
        temp.write_text(json.dumps(enriched, separators=(",", ":")), encoding="utf-8")
        temp.replace(self.path)
        return self.path

    def load(self) -> dict:
        if not self.path.exists():
            raise FileNotFoundError(f"Forecast snapshot not ready: {self.path}")
        return json.loads(self.path.read_text(encoding="utf-8"))

    def exists(self) -> bool:
        return self.path.exists() and self.path.stat().st_size > 0
