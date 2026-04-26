"""sector_valuation 5년 historical backfill — yfinance only (FMP 의존 X).

[FMP backfill 이 free tier limit 으로 partial 실패 → yfinance 로 동일 로직 재구현]

전략:
1. yfinance Ticker(ETF).funds_data.top_holdings → top 10 종목 + 가중치
2. 각 holding stock 의 yfinance Ticker.income_stmt + balance_sheet → annual EPS, Equity, Shares
3. 각 fiscal year 별로:
       PE_stock = Close@year_end / Diluted_EPS
       PB_stock = Close@year_end / (Equity / Shares)
4. fiscal year (calendar year 기준) 끼리 묶어 가중평균 → ETF historical PE/PB
5. sector_valuation upsert (per ticker 5점 + 오늘 1점)

가정/한계:
- 5년간 holdings 변화 무시 (today's top10 weight 고정)
- top10 만 = ETF 자산의 ~50-70%
- annual 만 (yfinance income_stmt 기본 = 4년치 + 현재)

장점 vs FMP: 무료 + 모든 종목 (FMP free 가 차단한 NEE, JNJ, WELL 등 모두 받음).
"""
from collections import defaultdict
from datetime import date

import pandas as pd
import yfinance as yf

from collector.sector_valuation import SECTOR_VALUATION_ETFS
from database.repositories import upsert_sector_valuation


MIN_WEIGHT_COVERAGE = 0.40
HISTORY_YEARS = 5


def get_etf_holdings(etf_ticker: str) -> dict[str, float]:
    df = yf.Ticker(etf_ticker).funds_data.top_holdings
    weights = df["Holding Percent"].to_dict()
    total = sum(weights.values())
    return {sym: w / total for sym, w in weights.items()} if total > 0 else {}


def get_stock_annual_pepb(stock_ticker: str) -> dict[int, dict]:
    """yfinance 로 stock 의 fiscal year 별 PE / PB 계산.
    반환: {calendar_year: {'per': float, 'pbr': float, 'date': 'YYYY-MM-DD'}}
    """
    try:
        st = yf.Ticker(stock_ticker)
        income = st.income_stmt        # annual
        balance = st.balance_sheet     # annual
        # 충분히 긴 history 가져오기 (5년 + 여유)
        hist = st.history(period="6y", interval="1d", auto_adjust=False)
    except Exception as e:
        print(f"  [{stock_ticker}] yfinance 실패: {e}")
        return {}

    if income is None or income.empty or hist is None or hist.empty:
        return {}

    eps_row = income.loc["Diluted EPS"] if "Diluted EPS" in income.index else None
    if eps_row is None and "Basic EPS" in income.index:
        eps_row = income.loc["Basic EPS"]
    equity_row = balance.loc["Stockholders Equity"] if "Stockholders Equity" in balance.index else None
    shares_row = balance.loc["Ordinary Shares Number"] if "Ordinary Shares Number" in balance.index else None

    if eps_row is None:
        return {}

    out: dict[int, dict] = {}
    for fy_end_ts in eps_row.index:
        year = fy_end_ts.year
        eps = eps_row.get(fy_end_ts)
        if pd.isna(eps) or eps is None:
            continue

        # fiscal year end 직전/당일 ETF close
        target = pd.Timestamp(fy_end_ts).tz_localize(None) if fy_end_ts.tzinfo is None else pd.Timestamp(fy_end_ts).tz_convert(None).tz_localize(None)
        hist_naive = hist.copy()
        if hist_naive.index.tz is not None:
            hist_naive.index = hist_naive.index.tz_localize(None)
        # asof 사용 — target 이전 가장 최근 거래일
        try:
            close = hist_naive["Close"].asof(target)
        except Exception:
            close = None
        if pd.isna(close) or close is None:
            continue

        per = float(close) / float(eps) if eps > 0 else None

        bvps = None
        if equity_row is not None and shares_row is not None:
            equity = equity_row.get(fy_end_ts)
            shares = shares_row.get(fy_end_ts)
            if pd.notna(equity) and pd.notna(shares) and shares > 0:
                bvps = float(equity) / float(shares)
        pbr = float(close) / bvps if (bvps and bvps > 0) else None

        out[year] = {"per": per, "pbr": pbr, "date": target.strftime("%Y-%m-%d")}
    return out


def reconstruct_etf_history(etf_ticker: str, sector_name: str) -> list[dict]:
    holdings = get_etf_holdings(etf_ticker)
    if not holdings:
        return []

    by_year_per: dict[int, list[tuple[float, float]]] = defaultdict(list)
    by_year_pbr: dict[int, list[tuple[float, float]]] = defaultdict(list)
    year_to_date: dict[int, str] = {}

    for stock, weight in holdings.items():
        ratios = get_stock_annual_pepb(stock)
        for year, r in ratios.items():
            if r["per"] is not None and r["per"] > 0:
                by_year_per[year].append((weight, r["per"]))
            if r["pbr"] is not None and r["pbr"] > 0:
                by_year_pbr[year].append((weight, r["pbr"]))
            d = r["date"]
            if year not in year_to_date or d > year_to_date[year]:
                year_to_date[year] = d

    out = []
    today_year = date.today().year
    for year in sorted(set(by_year_per.keys()) | set(by_year_pbr.keys())):
        # 너무 오래된 것 제외 (HISTORY_YEARS+1 까지)
        if year < today_year - HISTORY_YEARS - 1:
            continue
        per_pairs = by_year_per.get(year, [])
        pbr_pairs = by_year_pbr.get(year, [])
        per_w = sum(w for w, _ in per_pairs)
        pbr_w = sum(w for w, _ in pbr_pairs)
        per_t = (sum(w * v for w, v in per_pairs) / per_w) if per_w >= MIN_WEIGHT_COVERAGE else None
        pbr_t = (sum(w * v for w, v in pbr_pairs) / pbr_w) if pbr_w >= MIN_WEIGHT_COVERAGE else None
        if per_t is None and pbr_t is None:
            continue
        out.append({
            "date": year_to_date[year],
            "ticker": etf_ticker,
            "sector_name": sector_name,
            "per": per_t,
            "pbr": pbr_t,
        })
    print(f"  [{etf_ticker}] {len(out)}점")
    return out


def backfill_all() -> int:
    total: list[dict] = []
    for etf, sector in SECTOR_VALUATION_ETFS.items():
        print(f"[{etf}] {sector}")
        total.extend(reconstruct_etf_history(etf, sector))
    if not total:
        return 0
    for i in range(0, len(total), 100):
        upsert_sector_valuation(total[i:i + 100])
    print(f"\n총 {len(total)} 행 upsert")
    return len(total)


if __name__ == "__main__":
    backfill_all()
