"""차트 패턴 유사도 매칭.

오늘의 N일 패턴과 가장 비슷했던 과거 N일 구간 top-K + "그 다음" 구간(후속 K일)을 반환.
유사도: z-score 정규화한 log-return 의 Pearson 상관.

자문 가드: 응답에 면책 문구 포함. 호출 측 UI 도 "과거 관찰일 뿐 미래 예측 X" 노출 필수.
"""
import datetime
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

DEFAULT_WINDOW = 60                # 매칭에 쓸 구간 길이 (영업일)
DEFAULT_FOLLOWUP = 30              # 매칭 직후 후속 구간 길이
DEFAULT_TOP_K = 3                  # 반환할 top-K 매칭 수
EXCLUDE_RECENT_DAYS = 90           # today 와 겹치는 자기-매칭 차단 (오늘 ± 90일)
DIVERSIFY_GAP_DAYS = 90            # top-K 사이 최소 간격 — 같은 시기 클러스터 차단


def _is_kr_ticker(ticker: str) -> bool:
    """6자리 숫자만 있으면 KR ETF (api.routers.chart 와 동일 규칙)."""
    return ticker.isdigit() and len(ticker) == 6


def _fetch_close(ticker: str) -> pd.Series:
    """KR (pykrx → yfinance(.KS) 폴백) / US (yfinance) 종가 시계열. 7년 이상."""
    if _is_kr_ticker(ticker):
        try:
            from pykrx import stock
            today = datetime.date.today().strftime('%Y%m%d')
            start = (datetime.date.today() - datetime.timedelta(days=365 * 7)).strftime('%Y%m%d')
            df = stock.get_market_ohlcv(start, today, ticker)
            if df is not None and not df.empty and '종가' in df.columns:
                series = df['종가'].astype(float)
                series.index = pd.to_datetime(series.index)
                series.name = 'Close'
                return series
        except Exception as e:
            print(f'[similarity KR] {ticker} pykrx 실패: {e}')
        try:
            df = yf.download(f'{ticker}.KS', period='7y', interval='1d',
                             auto_adjust=True, progress=False)
            if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
                df.columns = df.columns.get_level_values(0)
            if not df.empty and 'Close' in df.columns:
                return df['Close'].astype(float)
        except Exception as e:
            print(f'[similarity KR] {ticker} yfinance 실패: {e}')
        return pd.Series(dtype=float)

    # US — 10년치 (매칭 후보 풍부하게)
    try:
        df = yf.download(ticker, period='10y', interval='1d',
                         auto_adjust=True, progress=False)
        if df.empty:
            return pd.Series(dtype=float)
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)
        return df['Close'].astype(float)
    except Exception as e:
        print(f'[similarity US] {ticker} 실패: {e}')
        return pd.Series(dtype=float)


def _zscore_log_returns(close_window: pd.Series) -> np.ndarray:
    """log-return → z-score 정규화 array. 길이 = window-1.

    절대 가격에 무관한 "모양" 매칭이 목적.
    표준편차 0 (가격 변동 없음) 인 경우 mean centering 만.
    """
    ret = np.log(close_window / close_window.shift(1)).dropna().values
    if len(ret) == 0:
        return ret
    mu = ret.mean()
    sd = ret.std()
    if sd < 1e-9:
        return ret - mu
    return (ret - mu) / sd


