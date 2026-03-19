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
def get_prediction(ticker: str = Query('SPY', description='ETF 티커')):
    """Prophet 30일 예측 결과를 DB에서 조회 (스케줄러가 3시간마다 갱신)"""
    from database.repositories import fetch_chart_predict

    ticker = ticker.upper()
    if ticker not in CHART_TICKERS:
        return {'error': 'unsupported ticker'}

    result = fetch_chart_predict(ticker)
    if result is None:
        return {'error': 'no prediction available yet'}

    return {
        'ticker': result['ticker'],
        'actual': result['actual'],
        'predicted': result['predicted'],
    }


@router.get('/tickers')
def get_tickers():
    """차트 가능 티커 목록"""
    return CHART_TICKERS
