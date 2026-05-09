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
DIRECTION_NEUTRAL_TOL = 0.02       # 윈도 누적 수익률 |x| < 2% 면 중립 — 방향 필터 통과


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


def _cumulative_log_returns(close_window: pd.Series) -> np.ndarray:
    """log(close_t / close_0) — 시작점 0 기준 누적 로그수익률 path.

    이전엔 z-score 정규화 log-return 의 Pearson 상관을 썼는데, 그러면 *변동 패턴*
    만 보고 *추세 방향* 은 무시되어 강세장 today 가 약세장 candidate 와도
    높은 상관이 나오는 문제 발생 (사용자 보고 2026-05-09).
    누적 path 를 비교하면 path 모양 자체가 매칭되어 추세 방향이 자연 보존됨.
    Pearson 자체가 mean·scale invariant 이므로 절대 가격은 여전히 무관.
    """
    if len(close_window) < 2:
        return np.array([])
    log_close = np.log(close_window.values.astype(float))
    return log_close - log_close[0]


def _total_log_return(close_window: pd.Series) -> float:
    """윈도 시작 → 끝 누적 로그수익률. 방향 필터 sign 판정용."""
    if len(close_window) < 2:
        return 0.0
    try:
        return float(np.log(close_window.iloc[-1] / close_window.iloc[0]))
    except Exception:
        return 0.0


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

    # 오늘 패턴: 마지막 window 일 — 누적 path + 총 로그수익률
    today_close = close.iloc[-window:]
    today_path = _cumulative_log_returns(today_close)
    today_total = _total_log_return(today_close)
    if len(today_path) == 0:
        return {'ticker': ticker, 'matches': [], 'error': 'no returns',
                'debug': {'n_close': n_close, 'today_path_len': 0}}

    # 후보 슬라이드 + 방향 필터: today 가 강세(>+2%)면 강세 후보만, 약세(<-2%)면 약세만.
    # 중립(|total| ≤ 2%) 일 땐 sign 무시.
    n = len(close)
    cutoff_end = n - EXCLUDE_RECENT_DAYS
    today_dir = 0
    if today_total > DIRECTION_NEUTRAL_TOL:
        today_dir = 1
    elif today_total < -DIRECTION_NEUTRAL_TOL:
        today_dir = -1

    candidates = []
    n_skipped_len = 0
    n_skipped_nan = 0
    n_skipped_dir = 0
    for end_idx in range(window - 1, cutoff_end):
        start_idx = end_idx - window + 1
        c_window = close.iloc[start_idx:end_idx + 1]
        if len(c_window) != window:
            n_skipped_len += 1
            continue
        c_path = _cumulative_log_returns(c_window)
        if len(c_path) != len(today_path):
            n_skipped_len += 1
            continue
        # 방향 필터: today 가 명확한 방향이면 같은 방향 후보만 통과.
        # 후보가 중립이면 통과 (today 와 같은 정적 구간이면 매치 가능).
        if today_dir != 0:
            c_total = _total_log_return(c_window)
            c_dir = 0
            if c_total > DIRECTION_NEUTRAL_TOL:
                c_dir = 1
            elif c_total < -DIRECTION_NEUTRAL_TOL:
                c_dir = -1
            if c_dir != 0 and c_dir != today_dir:
                n_skipped_dir += 1
                continue
        with np.errstate(invalid='ignore'):
            corr = float(np.corrcoef(today_path, c_path)[0, 1])
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
            'today_path_len': len(today_path),
            'today_total_logret': round(today_total, 4),
            'today_dir': today_dir,
            'cutoff_end': cutoff_end,
            'n_candidates': len(candidates),
            'n_skipped_len': n_skipped_len,
            'n_skipped_dir': n_skipped_dir,
            'n_skipped_nan': n_skipped_nan,
            'n_selected': len(matches),
        },
    }


