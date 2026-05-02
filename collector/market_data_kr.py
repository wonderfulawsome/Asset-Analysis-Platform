"""한국 시장 거시·지수 데이터 수집기.

데이터 소스:
- pykrx: KRX 주가·시총·PER/PBR·VKOSPI·옵션 P/C
- ECOS: 한국 거시 (국고채 금리)
- FinanceDataReader: VKOSPI 폴백

미국 macro_raw 스키마(sp500_close, sp500_return, vix, tnx 등)에 KR 등가 데이터를
의미적으로 매핑해 region='kr' 행으로 적재.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# 기본 fetch 함수들
# ─────────────────────────────────────────────────────────────────────────────

def _fdr_fallback_index(symbol: str, days: int) -> pd.DataFrame:
    """FinanceDataReader → yfinance 2단계 폴백.

    FDR 의 KS11 등은 내부적으로 pykrx 호출하는 경우가 많아 KRX 장애 시 함께 실패.
    이때 yfinance ^KS11 등으로 한번 더 폴백.
    """
    end = _dt.date.today()
    start = end - _dt.timedelta(days=days * 2)
    # 1차: FDR
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(symbol, start, end)
        if df is not None and not df.empty:
            return df.rename(columns={
                'Open': '시가', 'High': '고가', 'Low': '저가',
                'Close': '종가', 'Volume': '거래량',
            })
    except Exception as e:
        print(f"[KR] FDR {symbol} 실패: {e}")
    # 2차: yfinance (지수에는 ^ 접두사)
    try:
        import yfinance as yf
        yf_symbol = '^' + symbol if not symbol.startswith('^') else symbol
        df = yf.download(yf_symbol, start=start, end=end, progress=False, auto_adjust=False)
        if df is None or df.empty:
            return pd.DataFrame()
        # MultiIndex 컬럼 평탄화 (yfinance 최근 버전)
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)
        return df.rename(columns={
            'Open': '시가', 'High': '고가', 'Low': '저가',
            'Close': '종가', 'Volume': '거래량',
        })
    except Exception as e:
        print(f"[KR] yfinance {symbol} 실패: {e}")
        return pd.DataFrame()


def fetch_kospi_price_history(days: int = 252) -> pd.DataFrame:
    """KOSPI 종가 시계열 (최근 N 영업일). pykrx 우선, 실패 시 FDR 폴백."""
    try:
        from pykrx import stock
        end = _dt.date.today().strftime('%Y%m%d')
        start = (_dt.date.today() - _dt.timedelta(days=days * 2)).strftime('%Y%m%d')
        df = stock.get_index_ohlcv(start, end, '1001')
        if df is not None and not df.empty:
            return df
    except Exception as e:
        print(f"[KR] pykrx KOSPI 실패 → FDR 폴백: {e}")
    return _fdr_fallback_index('KS11', days)


def fetch_kospi200_price_history(days: int = 252) -> pd.DataFrame:
    """KOSPI200 종가 시계열. pykrx 우선, 실패 시 FDR 폴백."""
    try:
        from pykrx import stock
        end = _dt.date.today().strftime('%Y%m%d')
        start = (_dt.date.today() - _dt.timedelta(days=days * 2)).strftime('%Y%m%d')
        df = stock.get_index_ohlcv(start, end, '1028')
        if df is not None and not df.empty:
            return df
    except Exception as e:
        print(f"[KR] pykrx KOSPI200 실패 → FDR 폴백: {e}")
    return _fdr_fallback_index('KS200', days)


def fetch_vkospi_history(days: int = 252) -> pd.DataFrame:
    """VKOSPI 시계열. 1차 FDR, 실패시 KOSPI 일간 수익률 20일 연율화 std × 100 proxy."""
    end = _dt.date.today()
    start = end - _dt.timedelta(days=days * 2)
    # 1차 FDR
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader('VKOSPI', start, end)
        if df is not None and not df.empty and 'Close' in df.columns:
            return df
    except Exception as e:
        print(f"[KR] VKOSPI FDR 실패 → KOSPI RV proxy: {e}")
    # 2차: KOSPI 20D realized vol × 100 (proxy)
    try:
        kospi = fetch_kospi_price_history(days=days * 2)
        if kospi is None or kospi.empty:
            return pd.DataFrame()
        close = kospi['종가']
        ret = close.pct_change()
        rv = (ret.rolling(20).std() * np.sqrt(252) * 100).dropna()
        return pd.DataFrame({'Close': rv})
    except Exception as e:
        print(f"[KR] VKOSPI proxy 실패: {e}")
        return pd.DataFrame()


def fetch_kospi_per_pbr(days: int = 252) -> pd.DataFrame:
    """KOSPI 일별 PER/PBR/배당수익률 (시총 가중 평균). pykrx 만 지원 — 실패 시 빈 DF."""
    try:
        from pykrx import stock
        end = _dt.date.today().strftime('%Y%m%d')
        start = (_dt.date.today() - _dt.timedelta(days=days * 2)).strftime('%Y%m%d')
        df = stock.get_index_fundamental(start, end, '1001')
        if df is not None and not df.empty:
            return df
    except Exception as e:
        print(f"[KR] pykrx PER 실패 (FDR 폴백 없음): {e}")
    return pd.DataFrame()


# KR 국채 fallback 상수 — Yahoo 'KR10YT=RR' 가 더 이상 작동 안 할 때 사용 (2026 기준).
# 정확한 시계열이 필요하면 ECOS API (collector/ecos_macro) 의 시장금리 통계표 통합 권장.
_KR_10Y_FALLBACK = 0.035  # 3.5% (2026 평균 근사)
_KR_3Y_FALLBACK = 0.030   # 3.0%


def _fdr_close(symbol: str, days: int) -> pd.Series:
    """FDR 'Close' 컬럼만 반환 (없으면 빈 Series)."""
    try:
        import FinanceDataReader as fdr
        end = _dt.date.today()
        start = end - _dt.timedelta(days=days * 2)
        df = fdr.DataReader(symbol, start, end)
        if df is not None and not df.empty and 'Close' in df.columns:
            return df['Close']
    except Exception as e:
        print(f"[KR] FDR {symbol} 실패: {e}")
    return pd.Series(dtype=float)


def fetch_kr_10y_treasury(days: int = 252) -> pd.Series:
    """한국 10년 국고채 yield (%). FDR 'KR10YT=RR' 시도, 실패시 fallback 상수 시리즈."""
    s = _fdr_close('KR10YT=RR', days)
    if not s.empty:
        return s
    # fallback: KOSPI close 인덱스 기준으로 평탄한 fallback 시리즈
    try:
        kospi = fetch_kospi_price_history(days=days * 2)
        if kospi is None or kospi.empty:
            return pd.Series(dtype=float)
        return pd.Series(_KR_10Y_FALLBACK * 100, index=kospi.index)  # % 단위 (3.5)
    except Exception:
        return pd.Series(dtype=float)


def fetch_kr_3y_treasury(days: int = 252) -> pd.Series:
    """한국 3년 국고채 (yield_spread 계산용). FDR 실패시 fallback 상수."""
    s = _fdr_close('KR3YT=RR', days)
    if not s.empty:
        return s
    try:
        kospi = fetch_kospi_price_history(days=days * 2)
        if kospi is None or kospi.empty:
            return pd.Series(dtype=float)
        return pd.Series(_KR_3Y_FALLBACK * 100, index=kospi.index)
    except Exception:
        return pd.Series(dtype=float)


# ─────────────────────────────────────────────────────────────────────────────
# 외국인·기관 수급 (한국 합성 F&G 컴포넌트)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_foreign_institution_flow(days: int = 60) -> pd.DataFrame:
    """KOSPI 외국인·기관 일별 순매수액."""
    from pykrx import stock
    end = _dt.date.today().strftime('%Y%m%d')
    start = (_dt.date.today() - _dt.timedelta(days=days * 2)).strftime('%Y%m%d')
    return stock.get_market_trading_value_by_date(start, end, 'KOSPI')


# ─────────────────────────────────────────────────────────────────────────────
# 일별 KR 매크로 record — macro_raw 스키마에 매핑
# ─────────────────────────────────────────────────────────────────────────────

def _rsi(prices: pd.Series, period: int = 14) -> Optional[float]:
    """RSI(14) — 미국 _calc_rsi 와 동일 알고리즘."""
    if len(prices) < period + 1:
        return None
    delta = prices.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return None if pd.isna(val) else round(float(val), 1)


def compute_kr_macro_history(days: int = 30) -> list[dict]:
    """최근 N 영업일의 KR 매크로 record 리스트.

    macro_raw 스키마 매핑:
    - sp500_close  ← KOSPI close
    - sp500_return ← KOSPI 일간 수익률 (%)
    - sp500_vol20  ← KOSPI 20일 연율화 변동성 (std * sqrt(252))
    - sp500_rsi    ← KOSPI RSI(14)
    - vix          ← VKOSPI
    - tnx          ← KR 10Y KTB rate (%)
    - yield_spread ← (KR 10Y - KR 3Y) (%)
    - dxy_return   ← None (한국 시장에 직접 등가 없음)
    - putcall_ratio← None (Stage 3 — KRX 옵션 시장)
    """
    # 데이터 한 번에 fetch
    kospi = fetch_kospi_price_history(days=max(days * 2, 60))
    vkospi = fetch_vkospi_history(days=max(days * 2, 60))
    kr_10y = fetch_kr_10y_treasury(days=max(days * 2, 60))
    kr_3y = fetch_kr_3y_treasury(days=max(days * 2, 60))

    if kospi.empty:
        print('[KR-Macro] KOSPI 데이터 없음 — 빈 리스트 반환')
        return []

    # KOSPI 수익률·변동성 계산
    close = kospi['종가']                                        # 종가 컬럼
    daily_return = close.pct_change() * 100                     # 일간 수익률 %
    vol20 = close.pct_change().rolling(20).std() * np.sqrt(252) * 100  # 연율화 변동성 %

    # 최근 days 만큼 잘라 record 생성
    target_dates = close.index[-days:]
    records = []
    for d in target_dates:
        date_str = d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d)[:10]
        # 각 시리즈에서 해당 날짜 또는 가장 가까운 이전 거래일 값 조회
        kospi_close = float(close.loc[d])
        ret = daily_return.loc[d] if d in daily_return.index else None
        vol = vol20.loc[d] if d in vol20.index else None
        # VKOSPI / KR 금리는 다른 인덱스라 forward-fill 식으로 매칭
        vkospi_val = _value_at_or_before(vkospi['Close'] if 'Close' in vkospi.columns else None, d)
        kr10y_val = _value_at_or_before(kr_10y, d)
        kr3y_val = _value_at_or_before(kr_3y, d)
        # RSI — 해당 날짜 이전까지 데이터로
        rsi_val = _rsi(close.loc[:d])

        records.append({
            'date': date_str,
            'sp500_close': round(kospi_close, 2),
            'sp500_return': round(float(ret), 4) if ret is not None and not pd.isna(ret) else None,
            'sp500_vol20': round(float(vol), 4) if vol is not None and not pd.isna(vol) else None,
            'sp500_rsi': rsi_val,
            'vix': round(float(vkospi_val), 2) if vkospi_val is not None else None,
            'tnx': round(float(kr10y_val), 4) if kr10y_val is not None else None,
            'yield_spread': (round(float(kr10y_val - kr3y_val), 4)
                             if (kr10y_val is not None and kr3y_val is not None) else None),
            'dxy_return': None,
        })
    return records


def _value_at_or_before(series, target_date):
    """series 의 target_date 또는 가장 가까운 이전 값 반환 (없으면 None)."""
    if series is None or len(series) == 0:
        return None
    try:
        sub = series.loc[:target_date]
        if len(sub) == 0:
            return None
        val = sub.iloc[-1]
        return None if pd.isna(val) else float(val)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# KOSPI ETF 가격 (index_price_raw 적재용)
# ─────────────────────────────────────────────────────────────────────────────

KR_INDEX_TICKERS = {
    '069500': 'KODEX 200',          # KOSPI200 ETF
    '102110': 'TIGER 200',           # KOSPI200 ETF
    '232080': 'TIGER 코스닥150',
    '229200': 'KODEX 코스닥150',
    '226490': 'KODEX KOSPI',         # 코스피 전체
}


def _etf_ohlcv_fallback(ticker: str, days: int = 10) -> pd.DataFrame:
    """ETF OHLCV pykrx → FDR → yfinance(.KS suffix) 3-단 폴백."""
    end = _dt.date.today()
    start_str = (end - _dt.timedelta(days=days)).strftime('%Y%m%d')
    end_str = end.strftime('%Y%m%d')
    start = end - _dt.timedelta(days=days)
    # 1차 pykrx
    try:
        from pykrx import stock
        df = stock.get_etf_ohlcv_by_date(start_str, end_str, ticker)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    # 2차 FDR
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(ticker, start, end)
        if df is not None and not df.empty:
            return df.rename(columns={
                'Open': '시가', 'High': '고가', 'Low': '저가',
                'Close': '종가', 'Volume': '거래량',
            })
    except Exception:
        pass
    # 3차 yfinance (한국 ETF: 6자리코드.KS 형식)
    try:
        import yfinance as yf
        yf_symbol = f'{ticker}.KS'
        df = yf.download(yf_symbol, start=start, end=end, progress=False, auto_adjust=False)
        if df is None or df.empty:
            return pd.DataFrame()
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)
        return df.rename(columns={
            'Open': '시가', 'High': '고가', 'Low': '저가',
            'Close': '종가', 'Volume': '거래량',
        })
    except Exception as e:
        print(f"[KR] ETF {ticker} 모든 폴백 실패: {e}")
        return pd.DataFrame()


def fetch_kr_index_prices_today() -> list[dict]:
    """오늘(또는 직전 거래일) KR 주요 ETF 가격 + 등락률 — index_price_raw 형식.

    NOTE: index_price_raw 스키마는 (date, ticker, close, change_pct) 만 보유.
    'name'/'volume' 은 컬럼 없으므로 record 에 포함 안 함 (한국어 이름은 frontend 매핑).
    """
    out = []
    for ticker in KR_INDEX_TICKERS.keys():
        df = _etf_ohlcv_fallback(ticker, days=10)
        if df is None or df.empty or len(df) < 2:
            continue
        try:
            last = df.iloc[-1]
            prev = df.iloc[-2]
            close = float(last['종가'])
            change_pct = round((close - float(prev['종가'])) / float(prev['종가']) * 100, 2)
            out.append({
                'date': df.index[-1].strftime('%Y-%m-%d'),
                'ticker': ticker,
                'close': close,
                'change_pct': change_pct,
            })
        except Exception as e:
            print(f"[KR-Index] {ticker} 처리 실패: {e}")
    return out
