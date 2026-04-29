"""섹터 모멘텀 랭킹 — 11개 섹터 ETF 의 1주일·1개월 누적 수익률 + 1주일 기준 랭킹.

데이터 소스: index_price_raw 의 일별 종가 (이미 매일 수집됨, yfinance 호출 0회)
- 1주일 = 5 거래일 (월~금 한 주)
- 1개월 = 21 거래일 (월평균 거래일 수)
- 랭킹: 1주일 수익률 내림차순 (큰 게 1위) — 단기 모멘텀 추적용
"""
from __future__ import annotations

from datetime import date

from collector.sector_valuation import SECTOR_VALUATION_ETFS
from database.repositories import get_client


_TRADING_DAYS_1W = 5
_TRADING_DAYS_1M = 21


def _cum_return_days(prices: list[float], days: int) -> float | None:
    """일별 종가 기준 N 거래일 누적 수익률. 데이터 부족하면 None."""
    if len(prices) < days + 1:
        return None
    return prices[-1] / prices[-days - 1] - 1


def _rank_dict(d: dict[str, float], reverse: bool = True) -> dict[str, int]:
    """value 내림차순 (큰 게 1위) 으로 ticker → rank 매핑."""
    sorted_items = sorted(d.items(), key=lambda x: x[1], reverse=reverse)
    return {k: i + 1 for i, (k, _) in enumerate(sorted_items)}


def compute_sector_momentum() -> dict:
    """11개 섹터의 1W·1M 수익률 + 1W 기준 랭킹.

    반환:
      {
        as_of_date: str,
        momentum: [
          {ticker, sector_name, return_1w, return_1m, rank}, ...11
        ]
      }
    """
    client = get_client()
    rows: list[dict] = []
    PAGE = 1000
    offset = 0
    tickers = list(SECTOR_VALUATION_ETFS.keys())
    while True:
        resp = (
            client.table("index_price_raw")
            .select("date,ticker,close")
            .in_("ticker", tickers)
            .order("date", desc=False)
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        chunk = resp.data or []
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        offset += PAGE
    if not rows:
        return {"as_of_date": None, "momentum": []}

    # ticker → 일별 종가 시계열 (date ASC)
    by_ticker: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append((r["date"], r.get("close") or 0))

    # 일별 종가 list (date 정렬 — query 가 이미 ASC, 안전망으로 한 번 더)
    daily_close: dict[str, list[float]] = {
        t: [c for _, c in sorted(s)] for t, s in by_ticker.items()
    }

    # 1주일·1개월 누적 수익률
    returns_1w: dict[str, float] = {}
    returns_1m: dict[str, float] = {}
    for ticker, prices in daily_close.items():
        r1w = _cum_return_days(prices, _TRADING_DAYS_1W)
        r1m = _cum_return_days(prices, _TRADING_DAYS_1M)
        if r1w is not None:
            returns_1w[ticker] = r1w
        if r1m is not None:
            returns_1m[ticker] = r1m

    # 랭킹: 1주일 수익률 기준 (큰 게 1위)
    rank_by_1w = _rank_dict(returns_1w)

    out = []
    for ticker, sector_name in SECTOR_VALUATION_ETFS.items():
        out.append({
            "ticker": ticker,
            "sector_name": sector_name,
            "return_1w": round(returns_1w.get(ticker) * 100, 2) if ticker in returns_1w else None,
            "return_1m": round(returns_1m.get(ticker) * 100, 2) if ticker in returns_1m else None,
            "rank": rank_by_1w.get(ticker),
        })
    # 랭킹 오름차순 (1위부터 위로)
    out.sort(key=lambda x: x["rank"] if x["rank"] is not None else 999)

    return {
        "as_of_date": date.today().isoformat(),
        "momentum": out,
    }
