"""sector_valuation 5년 historical backfill — yfinance holdings + FMP stock ratios.

전략:
1. yfinance Ticker(ETF).funds_data.top_holdings → top 10 종목 + 가중치 (현재 시점)
2. FMP /stable/ratios → 각 holding 의 5년 annual priceToEarningsRatio / priceToBookRatio
3. 같은 fiscalYear 끼리 묶어 가중평균 → ETF 의 implied PER/PBR 시계열
4. sector_valuation 테이블에 (date, ticker, per, pbr) upsert

가정/한계:
- 5년간 holdings 변화 무시 (today's top10 weight 를 모든 과거 시점에 적용)
- top10 만 = ETF 자산의 ~50-70% — 나머지 30-50% 미반영
- FMP 무료 tier 는 annual 만 (분기별 premium) → 시점 5점
- 회사별 fiscalYear 차이 (Apple Sep, NVDA Jan, 일반 Dec) 가 있는데 단순히 fiscalYear 문자열로 그룹핑 → 작은 노이즈

호출 횟수: 12 ETF × 10 holdings = 120 FMP calls (250/day 무료 tier 안에서 안전).
"""
import os
import time
from collections import defaultdict

import requests
import yfinance as yf
from dotenv import load_dotenv

from collector.sector_valuation import SECTOR_VALUATION_ETFS
from database.repositories import upsert_sector_valuation


load_dotenv()
FMP_KEY = os.getenv("FMP_API_KEY")
FMP_RATIOS_URL = "https://financialmodelingprep.com/stable/ratios"

MIN_WEIGHT_COVERAGE = 0.40   # 한 fiscalYear 에서 weight cover 40% 미만이면 그 점 skip
TOP_N_HOLDINGS_LIMIT = 10    # yfinance funds_data.top_holdings 가 기본 10개
HISTORY_YEARS = 5


def fetch_fmp_ratios(stock_ticker: str, limit: int = HISTORY_YEARS) -> list[dict]:
    """FMP /stable/ratios → annual PE/PB historical."""
    if not FMP_KEY:
        raise RuntimeError("FMP_API_KEY 가 .env 에 없음")
    r = requests.get(
        FMP_RATIOS_URL,
        params={"symbol": stock_ticker, "limit": limit, "apikey": FMP_KEY},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("Error Message"):
        raise RuntimeError(f"FMP error: {data['Error Message']}")
    return data if isinstance(data, list) else []


def get_etf_holdings(etf_ticker: str) -> dict[str, float]:
    """ETF top10 holdings 의 normalized weight 반환 ({symbol: weight}).
    합이 1 미만이면 normalize 해서 sum=1 로 만듦."""
    df = yf.Ticker(etf_ticker).funds_data.top_holdings
    weights = df["Holding Percent"].to_dict()
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {sym: w / total for sym, w in weights.items()}


def reconstruct_etf_history(etf_ticker: str, sector_name: str) -> list[dict]:
    """ETF 의 historical PER/PBR 시계열 (가중평균)."""
    holdings = get_etf_holdings(etf_ticker)
    if not holdings:
        print(f"  [{etf_ticker}] holdings 없음 — skip")
        return []

    # fiscalYear → list of (weight, value)
    by_year_per: dict[str, list[tuple[float, float]]] = defaultdict(list)
    by_year_pbr: dict[str, list[tuple[float, float]]] = defaultdict(list)
    # fiscalYear → date 매핑 (가장 늦은 회사의 fiscal year end 사용)
    year_to_date: dict[str, str] = {}

    for stock, weight in holdings.items():
        try:
            rows = fetch_fmp_ratios(stock, limit=HISTORY_YEARS)
        except Exception as e:
            print(f"  [{etf_ticker}/{stock}] FMP 실패: {e}")
            continue
        time.sleep(0.15)  # rate-limit polite

        for row in rows:
            year = str(row.get("fiscalYear") or "")
            row_date = row.get("date")  # "YYYY-MM-DD"
            per = row.get("priceToEarningsRatio")
            pbr = row.get("priceToBookRatio")
            if not year:
                continue
            if per is not None and per > 0:
                by_year_per[year].append((weight, float(per)))
            if pbr is not None and pbr > 0:
                by_year_pbr[year].append((weight, float(pbr)))
            # date 는 그 fiscalYear 에 등록된 가장 늦은 날짜로 (12월 결산 우선)
            if row_date and (year not in year_to_date or row_date > year_to_date[year]):
                year_to_date[year] = row_date

    out = []
    for year in sorted(set(by_year_per.keys()) | set(by_year_pbr.keys())):
        per_pairs = by_year_per.get(year, [])
        pbr_pairs = by_year_pbr.get(year, [])
        per_w = sum(w for w, _ in per_pairs)
        pbr_w = sum(w for w, _ in pbr_pairs)
        per_t = (sum(w * v for w, v in per_pairs) / per_w) if per_w >= MIN_WEIGHT_COVERAGE else None
        pbr_t = (sum(w * v for w, v in pbr_pairs) / pbr_w) if pbr_w >= MIN_WEIGHT_COVERAGE else None
        if per_t is None and pbr_t is None:
            continue
        d = year_to_date.get(year, f"{year}-12-31")
        out.append({
            "date": d,
            "ticker": etf_ticker,
            "sector_name": sector_name,
            "per": per_t,
            "pbr": pbr_t,
        })
    print(f"  [{etf_ticker}] {len(out)}점 수집")
    return out


def backfill_all() -> int:
    total: list[dict] = []
    for etf, sector in SECTOR_VALUATION_ETFS.items():
        print(f"[{etf}] {sector}")
        total.extend(reconstruct_etf_history(etf, sector))

    if not total:
        print("upsert 대상 없음")
        return 0
    for i in range(0, len(total), 100):
        upsert_sector_valuation(total[i:i + 100])
    print(f"\n총 {len(total)} 행 upsert 완료")
    return len(total)


if __name__ == "__main__":
    backfill_all()
