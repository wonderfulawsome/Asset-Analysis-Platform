"""통계청 KOSIS API — 거시경제 탭(sector cycle) 전용 KR 거시 4종.

US sector_macro.py 의 일부 FRED 시리즈 등가:
  kr_indpro  ← INDPRO 등가, 광공업생산지수    (orgId=101, tblId=DT_1F31501)
  kr_retail  ← RRSFS 등가, 소매판매액지수      (orgId=101, tblId=DT_1KS1003)
  kr_capex   ← ANDENO 등가, 설비투자지수      (orgId=101, tblId=DT_1F31503)
  kr_permit  ← PERMIT 등가, 건축허가 면적      (orgId=116, tblId=DT_MLTM_5345)

⚠️ tblId/itmId 코드는 KOSIS 통계지표 검색에서 1회 sweep 검증 권장 (변경 빈도 높음).
실패 시 try/except 안에서 빈 시계열 반환 — sector_macro_kr aggregator 가 부재 컬럼 NaN 처리.

패턴: collector/kosis_migration.py 의 KOSIS_KEY + httpx.get + JSON 파싱 그대로 재사용.
"""
import os
from datetime import date

import httpx


KOSIS_KEY = os.getenv("KOSIS_API_KEY", "")
KOSIS_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"

# 4 거시 시리즈 spec — orgId/tblId/itmId/objL1.
# objL1 은 통계표마다 의미 다름 (분류 차원). 필요 시 sub-카테고리는 default ("T1" 등) 사용.
KOSIS_MACRO_SPECS = {
    "kr_indpro": {
        "orgId": "101", "tblId": "DT_1F31501",
        "itmId": "T1", "objL1": "ALL",  # 광공업생산지수 (전 산업)
        "prdSe": "M",
    },
    "kr_retail": {
        "orgId": "101", "tblId": "DT_1KS1003",
        "itmId": "T1", "objL1": "ALL",  # 소매판매액지수 (총지수)
        "prdSe": "M",
    },
    "kr_capex": {
        "orgId": "101", "tblId": "DT_1F31503",
        "itmId": "T2", "objL1": "ALL",  # 설비투자지수
        "prdSe": "M",
    },
    "kr_permit": {
        "orgId": "116", "tblId": "DT_MLTM_5345",
        "itmId": "T1", "objL1": "ALL",  # 건축허가 면적 (전국 합계)
        "prdSe": "M",
    },
}


def fetch_kosis_macro_series(metric: str, months: int = 240) -> list[dict]:
    """단일 KOSIS 거시 지표를 최근 N개월 조회.

    Returns: list of {date: 'YYYY-MM-DD', value: float, metric: str}
    실패 시 빈 list. KOSIS API 키 미설정 시 RuntimeError.
    """
    if not KOSIS_KEY:
        raise RuntimeError("KOSIS_API_KEY 환경변수가 설정되지 않았습니다.")
    if metric not in KOSIS_MACRO_SPECS:
        raise ValueError(f"unknown KOSIS metric: {metric}")

    spec = KOSIS_MACRO_SPECS[metric]
    params = {
        "method": "getList",
        "apiKey": KOSIS_KEY,
        "format": "json",
        "jsonVD": "Y",
        "orgId": spec["orgId"],
        "tblId": spec["tblId"],
        "prdSe": spec["prdSe"],
        "newEstPrdCnt": str(months),
        "itmId": spec["itmId"],
        "objL1": spec["objL1"],
    }
    try:
        r = httpx.get(KOSIS_URL, params=params, timeout=30.0)
        r.raise_for_status()
        rows = r.json()
    except Exception as e:
        print(f"[kosis_macro] {metric} HTTP 실패: {e}")
        return []

    # 에러 응답: {"err": "...", "errMsg": "..."}
    if isinstance(rows, dict) and "err" in rows:
        print(f"[kosis_macro] {metric}: {rows.get('err')}: {rows.get('errMsg')}")
        return []
    if not isinstance(rows, list):
        print(f"[kosis_macro] {metric} 비정상 응답: {type(rows)}")
        return []

    out = []
    for row in rows:
        ym = row.get("PRD_DE", "")     # 예: '202403' (월별)
        if not ym or len(ym) != 6:
            continue
        try:
            v = float(row.get("DT", "0"))
        except (ValueError, TypeError):
            continue
        out.append({
            "date": f"{ym[:4]}-{ym[4:6]}-01",   # 월초 1일로 통일 (sector_macro_raw MS 인덱스와 정합)
            "value": v,
            "metric": metric,
        })
    # 같은 날짜 중복 (objL1=ALL 이 여러 행 반환 시) → 마지막 값 사용
    by_date = {row["date"]: row for row in out}
    return sorted(by_date.values(), key=lambda r: r["date"])


def fetch_kosis_macro_all(months: int = 240) -> dict:
    """4종 모두 fetch — sector_macro_kr aggregator 가 한 번에 호출.

    Returns: {metric_name: list_of_records} — 실패한 시리즈는 빈 list.
    """
    out = {}
    for metric in KOSIS_MACRO_SPECS.keys():
        try:
            rows = fetch_kosis_macro_series(metric, months=months)
            out[metric] = rows
            print(f"[kosis_macro] {metric}: {len(rows)}건")
        except Exception as e:
            print(f"[kosis_macro] {metric} 실패: {e}")
            out[metric] = []
    return out


if __name__ == "__main__":
    # 수동 검증: python -m collector.kosis_macro
    bundle = fetch_kosis_macro_all(months=24)
    for k, rows in bundle.items():
        if rows:
            print(f"  {k}: {rows[0]['date']} ~ {rows[-1]['date']} ({len(rows)}건), last={rows[-1]['value']}")
        else:
            print(f"  {k}: 빈 결과")
