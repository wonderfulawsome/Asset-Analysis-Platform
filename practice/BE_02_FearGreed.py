# ============================================================
# BE_02_FearGreed — CNN 공포·탐욕 지수 + PUT/CALL Ratio 수집 빈칸 연습
# 원본: collector/fear_greed.py
# 총 빈칸: 40개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

# Q1~Q2: 필요한 모듈 임포트
import ___                                              # Q1: 날짜/시간 처리 모듈
from curl_cffi import requests as ___                   # Q2: curl_cffi 요청 모듈의 별칭

# Q3: CNN Fear & Greed API URL
URL = '___'                                             # Q3: CNN 공포·탐욕 지수 데이터 API 주소

# Q4~Q8: 영문 등급 → 한글 등급 매핑
RATING_KO = {
    '___':  '극도 공포',                                 # Q4: 극심한 공포 상태의 영문 등급명
    '___':          '공포',                              # Q5: 공포 상태의 영문 등급명
    '___':       '중립',                                 # Q6: 중립 상태의 영문 등급명
    '___':         '탐욕',                               # Q7: 탐욕 상태의 영문 등급명
    '___': '극도 탐욕',                                  # Q8: 극심한 탐욕 상태의 영문 등급명
}


def fetch_fear_greed() -> ___:                           # Q9: 파이썬 내장 딕셔너리 타입
    """CNN API에서 공포·탐욕 지수를 수집합니다."""
    # Q10: Chrome으로 위장한 HTTP 세션 생성
    session = crequests.Session(___='chrome')             # Q10: 브라우저 위장 파라미터명
    # Q11: API에 GET 요청 (10초 타임아웃)
    resp = session.___(URL, timeout=10)                  # Q11: HTTP GET 요청 메서드
    # Q12: HTTP 에러 시 예외 발생
    resp.___()                                           # Q12: HTTP 에러 시 예외 발생 메서드

    # Q13: JSON 응답에서 fear_and_greed 객체 추출
    data      = resp.___()['___']                        # Q13~Q14: JSON 파싱 메서드와 공포·탐욕 데이터 키
    # Q15: 오늘 날짜를 YYYY-MM-DD 형식으로 변환
    today     = datetime.date.today().___('___')          # Q15~Q16: 날짜 포맷 변환 메서드와 연-월-일 형식 문자열
    # Q17: 점수를 소수점 1자리로 반올림
    score     = round(float(data['___']), 1)             # Q17: 공포·탐욕 점수 키
    # Q18~Q19: 영문 등급을 한글로 변환
    rating_ko = RATING_KO.___(data['___'].title(), data['rating'])  # Q18~Q19: 딕셔너리에서 키로 값을 조회하는 메서드와 등급 키

    print(f'[FearGreed] {today} → {score} ({rating_ko})')
    return {'___': today, '___': score, '___': rating_ko}  # Q20~Q22: 반환 딕셔너리의 날짜/점수/등급 키


def fetch_fear_greed() -> dict:
    # CNN API에서 공폼 탐욕지수를 수집
    session = crequests.Session(inpersonate='Chrome')
    resp=session.get(URL, timeout=10)
    resp.raise_for_status()

    # json응답에서 공포탐욕 객체 추출
    data = resp.json()['fear_and_greed']
    # 오늘 날짜를 형식 전환
    today=datetime.date.today().strftime('%Y-%m-%d')
    #점수를 소수점 1자리로 반올림
    score = round(float(data['score']),1)
    # 영문등급을 한글로 반환
    rating_ko = RATING_KO.get(data['rating'].title(), data['rating'])

    print(f'[FearGreed]{today} -> {score} ({rating_ko})')
    return {'date':today, 'score': score, 'rating': rating_ko}





# ── PUT/CALL Ratio 수집 (CBOE 웹스크래핑) ──────────────────────

# Q23: CBOE 시장 통계 페이지 URL
CBOE_URL = '___'                                         # Q23: CBOE 옵션 시장 통계 페이지 URL


