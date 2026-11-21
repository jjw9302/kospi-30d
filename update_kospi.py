#!/usr/bin/env python3
"""
네이버 증권에서 코스피(KOSPI) 5년치 / 1년치 / 1주일치 데이터를 조회·비교·검증하고
data/kospi_5y.json, data/kospi_5y_stats.txt, data/verify_log.txt를 갱신합니다.

모드:
  --mode 10m     : 10분 1회 — 최근 1주일치(7거래일)만 비교·검증
  --mode weekly  : 주 1회   — 최근 1년치(365일)만 비교·검증
  --mode monthly : 월 1회   — 전체 5년치 비교·검증
  --mode full    : 최초 실행 — 전체 5년치 수집 및 검증
"""
import argparse
import ast
import datetime
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
JSON_PATH = DATA_DIR / "kospi_5y.json"
STATS_TXT_PATH = DATA_DIR / "kospi_5y_stats.txt"
VERIFY_LOG_PATH = DATA_DIR / "verify_log.txt"

KST = datetime.timezone(datetime.timedelta(hours=9))
HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_sise_range(start_yyyymmdd: str, end_yyyymmdd: str) -> list[dict]:
    url = (
        "https://api.finance.naver.com/siseJson.naver"
        f"?symbol=KOSPI&requestType=1&startTime={start_yyyymmdd}&endTime={end_yyyymmdd}&timeframe=day"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="replace").strip()
    parsed = ast.literal_eval(raw)
    rows = []
    for item in parsed[1:]:
        if not item or len(item) < 6:
            continue
        ds = str(item[0]).strip()
        if len(ds) != 8 or not ds.isdigit():
            continue
        iso = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
        rows.append({
            "date": iso,
            "open": round(float(item[1]), 2),
            "high": round(float(item[2]), 2),
            "low": round(float(item[3]), 2),
            "close": round(float(item[4]), 2),
            "volume": int(float(item[5])),
        })
    return rows


def fetch_recent_mobile(count: int = 10) -> list[dict]:
    url = f"https://m.stock.naver.com/api/index/KOSPI/price?pageSize={count}&page=1"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rows = []
    for r in data:
        rows.append({
            "date": r["localTradedAt"],
            "open": round(float(str(r["openPrice"]).replace(",", "")), 2),
            "high": round(float(str(r["highPrice"]).replace(",", "")), 2),
            "low": round(float(str(r["lowPrice"]).replace(",", "")), 2),
            "close": round(float(str(r["closePrice"]).replace(",", "")), 2),
            "volume": 0,
        })
    return rows


def recompute_changes(rows_by_date: dict[str, dict]) -> list[dict]:
    # Sort ascending to compute daily change & ratio accurately
    asc = [rows_by_date[d] for d in sorted(rows_by_date.keys())]
    prev_close = None
    for row in asc:
        if prev_close and prev_close > 0:
            chg = round(row["close"] - prev_close, 2)
            ratio = round((chg / prev_close) * 100.0, 2)
        else:
            chg = 0.0
            ratio = 0.0
        row["change"] = chg
        row["ratio"] = ratio
        prev_close = row["close"]
    # Keep newest-first for storage
    return list(reversed(asc))


def compute_weekly_bars(asc_rows: list[dict]) -> list[dict]:
    weeks: dict[tuple[int, int], list[dict]] = {}
    for r in asc_rows:
        dt = datetime.date.fromisoformat(r["date"])
        iso = dt.isocalendar()
        key = (iso[0], iso[1])
        weeks.setdefault(key, []).append(r)
    out = []
    for key in sorted(weeks.keys()):
        grp = weeks[key]
        out.append({
            "date": grp[-1]["date"],
            "open": grp[0]["open"],
            "high": max(x["high"] for x in grp),
            "low": min(x["low"] for x in grp),
            "close": grp[-1]["close"],
        })
    return out


def sma(values: list[float], period: int) -> list[float | None]:
    res: list[float | None] = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= period:
            s -= values[i - period]
        if i >= period - 1:
            res.append(round(s / period, 2))
        else:
            res.append(None)
    return res


