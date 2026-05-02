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

# 주요 US ETF 목록 (yfinance)
CHART_TICKERS = ['SPY', 'QQQ', 'DIA', 'IWM', 'VTI', 'VOO', 'SOXX', 'SMH',
                 'XLK', 'XLF', 'XLE', 'XLV', 'ARKK', 'GLD', 'TLT', 'SCHD']

# 주요 KR ETF 목록 (pykrx, 6자리 종목코드)
CHART_TICKERS_KR = [
    '069500',  # KODEX 200
    '102110',  # TIGER 200
    '232080',  # TIGER 코스닥150
    '229200',  # KODEX 코스닥150
    '091160',  # KODEX 반도체
    '139260',  # TIGER 200 IT
    '091170',  # KODEX 은행
    '266420',  # KODEX 헬스케어
    '139250',  # TIGER 200 에너지화학
    '091180',  # KODEX 자동차
    '117680',  # KODEX 철강
    '341850',  # TIGER 리츠부동산인프라
]


def _is_kr_ticker(ticker: str) -> bool:
    """6자리 숫자만 있으면 KR ETF, 아니면 US."""
    return ticker.isdigit() and len(ticker) == 6

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


def _download_kr(ticker: str, interval: str):
    """pykrx 로 KR ETF OHLCV 다운로드.

    pykrx 컬럼은 한글이라 영어로 리네임. interval='1d' 만 직접 지원,
    '1wk'/'1mo' 는 일봉을 받아 리샘플링.
    """
    try:
        from pykrx import stock
        from datetime import date, timedelta
        # period 결정 — interval 별 다른 길이
        if interval == '1d':
            period_days = 365 * 2  # 2년
        elif interval == '1wk':
            period_days = 365 * 5
        else:
            period_days = 365 * 10
        end = date.today().strftime('%Y%m%d')
        start = (date.today() - timedelta(days=period_days)).strftime('%Y%m%d')
        df = stock.get_etf_ohlcv_by_date(start, end, ticker)
        if df is None or df.empty:
            return None
        # 한글 컬럼 → 영어
        df = df.rename(columns={
            '시가': 'Open', '고가': 'High', '저가': 'Low', '종가': 'Close', '거래량': 'Volume',
        })
        # Index 가 datetime 인지 확인
        if not pd.api.types.is_datetime64_any_dtype(df.index):
            df.index = pd.to_datetime(df.index)
        # 1wk / 1mo 리샘플
        if interval in ('1wk', '1mo'):
            df = _resample_daily_to(df, interval)
        return df
    except Exception as e:
        print(f'[Chart-KR] {ticker} {interval}: 실패: {e}')
        return None


def _download_with_fallback(ticker, interval, max_retries=2):
    """yfinance(US) / pykrx(KR) 자동 분기 다운로드.

    1차: 요청 interval로 직접 다운로드 (재시도 포함)
    2차: 일봉 다운로드 → 주봉/월봉 리샘플링 (1wk, 1mo인 경우, US 만 적용)
    """
    # KR 티커는 pykrx 경로
    if _is_kr_ticker(ticker):
        return _download_kr(ticker, interval)

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
    ticker: str = Query('SPY', description='ETF 티커 (US: SPY 등 / KR: 069500 등 6자리)'),
    interval: str = Query('1d', description='봉 간격: 1d, 1wk, 1mo'),
):
    """캔들스틱 OHLC 데이터 반환 — US (yfinance) / KR (pykrx) 자동 분기."""
    # KR 6자리 숫자면 그대로, US 는 대문자 변환
    if not _is_kr_ticker(ticker):
        ticker = ticker.upper()
    # 허용 ticker 검증
    if ticker not in CHART_TICKERS and ticker not in CHART_TICKERS_KR:
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
    """예측 데이터에 유효한 값이 있는지 확인.

    두 형식 모두 지원:
      - 신규 dict: {'forecast': [...], 'predicted': [...], 'metrics': {...}, ...}
      - legacy list: [{date, yhat, lower, upper}, ...]
    """
    if not predicted:
        return False
    # 신규 dict 형식 — forecast 또는 predicted (legacy) 안의 유효 row 5개 이상
    if isinstance(predicted, dict):
        for key in ('forecast', 'predicted'):
            arr = predicted.get(key)
            if isinstance(arr, list):
                valid_key = 'median' if key == 'forecast' else 'yhat'
                valid = [p for p in arr
                         if isinstance(p, dict) and p.get(valid_key) is not None]
                if len(valid) >= 5:
                    return True
        return False
    # Legacy list 형식
    if isinstance(predicted, list):
        valid = [p for p in predicted
                 if isinstance(p, dict) and p.get('yhat') is not None]
        return len(valid) >= 5
    return False


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
    """5-모델 앙상블 30일 예측 결과를 DB에서 조회.
    DB에 없으면 백그라운드 재생성 후 폴링하여 완료를 대기한다.

    KR 티커는 Stage 3 에서 모델 학습 추가 예정 — 현재는 'no model' 응답.
    """
    from database.repositories import fetch_chart_predict

    if not _is_kr_ticker(ticker):
        ticker = ticker.upper()
    if ticker not in CHART_TICKERS and ticker not in CHART_TICKERS_KR:
        return {'error': 'unsupported ticker'}
    if _is_kr_ticker(ticker):
        return {'error': 'KR 예측 모델 미학습 — Stage 3 에서 제공 예정'}

    def _fetch_valid(t):
        r = fetch_chart_predict(t)
        if r is not None:
            sp = _sanitize_floats(r.get('predicted', []))
            if _is_prediction_valid(sp):
                return r
            print(f'[Chart] {t} 예측 데이터 손상 감지')
        return None

    result = _fetch_valid(ticker)

    if result is None:
        # 백그라운드에서 재생성 트리거
        if ticker not in _predict_running:
            _predict_running.add(ticker)
            threading.Thread(target=_regenerate_in_background, args=(ticker,),
                             daemon=True).start()

        # 백그라운드 재생성 완료까지 폴링 대기 (최대 ~120초)
        _POLL_INTERVAL = 3   # 초
        _MAX_POLLS = 40      # 40 × 3초 = 120초
        for i in range(_MAX_POLLS):
            time.sleep(_POLL_INTERVAL)
            # 백그라운드 스레드 완료 확인
            if ticker not in _predict_running:
                result = _fetch_valid(ticker)
                break
            # 스레드 실행 중에도 주기적으로 DB 확인 (15초 간격)
            if i % 5 == 4:
                result = _fetch_valid(ticker)
                if result is not None:
                    break

        if result is None:
            return {'error': 'prediction generation failed, please try again later'}

    pred_clean = _sanitize_floats(result['predicted'])

    response = {
        'ticker': result['ticker'],
        'actual': _sanitize_floats(result['actual']),
    }

    # 신규 dict 형식이면 forecast/sample_paths/metrics/metadata 모두 펴서 노출
    # 동시에 legacy 'predicted' 필드도 유지 (chart.js 하위 호환)
    if isinstance(pred_clean, dict):
        response['predicted'] = pred_clean.get('predicted', [])         # legacy
        response['forecast'] = pred_clean.get('forecast', [])           # 신규 분위수
        response['sample_paths'] = pred_clean.get('sample_paths', [])
        response['metrics'] = pred_clean.get('metrics', {})
        response['metadata'] = pred_clean.get('metadata', {})
    else:
        # 옛 DB row (list) — chart.js 그대로 작동
        response['predicted'] = pred_clean

    return response


@router.get('/tickers')
def get_tickers():
    """차트 가능 티커 목록"""
    return CHART_TICKERS
