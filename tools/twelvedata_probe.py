from __future__ import annotations

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
TIME_SERIES_URL = "https://api.twelvedata.com/time_series"
COMMODITIES_URL = "https://api.twelvedata.com/commodities"


def _request_json(url: str, params: dict) -> tuple[int, dict | list | str]:
    response = requests.get(url, params=params, timeout=60)
    try:
        payload = response.json()
    except ValueError:
        payload = response.text[:1000]
    return response.status_code, payload


def probe_catalog(api_key: str) -> dict:
    status_code, payload = _request_json(COMMODITIES_URL, {"apikey": api_key, "outputsize": 5000})
    symbols = []
    if isinstance(payload, dict):
        for item in payload.get("data") or []:
            if item.get("symbol") in SYMBOLS:
                symbols.append(item)
    return {"http_status": status_code, "matches": symbols}


def probe_latest(symbol: str, api_key: str) -> dict:
    status_code, payload = _request_json(
        TIME_SERIES_URL,
        {
            "symbol": symbol,
            "interval": INTERVAL,
            "timezone": "UTC",
            "outputsize": 5,
            "apikey": api_key,
        },
    )
    result = {"http_status": status_code}
    if isinstance(payload, dict):
        result["status"] = payload.get("status")
        result["message"] = payload.get("message")
        result["code"] = payload.get("code")
        result["meta"] = payload.get("meta")
        result["rows"] = len(payload.get("values") or [])
    else:
        result["body"] = str(payload)[:500]
    return result


def probe_range(symbol: str, api_key: str) -> dict:
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
    status_code, payload = _request_json(TIME_SERIES_URL, params)
    if status_code != 200 or not isinstance(payload, dict) or payload.get("status") == "error":
        if isinstance(payload, dict):
            return {
                "ok": False,
                "http_status": status_code,
                "status": payload.get("status"),
                "code": payload.get("code"),
                "message": payload.get("message"),
                "meta": payload.get("meta"),
            }
        return {"ok": False, "http_status": status_code, "body": str(payload)[:500]}

    values = payload.get("values") or []
    if not values:
        return {"ok": False, "http_status": status_code, "message": "No values returned", "meta": payload.get("meta")}

    df = pd.DataFrame(values)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.sort_values("datetime").drop_duplicates("datetime")
    numeric_columns = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    return {
        "ok": True,
        "http_status": status_code,
        "rows": int(len(df)),
        "columns": list(df.columns),
        "first_timestamp": df["datetime"].min().isoformat(),
        "last_timestamp": df["datetime"].max().isoformat(),
        "span_days": round((df["datetime"].max() - df["datetime"].min()).total_seconds() / 86400, 3),
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
        "catalog": probe_catalog(api_key),
        "symbols": [],
    }

    print(json.dumps({"catalog": report["catalog"]}, ensure_ascii=False))
    for symbol in SYMBOLS:
        item = {
            "symbol": symbol,
            "latest": probe_latest(symbol, api_key),
            "range": probe_range(symbol, api_key),
        }
        report["symbols"].append(item)
        safe_range = {k: v for k, v in item["range"].items() if k not in {"sample_first", "sample_last"}}
        print(json.dumps({"symbol": symbol, "latest": item["latest"], "range": safe_range}, ensure_ascii=False))

    Path("twelvedata_probe_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
