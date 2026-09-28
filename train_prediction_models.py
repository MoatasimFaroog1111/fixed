"""Offline training entrypoint for persisted multi-horizon prediction models."""
import argparse
import json
from prediction_system import PredictionTrainingService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--security-id")
    parser.add_argument("--horizon")
    args = parser.parse_args()

    service = PredictionTrainingService()
    if args.security_id or args.horizon:
        if not (args.security_id and args.horizon):
            parser.error("--security-id and --horizon must be provided together")
        result = service.train_horizon(args.security_id, args.horizon)
    else:
        result = service.train_all()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
