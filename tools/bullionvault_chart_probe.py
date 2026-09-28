from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, asdict
from typing import Iterable
from urllib.parse import urljoin

import requests

BASE = "https://www.bullionvault.com"
LIBRARY = f"{BASE}/chart/bullionvaultchart.js?v=1"
METALS = ("gold", "silver", "platinum", "palladium")
TIMEFRAMES = ("1h", "6h", "1d", "1w", "1m", "1y", "5y", "20y")


@dataclass
class ProbeResult:
    metal: str
    timeframe: str
    url: str
    status: int | None
    content_type: str | None
    bytes: int
    csv_rows: int | None = None
    columns: list[str] | None = None
    first_row: list[str] | None = None
    last_row: list[str] | None = None
    error: str | None = None


def _get_text(url: str) -> str:
    response = requests.get(url, timeout=45, headers={"User-Agent": "Mozilla/5.0 BV-chart-probe/1.0"})
    response.raise_for_status()
    return response.text


def discover_endpoint_templates(js: str) -> list[str]:
    """Find URL-like strings in the official chart library, prioritising CSV/export/data endpoints."""
    strings = re.findall(r"['\"]([^'\"]{4,300})['\"]", js)
    candidates: list[str] = []
    for value in strings:
        low = value.lower()
        if any(token in low for token in ("csv", "export", "chart", "data")) and (
            ".do" in low or ".csv" in low or "download" in low or "chart" in low
        ):
            if value not in candidates:
                candidates.append(value)
    return candidates


def _normalise_candidate(value: str) -> str:
    value = value.replace("\\/", "/")
    if value.startswith("//"):
        return "https:" + value
    return urljoin(BASE + "/", value)


def _looks_like_csv(response: requests.Response) -> bool:
    ctype = (response.headers.get("content-type") or "").lower()
    text = response.text[:500].lower()
    return "csv" in ctype or ("," in text and "<html" not in text and "<!doctype" not in text)


def _summarise_csv(text: str) -> tuple[int, list[str], list[str] | None, list[str] | None]:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return 0, [], None, None
    header = rows[0]
    data = [row for row in rows[1:] if any(cell.strip() for cell in row)]
    return len(data), header, (data[0] if data else None), (data[-1] if data else None)


def build_candidate_urls(templates: Iterable[str], metal: str, timeframe: str) -> list[str]:
    urls: list[str] = []
    replacements = {
        "{metal}": metal,
        "{bullion}": metal,
        "{timeframe}": timeframe,
        "{timeScale}": timeframe,
        "{currency}": "USD",
    }
    for raw in templates:
        value = raw
        for old, new in replacements.items():
            value = value.replace(old, new)
        # Also replace common JS concatenation placeholders conservatively.
        value = re.sub(r"['\"]?\s*\+\s*(?:this\.)?(?:bullion|metal)\s*\+\s*['\"]?", metal, value)
        value = re.sub(r"['\"]?\s*\+\s*(?:this\.)?(?:timeframe|timeScale)\s*\+\s*['\"]?", timeframe, value)
        value = re.sub(r"['\"]?\s*\+\s*(?:this\.)?currency\s*\+\s*['\"]?", "USD", value)
        if "http" in value or value.startswith("/"):
            url = _normalise_candidate(value)
            if url not in urls:
                urls.append(url)

    # Known chart pages are included as diagnostic fallbacks; the probe does not assume they are CSV.
    fallbacks = [
        f"{BASE}/{metal}-price-chart.do?currency=USD&timeframe={timeframe}&weight=kg",
        f"{BASE}/chart-popup.do?metal={metal}&timeScale={timeframe}",
    ]
    for url in fallbacks:
        if url not in urls:
            urls.append(url)
    return urls


def probe_url(url: str, metal: str, timeframe: str) -> ProbeResult:
    try:
        response = requests.get(url, timeout=45, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0 BV-chart-probe/1.0"})
        result = ProbeResult(
            metal=metal,
            timeframe=timeframe,
            url=response.url,
            status=response.status_code,
            content_type=response.headers.get("content-type"),
            bytes=len(response.content),
        )
        if response.ok and _looks_like_csv(response):
            rows, columns, first_row, last_row = _summarise_csv(response.text)
            result.csv_rows = rows
            result.columns = columns
            result.first_row = first_row
            result.last_row = last_row
        return result
    except Exception as exc:
        return ProbeResult(metal, timeframe, url, None, None, 0, error=repr(exc))


def main() -> int:
    js = _get_text(LIBRARY)
    print(f"Loaded official chart library: {len(js):,} chars")
    templates = discover_endpoint_templates(js)
    print("\nDiscovered URL-like export/data candidates:")
    for item in templates:
        print("  ", item)

    # Print code neighbourhoods around CSV/export tokens so the exact request construction is visible in CI logs.
    print("\nJS neighbourhoods around csv/export/download:")
    lowered = js.lower()
    for token in ("csv", "export", "download"):
        start = 0
        hits = 0
        while hits < 8:
            idx = lowered.find(token, start)
            if idx < 0:
                break
            lo, hi = max(0, idx - 350), min(len(js), idx + 500)
            print(f"\n--- {token} @ {idx} ---\n{js[lo:hi]}")
            start = idx + len(token)
            hits += 1

    results: list[ProbeResult] = []
    for metal in METALS:
        # Start with 1h and 5y because these directly test the desired history/resolution combination.
        for timeframe in ("1h", "5y"):
            for url in build_candidate_urls(templates, metal, timeframe)[:20]:
                result = probe_url(url, metal, timeframe)
                results.append(result)
                print(json.dumps(asdict(result), ensure_ascii=False))
                if result.csv_rows:
                    print(f"FOUND CSV: {metal} {timeframe} rows={result.csv_rows} url={result.url}")
                    break

    with open("bullionvault_chart_probe_report.json", "w", encoding="utf-8") as handle:
        json.dump([asdict(item) for item in results], handle, ensure_ascii=False, indent=2)

    found = [item for item in results if item.csv_rows]
    print(f"\nCSV responses found: {len(found)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
