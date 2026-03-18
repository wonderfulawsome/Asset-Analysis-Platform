# ============================================================
# BE_03_IndexPrice — ETF 가격/등락률 수집 빈칸 연습
# 원본: collector/index_price.py
# 총 빈칸: 40개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.
# ===================================================================

# Q1~Q3: 필요한 모듈 임포트
import ___                                              # Q1: 날짜/시간 처리 모듈
import ___                                              # Q2: 시간 측정 모듈
import ___                                              # Q3: HTTP 요청 라이브러리

# ===================================================================
import datetime
import time
import requests
# ===================================================================
# Q4: Yahoo Finance API 헤더
HEADERS = {'___': 'Mozilla/5.0'}                        # Q4: HTTP 요청 시 브라우저 식별 헤더 키

HEADERS = {'User-Agent: Mozilla/5.0'}
# Q5: 수집할 ETF 티커 목록 (총 31개)
TICKERS = [
    'SPY', 'QQQ', 'SOXX', 'BND', 'IWM', 'DIA',         # Q5~Q6: S&P 500 추종 ETF, 나스닥 100 추종 ETF
    'VTI', 'VOO', 'SMH', 'ARKK', 'GLD', 'SLV',         # Q7: 금 현물 추종 ETF
    'TLT', 'HYG', 'VNQ', 'EEM', 'EFA', 'VGK',          # Q8: 장기 국채 ETF
    'KWEB', 'XBI', 'JETS', 'SCHD', 'VXUS',
    'XLK', 'XLF', 'XLE', 'XLV', 'XLB', 'XLP',
    'XLU', 'XLI', 'XLRE',
]


def fetch_index_prices() -> list[___]:                   # Q9: 파이썬 내장 딕셔너리 타입
    """ETF 티커별 전일 대비 등락률을 수집해 레코드 리스트로 반환합니다."""
    today = datetime.date.___()                          # Q10: 오늘 날짜를 가져오는 메서드
    from_date = today - datetime.timedelta(days=___)     # Q11: 과거 데이터 조회 일수
    # Q12~Q13: 날짜를 Unix timestamp로 변환
    from_ts = int(datetime.datetime.combine(from_date, datetime.time()).___())  # Q12: datetime을 Unix 타임스탬프로 변환하는 메서드
    to_ts   = int(datetime.datetime.combine(today + datetime.timedelta(days=___), datetime.time()).timestamp())  # Q13: 오늘 이후 추가 여유 일수

    result = []                                          # 최종 결과 리스트
    for ticker in ___:                                   # Q14: ETF 티커 목록 변수
        try:
            # Q15: Yahoo Finance v8 API URL 구성
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{___}'  # Q15: URL에 삽입할 티커 변수
            params = {'interval': '1d', 'period1': from_ts, 'period2': to_ts}
            resp = requests.get(url, params=params, headers=HEADERS, timeout=___)  # Q16: HTTP 요청 타임아웃 (초)
            resp.raise_for_status()
            data   = resp.json()['___']['result'][0]     # Q17: Yahoo Finance 응답의 최상위 키
            meta   = data['___']                         # Q18: 티커 메타데이터 키
            closes = data['indicators']['adjclose'][0]['adjclose']
            closes = [c for c in closes if c is not ___]  # Q19: 결측값을 나타내는 파이썬 키워드

            if len(closes) < ___:                        # Q20: 최소 필요 데이터 건수
                continue

            # Q21~Q22: currentTradingPeriod로 장 중 여부 판단
            now_ts = int(time.___())                     # Q21: 현재 Unix 타임스탬프를 반환하는 함수
            trading = meta.get('___', {}).get('regular', {})  # Q22: 거래 시간 정보를 담은 메타데이터 키
            is_market_open = trading.get('___', 0) <= now_ts <= trading.get('___', 0)  # Q23~Q24: 정규 거래 시간의 시작/종료 키

            # Q25: 실시간 가격 가져오기
            realtime_price = meta.get('___')             # Q25: 실시간 시장 가격 메타데이터 키
            if is_market_open and realtime_price:         # 장 중이면 실시간 가격 사용
                prev = closes[-2] if len(closes) >= ___ else closes[-1]  # Q26: 전일 종가 접근을 위한 최소 데이터 건수
                curr = ___                               # Q27: 실시간 가격 변수
            else:                                        # 장 마감이면 확정 종가 사용
                if len(closes) < 2:
                    continue
                prev, curr = closes[___], closes[___]    # Q28~Q29: 전일 종가와 당일 종가의 리스트 인덱스

            if prev and curr and prev > ___:             # Q30: 0으로 나누기 방지를 위한 최솟값
                result.___(  {                            # Q31: 리스트에 항목을 추가하는 메서드
                    '___':       str(today),              # Q32: 날짜 키
                    '___':     ticker,                    # Q33: 티커 심볼 키
                    '___':      round(curr, 2),           # Q34: 종가 키
                    '___': round((curr - prev) / prev * ___, 2),  # Q35~Q36: 등락률 키와 백분율 변환 승수
                })
        except Exception as e:
            print(f'[IndexPrice] {ticker} 수집 실패: {e}')

    print(f'[IndexPrice] {___(result)}/{len(TICKERS)}개 수집 완료')  # Q37: 리스트 길이를 반환하는 내장 함수
    return ___                                           # Q38: 최종 결과 리스트 변수
