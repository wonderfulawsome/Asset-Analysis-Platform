"""Noise vs Signal HMM: 데이터 수집 + 8피처 엔지니어링

노트북 HMM.ipynb Cell 2~9 로직을 production 코드로 변환.
8개 월별 피처: fundamental_gap, erp_zscore, residual_corr, dispersion,
              amihud, vix_term, hy_spread, realized_vol
"""

import datetime
import time
import warnings
from itertools import combinations
from io import StringIO

import numpy as np
import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings('ignore')

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
FRED_BASE = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id='
SHILLER_URL = 'http://www.econ.yale.edu/~shiller/data/ie_data.xls'

SECTOR_STOCKS = {
    'XLK': ['AAPL', 'MSFT', 'NVDA', 'AVGO', 'CRM'],
    'XLF': ['JPM', 'BAC', 'WFC', 'GS', 'MS'],
    'XLE': ['XOM', 'CVX', 'COP', 'SLB', 'EOG'],
    'XLV': ['UNH', 'JNJ', 'LLY', 'PFE', 'ABT'],
    'XLI': ['CAT', 'HON', 'UNP', 'GE', 'RTX'],
}
ALL_STOCKS = [s for stocks in SECTOR_STOCKS.values() for s in stocks]

AMIHUD_STOCKS = ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META']

FEATURE_NAMES = [
    'fundamental_gap', 'erp_zscore', 'residual_corr',
    'dispersion', 'amihud', 'vix_term', 'hy_spread',
    'realized_vol',
]

# FRED 시리즈 ID (VIX/VIX3M은 Yahoo Finance로 대체)
FRED_SERIES = {
    'DFII10': 'tips_rate',       # 10년 TIPS 실질금리
    'BAMLH0A0HYM2': 'hy_spread', # ICE BofA HY OAS
}

# Yahoo Finance로 수집하는 변동성 지수 (FRED 대체)
YAHOO_VOL_TICKERS = {
    '^VIX': 'vix',               # VIX 일별 (FRED VIXCLS 대체)
    '^VIX3M': 'vix3m',           # VIX3M 일별 (FRED VXVCLS 대체)
}


_fred_session = requests.Session()                           # FRED 전용 세션 (TCP 연결 재사용)
_fred_session.headers.update(HEADERS)


def _fetch_fred(series_id: str, col_name: str, retries: int = 5,
                timeout: tuple = (15, 60)) -> pd.DataFrame:
    """FRED CSV 다운로드 (지수 백오프 재시도, connect=15s/read=60s 타임아웃).

    Args:
        series_id: FRED 시리즈 ID (예: DFII10)
        col_name: 결과 DataFrame 컬럼명
        retries: 최대 재시도 횟수 (기본 5)
        timeout: (connect, read) 타임아웃 튜플 (기본 15초/60초)
    """
    url = FRED_BASE + series_id                              # FRED CSV 다운로드 URL
    for attempt in range(retries):                           # 최대 retries번 시도
        try:
            resp = _fred_session.get(url, timeout=timeout)   # 세션 기반 요청 (연결 재사용)
            resp.raise_for_status()                          # 4xx/5xx 에러 시 예외
            df = pd.read_csv(StringIO(resp.text), index_col=0, parse_dates=True)  # CSV 파싱
            df.columns = [col_name]                          # 컬럼명 설정
            df[col_name] = pd.to_numeric(df[col_name], errors='coerce')  # 숫자 변환
            return df                                        # 성공 시 반환
        except Exception as e:
            if attempt < retries - 1:                        # 마지막 시도 전이면
                wait = 3 * (2 ** attempt)                    # 3초, 6초, 12초, 24초 대기
                print(f'  [{series_id}] 재시도 {attempt+1}/{retries} ({wait}초 대기) — {type(e).__name__}')
                time.sleep(wait)                             # 대기 후 재시도
            else:
                raise                                        # 최종 실패 시 예외


