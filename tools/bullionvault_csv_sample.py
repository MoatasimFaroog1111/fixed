from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass

import pandas as pd
import requests

HOST = "https://chart-data.bullionvault.com"
METALS = ("AUX", "AGX", "PTX", "PDX")
# Intervals exposed by BullionVault's official embedded chart library.
INTERVALS = (15, 120, 600, 3600, 14400, 172800, 864000)


@dataclass
class Sample:
    metal: str
    interval_seconds: int
    url: str
    status: int
    content_type: str
    bytes: int
    rows: int
    columns: list[str]
    first_row: list[str] | None
    last_row: list[str] | None
    first_timestamp: str | None
    last_timestamp: str | None
    span_days: float | None
    median_delta_seconds: float | None


def parse_timestamps(frame: pd.DataFrame) -> pd.Series | None:
    if frame.empty:
        return None
    candidates = list(frame.columns[:2])
    for column in candidates:
        series = frame[column]
        parsed = pd.to_datetime(series, errors="coerce", utc=True)
        if parsed.notna().mean() >= 0.8:
            return parsed.dropna()
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.notna().mean() >= 0.8:
            for unit in ("ms", "s"):
                parsed = pd.to_datetime(numeric, unit=unit, errors="coerce", utc=True)
                if parsed.notna().mean() >= 0.8:
                    return parsed.dropna()
    return None


def sample(metal: str, interval: int) -> Sample:
    url = f"{HOST}/prices/CSV/{metal}/USD/{interval}/Full"
    response = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0 BullionVault-history-validation/1.0"})
    response.raise_for_status()
    text = response.text
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0] if rows else []
    data = [row for row in rows[1:] if any(cell.strip() for cell in row)] if rows else []

    frame = pd.read_csv(io.StringIO(text)) if text.strip() else pd.DataFrame()
    ts = parse_timestamps(frame)
    first_ts = last_ts = None
    span_days = median_delta = None
    if ts is not None and not ts.empty:
        ts = ts.sort_values().drop_duplicates()
        first_ts = ts.iloc[0].isoformat()
        last_ts = ts.iloc[-1].isoformat()
        span_days = round((ts.iloc[-1] - ts.iloc[0]).total_seconds() / 86400, 3)
        if len(ts) > 1:
            median_delta = float(ts.diff().dropna().dt.total_seconds().median())

    return Sample(
        metal=metal,
        interval_seconds=interval,
        url=url,
        status=response.status_code,
        content_type=response.headers.get("content-type", ""),
        bytes=len(response.content),
        rows=len(data),
        columns=[str(c) for c in frame.columns] if not frame.empty else header,
        first_row=data[0] if data else None,
        last_row=data[-1] if data else None,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        span_days=span_days,
        median_delta_seconds=median_delta,
    )


def main() -> None:
    results: list[Sample] = []
    for metal in METALS:
        for interval in INTERVALS:
            item = sample(metal, interval)
            results.append(item)
            print(json.dumps(asdict(item), ensure_ascii=False))

    with open("bullionvault_csv_sample_report.json", "w", encoding="utf-8") as handle:
        json.dump([asdict(item) for item in results], handle, ensure_ascii=False, indent=2)

    print("\nSUMMARY")
    for item in results:
        print(
            item.metal,
            item.interval_seconds,
            "rows=", item.rows,
            "span_days=", item.span_days,
            "median_delta_s=", item.median_delta_seconds,
            "columns=", item.columns,
        )


if __name__ == "__main__":
    main()
