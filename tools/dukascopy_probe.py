from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://freeserv.dukascopy.com/2.0/"
TARGET_TOKENS = {
    "gold": ["XAU/USD", "XAUUSD", "GOLD"],
    "silver": ["XAG/USD", "XAGUSD", "SILVER"],
    "platinum": ["XPT", "PLATINUM"],
    "palladium": ["XPD", "PALLADIUM"],
}
SAMPLE_START = int(datetime(2021, 8, 15, tzinfo=timezone.utc).timestamp() * 1000)
SAMPLE_END = int(datetime(2021, 8, 22, tzinfo=timezone.utc).timestamp() * 1000)


def get_json(params: dict) -> tuple[int, object]:
    response = requests.get(BASE_URL, params=params, timeout=60)
    try:
        payload = response.json()
    except ValueError:
        payload = {"text": response.text[:2000]}
    return response.status_code, payload


def collect_instrument_dicts(node: object, out: list[dict]) -> None:
    if isinstance(node, dict):
        if "id" in node and any(k in node for k in ("name", "nameLong", "symbol", "instrument")):
            out.append(node)
        for value in node.values():
            collect_instrument_dicts(value, out)
    elif isinstance(node, list):
        for value in node:
            collect_instrument_dicts(value, out)


def normalize_instruments(payload: object) -> list[dict]:
    found: list[dict] = []
    collect_instrument_dicts(payload, found)
    seen = set()
    unique = []
    for item in found:
        key = (str(item.get("id")), str(item.get("name")), str(item.get("nameLong")))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def raw_shape(payload: object) -> dict:
    if isinstance(payload, dict):
        return {"type": "dict", "keys": list(payload.keys())[:30], "preview": str(payload)[:1000]}
    if isinstance(payload, list):
        return {"type": "list", "length": len(payload), "preview": str(payload[:3])[:1000]}
    return {"type": type(payload).__name__, "preview": str(payload)[:1000]}


def searchable_text(item: dict) -> str:
    return " ".join(str(item.get(k, "")) for k in ("id", "name", "nameLong", "symbol", "instrument")).upper()


def find_candidates(instruments: list[dict], tokens: list[str]) -> list[dict]:
    return [item for item in instruments if any(token.upper() in searchable_text(item) for token in tokens)]


def historical_sample(instrument_id: int | str) -> dict:
    status, payload = get_json({
        "path": "api/historicalPrices",
        "instrument": instrument_id,
        "timeFrame": "1hour",
        "count": 200,
        "start": SAMPLE_START,
        "end": SAMPLE_END,
        "dayStartTime": "UTC",
        "offerSide": "B",
    })
    result = {"http_status": status, "payload_type": type(payload).__name__}
    if isinstance(payload, list):
        result["rows"] = len(payload)
        result["sample_first"] = payload[:2]
        result["sample_last"] = payload[-2:]
    else:
        result["payload"] = payload
    return result


def main() -> None:
    status, raw = get_json({
        "path": "api/instrumentList",
        "fields": "id,name,pipValue,nameLong",
    })
    instruments = normalize_instruments(raw)
    shape = raw_shape(raw)
    print(json.dumps({"instrument_list_http_status": status, "shape": shape, "normalized_count": len(instruments)}, ensure_ascii=False))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "instrument_list_http_status": status,
        "raw_shape": shape,
        "instrument_count": len(instruments),
        "targets": {},
    }

    for metal, tokens in TARGET_TOKENS.items():
        candidates = find_candidates(instruments, tokens)
        compact = [
            {k: item.get(k) for k in ("id", "name", "nameLong", "pipValue") if k in item}
            for item in candidates[:10]
        ]
        target = {"search_tokens": tokens, "catalog_matches": compact, "h1_samples": []}
        for item in candidates[:3]:
            instrument_id = item.get("id")
            if instrument_id is None:
                continue
            target["h1_samples"].append({
                "instrument": {k: item.get(k) for k in ("id", "name", "nameLong")},
                "sample": historical_sample(instrument_id),
            })
        report["targets"][metal] = target
        print(json.dumps({metal: target}, ensure_ascii=False))

    Path("dukascopy_probe_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