def _fetch_yahoo_monthly(ticker: str, years: int = 3) -> pd.Series:
    """Yahoo Finance v8 API로 월별 종가 Series 반환."""
    today = datetime.date.today()
    from_date = today - datetime.timedelta(days=365 * years)
    epoch = datetime.datetime(1970, 1, 1)
    from_ts = int((datetime.datetime.combine(from_date, datetime.time()) - epoch).total_seconds())
    to_ts = int((datetime.datetime.combine(today, datetime.time()) - epoch).total_seconds())
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
    params = {'interval': '1mo', 'period1': from_ts, 'period2': to_ts}
    resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    result = resp.json()['chart']['result'][0]
    timestamps = result['timestamp']
    closes = result['indicators']['adjclose'][0]['adjclose']
    index = pd.to_datetime(timestamps, unit='s').normalize()
    return pd.Series(closes, index=index, name='P')


def _fetch_yahoo_daily(ticker: str, years: int = 20) -> pd.DataFrame:
    """Yahoo Finance v8 API로 일별 종가 DataFrame 반환 (VIX/VIX3M용)."""
    today = datetime.date.today()                        # 오늘 날짜
    from_date = today - datetime.timedelta(days=365 * years)  # 시작일
    epoch = datetime.datetime(1970, 1, 1)                # Unix epoch
    from_ts = int((datetime.datetime.combine(from_date, datetime.time()) - epoch).total_seconds())  # 시작 timestamp
    to_ts = int((datetime.datetime.combine(today, datetime.time()) - epoch).total_seconds())  # 종료 timestamp
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'  # API URL
    params = {'interval': '1d', 'period1': from_ts, 'period2': to_ts}  # 일봉, 기간
    resp = requests.get(url, params=params, headers=HEADERS, timeout=15)  # HTTP 요청
    resp.raise_for_status()                              # 에러 시 예외
    result = resp.json()['chart']['result'][0]           # 차트 데이터
    timestamps = result['timestamp']                     # 타임스탬프 배열
    closes = result['indicators']['adjclose'][0]['adjclose']  # 수정 종가 배열
    index = pd.to_datetime(timestamps, unit='s').normalize()  # 날짜 인덱스
    col_name = YAHOO_VOL_TICKERS.get(ticker, ticker)     # 내부 컬럼명 매핑
    df = pd.DataFrame({col_name: closes}, index=index)   # DataFrame 생성
    df = df[~df.index.duplicated(keep='last')]           # 중복 날짜 제거
    return df


def _strip_tz(s: pd.Series) -> pd.Series:
    """타임존 제거."""
    s = s.copy()
    if hasattr(s.index, 'tz') and s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    return s


