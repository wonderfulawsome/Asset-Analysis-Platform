import math
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


def _sanitize_floats(obj):
    """NaN/Infinity를 None으로 변환하여 JSON 직렬화 오류 방지."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


def _is_prediction_valid(predicted):
    """예측 데이터에 유효한 값이 있는지 확인."""
    if not predicted or not isinstance(predicted, list):
        return False
    valid = [p for p in predicted
             if isinstance(p, dict) and p.get('yhat') is not None]
    return len(valid) >= 5  # 최소 5개 유효 포인트


# 백그라운드 재생성 상태 관리
_predict_running = set()


def _regenerate_in_background(ticker: str):
    """백그라운드 스레드에서 예측 데이터를 재생성한다."""
    try:
        from processor.feature4_chart_predict import run_chart_predict_single
        from database.repositories import upsert_chart_predict
        print(f'[Chart] {ticker} 백그라운드 예측 재생성 시작...')
        rec = run_chart_predict_single(ticker)
        if rec:
            upsert_chart_predict(rec)
            print(f'[Chart] {ticker} 백그라운드 예측 재생성 완료')
        else:
            print(f'[Chart] {ticker} 백그라운드 예측 재생성 실패: 데이터 없음')
    except Exception as e:
        print(f'[Chart] {ticker} 백그라운드 예측 재생성 실패: {e}')
    finally:
        _predict_running.discard(ticker)


@router.get('/predict')
def get_prediction(ticker: str = Query('SPY', description='ETF 티커')):
    """Prophet 30일 예측 결과를 DB에서 조회 (스케줄러가 3시간마다 갱신)"""
    from database.repositories import fetch_chart_predict

    ticker = ticker.upper()
    if ticker not in CHART_TICKERS:
        return {'error': 'unsupported ticker'}

    result = fetch_chart_predict(ticker)

    # DB 데이터 유효성 검증
    if result is not None:
        sanitized_pred = _sanitize_floats(result.get('predicted', []))
        if not _is_prediction_valid(sanitized_pred):
            print(f'[Chart] {ticker} 예측 데이터 손상 감지')
            result = None

    if result is None:
        # 백그라운드에서 재생성 트리거 (사용자는 기다리지 않음)
        if ticker not in _predict_running:
            _predict_running.add(ticker)
            threading.Thread(target=_regenerate_in_background, args=(ticker,),
                             daemon=True).start()
        return {'error': 'prediction is being prepared, please retry in a moment'}

    return {
        'ticker': result['ticker'],
        'actual': _sanitize_floats(result['actual']),
        'predicted': _sanitize_floats(result['predicted']),
    }


@router.get('/tickers')
def get_tickers():
    """차트 가능 티커 목록"""
    return CHART_TICKERS
