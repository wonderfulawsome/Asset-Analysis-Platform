"""XGBoost Crash/Surge: 데이터 수집 + 44 피처 엔지니어링

노트북 XGBoost_CrashSurge.ipynb Cell 1~3 로직을 production 코드로 변환.
44개 일별 피처: 가격/변동성/옵션/신용/금리/크로스에셋/Tier2 보조
"""

import time
import warnings
from io import StringIO

import numpy as np
import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings('ignore')

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
FRED_BASE = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id='

# FRED 8개 시리즈 (Yahoo로 대체 불가능한 것만 유지)
FRED_MAP = {
    'BAMLH0A0HYM2': 'HY_OAS',   # HY 신용스프레드 (FRED 전용)
    'BAMLC0A4CBBB': 'BBB_OAS',   # BBB 신용스프레드 (FRED 전용)
    'BAMLH0A3HYC':  'CCC_OAS',   # CCC 신용스프레드 (FRED 전용)
    'DFII10':       'DFII10',    # 10년 TIPS 실질금리 (FRED 전용)
    'T10YIE':       'T10YIE',    # 10년 기대인플레 (FRED 전용)
    'SOFR':         'SOFR',      # SOFR 금리 (FRED 전용)
    'EFFR':         'EFFR',      # EFFR 금리 (FRED 전용)
    'NFCI':         'NFCI',      # 금융여건지수 (FRED 전용)
}

# Yahoo Finance로 대체한 시리즈 (기존 FRED DGS10, T10Y3M, DCOILWTICO)
# DX-Y.NYB(달러인덱스)는 Yahoo 500 에러로 제거 — DTWEXBGS_RET_5D는 0으로 채움
YAHOO_MACRO_MAP = {
    '^TNX':      'DGS10',      # 10년 국채금리 (FRED DGS10 대체)
    '^IRX':      'IRX_3M',     # 3개월 국채금리 (T10Y3M 계산용)
    'CL=F':      'WTI',        # WTI 원유선물 (FRED DCOILWTICO 대체)
}

# Cboe 지수
CBOE_MAP = {'^VIX': 'VIX', '^VIX3M': 'VIX3M', '^VIX9D': 'VIX9D', '^VVIX': 'VVIX', '^SKEW': 'SKEW'}

# ── 피처 목록 ──
CORE_FEATURES = [
    'SP500_LOGRET_1D', 'SP500_LOGRET_5D', 'SP500_LOGRET_10D', 'SP500_LOGRET_20D',
    'SP500_DRAWDOWN_60D', 'SP500_MA_GAP_50', 'SP500_MA_GAP_200', 'SP500_INTRADAY_RANGE',
    'RV_5D', 'RV_21D', 'EWMA_VOL_L94', 'VOL_OF_VOL_21D',
    'HY_OAS', 'BBB_OAS', 'CCC_OAS',
    'DGS10_LEVEL', 'T10Y3M_SLOPE',
]

AUX_FEATURES = [
    'VIX_LEVEL', 'VIX_CHANGE_1D', 'VIX_PCTL_252D',
    'VXV_MINUS_VIX', 'SKEW_LEVEL',
    'DTWEXBGS_RET_5D', 'WTI_RET_5D',
    'VIX9D_MINUS_VIX', 'VVIX_LEVEL',
    'VARIANCE_RISK_PREMIUM', 'PARKINSON_VOL_21D',
    'SP500_AMIHUD_ILLIQ_20D', 'SP500_DOLLAR_VOLUME_Z_20D',
    'DFII10_REAL10Y', 'T10YIE_BREAKEVEN',
    'SOFR_MINUS_EFFR', 'NFCI_LEVEL', 'CORR_EQ_DGS10_60D',
    'HY_OAS_CHG_5D', 'HY_OAS_CHG_20D',
    'BBB_OAS_CHG_5D', 'BBB_OAS_CHG_20D',
    'CCC_OAS_CHG_5D', 'CCC_OAS_CHG_20D',
    'VIX9D_VIX_RATIO', 'VIX_VIX3M_RATIO', 'VIX_CHG_5D',
]

ALL_FEATURES = CORE_FEATURES + AUX_FEATURES

# 라벨 파라미터
FORWARD_WINDOW = 20
CRASH_THRESHOLD = -0.10
SURGE_THRESHOLD = 0.10


# ── 헬퍼 ──

