"""섹터 모멘텀 랭킹 — 11개 섹터 ETF 의 1M·3M·6M 누적 수익률 + 현재 phase 의 예상 순위 비교.

데이터 소스: index_price_raw 의 일별 종가 (이미 매일 수집됨, yfinance 호출 0회)
phase 별 예상 순위: sector_cycle_result.phase_holding_perf JSON 의 현재 phase 평균 수익률
"""
from __future__ import annotations

from datetime import date

from collector.sector_valuation import SECTOR_VALUATION_ETFS
from database.repositories import get_client, fetch_sector_cycle_latest


def _cum_return(prices: list[float], months: int) -> float | None:
    """월말 종가 기준 N개월 누적 수익률. 데이터 부족하면 None."""
    if len(prices) < months + 1:
        return None
    return prices[-1] / prices[-months - 1] - 1


def _rank_dict(d: dict[str, float], reverse: bool = True) -> dict[str, int]:
    """value 내림차순 (큰 게 1위) 으로 ticker → rank 매핑."""
    sorted_items = sorted(d.items(), key=lambda x: x[1], reverse=reverse)
    return {k: i + 1 for i, (k, _) in enumerate(sorted_items)}


def compute_sector_momentum() -> dict:
    """11개 섹터의 1M·3M·6M 수익률 + 현재 phase 예상 순위 vs 실제 순위.

    반환:
      {
        phase_name: str,
        as_of_date: str,
        momentum: [
          {ticker, sector_name, return_1m, return_3m, return_6m,
           current_rank, expected_rank, rank_diff}, ...11
        ]
      }
    """
    client = get_client()
    # 13개 섹터 ETF 일별 종가 — 최근 1년치. Supabase 기본 1000행 한계 회피 위해 페이지네이션.
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
        return {"phase_name": None, "as_of_date": None, "momentum": []}

    # ticker → 월말 종가 시계열 (date ASC)
    by_ticker: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append((r["date"], r.get("close") or 0))

    # 월말 추출 — 같은 YYYYMM 의 마지막 거래일만
    month_close: dict[str, list[float]] = {}
    for ticker, series in by_ticker.items():
        month_to_close: dict[str, float] = {}
        for d, c in series:
            month_to_close[d[:7]] = c  # YYYY-MM key, 마지막 행이 덮어쓰는 게 월말
        # 정렬된 월별 종가
        month_close[ticker] = [month_to_close[m] for m in sorted(month_to_close)]

    # 누적 수익률
    returns_1m: dict[str, float] = {}
    returns_3m: dict[str, float] = {}
    returns_6m: dict[str, float] = {}
    for ticker, prices in month_close.items():
        for n, dest in [(1, returns_1m), (3, returns_3m), (6, returns_6m)]:
            r = _cum_return(prices, n)
            if r is not None:
                dest[ticker] = r

    # 현재 순위 (3M 기준)
    current_rank = _rank_dict(returns_3m)

    # 예상 순위 — phase_holding_perf 의 현재 phase 섹터 평균 수익률 활용
    cycle = fetch_sector_cycle_latest()
    phase_name = cycle.get("phase_name") if cycle else None
    expected_rank: dict[str, int] = {}
    if cycle:
        # phase_sector_perf: {'회복': {'XLK': 1.23, ...}, ...} 형식 (sector_cycle.py 출력)
        ps = cycle.get("phase_sector_perf") or {}
        cur_phase_perf = ps.get(phase_name, {}) if phase_name else {}
        # SECTOR_VALUATION_ETFS 의 11 ticker 만 필터
        filt = {t: v for t, v in cur_phase_perf.items() if t in SECTOR_VALUATION_ETFS}
        if filt:
            expected_rank = _rank_dict(filt)

    out = []
    for ticker, sector_name in SECTOR_VALUATION_ETFS.items():
        cur = current_rank.get(ticker)
        exp = expected_rank.get(ticker)
        out.append({
            "ticker": ticker,
            "sector_name": sector_name,
            "return_1m": round(returns_1m.get(ticker) * 100, 2) if ticker in returns_1m else None,
            "return_3m": round(returns_3m.get(ticker) * 100, 2) if ticker in returns_3m else None,
            "return_6m": round(returns_6m.get(ticker) * 100, 2) if ticker in returns_6m else None,
            "current_rank": cur,
            "expected_rank": exp,
            # rank_diff 양수 = 예상보다 낮은 순위 (언더퍼폼) / 음수 = 오버퍼폼
            "rank_diff": (exp - cur) if (cur and exp) else None,
        })
    # 3M 수익률 기준 정렬
    out.sort(key=lambda x: x["return_3m"] if x["return_3m"] is not None else -999, reverse=True)

    return {
        "phase_name": phase_name,
        "as_of_date": date.today().isoformat(),
        "momentum": out,
    }
