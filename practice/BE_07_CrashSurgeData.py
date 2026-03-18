# ============================================================
# BE_07_CrashSurgeData — XGBoost 폭락/급등 데이터 수집 + 44피처 빈칸 연습
# 원본: collector/crash_surge_data.py
# 총 빈칸: 55개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

import time
import warnings
from io import StringIO

import numpy as ___                                      # Q1: 수치 계산 모듈 별칭
import pandas as ___                                     # Q2: 데이터프레임 모듈 별칭
import requests
import yfinance as ___                                   # Q3: 야후 파이낸스 모듈 별칭

warnings.filterwarnings('ignore')

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
FRED_BASE = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id='

# Q4~Q11: FRED 8개 시리즈 매핑
FRED_MAP = {
    '___': 'HY_OAS',                                     # Q4: 하이일드 스프레드 FRED 시리즈 ID
    '___': 'BBB_OAS',                                    # Q5: BBB등급 스프레드 FRED 시리즈 ID
    '___':  'CCC_OAS',                                   # Q6: CCC등급 스프레드 FRED 시리즈 ID
    '___':       'DFII10',                               # Q7: 10년 실질금리 FRED 시리즈 ID (값과 동일)
    'T10YIE':       '___',                               # Q8: 10년 기대인플레이션 컬럼 별칭 (키와 동일)
    'SOFR':         '___',                               # Q9: 담보부 익일물 금리 컬럼 별칭 (키와 동일)
    'EFFR':         '___',                               # Q10: 실효 연방기금금리 컬럼 별칭 (키와 동일)
    'NFCI':         '___',                               # Q11: 금융환경지수 컬럼 별칭 (키와 동일)
}

# Q12~Q15: Yahoo Finance 매크로 매핑
YAHOO_MACRO_MAP = {
    '___':      'DGS10',                                 # Q12: 10년 국채수익률 Yahoo 티커
    '___':      'IRX_3M',                                # Q13: 3개월 국채수익률 Yahoo 티커
    '___':  'DTWEXBGS',                                  # Q14: 달러인덱스 Yahoo 티커
    '___':      'WTI',                                   # Q15: 원유 선물 Yahoo 티커
}

# Cboe 지수 매핑
CBOE_MAP = {'^VIX': '___', '^VIX3M': '___', '^VIX9D': '___', '^VVIX': '___', '^SKEW': '___'}  # Q16~Q20: 각 Cboe 티커의 컬럼 별칭 (^ 접두사 제거한 이름)

# 라벨 파라미터
FORWARD_WINDOW = ___                                     # Q21: 향후 수익률 관측 기간 (영업일 수)
CRASH_THRESHOLD = ___                                    # Q22: 폭락 판단 수익률 기준 (음수 소수)
SURGE_THRESHOLD = ___                                    # Q23: 급등 판단 수익률 기준 (양수 소수)


def fetch_crash_surge_raw(start: str = '___') -> dict:   # Q24: 데이터 수집 시작 날짜 (YYYY-MM-DD)
    """원시 데이터 수집: SPY OHLCV + FRED 8개 + Yahoo 4개 + Cboe 5개."""
    # 1) SPY OHLCV
    spy_raw = yf.Ticker('___').history(start=start, auto_adjust=True)  # Q25: S&P500 추종 ETF 티커명
    spy = _strip_tz(spy_raw)[['Open', 'High', 'Low', '___', '___']]    # Q26~Q27: 종가 컬럼명 / 거래량 컬럼명

    # 2) FRED 8개
    fred = {}
    for sid, col in FRED_MAP.___():                      # Q28: 딕셔너리의 키-값 쌍 순회 메서드
        try:
            fred[col] = _fetch_fred(sid, col)
        except Exception as e:
            fred[col] = pd.DataFrame({col: []}, index=pd.DatetimeIndex([]))

    # 3) Yahoo 매크로 4개
    yahoo_macro = {}
    for ticker, col in YAHOO_MACRO_MAP.items():
        yahoo_macro[col] = _fetch_yahoo_macro(ticker, col, ___=start)  # Q29: 시작 날짜 파라미터명

    # 4) Cboe 5개
    cboe = {}
    for ticker, col in CBOE_MAP.items():
        try:
            h = yf.Ticker(ticker).history(start=start, auto_adjust=True)
            h = _strip_tz(h)
            cboe[col] = h['___'].rename(col)             # Q30: 종가 컬럼명
        except Exception:
            cboe[col] = pd.Series(dtype=float, name=col)

    return {'spy': spy, 'fred': fred, '___': cboe, '___': yahoo_macro}  # Q31~Q32: Cboe 데이터 딕셔너리 키명 / Yahoo 매크로 데이터 딕셔너리 키명


