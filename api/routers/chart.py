import threading
from datetime import datetime
from fastapi import APIRouter, Query
import yfinance as yf

router = APIRouter()

# 캐시: {ticker_interval: {data, expires}}
_cache: dict = {}
_lock = threading.Lock()
_CACHE_SEC = 600  # 10분

# 주요 ETF 목록
CHART_TICKERS = ['SPY', 'QQQ', 'DIA', 'IWM', 'VTI', 'VOO', 'SOXX', 'SMH',
                 'XLK', 'XLF', 'XLE', 'XLV', 'ARKK', 'GLD', 'TLT', 'SCHD']

# yfinance interval → period 매핑
INTERVAL_CONFIG = {
    '1d':  {'period': '2y'},    # 일봉: 2년
    '1wk': {'period': '5y'},    # 주봉: 5년
    '1mo': {'period': 'max'},   # 월봉: 최대
}


@router.get('/ohlc')
def get_ohlc(
    ticker: str = Query('SPY', description='ETF 티커'),
    interval: str = Query('1d', description='봉 간격: 1d, 1wk, 1mo'),
):
    """캔들스틱 OHLC 데이터 반환"""
    ticker = ticker.upper()
    if ticker not in CHART_TICKERS:
        return {'error': 'unsupported ticker'}
    if interval not in INTERVAL_CONFIG:
        return {'error': 'unsupported interval'}

    cache_key = f'{ticker}_{interval}'
    now_ts = datetime.now().timestamp()

    with _lock:
        cached = _cache.get(cache_key)
        if cached and now_ts < cached['expires']:
            return cached['data']

    try:
        cfg = INTERVAL_CONFIG[interval]
        df = yf.download(ticker, period=cfg['period'], interval=interval,
                         auto_adjust=True, progress=False)
        if df.empty:
            return {'error': 'no data'}

        # MultiIndex 처리 (yfinance 0.2.x)
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)

        candles = []
        for idx, row in df.iterrows():
            dt_str = idx.strftime('%Y-%m-%d')
            candles.append({
                'd': dt_str,
                'o': round(float(row['Open']), 2),
                'h': round(float(row['High']), 2),
                'l': round(float(row['Low']), 2),
                'c': round(float(row['Close']), 2),
                'v': int(row['Volume']) if 'Volume' in row and row['Volume'] == row['Volume'] else 0,
            })

        result = {'ticker': ticker, 'interval': interval, 'candles': candles}

        with _lock:
            _cache[cache_key] = {'data': result, 'expires': now_ts + _CACHE_SEC}

        return result
    except Exception as e:
        return {'error': str(e)}


@router.get('/predict')
# 기본값은 SPY로 파라미터 설정
def get_prediction(ticker: str = Query('SPY', description='ETF 티커')):
    """Prophet 모델로 30일 주가 예측"""
    # ticker 대문자로 변경
    ticker = ticker.upper()
    if ticker not in CHART_TICKERS:
        return {'error': 'unsupported ticker'}

    # cache_key는 pred_{ticker}로 설정
    cache_key = f'pred_{ticker}'
    now_ts = datetime.now().timestamp()
    with _lock:
        cached = _cache.get(cache_key)
        # 만약 cached와 now_ts가 10분 이전 데이터라면 cached 데이터를 가져와서 중복 호출을 방지한다
        if cached and now_ts < cached['expires']:
            return cached['data']

    try:
        from prophet import Prophet
        import pandas as pd

        # 최근 2년의 일봉을 다운로드 (추세 학습 개선)
        df = yf.download(ticker, period='2y', interval='1d',
                         auto_adjust=True, progress=False)
        if df.empty:
            return {'error': 'no data'}

        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)

        import numpy as np

        # ds(날짜) y(종가)를 학습데이터로 사용
        prophet_df = df[['Close']].reset_index()
        prophet_df.columns = ['ds', 'y']

        # 로그 변환: 주가는 %로 움직이므로 log 스케일이 현실적
        prophet_df['y'] = np.log(prophet_df['y'])

        # changepoint_prior_scale=0.15: 최근 추세를 민감하게 반영
        # n_changepoints=50: 추세 변화점을 세밀하게 포착
        # seasonality_mode='multiplicative': 가격 수준에 비례하는 계절성
        model = Prophet(
            daily_seasonality=False,
            yearly_seasonality=True,
            weekly_seasonality=False,
            changepoint_prior_scale=0.15,
            n_changepoints=50,
            seasonality_mode='multiplicative',
        )
        model.fit(prophet_df)

        # freq='B' 영업일만 생성하여 주말 포인트 제거
        future = model.make_future_dataframe(periods=30, freq='B')
        forecast = model.predict(future)

        # 로그 역변환 (exp)
        forecast['yhat'] = np.exp(forecast['yhat'])
        forecast['yhat_lower'] = np.exp(forecast['yhat_lower'])
        forecast['yhat_upper'] = np.exp(forecast['yhat_upper'])
        prophet_df['y'] = np.exp(prophet_df['y'])

        recent = prophet_df.tail(30)
        actual = [{'date': str(r.ds.date()), 'close': round(float(r.y), 2)}
                  for _, r in recent.iterrows()]

        # yhat=예측 중앙값 (prophet으로 예측시 자동으로 생성)
        pred = forecast.tail(30)
        predicted = [{'date': str(r.ds.date()),
                      'yhat': round(float(r.yhat), 2),
                      'lower': round(float(r.yhat_lower), 2),
                      'upper': round(float(r.yhat_upper), 2)}
                     for _, r in pred.iterrows()]

        result = {'ticker': ticker, 'actual': actual, 'predicted': predicted}

        with _lock:
            _cache[cache_key] = {'data': result, 'expires': now_ts + _CACHE_SEC}

        return result
    except Exception as e:
        return {'error': str(e)}


@router.get('/tickers')
def get_tickers():
    """차트 가능 티커 목록"""
    return CHART_TICKERS
