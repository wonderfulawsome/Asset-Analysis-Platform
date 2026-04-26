"""행정안전부 법정동 인구통계 API — 인구·세대원수 수집.

3개 함수를 한 모듈에서 담당: 총인구(lv=3), 세대원수별(lv=3 admmCd), 매핑(lv=4).
NODATA(resultCode=3) 처리 포함 — 폐지된 동·미집계 월에서 루프 중단 방지.
"""
import os

import httpx
import xmltodict


MOIS_POP_URL = "https://apis.data.go.kr/1741000/stdgPpltnHhStus/selectStdgPpltnHhStus"
MOIS_HH_URL = "https://apis.data.go.kr/1741000/admmHsmbHh/selectAdmmHsmbHh"

API_KEY = os.getenv("DATA_GO_KR_KEY")

# MOIS(행안부) XML 응답 규약: Response/head, resultCode "0"
_MOIS_SPEC = {"root": "Response", "head_key": "head", "ok_codes": {"0"}}


def fetch_population(stdg_cd: str, ym: str) -> list[dict]:
    """법정동 코드(10자리) + YYYYMM → 인구·세대 데이터 (lv=3)."""
    return _fetch_all_mois(MOIS_POP_URL, {
        "serviceKey": API_KEY,
        "stdgCd": stdg_cd,
        "lv": "3",
        "regSeCd": "1",
        "srchFrYm": ym,
        "srchToYm": ym,
    })


def fetch_household_by_size(admm_cd: str, ym: str) -> list[dict]:
    """행정동 코드(10자리) + YYYYMM → 세대원수별 세대수 데이터 (lv=3)."""
    return _fetch_all_mois(MOIS_HH_URL, {
        "serviceKey": API_KEY,
        "admmCd": admm_cd,
        "lv": "3",
        "regSeCd": "1",
        "srchFrYm": ym,
        "srchToYm": ym,
    })


def fetch_mapping_pairs(stdg_cd: str, ym: str) -> list[dict]:
    """lv=4 호출로 (법정동, 행정동) 매핑 쌍 추출 — 노트북 03 fetch_mapping_for_dong 이식.

    lv=4 는 통반 단위로 수백 행을 돌려주는데, (stdgCd, admmCd) 조합을 dedupe 하면
    실제 매핑 쌍 수 개만 남는다. 별도 매핑 API 없이 역추출하는 트릭.
    """
    items = _fetch_all_mois(MOIS_POP_URL, {
        "serviceKey": API_KEY,
        "stdgCd": stdg_cd,
        "lv": "4",
        "regSeCd": "1",
        "srchFrYm": ym,
        "srchToYm": ym,
    })
    pairs: dict[tuple, dict] = {}
    for it in items:
        stdg = it.get("stdgCd")
        admm = it.get("admmCd")
        if not stdg or not admm:
            continue
        key = (stdg, admm)
        if key not in pairs:
            # API가 행정동명을 admmNm 이 아닌 dongNm 으로 내려줌 — 필드명 통일
            pairs[key] = {
                "stdgCd": stdg,
                "stdgNm": it.get("stdgNm"),
                "admmCd": admm,
                "admmNm": it.get("dongNm"),
                "ctpvNm": it.get("ctpvNm"),
                "sggNm":  it.get("sggNm"),
            }
    return list(pairs.values())


def fetch_all_sgg_codes(ym: str) -> list[str]:
    """전국 시군구 5자리 코드 목록 (MOLIT LAWD_CD 포맷) 동적 조회.

    lv=1로 전국→시도 17개를 얻고, 각 시도에 lv=2를 걸어 시군구 10자리 코드 수집 후
    앞 5자리만 추출(MOLIT LAWD_CD는 5자리). 17 + 17 = 34회 MOIS 호출.
    """
    # lv=1: 전국 루트 → 시도 목록
    ctpv_items = _fetch_all_mois(MOIS_POP_URL, {
        "serviceKey": API_KEY,
        "stdgCd": "1000000000",
        "lv": "1",
        "regSeCd": "1",
        "srchFrYm": ym,
        "srchToYm": ym,
    })
    sgg_codes: set[str] = set()
    for ctpv in ctpv_items:
        ctpv_cd = ctpv.get("stdgCd")
        if not ctpv_cd:
            continue
        # lv=2: 시도 → 시군구 목록
        sgg_items = _fetch_all_mois(MOIS_POP_URL, {
            "serviceKey": API_KEY,
            "stdgCd": ctpv_cd,
            "lv": "2",
            "regSeCd": "1",
            "srchFrYm": ym,
            "srchToYm": ym,
        })
        for sgg in sgg_items:
            stdg_10 = sgg.get("stdgCd")
            if stdg_10 and len(stdg_10) == 10:
                sgg_codes.add(stdg_10[:5])
    return sorted(sgg_codes)


def _fetch_all_mois(url: str, base_params: dict, num_of_rows: int = 1000,
                    max_pages: int = 100) -> list[dict]:
    """행안부 전량 페이지네이션. NODATA(code=3)는 빈 결과로 흡수."""
    all_items: list[dict] = []
    total = 0
    for page in range(1, max_pages + 1):
        params = {**base_params, "pageNo": str(page), "numOfRows": str(num_of_rows)}
        result = _fetch_page_mois(url, params)
        all_items.extend(result["items"])
        total = result["totalCount"]
        if page * num_of_rows >= total or not result["items"]:
            break
    else:
        raise RuntimeError(f"max_pages({max_pages}) 초과 — totalCount={total}")
    return all_items


def _fetch_page_mois(url: str, params: dict, timeout: float = 30.0) -> dict:
    r = httpx.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    parsed = _parse_mois_response(r.text)
    return {
        "totalCount": parsed["totalCount"],
        "pageNo": parsed["pageNo"],
        "items": _normalize_items(parsed["items_raw"]),
    }


def _parse_mois_response(xml_text: str) -> dict:
    """행안부 XML → dict, resultCode 검증. NODATA(code=3)는 빈 결과로 변환."""
    data = xmltodict.parse(xml_text)
    root = data[_MOIS_SPEC["root"]]
    head = root[_MOIS_SPEC["head_key"]]
    code = head["resultCode"]
    # NODATA: 폐지된 동·해당 월 미집계. 루프 전체 중단 방지를 위해 빈 결과로 흡수.
    if code == "3":
        return {"totalCount": 0, "pageNo": 1, "numOfRows": 0, "items_raw": None}
    if code not in _MOIS_SPEC["ok_codes"]:
        raise ValueError(f"[mois] API error resultCode={code}: {head.get('resultMsg', '?')}")
    body = root.get("body", root)
    return {
        "totalCount": int(body.get("totalCount", head.get("totalCount", 0))),
        "pageNo": int(body.get("pageNo", head.get("pageNo", 1))),
        "numOfRows": int(body.get("numOfRows", head.get("numOfRows", 0))),
        "items_raw": body.get("items"),
    }


def _normalize_items(items_raw) -> list[dict]:
    """xmltodict 단복수 함정 흡수 → 항상 list[dict]."""
    if not items_raw:
        return []
    item = items_raw.get("item", []) if isinstance(items_raw, dict) else items_raw
    if isinstance(item, dict):
        return [item]
    return item
