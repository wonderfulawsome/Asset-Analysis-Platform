"""US 섹터 ETF — 종목별 trailingPE 가중평균 PER 산출 (yfinance).

KR 의 sector_etf_kr.fetch_sector_etf_per_pbr_kr 등가 — DART 대신 yfinance 사용.
미국 종목은 yfinance .info['trailingPE'] 가 잘 동작 (KR 과 다른 점).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import yfinance as yf

from collector.etf_holdings_us import fetch_etf_holdings_us, US_SECTOR_ETFS


def _fetch_per_for_codes(codes: list[str]) -> dict[str, float]:
    """다수 종목의 yfinance trailingPE — 일괄 fetch.

    Returns: {stock_code: per (>0, <=100)}.
    """
    out = {}
    for sc in codes:
        try:
            info = yf.Ticker(sc).info
            per = info.get('trailingPE') or info.get('forwardPE')
            if per is None:
                continue
            per = float(per)
            if per <= 0 or per > 100:
                continue
            out[sc] = per
        except Exception:
            continue
    return out


def _weighted_avg(holdings: list[dict], stock_per: dict[str, float]) -> tuple[Optional[float], float]:
    """비중 가중평균 — 적자/부재 종목 제외 후 정규화. (val, coverage_ratio)."""
    if not holdings:
        return None, 0.0
    total_w = sum(h.get('weight', 0) for h in holdings)
    if total_w <= 0:
        return None, 0.0
    valid_sum = 0.0
    valid_w = 0.0
    for h in holdings:
        sc = h.get('stock_code')
        w = h.get('weight', 0)
        if w <= 0 or sc not in stock_per:
            continue
        valid_sum += w * stock_per[sc]
        valid_w += w
    if valid_w <= 0:
        return None, 0.0
    return valid_sum / valid_w, valid_w / total_w


def fetch_sector_etf_per_us(today: date | None = None) -> list[dict]:
    """13 SPDR ETF 별 trailingPE 가중평균.

    Returns: [{date, ticker, per_weighted, coverage}, ...]
    coverage<0.3 면 per_weighted=None (적재 안 함 권장).
    """
    today = today or date.today()
    today_str = today.isoformat()

    # 1) holdings 캐시
    bundle = fetch_etf_holdings_us()

    # 2) holdings union 의 unique 종목 list
    codes = set()
    for etf in US_SECTOR_ETFS:
        h = bundle.get(etf, [])
        if isinstance(h, list):
            for it in h:
                sc = it.get('stock_code')
                if sc:
                    codes.add(sc)
    codes = sorted(codes)
    print(f'[sector_per_us] {len(codes)} unique 종목 trailingPE fetch...')
    stock_per = _fetch_per_for_codes(codes)
    print(f'[sector_per_us] PER 산출: {len(stock_per)}/{len(codes)} 종목')

    # 3) ETF 별 가중평균
    out = []
    for etf in US_SECTOR_ETFS:
        h = bundle.get(etf, [])
        if not isinstance(h, list):
            continue
        per, cov = _weighted_avg(h, stock_per)
        if cov < 0.3 or per is None:
            print(f'[sector_per_us] {etf} coverage {cov*100:.0f}% < 30% — per_weighted=None')
            per = None
        out.append({
            'date': today_str,
            'ticker': etf,
            'per_weighted': round(per, 2) if per is not None else None,
        })
    return out
