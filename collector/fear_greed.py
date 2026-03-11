# CNN API에서 공포·탐욕 지수 수집

import datetime
from curl_cffi import requests as crequests

# CNN 사이트 URL 
URL = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata'

RATING_KO = {
    'Extreme Fear':  '극도 공포',
    'Fear':          '공포',
    'Neutral':       '중립',
    'Greed':         '탐욕',
    'Extreme Greed': '극도 탐욕',
}

# 공포탐욕지수를 api로 불러오고 오늘날짜를 가져오기
def fetch_fear_greed() -> dict:
    # 봇 차단 우회를 위해 Chrome으로 위장한 HTTP 세션 생성
    session = crequests.Session(impersonate='chrome')
    # CNN Fear & Greed API에 GET 요청 (10초 타임아웃)
    resp = session.get(URL, timeout=10)
    # HTTP 오류 상태코드(4xx, 5xx)면 예외 발생
    resp.raise_for_status()

    # JSON 응답에서 fear_and_greed 객체만 추출
    data      = resp.json()['fear_and_greed']
    # 오늘 날짜를 YYYY-MM-DD 형식으로 변환
    today     = datetime.date.today().strftime('%Y-%m-%d')
    # 지수 점수를 소수점 1자리로 반올림
    score     = round(float(data['score']), 1)
    # 영문 등급을 RATING_KO 딕셔너리로 한글 변환 (매핑 없으면 원문 유지)
    rating_ko = RATING_KO.get(data['rating'].title(), data['rating'])

    print(f'[FearGreed] {today} → {score} ({rating_ko})')
    # 날짜, 점수, 한글 등급을 dict로 반환
    return {'date': today, 'score': score, 'rating': rating_ko}


# ── PUT/CALL Ratio 수집 (CBOE 웹스크래핑) ──────────────────────

# CBOE 시장 통계 페이지 URL (Total/Index/Equity P/C ratio 포함)
CBOE_URL = 'https://ww2.cboe.com/us/options/market_statistics/?iframe=1'


def fetch_putcall_ratio() -> float:
    """CBOE에서 Total PUT/CALL Ratio 최신값 스크래핑."""
    import re
    try:
        # curl_cffi로 CBOE 페이지 요청 (봇 차단 우회)
        session = crequests.Session(impersonate='chrome')
        resp = session.get(CBOE_URL, timeout=15)
        resp.raise_for_status()

        html = resp.text
        # <h3>Total</h3> ~ <h3>Index Options</h3> 구간에서 P/C Ratio 추출
        h3_total = html.find('<h3>Total</h3>')
        h3_index = html.find('<h3>Index Options</h3>')

        if h3_total < 0:
            print('[PutCall] CBOE 페이지에서 Total 섹션 없음')
            return None

        # Total 섹션만 잘라내기 (Index 섹션 시작 전까지)
        end = h3_index if h3_index > h3_total else len(html)
        total_section = html[h3_total:end]

        # Total 섹션에서 0.XX 형태의 P/C ratio 값 추출 (빈 td 제외)
        ratios = re.findall(r'<td>\s*(\d\.\d{2})\s*</td>', total_section)
        if ratios:
            # 가장 마지막 비어있지 않은 ratio 값 (최신 시간대)
            value = round(float(ratios[-1]), 2)
            print(f'[PutCall] CBOE Total P/C ratio → {value}')
            return value
        else:
            print('[PutCall] Total 섹션에서 P/C ratio 파싱 실패')
            return None
    except Exception as e:
        print(f'[PutCall] CBOE 스크래핑 실패: {e}')
        return None