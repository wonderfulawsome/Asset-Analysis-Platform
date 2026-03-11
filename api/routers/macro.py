import threading
from datetime import datetime, time as dtime
from fastapi import APIRouter
import pandas as pd
import pytz
import yfinance as yf
from database.repositories import fetch_macro_latest2, fetch_fear_greed_latest2

router = APIRouter()

# 미국 동부시간 타임존
_ET = pytz.timezone('US/Eastern')
# 장 시작/종료 시각 (ET)
_MARKET_OPEN = dtime(9, 30)
_MARKET_CLOSE = dtime(16, 0)

# 캐시: (값, 만료시각)
_vol_cache: dict = {'value': None, 'expires': 0}
_vol_lock = threading.Lock()
_CACHE_SEC = 300  # 5분 캐시


def _realtime_vol_ratio():
    """SPY 30분봉으로 동시간대 거래량 비율 계산. 장중에만 유효, 5분 캐시."""
    now_ts = datetime.now().timestamp()
    # 캐시 유효하면 바로 반환
    with _vol_lock:
        if _vol_cache['value'] is not None and now_ts < _vol_cache['expires']:
            return _vol_cache['value']
    try:
        now_et = datetime.now(_ET)
        # 주말이면 None
        if now_et.weekday() >= 5:
            return None
        # 장 시간 외면 None (전일 마감 데이터 사용)
        if not (_MARKET_OPEN <= now_et.time() <= _MARKET_CLOSE):
            return None
        # SPY 30분봉 1달치 다운로드
        df = yf.download('SPY', period='1mo', interval='30m', progress=False)
        vol = df['Volume'].squeeze()
        vol.index = vol.index.tz_convert(_ET)
        # 날짜/시간 분리
        dates = vol.index.date
        times = vol.index.time
        today = now_et.date()
        # 오늘 데이터 필터
        today_mask = dates == today
        if not today_mask.any():
            return None
        # 오늘 누적 거래량과 마지막 봉 시간
        today_cumvol = int(vol[today_mask].sum())
        last_time = times[today_mask][-1]
        # 과거 각 날짜별 동시간대(<=last_time) 누적 거래량
        past_mask = (dates != today) & (times <= last_time)
        past_vol = vol[past_mask]
        if past_vol.empty:
            return None
        past_dates = past_vol.index.date
        past_daily = pd.Series(past_vol.values, index=past_dates).groupby(level=0).sum()
        avg_past = past_daily.mean()
        if avg_past <= 0:
            return None
        result = round(today_cumvol / avg_past, 4)
        # 캐시 저장
        with _vol_lock:
            _vol_cache['value'] = result
            _vol_cache['expires'] = now_ts + _CACHE_SEC
        return result
    except Exception:
        return None


@router.get('/latest')
def get_latest():
    rows = fetch_macro_latest2()
    if not rows:
        return None
    current = rows[0]
    # 최신 레코드의 주요 값이 null이면(putcall만 별도 upsert된 경우) 이전 레코드로 보완
    if current.get('vix') is None and len(rows) >= 2 and rows[1].get('vix') is not None:
        prev_full = rows[1]
        for key in ('sp500_close', 'sp500_return', 'sp500_vol20', 'vix', 'tnx', 'yield_spread', 'dxy_return', 'sp500_rsi'):
            if current.get(key) is None and prev_full.get(key) is not None:
                current[key] = prev_full[key]
    if len(rows) >= 2:
        prev = rows[1]
        current['prev_vix'] = prev.get('vix')
        current['prev_sp500_vol20'] = prev.get('sp500_vol20')
    # 실시간 동시간대 거래량 비율 (장중이면 덮어쓰기)
    rt_vol = _realtime_vol_ratio()
    if rt_vol is not None:
        current['sp500_vol20'] = rt_vol
    return current


@router.get('/fear-greed')
def get_fear_greed():
    rows = fetch_fear_greed_latest2()
    if not rows:
        return None
    current = rows[0]
    if len(rows) >= 2:
        current['prev_score'] = rows[1].get('score')
    return current