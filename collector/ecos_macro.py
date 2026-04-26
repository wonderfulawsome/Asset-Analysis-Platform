"""한국은행 ECOS API — 기준금리·주담대 금리·주담대 잔액 수집.

ECOS REST 엔드포인트 형식:
  https://ecos.bok.or.kr/api/StatisticSearch/{API_KEY}/json/kr/
    {start}/{end}/{table_id}/{cycle}/{from_date}/{to_date}/{item_code}

cycle: D(일별), M(월별), Q(분기), A(연간).
응답: JSON — StatisticSearch.row 배열, 각 row 는 {TIME, DATA_VALUE, ITEM_NAME1, ...}.

지표별 통계표·항목 코드 (ECOS StatisticItemList 로 직접 확인한 값, 2026-04 기준):
  - 기준금리:           722Y001 / 0101000     (cycle=M)
  - 주담대 금리:        121Y006 / BECBLA0302  (cycle=M, 예금은행 신규취급 가중평균 - 주택담보대출)
  - 주담대 잔액:        151Y005 / 11110A0     (cycle=M, 예금은행 주택담보대출 잔액)

위 코드는 ECOS 변경 시 깨질 수 있어 fetch_ecos_series 호출 시 SPECS 외부 override 가능.
"""
import os
from datetime import date, timedelta

import httpx


ECOS_KEY = os.getenv("ECOS_API_KEY", "")
ECOS_URL = "https://ecos.bok.or.kr/api/StatisticSearch"

# 지표별 spec — 변경 시 한 곳만 수정하면 모든 fetch 함수가 따라감
SPECS = {
    "base_rate":        {"table": "722Y001", "item": "0101000",    "cycle": "M"},
    "mortgage_rate":    {"table": "121Y006", "item": "BECBLA0302", "cycle": "M"},
    "mortgage_balance": {"table": "151Y005", "item": "11110A0",    "cycle": "M"},
}


def fetch_ecos_series(metric: str, from_ym: str, to_ym: str) -> list[dict]:
    """단일 지표를 from_ym ~ to_ym(YYYYMM) 범위로 조회.

    반환: list of {date, value, cycle, metric}
    """
    if not ECOS_KEY:
        raise RuntimeError("ECOS_API_KEY 환경변수가 설정되지 않았습니다.")
    spec = SPECS[metric]

    # ECOS URL 은 REST path 형식 — query string 아님
    url = (
        f"{ECOS_URL}/{ECOS_KEY}/json/kr/1/100000/"
        f"{spec['table']}/{spec['cycle']}/"
        f"{from_ym}/{to_ym}/{spec['item']}"
    )
    r = httpx.get(url, timeout=20.0)
    r.raise_for_status()
    j = r.json()

    # 에러 응답: {"RESULT": {"CODE": "INFO-200", "MESSAGE": "..."}}
    if "RESULT" in j:
        raise ValueError(f"[ecos] {metric}: {j['RESULT']}")
    rows = j.get("StatisticSearch", {}).get("row", [])
    out = []
    for row in rows:
        # TIME 은 cycle 따라 형식 다름 — D: YYYYMMDD, M: YYYYMM, Q: YYYYQ#, A: YYYY
        t = row.get("TIME", "")
        d = _ecos_time_to_date(t, spec["cycle"])
        if not d:
            continue
        try:
            v = float(row.get("DATA_VALUE", "0"))
        except ValueError:
            continue
        out.append({
            "date": d,
            "value": v,
            "cycle": spec["cycle"],
            "metric": metric,
        })
    return out


def _ecos_time_to_date(t: str, cycle: str) -> str | None:
    """ECOS TIME 문자열 → YYYY-MM-DD ISO 형식. 잘못된 형식은 None."""
    if not t:
        return None
    if cycle == "D" and len(t) == 8:
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    if cycle == "M" and len(t) == 6:
        return f"{t[:4]}-{t[4:6]}-01"  # 월 데이터는 해당월 1일로 통일
    if cycle == "A" and len(t) == 4:
        return f"{t}-01-01"
    return None


def fetch_macro_rate_kr(from_ym: str = "", months: int = 24) -> list[dict]:
    """3개 지표 통합 — 한 행 = 한 날짜, 여러 컬럼 wide 형식으로 반환.

    날짜 누락된 지표는 해당 컬럼이 None.
    """
    if not from_ym:
        # 기본: 최근 N개월 (months) — to_ym 은 당월
        today = date.today()
        # 월별 빼기 — 정확히 calculate
        m = today.month - months
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        from_ym = f"{y:04d}{m:02d}"
    to_ym = date.today().strftime("%Y%m")

    # 3개 지표 각각 호출 후 date 기준 merge
    by_date: dict[str, dict] = {}
    for metric in SPECS.keys():
        try:
            for row in fetch_ecos_series(metric, from_ym, to_ym):
                d = row["date"]
                rec = by_date.setdefault(d, {"date": d, "cycle": row["cycle"]})
                # 잔액은 정수, 금리는 실수
                if metric == "mortgage_balance":
                    rec[metric] = int(row["value"])
                else:
                    rec[metric] = row["value"]
        except Exception as e:
            # 한 지표 실패해도 다른 지표는 진행 — 부분 결과 허용
            print(f"[ecos] {metric} 실패: {e}")

    # date 기준 정렬
    return [by_date[d] for d in sorted(by_date)]