def build_stats_txt(rows_desc: list[dict], mode: str, diff_count: int, checked_count: int, now_kst: str) -> str:
    asc = list(reversed(rows_desc))
    latest = rows_desc[0]
    oldest = rows_desc[-1]

    high_row = max(rows_desc, key=lambda r: r["high"])
    low_row = min(rows_desc, key=lambda r: r["low"])
    avg_close = sum(r["close"] for r in rows_desc) / len(rows_desc)
    total_diff = latest["close"] - oldest["close"]
    total_pct = (total_diff / oldest["close"]) * 100.0
    up_days = sum(1 for r in rows_desc if r["change"] > 0)
    down_days = sum(1 for r in rows_desc if r["change"] < 0)

    # Yearly breakdown
    by_year: dict[str, list[dict]] = {}
    for r in asc:
        by_year.setdefault(r["date"][:4], []).append(r)

    # Daily MA
    d_closes = [r["close"] for r in asc]
    d_ma5 = sma(d_closes, 5)[-1]
    d_ma20 = sma(d_closes, 20)[-1]
    d_ma60 = sma(d_closes, 60)[-1]
    d_ma120 = sma(d_closes, 120)[-1]

    # Weekly MA5 / MA20 / MA60 / MA120 & crossovers
    weekly = compute_weekly_bars(asc)
    w_closes = [w["close"] for w in weekly]
    w_ma5 = sma(w_closes, 5)
    w_ma20 = sma(w_closes, 20)
    w_ma60 = sma(w_closes, 60)
    w_ma120 = sma(w_closes, 120)

    crosses = []
    for i in range(1, len(weekly)):
        if None in (w_ma5[i - 1], w_ma20[i - 1], w_ma5[i], w_ma20[i]):
            continue
        prev_d = w_ma5[i - 1] - w_ma20[i - 1]
        curr_d = w_ma5[i] - w_ma20[i]
        if prev_d <= 0 < curr_d:
            crosses.append((weekly[i]["date"], "골든크로스 (주5 ↑ 주20)", weekly[i]["close"]))
        elif prev_d >= 0 > curr_d:
            crosses.append((weekly[i]["date"], "데드크로스 (주5 ↓ 주20)", weekly[i]["close"]))

    fmt_ma = lambda v: f"{v:,.2f}" if v is not None else "-"
    lines = [
        "============================================================",
        "  KOSPI 최근 5년 통계 요약 (출처: 네이버 증권)",
        "============================================================",
        f"최종 갱신 시각 (KST) : {now_kst}",
        f"최근 검증 모드       : {mode} (비교 {checked_count}거래일 / 변동 {diff_count}건)",
        f"데이터 기간          : {oldest['date']} ~ {latest['date']} (총 {len(rows_desc):,}거래일)",
        "",
        "[1. 핵심 요약]",
        f"  - 최신 종가 ({latest['date']}) : {latest['close']:,.2f} ({latest['change']:+,.2f} / {latest['ratio']:+.2f}%)",
        f"  - 5년 최고가 (장중)         : {high_row['high']:,.2f} ({high_row['date']}, 종가 {high_row['close']:,.2f})",
        f"  - 5년 최저가 (장중)         : {low_row['low']:,.2f} ({low_row['date']}, 종가 {low_row['close']:,.2f})",
        f"  - 5년 평균 종가             : {avg_close:,.2f}",
        f"  - 5년 누적 변동             : {total_diff:+,.2f} ({total_pct:+.2f}%)",
        f"  - 상승일 / 하락일           : {up_days:,}일 / {down_days:,}일 (승률 {up_days / len(rows_desc) * 100:.1f}%)",
        "",
        "[2. 이동평균선 현황]",
        f"  - 일봉 MA5 / MA20 / MA60 / MA120 : {fmt_ma(d_ma5)} / {fmt_ma(d_ma20)} / {fmt_ma(d_ma60)} / {fmt_ma(d_ma120)}",
        f"  - 주봉 주5 / 주20 / 주60 / 주120 : {fmt_ma(w_ma5[-1])} / {fmt_ma(w_ma20[-1])} / {fmt_ma(w_ma60[-1])} / {fmt_ma(w_ma120[-1])} ({'정배열(주5>주20)' if w_ma5[-1] >= w_ma20[-1] else '역배열(주5<주20)'})",
        "",
        "[3. 주5 · 주20 이평선 교차 이력 (최근 6건)]",
    ]
    for dt, label, cl in crosses[-6:][::-1]:
        lines.append(f"  - {dt} | {label} | 주간종가 {cl:,.2f}")

    lines.append("")
    lines.append("[4. 연도별 통계]")
    lines.append(f"  {'연도':<6} {'거래일':>6} {'시작종가':>10} {'마지막종가':>10} {'연간수익률':>10} {'연중최고':>10} {'연중최저':>10}")
    for yr in sorted(by_year.keys()):
        grp = by_year[yr]
        y_start = grp[0]["close"]
        y_end = grp[-1]["close"]
        y_ret = (y_end - y_start) / y_start * 100.0
        y_hi = max(x["high"] for x in grp)
        y_lo = min(x["low"] for x in grp)
        lines.append(
            f"  {yr:<6} {len(grp):>6} {y_start:>10,.2f} {y_end:>10,.2f} {y_ret:>+9.2f}% {y_hi:>10,.2f} {y_lo:>10,.2f}"
        )

    lines.append("============================================================")
    return "\n".join(lines) + "\n"


