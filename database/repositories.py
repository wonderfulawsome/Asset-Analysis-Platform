import json
from typing import Optional
from database.supabase_client import get_client

### 테이블별 저장(upsert)/조회(fetch) 함수 모음

# ── macro_raw ──────────────────────────────────────────────

# get_client = supabase_client.py에서 db연결 객체를 변환하는 함수
# macro_raw 테이블에 records를 딕셔너리 형태로 저장
def upsert_macro(records: list[dict]) -> None:
    """거시 지표 데이터를 macro_raw 테이블에 upsert합니다. (date 기준)"""
    if not records:
        return
    client = get_client()
    client.table("macro_raw").upsert(records, on_conflict="date").execute()
    print(f"[DB] macro_raw {len(records)}건 upsert 완료")

# macro_raw에서 756일치를 조회하는 함수
def fetch_macro(days: int = 756) -> list[dict]:
    """최근 N일 거시 지표를 날짜 오름차순으로 조회합니다. (기본 3년 = 756일)"""
    client = get_client()
    response = (
        client.table("macro_raw")
        .select("*")
        .order("date", desc=False)
        .limit(days)
        .execute()
    )
    return response.data


# ── market_regime ──────────────────────────────────────────

#HMM 국면 결과의 확률값을 JSON 문자열로 변환한 뒤 market_regime 테이블에 날짜 기준으로 저장
# records: 주가의 딕셔너리 형태
def upsert_regime(record: dict) -> None:
    """HMM 국면 결과를 market_regime 테이블에 upsert합니다. (date 기준)"""
    # jsonb 필드는 문자열로 직렬화
    if isinstance(record.get("probabilities"), dict):
        record = dict(record)
        # records의 확률 칼럼을 json형태로 바꾸기
        record["probabilities"] = json.dumps(record["probabilities"], ensure_ascii=False)
    client = get_client()
    # market_regime에 확률(오늘국면) 저장 (date + index_name 기준)
    # market_regime 테이블에 인덱스의 record를 저장, date와 index_name 조합이 중복이면 덮어쓰기
    client.table("market_regime").upsert(record, on_conflict="date,index_name").execute()
    print(f"[DB] market_regime {record['date']} ({record.get('index_name', 'sp500')}) upsert 완료")

# DB에서 문자열로 저장된 probabilities 필드를 dict로 역직렬화합니다.
# API로 돌려줄때에는 dict형태여야 함.
def _parse_probabilities(record: dict) -> dict:
    if isinstance(record.get("probabilities"), str):
        record = dict(record)
        record["probabilities"] = json.loads(record["probabilities"])
    return record


