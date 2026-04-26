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
    'XLU', 'XLI', 'XLRE', 'XLY', 'XLC',                # 섹터 ETF (유틸리티/산업/부동산/소비재/통신)
    'IGV',                                             # 소프트웨어 (Tech sub-sector)
]


def fetch_index_prices() -> list[dict]:
    """ETF 티커별 전일 대비 등락률을 수집해 레코드 리스트로 반환합니다.
    장 중(REGULAR)이면 실시간 가격(regularMarketPrice), 장 마감이면 확정 종가(adjclose) 사용.
    """
    today = datetime.date.today()                        # 오늘 날짜 (서버 UTC 기준)
    from_date = today - datetime.timedelta(days=10)      # 10일 전부터 조회 (주말/공휴일 대비 여유분)
    # 날짜를 Unix timestamp(초)로 변환 — Yahoo API가 이 형식을 요구함
    from_ts = int(datetime.datetime.combine(from_date, datetime.time()).timestamp())
    to_ts   = int(datetime.datetime.combine(today + datetime.timedelta(days=1), datetime.time()).timestamp())  # +1일: 장 중 실시간 데이터 포함

    result = []  # 최종 결과를 담을 리스트
    for ticker in TICKERS:  # 31개 티커를 하나씩 순회
        try:
            # Yahoo Finance v8 API URL 구성
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
            params = {'interval': '1d', 'period1': from_ts, 'period2': to_ts}  # 일봉, 기간 지정
            resp = requests.get(url, params=params, headers=HEADERS, timeout=15)  # API 호출 (15초 타임아웃)
            resp.raise_for_status()                      # HTTP 에러 시 예외 발생
            data   = resp.json()['chart']['result'][0]   # JSON 응답에서 차트 데이터 추출
            meta   = data['meta']                        # 메타 정보 (실시간/최종 체결가 포함)
            closes = data['indicators']['adjclose'][0]['adjclose']  # 수정 종가 리스트
            closes = [c for c in closes if c is not None]  # None 값 제거 (거래 없는 날)

            # regularMarketPrice: 장 중엔 실시간가, 장 마감 후엔 최종 종가
            realtime_price = meta.get('regularMarketPrice')  # 최종 체결가 (항상 존재)
            # curr: regularMarketPrice가 있으면 사용, 없으면 adjclose 마지막 값 사용
            curr = realtime_price if realtime_price else (closes[-1] if closes else None)

            # prev(전일 종가): adjclose 배열을 뒤에서부터 순회하여 당일 종가와 다른 첫 번째 값을 찾음
            # (장 마감 후 adjclose 마지막 2개가 동일해지므로 closes[-2]는 사용 불가)
            prev = None                                  # 전일 종가 초기화 (아직 못 찾은 상태)
            if curr and closes:
                for c in reversed(closes):               # 배열 끝에서부터 역순 탐색
                    if round(c, 2) != round(curr, 2):    # 당일 종가와 다른 값 발견 시
                        prev = c                         # 그 값이 전일 종가
                        break

            if not curr or not prev or prev <= 0:        # 유효하지 않으면 건너뜀
                continue

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