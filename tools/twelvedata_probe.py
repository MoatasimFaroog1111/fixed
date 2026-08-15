from __future__ import annotations

# Probe trigger after TWELVE_DATA_API_KEY was configured in repository secrets.
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

SYMBOLS = ["XAU/USD", "XAG/USD", "XPT/USD", "XPD/USD"]
START = "2021-08-15 00:00:00"
END = "2026-08-15 23:59:59"
INTERVAL = "1h"
API_URL = "https://api.twelvedata.com/time_series"


def fetch_symbol(symbol: str, api_key: str) -> dict:
    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "start_date": START,
        "end_date": END,
        "timezone": "UTC",
        "order": "ASC",
        "outputsize": 5000,
        "apikey": api_key,
    }
    response = requests.get(API_URL, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()

    if payload.get("status") == "error":
        return {"symbol": symbol, "ok": False, "error": payload}

    values = payload.get("values") or []
    if not values:
        return {"symbol": symbol, "ok": False, "error": "No values returned", "meta": payload.get("meta")}

    df = pd.DataFrame(values)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.sort_values("datetime").drop_duplicates("datetime")

    expected = pd.date_range(df["datetime"].min(), df["datetime"].max(), freq="1h", tz="UTC")
    observed = pd.DatetimeIndex(df["datetime"])
    missing = expected.difference(observed)

    numeric_columns = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    return {
        "symbol": symbol,
        "ok": True,
        "rows": int(len(df)),
        "columns": list(df.columns),
        "first_timestamp": df["datetime"].min().isoformat(),
        "last_timestamp": df["datetime"].max().isoformat(),
        "span_days": round((df["datetime"].max() - df["datetime"].min()).total_seconds() / 86400, 3),
        "missing_calendar_hours": int(len(missing)),
        "meta": payload.get("meta", {}),
        "sample_first": df.head(2).astype(str).to_dict(orient="records"),
        "sample_last": df.tail(2).astype(str).to_dict(orient="records"),
    }


def main() -> None:
    api_key = os.environ.get("TWELVE_DATA_API_KEY")
    if not api_key:
        raise SystemExit("TWELVE_DATA_API_KEY is required")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "interval": INTERVAL,
        "requested_start": START,
        "requested_end": END,
        "symbols": [],
    }

    for symbol in SYMBOLS:
        result = fetch_symbol(symbol, api_key)
        report["symbols"].append(result)
        safe = {k: v for k, v in result.items() if k not in {"sample_first", "sample_last"}}
        print(json.dumps(safe, ensure_ascii=False))

    Path("twelvedata_probe_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    failed = [item for item in report["symbols"] if not item.get("ok")]
    if failed:
        raise SystemExit(f"Probe failed for {len(failed)} symbol(s)")


if __name__ == "__main__":
    main()