def _fetch_fred(series_id: str, col_name: str, retries: int = 4, timeout: int = 30) -> pd.DataFrame:
    """FRED CSV 다운로드 (지수 백오프 재시도)."""
    url = FRED_BASE + series_id
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            df = pd.read_csv(StringIO(resp.text), index_col=0, parse_dates=True)
            df.columns = [col_name]
            df[col_name] = pd.to_numeric(df[col_name], errors='coerce')
            return df
        except Exception:
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f'  [{series_id}] 재시도 {attempt+1}/{retries} ({wait}초 대기)...')
                time.sleep(wait)
            else:
                raise


def _strip_tz(obj):
    """타임존 제거 (Series / DataFrame)."""
    obj = obj.copy()
    if hasattr(obj.index, 'tz') and obj.index.tz is not None:
        obj.index = obj.index.tz_localize(None)
    return obj


def _fetch_yahoo_macro(ticker: str, col_name: str, start: str = None,
                       period: str = None) -> pd.Series:
    """Yahoo Finance에서 매크로 시리즈 수집 (종가 기준)."""
    try:
        if start:  # 전체 수집 (fetch_crash_surge_raw)
            h = yf.Ticker(ticker).history(start=start, auto_adjust=True)
        else:  # 경량 수집 (fetch_crash_surge_light)
            h = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        h = _strip_tz(h)  # 타임존 제거
        s = h['Close'].rename(col_name)  # 종가만 추출
        s = s[~s.index.duplicated(keep='last')]  # 중복 인덱스 제거
        return s
    except Exception as e:
        print(f'  [Yahoo] {ticker}({col_name}): 실패 — {e}')
        return pd.Series(dtype=float, name=col_name)  # 빈 Series 반환


# ── 데이터 수집 ──

def fetch_crash_surge_raw(start: str = '2000-01-01') -> dict:
    """원시 데이터 수집: SPY OHLCV + FRED 8개 + Yahoo 매크로 4개 + Cboe 5개.

    Returns:
        {'spy': DataFrame, 'fred': dict, 'cboe': dict, 'yahoo_macro': dict}
    """
    # 1) SPY OHLCV
    print('  [CrashSurge] SPY OHLCV 수집...')
    spy_raw = yf.Ticker('SPY').history(start=start, auto_adjust=True)
    spy = _strip_tz(spy_raw)[['Open', 'High', 'Low', 'Close', 'Volume']]
    print(f'  [CrashSurge] SPY: {spy.index[0].date()} ~ {spy.index[-1].date()} ({len(spy)}행)')

    # 2) FRED 8개 (신용스프레드, 실질금리, 기대인플레, SOFR, EFFR, NFCI)
    fred = {}
    print('  [CrashSurge] FRED 시리즈 수집...')
    for sid, col in FRED_MAP.items():
        try:
            fred[col] = _fetch_fred(sid, col)
        except Exception as e:
            print(f'  [CrashSurge] {col}: 실패 — {e}')
            fred[col] = pd.DataFrame({col: []}, index=pd.DatetimeIndex([]))

    # 3) Yahoo 매크로 4개 (금리, 달러, 원유 — FRED 대체)
    yahoo_macro = {}  # Yahoo 매크로 시리즈 저장용
    print('  [CrashSurge] Yahoo 매크로 수집...')
    for ticker, col in YAHOO_MACRO_MAP.items():  # ^TNX, ^IRX, CL=F
        yahoo_macro[col] = _fetch_yahoo_macro(ticker, col, start=start)  # 전체 기간 수집

    # 4) Cboe 5개
    cboe = {}
    print('  [CrashSurge] Cboe 지수 수집...')
    for ticker, col in CBOE_MAP.items():
        try:
            h = yf.Ticker(ticker).history(start=start, auto_adjust=True)
            h = _strip_tz(h)
            cboe[col] = h['Close'].rename(col)
        except Exception as e:
            print(f'  [CrashSurge] {col}: 실패 — {e}')
            cboe[col] = pd.Series(dtype=float, name=col)

    return {'spy': spy, 'fred': fred, 'cboe': cboe, 'yahoo_macro': yahoo_macro}


