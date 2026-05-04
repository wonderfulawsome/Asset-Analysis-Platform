"""KR 섹터 ETF 보유 종목·비중 — pykrx PDF (Portfolio Deposit File) 캐싱.

목적: fetch_sector_etf_per_pbr_kr 가 ETF 별 가중평균 PER/PBR 산출 시 사용.
주 1회 갱신 (TTL 7일) — KRX API 부하 최소화 + ETF 재구성 빈도 (분기 1회) 대비 충분.

캐시 파일: models/etf_holdings_kr.json
형식: {ticker: [{'stock_code': '005930', 'weight': 28.5}, ...], 'updated_at': iso, ...}
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Optional

# 캐시 파일 경로 — repo root 기준
_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'models',
    'etf_holdings_kr.json',
)
_TTL_DAYS = 7


def _load_cache() -> Optional[dict]:
    """캐시 JSON 로드. 없거나 손상이면 None."""
    try:
        if not os.path.exists(_CACHE_PATH):
            return None
        with open(_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(data: dict) -> None:
    """캐시 JSON 저장."""
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'[etf_holdings_kr] 캐시 저장 실패: {e}')


def _is_fresh(cache: dict) -> bool:
    """캐시가 TTL 7일 이내면 True."""
    try:
        updated = datetime.fromisoformat(cache.get('updated_at', '2000-01-01'))
        return (datetime.now() - updated).days < _TTL_DAYS
    except Exception:
        return False


def _fetch_pdf_for_ticker(etf_ticker: str, ref_date: str) -> list[dict]:
    """pykrx 의 ETF PDF (Portfolio Deposit File) 1개 ticker 조회.

    Returns: [{'stock_code': '005930', 'weight': 28.5}, ...] 또는 [] (실패 시).
    """
    try:
        from pykrx import stock
        df = stock.get_etf_portfolio_deposit_file(ref_date, etf_ticker)
        if df is None or df.empty:
            return []
        # pykrx 컬럼: 보통 '계약수' 또는 '비중' 등 — 'CU당 구성종목수' 와 stock code index
        # 비중 산출: 각 종목 시가총액 = (close × cu_count) → ETF 전체 시총 대비 비율
        # 다행히 pykrx 새 버전은 '비중' 컬럼 직접 제공 — fallback 으로 시총 추정
        if '비중' in df.columns:
            holdings = []
            for code, w in df['비중'].items():
                try:
                    weight = float(w)
                    if weight > 0:
                        holdings.append({'stock_code': str(code), 'weight': round(weight, 4)})
                except (TypeError, ValueError):
                    continue
            return holdings
        # fallback: cu_count × close → 시총 추정 → 비중
        if '계약수' in df.columns and '종가' in df.columns:
            total_value = (df['계약수'].astype(float) * df['종가'].astype(float)).sum()
            if total_value <= 0:
                return []
            holdings = []
            for code, row in df.iterrows():
                try:
                    cu = float(row['계약수'])
                    close = float(row['종가'])
                    if cu > 0 and close > 0:
                        weight = (cu * close) / total_value * 100
                        holdings.append({'stock_code': str(code), 'weight': round(weight, 4)})
                except (TypeError, ValueError):
                    continue
            return holdings
        print(f'[etf_holdings_kr] {etf_ticker}: 알 수 없는 PDF 컬럼 — {list(df.columns)}')
        return []
    except Exception as e:
        print(f'[etf_holdings_kr] {etf_ticker} PDF fetch 실패: {e}')
        return []


def fetch_etf_holdings_kr(force_refresh: bool = False) -> dict:
    """10 KR 섹터 ETF holdings — TTL 7일 캐시.

    Returns:
        {ticker: [{'stock_code': '005930', 'weight': 28.5}, ...], 'updated_at': iso}
        실패 ticker 는 빈 list — 호출측이 fallback 결정.
    """
    if not force_refresh:
        cached = _load_cache()
        if cached and _is_fresh(cached):
            print(f'[etf_holdings_kr] 캐시 hit ({cached.get("updated_at", "?")[:10]})')
            return cached

    from collector.sector_etf_kr import SECTOR_ETF_KR

    ref_date = date.today().strftime('%Y%m%d')
    holdings_by_ticker = {}
    for etf_ticker in SECTOR_ETF_KR.keys():
        h = _fetch_pdf_for_ticker(etf_ticker, ref_date)
        holdings_by_ticker[etf_ticker] = h
        if h:
            print(f'[etf_holdings_kr] {etf_ticker}: {len(h)} 종목, sum_weight={sum(x["weight"] for x in h):.1f}')
        else:
            print(f'[etf_holdings_kr] {etf_ticker}: 빈 holdings (PDF 실패)')

    bundle = {
        **holdings_by_ticker,
        'updated_at': datetime.now().isoformat(),
        'ref_date': ref_date,
    }
    _save_cache(bundle)
    return bundle


def get_holdings_for_etf(etf_ticker: str) -> list[dict]:
    """헬퍼 — 특정 ETF holdings 반환. 캐시 자동 사용."""
    cache = fetch_etf_holdings_kr()
    h = cache.get(etf_ticker)
    return h if isinstance(h, list) else []
