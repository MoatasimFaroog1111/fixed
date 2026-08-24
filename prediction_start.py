"""Railway entrypoint for the standalone prediction dashboard service."""
from __future__ import annotations

import os
import threading

from prediction_model_bootstrap import ensure_models
from prediction_system import PredictionService
from prediction_system.snapshot import JsonForecastSnapshotRepository


def _warm_snapshot() -> None:
    snapshots = JsonForecastSnapshotRepository()
    try:
        print("Building forecast snapshot from persisted models...")
        payload = PredictionService().predict_all()
        path = snapshots.save(payload)
        print(f"Forecast snapshot ready: {path}")
    except Exception as exc:
        print(f"Forecast snapshot warmup failed: {exc}", flush=True)


def main() -> None:
    ensure_models()
    import prediction_dashboard  # imported after models exist

    threading.Thread(target=_warm_snapshot, name="forecast-snapshot-warmup", daemon=True).start()

    port = int(os.getenv("PORT", "8080"))
    server = prediction_dashboard.ThreadingHTTPServer(("0.0.0.0", port), prediction_dashboard.Handler)
    print(f"Prediction dashboard listening on 0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
