"""국토교통부 실거래가 API — 매매·전월세 수집.

노트북 02(collector_functions)에서 검증한 fetch_all / parse_response / normalize_items 로직을
프로덕션 모듈로 이식. API 엔드포인트·파라미터 규약은 reference_datagokr_apis 메모리 참고.
"""
import os

import httpx
import xmltodict


MOLIT_TRADE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
MOLIT_RENT_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

API_KEY = os.getenv("DATA_GO_KR_KEY")

# MOLIT(국토부) XML 응답 규약: response/header, resultCode "000"
_MOLIT_SPEC = {"root": "response", "head_key": "header", "ok_codes": {"000"}}


def fetch_trades(sgg_cd: str, deal_ym: str) -> list[dict]:
    """시군구 코드(5자리) + YYYYMM → 해당 월 매매 실거래 전량 반환."""
    return _fetch_all(MOLIT_TRADE_URL, {
        "serviceKey": API_KEY,
        "LAWD_CD": sgg_cd,
        "DEAL_YMD": deal_ym,
    })


def fetch_rents(sgg_cd: str, deal_ym: str) -> list[dict]:
    """시군구 코드(5자리) + YYYYMM → 해당 월 전월세 실거래 전량 반환."""
    return _fetch_all(MOLIT_RENT_URL, {
        "serviceKey": API_KEY,
        "LAWD_CD": sgg_cd,
        "DEAL_YMD": deal_ym,
    })


def _fetch_all(url: str, base_params: dict, num_of_rows: int = 1000,
               max_pages: int = 100) -> list[dict]:
    """페이지네이션 전량 수집."""
    all_items: list[dict] = []
    total = 0
    for page in range(1, max_pages + 1):
        params = {**base_params, "pageNo": str(page), "numOfRows": str(num_of_rows)}
        result = _fetch_page(url, params)
        all_items.extend(result["items"])
        total = result["totalCount"]
        if page * num_of_rows >= total or not result["items"]:
            break
    else:
        # for-else: break 없이 루프 종료 = max_pages 초과 (무한루프 방지)
        raise RuntimeError(f"max_pages({max_pages}) 초과 — totalCount={total}")
    return all_items


def _fetch_page(url: str, params: dict, timeout: float = 30.0) -> dict:
    r = httpx.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    parsed = _parse_molit_response(r.text)
    return {
        "totalCount": parsed["totalCount"],
        "pageNo": parsed["pageNo"],
        "items": _normalize_items(parsed["items_raw"]),
    }


def _parse_molit_response(xml_text: str) -> dict:
    """국토부 XML → dict, resultCode 검증."""
    data = xmltodict.parse(xml_text)
    root = data[_MOLIT_SPEC["root"]]
    head = root[_MOLIT_SPEC["head_key"]]
    code = head["resultCode"]
    if code not in _MOLIT_SPEC["ok_codes"]:
        raise ValueError(f"[molit] API error resultCode={code}: {head.get('resultMsg', '?')}")
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