def fetch_crash_surge_light(lookback_days: int = 300) -> dict:
    """경량 수집: 최근 N일치만 빠르게 가져옴 (30분 주기 예측용).
    yfinance 장 중 호출 시 SPY/Cboe/Yahoo매크로는 실시간 데이터 포함.
    FRED는 일별 업데이트만 가능하므로 최신 확정값 사용.
    """
    # 1) SPY OHLCV — 장 중이면 실시간 가격 포함
    print('  [CrashSurge-Light] SPY OHLCV 수집...')
    spy_raw = yf.Ticker('SPY').history(period=f'{lookback_days}d', auto_adjust=True)  # 최근 N일
    spy = _strip_tz(spy_raw)[['Open', 'High', 'Low', 'Close', 'Volume']]  # OHLCV만 추출

    # 2) FRED 8개 — 일별 확정값 (실시간 불가)
    fred = {}  # FRED 시리즈 저장용
    print('  [CrashSurge-Light] FRED 시리즈 수집...')
    for sid, col in FRED_MAP.items():  # 8개 시리즈 순회
        try:
            fred[col] = _fetch_fred(sid, col)  # CSV 다운로드
        except Exception as e:
            print(f'  [CrashSurge-Light] {col}: 실패 — {e}')
            fred[col] = pd.DataFrame({col: []}, index=pd.DatetimeIndex([]))  # 빈 DataFrame

    # 3) Yahoo 매크로 4개 — 장 중이면 실시간 가격 포함
    yahoo_macro = {}  # Yahoo 매크로 시리즈 저장용
    print('  [CrashSurge-Light] Yahoo 매크로 수집...')
    for ticker, col in YAHOO_MACRO_MAP.items():  # ^TNX, ^IRX, CL=F
        yahoo_macro[col] = _fetch_yahoo_macro(ticker, col, period=f'{lookback_days}d')  # 최근 N일

    # 4) Cboe 5개 — 장 중이면 실시간 가격 포함
    cboe = {}  # Cboe 지수 저장용
    print('  [CrashSurge-Light] Cboe 지수 수집...')
    for ticker, col in CBOE_MAP.items():  # VIX, VIX3M, VIX9D, VVIX, SKEW
        try:
            h = yf.Ticker(ticker).history(period=f'{lookback_days}d', auto_adjust=True)  # 최근 N일
            h = _strip_tz(h)  # 타임존 제거
            cboe[col] = h['Close'].rename(col)  # 종가만 추출
        except Exception as e:
            print(f'  [CrashSurge-Light] {col}: 실패 — {e}')
            cboe[col] = pd.Series(dtype=float, name=col)  # 빈 Series

    print(f'  [CrashSurge-Light] SPY: {len(spy)}행, 실시간 데이터 포함')
    return {'spy': spy, 'fred': fred, 'cboe': cboe, 'yahoo_macro': yahoo_macro}  # 전체 데이터 반환


# ── 피처 엔지니어링 ──

