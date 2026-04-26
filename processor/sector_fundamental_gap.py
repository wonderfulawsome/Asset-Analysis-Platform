"""각 섹터 ETF 의 fundamental_gap 시계열 산출.

fundamental_gap_t = log(P_t / P_{t-12}) - log(E_t / E_{t-12})
              = 12개월 가격 누적 수익률 − 12개월 EPS 누적 성장률
              ↑ 가격이 EPS 보다 더 빨리 성장 → 비싸짐 (양수)
              ↓ EPS 가 가격보다 더 빨리 성장 → 싸짐 (음수)

펀더멘털 탭 (broad market) 의 fundamental_gap 정의를 그대로 sector ETF 에 적용.
- P_t = ETF 의 월말 종가 (yfinance history, interval=1mo)
- E_t = top10 holdings 의 가중평균 annual EPS, fiscal year 단위로 forward-fill 한
        monthly TTM EPS proxy

저장: sector_valuation 테이블의 per 컬럼 재활용 (fundamental_gap 값을 per 에 저장).
      pbr 컬럼은 NULL (단일 metric 만 사용).
"""
from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf

from collector.sector_valuation import SECTOR_VALUATION_ETFS
from database.repositories import upsert_sector_valuation


HISTORY_YEARS = 6           # ETF 가격 시계열 길이 (12개월 lag 위해 5년 + 여유)
MIN_WEIGHT_COVER = 0.40     # fiscal year 가중치 최소 cover


def _strip_tz(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return idx.tz_localize(None) if idx.tz is not None else idx


def get_etf_holdings(etf_ticker: str) -> dict[str, float]:
    df = yf.Ticker(etf_ticker).funds_data.top_holdings
    weights = df["Holding Percent"].to_dict()
    total = sum(weights.values())
    return {sym: w / total for sym, w in weights.items()} if total > 0 else {}


def compute_weighted_annual_eps(holdings: dict[str, float]) -> dict[int, float]:
    """holdings 의 fiscal year 별 가중평균 EPS.

    반환: {calendar_year: weighted_avg_EPS}
    """
    by_year_pairs: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for stock, weight in holdings.items():
        try:
            income = yf.Ticker(stock).income_stmt
        except Exception as e:
            print(f"  {stock} income_stmt 실패: {e}")
            continue
        if income is None or "Diluted EPS" not in income.index:
            continue
        eps_row = income.loc["Diluted EPS"]
        for fy_end, eps in eps_row.items():
            if pd.isna(eps):
                continue
            by_year_pairs[fy_end.year].append((weight, float(eps)))

    out: dict[int, float] = {}
    for year, pairs in by_year_pairs.items():
        cover = sum(w for w, _ in pairs)
        if cover < MIN_WEIGHT_COVER:
            continue
        out[year] = sum(w * v for w, v in pairs) / cover
    return out


def compute_etf_fundamental_gap(etf_ticker: str) -> pd.Series:
    """한 ETF 의 monthly fundamental_gap 시계열."""
    holdings = get_etf_holdings(etf_ticker)
    if not holdings:
        return pd.Series(dtype=float)

    # ETF 월말 가격 시계열
    hist = yf.Ticker(etf_ticker).history(
        period=f"{HISTORY_YEARS}y", interval="1mo", auto_adjust=False
    )
    if hist is None or hist.empty:
        return pd.Series(dtype=float)
    prices = hist["Close"].dropna()
    prices.index = _strip_tz(prices.index)

    # 가중평균 annual EPS
    annual_eps = compute_weighted_annual_eps(holdings)
    if not annual_eps:
        return pd.Series(dtype=float)

    # monthly EPS forward-fill: 매 month_end 의 EPS 는 가장 최근 끝난 fiscal year 의 EPS
    years_sorted = sorted(annual_eps.keys())

    def eps_at(month_end: pd.Timestamp):
        # 전년도 EPS (fiscal year 가 작년에 끝났음을 가정)
        candidates = [y for y in years_sorted if y <= month_end.year - 1]
        if not candidates:
            return None
        return annual_eps.get(max(candidates))

    monthly_eps = pd.Series(
        [eps_at(d) for d in prices.index], index=prices.index, dtype=float
    )

    # fundamental_gap = log(P).diff(12) - log(E).diff(12)
    log_p = np.log(prices)
    log_e = np.log(monthly_eps.dropna()).reindex(log_p.index)
    fg = (log_p.diff(12) - log_e.diff(12)).dropna()
    return fg


def backfill_all() -> int:
    rows: list[dict] = []
    for etf, sector in SECTOR_VALUATION_ETFS.items():
        print(f"[{etf}] {sector}")
        try:
            fg = compute_etf_fundamental_gap(etf)
        except Exception as e:
            print(f"  실패: {e}")
            continue
        if fg.empty:
            print("  → 0점")
            continue
        for ts, v in fg.items():
            rows.append({
                "date": ts.date().isoformat(),
                "ticker": etf,
                "sector_name": sector,
                "per": float(v),   # fundamental_gap 을 per 컬럼에 저장 (스키마 재활용)
                "pbr": None,
            })
        print(f"  → {len(fg)}점 (latest={fg.index[-1].date()}, fg={fg.iloc[-1]:+.3f})")

    if not rows:
        return 0
    for i in range(0, len(rows), 200):
        upsert_sector_valuation(rows[i:i + 200])
    print(f"\n총 {len(rows)} 행 upsert (fundamental_gap)")
    return len(rows)


if __name__ == "__main__":
    backfill_all()
