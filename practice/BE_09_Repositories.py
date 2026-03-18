# ============================================================
# BE_09_Repositories — Supabase 테이블별 upsert/fetch 함수 빈칸 연습
# 원본: database/repositories.py
# 총 빈칸: 50개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

# Q1: JSON 직렬화/역직렬화 모듈
import ___                                              # Q1: 직렬화/역직렬화 표준 모듈
# Q2: Optional 타입 힌트 임포트
from typing import ___                                  # Q2: 값이 없을 수 있음을 나타내는 타입 힌트
# Q3: Supabase 클라이언트 가져오는 함수 임포트
from database.supabase_client import ___                 # Q3: DB 클라이언트 반환 함수명


# ── macro_raw 테이블 ─────────────────────────────────────────

def upsert_macro(records: list[dict]) -> None:           # macro 데이터 저장 함수
    """거시 지표 데이터를 macro_raw 테이블에 upsert합니다."""
    if not records:                                      # 빈 리스트면 아무것도 하지 않음
        return                                           # 조기 반환
    client = ___()                                       # Q4: DB 클라이언트 반환 함수 호출
    # Q5~Q7: 테이블명, upsert 메서드, 충돌 기준 컬럼
    client.___("___").___( records, on_conflict="___").execute()  # Q5: 테이블 선택 메서드 / Q6: 거시지표 테이블명 / Q7: 삽입·갱신 메서드 / Q8: 충돌 판단 기준 컬럼
    print(f"[DB] macro_raw {len(records)}건 upsert 완료")


def fetch_macro(days: int = ___) -> list[dict]:          # Q9: 기본 조회 일수 (약 3년 영업일)
    """최근 N일 거시 지표를 날짜 오름차순으로 조회합니다."""
    client = get_client()                                # DB 연결 객체 가져오기
    response = (
        client.table("macro_raw")                        # macro_raw 테이블 선택
        .___("*")                                        # Q10: 조회 컬럼 지정 메서드
        .order("date", desc=___)                         # Q11: 오름차순 정렬 여부 (불리언)
        .___( days)                                      # Q12: 결과 행 수 제한 메서드
        .___()                                           # Q13: 쿼리 실행 메서드
    )
    return response.___                                  # Q14: 응답에서 데이터 추출 속성


# ── market_regime 테이블 ─────────────────────────────────────

def upsert_regime(record: dict) -> None:                 # 국면 결과 저장 함수
    """HMM 국면 결과를 market_regime 테이블에 upsert합니다."""
    # Q15: probabilities 값이 dict 타입인지 확인
    if isinstance(record.get("___"), ___):               # Q15: 확률 분포 저장 필드명 / Q16: 확인할 자료형 타입
        record = dict(record)                            # 원본 보호를 위해 복사
        # Q17~Q18: JSON 직렬화 함수와 한글 유지 옵션
        record["probabilities"] = json.___(record["probabilities"], ___=False)  # Q17: 객체→문자열 변환 함수 / Q18: ASCII 강제 변환 옵션명
    client = get_client()                                # DB 연결 객체 가져오기
    # Q19: 복합 유니크 키 (날짜 + 지수명)
    client.table("market_regime").upsert(record, on_conflict="___").execute()  # Q19: 복합 유니크 키 (날짜+지수명 쉼표 구분)


def _parse_probabilities(record: dict) -> dict:          # JSON 역직렬화 헬퍼
    """DB에서 문자열로 저장된 probabilities를 dict로 역직렬화합니다."""
    if isinstance(record.get("probabilities"), ___):     # Q20: 문자열 여부 확인 타입
        record = dict(record)                            # 원본 보호를 위해 복사
        record["probabilities"] = json.___(record["probabilities"])  # Q21: 문자열→객체 역직렬화 함수
    return record                                        # 파싱된 레코드 반환


def fetch_regime_current(index_name: str = '___') -> Optional[dict]:  # Q22: 기본 조회 대상 지수명
    """특정 지수의 가장 최근 국면 1건을 조회합니다."""
    client = get_client()                                # DB 연결 객체 가져오기
    response = (
        client.table("market_regime")                    # market_regime 테이블 선택
        .select("*")                                     # 전체 컬럼 조회
        .___("index_name", index_name)                   # Q23: 값 일치 필터 메서드
        .order("date", desc=___)                         # Q24: 최신 날짜 우선 정렬 (불리언)
        .limit(___)                                      # Q25: 최신 1건만 조회
        .execute()                                       # 쿼리 실행
    )
    # Q26: 삼항 표현식 — 데이터 있으면 파싱 후 반환, 없으면 None
    return _parse_probabilities(response.data[___]) if response.data else ___  # Q26: 첫 번째 요소 인덱스 / Q27: 데이터 없을 때 반환값