def compute_features(spy: pd.DataFrame, fred: dict, cboe: dict,
                     yahoo_macro: dict = None) -> pd.DataFrame:
    """44 피처 DataFrame 생성 (SPY index 기준, 일별).

    Args:
        spy: SPY OHLCV DataFrame
        fred: FRED 시리즈 dict (8개)
        cboe: Cboe 지수 dict (5개)
        yahoo_macro: Yahoo 매크로 dict (4개: DGS10, IRX_3M, DTWEXBGS, WTI)
    """
    if yahoo_macro is None:  # 하위호환성 (기존 호출부 보호)
        yahoo_macro = {}

    close = spy['Close']
    high = spy['High']
    low = spy['Low']
    opn = spy['Open']
    vol = spy['Volume']

    feat = pd.DataFrame(index=spy.index)

    # ── 가격/수익률/추세 (8개) ──
    for n in [1, 5, 10, 20]:
        feat[f'SP500_LOGRET_{n}D'] = np.log(close / close.shift(n))
    feat['SP500_DRAWDOWN_60D'] = close / close.rolling(60).max() - 1
    feat['SP500_MA_GAP_50'] = close / close.rolling(50).mean() - 1
    feat['SP500_MA_GAP_200'] = close / close.rolling(200).mean() - 1
    feat['SP500_INTRADAY_RANGE'] = (high - low) / close

    # ── 실현변동성 (4개) ──
    daily_ret = np.log(close / close.shift(1))
    feat['RV_5D'] = daily_ret.rolling(5).std() * np.sqrt(252)
    feat['RV_21D'] = daily_ret.rolling(21).std() * np.sqrt(252)

    # EWMA λ=0.94
    lam = 0.94
    ewma_var = daily_ret.copy() * 0
    ewma_var.iloc[0] = daily_ret.iloc[:21].var()
    for i in range(1, len(daily_ret)):
        ewma_var.iloc[i] = lam * ewma_var.iloc[i - 1] + (1 - lam) * daily_ret.iloc[i] ** 2
    feat['EWMA_VOL_L94'] = np.sqrt(ewma_var) * np.sqrt(252)
    feat['VOL_OF_VOL_21D'] = feat['RV_5D'].rolling(21).std()

    # ── 옵션/내재변동성 (5개) ──
    vix_s = cboe.get('VIX', pd.Series(dtype=float))
    feat['VIX_LEVEL'] = np.log(vix_s.reindex(spy.index).ffill().clip(lower=1))
    feat['VIX_CHANGE_1D'] = vix_s.reindex(spy.index).ffill().pct_change(1)
    feat['VIX_PCTL_252D'] = vix_s.reindex(spy.index).ffill().rolling(252).apply(
        lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
    )

    vix3m_s = cboe.get('VIX3M', pd.Series(dtype=float))
    feat['VXV_MINUS_VIX'] = vix3m_s.reindex(spy.index).ffill() - vix_s.reindex(spy.index).ffill()

    skew_s = cboe.get('SKEW', pd.Series(dtype=float))
    feat['SKEW_LEVEL'] = skew_s.reindex(spy.index).ffill()

    # ── 신용 (3개) — FRED 전용 ──
    for col in ['HY_OAS', 'BBB_OAS', 'CCC_OAS']:
        feat[col] = fred[col][col].reindex(spy.index).ffill()

    # ── 금리 (2개) — Yahoo ^TNX, ^IRX 사용 ──
    dgs10_s = yahoo_macro.get('DGS10', pd.Series(dtype=float))  # ^TNX (10년 금리)
    irx_s = yahoo_macro.get('IRX_3M', pd.Series(dtype=float))   # ^IRX (3개월 금리)
    feat['DGS10_LEVEL'] = dgs10_s.reindex(spy.index).ffill()    # 10년 국채금리
    # T10Y3M = 10년 금리 - 3개월 금리 (수익률곡선 기울기)
    feat['T10Y3M_SLOPE'] = (dgs10_s.reindex(spy.index).ffill()
                            - irx_s.reindex(spy.index).ffill())

    # ── 크로스에셋 (2개) — DX-Y.NYB 제거, CL=F 사용 ──
    dxy_s = yahoo_macro.get('DTWEXBGS', pd.Series(dtype=float))  # 달러인덱스 (DX-Y.NYB 제거됨)
    if dxy_s.empty:                                                # DX-Y.NYB 미수집 시
        feat['DTWEXBGS_RET_5D'] = 0.0                             # 0으로 채움 (피처 순서 유지)
    else:                                                          # 혹시 복구되면 정상 계산
        dxy_ff = dxy_s.reindex(spy.index).ffill()                  # 영업일 기준 정렬
        feat['DTWEXBGS_RET_5D'] = np.log(dxy_ff / dxy_ff.shift(5))  # 달러 5일 수익률

    wti_s = yahoo_macro.get('WTI', pd.Series(dtype=float))  # CL=F (WTI 원유)
    wti_ff = wti_s.reindex(spy.index).ffill()
    feat['WTI_RET_5D'] = np.log(wti_ff / wti_ff.shift(5))  # WTI 5일 수익률

    # ── Tier 2 보조 ──
    vix9d_s = cboe.get('VIX9D', pd.Series(dtype=float))
    feat['VIX9D_MINUS_VIX'] = vix9d_s.reindex(spy.index).ffill() - vix_s.reindex(spy.index).ffill()

    vvix_s = cboe.get('VVIX', pd.Series(dtype=float))
    feat['VVIX_LEVEL'] = vvix_s.reindex(spy.index).ffill()

    vix_ann = (vix_s.reindex(spy.index).ffill() / 100)
    feat['VARIANCE_RISK_PREMIUM'] = vix_ann ** 2 - (feat['RV_21D'] / np.sqrt(252)) ** 2 * 252

    feat['PARKINSON_VOL_21D'] = np.sqrt(
        (np.log(high / low) ** 2 / (4 * np.log(2))).rolling(21).mean() * 252
    )

    oc_ret = np.log(close / opn).abs()
    dollar_vol = close * vol
    amihud_daily = oc_ret / dollar_vol.replace(0, np.nan)
    feat['SP500_AMIHUD_ILLIQ_20D'] = np.log(amihud_daily.rolling(20).mean() + 1e-15)

    dv = close * vol
    dv_mean = dv.rolling(20).mean()
    dv_std = dv.rolling(20).std()
    feat['SP500_DOLLAR_VOLUME_Z_20D'] = (dv - dv_mean) / dv_std.replace(0, np.nan)

    feat['DFII10_REAL10Y'] = fred['DFII10']['DFII10'].reindex(spy.index).ffill()  # FRED 전용
    feat['T10YIE_BREAKEVEN'] = fred['T10YIE']['T10YIE'].reindex(spy.index).ffill()  # FRED 전용

    sofr_s = fred['SOFR']['SOFR'].reindex(spy.index).ffill()  # FRED 전용
    effr_s = fred['EFFR']['EFFR'].reindex(spy.index).ffill()  # FRED 전용
    feat['SOFR_MINUS_EFFR'] = sofr_s - effr_s

    nfci_s = fred['NFCI']['NFCI'].reindex(spy.index).ffill()  # FRED 전용
    feat['NFCI_LEVEL'] = nfci_s

    # CORR_EQ_DGS10_60D — Yahoo ^TNX 사용
    dgs10_chg = dgs10_s.reindex(spy.index).ffill().diff()  # 10년 금리 일변화
    feat['CORR_EQ_DGS10_60D'] = daily_ret.rolling(60).corr(dgs10_chg)  # 주식-금리 상관관계

    # ── v2: 크레딧 스프레드 변화율 (6개) — FRED 전용 ──
    for col in ['HY_OAS', 'BBB_OAS', 'CCC_OAS']:
        s = fred[col][col].reindex(spy.index).ffill()
        feat[f'{col}_CHG_5D'] = s.diff(5)
        feat[f'{col}_CHG_20D'] = s.diff(20)

    # ── v2: VIX 텀스트럭처 (3개) ──
    vix_ff = vix_s.reindex(spy.index).ffill()
    vix3m_ff = vix3m_s.reindex(spy.index).ffill()
    vix9d_ff = vix9d_s.reindex(spy.index).ffill()
    feat['VIX9D_VIX_RATIO'] = vix9d_ff / vix_ff.clip(lower=1)
    feat['VIX_VIX3M_RATIO'] = vix_ff / vix3m_ff.clip(lower=1)
    feat['VIX_CHG_5D'] = vix_ff.pct_change(5)

    return feat


