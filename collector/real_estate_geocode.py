"""카카오 로컬 API — 주소 → 위경도 변환.

다른 수집기와 파일을 분리해 외부 의존을 격리.
카카오 장애 시 이 모듈만 비활성화하고 나머지 파이프라인은 유지 가능.
"""
import os

import httpx


KAKAO_REST_KEY = os.getenv("KAKAO_REST_KEY")
KAKAO_GEOCODE_URL = "https://dapi.kakao.com/v2/local/search/address.json"


def geocode(address: str) -> dict | None:
    """주소 문자열 → {lat, lng, road_address, jibun_address} 또는 None(결과 없음)."""
    if not KAKAO_REST_KEY:
        raise RuntimeError("KAKAO_REST_KEY 환경변수가 설정되지 않았습니다.")
    r = httpx.get(
        KAKAO_GEOCODE_URL,
        params={"query": address},
        headers={"Authorization": f"KakaoAK {KAKAO_REST_KEY}"},
        timeout=10.0,
    )
    r.raise_for_status()
    docs = r.json().get("documents", [])
    if not docs:
        return None
    d = docs[0]
    return {
        "lat": float(d["y"]),
        "lng": float(d["x"]),
        # road_address / address 는 dict 또는 None 으로 올 수 있어 방어적으로 꺼냄
        "road_address": (d["road_address"] or {}).get("address_name"),
        "jibun_address": (d["address"] or {}).get("address_name"),
    }


def batch_geocode(addresses: list[str]) -> list[dict | None]:
    """주소 리스트를 순차 지오코딩. 실패 항목은 None으로 채운다."""
    results: list[dict | None] = []
    for addr in addresses:
        try:
            results.append(geocode(addr))
        except Exception:
            results.append(None)
    return results
