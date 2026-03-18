# ============================================================
# BE_06_NoiseRegimeData — Noise HMM 데이터 수집 + 8피처 엔지니어링 빈칸 연습
# 원본: collector/noise_regime_data.py
# 총 빈칸: 55개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

import datetime
import time
import warnings
from itertools import ___                                # Q1: 주어진 요소에서 조합을 생성하는 함수
from io import ___                                       # Q2: 문자열을 파일처럼 읽는 클래스

import numpy as ___                                      # Q3: numpy 관례적 별칭
import pandas as ___                                     # Q4: pandas 관례적 별칭
import requests
import yfinance as ___                                   # Q5: yfinance 관례적 별칭

warnings.filterwarnings('ignore')

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
FRED_BASE = '___'                                        # Q6: FRED CSV 다운로드 전체 URL (시리즈 ID 앞부분)
SHILLER_URL = '___'                                      # Q7: Shiller 교수의 ie_data 엑셀 파일 URL

# Q8: 섹터별 대표 종목 딕셔너리
SECTOR_STOCKS = {
    '___': ['AAPL', 'MSFT', 'NVDA', 'AVGO', 'CRM'],     # Q8: 기술 섹터 ETF 티커
    '___': ['JPM', 'BAC', 'WFC', 'GS', 'MS'],            # Q9: 금융 섹터 ETF 티커
    '___': ['XOM', 'CVX', 'COP', 'SLB', 'EOG'],          # Q10: 에너지 섹터 ETF 티커
    'XLV': ['UNH', 'JNJ', 'LLY', 'PFE', 'ABT'],
    'XLI': ['CAT', 'HON', 'UNP', 'GE', 'RTX'],
}
ALL_STOCKS = [s for stocks in SECTOR_STOCKS.___() for s in stocks]  # Q11: 딕셔너리의 값 목록만 반환하는 메서드

# Q12: Amihud 비유동성 측정 대상 종목
AMIHUD_STOCKS = ['AAPL', 'MSFT', '___', '___', '___']    # Q12~Q14: 대형 기술주 3종목 티커 (전자상거래·검색·SNS 대표 기업)

# Q15: 8개 피처 이름 리스트
FEATURE_NAMES = [
    '___', '___', 'residual_corr',                       # Q15~Q16: 펀더멘털 괴리도 피처명, ERP Z점수 피처명
    '___', '___', '___', '___',                          # Q17~Q20: 수익률 분산 피처명, 비유동성 피처명, VIX 기간구조 피처명, 하이일드 스프레드 피처명
    '___',                                               # Q21: 실현 변동성 피처명
]

# FRED 시리즈 ID
FRED_SERIES = {
    '___': 'tips_rate',                                  # Q22: 10년 TIPS 실질금리 FRED 시리즈 ID
    '___': 'hy_spread',                                  # Q23: 하이일드 채권 스프레드 FRED 시리즈 ID
}

# Yahoo Finance 변동성 지수
YAHOO_VOL_TICKERS = {
    '___': 'vix',                                        # Q24: CBOE 변동성 지수 Yahoo Finance 티커
    '___': 'vix3m',                                      # Q25: CBOE 3개월 변동성 지수 Yahoo Finance 티커
}


def _fetch_fred(series_id: str, col_name: str, retries: int = 4, timeout: int = 30) -> pd.DataFrame:
    """FRED CSV 다운로드 (지수 백오프 재시도)."""
    url = FRED_BASE + series_id
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.___()                                   # Q26: HTTP 응답 상태 코드가 에러이면 예외를 발생시키는 메서드
            df = pd.read_csv(StringIO(resp.text), index_col=0, parse_dates=True)
            df.columns = [col_name]
            df[col_name] = pd.to_numeric(df[col_name], errors='coerce')
            return df
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def _strip_tz(s: pd.Series) -> pd.Series:
    """타임존 제거."""
    s = s.copy()
    if hasattr(s.index, '___') and s.index.tz is not None:  # Q27: 타임존 속성 이름
        s.index = s.index.tz_localize(___)               # Q28: 타임존을 제거하기 위해 전달하는 값
    return s


def fetch_shiller() -> pd.DataFrame:
    """Shiller ie_data.xls에서 P, E, CAPE 월별 DataFrame 반환."""
    shiller = pd.read_excel(SHILLER_URL, sheet_name='___', skiprows=7, header=0)  # Q29: 엑셀 시트 이름
    # ... (파싱 로직 생략 — 핵심 피처 엔지니어링에 집중)
    return shiller[['P', 'E', '___']]                    # Q30: 경기 조정 주가수익비율 컬럼명


