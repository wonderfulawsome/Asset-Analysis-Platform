"""US 섹터 ETF (SPDR 13종) 보유 종목·비중 — yfinance funds_data 캐싱.

KR 의 etf_holdings_kr.py 등가 — yfinance Ticker.funds_data.top_holdings 활용.
주 1회 갱신 (TTL 7일).

캐시: models/etf_holdings_us.json
형식: {ticker: [{'stock_code': 'AAPL', 'weight': 7.5}, ...], updated_at: iso}
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

import yfinance as yf


_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'models',
    'etf_holdings_us.json',
)
_TTL_DAYS = 7

# SPDR 13개 sector ETF (collector/sector_etf.py 와 일치 — 화면 노출되는 set)
US_SECTOR_ETFS = [
    'XLK',  'XLF',  'XLE',  'XLV',  'XLY',  'XLI',  'XLB',
    'XLU',  'XLRE', 'XLC',  'XLP',  'SOXX', 'IGV',
]


def _load_cache() -> Optional[dict]:
    try:
        if not os.path.exists(_CACHE_PATH):
            return None
        with open(_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(data: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'[etf_holdings_us] 캐시 저장 실패: {e}')


def _is_fresh(cache: dict) -> bool:
    try:
        holdings = [v for k, v in cache.items()
                    if k not in ('updated_at',) and isinstance(v, list)]
        if holdings and all(len(v) == 0 for v in holdings):
            return False
        updated = datetime.fromisoformat(cache.get('updated_at', '2000-01-01'))
        return (datetime.now() - updated).days < _TTL_DAYS
    except Exception:
        return False


def _fetch_holdings_for_ticker(etf_ticker: str) -> list[dict]:
    """yfinance funds_data.top_holdings — top N 보유종목 + 비중.

    Returns: [{'stock_code': 'AAPL', 'weight': 7.5}, ...] 또는 [].
    yfinance funds_data 가 ETF 별로 다른 필드 구조 — DataFrame 또는 dict.
    """
    try:
        ticker = yf.Ticker(etf_ticker)
        funds = ticker.funds_data
        if funds is None:
            return []
        top = funds.top_holdings
        if top is None or (hasattr(top, 'empty') and top.empty):
            return []
        # DataFrame 형태 — index=종목코드, column='Holding Percent' 또는 비중
        holdings = []
        if hasattr(top, 'iterrows'):
            for code, row in top.iterrows():
                # 비중 컬럼 자동 탐색
                weight = None
                for col in ('Holding Percent', 'holdingPercent', 'Weight', 'weight'):
                    if col in row.index:
                        try:
                            v = float(row[col])
                            # 0~1 ratio 면 100 곱
                            weight = v * 100 if v <= 1.0 else v
                            break
                        except (TypeError, ValueError):
                            continue
                if weight is None:
                    continue
                if weight > 0:
                    holdings.append({'stock_code': str(code), 'weight': round(weight, 4)})
        return holdings
    except Exception as e:
        print(f'[etf_holdings_us] {etf_ticker} fetch 실패: {e}')
        return []


def fetch_etf_holdings_us(force_refresh: bool = False) -> dict:
    """13 US 섹터 ETF holdings — TTL 7일 캐시.

    Returns: {ticker: [{'stock_code': str, 'weight': float}, ...], updated_at: iso}
    """
    if not force_refresh:
        cached = _load_cache()
        if cached and _is_fresh(cached):
            print(f'[etf_holdings_us] 캐시 hit ({cached.get("updated_at", "?")[:10]})')
            return cached

    holdings_by_ticker = {}
    for etf in US_SECTOR_ETFS:
        h = _fetch_holdings_for_ticker(etf)
        holdings_by_ticker[etf] = h
        if h:
            print(f'[etf_holdings_us] {etf}: {len(h)} 종목, '
                  f'sum_weight={sum(x["weight"] for x in h):.1f}')
        else:
            print(f'[etf_holdings_us] {etf}: 빈 holdings')

    bundle = {
        **holdings_by_ticker,
        'updated_at': datetime.now().isoformat(),
    }
    _save_cache(bundle)
    return bundle


def get_holdings_for_etf(etf_ticker: str) -> list[dict]:
    cache = fetch_etf_holdings_us()
    h = cache.get(etf_ticker)
    return h if isinstance(h, list) else []
