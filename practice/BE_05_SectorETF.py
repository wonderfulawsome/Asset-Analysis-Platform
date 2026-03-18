# ============================================================
# BE_05_SectorETF — 섹터 ETF + 보유 종목 월별 수익률 수집 빈칸 연습
# 원본: collector/sector_etf.py
# 총 빈칸: 30개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

# Q1~Q2: 필요한 모듈 임포트
import pandas as ___                                    # Q1: pandas 관례적 별칭
import yfinance as ___                                  # Q2: yfinance 관례적 별칭

# Q3: 섹터별 대표 ETF 10개
SECTOR_ETFS = ['___', '___', '___', 'XLV', 'XLB', 'XLP', 'XLU', 'XLI', 'XLRE', 'SOXX']  # Q3~Q5: 금융·에너지·기술 섹터 ETF 티커

# Q6: 보유 종목 ETF 22개
ALL_HOLDINGS = [
    'QQQ', '___', 'DIA', 'IWM', 'VTI', 'VOO',          # Q6: S&P 500 추종 대표 ETF 티커
    'SMH', 'ARKK', 'GLD', 'SLV', 'TLT', 'BND',
    'HYG', 'VNQ', 'EEM', 'EFA', 'VGK', 'KWEB',
    'XBI', 'JETS', '___', 'VXUS',                       # Q7: 배당 성장 ETF 티커
]


def fetch_sector_etf_returns(macro_start: str, etf_start: str = '___') -> tuple[pd.DataFrame, pd.DataFrame]:  # Q8: ETF 수집 시작 날짜 기본값 (yyyy-mm-dd)
    """섹터 ETF + 보유 종목 월별 수익률을 반환합니다."""
    all_tickers = SECTOR_ETFS + ___                     # Q9: 보유 종목 ETF 리스트 변수
    start_date = ___(macro_start, etf_start)             # Q10: 두 값 중 더 큰 값을 반환하는 내장 함수

    frames = {}                                          # 티커별 종가 딕셔너리
    for ticker in ___:                                   # Q11: 전체 티커 목록 변수
        try:
            t = yf.___(ticker)                           # Q12: 개별 종목 객체를 생성하는 yfinance 클래스
            hist = t.___(start=start_date, auto_adjust=True)  # Q13: 과거 주가 데이터를 가져오는 메서드
            if len(hist) > 0:
                frames[ticker] = hist['___']             # Q14: 종가 컬럼명
        except Exception as e:
            print(f'  ✗ {ticker}: {e}')

    raw = pd.___(frames)                                 # Q15: 딕셔너리로부터 표 형태 객체를 생성하는 pandas 클래스
    raw.index = pd.to_datetime(raw.index)
    if raw.index.___ is not None:                        # Q16: 인덱스의 타임존 속성
        raw.index = raw.index.tz_localize(___)           # Q17: 타임존을 제거하기 위해 전달하는 값

    # Q18~Q19: 월별 리샘플링 + 수익률 계산
    monthly_prices  = raw.resample('___').last()          # Q18: 월초 기준 리샘플링 주기 코드
    monthly_returns = monthly_prices.___()               # Q19: 이전 대비 변화율을 계산하는 메서드

    # Q20~Q21: 섹터 ETF와 보유 종목 분리
    sector_ret  = monthly_returns[[c for c in ___ if c in monthly_returns.columns]]   # Q20: 섹터 ETF 티커 리스트 변수
    holding_ret = monthly_returns[[c for c in ___ if c in monthly_returns.columns]]   # Q21: 보유 종목 ETF 리스트 변수

    print(f'[SectorETF] 수집 완료: 섹터 {sector_ret.___}, 보유 {holding_ret.shape}')  # Q22: DataFrame의 행×열 크기를 나타내는 속성
    return sector_ret, ___                               # Q23: 보유 종목 수익률 DataFrame 변수


# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                    |
# |----|-------------------------------|------------------------|
# | Q1 | as ___                        | pd                     |
# | Q2 | as ___                        | yf                     |
# | Q3 | '___'                         | XLF                    |
# | Q4 | '___'                         | XLE                    |
# | Q5 | '___'                         | XLK                    |
# | Q6 | '___'                         | SPY                    |
# | Q7 | '___'                         | SCHD                   |
# | Q8 | '___'                         | 1999-01-01             |
# | Q9 | + ___                         | ALL_HOLDINGS           |
# | Q10| ___(...)                       | max                    |
# | Q11| for ticker in ___             | all_tickers            |
# | Q12| yf.___                        | Ticker                 |
# | Q13| t.___                         | history                |
# | Q14| hist['___']                   | Close                  |
# | Q15| pd.___                        | DataFrame              |
# | Q16| .index.___                    | tz                     |
# | Q17| tz_localize(___)              | None                   |
# | Q18| .resample('___')              | MS                     |
# | Q19| .___()                        | pct_change             |
# | Q20| for c in ___                  | SECTOR_ETFS            |
# | Q21| for c in ___                  | ALL_HOLDINGS           |
# | Q22| .___                          | shape                  |
# | Q23| return sector_ret, ___        | holding_ret            |
# ============================================================
