from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_URL = "https://freeserv.dukascopy.com/2.0/"
TARGETS = {
    "gold": ["XAUUSD"],
    "silver": ["XAGUSD"],
    "platinum": ["XPT.CMD/USD", "XPTCMDUSD"],
    "palladium": ["XPD.CMD/USD", "XPDCMDUSD"],
}


def get_json(params: dict) -> tuple[int, object]:
    response = requests.get(BASE_URL, params=params, timeout=45)
    try:
        payload = response.json()
    except ValueError:
        payload = {"text": response.text[:1000]}
    return response.status_code, payload


def main() -> None:
    status, instruments = get_json({"path": "api/instrumentList"})
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "instrument_list_http_status": status,
        "targets": {},
    }

    searchable = json.dumps(instruments, ensure_ascii=False).upper()
    for metal, candidates in TARGETS.items():
        matches = [candidate for candidate in candidates if candidate.upper() in searchable]
        report["targets"][metal] = {"candidates": candidates, "catalog_matches": matches}
        print(json.dumps({metal: report["targets"][metal]}, ensure_ascii=False))

    Path("dukascopy_probe_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
