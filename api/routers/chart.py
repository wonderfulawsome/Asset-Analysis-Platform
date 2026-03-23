import math
import time
import threading
from datetime import datetime
import pandas as pd
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


def _flatten_columns(df):
    """yfinance MultiIndex 컬럼을 단일 레벨로 변환."""
    if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
        df.columns = df.columns.get_level_values(0)
    return df


def _resample_daily_to(df, interval):
    """일봉 DataFrame을 주봉/월봉으로 리샘플링."""
    rule = 'W' if interval == '1wk' else 'ME'
    resampled = df.resample(rule).agg({
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum',
    }).dropna(subset=['Open', 'Close'])
    return resampled


def _download_with_fallback(ticker, interval, max_retries=2):
    """yfinance 다운로드 + 재시도 + 일봉 리샘플링 fallback.

    1차: 요청 interval로 직접 다운로드 (재시도 포함)
    2차: 일봉 다운로드 → 주봉/월봉 리샘플링 (1wk, 1mo인 경우)
    """
    cfg = INTERVAL_CONFIG[interval]

    # 1차: 직접 다운로드 (재시도)
    for attempt in range(max_retries):
        try:
            df = yf.download(ticker, period=cfg['period'], interval=interval,
                             auto_adjust=True, progress=False)
            df = _flatten_columns(df)
            if not df.empty and len(df) >= 2:
                return df
        except Exception:
            pass
        if attempt < max_retries - 1:
            time.sleep(1)

    # 2차: 일봉으로 다운로드 → 리샘플링 (주봉/월봉만)
    if interval in ('1wk', '1mo'):
        try:
            period = '5y' if interval == '1wk' else '10y'
            df_daily = yf.download(ticker, period=period, interval='1d',
                                   auto_adjust=True, progress=False)
            df_daily = _flatten_columns(df_daily)
            if not df_daily.empty:
                resampled = _resample_daily_to(df_daily, interval)
                if not resampled.empty and len(resampled) >= 2:
                    print(f'[Chart] {ticker} {interval}: 일봉→리샘플링 fallback 사용')
                    return resampled
        except Exception as e:
            print(f'[Chart] {ticker} {interval}: 리샘플링 fallback 실패: {e}')

    return None


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
        df = _download_with_fallback(ticker, interval)
        if df is None or df.empty:
            return {'error': 'no data'}

        candles = []
        for idx, row in df.iterrows():
            o, h, l, c = float(row['Open']), float(row['High']), float(row['Low']), float(row['Close'])
            # NaN/Infinity 행 건너뛰기 — JSON 직렬화 오류 방지
            if any(math.isnan(v) or math.isinf(v) for v in (o, h, l, c)):
                continue
            vol = row.get('Volume', 0) if 'Volume' in row else 0
            candles.append({
                'd': idx.strftime('%Y-%m-%d'),
                'o': round(o, 2),
                'h': round(h, 2),
                'l': round(l, 2),
                'c': round(c, 2),
                'v': int(vol) if vol == vol and not math.isinf(float(vol)) else 0,
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
