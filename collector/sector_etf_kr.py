"""한국 섹터 ETF 가격·PER/PBR 수집기 (KODEX·TIGER 10종).

미국 SPDR 13개와 1:1 매핑은 어려워 안정적인 10개로 출발.
나머지(XLI/XLU/XLC) 는 한국 섹터 ETF 가 부족하거나 KOSPI200 흡수.
"""

from __future__ import annotations

import datetime as _dt
import pandas as pd


# ── 미국 SPDR ↔ 한국 KODEX/TIGER 매핑 ─────────────────────────────
# 한국 섹터 ETF 는 ticker = 6자리 종목코드 (문자열).
# kr_name 은 화면 표시용 한국어, en_name 은 LLM 입력용 영문.
SECTOR_ETF_KR = {
    '139260': {'kr_name': 'IT',          'en_name': 'Technology',     'us_proxy': 'XLK'},   # TIGER 200 IT
    '091160': {'kr_name': '반도체',       'en_name': 'Semiconductor',  'us_proxy': 'SOXX'},  # KODEX 반도체
    '300610': {'kr_name': '게임산업',     'en_name': 'Software/Game',  'us_proxy': 'IGV'},   # KODEX 게임산업
    '091170': {'kr_name': '은행',        'en_name': 'Financials',     'us_proxy': 'XLF'},   # KODEX 은행
    '139250': {'kr_name': '에너지화학',    'en_name': 'Energy/Chemical','us_proxy': 'XLE'},   # TIGER 200 에너지화학
    '266420': {'kr_name': '헬스케어',     'en_name': 'Healthcare',     'us_proxy': 'XLV'},   # KODEX 헬스케어
    '091180': {'kr_name': '자동차',       'en_name': 'Auto',           'us_proxy': 'XLY'},   # KODEX 자동차
    '117680': {'kr_name': '철강',        'en_name': 'Steel/Materials','us_proxy': 'XLB'},   # KODEX 철강
    '341850': {'kr_name': '리츠',        'en_name': 'REIT',           'us_proxy': 'XLRE'},  # TIGER 리츠부동산인프라
    '227560': {'kr_name': '필수소비재',    'en_name': 'Staples',        'us_proxy': 'XLP'},   # TIGER 200 생활소비재
}


def _etf_ohlcv_dual_source(ticker: str, days: int) -> pd.DataFrame:
    """ETF OHLCV — pykrx 우선, 실패 시 FDR 폴백 (한글 컬럼 통일)."""
    try:
        from pykrx import stock
        end = _dt.date.today().strftime('%Y%m%d')
        start = (_dt.date.today() - _dt.timedelta(days=days * 2)).strftime('%Y%m%d')
        df = stock.get_etf_ohlcv_by_date(start, end, ticker)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    # FDR 폴백
    try:
        import FinanceDataReader as fdr
        end = _dt.date.today()
        start = end - _dt.timedelta(days=days * 2)
        df = fdr.DataReader(ticker, start, end)
        if df is None or df.empty:
            return pd.DataFrame()
        return df.rename(columns={
            'Open': '시가', 'High': '고가', 'Low': '저가',
            'Close': '종가', 'Volume': '거래량',
        })
    except Exception as e:
        print(f"[SectorETF-KR] {ticker} FDR 폴백 실패: {e}")
        return pd.DataFrame()


def fetch_sector_etf_prices_kr(days: int = 252) -> dict[str, pd.DataFrame]:
    """10개 KODEX/TIGER 섹터 ETF 일별 OHLCV (pykrx → FDR 폴백)."""
    out = {}
    for ticker in SECTOR_ETF_KR.keys():
        df = _etf_ohlcv_dual_source(ticker, days)
        if df is not None and not df.empty:
            out[ticker] = df
    return out


def fetch_sector_etf_per_pbr_kr() -> list[dict]:
    """각 섹터 ETF 의 최신 PER/PBR/배당 — pykrx ETF fundamental 미지원.
    대신 ETF 의 NAV 기반 추정 또는 구성 종목 가중평균 (Stage 2 구현).

    임시: get_etf_portfolio_deposit_file 로 구성종목 받아서 종목별 PER 가중합.
    """
    return []  # Stage 2 구현
