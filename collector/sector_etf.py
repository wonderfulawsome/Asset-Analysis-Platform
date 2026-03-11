### 섹터 ETF + 보유 종목 월별 수익률 수집

import pandas as pd    # 데이터프레임 처리
import yfinance as yf  # Yahoo Finance 주가 데이터 다운로드 라이브러리

# 섹터별 대표 ETF 10개 (경기국면 분석용)
SECTOR_ETFS = ['XLF', 'XLE', 'XLK', 'XLV', 'XLB', 'XLP', 'XLU', 'XLI', 'XLRE', 'SOXX']

# 사용자가 관심 있는 보유 종목 ETF 22개
ALL_HOLDINGS = [
    'QQQ', 'SPY', 'DIA', 'IWM', 'VTI', 'VOO',    # 주요 지수 ETF
    'SMH', 'ARKK', 'GLD', 'SLV', 'TLT', 'BND',    # 테마/원자재/채권 ETF
    'HYG', 'VNQ', 'EEM', 'EFA', 'VGK', 'KWEB',    # 하이일드/리츠/해외 ETF
    'XBI', 'JETS', 'SCHD', 'VXUS',                  # 테마/배당/해외 ETF
]


def fetch_sector_etf_returns(macro_start: str, etf_start: str = '1999-01-01') -> tuple[pd.DataFrame, pd.DataFrame]:
    """섹터 ETF + 보유 종목 월별 수익률을 반환합니다.

    Returns: (sector_ret, holding_ret) - 월별 수익률 DataFrame 쌍
    """
    all_tickers = SECTOR_ETFS + ALL_HOLDINGS           # 섹터 10 + 보유 22 = 총 32개 티커
    start_date = max(macro_start, etf_start)           # 두 시작일 중 더 늦은 날짜 사용(데이터 정합성)

    print(f'[SectorETF] {len(all_tickers)}개 종목 다운로드 (시작: {start_date})')

    frames = {}                                        # 티커별 종가를 모을 딕셔너리
    for ticker in all_tickers:                         # 32개 티커 순회
        try:
            t = yf.Ticker(ticker)                      # yfinance 티커 객체 생성
            hist = t.history(start=start_date, auto_adjust=True)  # 주가 히스토리 다운로드 (수정 종가)
            if len(hist) > 0:
                frames[ticker] = hist['Close']         # 종가만 저장
                print(f'  ✓ {ticker}: {len(hist)}일')
            else:
                print(f'  ✗ {ticker}: 데이터 없음')
        except Exception as e:
            print(f'  ✗ {ticker}: {e}')                # 실패 시 로그 출력 후 계속

    raw = pd.DataFrame(frames)                         # 전체 종가를 하나의 DataFrame으로 합침
    raw.index = pd.to_datetime(raw.index)              # 인덱스를 datetime으로 변환
    if raw.index.tz is not None:
        raw.index = raw.index.tz_localize(None)        # 타임존 제거 (UTC → naive)

    ### 섹터 etf + 주요 ETF 의 종가를 수집 (시작날짜 맞추기 + 타임존 제거)

    monthly_prices  = raw.resample('MS').last()        # 월초 기준 리샘플링 → 월말 종가
    monthly_returns = monthly_prices.pct_change()      # 월별 수익률 계산 (전월 대비 변화율)

    # 섹터 ETF와 보유 종목을 분리
    sector_ret  = monthly_returns[[c for c in SECTOR_ETFS if c in monthly_returns.columns]]   # 섹터 ETF 수익률
    holding_ret = monthly_returns[[c for c in ALL_HOLDINGS if c in monthly_returns.columns]]   # 보유 종목 수익률

    ### 다운로드는 한번에, 분석을 위해서 데이터를 분리

    print(f'[SectorETF] 수집 완료: 섹터 {sector_ret.shape}, 보유 {holding_ret.shape}')
    return sector_ret, holding_ret  # (섹터 수익률 DF, 보유종목 수익률 DF) 튜플 반환

# -------------------------------------------------------------------
# 섹터 etf + 주요 ETF 의 종가를 수집
# -------------------------------------------------------------------