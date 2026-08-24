"""SOLID multi-horizon precious-metal forecasting package."""
from .service import PredictionService
from .trainer import PredictionTrainingService

__all__ = ["PredictionService", "PredictionTrainingService"]