# ── 강도 매칭 (6개월 누적 수익률 기준 + 후속 6개월 분포) ────────────────────
# 사용자 의도: 비슷한 강도의 상승/하락이 과거에 있었을 때 그 *다음* 어떻게
# 됐는지 *경험적 분포* 로 가늠. 패턴 모양 매칭과 다른 차원 — 강도(누적 수익률)
# 가 비슷한 시점들의 후속 6개월 분포를 통계로 보여줌.
# 자문 가드: "버블/매수/매도/예측" 단어 0. "유사 강도 N건 · 후속 분포" 사실 진술만.

DEFAULT_MAGNITUDE_WINDOW = 126     # 6개월 ≈ 영업일 126
DEFAULT_MAGNITUDE_FOLLOWUP = 126   # 후속 6개월
DEFAULT_MAGNITUDE_TOP_K = 5
DEFAULT_MAGNITUDE_DRAWDOWN_PCT = 0.10   # 후속 -10% 이상 하락 카운트 임계


def find_magnitude_matches(
    ticker: str,
    window: int = DEFAULT_MAGNITUDE_WINDOW,
    followup: int = DEFAULT_MAGNITUDE_FOLLOWUP,
    top_k: int = DEFAULT_MAGNITUDE_TOP_K,
) -> dict:
    """today 의 window-day 누적 수익률과 *비슷한 크기* 였던 과거 시점 top-K +
    각 시점의 후속 followup-day 분포 통계.

    매칭 기준:
      - 같은 방향 (강세 today 면 강세 candidate, 약세면 약세) — 양쪽 모두 NEUTRAL_TOL
        이내 정적이면 sign 무시.
      - |today_total - c_total| 절대값 작은 순. (path 모양 무관, magnitude 만 본다)
      - DIVERSIFY_GAP_DAYS 로 top-K 사이 최소 간격 보장.

    Returns:
        {
          'ticker', 'mode': 'magnitude', 'window_days', 'followup_days',
          'today_window': {start, end, total_pct, data},
          'matches': [{rank, match_total_pct, post_total_pct, post_max_dd_pct,
                       match_start, match_end, followup_end, data: [{date, close, is_followup}]}],
          'summary': {n_matches, post_mean_pct, post_median_pct, post_min_pct,
                      post_max_pct, n_drawdown_10pct},
          'disclaimer': '...',
          'debug': {...},
        }
    """
    close = _fetch_close(ticker)
    close = close.dropna()
    n_close = len(close)
    needed = window + followup + EXCLUDE_RECENT_DAYS + 50
    if close.empty or n_close < needed:
        return {
            'ticker': ticker, 'mode': 'magnitude',
            'window_days': window, 'followup_days': followup,
            'today_window': None, 'matches': [], 'summary': None,
            'error': f'insufficient history (have {n_close}, need {needed})',
            'debug': {'n_close': n_close, 'needed': needed},
        }

    today_close = close.iloc[-window:]
    today_total = _total_log_return(today_close)
    today_total_pct = float((np.exp(today_total) - 1) * 100)
    today_dir = 0
    if today_total > DIRECTION_NEUTRAL_TOL:
        today_dir = 1
    elif today_total < -DIRECTION_NEUTRAL_TOL:
        today_dir = -1

    # 후보 슬라이드: end_idx 가 [window-1, n - EXCLUDE_RECENT_DAYS - followup - 1]
    # followup 만큼은 미래 데이터가 있어야 후속 분포 계산 가능.
    n = n_close
    cutoff_end = n - EXCLUDE_RECENT_DAYS - followup
    candidates = []
    n_skipped_len = 0
    n_skipped_dir = 0
    for end_idx in range(window - 1, cutoff_end):
        start_idx = end_idx - window + 1
        c_window = close.iloc[start_idx:end_idx + 1]
        if len(c_window) != window:
            n_skipped_len += 1
            continue
        c_total = _total_log_return(c_window)
        if today_dir != 0:
            c_dir = 0
            if c_total > DIRECTION_NEUTRAL_TOL:
                c_dir = 1
            elif c_total < -DIRECTION_NEUTRAL_TOL:
                c_dir = -1
            if c_dir != 0 and c_dir != today_dir:
                n_skipped_dir += 1
                continue
        diff = abs(today_total - c_total)
        candidates.append({'end_idx': end_idx, 'c_total': c_total, 'diff': diff})

    # |diff| 작은 순 + 다양화
    candidates.sort(key=lambda x: x['diff'])
    selected = []
    for c in candidates:
        if any(abs(c['end_idx'] - s['end_idx']) < DIVERSIFY_GAP_DAYS for s in selected):
            continue
        selected.append(c)
        if len(selected) >= top_k:
            break

    today_data = [
        {'date': str(idx.date()), 'close': round(float(val), 4)}
        for idx, val in today_close.items()
    ]
    today_window_obj = {
        'start_date': str(today_close.index[0].date()),
        'end_date': str(today_close.index[-1].date()),
        'total_pct': round(today_total_pct, 2),
        'data': today_data,
    }

    matches = []
    post_logrets = []
    for rank, sel in enumerate(selected, 1):
        end_idx = sel['end_idx']
        start_idx = end_idx - window + 1
        followup_end_idx = min(end_idx + followup, n - 1)
        m_window = close.iloc[start_idx:followup_end_idx + 1]
        match_len = end_idx - start_idx + 1   # = window

        match_total_pct = float((np.exp(sel['c_total']) - 1) * 100)
        # 후속: end_idx (=윈도 끝, 매칭 마지막 close) → followup_end_idx
        post_close = close.iloc[end_idx:followup_end_idx + 1]
        post_logret = _total_log_return(post_close)
        post_logrets.append(post_logret)
        post_total_pct = float((np.exp(post_logret) - 1) * 100)
        # 후속 최대 낙폭 (peak-to-trough within followup window)
        post_max_dd_pct = 0.0
        if len(post_close) >= 2:
            running_max = post_close.cummax()
            dd_series = (post_close / running_max - 1) * 100
            post_max_dd_pct = float(dd_series.min())

        data = []
        for i, (idx, val) in enumerate(m_window.items()):
            data.append({
                'date': str(idx.date()),
                'close': round(float(val), 4),
                'is_followup': i >= match_len,
            })
        matches.append({
            'rank': rank,
            'match_total_pct': round(match_total_pct, 2),
            'post_total_pct': round(post_total_pct, 2),
            'post_max_dd_pct': round(post_max_dd_pct, 2),
            'match_start': str(close.index[start_idx].date()),
            'match_end': str(close.index[end_idx].date()),
            'followup_end': str(close.index[followup_end_idx].date()),
            'data': data,
        })

    # 후속 분포 요약
    summary = None
    if post_logrets:
        post_pcts = [(np.exp(x) - 1) * 100 for x in post_logrets]
        summary = {
            'n_matches': len(post_pcts),
            'post_mean_pct': round(float(np.mean(post_pcts)), 2),
            'post_median_pct': round(float(np.median(post_pcts)), 2),
            'post_min_pct': round(float(np.min(post_pcts)), 2),
            'post_max_pct': round(float(np.max(post_pcts)), 2),
            'n_drawdown_10pct': sum(1 for m in matches
                                    if m['post_max_dd_pct'] <= -DEFAULT_MAGNITUDE_DRAWDOWN_PCT * 100),
        }

    return {
        'ticker': ticker,
        'mode': 'magnitude',
        'window_days': window,
        'followup_days': followup,
        'today_window': today_window_obj,
        'matches': matches,
        'summary': summary,
        'disclaimer': '과거 관찰 사실의 분포일 뿐 미래 가격을 예측하지 않습니다.',
        'debug': {
            'n_close': n_close,
            'today_total_pct': round(today_total_pct, 4),
            'today_dir': today_dir,
            'cutoff_end': cutoff_end,
            'n_candidates': len(candidates),
            'n_skipped_len': n_skipped_len,
            'n_skipped_dir': n_skipped_dir,
            'n_selected': len(matches),
        },
    }