# ============================================================
def fetch_index_prices() -> list[dict]:
    # 티커별 전일 대비 등락률을 수집하여 레코드 리스트를 반환
    today = datetime.date.today()
    from_ts = int(datetime.datetime.combine(from_date, datetime.time()).timestamp())
    to_ts = int(datetime.datetime.combine(today + datime.timedelta(days = 1), datetime.time()).timestamp())
    
    result=[]
    for ticker in TICKERS:
        try:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
            params = {'interval': 'id', 'period1': from_ts, 'period2': to_ts}
            resp = requests.get(url, params=params, headers=HEADERS, timeout = 10)
            resp.raise_for_status()
            data = resp.json()['chart']['result'][0]
            meta = data['ticker']
            closes = data['indicators']['adjclose'][0]['adjclose']
            closes = [c for c in closes if c is not None]

            if len(closes) < 1:
                continue

            #장중 여부 판단
            now_ts = int(time.time())
            trading = meta.get('currentTradingPeriod',{}).get('regular',{})
            is_market_ope=trading.get('start',0)<=now_ts <= trading.get('end',0)

            realtime_price=meta.get('regularMarketPrice')
            if is_market_open and realtime_price:
                prev = closes[-2] if len(closes) >=2 else closes[-1]
                curr = realtime_price
            else:
                if len(closes)<2:
                    continue
                prev, curr =closes[-2], closes[-1] # 전일 종가와 당일 종가의 리스트 인덱스

            # 0으로 나누기 방지를위한 최솟값
            if prev and curr and prev> 0:
                result.append( {
                    'date': str(today),
                    'ticker': ticker,
                    'close': round(curr,2),
                    'change_pct': round(curr-prev/prev * 100,2) # 등락률 키와 백분율 변환 승수
                })
        except Exception as e:
            print(f'[IndexPrice]{ticker}')

    print(f'[IndexPrice]{list(result)}/{len(TICKERS)}개 수집 완료')
    return result
                    
# ============================================================

# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                    |
# |----|-------------------------------|------------------------|
# | Q1 | import ___                    | datetime               |
# | Q2 | import ___                    | time                   |
# | Q3 | import ___                    | requests               |
# | Q4 | {'___': ...}                  | User-Agent             |
# | Q5 | '___'                         | SPY                    |
# | Q6 | '___'                         | QQQ                    |
# | Q7 | '___'                         | GLD                    |
# | Q8 | '___'                         | TLT                    |
# | Q9 | list[___]                     | dict                   |
# | Q10| .___()                        | today                  |
# | Q11| days=___                      | 10                     |
# | Q12| .___()                        | timestamp              |
# | Q13| days=___                      | 1                      |
# | Q14| for ticker in ___             | TICKERS                |
# | Q15| {___}                         | ticker                 |
# | Q16| timeout=___                   | 15                     |
# | Q17| ['___']                       | chart                  |
# | Q18| data['___']                   | meta                   |
# | Q19| is not ___                    | None                   |
# | Q20| < ___                         | 1                      |
# | Q21| time.___()                    | time                   |
# | Q22| meta.get('___', {})           | currentTradingPeriod   |
# | Q23| .get('___', 0)                | start                  |
# | Q24| .get('___', 0)                | end                    |
# | Q25| meta.get('___')               | regularMarketPrice     |
# | Q26| >= ___                        | 2                      |
# | Q27| curr = ___                    | realtime_price         |
# | Q28| closes[___]                   | -2                     |
# | Q29| closes[___]                   | -1                     |
# | Q30| prev > ___                    | 0                      |
# | Q31| result.___                    | append                 |
# | Q32| '___': str(today)             | date                   |
# | Q33| '___': ticker                 | ticker                 |
# | Q34| '___': round(...)             | close                  |
# | Q35| '___': round(...)             | change_pct             |
# | Q36| * ___                         | 100                    |
# | Q37| ___(result)                   | len                    |
# | Q38| return ___                    | result                 |
# ============================================================
