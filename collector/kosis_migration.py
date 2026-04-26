"""통계청 KOSIS API — 시군구 인구이동 (월별 전입·전출) 수집.

통계표: DT_1B26001 (시군구/성/연령(5세)별 이동자수, orgId=101)
분류 차원:
  - C1 = 시군구 코드 5자리      → objL1
  - C2 = 성별 (0=계, 1=남, 2=여) → objL2
  - C3 = 연령 (000=계, 005=0-4 등) → objL3
항목 ITM_ID:
  - T10 = 총전입 (Total in-migrants)
  - T20 = 총전출 (Total out-migrants)
  - T25 = 순이동 (Net migration = 전입 - 전출)

KOSIS는 한 호출에 itmId 여러 개를 +로 묶을 수 있어 1회로 in/out/net 동시 가져옴.
한 호출당 최대 40,000셀 제한 → sgg_cd × months 조합이 작아야 함.
"""
import os

import httpx


KOSIS_KEY = os.getenv("KOSIS_API_KEY", "")
KOSIS_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"


def fetch_kosis_migration(sgg_cds: list[str], months: int = 12) -> list[dict]:
    """여러 시군구의 최근 N개월 인구이동 (성별·연령 합계) 조회.

    반환: list of {sgg_cd, stats_ym, in_count, out_count, net_flow}
    """
    if not KOSIS_KEY:
        raise RuntimeError("KOSIS_API_KEY 환경변수가 설정되지 않았습니다.")

    # 시군구 코드는 + 로 묶어 한 번에 호출 (40,000셀 제한 주의)
    obj_l1 = "+".join(sgg_cds)
    params = {
        "method": "getList",
        "apiKey": KOSIS_KEY,
        "format": "json",
        "jsonVD": "Y",
        "orgId": "101",
        "tblId": "DT_1B26001",
        "prdSe": "M",
        "newEstPrdCnt": str(months),
        "itmId": "T10+T20+T25",   # 전입·전출·순이동 한꺼번에
        "objL1": obj_l1,
        "objL2": "0",              # 성별 계
        "objL3": "000",            # 연령 계
    }
    r = httpx.get(KOSIS_URL, params=params, timeout=30.0)
    r.raise_for_status()
    rows = r.json()
    if isinstance(rows, dict) and "err" in rows:
        raise ValueError(f"[kosis] {rows.get('err')}: {rows.get('errMsg')}")

    by_key: dict[tuple, dict] = {}
    for row in rows:
        sgg = row.get("C1")
        ym = row.get("PRD_DE")
        itm = row.get("ITM_ID")
        try:
            v = int(row.get("DT", "0"))
        except (ValueError, TypeError):
            continue
        if not (sgg and ym and itm):
            continue
        rec = by_key.setdefault((sgg, ym), {
            "sgg_cd": sgg, "stats_ym": ym,
            "in_count": None, "out_count": None, "net_flow": None,
        })
        if itm == "T10":
            rec["in_count"] = v
        elif itm == "T20":
            rec["out_count"] = v
        elif itm == "T25":
            rec["net_flow"] = v

    # net_flow 미제공 시 fallback 계산
    out = []
    for d in by_key.values():
        if d["net_flow"] is None and d["in_count"] is not None and d["out_count"] is not None:
            d["net_flow"] = d["in_count"] - d["out_count"]
        out.append(d)
    return out
