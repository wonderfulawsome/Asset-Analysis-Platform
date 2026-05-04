"""한국은행 ECOS API — 기준금리·주담대 금리·주담대 잔액 + KR 국고채 / 회사채 수집.

ECOS REST 엔드포인트 형식:
  https://ecos.bok.or.kr/api/StatisticSearch/{API_KEY}/json/kr/
    {start}/{end}/{table_id}/{cycle}/{from_date}/{to_date}/{item_code}

cycle: D(일별), M(월별), Q(분기), A(연간).
응답: JSON — StatisticSearch.row 배열, 각 row 는 {TIME, DATA_VALUE, ITEM_NAME1, ...}.

지표별 통계표·항목 코드 (ECOS StatisticItemList 로 직접 확인한 값, 2026-04 기준):
  - 기준금리:           722Y001 / 0101000     (cycle=M)
  - 주담대 금리:        121Y006 / BECBLA0302  (cycle=M, 예금은행 신규취급 가중평균 - 주택담보대출)
  - 주담대 잔액:        151Y005 / 11110A0     (cycle=M, 예금은행 주택담보대출 잔액)

KR 시장금리 (817Y002 일별 시장금리 통계표 — 2026-04 ECOS 검증 기준):
  - 국고채(10년):       817Y002 / 010210000   (cycle=D)
  - 국고채(3년):        817Y002 / 010200000   (cycle=D)
  - 회사채(3년,AA-):    817Y002 / 010320000   (cycle=D)
  ⚠️ ECOS 통계표 코드는 변경될 수 있어 fetch 실패 시 fallback 작동.

위 코드는 ECOS 변경 시 깨질 수 있어 fetch_ecos_series 호출 시 SPECS 외부 override 가능.
"""
import os
from datetime import date, timedelta
from typing import Optional

import httpx

# .env 자동 로드 — standalone script (train_kr_hmm 등) 에서도 ECOS_API_KEY 인식하도록
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _ecos_key() -> str:
    """매번 환경변수에서 읽기 — 실행 중 키 추가/변경 대응."""
    return os.getenv("ECOS_API_KEY", "")


ECOS_KEY = _ecos_key()  # 모듈 import 시점 캐시 (대부분 사용처에서 충분)
ECOS_URL = "https://ecos.bok.or.kr/api/StatisticSearch"

# 지표별 spec — 변경 시 한 곳만 수정하면 모든 fetch 함수가 따라감.
# ⚠️ fetch_macro_rate_kr() 는 RATE_SPECS 만 순회하고, sector_macro_kr 은 SECTOR_MACRO_SPECS
# 만 사용 — SPECS 통합 dict 는 하위 호환 (fetch_ecos_series 가 'metric' 키로 lookup) 용.
# 두 dict 분리 이유: 매수 시그널(rate) 호출이 sector cycle 거시 12종까지 끌어 호출 폭증하지 않도록.
RATE_SPECS = {
    "base_rate":        {"table": "722Y001", "item": "0101000",    "cycle": "M"},
    "mortgage_rate":    {"table": "121Y006", "item": "BECBLA0302", "cycle": "M"},
    "mortgage_balance": {"table": "151Y005", "item": "11110A0",    "cycle": "M"},
    # KR 시장금리 — 일별
    "kr_10y_daily":     {"table": "817Y002", "item": "010210000",  "cycle": "D"},
    "kr_3y_daily":      {"table": "817Y002", "item": "010200000",  "cycle": "D"},
    "kr_corp_aa3y":     {"table": "817Y002", "item": "010320000",  "cycle": "D"},
}

# Sector cycle 거시경제 탭 전용 (collector/sector_macro_kr 만 사용).
# ⚠️ 통계표/항목 코드는 ECOS StatisticTableList + StatisticItemList sweep 으로 직접 검증 (2026-05-04).
# ECOS 시리즈 모두 월별/분기별 — 일별 sector_cycle 계산엔 사용 안 함.
SECTOR_MACRO_SPECS = {
    "kr_cpi":             {"table": "901Y009", "item": "0",       "cycle": "M"},  # 소비자물가지수 총지수 (1965~)
    "kr_gdp":             {"table": "200Y108", "item": "10601",   "cycle": "Q"},  # 국내총생산에 대한 지출(계절조정 실질, 1960Q1~)
    "kr_unemp_rate":      {"table": "901Y027", "item": "I61BC",   "cycle": "M"},  # 실업률 (1999.06~)
    "kr_m2":              {"table": "161Y007", "item": "BBGS00",  "cycle": "M"},  # M2(말잔, 계절조정계열, 2003~)
    "kr_indpro":          {"table": "901Y033", "item": "AB00",    "cycle": "M"},  # 광공업생산지수 (2000~)
    "kr_retail":          {"table": "901Y100", "item": "G0",      "cycle": "M"},  # 소매판매액지수 총지수 (1995~)
    "kr_capex":           {"table": "901Y066", "item": "I15B",    "cycle": "M"},  # 설비투자지수 (계절조정, 월별)
    "kr_permit":          {"table": "901Y105", "item": "ALL",     "cycle": "M"},  # 주택건설인허가실적 전국 (2007.01~)
}

