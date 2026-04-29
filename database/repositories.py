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
    """가장 최근 날짜의 ETF 가격/등락률 전체를 조회합니다.
    change_pct가 모두 0인 날짜(비거래일/장 시작 전)는 건너뛰고
    실제 거래 데이터가 있는 가장 최근 날짜를 반환합니다.
    """
    client = get_client()
    # change_pct > 0 또는 < 0 인 행에서 가장 최근 날짜를 직접 찾기
    nz = (
        client.table("index_price_raw")
        .select("date")
        .or_("change_pct.gt.0,change_pct.lt.0")
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    if nz.data:
        target_date = nz.data[0]["date"]
    else:
        # 전부 0이면 가장 최근 날짜 사용
        latest = (
            client.table("index_price_raw")
            .select("date")
            .order("date", desc=True)
            .limit(1)
            .execute()
        )
        if not latest.data:
            return []
        target_date = latest.data[0]["date"]

    response = (
        client.table("index_price_raw")
        .select("*")
        .eq("date", target_date)
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


def fetch_sector_macro_history(limit: int = 120) -> list[dict]:
    """sector_macro_raw에서 최근 N건 매크로 지표를 날짜 오름차순으로 조회합니다."""
    client = get_client()
    response = (
        client.table("sector_macro_raw")
        .select("date,pmi,yield_spread,anfci,icsa_yoy,permit_yoy,real_retail_yoy,capex_yoy,real_income_yoy")
        .order("date", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(response.data))


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


def _flip_noise_record(record: Optional[dict]) -> Optional[dict]:
    """DB 저장 부호(양수=감정) → 표시 부호(양수=이성) 변환.

    DB 컬럼 noise_score 와 feature_contributions[*].contribution 의 부호를 반전.
    regime_name 은 그대로 — '일치/불일치' 단어 의미는 두 컨벤션에서 공통이라서:
        DB ns=-0.9 (옛 이성), regime='일치' → 반전 후 +0.9 (새 이성), '일치' ✓
        DB ns=+1.6 (옛 감정), regime='불일치' → 반전 후 -1.6 (새 감정), '불일치' ✓
    """
    if record is None:
        return None
    if record.get('noise_score') is not None:
        record['noise_score'] = round(-float(record['noise_score']), 4)
    fc = record.get('feature_contributions')
    if isinstance(fc, list):
        for c in fc:
            if c.get('contribution') is not None:
                c['contribution'] = round(-float(c['contribution']), 4)
    return record


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
    return _flip_noise_record(_parse_json_fields(response.data[0], _NR_JSON_FIELDS))


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
    return [_flip_noise_record(_parse_json_fields(r, _NR_JSON_FIELDS)) for r in response.data]


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


# ── chart_predict_result ──────────────────────────────────

def upsert_chart_predict(record: dict) -> None:
    """앙상블 예측 결과를 chart_predict_result 테이블에 upsert합니다. (date+ticker 기준)"""
    record = dict(record)
    for key in ('actual', 'predicted'):
        if isinstance(record.get(key), list):
            record[key] = json.dumps(record[key], ensure_ascii=False)
    client = get_client()
    client.table("chart_predict_result").upsert(record, on_conflict="date,ticker").execute()
    print(f"[DB] chart_predict_result {record['date']} ({record['ticker']}) upsert 완료")


def fetch_chart_predict(ticker: str) -> Optional[dict]:
    """특정 티커의 최신 앙상블 예측 결과를 조회합니다."""
    client = get_client()
    response = (
        client.table("chart_predict_result")
        .select("*")
        .eq("ticker", ticker)
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    row = response.data[0]
    for key in ('actual', 'predicted'):
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    return row


# ── user_visit ──────────────────────────────────────────

def track_user_visit(user_hash: str, visit_date: str) -> dict:
    """사용자 방문을 기록하고 신규/재방문 여부를 반환합니다.
    Returns: {"is_new": bool, "user_hash": str, "visit_date": str}
    """
    client = get_client()
    # 해당 해시가 DB에 이미 존재하는지 확인 (과거 어떤 날짜든)
    existing = (
        client.table("user_visit")
        .select("id")
        .eq("user_hash", user_hash)
        .limit(1)
        .execute()
    )
    is_new = len(existing.data) == 0

    # 오늘 방문 기록 upsert (같은 날 중복 방문은 무시)
    record = {"user_hash": user_hash, "visit_date": visit_date, "is_new": is_new}
    client.table("user_visit").upsert(record, on_conflict="user_hash,visit_date").execute()
    print(f"[DB] user_visit {user_hash[:8]}... ({visit_date}) {'신규' if is_new else '재방문'}")
    return record


def fetch_dau(date: str) -> int:
    """특정 날짜의 DAU(일간 활성 사용자 수)를 반환합니다."""
    client = get_client()
    response = (
        client.table("user_visit")
        .select("user_hash")
        .eq("visit_date", date)
        .execute()
    )
    return len(response.data)


def fetch_mau(year_month: str) -> int:
    """특정 월의 MAU(월간 활성 사용자 수)를 반환합니다.
    year_month: 'YYYY-MM' 형식 (예: '2026-03')
    """
    client = get_client()
    start_date = f"{year_month}-01"
    # 월 말일 계산: 다음 달 1일 전날
    year, month = map(int, year_month.split("-"))
    if month == 12:
        end_date = f"{year + 1}-01-01"
    else:
        end_date = f"{year}-{month + 1:02d}-01"
    response = (
        client.table("user_visit")
        .select("user_hash")
        .gte("visit_date", start_date)
        .lt("visit_date", end_date)
        .execute()
    )
    # 고유 해시 수 계산
    unique_hashes = set(r["user_hash"] for r in response.data)
    return len(unique_hashes)


def fetch_user_stats(date: str, year_month: str) -> dict:
    """DAU, MAU, 신규/재방문 사용자 수를 한번에 조회합니다."""
    client = get_client()

    # DAU: 해당 날짜의 고유 사용자
    dau_resp = (
        client.table("user_visit")
        .select("user_hash")
        .eq("visit_date", date)
        .execute()
    )
    dau = len(dau_resp.data)

    # 당일 신규 사용자 수
    new_resp = (
        client.table("user_visit")
        .select("user_hash")
        .eq("visit_date", date)
        .eq("is_new", True)
        .execute()
    )
    new_users = len(new_resp.data)

    # MAU: 해당 월의 고유 사용자
    start_date = f"{year_month}-01"
    year, month = map(int, year_month.split("-"))
    if month == 12:
        end_date = f"{year + 1}-01-01"
    else:
        end_date = f"{year}-{month + 1:02d}-01"
    mau_resp = (
        client.table("user_visit")
        .select("user_hash")
        .gte("visit_date", start_date)
        .lt("visit_date", end_date)
        .execute()
    )
    unique_hashes = set(r["user_hash"] for r in mau_resp.data)
    mau = len(unique_hashes)

    # ── 누적 통계 ──
    # 전체 고유 사용자 (distinct user_hash)
    all_users_resp = (
        client.table("user_visit")
        .select("user_hash, visit_date")
        .execute()
    )
    all_hashes = set(r["user_hash"] for r in all_users_resp.data)
    total_users = len(all_hashes)
    total_visits = len(all_users_resp.data)

    # 전체 기간 일별 신규 사용자 추이 (누적 그래프용)
    # 각 user_hash의 최초 방문일 계산
    from datetime import datetime, timedelta
    first_visit = {}
    for r in all_users_resp.data:
        h, d = r["user_hash"], r.get("visit_date", "")
        if d and (h not in first_visit or d < first_visit[h]):
            first_visit[h] = d

    # 날짜별 신규 유입 수 집계
    daily_new = {}
    for d in first_visit.values():
        daily_new[d] = daily_new.get(d, 0) + 1

    # 전체 기간 누적 차트 생성
    if daily_new:
        sorted_dates = sorted(daily_new.keys())
        first_date = sorted_dates[0]
        end_dt = datetime.strptime(date, "%Y-%m-%d")
        start_dt = datetime.strptime(first_date, "%Y-%m-%d")
        cumulative_chart = []
        running = 0
        dt = start_dt
        while dt <= end_dt:
            ds = dt.strftime("%Y-%m-%d")
            running += daily_new.get(ds, 0)
            cumulative_chart.append({"date": ds, "total": running})
            dt += timedelta(days=1)
    else:
        cumulative_chart = []

    return {
        "date": date,
        "year_month": year_month,
        "dau": dau,
        "mau": mau,
        "new_users": new_users,
        "returning_users": dau - new_users,
        "total_users": total_users,
        "total_visits": total_visits,
        "cumulative_chart": cumulative_chart,
    }


############ Supabase DB의 각 테이블에 데이터를 저장(upsert)하고 조회(fetch)하는 함수들을 모아놓은 파일


# ── real_estate_trade_raw ──────────────────────────────────────────

def upsert_re_trades(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("real_estate_trade_raw").upsert(
        records, on_conflict="apt_seq,deal_date,floor,exclu_use_ar"
    ).execute()
    print(f"[DB] real_estate_trade_raw {len(records)}건 upsert 완료")


def fetch_re_trades(sgg_cd: str, ym: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("real_estate_trade_raw")
        .select("*")
        .eq("sgg_cd", sgg_cd)
        .eq("deal_ym", ym)
        .order("deal_date", desc=False)
        .execute()
    )
    return response.data


# ── real_estate_rent_raw ──────────────────────────────────────────

def upsert_re_rents(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("real_estate_rent_raw").upsert(
        records, on_conflict="apt_seq,deal_date,floor,exclu_use_ar,deposit,monthly_rent"
    ).execute()
    print(f"[DB] real_estate_rent_raw {len(records)}건 upsert 완료")


def fetch_re_rents(sgg_cd: str, ym: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("real_estate_rent_raw")
        .select("*")
        .eq("sgg_cd", sgg_cd)
        .eq("deal_ym", ym)
        .order("deal_date", desc=False)
        .execute()
    )
    return response.data


# ── mois_population ──────────────────────────────────────────

def upsert_mois_population(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("mois_population").upsert(
        records, on_conflict="stats_ym,stdg_cd"
    ).execute()
    print(f"[DB] mois_population {len(records)}건 upsert 완료")


def fetch_mois_population(sgg_cd: str, ym: str) -> list[dict]:
    # stdg_cd는 10자리인데 앞 5자리가 sgg_cd — LIKE로 시군구 단위 필터링
    client = get_client()
    response = (
        client.table("mois_population")
        .select("*")
        .like("stdg_cd", f"{sgg_cd}%")
        .eq("stats_ym", ym)
        .execute()
    )
    return response.data


# ── mois_household_by_size ──────────────────────────────────────────

def upsert_mois_household(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("mois_household_by_size").upsert(
        records, on_conflict="stats_ym,admm_cd"
    ).execute()
    print(f"[DB] mois_household_by_size {len(records)}건 upsert 완료")


def fetch_mois_household(sgg_cd: str, ym: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("mois_household_by_size")
        .select("*")
        .like("admm_cd", f"{sgg_cd}%")
        .eq("stats_ym", ym)
        .execute()
    )
    return response.data


# ── stdg_admm_mapping ──────────────────────────────────────────

def upsert_stdg_admm_mapping(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("stdg_admm_mapping").upsert(
        records, on_conflict="ref_ym,stdg_cd,admm_cd"
    ).execute()
    print(f"[DB] stdg_admm_mapping {len(records)}건 upsert 완료")


def fetch_stdg_admm_mapping(sgg_cd: str, ref_ym: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("stdg_admm_mapping")
        .select("*")
        .like("stdg_cd", f"{sgg_cd}%")
        .eq("ref_ym", ref_ym)
        .execute()
    )
    return response.data


# ── geo_stdg ──────────────────────────────────────────

def upsert_geo_stdg(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("geo_stdg").upsert(records, on_conflict="stdg_cd").execute()
    print(f"[DB] geo_stdg {len(records)}건 upsert 완료")


def fetch_geo_stdg(sgg_cd: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("geo_stdg")
        .select("stdg_cd,lat,lng")
        .like("stdg_cd", f"{sgg_cd}%")
        .execute()
    )
    return response.data


# ── region_summary ──────────────────────────────────────────

def upsert_region_summary(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("region_summary").upsert(
        records, on_conflict="stdg_cd,stats_ym"
    ).execute()
    print(f"[DB] region_summary {len(records)}건 upsert 완료")


def fetch_region_summary(sgg_cd: str, ym: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("region_summary")
        .select("*")
        .eq("sgg_cd", sgg_cd)
        .eq("stats_ym", ym)
        .order("median_price_per_py", desc=True)
        .execute()
    )
    return response.data


def fetch_region_timeseries(sgg_cd: str) -> list[dict]:
    """시군구의 전체 월별 집계 — 시계열 차트용 (최근 → 과거 순)."""
    client = get_client()
    response = (
        client.table("region_summary")
        .select("*")
        .eq("sgg_cd", sgg_cd)
        .order("stats_ym", desc=False)
        .execute()
    )
    return response.data


def fetch_region_by_stdg_cd(stdg_cd: str, ym: str) -> dict | None:
    """단일 법정동 region_summary 한 행 — UNIQUE(stdg_cd, stats_ym) 보장됨."""
    client = get_client()
    response = (
        client.table("region_summary")
        .select("*")
        .eq("stdg_cd", stdg_cd)
        .eq("stats_ym", ym)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def fetch_region_timeseries_by_stdg(stdg_cd: str, months: int = 12) -> list[dict]:
    """법정동의 월별 집계 — 시계열 차트용. months 만큼만 최근 데이터 (과거→최근 정렬)."""
    client = get_client()
    response = (
        client.table("region_summary")
        .select("*")
        .eq("stdg_cd", stdg_cd)
        .order("stats_ym", desc=True)
        .limit(months)
        .execute()
    )
    # desc 로 받았으니 뒤집어 ASC 반환
    return list(reversed(response.data))


def fetch_complex_compare(apt_seqs: list[str], months: int = 12) -> list[dict]:
    """단지(apt_seq) 별 12개월 시계열 — 평단가·거래량·전세가율.

    매매: real_estate_trade_raw 에서 apt_seq + deal_ym groupby → median 평단가, count.
    전세: real_estate_rent_raw monthly_rent=0 만 → avg 보증금.
    전세가율 = avg(전세 보증금) / avg(매매 거래금액). 둘 중 하나 없으면 None.
    """
    from statistics import median
    from collections import defaultdict
    from datetime import date, timedelta
    if not apt_seqs:
        return []
    client = get_client()
    # 최근 N개월 ym 리스트
    today = date.today()
    cur = today.replace(day=1) - timedelta(days=1)
    yms: list[str] = []
    for _ in range(months):
        yms.append(cur.strftime("%Y%m"))
        cur = cur.replace(day=1) - timedelta(days=1)
    yms.reverse()  # 과거→최근

    # 매매: apt_seq + deal_ym → 평단가 리스트 + 평균 거래금액 (전세가율용)
    trade_resp = (
        client.table("real_estate_trade_raw")
        .select("apt_seq,apt_nm,build_year,sgg_cd,umd_nm,deal_ym,deal_amount,exclu_use_ar")
        .in_("apt_seq", apt_seqs)
        .in_("deal_ym", yms)
        .execute()
    )
    trade_buckets: dict[tuple, list[float]] = defaultdict(list)
    sale_amount_buckets: dict[tuple, list[int]] = defaultdict(list)
    meta: dict[str, dict] = {}
    for r in trade_resp.data:
        seq = r["apt_seq"]; ym = r["deal_ym"]
        ar = r.get("exclu_use_ar") or 0
        amt = r.get("deal_amount") or 0
        if not seq or not ym or ar <= 0 or amt <= 0:
            continue
        trade_buckets[(seq, ym)].append(amt / (ar / 3.305785))
        sale_amount_buckets[(seq, ym)].append(amt)
        meta.setdefault(seq, {
            "apt_nm": r.get("apt_nm"),
            "build_year": r.get("build_year"),
            "sgg_cd": r.get("sgg_cd"),
            "umd_nm": r.get("umd_nm"),
        })

    # 전세: monthly_rent=0 만, 보증금 평균 (전세가율 산출용)
    rent_resp = (
        client.table("real_estate_rent_raw")
        .select("apt_seq,deal_ym,deposit,monthly_rent")
        .in_("apt_seq", apt_seqs)
        .in_("deal_ym", yms)
        .eq("monthly_rent", 0)
        .execute()
    )
    jeonse_buckets: dict[tuple, list[int]] = defaultdict(list)
    for r in rent_resp.data:
        seq = r.get("apt_seq"); ym = r.get("deal_ym")
        dep = r.get("deposit") or 0
        if seq and ym and dep > 0:
            jeonse_buckets[(seq, ym)].append(dep)

    # 단지별 시계열 만들기 (모든 ym 채우기 — 거래 없으면 None)
    out = []
    for seq in apt_seqs:
        m = meta.get(seq, {})
        ts = []
        for ym in yms:
            prices = trade_buckets.get((seq, ym), [])
            sales = sale_amount_buckets.get((seq, ym), [])
            jeonses = jeonse_buckets.get((seq, ym), [])
            avg_sale = (sum(sales) / len(sales)) if sales else None
            avg_jeonse = (sum(jeonses) / len(jeonses)) if jeonses else None
            jeonse_rate = (avg_jeonse / avg_sale) if (avg_jeonse and avg_sale) else None
            ts.append({
                "ym": ym,
                "median_price_per_py": round(median(prices), 0) if prices else None,
                "trade_count": len(prices),
                "avg_sale": round(avg_sale, 0) if avg_sale else None,
                "avg_jeonse": round(avg_jeonse, 0) if avg_jeonse else None,
                "jeonse_rate": round(jeonse_rate, 4) if jeonse_rate else None,
            })
        out.append({
            "apt_seq": seq,
            "apt_nm": m.get("apt_nm"),
            "build_year": m.get("build_year"),
            "sgg_cd": m.get("sgg_cd"),
            "umd_nm": m.get("umd_nm"),
            "timeseries": ts,
        })
    return out


def fetch_complex_summary_by_stdg(stdg_cd: str, ym: str, top: int = 10) -> list[dict]:
    """법정동 단지(apt_seq) 단위 요약 — 평단가 내림차순 top N.

    real_estate_trade_raw 에서 (stdg_cd, deal_ym) 필터로 최근 거래만 가져와
    Python 측에서 apt_seq groupby 평균 평단가·거래수·apt_nm·build_year 계산.
    """
    from statistics import median
    from collections import defaultdict
    client = get_client()
    # 최근 3개월 윈도우 — ym 포함 + 직전 2개월
    y, m = int(ym[:4]), int(ym[4:6])
    yms = []
    for _ in range(3):
        yms.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    response = (
        client.table("real_estate_trade_raw")
        .select("apt_seq,apt_nm,build_year,deal_amount,exclu_use_ar")
        .eq("stdg_cd", stdg_cd)
        .in_("deal_ym", yms)
        .execute()
    )
    bucket: dict[str, list] = defaultdict(list)
    meta: dict[str, dict] = {}
    for r in response.data:
        seq = r.get("apt_seq")
        if not seq:
            continue
        ar = r.get("exclu_use_ar") or 0
        amt = r.get("deal_amount") or 0
        if ar <= 0 or amt <= 0:
            continue
        # 만원/평 = 거래금액 / (전용면적 / 3.305785)
        bucket[seq].append(amt / (ar / 3.305785))
        # 메타는 첫 등장값으로 (단지 정보는 거래마다 같음)
        meta.setdefault(seq, {"apt_nm": r.get("apt_nm"), "build_year": r.get("build_year")})
    out = []
    for seq, prices in bucket.items():
        out.append({
            "apt_seq": seq,
            "apt_nm": meta[seq]["apt_nm"],
            "build_year": meta[seq]["build_year"],
            "trade_count": len(prices),
            "median_price_per_py": round(median(prices), 0),
        })
    out.sort(key=lambda x: x["median_price_per_py"], reverse=True)
    return out[:top]


# ── buy_signal_result ──────────────────────────────────────────

def upsert_buy_signal(record: dict) -> None:
    """매수 시그널 레코드 upsert — UNIQUE(sgg_cd, stats_ym)."""
    if not record:
        return
    client = get_client()
    client.table("buy_signal_result").upsert(
        record, on_conflict="sgg_cd,stats_ym"
    ).execute()


def fetch_buy_signal(sgg_cd: str, ym: str | None = None) -> dict | None:
    """ym 미지정 시 가장 최근 시그널 1건 반환."""
    client = get_client()
    q = client.table("buy_signal_result").select("*").eq("sgg_cd", sgg_cd)
    if ym:
        q = q.eq("stats_ym", ym)
    response = q.order("stats_ym", desc=True).limit(1).execute()
    return response.data[0] if response.data else None


def fetch_buy_signal_history(sgg_cd: str) -> list[dict]:
    """시군구의 시그널 시계열 (과거 → 최근)."""
    client = get_client()
    response = (
        client.table("buy_signal_result")
        .select("*")
        .eq("sgg_cd", sgg_cd)
        .order("stats_ym", desc=False)
        .execute()
    )
    return response.data


# ── macro_rate_kr (ECOS) ──────────────────────────────────────────

def upsert_macro_rate_kr(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("macro_rate_kr").upsert(records, on_conflict="date").execute()
    print(f"[DB] macro_rate_kr {len(records)}건 upsert 완료")


def fetch_macro_rate_kr(months: int = 24) -> list[dict]:
    """최근 N개월 ECOS 시계열 (date ASC)."""
    client = get_client()
    response = (
        client.table("macro_rate_kr")
        .select("*")
        .order("date", desc=False)
        .limit(months * 31)  # 일별/월별 혼재 대비 여유분
        .execute()
    )
    return response.data


# ── region_migration (KOSIS) ──────────────────────────────────────

def upsert_region_migration(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("region_migration").upsert(
        records, on_conflict="sgg_cd,stats_ym"
    ).execute()
    print(f"[DB] region_migration {len(records)}건 upsert 완료")


def fetch_region_migration(sgg_cd: str) -> list[dict]:
    """시군구의 인구이동 시계열 (과거 → 최근)."""
    client = get_client()
    response = (
        client.table("region_migration")
        .select("*")
        .eq("sgg_cd", sgg_cd)
        .order("stats_ym", desc=False)
        .execute()
    )
    return response.data


# ── sector_valuation ──────────────────────────────────────────

def upsert_sector_valuation(records: list[dict]) -> None:
    """11개 섹터 ETF 의 PER/PBR upsert."""
    if not records:
        return
    client = get_client()
    client.table("sector_valuation").upsert(
        records, on_conflict="date,ticker"
    ).execute()
    print(f"[DB] sector_valuation {len(records)}건 upsert 완료")


def fetch_sector_valuation_history(days: int = 365 * 5) -> list[dict]:
    """sector_valuation 테이블의 최근 N일치 모든 ticker 시계열.

    각 ticker 의 historical mean/stdev 산출용. 테이블 없거나 비어있으면 [].
    """
    from datetime import date, timedelta
    client = get_client()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    try:
        response = (
            client.table("sector_valuation")
            .select("date, ticker, per, pbr")
            .gte("date", cutoff)
            .order("date", desc=False)
            .execute()
        )
    except Exception as e:
        print(f"[DB] sector_valuation history 조회 실패: {e}")
        return []
    return response.data or []


def fetch_sector_valuation_latest() -> list[dict]:
    """가장 최근 date 의 12개 섹터 밸류에이션 행. 테이블 미생성/빈 상태면 []."""
    client = get_client()
    try:
        last = (
            client.table("sector_valuation")
            .select("date")
            .order("date", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        # PGRST205: 테이블 없음 — DDL 미실행 시
        print(f"[DB] sector_valuation 조회 실패 (테이블 없음 가능): {e}")
        return []
    if not last.data:
        return []
    target = last.data[0]["date"]
    response = (
        client.table("sector_valuation")
        .select("*")
        .eq("date", target)
        .execute()
    )
    return response.data


# ── valuation_signal (ERP / Fed Model) ─────────────────────────

def upsert_valuation_signal(record: dict) -> None:
    """ERP 1행 upsert (date UNIQUE)."""
    if not record:
        return
    client = get_client()
    client.table("valuation_signal").upsert(
        record, on_conflict="date"
    ).execute()


def upsert_valuation_signal_bulk(records: list[dict]) -> None:
    """30일 backfill 등 다행 일괄 upsert."""
    if not records:
        return
    client = get_client()
    for i in range(0, len(records), 200):
        client.table("valuation_signal").upsert(
            records[i:i + 200], on_conflict="date"
        ).execute()


def fetch_valuation_signal_latest() -> dict | None:
    """가장 최근 1건. 없으면 None."""
    client = get_client()
    try:
        r = (
            client.table("valuation_signal")
            .select("*")
            .order("date", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        print(f"[DB] valuation_signal latest 실패: {e}")
        return None
    return r.data[0] if r.data else None


def fetch_valuation_signal_history(days: int = 30) -> list[dict]:
    """최근 N 거래일 historical (오래된 → 최신)."""
    client = get_client()
    try:
        r = (
            client.table("valuation_signal")
            .select("*")
            .order("date", desc=True)
            .limit(days)
            .execute()
        )
    except Exception as e:
        print(f"[DB] valuation_signal history 실패: {e}")
        return []
    return list(reversed(r.data or []))