"""시장 이상 탐지 (Anomaly Detection) API.

신호 탭 교체용 endpoint. anomaly_daily 테이블에서 read-only 조회만 — 계산은
스케줄러가 매일 1회 수행 (compute_today_anomaly).

자문 리스크 차단을 위해 응답은 모두 descriptive 필드 (D², percentile, contributors,
유사 과거 시점). "예측", "위험", "권장" 류 단어 미포함.
"""
from datetime import date as _date, timedelta
from functools import lru_cache
from fastapi import APIRouter, Query
from database.repositories import fetch_anomaly_current, fetch_anomaly_history

router = APIRouter()

REGIME_TICKERS = {'us': '^GSPC', 'kr': '^KS11'}
REGIME_50_WINDOW = 50  # 차트 배경 강세장/하락장 음영 — 종가 vs 50영업일 SMA


@lru_cache(maxsize=4)
def _regime_50_dict(region: str, day_key: str) -> dict:
    """{'YYYY-MM-DD': 1(bull) | 0(bear) | None} — region 별 50d SMA 라벨.

    day_key 는 캐시 키용 (date.today().isoformat()) — 일자 바뀌면 캐시 자동 갱신.
    yfinance 실패 시 빈 dict (frontend 는 음영 미표시 fallback).
    """
    try:
        import yfinance as yf
        import pandas as pd
        import numpy as np
        ticker = REGIME_TICKERS.get(region, '^GSPC')
        start = (_date.today() - timedelta(days=int(365.25 * 12))).isoformat()
        df = yf.download(ticker, start=start, progress=False, auto_adjust=False)
        if df.empty:
            return {}
        close = df['Close']
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        sma = close.rolling(REGIME_50_WINDOW).mean()
        regime = (close > sma).astype(float).where(sma.notna())
        if regime.index.tz is not None:
            regime.index = regime.index.tz_localize(None)
        regime_ff = regime.ffill()  # 휴장일 갭 — 직전 라벨 유지
        return {idx.strftime('%Y-%m-%d'): (None if pd.isna(v) else int(v))
                for idx, v in regime_ff.items()}
    except Exception:
        return {}


def _norm_region(region: str) -> str:
    return region if region in ('us', 'kr') else 'us'


@router.get('/current')
def get_current(region: str = Query('us')):
    """오늘의 이상도 단일 row.

    응답: {date, d2, percentile_10y, percentile_90d, feature_vector,
           top_contributors[], knn_dates[], n_history, region}
    빈 결과면 {empty: True} 반환.
    """
    region = _norm_region(region)
    row = fetch_anomaly_current(region=region)
    if not row:
        return {'empty': True, 'region': region}
    return {**row, 'region': region}


@router.get('/history')
def get_history(days: int = Query(2520, ge=30, le=4000), region: str = Query('us')):
    """이상도 D² 시계열 (차트용). default 2520 ≈ 10년 거래일.

    응답: {region, days_requested, count, series: [{date, d2, percentile_10y, percentile_90d}, ...]}
    """
    region = _norm_region(region)
    rows = fetch_anomaly_history(days=days, region=region)
    regime_dict = _regime_50_dict(region, _date.today().isoformat())
    series = [
        {
            'date': r['date'],
            'd2': r.get('d2'),
            'percentile_10y': r.get('percentile_10y'),
            'percentile_90d': r.get('percentile_90d'),
            'regime_50': regime_dict.get(str(r['date'])[:10]),
        }
        for r in rows
    ]
    return {
        'region': region,
        'days_requested': days,
        'count': len(series),
        'series': series,
    }
