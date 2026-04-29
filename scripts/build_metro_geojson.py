"""수도권 (서울+경기+인천) 시군구 GeoJSON 합본 생성.

출처: https://github.com/southkorea/southkorea-maps (kostat 2013 코드 체계, 통계청)
변환: 통계청 코드 → 행안부 LAWD_CD (5자리). DB·MOLIT API 와 join 가능하도록.

특이 케이스:
- 인천 남구(23030) → 행안부 28177 미추홀구 (2018 변경)
- 경기 부천시: geojson 은 3구(원미·소사·오정) 분리 / 행안부는 41194 단일 (2016 일반구 폐지)
  → 3 폴리곤 모두 41194 로 매핑 (지도엔 3개 모양, 같은 데이터)

사용법: python scripts/build_metro_geojson.py
출력: frontend-realestate/public/geojson/metro-sgg.geojson
       static/realestate/geojson/metro-sgg.geojson  (Vite 빌드 산출물 동기화)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_URL = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2013/json/skorea_municipalities_geo_simple.json"
TMP_PATH = "/tmp/skorea_muni_source.json"

OUT_PATHS = [
    os.path.join(ROOT, "frontend-realestate/public/geojson/metro-sgg.geojson"),
    os.path.join(ROOT, "static/realestate/geojson/metro-sgg.geojson"),
]


# 서울 25 — name → 행안부 sgg_cd
SEOUL: dict[str, str] = {
    "종로구": "11110", "중구": "11140", "용산구": "11170", "성동구": "11200", "광진구": "11215",
    "동대문구": "11230", "중랑구": "11260", "성북구": "11290", "강북구": "11305", "도봉구": "11320",
    "노원구": "11350", "은평구": "11380", "서대문구": "11410", "마포구": "11440", "양천구": "11470",
    "강서구": "11500", "구로구": "11530", "금천구": "11545", "영등포구": "11560", "동작구": "11590",
    "관악구": "11620", "서초구": "11650", "강남구": "11680", "송파구": "11710", "강동구": "11740",
}

# 인천 10 — geojson 의 "남구" 는 2018년 미추홀구로 변경 → 28177
INCHEON: dict[str, str] = {
    "중구": "28110", "동구": "28140", "남구": "28177", "미추홀구": "28177",
    "연수구": "28185", "남동구": "28200", "부평구": "28237", "계양구": "28245", "서구": "28260",
    "강화군": "28710", "옹진군": "28720",
}

# 경기 — 단일 시군 + 일반구. 부천 3구는 41194 (2016 일반구 폐지) 단일 매핑.
GYEONGGI: dict[str, str] = {
    # 수원시 4구
    "수원시장안구": "41111", "수원시권선구": "41113", "수원시팔달구": "41115", "수원시영통구": "41117",
    # 성남시 3구
    "성남시수정구": "41131", "성남시중원구": "41133", "성남시분당구": "41135",
    "의정부시": "41150",
    # 안양시 2구
    "안양시만안구": "41171", "안양시동안구": "41173",
    # 부천시 (3구 모두 41194)
    "부천시": "41194", "부천시원미구": "41194", "부천시소사구": "41194", "부천시오정구": "41194",
    "광명시": "41210", "평택시": "41220", "동두천시": "41250",
    # 안산시 2구
    "안산시상록구": "41271", "안산시단원구": "41273",
    # 고양시 3구
    "고양시덕양구": "41281", "고양시일산동구": "41285", "고양시일산서구": "41287",
    "과천시": "41290", "구리시": "41310", "남양주시": "41360", "오산시": "41370",
    "시흥시": "41390", "군포시": "41410", "의왕시": "41430", "하남시": "41450",
    # 용인시 3구
    "용인시처인구": "41461", "용인시기흥구": "41463", "용인시수지구": "41465",
    "파주시": "41480", "이천시": "41500", "안성시": "41550", "김포시": "41570",
    "화성시": "41590", "광주시": "41610", "양주시": "41630", "포천시": "41650",
    "여주시": "41670",
    "연천군": "41800", "가평군": "41820", "양평군": "41830",
}


def map_feature(feat: dict) -> tuple[str | None, str]:
    """(sgg_cd, ctpv_nm) 반환. sgg_cd None 이면 수도권 외 (스킵)."""
    code = str(feat["properties"].get("code") or "")
    name = (feat["properties"].get("name") or "").strip()
    sido = code[:2]

    if sido == "11":
        return SEOUL.get(name), "서울특별시"
    if sido == "23":
        return INCHEON.get(name), "인천광역시"
    if sido == "31":
        return GYEONGGI.get(name), "경기도"
    return None, ""


def main() -> int:
    # 1) 다운로드 (캐시: 있으면 재사용)
    if not os.path.exists(TMP_PATH):
        print(f"[1/4] 다운로드: {SOURCE_URL}")
        urllib.request.urlretrieve(SOURCE_URL, TMP_PATH)
    src = json.load(open(TMP_PATH))
    print(f"[2/4] 원본: {len(src['features'])}개 features")

    # 2) 수도권 필터 + sgg_cd 부여
    out_features = []
    skipped: list[tuple[str, str]] = []
    for feat in src["features"]:
        sgg_cd, ctpv = map_feature(feat)
        name = feat["properties"].get("name", "?")
        code = feat["properties"].get("code", "?")
        if not sgg_cd:
            # 서울/인천/경기 인데 매핑 누락이면 경고
            sido = str(code)[:2]
            if sido in ("11", "23", "31"):
                skipped.append((code, name))
            continue
        # properties 정리 — sgg_cd, name, ctpv_nm 만 노출 (간결)
        new_props = {
            "sgg_cd": sgg_cd,
            "name": name,
            "ctpv_nm": ctpv,
            "src_code": code,
        }
        out_features.append({
            "type": "Feature",
            "properties": new_props,
            "geometry": feat["geometry"],
        })
    if skipped:
        print(f"  ⚠ 매핑 누락 {len(skipped)}개: {skipped[:5]}{'...' if len(skipped)>5 else ''}")
    print(f"[3/4] 수도권 필터 결과: {len(out_features)}개 (서울+인천+경기)")

    out_geo = {"type": "FeatureCollection", "features": out_features}

    # 3) 저장 (frontend public + static 둘 다)
    for path in OUT_PATHS:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out_geo, f, ensure_ascii=False, separators=(",", ":"))
        size_kb = os.path.getsize(path) / 1024
        print(f"[4/4] 저장: {path} ({size_kb:.1f} KB)")

    # 매핑 통계
    sgg_set = {f["properties"]["sgg_cd"] for f in out_features}
    print(f"\n  유니크 sgg_cd 수: {len(sgg_set)} (수도권 시군구 = 25서울 + 10인천 + 31경기 = 66)")
    # 폴리곤 수와 sgg_cd 수의 차이 = 일반구 개수 (4 부천 + 0 다른 합쳐진 곳)
    print(f"  폴리곤 features 수: {len(out_features)} (일반구 분리 케이스 포함)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
