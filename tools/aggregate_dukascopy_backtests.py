from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

METAL_NAMES = {
    "AUXLN": "Gold",
    "AGXLN": "Silver",
    "PTXLN": "Platinum",
    "PDXLN": "Palladium",
}

HORIZON_ORDER = ["6h", "12h", "18h", "24h", "48h", "1w", "1m"]


def classify(direction: float, confidence: float) -> str:
    if direction >= 0.65 and confidence >= 0.55:
        return "strong"
    if direction >= 0.58 and confidence >= 0.45:
        return "usable"
    return "needs_specialized_model"


def extract_result(payload: dict) -> tuple[str | None, str | None, dict]:
    selection = payload.get("selection") or {}
    metal = selection.get("metal") or payload.get("metal")
    horizon = selection.get("horizon") or payload.get("horizon")
    if metal and horizon:
        nested = ((payload.get("results") or {}).get(metal) or {}).get(horizon)
        if isinstance(nested, dict):
            return metal, horizon, nested
    result = payload.get("result")
    return metal, horizon, result if isinstance(result, dict) else {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--json-out", default="dukascopy_backtest_summary.json")
    ap.add_argument("--csv-out", default="dukascopy_backtest_summary.csv")
    args = ap.parse_args()

    root = Path(args.input_dir)
    rows = []
    for path in sorted(root.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        metal, horizon, result = extract_result(payload)
        if not metal or not horizon or not result:
            continue
        direction = float(result.get("direction_accuracy") or 0.0)
        confidence = float(result.get("confidence") or 0.0)
        rows.append({
            "metal": metal,
            "metal_name": METAL_NAMES.get(metal, metal),
            "horizon": horizon,
            "status": result.get("status"),
            "test_samples": result.get("test_samples"),
            "mae_log_return": result.get("mae_log_return"),
            "rmse_log_return": result.get("rmse_log_return"),
            "direction_accuracy": direction,
            "confidence": confidence,
            "usable_rows": result.get("usable_rows"),
            "train_samples": result.get("train_samples"),
            "classification": classify(direction, confidence) if result.get("status") == "ok" else "failed",
        })

    rank = {h: i for i, h in enumerate(HORIZON_ORDER)}
    metal_rank = {m: i for i, m in enumerate(METAL_NAMES)}
    rows.sort(key=lambda r: (metal_rank.get(r["metal"], 99), rank.get(r["horizon"], 99)))

    summary = {
        "dataset": "Dukascopy H1 USD/kg candidate",
        "result_count": len(rows),
        "expected_count": 28,
        "all_complete": len(rows) == 28 and all(r["status"] == "ok" for r in rows),
        "strong_count": sum(r["classification"] == "strong" for r in rows),
        "usable_count": sum(r["classification"] == "usable" for r in rows),
        "needs_specialized_model_count": sum(r["classification"] == "needs_specialized_model" for r in rows),
        "results": rows,
    }
    Path(args.json_out).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    with Path(args.csv_out).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["metal", "horizon", "status"])
        writer.writeheader()
        writer.writerows(rows)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