def fetch_putcall_ratio() -> ___:                        # Q24: 실수형 반환 타입
    """CBOE에서 Total PUT/CALL Ratio 최신값 스크래핑."""
    import ___                                           # Q25: 정규표현식 모듈
    try:
        # Q26: curl_cffi로 CBOE 페이지 요청
        session = crequests.Session(impersonate='___')    # Q26: 위장할 브라우저 이름 (소문자)
        resp = session.get(CBOE_URL, timeout=___)         # Q27: HTTP 요청 타임아웃 (초)
        resp.raise_for_status()

        html = resp.___                                  # Q28: 응답 본문을 문자열로 가져오는 속성
        # Q29~Q30: Total 섹션과 Index Options 섹션 위치 찾기
        h3_total = html.___(  '<h3>Total</h3>')           # Q29: 문자열에서 위치를 찾는 메서드
        h3_index = html.find('___')                      # Q30: Index Options 섹션의 HTML 태그

        if h3_total < ___:                               # Q31: 문자열을 찾지 못했을 때의 반환값
            print('[PutCall] CBOE 페이지에서 Total 섹션 없음')
            return ___                                   # Q32: 값이 없음을 나타내는 파이썬 키워드

        # Total 섹션만 잘라내기
        end = h3_index if h3_index > h3_total else ___(html)  # Q33: 문자열 길이를 반환하는 내장 함수
        total_section = html[h3_total:___]               # Q34: 슬라이싱 끝 위치 변수

        # Q35: 정규표현식으로 0.XX 형태의 ratio 값 추출
        ratios = re.___(r'<td>\s*(\d\.\d{2})\s*</td>', total_section)  # Q35: 정규식 패턴과 일치하는 모든 항목을 찾는 함수
        if ratios:
            # Q36: 마지막 ratio 값 사용
            value = round(float(ratios[___]), 2)          # Q36: 리스트의 마지막 요소 인덱스
            print(f'[PutCall] CBOE Total P/C ratio → {value}')
            return ___                                   # Q37: 추출한 P/C ratio 값 변수
        else:
            print('[PutCall] Total 섹션에서 P/C ratio 파싱 실패')
            return None
    except ___ as e:                                     # Q38: 모든 예외를 잡는 기본 예외 클래스
        print(f'[PutCall] CBOE 스크래핑 실패: {___}')     # Q39: 예외 객체 변수
        return ___                                       # Q40: 값이 없음을 나타내는 파이썬 키워드

# ===================================================================
# ===================================================================

# CBOE 시장 통계 페이지 URL
CBOE_URL = 'https://ww2.cboe.com/us/options/market_statistics/?iframe=1'

# 풋콜 레이시오 수집 웹스크래핑
def fetch_put_ratio() -> float:
    import re
    try: 
        # curl cliff 로 페이지 요청
        session = crequests.Session(impersonate='chrome')
        resp = session.get(CBOE_URL, tiemeout=15)
        resp.raise_for_status()

        html = resp.text
        # total 섹션과 index options 섹션 위치 찾기
        h3_total = html.find('<h3>Total</h3>')
        h3_index = html.find('<h3>Index Options</h3>')
        
        if h3_total < 0:
            print('[PutCall] CBOE 페이지에서 Total 섹션 없음')
            return None
        
        #  Total 섹션만 잘라내기
        end = h3_index if h3_index > h3_total else len(html)
        total_section = html[h3_total:end]

        # 정규 표현식으로 0.xx 형태의 ratio 값 추출
        ratios = re.findall(r'<td>\s*(\d\.\d{2})\s*</td>', total_section)
        if ratios:
            value = round(float(ratios[-1]),2)
            print(f'[PutCall] CBOE Total P/C ratio -> {value}')
            return value
        else:
            print('파싱 실패')
            return None
    except Exception as e:
        print('스크래핑 실패')
        return 

# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                          |
# |----|-------------------------------|-------------------------------|
# | Q1 | import ___                    | datetime                      |
# | Q2 | as ___                        | crequests                     |
# | Q3 | URL = '___'                   | https://production.dataviz.cnn.io/index/fearandgreed/graphdata |
# | Q4 | '___': '극도 공포'            | Extreme Fear                  |
# | Q5 | '___': '공포'                 | Fear                          |
# | Q6 | '___': '중립'                 | Neutral                       |
# | Q7 | '___': '탐욕'                 | Greed                         |
# | Q8 | '___': '극도 탐욕'            | Extreme Greed                 |
# | Q9 | -> ___                        | dict                          |
# | Q10| ___='chrome'                  | impersonate                   |
# | Q11| session.___                   | get                           |
# | Q12| resp.___()                    | raise_for_status              |
# | Q13| resp.___()                    | json                          |
# | Q14| ['___']                       | fear_and_greed                |
# | Q15| .___('...')                   | strftime                      |
# | Q16| ('___')                       | %Y-%m-%d                      |
# | Q17| data['___']                   | score                         |
# | Q18| RATING_KO.___                 | get                           |
# | Q19| data['___']                   | rating                        |
# | Q20| '___': today                  | date                          |
# | Q21| '___': score                  | score                         |
# | Q22| '___': rating_ko              | rating                        |
# | Q23| CBOE_URL = '___'              | https://ww2.cboe.com/us/options/market_statistics/?iframe=1 |
# | Q24| -> ___                        | float                         |
# | Q25| import ___                    | re                            |
# | Q26| impersonate='___'             | chrome                        |
# | Q27| timeout=___                   | 15                            |
# | Q28| resp.___                      | text                          |
# | Q29| html.___                      | find                          |
# | Q30| html.find('___')              | <h3>Index Options</h3>        |
# | Q31| < ___                         | 0                             |
# | Q32| return ___                    | None                          |
# | Q33| ___(html)                     | len                           |
# | Q34| html[h3_total:___]            | end                           |
# | Q35| re.___                        | findall                       |
# | Q36| ratios[___]                   | -1                            |
# | Q37| return ___                    | value                         |
# | Q38| except ___ as e               | Exception                     |
# | Q39| {___}                         | e                             |
# | Q40| return ___                    | None                          |
# ============================================================