def fetch_regime_current_all() -> list[dict]:            # 3개 지수 국면 일괄 조회
    """sp500, ndx, sox 3개 지수의 최신 국면을 한번에 조회합니다."""
    result = []                                          # 결과 리스트 초기화
    for name in ['___', '___', '___']:                   # Q28~Q30: 3개 주요 지수명 (대형주/기술주/반도체)
        r = fetch_regime_current(name)                   # 각 지수 국면 조회
        if r:                                            # 결과가 있으면
            result.append(r)                             # 리스트에 추가
    return result                                        # 결과 반환


# ── fear_greed_raw 테이블 ────────────────────────────────────

def upsert_fear_greed(record: dict) -> None:             # 공포탐욕 저장 함수
    """공포·탐욕 지수를 fear_greed_raw 테이블에 upsert합니다."""
    client = get_client()                                # DB 연결 객체 가져오기
    client.table("___").upsert(record, on_conflict="___").execute()  # Q31: 공포탐욕 지수 테이블명 / Q32: 충돌 판단 기준 컬럼


def fetch_fear_greed_latest() -> Optional[dict]:         # 최신 공포탐욕 조회
    """가장 최근 공포·탐욕 지수 1건을 조회합니다."""
    client = get_client()                                # DB 연결 객체 가져오기
    response = (
        client.table("fear_greed_raw")                   # fear_greed_raw 테이블 선택
        .select("___")                                   # Q33: 전체 컬럼 조회 와일드카드
        .order("___", desc=True)                         # Q34: 정렬 기준 컬럼명
        .limit(1)                                        # 최신 1건만
        .execute()                                       # 쿼리 실행
    )
    return response.data[0] if response.___ else None    # Q35: 응답에서 데이터 추출 속성


# ── index_price_raw 테이블 ───────────────────────────────────

def upsert_index_prices(records: list[dict]) -> None:    # ETF 가격 저장 함수
    """ETF 가격/등락률을 index_price_raw 테이블에 upsert합니다."""
    if not records:                                      # 빈 리스트면 조기 반환
        return
    client = get_client()                                # DB 연결 객체 가져오기
    # Q36: 복합 유니크 키 (날짜 + 티커)
    client.table("index_price_raw").upsert(records, on_conflict="___").execute()  # Q36: 복합 유니크 키 (날짜+티커 쉼표 구분)


def fetch_index_prices_latest() -> list[dict]:           # 최신 ETF 가격 전체 조회
    """가장 최근 날짜의 ETF 가격/등락률 전체를 조회합니다."""
    client = get_client()                                # DB 연결 객체 가져오기
    # 최신 날짜 1건으로 날짜 확인
    latest = (
        client.table("index_price_raw")                  # 테이블 선택
        .select("___")                                   # Q37: 최신 날짜 확인용 컬럼명
        .order("date", desc=True)                        # 최신 먼저
        .limit(1)                                        # 1건만
        .execute()                                       # 실행
    )
    if not latest.data:                                  # 데이터 없으면
        return []                                        # 빈 리스트 반환
    latest_date = latest.data[0]["___"]                   # Q38: 날짜 컬럼 키명
    response = (
        client.table("index_price_raw")                  # 테이블 선택
        .select("*")                                     # 전체 컬럼
        .eq("date", ___)                                 # Q39: 위에서 추출한 최신 날짜 변수
        .execute()                                       # 실행
    )
    return response.data                                 # 전체 데이터 반환


# ── sector_cycle_result 테이블 ───────────────────────────────

def upsert_sector_cycle(record: dict) -> None:           # 경기국면 결과 저장
    """경기국면 분석 결과를 sector_cycle_result 테이블에 upsert합니다."""
    record = dict(record)                                # 원본 보호를 위해 복사
    # Q40: JSON 직렬화가 필요한 필드들 순회
    for key in ('probabilities', 'phase_sector_perf', 'phase_holding_perf',
                '___', '___'):                           # Q40~Q41
        if isinstance(record.get(key), (dict, ___)):     # Q42
            record[key] = json.dumps(record[key], ensure_ascii=False)  # JSON 문자열로 변환
    client = get_client()                                # DB 연결 객체 가져오기
    client.table("sector_cycle_result").upsert(record, on_conflict="date").execute()


