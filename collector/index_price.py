import datetime       # 날짜/시간 처리용 표준 라이브러리
import requests       # HTTP 요청을 보내기 위한 라이브러리

# Yahoo Finance API 호출 시 브라우저처럼 보이게 하는 헤더 (차단 방지)
HEADERS = {'User-Agent': 'Mozilla/5.0'}

# 수집할 ETF 티커 목록 (총 31개)
TICKERS = [
    'SPY', 'QQQ', 'SOXX', 'BND', 'IWM', 'DIA',      # 주요 지수 ETF
    'VTI', 'VOO', 'SMH', 'ARKK', 'GLD', 'SLV',       # 시장/테마/원자재 ETF
    'TLT', 'HYG', 'VNQ', 'EEM', 'EFA', 'VGK',        # 채권/리츠/해외 ETF
    'KWEB', 'XBI', 'JETS', 'SCHD', 'VXUS',            # 테마/배당/해외 ETF
    'XLK', 'XLF', 'XLE', 'XLV', 'XLB', 'XLP',        # 섹터 ETF (기술/금융/에너지/헬스/소재/필수소비)
    'XLU', 'XLI', 'XLRE',                              # 섹터 ETF (유틸리티/산업/부동산)
]


def fetch_index_prices() -> list[dict]:
    """ETF 티커별 전일 대비 등락률을 수집해 레코드 리스트로 반환합니다.
    장 중(REGULAR)이면 실시간 가격(regularMarketPrice), 장 마감이면 확정 종가(adjclose) 사용.
    """
    today = datetime.date.today()                        # 오늘 날짜 (서버 UTC 기준)
    from_date = today - datetime.timedelta(days=10)      # 10일 전부터 조회 (주말/공휴일 대비 여유분)
    # 날짜를 Unix timestamp(초)로 변환 — Yahoo API가 이 형식을 요구함
    from_ts = int(datetime.datetime.combine(from_date, datetime.time()).timestamp())
    to_ts   = int(datetime.datetime.combine(today,     datetime.time()).timestamp())

    result = []  # 최종 결과를 담을 리스트
    for ticker in TICKERS:  # 31개 티커를 하나씩 순회
        try:
            # Yahoo Finance v8 API URL 구성
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
            params = {'interval': '1d', 'period1': from_ts, 'period2': to_ts}  # 일봉, 기간 지정
            resp = requests.get(url, params=params, headers=HEADERS, timeout=15)  # API 호출 (15초 타임아웃)
            resp.raise_for_status()                      # HTTP 에러 시 예외 발생
            data   = resp.json()['chart']['result'][0]   # JSON 응답에서 차트 데이터 추출
            meta   = data['meta']                        # 메타 정보 (시장 상태, 실시간 가격 포함)
            market_state = meta.get('marketState', '')   # 시장 상태: REGULAR(장중), CLOSED, PRE, POST 등
            closes = data['indicators']['adjclose'][0]['adjclose']  # 수정 종가 리스트
            closes = [c for c in closes if c is not None]  # None 값 제거 (거래 없는 날)

            if len(closes) < 1:                          # 데이터가 없으면 건너뜀
                continue

            if market_state == 'REGULAR':                # 장 중이면 실시간 가격 사용
                curr = meta.get('regularMarketPrice')    # 실시간 현재가
                prev = closes[-1]                        # 전일 확정 종가 (adjclose 마지막 값)
            else:                                        # 장 마감이면 확정 종가 사용
                if len(closes) < 2:                      # 최소 2일치 필요
                    continue
                prev, curr = closes[-2], closes[-1]      # 전일 종가, 당일 확정 종가

            if prev and curr and prev > 0:               # 유효한 값인지 확인
                result.append({
                    'date':       str(today),             # 수집 날짜
                    'ticker':     ticker,                 # ETF 티커명
                    'close':      round(curr, 2),         # 현재가 (소수점 2자리)
                    'change_pct': round((curr - prev) / prev * 100, 2),  # 전일 대비 등락률 (%)
                })
        except Exception as e:
            print(f'[IndexPrice] {ticker} 수집 실패: {e}')  # 실패 시 로그 출력 후 다음 티커로 계속

    print(f'[IndexPrice] {len(result)}/{len(TICKERS)}개 수집 완료')  # 성공/전체 개수 출력
    return result  # 수집된 레코드 리스트 반환


# -------------------------------------------------------------------
# 티커별 최신 종가 데이터 추출
# -------------------------------------------------------------------