#!/usr/bin/env python3
"""
네이버 증권에서 코스피(KOSPI) 최근 30거래일 데이터를 가져와
index.html의 RAW_DATA 및 기준일 문구를 자동 갱신합니다.
"""
import json
import re
import urllib.request
from pathlib import Path

API_URL = "https://m.stock.naver.com/api/index/KOSPI/price?pageSize=30&page=1"
INDEX_HTML = Path(__file__).resolve().parent / "index.html"


def fetch_kospi_30d() -> list[dict]:
    req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = json.loads(resp.read().decode("utf-8"))

    rows = []
    for r in raw:
        rows.append({
            "date": r["localTradedAt"],
            "close": float(str(r["closePrice"]).replace(",", "")),
            "open": float(str(r["openPrice"]).replace(",", "")),
            "high": float(str(r["highPrice"]).replace(",", "")),
            "low": float(str(r["lowPrice"]).replace(",", "")),
            "change": float(str(r["compareToPreviousClosePrice"]).replace(",", "")),
            "ratio": float(str(r["fluctuationsRatio"]).replace(",", "")),
        })
    return rows


def update_html(rows: list[dict]) -> None:
    if not rows:
        raise RuntimeError("네이버 증권에서 KOSPI 데이터를 가져오지 못했습니다.")

    html = INDEX_HTML.read_text(encoding="utf-8")
    latest_date = rows[0]["date"]
    oldest_date = rows[-1]["date"]

    # 1) RAW_DATA 배열 교체
    js_array = "const RAW_DATA = " + json.dumps(rows, ensure_ascii=False, indent=2) + ";"
    new_html, n1 = re.subn(
        r"const RAW_DATA = \[[\s\S]*?\];",
        js_array,
        html,
        count=1,
    )
    if n1 != 1:
        raise RuntimeError("index.html에서 RAW_DATA 블록을 찾지 못했습니다.")

    # 2) 헤더 기간 문구 및 KPI 기준일 교체
    new_html = re.sub(
        r"출처: 네이버 증권 \([^)]+\)",
        f"출처: 네이버 증권 ({oldest_date} ~ {latest_date} · 총 {len(rows)}거래일)",
        new_html,
    )
    new_html = re.sub(
        r"최신 종가 \([0-9-]+\)",
        f"최신 종가 ({latest_date})",
        new_html,
    )
    new_html = re.sub(
        r"kospi_30d_[0-9]+\.csv",
        f"kospi_30d_{latest_date.replace('-', '')}.csv",
        new_html,
    )

    INDEX_HTML.write_text(new_html, encoding="utf-8")
    print(f"Updated {INDEX_HTML.name}: {oldest_date} ~ {latest_date} (latest close: {rows[0]['close']})")


if __name__ == "__main__":
    update_html(fetch_kospi_30d())