def _parse_json_fields(record: dict, fields: list[str]) -> dict:  # JSON 역직렬화 헬퍼
    """DB에서 문자열로 저장된 JSON 필드를 dict/list로 역직렬화합니다."""
    record = dict(record)                                # 원본 보호를 위해 복사
    for f in fields:                                     # 각 필드 순회
        if isinstance(record.get(f), str):               # 문자열이면
            record[f] = json.___(record[f])              # Q43
    return record                                        # 파싱된 레코드 반환


# ── 페이지네이션 전체 조회 ───────────────────────────────────

def _fetch_all_pages(table: str, select: str, order_col: str = "date") -> list[dict]:
    """Supabase 1000행 제한을 우회하여 전체 데이터를 페이지네이션으로 조회합니다."""
    client = get_client()                                # DB 연결 객체 가져오기
    all_data = []                                        # 전체 결과 저장용
    page_size = ___                                      # Q44
    offset = ___                                         # Q45
    while True:                                          # 무한 반복 (마지막 페이지에서 break)
        response = (
            client.table(table)                          # 테이블 선택
            .select(select)                              # 조회할 컬럼
            .order(order_col, desc=False)                 # 오름차순 정렬
            .___( offset, offset + page_size - 1)        # Q46
            .execute()                                   # 실행
        )
        batch = response.data                            # 현재 페이지 결과
        all_data.___(batch)                              # Q47
        if len(batch) < ___:                             # Q48
            break                                        # 마지막 페이지면 종료
        offset += ___                                    # Q49
    return all_data                                      # 전체 데이터 반환


def fetch_crash_surge_all() -> list[dict]:               # 전체 crash/surge 조회
    """전체 crash/surge 히스토리를 날짜 오름차순으로 조회합니다."""
    return _fetch_all_pages(                             # 페이지네이션으로 전체 조회
        "___",                                           # Q50
        "date,crash_score,surge_score,net_score",        # 방향성 분석에 필요한 컬럼만
    )


# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                    |
# |----|-------------------------------|------------------------|
# | Q1 | import ___                    | json                   |
# | Q2 | from typing import ___        | Optional               |
# | Q3 | from ... import ___           | get_client             |
# | Q4 | ___()                         | get_client             |
# | Q5 | client.___("...")             | table                  |
# | Q6 | .___("macro_raw")             | macro_raw              |
# | Q7 | .___( records, ...)           | upsert                 |
# | Q8 | on_conflict="___"             | date                   |
# | Q9 | days: int = ___               | 756                    |
# | Q10| .___("*")                     | select                 |
# | Q11| desc=___                      | False                  |
# | Q12| .___(days)                    | limit                  |
# | Q13| .___()                        | execute                |
# | Q14| response.___                  | data                   |
# | Q15| record.get("___")            | probabilities          |
# | Q16| isinstance(..., ___)          | dict                   |
# | Q17| json.___( ...)                | dumps                  |
# | Q18| ___=False                     | ensure_ascii           |
# | Q19| on_conflict="___"             | date,index_name        |
# | Q20| isinstance(..., ___)          | str                    |
# | Q21| json.___(...)                 | loads                  |
# | Q22| index_name='___'              | sp500                  |
# | Q23| .___("index_name", ...)       | eq                     |
# | Q24| desc=___                      | True                   |
# | Q25| .limit(___)                   | 1                      |
# | Q26| response.data[___]            | 0                      |
# | Q27| else ___                      | None                   |
# | Q28| '___'                         | sp500                  |
# | Q29| '___'                         | ndx                    |
# | Q30| '___'                         | sox                    |
# | Q31| .table("___")                 | fear_greed_raw         |
# | Q32| on_conflict="___"             | date                   |
# | Q33| .select("___")               | *                      |
# | Q34| .order("___", ...)            | date                   |
# | Q35| response.___                  | data                   |
# | Q36| on_conflict="___"             | date,ticker            |
# | Q37| .select("___")               | date                   |
# | Q38| latest.data[0]["___"]         | date                   |
# | Q39| .eq("date", ___)             | latest_date            |
# | Q40| '___'                         | top3_sectors           |
# | Q41| '___'                         | macro_snapshot          |
# | Q42| (dict, ___)                   | list                   |
# | Q43| json.___( ...)                | loads                  |
# | Q44| page_size = ___               | 1000                   |
# | Q45| offset = ___                  | 0                      |
# | Q46| .___(offset, ...)             | range                  |
# | Q47| all_data.___(batch)           | extend                 |
# | Q48| len(batch) < ___              | page_size              |
# | Q49| offset += ___                 | page_size              |
# | Q50| "___"                         | crash_surge_result     |
# ============================================================