def compute_features(spy, fred, cboe, yahoo_macro=None) -> pd.DataFrame:
    """44 피처 DataFrame 생성."""
    if yahoo_macro is None:
        yahoo_macro = {}

    close = spy['___']                                   # Q33: 종가 컬럼명
    high = spy['High']
    low = spy['Low']
    opn = spy['Open']
    vol = spy['___']                                     # Q34: 거래량 컬럼명

    feat = pd.DataFrame(index=spy.index)

    # ── 가격/수익률/추세 (8개) ──
    for n in [1, 5, 10, 20]:
        feat[f'SP500_LOGRET_{n}D'] = np.___(close / close.shift(n))  # Q35: 로그 수익률 계산용 수학 함수

    feat['SP500_DRAWDOWN_60D'] = close / close.rolling(___).max() - 1  # Q36: 드로다운 관측 기간 (피처명에 힌트)
    feat['SP500_MA_GAP_50'] = close / close.rolling(___).mean() - 1    # Q37: 이동평균 기간 (피처명에 힌트)
    feat['SP500_MA_GAP_200'] = close / close.rolling(___).mean() - 1   # Q38: 이동평균 기간 (피처명에 힌트)
    feat['SP500_INTRADAY_RANGE'] = (high - ___) / close                # Q39: 일중 범위 하단 가격 변수

    # ── 실현변동성 (4개) ──
    daily_ret = np.log(close / close.shift(___))         # Q40: 전일 대비 시프트 일수
    feat['RV_5D'] = daily_ret.rolling(5).___() * np.sqrt(252)   # Q41: 표준편차 계산 메서드
    feat['RV_21D'] = daily_ret.rolling(___).std() * np.sqrt(252) # Q42: 약 1개월 영업일 수

    # EWMA λ=0.94
    lam = ___                                            # Q43: EWMA 감쇠 계수 (람다 값)
    ewma_var = daily_ret.copy() * 0
    ewma_var.iloc[0] = daily_ret.iloc[:21].___()         # Q44: 초기 분산값 계산 메서드
    for i in range(1, len(daily_ret)):
        ewma_var.iloc[i] = lam * ewma_var.iloc[i - 1] + (1 - lam) * daily_ret.iloc[i] ** ___  # Q45: 분산 계산을 위한 거듭제곱 지수
    feat['EWMA_VOL_L94'] = np.sqrt(ewma_var) * np.sqrt(___)  # Q46: 연간화 환산 영업일 수

    # ── 신용 (3개) — FRED ──
    for col in ['HY_OAS', '___', '___']:                 # Q47~Q48: 나머지 두 신용 스프레드 컬럼명 (등급명_OAS)
        feat[col] = fred[col][col].reindex(spy.index).___()  # Q49: 결측값을 직전 값으로 채우는 메서드

    # ── 금리 (2개) — Yahoo ──
    dgs10_s = yahoo_macro.get('___', pd.Series(dtype=float))  # Q50: 10년 국채수익률 컬럼명
    irx_s = yahoo_macro.get('___', pd.Series(dtype=float))     # Q51: 3개월 국채수익률 컬럼명
    feat['DGS10_LEVEL'] = dgs10_s.reindex(spy.index).ffill()
    feat['T10Y3M_SLOPE'] = (dgs10_s.reindex(spy.index).ffill()
                            - irx_s.reindex(spy.index).ffill())

    return feat