def run(mode: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(KST)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S KST")
    today_str = now.strftime("%Y%m%d")

    existing_by_date: dict[str, dict] = {}
    if JSON_PATH.exists():
        loaded = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        for r in loaded.get("rows", []):
            existing_by_date[r["date"]] = r

    # If no existing data, force full 5-year bootstrap
    effective_mode = mode
    if not existing_by_date:
        effective_mode = "full"

    if effective_mode in ("full", "monthly"):
        start_dt = (now - datetime.timedelta(days=365 * 5 + 5)).strftime("%Y%m%d")
        fetched = fetch_sise_range(start_dt, today_str)
        # Also merge latest mobile quote to reflect intraday/latest close immediately
        for m in fetch_recent_mobile(5):
            fetched.append(m)
    elif effective_mode == "weekly":
        start_dt = (now - datetime.timedelta(days=366)).strftime("%Y%m%d")
        fetched = fetch_sise_range(start_dt, today_str)
        for m in fetch_recent_mobile(5):
            fetched.append(m)
    elif effective_mode == "10m":
        # 1 week (~7 trading days) check via Naver mobile price API
        fetched = fetch_recent_mobile(7)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    # Deduplicate fetched by date (later entries overwrite earlier)
    fetched_map: dict[str, dict] = {}
    for r in fetched:
        if r["date"] in fetched_map and r.get("volume", 0) == 0:
            r["volume"] = fetched_map[r["date"]].get("volume", 0)
        fetched_map[r["date"]] = r

    # Compare & verify differences
    diff_count = 0
    for d, nr in fetched_map.items():
        old = existing_by_date.get(d)
        if old is None:
            diff_count += 1
            existing_by_date[d] = nr
        else:
            changed = any(
                old.get(k) != nr.get(k)
                for k in ("open", "high", "low", "close")
            )
            if changed:
                diff_count += 1
                if nr.get("volume", 0) == 0 and old.get("volume", 0) > 0:
                    nr["volume"] = old["volume"]
                existing_by_date[d] = nr

    # Trim anything older than 5 years + 5 days
    cutoff = (now - datetime.timedelta(days=365 * 5 + 5)).strftime("%Y-%m-%d")
    trimmed = {d: r for d, r in existing_by_date.items() if d >= cutoff}

    rows_desc = recompute_changes(trimmed)

    payload = {
        "meta": {
            "symbol": "KOSPI",
            "source": "네이버 증권 (stock.naver.com/domestic/index/KOSPI/price)",
            "updatedAt": now_str,
            "lastMode": effective_mode,
            "checkedCount": len(fetched_map),
            "diffCount": diff_count,
            "count": len(rows_desc),
            "startDate": rows_desc[-1]["date"],
            "endDate": rows_desc[0]["date"],
        },
        "rows": rows_desc,
    }

    if effective_mode == "10m" and diff_count == 0 and JSON_PATH.exists() and STATS_TXT_PATH.exists():
        print(f"[{now_str}] mode=10m     checked={len(fetched_map):<4} diff=0    (no changes, skipping file rewrite)")
        return

    # Write JSON & TXT stats if changed or scheduled weekly/monthly/full audit
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    stats_txt = build_stats_txt(rows_desc, effective_mode, diff_count, len(fetched_map), now_str)
    STATS_TXT_PATH.write_text(stats_txt, encoding="utf-8")

    # Append verification log (keep last 50 lines)
    log_line = f"[{now_str}] mode={effective_mode:<7} checked={len(fetched_map):<4} diff={diff_count:<4} total={len(rows_desc)} latest={rows_desc[0]['date']}({rows_desc[0]['close']:,.2f})"
    prev_logs = VERIFY_LOG_PATH.read_text(encoding="utf-8").splitlines() if VERIFY_LOG_PATH.exists() else []
    prev_logs.insert(0, log_line)
    VERIFY_LOG_PATH.write_text("\n".join(prev_logs[:50]) + "\n", encoding="utf-8")

    print(log_line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KOSPI 5년/30일 데이터 수집 및 검증 스크립트")
    parser.add_argument(
        "--mode",
        choices=["10m", "weekly", "monthly", "full"],
        default="full",
        help="검증 범위: 10m(1주일), weekly(1년), monthly/full(전체 5년)",
    )
    args = parser.parse_args()
    run(args.mode)