def _strip_tz_df(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame 타임존 제거."""
    df = df.copy()
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 데이터 수집 함수
# ─────────────────────────────────────────────────────────────────────────────

def fetch_shiller() -> pd.DataFrame:
    """Shiller ie_data.xls에서 P, E, CAPE 월별 DataFrame 반환.

    최신 P가 끊기는 구간은 Yahoo Finance ^GSPC로 보완.
    E는 forward-fill, CAPE 없으면 P/E10으로 계산.
    """
    print('[NoiseHMM] Shiller ie_data.xls 다운로드 중...')
    shiller = pd.read_excel(SHILLER_URL, sheet_name='Data', skiprows=7, header=0)

    cols = shiller.columns.tolist()
    shiller = shiller.rename(columns={cols[0]: 'date_raw', cols[1]: 'P', cols[3]: 'E'})

    # CAPE 컬럼 찾기
    cape_col = None
    for c in cols:
        if isinstance(c, str) and ('cape' in c.lower() or 'cyclically' in c.lower()):
            cape_col = c
            break

    cape_available = cape_col is not None
    if cape_available:
        shiller = shiller.rename(columns={cape_col: 'CAPE'})

    # 날짜 파싱
    def parse_date(val):
        try:
            s = str(val)
            parts = s.split('.')
            year = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 and parts[1] else 1
            month = max(1, min(12, month))
            return pd.Timestamp(year=year, month=month, day=1)
        except Exception:
            return pd.NaT

    shiller['date'] = shiller['date_raw'].apply(parse_date)
    shiller = shiller.dropna(subset=['date']).set_index('date')
    shiller = shiller[~shiller.index.duplicated(keep='last')].sort_index()

    for col in ['P', 'E']:
        shiller[col] = pd.to_numeric(shiller[col], errors='coerce')
    if cape_available:
        shiller['CAPE'] = pd.to_numeric(shiller['CAPE'], errors='coerce')

    # Yahoo Finance로 최신 P 보완
    sp_yahoo = _fetch_yahoo_monthly('^GSPC')
    sp_yahoo.index = sp_yahoo.index.to_period('M').to_timestamp()
    last_shiller_p = shiller['P'].dropna().index[-1]
    new_months = sp_yahoo[sp_yahoo.index > last_shiller_p]
    for dt, price in new_months.items():
        if dt not in shiller.index:
            shiller.loc[dt] = np.nan
        shiller.loc[dt, 'P'] = price
    shiller = shiller.sort_index()

    # E forward-fill, CAPE 계산
    shiller['E'] = shiller['E'].ffill()
    e10 = shiller['E'].rolling(120, min_periods=60).mean()
    if cape_available:
        shiller['CAPE'] = shiller['CAPE'].fillna(shiller['P'] / e10)
    else:
        shiller['CAPE'] = shiller['P'] / e10

    shiller = shiller[shiller['P'].notna() & shiller['E'].notna()]
    print(f'  Shiller: {shiller.index[0].date()} ~ {shiller.index[-1].date()} ({len(shiller)}개월)')
    return shiller[['P', 'E', 'CAPE']]


def fetch_fred_regime() -> dict:
    """FRED 2개(TIPS, HY) + Yahoo 2개(VIX, VIX3M) 수집 → dict[str, DataFrame] 반환."""
    result = {}                                          # 결과 딕셔너리

    # ── FRED 시리즈 수집 (TIPS 실질금리, HY 스프레드) ──
    print('[NoiseHMM] FRED 데이터 수집 중...')
    for series_id, col_name in FRED_SERIES.items():      # DFII10, BAMLH0A0HYM2
        try:
            df = _fetch_fred(series_id, col_name)            # CSV 다운로드
            result[col_name] = df                            # 결과에 저장
            monthly = df[col_name].resample('MS').last().dropna()  # 월별 집계
            print(f'  {series_id} ({col_name}): {len(monthly)}개월')
        except Exception as e:
            print(f'  [{series_id}] FRED 수집 실패, 빈 데이터 사용: {e}')
            result[col_name] = pd.DataFrame({col_name: []}, index=pd.DatetimeIndex([]))

    # ── Yahoo Finance로 VIX/VIX3M 수집 (FRED 대체) ──
    print('[NoiseHMM] Yahoo Finance VIX/VIX3M 수집 중...')
    for ticker, col_name in YAHOO_VOL_TICKERS.items():   # ^VIX, ^VIX3M
        df = _fetch_yahoo_daily(ticker)                  # Yahoo v8 API 호출
        result[col_name] = df                            # 결과에 저장
        monthly = df[col_name].resample('MS').last().dropna()  # 월별 집계
        print(f'  {ticker} ({col_name}): {len(monthly)}개월')

    return result


def fetch_sector_stocks(start_date: str) -> pd.DataFrame:
    """25 섹터 종목 + SPY 일별 종가 수집 (yfinance)."""
    print(f'[NoiseHMM] 섹터 종목 + SPY 일별 종가 수집 중... (from {start_date})')
    frames = {}
    for ticker in ['SPY'] + ALL_STOCKS:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(start=start_date, auto_adjust=True)
            if len(hist) > 0:
                idx = hist.index
                if hasattr(idx, 'tz') and idx.tz is not None:
                    idx = idx.tz_localize(None)
                frames[ticker] = pd.Series(hist['Close'].values, index=idx, name=ticker)
        except Exception as e:
            print(f'  {ticker} 실패: {e}')

    df = pd.DataFrame(frames)
    df.index = pd.to_datetime(df.index)
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    print(f'  종목 수: {len(df.columns)}, 기간: {len(df)}일')
    return df


def fetch_amihud_stocks(start_date: str) -> dict:
    """5 mega-cap OHLCV 수집 → dict[ticker, DataFrame]."""
    print(f'[NoiseHMM] Amihud 종목 OHLCV 수집 중...')
    result = {}
    for ticker in AMIHUD_STOCKS:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(start=start_date, auto_adjust=True)
            if len(hist) > 0:
                hist = _strip_tz_df(hist)
                result[ticker] = hist[['Open', 'Close', 'Volume']]
        except Exception as e:
            print(f'  {ticker} 실패: {e}')
    print(f'  Amihud 종목: {len(result)}개')
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 피처 엔지니어링
# ─────────────────────────────────────────────────────────────────────────────

def compute_monthly_features(
    shiller: pd.DataFrame,
    fred: dict,
    stock_prices: pd.DataFrame,
    amihud_data: dict,
) -> dict:
    """8개 월별 피처 계산 + 윈저라이징.

    Returns:
        dict with keys:
        - 'features': pd.DataFrame (N, 8) 월별 피처 (윈저라이징 적용)
        - 'winsor_bounds': dict[str, (float, float)] 각 피처의 1/99 백분위
        - 'residuals': pd.DataFrame 일별 잔차 수익률
        - 'stock_returns': pd.DataFrame 일별 주가 수익률
        - 'amihud_frames': dict 일별 amihud OHLCV
        - 'fred_raw': dict 원본 FRED DataFrame
        - 'spy_ret': pd.Series SPY 일별 수익률
        - 'amihud_q01': float
        - 'amihud_q99': float
    """
    # ── ① fundamental_gap ──
    shiller_c = shiller.copy()
    shiller_c['log_P'] = np.log(shiller_c['P'])
    shiller_c['log_E'] = np.log(shiller_c['E'].clip(lower=0.01))
    fundamental_gap = (shiller_c['log_P'].diff(12) - shiller_c['log_E'].diff(12)).dropna()
    fundamental_gap.name = 'fundamental_gap'

    # ── ② erp_zscore ──
    cape_series = shiller_c['CAPE'].dropna()
    real_ey = 1.0 / cape_series
    tips_monthly = fred['tips_rate']['tips_rate'].resample('MS').last().dropna() / 100.0
    erp_df = pd.DataFrame({'ey': real_ey, 'tips': tips_monthly}).dropna()
    erp = erp_df['ey'] - erp_df['tips']
    erp_rm = erp.rolling(120, min_periods=60).mean()
    erp_rs = erp.rolling(120, min_periods=60).std()
    erp_zscore = ((erp - erp_rm) / erp_rs).abs().dropna()
    erp_zscore.name = 'erp_zscore'

    # ── ③ residual_corr + dispersion ──
    stock_returns = stock_prices.pct_change().dropna()
    spy_ret = _strip_tz(stock_returns['SPY']) if 'SPY' in stock_returns.columns else None

    # 베타 제거 잔차
    residuals = pd.DataFrame(index=stock_returns.index)
    for ticker in ALL_STOCKS:
        if ticker not in stock_returns.columns or spy_ret is None:
            continue
        ret = stock_returns[ticker]
        cov_spy = ret.rolling(60, min_periods=30).cov(spy_ret)
        spy_var = spy_ret.rolling(60, min_periods=30).var()
        beta = cov_spy / spy_var
        residuals[ticker] = ret - beta * spy_ret
    residuals = residuals.dropna(how='all')

    # 섹터별 잔차 페어와이즈 상관 → 전체 평균
    sector_corrs = []
    for sector, stocks in SECTOR_STOCKS.items():
        available = [s for s in stocks if s in residuals.columns]
        if len(available) < 2:
            continue
        pair_corrs = []
        for s1, s2 in combinations(available, 2):
            rc = residuals[s1].rolling(20).corr(residuals[s2])
            pair_corrs.append(rc)
        sector_avg = pd.concat(pair_corrs, axis=1).mean(axis=1)
        sector_corrs.append(sector_avg)
    daily_resid_corr = pd.concat(sector_corrs, axis=1).mean(axis=1).dropna()
    residual_corr_monthly = _strip_tz(daily_resid_corr).resample('MS').mean().dropna()
    residual_corr_monthly.name = 'residual_corr'

    # 크로스섹션 디스퍼전
    avail_stocks = [s for s in ALL_STOCKS if s in stock_returns.columns]
    cross_std = stock_returns[avail_stocks].std(axis=1)
    disp_daily = cross_std.rolling(20).mean().dropna()
    dispersion_monthly = _strip_tz(disp_daily).resample('MS').mean().dropna()
    dispersion_monthly.name = 'dispersion'

    # ── ④ amihud ──
    amihud_per_stock = []
    for ticker, df_t in amihud_data.items():
        oc_ret = np.log(df_t['Close'] / df_t['Open']).abs()
        dollar_vol = df_t['Close'] * df_t['Volume']
        ami_t = oc_ret / dollar_vol.replace(0, np.nan)
        amihud_per_stock.append(ami_t)

    amihud_avg = pd.concat(amihud_per_stock, axis=1).mean(axis=1).dropna()
    amihud_rolling = amihud_avg.rolling(20).mean().dropna()
    log_amihud = np.log(amihud_rolling + 1e-15)
    amihud_q01 = log_amihud.quantile(0.01)
    amihud_q99 = log_amihud.quantile(0.99)
    log_amihud_w = log_amihud.clip(amihud_q01, amihud_q99)
    log_amihud_w = _strip_tz(log_amihud_w)
    if hasattr(log_amihud_w.index, 'tz') and log_amihud_w.index.tz is not None:
        log_amihud_w.index = log_amihud_w.index.tz_localize(None)
    amihud_monthly = log_amihud_w.resample('MS').mean().dropna()
    amihud_monthly.name = 'amihud'

    # ── ⑤ vix_term ──
    vix_monthly = fred['vix']['vix'].resample('MS').last().dropna()
    vix3m_monthly = fred['vix3m']['vix3m'].resample('MS').last().dropna()
    vix_term_df = pd.DataFrame({'vix': vix_monthly, 'vix3m': vix3m_monthly}).dropna()
    vix_term = (vix_term_df['vix'] / vix_term_df['vix3m']).dropna()
    vix_term.name = 'vix_term'

    # ── ⑥ hy_spread ──
    hy_spread = fred['hy_spread']['hy_spread'].resample('MS').last().dropna()
    hy_spread.name = 'hy_spread'

    # ── ⑦ realized_vol ──
    spy_ret_clean = _strip_tz(spy_ret)
    rv_daily = spy_ret_clean.rolling(20).std() * np.sqrt(252)
    realized_vol_monthly = rv_daily.resample('MS').mean().dropna()
    realized_vol_monthly.name = 'realized_vol'

    # ── 병합 ──
    all_series = {
        'fundamental_gap': fundamental_gap,
        'erp_zscore': erp_zscore,
        'residual_corr': residual_corr_monthly,
        'dispersion': dispersion_monthly,
        'amihud': amihud_monthly,
        'vix_term': vix_term,
        'hy_spread': hy_spread,
        'realized_vol': realized_vol_monthly,
    }
    features = pd.DataFrame({k: _strip_tz(v) for k, v in all_series.items()})
    features = features.dropna()
    print(f'[NoiseHMM] 피처 병합: {features.shape} | {features.index[0].date()} ~ {features.index[-1].date()}')

    # ── 윈저라이징 (1/99 퍼센타일) ──
    winsor_bounds = {}
    for col in FEATURE_NAMES:
        q01 = features[col].quantile(0.01)
        q99 = features[col].quantile(0.99)
        n_clipped = ((features[col] < q01) | (features[col] > q99)).sum()
        features[col] = features[col].clip(q01, q99)
        winsor_bounds[col] = (float(q01), float(q99))
        if n_clipped > 0:
            print(f'  {col}: {n_clipped}개 클리핑')

    return {
        'features': features,
        'winsor_bounds': winsor_bounds,
        'residuals': residuals,
        'stock_returns': stock_returns,
        'amihud_frames': amihud_data,
        'fred_raw': fred,
        'spy_ret': spy_ret,
        'amihud_q01': float(amihud_q01),
        'amihud_q99': float(amihud_q99),
    }


def compute_daily_features(bundle: dict) -> np.ndarray:
    """오늘의 8피처 벡터 (1, 8) 반환.

    월별 피처(fundamental_gap, erp_zscore)는 마지막 값 forward-fill.
    빠른 피처(residual_corr, dispersion, amihud, vix_term, hy_spread, realized_vol)는
    최근 20일 데이터로 재계산.
    """
    features = bundle['features']
    residuals = bundle['residuals']
    stock_returns = bundle['stock_returns']
    amihud_frames = bundle['amihud_frames']
    fred_raw = bundle['fred_raw']
    spy_ret = bundle['spy_ret']
    amihud_q01 = bundle['amihud_q01']
    amihud_q99 = bundle['amihud_q99']

    # ① fundamental_gap: 월별 ffill
    fg_val = float(features['fundamental_gap'].iloc[-1])

    # ② erp_zscore: 월별 ffill
    ez_val = float(features['erp_zscore'].iloc[-1])

    # ③-A residual_corr: 최근 20일 잔차 페어와이즈 상관
    recent_resid = residuals.iloc[-20:]
    pair_corrs = []
    for sector, stocks in SECTOR_STOCKS.items():
        avail = [s for s in stocks if s in recent_resid.columns]
        if len(avail) < 2:
            continue
        for s1, s2 in combinations(avail, 2):
            c = recent_resid[s1].corr(recent_resid[s2])
            pair_corrs.append(c)
    rc_val = float(np.mean(pair_corrs)) if pair_corrs else float(features['residual_corr'].iloc[-1])

    # ③-B dispersion: 최근 20일 횡단면 std 평균
    avail_stocks = [s for s in ALL_STOCKS if s in stock_returns.columns]
    recent_ret = stock_returns[avail_stocks].iloc[-20:]
    disp_val = float(recent_ret.std(axis=1).mean())

    # ④ amihud: 최근 20일
    amihud_daily_vals = []
    for ticker, df_t in amihud_frames.items():
        recent_t = df_t.iloc[-20:]
        oc_ret = np.log(recent_t['Close'] / recent_t['Open']).abs()
        dollar_vol = recent_t['Close'] * recent_t['Volume']
        ami_t = oc_ret / dollar_vol.replace(0, np.nan)
        amihud_daily_vals.append(ami_t)
    amihud_recent = pd.concat(amihud_daily_vals, axis=1).mean(axis=1).dropna()
    log_ami = np.log(amihud_recent.mean() + 1e-15)
    ami_val = float(np.clip(log_ami, amihud_q01, amihud_q99))

    # ⑤ vix_term: 최신 일별
    latest_vix = float(fred_raw['vix']['vix'].dropna().iloc[-1])
    latest_vix3m = float(fred_raw['vix3m']['vix3m'].dropna().iloc[-1])
    vt_val = latest_vix / latest_vix3m

    # ⑥ hy_spread: 최신 일별
    hy_val = float(fred_raw['hy_spread']['hy_spread'].dropna().iloc[-1])

    # ⑦ realized_vol: 최근 20일 SPY
    spy_ret_recent = spy_ret.iloc[-20:]
    rv_val = float(spy_ret_recent.std() * np.sqrt(252))

    return np.array([[fg_val, ez_val, rc_val, disp_val, ami_val, vt_val, hy_val, rv_val]])


def fetch_noise_regime_light(model_bundle: dict, lookback_days: int = 60) -> np.ndarray:
    """경량 수집: 실시간 가능한 4피처는 Yahoo/FRED에서 재계산, 월별 4피처는 모델 번들에서 가져옴.

    실시간 피처: residual_corr, dispersion, amihud, realized_vol (Yahoo Finance)
    월별 피처(캐시): fundamental_gap, erp_zscore, vix_term, hy_spread (모델 저장 시 캐싱)

    Args:
        model_bundle: train_hmm()에서 저장한 모델 번들 (last_monthly_values 포함)
        lookback_days: 수집할 최근 일수 (기본 60일)

    Returns:
        np.ndarray shape (1, 8) — 8피처 벡터
    """
    # ── 모델 번들에서 월별 피처 캐시값 로드 ──
    monthly = model_bundle['last_monthly_values']        # 월별 4피처 최신값 딕셔너리
    fg_val = monthly['fundamental_gap']                  # 펀더멘털 갭
    ez_val = monthly['erp_zscore']                       # ERP Z-score
    vt_val_cached = monthly['vix_term']                  # VIX 텀 스트럭처 (캐시, FRED 실시간으로 덮어쓸 수 있음)
    hy_val_cached = monthly['hy_spread']                 # HY 스프레드 (캐시, FRED 실시간으로 덮어쓸 수 있음)
    amihud_q01 = model_bundle['amihud_q01']              # Amihud 윈저라이징 하한
    amihud_q99 = model_bundle['amihud_q99']              # Amihud 윈저라이징 상한

    period_str = f'{lookback_days}d'                     # yfinance 기간 문자열

    # ── ① SPY + 25 섹터 종목 일별 종가 수집 (실시간 반영) ──
    print('  [NoiseHMM-Light] SPY + 섹터 종목 수집...')
    all_tickers = ['SPY'] + ALL_STOCKS                   # SPY + 25개 섹터 종목
    frames = {}                                          # 티커별 종가 저장용
    for ticker in all_tickers:                           # 26개 티커 순회
        try:
            t = yf.Ticker(ticker)                        # yfinance 객체 생성
            hist = t.history(period=period_str, auto_adjust=True)  # 최근 N일 수집
            if len(hist) > 0:                            # 데이터가 있으면
                idx = hist.index                         # 인덱스 추출
                if hasattr(idx, 'tz') and idx.tz is not None:  # 타임존 있으면
                    idx = idx.tz_localize(None)          # 타임존 제거
                frames[ticker] = pd.Series(hist['Close'].values, index=idx, name=ticker)  # 종가 시리즈
        except Exception as e:
            print(f'    {ticker} 실패: {e}')             # 실패 로그

    stock_prices = pd.DataFrame(frames)                  # DataFrame으로 변환
    stock_returns = stock_prices.pct_change().dropna()   # 일별 수익률 계산

    # SPY 수익률 추출
    spy_ret = _strip_tz(stock_returns['SPY']) if 'SPY' in stock_returns.columns else None  # SPY 수익률

    # ── ② 베타 제거 잔차 계산 ──
    residuals = pd.DataFrame(index=stock_returns.index)  # 잔차 저장용 빈 DataFrame
    for ticker in ALL_STOCKS:                            # 25개 종목 순회
        if ticker not in stock_returns.columns or spy_ret is None:  # 데이터 없으면 건너뜀
            continue
        ret = stock_returns[ticker]                      # 종목 수익률
        cov_spy = ret.rolling(60, min_periods=20).cov(spy_ret)  # SPY와의 공분산 (min 20일)
        spy_var = spy_ret.rolling(60, min_periods=20).var()  # SPY 분산
        beta = cov_spy / spy_var                         # 베타 계산
        residuals[ticker] = ret - beta * spy_ret         # 잔차 = 수익률 - 베타*시장수익률
    residuals = residuals.dropna(how='all')              # 전부 NaN인 행 제거

    # ── ③-A residual_corr: 최근 20일 잔차 페어와이즈 상관 ──
    recent_resid = residuals.iloc[-20:]                  # 최근 20일 잔차
    pair_corrs = []                                      # 페어와이즈 상관 저장용
    for sector, stocks in SECTOR_STOCKS.items():         # 5개 섹터 순회
        avail = [s for s in stocks if s in recent_resid.columns]  # 사용 가능한 종목
        if len(avail) < 2:                               # 2개 미만이면 건너뜀
            continue
        for s1, s2 in combinations(avail, 2):            # 모든 쌍 조합
            c = recent_resid[s1].corr(recent_resid[s2])  # 상관계수 계산
            pair_corrs.append(c)                         # 리스트에 추가
    rc_val = float(np.mean(pair_corrs)) if pair_corrs else float(monthly.get('residual_corr_fallback', 0.0))  # 평균 또는 폴백

    # ── ③-B dispersion: 최근 20일 횡단면 std 평균 ──
    avail_stocks = [s for s in ALL_STOCKS if s in stock_returns.columns]  # 사용 가능한 종목
    recent_ret = stock_returns[avail_stocks].iloc[-20:]  # 최근 20일 수익률
    disp_val = float(recent_ret.std(axis=1).mean())      # 횡단면 표준편차 평균

    # ── ④ Amihud 종목 수집 + 계산 ──
    print('  [NoiseHMM-Light] Amihud 종목 수집...')
    amihud_daily_vals = []                               # Amihud 일별 값 저장용
    for ticker in AMIHUD_STOCKS:                         # 5개 메가캡 순회
        try:
            t = yf.Ticker(ticker)                        # yfinance 객체 생성
            hist = t.history(period=period_str, auto_adjust=True)  # 최근 N일 수집
            if len(hist) > 0:                            # 데이터가 있으면
                hist = _strip_tz_df(hist)                # 타임존 제거
                oc_ret = np.log(hist['Close'] / hist['Open']).abs()  # |log(종가/시가)|
                dollar_vol = hist['Close'] * hist['Volume']  # 달러 거래량
                ami_t = oc_ret / dollar_vol.replace(0, np.nan)  # Amihud 비유동성
                amihud_daily_vals.append(ami_t)          # 리스트에 추가
        except Exception as e:
            print(f'    Amihud {ticker} 실패: {e}')      # 실패 로그

    if amihud_daily_vals:                                # Amihud 데이터가 있으면
        amihud_recent = pd.concat(amihud_daily_vals, axis=1).mean(axis=1).dropna()  # 종목 평균
        log_ami = np.log(amihud_recent.iloc[-20:].mean() + 1e-15)  # 최근 20일 평균의 로그
        ami_val = float(np.clip(log_ami, amihud_q01, amihud_q99))  # 윈저라이징 적용
    else:
        ami_val = 0.0                                    # 폴백값

    # ── ⑤ Yahoo Finance 실시간: VIX, VIX3M ──
    print('  [NoiseHMM-Light] Yahoo VIX/VIX3M 수집...')
    try:
        vix_hist = yf.Ticker('^VIX').history(period='5d', auto_adjust=True)  # VIX 최근 5일
        vix3m_hist = yf.Ticker('^VIX3M').history(period='5d', auto_adjust=True)  # VIX3M 최근 5일
        latest_vix = float(vix_hist['Close'].dropna().iloc[-1])  # 최신 VIX 종가
        latest_vix3m = float(vix3m_hist['Close'].dropna().iloc[-1])  # 최신 VIX3M 종가
        vt_val = latest_vix / latest_vix3m               # VIX 텀 스트럭처 = VIX/VIX3M
    except Exception as e:
        print(f'    VIX term 실패, 캐시 사용: {e}')      # 실패 시 캐시 사용
        vt_val = vt_val_cached                           # 모델 번들의 캐시값

    # ── ⑤-B HY_OAS: 모델 번들 캐시값 사용 (경량 모드에서 FRED 호출 스킵)
    # FRED는 일별 업데이트이므로 10분 주기 호출 불필요, 캐시값으로 충분
    hy_val = hy_val_cached                               # 모델 번들의 캐시값 사용
    print(f'    HY spread: 캐시 사용 ({hy_val:.4f})')    # 캐시값 로그

    # ── ⑥ realized_vol: 최근 20일 SPY 수익률 기반 ──
    if spy_ret is not None and len(spy_ret) >= 20:       # SPY 데이터가 충분하면
        rv_val = float(spy_ret.iloc[-20:].std() * np.sqrt(252))  # 연율화 실현 변동성
    else:
        rv_val = float(monthly.get('realized_vol_fallback', 0.15))  # 폴백값

    # ── 윈저라이징 적용 ──
    winsor_bounds = model_bundle.get('winsor_bounds', {})  # 윈저라이징 범위 로드
    raw_values = [fg_val, ez_val, rc_val, disp_val, ami_val, vt_val, hy_val, rv_val]  # 8피처 원본값
    clipped_values = []                                  # 윈저라이징 적용 후 값
    for i, fname in enumerate(FEATURE_NAMES):            # 8피처 순회
        val = raw_values[i]                              # 원본값
        if fname in winsor_bounds:                       # 범위가 있으면
            q01, q99 = winsor_bounds[fname]              # 하한, 상한 추출
            val = float(np.clip(val, q01, q99))          # 클리핑 적용
        clipped_values.append(val)                       # 결과 추가

    feat_vector = np.array([clipped_values])             # (1, 8) shape 배열 생성
    print(f'  [NoiseHMM-Light] 8피처 벡터 생성 완료')    # 완료 로그
    return feat_vector                                   # 8피처 벡터 반환