def compute_labels(close: pd.Series) -> pd.Series:
    """3클래스 라벨 생성: 0=정상, 1=폭락전조, 2=급등전조."""
    fwd_ret_20d = close.pct_change(___).shift(-FORWARD_WINDOW)  # Q52: 수익률 관측 기간 상수

    crash_dates = fwd_ret_20d[fwd_ret_20d <= ___].index  # Q53: 폭락 기준값 상수
    surge_dates = fwd_ret_20d[fwd_ret_20d >= ___].index  # Q54: 급등 기준값 상수

    label = pd.Series(___, index=close.index, name='label')  # Q55: 정상 상태 기본 라벨값

    # 급등 먼저 (폭락이 나중에 덮어씀 → 폭락 우선)
    for dt in surge_dates:
        loc = close.index.get_loc(dt)
        start = max(0, loc - FORWARD_WINDOW)
        label.iloc[start:loc + 1] = ___                  # Q56: 급등 전조 라벨값

    for dt in crash_dates:
        loc = close.index.get_loc(dt)
        start = max(0, loc - FORWARD_WINDOW)
        label.iloc[start:loc + 1] = ___                  # Q57: 폭락 전조 라벨값

    return label


# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                    |
# |----|-------------------------------|------------------------|
# | Q1 | as ___                        | np                     |
# | Q2 | as ___                        | pd                     |
# | Q3 | as ___                        | yf                     |
# | Q4 | '___'                         | BAMLH0A0HYM2           |
# | Q5 | '___'                         | BAMLC0A4CBBB           |
# | Q6 | '___'                         | BAMLH0A3HYC            |
# | Q7 | '___'                         | DFII10                 |
# | Q8 | '___'                         | T10YIE                 |
# | Q9 | '___'                         | SOFR                   |
# | Q10| '___'                         | EFFR                   |
# | Q11| '___'                         | NFCI                   |
# | Q12| '___'                         | ^TNX                   |
# | Q13| '___'                         | ^IRX                   |
# | Q14| '___'                         | DX-Y.NYB               |
# | Q15| '___'                         | CL=F                   |
# | Q16| '___'                         | VIX                    |
# | Q17| '___'                         | VIX3M                  |
# | Q18| '___'                         | VIX9D                  |
# | Q19| '___'                         | VVIX                   |
# | Q20| '___'                         | SKEW                   |
# | Q21| FORWARD_WINDOW = ___          | 20                     |
# | Q22| CRASH_THRESHOLD = ___         | -0.10                  |
# | Q23| SURGE_THRESHOLD = ___         | 0.10                   |
# | Q24| start = '___'                 | 2000-01-01             |
# | Q25| Ticker('___')                 | SPY                    |
# | Q26| '___'                         | Close                  |
# | Q27| '___'                         | Volume                 |
# | Q28| .___()                        | items                  |
# | Q29| ___=start                     | start                  |
# | Q30| h['___']                      | Close                  |
# | Q31| '___': cboe                   | cboe                   |
# | Q32| '___': yahoo_macro            | yahoo_macro            |
# | Q33| spy['___']                    | Close                  |
# | Q34| spy['___']                    | Volume                 |
# | Q35| np.___                        | log                    |
# | Q36| .rolling(___)                 | 60                     |
# | Q37| .rolling(___)                 | 50                     |
# | Q38| .rolling(___)                 | 200                    |
# | Q39| high - ___                    | low                    |
# | Q40| .shift(___)                   | 1                      |
# | Q41| .___()                        | std                    |
# | Q42| .rolling(___)                 | 21                     |
# | Q43| lam = ___                     | 0.94                   |
# | Q44| .___()                        | var                    |
# | Q45| ** ___                        | 2                      |
# | Q46| np.sqrt(___)                  | 252                    |
# | Q47| '___'                         | BBB_OAS                |
# | Q48| '___'                         | CCC_OAS                |
# | Q49| .___()                        | ffill                  |
# | Q50| '___'                         | DGS10                  |
# | Q51| '___'                         | IRX_3M                 |
# | Q52| .pct_change(___)              | FORWARD_WINDOW         |
# | Q53| <= ___                        | CRASH_THRESHOLD        |
# | Q54| >= ___                        | SURGE_THRESHOLD        |
# | Q55| pd.Series(___,...)            | 0                      |
# | Q56| = ___                         | 2                      |
# | Q57| = ___                         | 1                      |
# ============================================================