def fetch_fred_regime() -> dict:
    """FRED 2개 + Yahoo 2개 수집 → dict 반환."""
    result = {}
    for series_id, col_name in FRED_SERIES.items():
        df = _fetch_fred(series_id, col_name)
        result[col_name] = df
    for ticker, col_name in YAHOO_VOL_TICKERS.items():
        df = _fetch_yahoo_daily(ticker)
        result[___] = df                                 # Q31: 딕셔너리 키로 사용할 컬럼명 변수
    return result


def fetch_sector_stocks(start_date: str) -> pd.DataFrame:
    """25 섹터 종목 + SPY 일별 종가 수집."""
    frames = {}
    for ticker in ['___'] + ALL_STOCKS:                  # Q32: 시장 벤치마크 지수 ETF 티커
        try:
            t = yf.Ticker(ticker)
            hist = t.history(start=start_date, ___=True)  # Q33: 분할·배당 자동 조정 옵션 매개변수명
            if len(hist) > 0:
                idx = hist.index
                if hasattr(idx, 'tz') and idx.tz is not None:
                    idx = idx.tz_localize(None)
                frames[ticker] = pd.Series(hist['___'].values, index=idx, name=ticker)  # Q34: 종가 컬럼명
        except Exception as e:
            print(f'  {ticker} 실패: {e}')
    return pd.DataFrame(frames)


def compute_monthly_features(shiller, fred, stock_prices, amihud_data) -> dict:
    """8개 월별 피처 계산 + 윈저라이징."""
    # ── ① fundamental_gap ──
    shiller_c = shiller.copy()
    shiller_c['log_P'] = np.___(shiller_c['P'])          # Q35: 자연로그를 계산하는 numpy 함수
    shiller_c['log_E'] = np.log(shiller_c['E'].clip(lower=0.01))
    fundamental_gap = (shiller_c['log_P'].diff(___) - shiller_c['log_E'].diff(12)).dropna()  # Q36: YoY(전년 대비)에 해당하는 월 수
    fundamental_gap.name = '___'                         # Q37: 펀더멘털 괴리도 피처명

    # ── ② erp_zscore ──
    cape_series = shiller_c['CAPE'].dropna()
    real_ey = 1.0 / ___                                  # Q38: CAPE의 역수로 실질 이익수익률을 구할 변수
    tips_monthly = fred['tips_rate']['tips_rate'].resample('MS').last().dropna() / 100.0
    erp_df = pd.DataFrame({'ey': real_ey, 'tips': tips_monthly}).dropna()
    erp = erp_df['ey'] - erp_df['___']                   # Q39: TIPS 실질금리 컬럼명
    erp_rm = erp.rolling(120, min_periods=60).___()       # Q40: 롤링 평균을 구하는 메서드
    erp_rs = erp.rolling(120, min_periods=60).___()       # Q41: 롤링 표준편차를 구하는 메서드
    erp_zscore = ((erp - erp_rm) / erp_rs).___().dropna() # Q42: 절대값을 구하는 메서드

    # ── ③ residual_corr ──
    stock_returns = stock_prices.pct_change().dropna()
    spy_ret = _strip_tz(stock_returns['SPY'])
    residuals = pd.DataFrame(index=stock_returns.index)
    for ticker in ALL_STOCKS:
        if ticker not in stock_returns.columns:
            continue
        ret = stock_returns[ticker]
        cov_spy = ret.rolling(60, min_periods=30).___(spy_ret)  # Q43: 두 시리즈 간 롤링 공분산을 구하는 메서드
        spy_var = spy_ret.rolling(60, min_periods=30).___()      # Q44: 롤링 분산을 구하는 메서드
        beta = cov_spy / spy_var
        residuals[ticker] = ret - ___ * spy_ret          # Q45: 시장 민감도 계수 변수

    # 섹터별 잔차 페어와이즈 상관
    sector_corrs = []
    for sector, stocks in SECTOR_STOCKS.items():
        available = [s for s in stocks if s in residuals.columns]
        if len(available) < ___:                          # Q46: 페어를 만들기 위한 최소 종목 수
            continue
        pair_corrs = []
        for s1, s2 in combinations(available, ___):       # Q47: 2개씩 조합하는 r값
            rc = residuals[s1].rolling(20).___(residuals[s2])  # Q48: 두 시리즈 간 롤링 상관계수를 구하는 메서드
            pair_corrs.append(rc)
        sector_avg = pd.concat(pair_corrs, axis=1).mean(axis=1)
        sector_corrs.append(sector_avg)

    # ── ④ amihud ──
    amihud_per_stock = []
    for ticker, df_t in amihud_data.items():
        oc_ret = np.log(df_t['Close'] / df_t['___']).abs()  # Q49: 장 시작 가격 컬럼명
        dollar_vol = df_t['Close'] * df_t['___']          # Q50: 거래량 컬럼명
        ami_t = oc_ret / dollar_vol.replace(0, np.nan)
        amihud_per_stock.append(ami_t)

    # ── ⑤ vix_term ──
    vix_monthly = fred['vix']['vix'].resample('MS').last().dropna()
    vix3m_monthly = fred['___']['vix3m'].resample('MS').last().dropna()  # Q51
    vix_term = (vix_monthly / ___).dropna()              # Q52

    # ── ⑥ realized_vol ──
    rv_daily = _strip_tz(spy_ret).rolling(___).std() * np.sqrt(___)  # Q53~Q54
    realized_vol_monthly = rv_daily.resample('MS').mean().dropna()

    # ── 윈저라이징 (1/99 퍼센타일) ──
    # features DataFrame 구성 후
    winsor_bounds = {}
    # for col in FEATURE_NAMES:
    #     q01 = features[col].quantile(___)                # Q55
    #     ...

    return {
        'features': None,  # 실제로는 DataFrame
        'winsor_bounds': winsor_bounds,
    }


# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                    |
# |----|-------------------------------|------------------------|
# | Q1 | from itertools import ___     | combinations           |
# | Q2 | from io import ___            | StringIO               |
# | Q3 | as ___                        | np                     |
# | Q4 | as ___                        | pd                     |
# | Q5 | as ___                        | yf                     |
# | Q6 | FRED_BASE = '___'             | https://fred.stlouisfed.org/graph/fredgraph.csv?id= |
# | Q7 | SHILLER_URL = '___'           | http://www.econ.yale.edu/~shiller/data/ie_data.xls |
# | Q8 | '___'                         | XLK                    |
# | Q9 | '___'                         | XLF                    |
# | Q10| '___'                         | XLE                    |
# | Q11| .___()                        | values                 |
# | Q12| '___'                         | AMZN                   |
# | Q13| '___'                         | GOOGL                  |
# | Q14| '___'                         | META                   |
# | Q15| '___'                         | fundamental_gap        |
# | Q16| '___'                         | erp_zscore             |
# | Q17| '___'                         | dispersion             |
# | Q18| '___'                         | amihud                 |
# | Q19| '___'                         | vix_term               |
# | Q20| '___'                         | hy_spread              |
# | Q21| '___'                         | realized_vol           |
# | Q22| '___'                         | DFII10                 |
# | Q23| '___'                         | BAMLH0A0HYM2           |
# | Q24| '___'                         | ^VIX                   |
# | Q25| '___'                         | ^VIX3M                 |
# | Q26| resp.___()                    | raise_for_status       |
# | Q27| hasattr(s.index, '___')       | tz                     |
# | Q28| tz_localize(___)              | None                   |
# | Q29| sheet_name='___'              | Data                   |
# | Q30| '___'                         | CAPE                   |
# | Q31| result[___]                   | col_name               |
# | Q32| '___'                         | SPY                    |
# | Q33| ___=True                      | auto_adjust            |
# | Q34| hist['___']                   | Close                  |
# | Q35| np.___                        | log                    |
# | Q36| .diff(___)                    | 12                     |
# | Q37| .name = '___'                 | fundamental_gap        |
# | Q38| 1.0 / ___                     | cape_series            |
# | Q39| erp_df['___']                 | tips                   |
# | Q40| .___()                        | mean                   |
# | Q41| .___()                        | std                    |
# | Q42| .___()                        | abs                    |
# | Q43| .___                          | cov                    |
# | Q44| .___()                        | var                    |
# | Q45| ___ * spy_ret                 | beta                   |
# | Q46| < ___                         | 2                      |
# | Q47| combinations(available, ___) | 2                      |
# | Q48| .___                          | corr                   |
# | Q49| df_t['___']                   | Open                   |
# | Q50| df_t['___']                   | Volume                 |
# | Q51| fred['___']                   | vix3m                  |
# | Q52| / ___                         | vix3m_monthly          |
# | Q53| .rolling(___).std()           | 20                     |
# | Q54| np.sqrt(___)                  | 252                    |
# | Q55| .quantile(___)               | 0.01                   |
# ============================================================