# ── 라벨 생성 ──

def compute_labels(close: pd.Series) -> pd.Series:
    """3클래스 라벨 생성: 0=정상, 1=폭락전조, 2=급등전조."""
    fwd_ret_20d = close.pct_change(FORWARD_WINDOW).shift(-FORWARD_WINDOW)

    crash_dates = fwd_ret_20d[fwd_ret_20d <= CRASH_THRESHOLD].index
    surge_dates = fwd_ret_20d[fwd_ret_20d >= SURGE_THRESHOLD].index

    label = pd.Series(0, index=close.index, name='label')

    # 급등 먼저 (폭락이 나중에 덮어씀 → 폭락 우선)
    for dt in surge_dates:
        loc = close.index.get_loc(dt)
        start = max(0, loc - FORWARD_WINDOW)
        label.iloc[start:loc + 1] = 2

    for dt in crash_dates:
        loc = close.index.get_loc(dt)
        start = max(0, loc - FORWARD_WINDOW)
        label.iloc[start:loc + 1] = 1

    return label


# ── 데이터셋 준비 ──

def prepare_datasets(features: pd.DataFrame, labels: pd.Series, close: pd.Series) -> dict:
    """학습/캘리브레이션/테스트/추론 데이터셋 준비.

    Returns:
        {
            'df_full': DataFrame (추론용, 최신일까지),
            'train': (X, y),
            'calib': (X, y),
            'test': (X, y),
            'dev': (X, y),
        }
    """
    df_full = features[ALL_FEATURES].copy()
    df_full['label'] = labels

    # Core NaN 제거, Aux fillna(0)
    df_full = df_full.dropna(subset=CORE_FEATURES)
    df_full[AUX_FEATURES] = df_full[AUX_FEATURES].fillna(0)
    df_full = df_full.replace([np.inf, -np.inf], np.nan).dropna(subset=ALL_FEATURES)

    # 학습용: 라벨 유효 구간 (최근 20일 제외)
    df = df_full[df_full.index <= close.index[-FORWARD_WINDOW - 1]].copy()

    if len(df) == 0:
        raise ValueError('데이터가 비어있습니다.')

    # 3분할
    holdout_days = min(504, len(df) - 100)
    calib_days = min(1008, len(df) - holdout_days - 100)

    test_df = df.iloc[-holdout_days:]
    calib_df = df.iloc[-(holdout_days + calib_days):-holdout_days]
    train_df = df.iloc[:-(holdout_days + calib_days)]
    dev_df = df.iloc[:-holdout_days]

    print(f'  [CrashSurge] 학습: {len(train_df)}, 캘리브: {len(calib_df)}, '
          f'테스트: {len(test_df)}, 추론: {len(df_full)}')

    return {
        'df_full': df_full,
        'train': (train_df[ALL_FEATURES].values, train_df['label'].values),
        'calib': (calib_df[ALL_FEATURES].values, calib_df['label'].values),
        'test': (test_df[ALL_FEATURES].values, test_df['label'].values),
        'dev': (dev_df[ALL_FEATURES].values, dev_df['label'].values),
    }
