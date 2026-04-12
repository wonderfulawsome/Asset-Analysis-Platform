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