def find_similar_patterns(
    ticker: str,
    window: int = DEFAULT_WINDOW,
    followup: int = DEFAULT_FOLLOWUP,
    top_k: int = DEFAULT_TOP_K,
) -> dict:
    """오늘의 window 일 패턴과 가장 비슷한 과거 top_k 구간 + 후속 followup 일 반환.

    Returns:
        {
          'ticker', 'window_days', 'followup_days',
          'today_window': {'start_date', 'end_date', 'data': [{date, close}, ...]},
          'matches': [{'rank', 'similarity', 'match_start', 'match_end',
                       'followup_end', 'data': [{date, close, is_followup}, ...]}],
          'disclaimer': '...',
        }
        실패 시 'error' 필드 포함.
    """
    close = _fetch_close(ticker)
    # NaN 제거 — yfinance/pykrx 가 휴장일이나 데이터 결손 시 NaN 을 끼워넣을 수 있고
    # 그러면 today_zret 와 candidate zret 의 길이가 어긋나 모든 후보가 length-mismatch
    # 로 skip 되어 matches 가 0건이 되는 케이스를 방어한다.
    close = close.dropna()
    n_close = len(close)
    needed = window + followup + EXCLUDE_RECENT_DAYS + 50  # 여유
    if close.empty or n_close < needed:
        return {
            'ticker': ticker, 'window_days': window, 'followup_days': followup,
            'today_window': None, 'matches': [],
            'error': f'insufficient history (have {n_close}, need {needed})',
            'debug': {'n_close': n_close, 'needed': needed},
        }

    # 오늘 패턴: 마지막 window 일
    today_close = close.iloc[-window:]
    today_zret = _zscore_log_returns(today_close)
    if len(today_zret) == 0:
        return {'ticker': ticker, 'matches': [], 'error': 'no returns',
                'debug': {'n_close': n_close, 'today_zret_len': 0}}

    # 후보 슬라이드: end_idx 가 [window-1, n - EXCLUDE_RECENT_DAYS - 1] 범위
    n = len(close)
    cutoff_end = n - EXCLUDE_RECENT_DAYS
    candidates = []
    n_skipped_len = 0
    n_skipped_nan = 0
    for end_idx in range(window - 1, cutoff_end):
        start_idx = end_idx - window + 1
        c_window = close.iloc[start_idx:end_idx + 1]
        if len(c_window) != window:
            n_skipped_len += 1
            continue
        c_zret = _zscore_log_returns(c_window)
        if len(c_zret) != len(today_zret):
            n_skipped_len += 1
            continue
        with np.errstate(invalid='ignore'):
            corr = float(np.corrcoef(today_zret, c_zret)[0, 1])
        if not np.isfinite(corr):
            n_skipped_nan += 1
            continue
        candidates.append({'end_idx': end_idx, 'similarity': corr})

    # 정렬 + 다양화 (top-K 사이 최소 DIVERSIFY_GAP_DAYS 간격)
    candidates.sort(key=lambda x: x['similarity'], reverse=True)
    selected = []
    for c in candidates:
        if any(abs(c['end_idx'] - s['end_idx']) < DIVERSIFY_GAP_DAYS for s in selected):
            continue
        selected.append(c)
        if len(selected) >= top_k:
            break

    # 응답 빌드
    today_data = [
        {'date': str(idx.date()), 'close': round(float(val), 4)}
        for idx, val in today_close.items()
    ]
    today_window = {
        'start_date': str(today_close.index[0].date()),
        'end_date': str(today_close.index[-1].date()),
        'data': today_data,
    }

    matches = []
    for rank, sel in enumerate(selected, 1):
        end_idx = sel['end_idx']
        start_idx = end_idx - window + 1
        followup_end_idx = min(end_idx + followup, n - 1)
        m_window = close.iloc[start_idx:followup_end_idx + 1]
        match_len = end_idx - start_idx + 1   # = window
        data = []
        for i, (idx, val) in enumerate(m_window.items()):
            data.append({
                'date': str(idx.date()),
                'close': round(float(val), 4),
                'is_followup': i >= match_len,
            })
        matches.append({
            'rank': rank,
            'similarity': round(sel['similarity'], 4),
            'match_start': str(close.index[start_idx].date()),
            'match_end': str(close.index[end_idx].date()),
            'followup_end': str(close.index[followup_end_idx].date()),
            'data': data,
        })

    return {
        'ticker': ticker,
        'window_days': window,
        'followup_days': followup,
        'today_window': today_window,
        'matches': matches,
        'disclaimer': '과거 관찰 사실일 뿐 미래 가격을 예측하지 않습니다.',
        'debug': {
            'n_close': n_close,
            'today_zret_len': len(today_zret),
            'cutoff_end': cutoff_end,
            'n_candidates': len(candidates),
            'n_skipped_len': n_skipped_len,
            'n_skipped_nan': n_skipped_nan,
            'n_selected': len(matches),
        },
    }