# 특정 지수의 가장 최근 국면 1건 조회
def fetch_regime_current(index_name: str = 'sp500') -> Optional[dict]:
    client = get_client()
    response = (
        client.table("market_regime")
        .select("*")
        .eq("index_name", index_name)
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    return _parse_probabilities(response.data[0]) if response.data else None


# sp500, ndx, sox 3개 지수의 최신 국면을 한번에 조회
def fetch_regime_current_all() -> list[dict]:
    result = []
    for name in ['sp500', 'ndx', 'sox']:
        r = fetch_regime_current(name)
        if r:
            result.append(r)
    return result

# 가장 최근 거시 지표 1건을 조회
def fetch_macro_latest() -> Optional[dict]:
    """가장 최근 거시 지표 1건을 조회합니다."""
    client = get_client()
    response = (
        client.table("macro_raw")
        .select("*")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def fetch_macro_latest2() -> list:
    """최근 거시 지표 5건을 조회합니다 (주말/공휴일 폴백 대비)."""
    client = get_client()
    response = (
        client.table("macro_raw")
        .select("*")
        .order("date", desc=True)
        .limit(5)                                            # 주말+공휴일 고려하여 5건 조회
        .execute()
    )
    return response.data


# 특정 지수의 최근 N일 국면 히스토리를 날짜 내림차순으로 조회
def fetch_regime_history(days: int = 30, index_name: str = 'sp500') -> list[dict]:
    client = get_client()
    # 쿼리문으로 각 인덱스별 최근 30일치 가져오는 쿼리문
    response = (
        client.table("market_regime")
        .select("*")
        .eq("index_name", index_name)
        # 날짜 내림차순
        .order("date", desc=True)
        # 최대 30개 가져오기
        .limit(days)
        # 요청 실행
        .execute()
    )
    return [_parse_probabilities(r) for r in response.data]


# ── fear_greed_raw ──────────────────────────────────────────

# fear_greed_raw 테이블에 공포·탐욕 지수 데이터를 날짜 기준으로 저장
def upsert_fear_greed(record: dict) -> None:
    client = get_client()
    client.table("fear_greed_raw").upsert(record, on_conflict="date").execute()
    print(f"[DB] fear_greed_raw {record['date']} upsert 완료")


def fetch_fear_greed_latest() -> Optional[dict]:
    # supabase 연결 클라이언트 가져오기
    client = get_client()
    response = (
        # fear_greed_raw 테이블에서
        client.table("fear_greed_raw")
        # 모든 컬럼 선택
        .select("*")
        # 날짜 내림차순 정렬
        .order("date", desc=True)
        # 최신 1건만 조회
        .limit(1)
        # 요청 실행
        .execute()
    )
    # 데이터가 있으면 첫 번째 행 반환, 없으면 None
    return response.data[0] if response.data else None


def fetch_fear_greed_latest2() -> list:
    """최근 공포·탐욕 지수 2건을 조회합니다 (전일 대비용)."""
    client = get_client()
    response = (
        client.table("fear_greed_raw")
        .select("*")
        .order("date", desc=True)
        .limit(2)
        .execute()
    )
    return response.data


# ── index_price_raw ─────────────────────────────────────────

def upsert_index_prices(records: list[dict]) -> None:
    """ETF 가격/등락률을 index_price_raw 테이블에 upsert합니다. (date+ticker 기준)"""
    if not records:
        return
    client = get_client()
    client.table("index_price_raw").upsert(records, on_conflict="date,ticker").execute()
    print(f"[DB] index_price_raw {len(records)}건 upsert 완료")


def fetch_index_prices_latest() -> list[dict]:
    """가장 최근 날짜의 ETF 가격/등락률 전체를 조회합니다."""
    client = get_client()
    # 최신 날짜 1건으로 날짜를 확인
    latest = (
        client.table("index_price_raw")
        .select("date")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    if not latest.data:
        return []
    latest_date = latest.data[0]["date"]
    response = (
        client.table("index_price_raw")
        .select("*")
        .eq("date", latest_date)
        .execute()
    )
    return response.data

# ── sector_macro_raw ──────────────────────────────────────────

def upsert_sector_macro(records: list[dict]) -> None:
    """섹터 매크로 지표를 sector_macro_raw 테이블에 upsert합니다. (date 기준)"""
    if not records:
        return
    client = get_client()
    client.table("sector_macro_raw").upsert(records, on_conflict="date").execute()
    print(f"[DB] sector_macro_raw {len(records)}건 upsert 완료")


# ── sector_cycle_result ───────────────────────────────────────

def upsert_sector_cycle(record: dict) -> None:
    """경기국면 분석 결과를 sector_cycle_result 테이블에 upsert합니다. (date 기준)"""
    record = dict(record)
    for key in ('probabilities', 'phase_sector_perf', 'phase_holding_perf',
                'top3_sectors', 'macro_snapshot'):
        if isinstance(record.get(key), (dict, list)):
            record[key] = json.dumps(record[key], ensure_ascii=False)
    client = get_client()
    client.table("sector_cycle_result").upsert(record, on_conflict="date").execute()
    print(f"[DB] sector_cycle_result {record['date']} upsert 완료")


def _parse_json_fields(record: dict, fields: list[str]) -> dict:
    """DB에서 문자열로 저장된 JSON 필드를 dict/list로 역직렬화합니다."""
    record = dict(record)
    for f in fields:
        if isinstance(record.get(f), str):
            record[f] = json.loads(record[f])
    return record


_SECTOR_JSON_FIELDS = ['probabilities', 'phase_sector_perf', 'phase_holding_perf',
                       'top3_sectors', 'macro_snapshot']


def fetch_sector_cycle_latest() -> Optional[dict]:
    """가장 최근 경기국면 분석 결과 1건을 조회합니다."""
    client = get_client()
    response = (
        client.table("sector_cycle_result")
        .select("*")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    return _parse_json_fields(response.data[0], _SECTOR_JSON_FIELDS)


def fetch_sector_cycle_history(days: int = 12) -> list[dict]:
    """최근 N건의 경기국면 히스토리를 날짜 내림차순으로 조회합니다."""
    client = get_client()
    response = (
        client.table("sector_cycle_result")
        .select("*")
        .order("date", desc=True)
        .limit(days)
        .execute()
    )
    return [_parse_json_fields(r, _SECTOR_JSON_FIELDS) for r in response.data]


# ── noise_regime ──────────────────────────────────────────

_NR_JSON_FIELDS = ['probabilities', 'feature_contributions', 'feature_values']


def upsert_noise_regime(record: dict) -> None:
    """Noise vs Signal 국면 결과를 noise_regime 테이블에 upsert합니다. (date 기준)"""
    record = dict(record)
    for key in _NR_JSON_FIELDS:
        if isinstance(record.get(key), (dict, list)):
            record[key] = json.dumps(record[key], ensure_ascii=False)
    client = get_client()
    try:
        client.table("noise_regime").upsert(record, on_conflict="date").execute()
    except Exception as e:
        if 'schema cache' in str(e) or 'column' in str(e).lower():
            # 새 JSONB 컬럼이 아직 DB에 없으면 해당 필드 제거 후 재시도
            for key in ('feature_contributions', 'feature_values'):
                record.pop(key, None)
            client.table("noise_regime").upsert(record, on_conflict="date").execute()
            print(f"[DB] noise_regime {record['date']} upsert 완료 (JSONB 컬럼 미존재, 기본 필드만 저장)")
            return
        raise
    print(f"[DB] noise_regime {record['date']} upsert 완료")


def fetch_noise_regime_current() -> Optional[dict]:
    """최신 noise regime 1건을 조회합니다. (단일 객체 반환)"""
    client = get_client()
    response = (
        client.table("noise_regime")
        .select("*")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    return _parse_json_fields(response.data[0], _NR_JSON_FIELDS)


def fetch_noise_regime_history(days: int = 30) -> list[dict]:
    """최근 N건의 noise regime 히스토리를 날짜 내림차순으로 조회합니다."""
    client = get_client()
    response = (
        client.table("noise_regime")
        .select("*")
        .order("date", desc=True)
        .limit(days)
        .execute()
    )
    return [_parse_json_fields(r, _NR_JSON_FIELDS) for r in response.data]


def fetch_noise_regime_all() -> list[dict]:
    """noise_regime 테이블의 전체 레코드를 조회합니다. (백필 시 기존 날짜 확인용)"""
    client = get_client()                              # Supabase 클라이언트
    response = (
        client.table("noise_regime")
        .select("date")                                # 날짜 컬럼만 조회 (경량)
        .order("date", desc=True)                      # 최신순 정렬
        .limit(1000)                                   # 최대 1000건
        .execute()
    )
    return response.data                               # [{date: '2026-03-16'}, ...] 반환


# ── crash_surge_result ──────────────────────────────────────────

_CS_JSON_FIELDS = ['shap_values', 'feature_importance', 'feature_values']


def upsert_crash_surge(record: dict) -> None:
    """폭락/급등 전조 결과를 crash_surge_result 테이블에 upsert합니다. (date 기준)"""
    record = dict(record)
    for key in _CS_JSON_FIELDS:
        if isinstance(record.get(key), (dict, list)):
            record[key] = json.dumps(record[key], ensure_ascii=False)
    client = get_client()
    try:
        client.table("crash_surge_result").upsert(record, on_conflict="date").execute()
    except Exception as e:
        if 'schema cache' in str(e) or 'column' in str(e).lower():
            # 새 JSONB 컬럼이 아직 DB에 없으면 해당 필드 제거 후 재시도
            for key in ('shap_values', 'feature_importance', 'feature_values'):
                record.pop(key, None)
            client.table("crash_surge_result").upsert(record, on_conflict="date").execute()
            print(f"[DB] crash_surge_result {record['date']} upsert 완료 (JSONB 컬럼 미존재, 기본 필드만 저장)")
            return
        raise
    print(f"[DB] crash_surge_result {record['date']} upsert 완료")


def fetch_crash_surge_current() -> Optional[dict]:
    """최신 crash/surge 결과 1건을 조회합니다."""
    client = get_client()
    response = (
        client.table("crash_surge_result")
        .select("*")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    return _parse_json_fields(response.data[0], _CS_JSON_FIELDS)


def fetch_crash_surge_history(days: int = 30) -> list[dict]:
    """최근 N건의 crash/surge 히스토리를 날짜 내림차순으로 조회합니다."""
    client = get_client()
    response = (
        client.table("crash_surge_result")
        .select("*")
        .order("date", desc=True)
        .limit(days)
        .execute()
    )
    return [_parse_json_fields(r, _CS_JSON_FIELDS) for r in response.data]


def _fetch_all_pages(table: str, select: str, order_col: str = "date") -> list[dict]:
    """Supabase 1000행 제한을 우회하여 전체 데이터를 페이지네이션으로 조회합니다."""
    client = get_client()                                # Supabase 클라이언트
    all_data = []                                        # 전체 결과 저장용
    page_size = 1000                                     # 한 번에 가져올 행 수
    offset = 0                                           # 시작 위치
    while True:
        response = (
            client.table(table)
            .select(select)                              # 조회할 컬럼
            .order(order_col, desc=False)                # 오름차순 정렬
            .range(offset, offset + page_size - 1)       # 페이지 범위 지정
            .execute()
        )
        batch = response.data                            # 현재 페이지 결과
        all_data.extend(batch)                           # 전체 결과에 추가
        if len(batch) < page_size:                       # 마지막 페이지면 종료
            break
        offset += page_size                              # 다음 페이지로 이동
    return all_data                                      # 전체 데이터 반환


def fetch_crash_surge_all() -> list[dict]:
    """전체 crash/surge 히스토리를 날짜 오름차순으로 조회합니다. (방향성 분석용)"""
    return _fetch_all_pages(                             # 페이지네이션으로 전체 조회
        "crash_surge_result",                            # 테이블명
        "date,crash_score,surge_score,net_score",        # 방향성 분석에 필요한 컬럼만
    )


def fetch_macro_closes() -> list[dict]:
    """전체 SPY 종가를 날짜 오름차순으로 조회합니다. (방향성 분석용)"""
    return _fetch_all_pages(                             # 페이지네이션으로 전체 조회
        "macro_raw",                                     # 테이블명
        "date,sp500_close",                              # 날짜와 종가만
    )


############ Supabase DB의 각 테이블에 데이터를 저장(upsert)하고 조회(fetch)하는 함수들을 모아놓은 파일