# 통합 dict — fetch_ecos_series 가 metric 키로 spec 조회할 때 사용. 새 metric 추가 시 양쪽 모두 보임.
SPECS = {**RATE_SPECS, **SECTOR_MACRO_SPECS}


def fetch_ecos_series(metric: str, from_ym: str, to_ym: str) -> list[dict]:
    """단일 지표를 from_ym ~ to_ym(YYYYMM) 범위로 조회.

    반환: list of {date, value, cycle, metric}
    """
    key = _ecos_key()
    if not key:
        raise RuntimeError("ECOS_API_KEY 환경변수가 설정되지 않았습니다.")
    spec = SPECS[metric]

    # ECOS URL 은 REST path 형식 — query string 아님
    url = (
        f"{ECOS_URL}/{key}/json/kr/1/100000/"
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
    if cycle == "Q" and len(t) == 6 and t[4] == "Q":
        # 분기 데이터: '2024Q1' → 2024-01-01, '2024Q4' → 2024-10-01 (분기 첫달 1일)
        try:
            year = int(t[:4])
            quarter = int(t[5])
            if quarter < 1 or quarter > 4:
                return None
            month = (quarter - 1) * 3 + 1
            return f"{year:04d}-{month:02d}-01"
        except ValueError:
            return None
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

    # 3개 지표 각각 호출 후 date 기준 merge.
    # ⚠️ RATE_SPECS 만 순회 — 매수 시그널용으로 sector cycle 거시 12종까지 끌고 오면 호출 폭증.
    by_date: dict[str, dict] = {}
    for metric in RATE_SPECS.keys():
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


# ─────────────────────────────────────────────────────────────────────────────
# KR 국고채 / 회사채 helpers — collector/market_data_kr 와 valuation_signal_kr 가 사용
# ─────────────────────────────────────────────────────────────────────────────

def fetch_kr_treasury_yields(years: int = 5):
    """KR 10Y / 3Y 국고채 일별 yield 시계열 (단위: %).

    Returns: dict[str, pandas.Series] — 'kr_10y' / 'kr_3y' 키. 빈 dict 면 ECOS 실패.
    Series.index 는 DatetimeIndex.
    """
    import pandas as pd

    end = date.today()
    start = end - timedelta(days=years * 365 + 30)
    from_ymd = start.strftime("%Y%m%d")
    to_ymd = end.strftime("%Y%m%d")

    out = {}
    for metric, key in [("kr_10y_daily", "kr_10y"), ("kr_3y_daily", "kr_3y")]:
        try:
            rows = fetch_ecos_series(metric, from_ymd, to_ymd)
            if not rows:
                continue
            idx = pd.to_datetime([r["date"] for r in rows])
            vals = [r["value"] for r in rows]
            out[key] = pd.Series(vals, index=idx).sort_index()
        except Exception as e:
            print(f"[ECOS] {metric} 실패: {e}")
    return out


def fetch_kr_corp_spread(years: int = 5) -> Optional["pd.Series"]:
    """KR 회사채(AA- 3Y) - 국고채 3Y 스프레드 시계열 (% 차이).

    HY 등가는 아니지만 KR 신용 환경 proxy. 실패 시 None.
    """
    import pandas as pd

    end = date.today()
    start = end - timedelta(days=years * 365 + 30)
    from_ymd = start.strftime("%Y%m%d")
    to_ymd = end.strftime("%Y%m%d")
    try:
        corp_rows = fetch_ecos_series("kr_corp_aa3y", from_ymd, to_ymd)
        kr3y_rows = fetch_ecos_series("kr_3y_daily", from_ymd, to_ymd)
    except Exception as e:
        print(f"[ECOS] corp spread 실패: {e}")
        return None
    if not corp_rows or not kr3y_rows:
        return None

    corp = pd.Series([r["value"] for r in corp_rows],
                     index=pd.to_datetime([r["date"] for r in corp_rows])).sort_index()
    kr3y = pd.Series([r["value"] for r in kr3y_rows],
                     index=pd.to_datetime([r["date"] for r in kr3y_rows])).sort_index()
    return (corp - kr3y).dropna()
