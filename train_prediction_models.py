"""Offline training entrypoint for persisted multi-horizon prediction models."""
import json
from prediction_system import PredictionTrainingService


if __name__ == "__main__":
    result = PredictionTrainingService().train_all()
    print(json.dumps(result, indent=2))
